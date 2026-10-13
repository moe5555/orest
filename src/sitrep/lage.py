"""The live values: each person's Risiko, Menschlichkeit and Berechenbarkeit now, and the alarm.

Fix 2 of knowledge/background/live_sitrep_latency.md ("A live values
stream"). The values used to change once a report was made. Here they are
worked out whenever they are asked for, from what the action recogniser read
in the last seconds (actions.py) and the lines rated as they were said
(utterances.py), so a blow or a threat shows within a second or two.

Decay. A piece of evidence counts in full when it is measured and half as
much every HALBWERTSZEIT seconds after, so a value falls back once the moment
has passed instead of staying up until the next report. The spec's "rule sets
the floor, decaying" (02_processing.md, Claude's notes). A person's value is
the strongest decayed evidence, rounded and clipped to 0-5, as a report's
peak is (actions.rate, report.Sitrep.bewertung). Loudness amplifies Risiko
evidence as it does there.

Berechenbarkeit. A person's live Berechenbarkeit is the mean of their
scores against the rehearsals (actions.py, predictability.py) over the last
SMOOTHING seconds. It does not decay: it describes how the person is moving
now, and a person no longer classified alone has none. It plays no part in
the alarm.

Scene. The scene in force (scenes.py) adds to what is measured and decides
what is shown:
- Podest, where the scene has the rule: each named person's Podest count
  (podest.Counter) is added to their Risiko, clipped to 0-5; a person with
  nothing measured is rated on it alone. It is a count over the scene, not
  evidence, and does not decay. It counts towards the alarm like any Risiko.
- Values set by hand (scenes.MANUAL) stand as set, until set again.
- Each person keeps only the values the scene shows them with. A Risiko not
  shown is not read by the alarm either.

Alarm. The alarm is raised by rule, not by the model: when a person's live
Risiko, or the decayed Risiko of a line whose speaker is unknown, reaches
ALARM. The thresholds of the spike triggers in live_sitrep_latency.md (fix
3): a line or an action rated Risiko >= 3. The alarm is what asks the model
for a recommendation (session.py); it is not itself one.

Nothing is kept here: the evidence stays with the recogniser and the Chronik,
which delete it when the run stops.
"""

import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

import numpy as np

from action import recognizer, sitrep_map

from . import actions, loudness, podest, report, scenes

# Seconds after which evidence counts half. live_sitrep_latency.md proposes
# 20-30 s and leaves the choice to the production ("Decay needs a
# dramaturgical decision").
HALBWERTSZEIT = 20.0

# Evidence older than this many half-lives counts for at most 5/16 and rounds
# to 0, so it is not read at all.
HORIZONT = 4

# Live Risiko at which the alarm is raised.
ALARM = 3

# Seconds of scores a live Berechenbarkeit is the mean of. At one reading a
# second, each over four seconds of movement, eight readings span twelve
# seconds of it: steady enough to read, recent enough to follow a change.
SMOOTHING = 8.0


@dataclass(frozen=True)
class Wert:
    """One live rating of a person: rounded, the value behind it (decayed
    evidence, or a mean score for Berechenbarkeit), what caused it and when
    that was measured."""

    wert: int
    staerke: float
    anlass: str = ""
    zeit: datetime | None = None


@dataclass(frozen=True)
class Alarm:
    """Whether the live values call for a recommendation, and why."""

    aktiv: bool
    wert: int = 0
    wer: str | None = None          # a name, or None for a line of unknown speaker
    anlass: str = ""


@dataclass(frozen=True)
class Stand:
    """The live values at one moment."""

    zeit: datetime
    personen: dict[str, dict[str, Wert]]
    alarm: Alarm

    def gerundet(self) -> tuple:
        """What an operator sees, whole values and their causes, for telling a
        change from the mere decay of a value."""
        return (tuple((name, tuple((wert.wert, wert.anlass) for wert in werte.values()))
                      for name, werte in sorted(self.personen.items())),
                self.alarm.aktiv, self.alarm.wert, self.alarm.wer)

    def beschreiben(self) -> str:
        """The live values as the model reads them."""
        if not self.personen:
            return "(niemand gemessen)"
        lines = []
        for name, werte in self.personen.items():
            parts = []
            for rating, wert in werte.items():
                part = f"{rating} {wert.wert}"
                if wert.wert and wert.anlass:
                    alter = int((self.zeit - wert.zeit).total_seconds()) if wert.zeit else 0
                    part += f" ({wert.anlass}, vor {alter} s)"
                parts.append(part)
            lines.append(f"- {name}: {', '.join(parts)}")
        return "\n".join(lines)


def abklingen(evidence: float, at: datetime, now: datetime,
              halbwertszeit: float = HALBWERTSZEIT) -> float:
    """Positive evidence as it counts now; calming evidence counts for nothing live."""
    if evidence <= 0:
        return 0.0
    age = max(0.0, (now - at).total_seconds())
    return evidence * 0.5 ** (age / halbwertszeit)


def _gerundet(staerke: float) -> int:
    return int(np.clip(np.floor(staerke + 0.5), 0, actions.RATING_MAX))


def stand(readings: list[actions.Evidence], names: dict[int, str],
          lines: list[report.Aeusserung], now: datetime,
          gain: actions.Gain | None = None,
          halbwertszeit: float = HALBWERTSZEIT) -> Stand:
    """The live values measured from the recent readings and lines, and the
    alarm they raise, with no scene applied (`measure`, `judge`)."""
    return judge(now, *measure(readings, names, lines, now, gain, halbwertszeit))


# Per person, their live values by rating.
Personen = dict[str, dict[str, Wert]]


def measure(readings: list[actions.Evidence], names: dict[int, str],
            lines: list[report.Aeusserung], now: datetime,
            gain: actions.Gain | None = None,
            halbwertszeit: float = HALBWERTSZEIT) -> tuple[Personen, tuple[float, str]]:
    """Each person's values from the recent readings and lines, and the
    strongest decayed Risiko of a line whose speaker is unknown, with its cause.

    `names` maps body track ids to people, as the recogniser holds them now.
    `gain` amplifies each reading's Risiko by how loud the room was over the
    seconds it covers.
    """
    risiko = sitrep_map.RATINGS.index("risiko")
    # Per person and rating: (decayed evidence, cause, when measured).
    best: dict[str, dict[str, tuple[float, str, datetime]]] = {}

    def offer(name: str, rating: str, evidence: float, cause: str, at: datetime):
        staerke = abklingen(evidence, at, now, halbwertszeit)
        held = best.setdefault(name, {}).get(rating)
        if held is None or staerke > held[0]:
            best[name][rating] = (staerke, cause, at)

    for record in readings:
        verstaerkung = (gain(record.at - timedelta(seconds=recognizer.WINDOW), record.at)
                        if gain else 1.0)
        for name in dict.fromkeys(names[member] for member in record.members
                                  if member in names):
            for column, rating in enumerate(sitrep_map.RATINGS):
                value = float(record.values[column])
                cause = record.causes[column]
                if column == risiko:
                    value = loudness.amplified(value, verstaerkung)
                    if verstaerkung > 1.0:
                        cause += f" · laut ×{verstaerkung:.1f}"
                offer(name, rating, value, cause, record.at)

    unklar: tuple[float, str] = (0.0, "")
    for line in lines:
        if line.risiko is None:
            continue
        cause = f"„{line.text}“: {line.begruendung}"
        if line.name is None or line.name == report.UNBEKANNT:
            staerke = abklingen(line.risiko_verstaerkt, line.ende, now, halbwertszeit)
            if staerke > unklar[0]:
                unklar = (staerke, cause)
            continue
        offer(line.name, "risiko", line.risiko_verstaerkt, cause, line.ende)
        offer(line.name, "menschlichkeit", line.menschlichkeit, cause, line.ende)

    personen: Personen = {}
    for name, ratings in best.items():
        personen[name] = {}
        for rating in report.GEMESSEN:
            staerke, cause, at = ratings.get(rating, (0.0, "", None))
            wert = _gerundet(staerke)
            personen[name][rating] = Wert(wert, round(staerke, 2), cause if wert else "",
                                          at if wert else None)
    # Every person scored has readings, and so Risiko and Menschlichkeit.
    for name, wert in predictabilities(readings, names, now).items():
        personen[name][report.BERECHENBARKEIT] = wert
    return personen, unklar


def with_podest(personen: Personen, counts: dict[str, tuple[int, datetime]]):
    """Add each person's Podest count to their Risiko; the cause carries the
    count, the time when it last changed."""
    for name, (count, changed) in counts.items():
        if not count:
            continue
        werte = personen.setdefault(name, {rating: Wert(0, 0.0) for rating in report.GEMESSEN})
        risiko = werte.get("risiko", Wert(0, 0.0))
        wert = int(np.clip(risiko.wert + count, 0, actions.RATING_MAX))
        cause = f"{podest.ANLASS} {count:+d}"
        if not wert:
            werte["risiko"] = Wert(0, round(risiko.staerke + count, 2))
            continue
        werte["risiko"] = Wert(wert, round(risiko.staerke + count, 2),
                               f"{risiko.anlass} · {cause}" if risiko.wert else cause,
                               max(risiko.zeit, changed) if risiko.zeit else changed)


# The cause shown with a value set by hand.
MANUELL = "vom Operator gesetzt"


def with_manual(personen: Personen, manual: dict[str, dict[str, tuple[int, datetime]]]):
    """Set the values the operator set by hand, as set."""
    for name, values in manual.items():
        werte = personen.setdefault(name, {})
        for value, (wert, at) in values.items():
            werte[value] = Wert(wert, float(wert), MANUELL if wert else "", at if wert else None)


def restricted(personen: Personen, values_of: Callable[[str], list[str]]) -> Personen:
    """Each person with only the values they are shown with, in that order.

    A value set by hand and not yet set reads 0; a measured value not
    measured stays absent.
    """
    return {name: {value: werte.get(value, Wert(0, 0.0)) for value in values_of(name)
                   if value in werte or value in scenes.MANUAL}
            for name, werte in personen.items()}


def judge(now: datetime, personen: Personen, unklar: tuple[float, str]) -> Stand:
    """The live values with the alarm they raise: the highest Risiko of a
    person, or of a line whose speaker is unknown."""
    kandidaten = [(werte["risiko"].wert, name, werte["risiko"].anlass)
                  for name, werte in personen.items() if "risiko" in werte]
    kandidaten.append((_gerundet(unklar[0]), None, unklar[1]))
    wert, wer, anlass = max(kandidaten, key=lambda kandidat: kandidat[0])
    alarm = Alarm(aktiv=wert >= ALARM, wert=wert, wer=wer, anlass=anlass if wert else "")
    return Stand(now, personen, alarm)


def predictabilities(readings: list[actions.Evidence], names: dict[int, str],
                     now: datetime, smoothing: float = SMOOTHING) -> dict[str, Wert]:
    """Each named person's live Berechenbarkeit, from their scores in the
    last `smoothing` seconds; people without one are left out."""
    since = now - timedelta(seconds=smoothing)
    recent: dict[str, list[actions.Evidence]] = {}
    for record in readings:
        if record.at < since or record.berechenbarkeit is None:
            continue
        for name in dict.fromkeys(names[member] for member in record.members
                                  if member in names):
            recent.setdefault(name, []).append(record)
    return {name: Wert(actions.mean_predictability(own),
                       round(float(np.mean([record.berechenbarkeit for record in own])), 2),
                       zeit=max(record.at for record in own))
            for name, own in recent.items()}


class Lage:
    """The live values of a run, worked out from its sources when asked for.

    `readings` gives the action readings after a moment and the names the
    bodies carry (actions.ActionRatings.since); `lines` the rated lines ended
    after a moment (chronik.Chronik.zeilen_seit); `gain` the loudness gain
    over a stretch of time; `podest` each body in view and whether it stands
    on the Podest now (actions.ActionRatings.podest_stance); `scene` the
    scene in force, without which none applies.
    """

    def __init__(self, readings: Callable | None, lines: Callable[[datetime], list],
                 gain: actions.Gain | None = None, halbwertszeit: float = HALBWERTSZEIT,
                 podest: Callable[[], dict[int, bool]] | None = None,
                 scene: scenes.Current | None = None):
        self._readings = readings
        self._lines = lines
        self._gain = gain
        self.halbwertszeit = halbwertszeit
        self._podest = podest
        self._scene = scene
        # The Podest count of the scene in force, and the selection it counts
        # for (scenes.Current.generation). The values are asked for from
        # several threads.
        self._counter = None
        self._counted: int | None = None
        self._lock = threading.Lock()

    def jetzt(self, now: datetime | None = None) -> Stand:
        now = now or datetime.now()
        since = now - timedelta(seconds=HORIZONT * self.halbwertszeit)
        readings, names = self._readings(since) if self._readings else ([], {})
        personen, unklar = measure(readings, names, self._lines(since), now, self._gain,
                                   self.halbwertszeit)
        if self._scene is None:
            return judge(now, personen, unklar)

        scene, generation = self._scene.scene, self._scene.generation
        if scene.podest is not None and self._podest is not None:
            # Only named bodies are rated, on the Podest as anywhere else.
            stance = {names[track]: up for track, up in self._podest().items() if track in names}
            measured = {name: werte["risiko"].wert for name, werte in personen.items()}
            with self._lock:
                if self._counted != generation:
                    self._counter = podest.Counter(scene.podest.step, scene.podest.floor)
                    self._counted = generation
                counts = self._counter.update(stance, measured, now)
            with_podest(personen, counts)
        with_manual(personen, self._scene.manual())
        return judge(now, restricted(personen, scene.values_of), unklar)
