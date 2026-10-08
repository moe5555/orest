"""The live values: each person's Risiko, Menschlichkeit and Vorhersehbarkeit now, and the alarm.

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

Vorhersehbarkeit. A person's live Vorhersehbarkeit is the mean of their
scores against the rehearsals (actions.py, predictability.py) over the last
SMOOTHING seconds. It does not decay: it describes how the person is moving
now, and a person no longer classified alone has none. It plays no part in
the alarm.

Alarm. The alarm is raised by rule, not by the model: when a person's live
Risiko, or the decayed Risiko of a line whose speaker is unknown, reaches
ALARM. The thresholds of the spike triggers in live_sitrep_latency.md (fix
3): a line or an action rated Risiko >= 3. The alarm is what asks the model
for a recommendation (session.py); it is not itself one.

Nothing is kept here: the evidence stays with the recogniser and the Chronik,
which delete it when the run stops.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

import numpy as np

from action import recognizer, sitrep_map

from . import actions, loudness, report

# Seconds after which evidence counts half. live_sitrep_latency.md proposes
# 20-30 s and leaves the choice to the production ("Decay needs a
# dramaturgical decision").
HALBWERTSZEIT = 20.0

# Evidence older than this many half-lives counts for at most 5/16 and rounds
# to 0, so it is not read at all.
HORIZONT = 4

# Live Risiko at which the alarm is raised.
ALARM = 3

# Seconds of scores a live Vorhersehbarkeit is the mean of. At one reading a
# second, each over four seconds of movement, eight readings span twelve
# seconds of it: steady enough to read, recent enough to follow a change.
SMOOTHING = 8.0


@dataclass(frozen=True)
class Wert:
    """One live rating of a person: rounded, the value behind it (decayed
    evidence, or a mean score for Vorhersehbarkeit), what caused it and when
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
    """The live values from the recent readings and lines.

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

    personen = {}
    for name, ratings in best.items():
        personen[name] = {}
        for rating in report.GEMESSEN:
            staerke, cause, at = ratings.get(rating, (0.0, "", None))
            wert = _gerundet(staerke)
            personen[name][rating] = Wert(wert, round(staerke, 2), cause if wert else "",
                                          at if wert else None)
    # Every person scored has readings, and so Risiko and Menschlichkeit.
    for name, wert in predictabilities(readings, names, now).items():
        personen[name][report.VORHERSEHBARKEIT] = wert

    kandidaten = [(werte["risiko"].wert, name, werte["risiko"].anlass)
                  for name, werte in personen.items()]
    kandidaten.append((_gerundet(unklar[0]), None, unklar[1]))
    wert, wer, anlass = max(kandidaten, key=lambda kandidat: kandidat[0])
    alarm = Alarm(aktiv=wert >= ALARM, wert=wert, wer=wer, anlass=anlass if wert else "")
    return Stand(now, personen, alarm)


def predictabilities(readings: list[actions.Evidence], names: dict[int, str],
                     now: datetime, smoothing: float = SMOOTHING) -> dict[str, Wert]:
    """Each named person's live Vorhersehbarkeit, from their scores in the
    last `smoothing` seconds; people without one are left out."""
    since = now - timedelta(seconds=smoothing)
    recent: dict[str, list[actions.Evidence]] = {}
    for record in readings:
        if record.at < since or record.vorhersehbarkeit is None:
            continue
        for name in dict.fromkeys(names[member] for member in record.members
                                  if member in names):
            recent.setdefault(name, []).append(record)
    return {name: Wert(actions.mean_predictability(own),
                       round(float(np.mean([record.vorhersehbarkeit for record in own])), 2),
                       zeit=max(record.at for record in own))
            for name, own in recent.items()}


class Lage:
    """The live values of a run, worked out from its sources when asked for.

    `readings` gives the action readings after a moment and the names the
    bodies carry (actions.ActionRatings.since); `lines` the rated lines ended
    after a moment (chronik.Chronik.zeilen_seit); `gain` the loudness gain
    over a stretch of time.
    """

    def __init__(self, readings: Callable | None, lines: Callable[[datetime], list],
                 gain: actions.Gain | None = None, halbwertszeit: float = HALBWERTSZEIT):
        self._readings = readings
        self._lines = lines
        self._gain = gain
        self.halbwertszeit = halbwertszeit

    def jetzt(self, now: datetime | None = None) -> Stand:
        now = now or datetime.now()
        since = now - timedelta(seconds=HORIZONT * self.halbwertszeit)
        readings, names = self._readings(since) if self._readings else ([], {})
        return stand(readings, names, self._lines(since), now, self._gain, self.halbwertszeit)
