"""Announcing the live SITREP and the presence roster to TouchDesigner over OSC.

The control half of the live interface in knowledge/components/03_render.md:
pixels travel as an NDI source (feed.py), and OSC carries the text. Addresses
are namespaced beside the search results `smartsearch/td.py` sends, so one OSC
In DAT receives both and routes on the prefix.

A report, made when the operator asks for one, is framed by a begin and an
end, with one message per table row between them:

    /apollon/sitrep/begin         <id> <nummer> <beginn> <ende> <dauer_s> <bilder>
                                <abschnitte> <latenz_s> <personen> <prognosen>
    /apollon/sitrep/verlauf       <id> <verlauf>
    /apollon/sitrep/beschreibung  <id> <beschreibung>
    /apollon/sitrep/gesagt        <id> <gesagt>
    /apollon/sitrep/person        <id> <zeile> <name> <vermutet> <beschreibung>
                                <risiko> <menschlichkeit> <vorhersehbarkeit>
    /apollon/sitrep/szene         <id> <relevanz> <eskalation> <gefahr>
    /apollon/sitrep/prognose      <id> <rang> <wahrscheinlichkeit> <verlauf>
    /apollon/sitrep/empfehlung    <id> <einschreiten> <massnahme>
    /apollon/sitrep/end           <id>

A person's ratings follow report.BEWERTUNGEN. `risiko` and `menschlichkeit`
are 0-5 and -1 when nothing of the person was measured. `vorhersehbarkeit` is
-5 to +5, where -1 is a value, and travels as an empty string when it was not
measured (no reference built, or the person never classified alone).

`begin` carries the row counts so TouchDesigner can size its tables before the
rows arrive, as `/apollon/results/begin` does for a search. The report id tells
one report's rows from the previous report's. Forecasts arrive most likely
first, `rang` 1 being the most likely. `vermutet` is 1 for Unbekannt and 0
for a name, since every name is a recognised cast member. `einschreiten` is 0
or 1, and 1 when the scene's `eskalation` or `gefahr` exceeds
report.SCHWELLE, and `massnahme` is empty otherwise.

The roster is a second, faster stream. It is not folded into the report
because the two move at very different rates: a report arrives when asked for,
while the tracker follows the room twice a second, and carrying the roster on
the report would make "who is on stage now" lag by up to a whole window —
exactly what presence.py exists to avoid.

    /apollon/presence/begin   <tick> <zeit> <anwesend>
    /apollon/presence/person  <tick> <zeile> <label> <name> <vermutet>
                            <aehnlichkeit> <sichtungen> <seit> <dauer_s>
    /apollon/presence/end     <tick>

`tick` counts upward rather than being a random id: a periodic stream over UDP
can arrive out of order, and a receiver keeps the highest tick it has seen
complete.

The fast lane (session.py) sends as things happen. The live values, whenever
one changes as an operator would see it, framed like the roster; `alarm` is 0
or 1, `alarm_wer` empty for a line of unknown speaker:

    /apollon/live/begin       <tick> <zeit> <personen> <alarm> <alarm_wert>
                            <alarm_wer> <alarm_anlass>
    /apollon/live/person      <tick> <zeile> <name> <risiko> <menschlichkeit>
                            <anlass_risiko> <anlass_menschlichkeit>
                            <vorhersehbarkeit>
    /apollon/live/end         <tick>

Each line as soon as it is transcribed, with `bewertet` 0, and again once it
is rated, with `bewertet` 1; `beginn` and `text` tell which line a rating
belongs to. `name` is empty where the speaker is not known, `risiko` and
`menschlichkeit` are the line's evidence, -5 to +5, and 0 until rated:

    /apollon/live/zeile       <beginn> <ende> <name> <text> <lautstaerke>
                            <risiko> <menschlichkeit> <bewertet>

Each recommendation, and each stretch the Chronik summarised; `eskalation`
and `gefahr` are -1 for a stretch the model could not summarise:

    /apollon/live/empfehlung  <nummer> <zeit> <einschreiten> <eskalation> <gefahr>
                            <lage> <massnahme> <anlass> <latenz_s>
    /apollon/chronik/abschnitt <beginn> <ende> <eskalation> <gefahr> <tendenz>
                            <zusammenfassung>
"""

import threading
import time
import uuid
from datetime import datetime

from osc import Message, Sender  # noqa: F401  (Sender is re-exported)

from . import presence, report

SITREP_BEGIN = "/apollon/sitrep/begin"
SITREP_VERLAUF = "/apollon/sitrep/verlauf"
SITREP_BESCHREIBUNG = "/apollon/sitrep/beschreibung"
SITREP_GESAGT = "/apollon/sitrep/gesagt"
SITREP_PERSON = "/apollon/sitrep/person"
SITREP_SZENE = "/apollon/sitrep/szene"
SITREP_PROGNOSE = "/apollon/sitrep/prognose"
SITREP_EMPFEHLUNG = "/apollon/sitrep/empfehlung"
SITREP_END = "/apollon/sitrep/end"

PRESENCE_BEGIN = "/apollon/presence/begin"
PRESENCE_PERSON = "/apollon/presence/person"
PRESENCE_END = "/apollon/presence/end"

LIVE_BEGIN = "/apollon/live/begin"
LIVE_PERSON = "/apollon/live/person"
LIVE_END = "/apollon/live/end"
LIVE_ZEILE = "/apollon/live/zeile"
LIVE_EMPFEHLUNG = "/apollon/live/empfehlung"
CHRONIK_ABSCHNITT = "/apollon/chronik/abschnitt"

# A person's rating that was not measured: -1 on the 0-5 scales, an empty
# string on Vorhersehbarkeit's -5 to +5.
NICHT_GEMESSEN = -1
NOT_MEASURED_SIGNED = ""

# Seconds between roster messages. Matches the tracker's own pass rate: sending
# faster would repeat a roster that has not changed.
ROSTER_INTERVAL = presence.INTERVAL


def new_sitrep_id() -> str:
    return uuid.uuid4().hex[:8]


def _clock(moment: datetime) -> str:
    """A time as text. The number that arithmetic needs travels separately."""
    return moment.isoformat(timespec="seconds")


def messages(document: report.Sitrep, nummer: int,
             sitrep_id: str | None = None) -> list[Message]:
    """One report as the rows TouchDesigner will lay out, in order."""
    sitrep_id = sitrep_id or new_sitrep_id()
    bericht = document.bericht
    zeit, quelle = document.zeitfenster, document.quelle

    built = [
        (SITREP_BEGIN, [sitrep_id, nummer, _clock(zeit.beginn), _clock(zeit.ende),
                        zeit.dauer_s, quelle.bilder, quelle.abschnitte, document.latenz_s,
                        len(bericht.personen), len(bericht.prognose)]),
        (SITREP_VERLAUF, [sitrep_id, bericht.verlauf]),
        (SITREP_BESCHREIBUNG, [sitrep_id, bericht.beschreibung]),
        # Sent even when nothing was said, so the table keeps its shape.
        (SITREP_GESAGT, [sitrep_id, document.gesagt]),
    ]

    for zeile, person in enumerate(bericht.personen, start=1):
        # Ratings are read off BEWERTUNGEN rather than named here, so renaming
        # a category cannot leave TouchDesigner reading a column that no longer
        # exists -- the reason report.py derives them in the first place. OSC
        # has no null, so a rating that was not measured travels as a marker.
        ratings = [value if value is not None
                   else NOT_MEASURED_SIGNED if rating == report.VORHERSEHBARKEIT
                   else NICHT_GEMESSEN
                   for rating, value in document.bewertungen(person).items()]
        built.append((SITREP_PERSON, [sitrep_id, zeile, person.name,
                                      int(person.name == report.UNBEKANNT),
                                      person.beschreibung, *ratings]))

    szene = bericht.szene
    built.append((SITREP_SZENE, [sitrep_id, szene.relevanz, szene.eskalation,
                                 szene.gefahr]))

    for rang, verlauf in enumerate(bericht.prognose, start=1):
        built.append((SITREP_PROGNOSE, [sitrep_id, rang, verlauf.wahrscheinlichkeit,
                                        verlauf.verlauf]))

    built.append((SITREP_EMPFEHLUNG, [sitrep_id, int(bericht.einschreiten),
                                      bericht.empfehlung]))
    built.append((SITREP_END, [sitrep_id]))
    return built


def roster_messages(roster: list[presence.Presence], tick: int,
                    at: datetime) -> list[Message]:
    """One reading of who is in the room: the cast members recognised.

    `name` equals `label` and `vermutet` is 0; both columns are kept so the
    tables in TouchDesigner keep their layout.
    """
    roster = [person for person in roster if person.known]
    built = [(PRESENCE_BEGIN, [tick, _clock(at), len(roster)])]
    for zeile, person in enumerate(roster, start=1):
        built.append((PRESENCE_PERSON, [
            tick, zeile, person.label, person.name or "", int(not person.known),
            person.similarity, person.sightings, _clock(person.first_seen),
            round(person.seconds, 1),
        ]))
    built.append((PRESENCE_END, [tick]))
    return built


def werte_messages(stand, tick: int) -> list[Message]:
    """The live values at one moment (lage.Stand)."""
    alarm = stand.alarm
    built = [(LIVE_BEGIN, [tick, _clock(stand.zeit), len(stand.personen), int(alarm.aktiv),
                           alarm.wert, alarm.wer or "", alarm.anlass])]
    for zeile, (name, werte) in enumerate(stand.personen.items(), start=1):
        vorhersehbarkeit = werte.get(report.VORHERSEHBARKEIT)
        built.append((LIVE_PERSON, [tick, zeile, name,
                                    *(werte[rating].wert for rating in report.GEMESSEN),
                                    *(werte[rating].anlass for rating in report.GEMESSEN),
                                    NOT_MEASURED_SIGNED if vorhersehbarkeit is None
                                    else vorhersehbarkeit.wert]))
    built.append((LIVE_END, [tick]))
    return built


def zeilen_messages(lines: list[report.Aeusserung], bewertet: bool = True) -> list[Message]:
    """Lines as they were transcribed or rated, one message each."""
    return [(LIVE_ZEILE, [_clock(line.beginn), _clock(line.ende), line.name or "", line.text,
                          line.lautstaerke, line.risiko or 0, line.menschlichkeit or 0,
                          int(bewertet)])
            for line in lines]


def abschnitt_messages(abschnitt) -> list[Message]:
    """One stretch the Chronik summarised (chronik.Abschnitt)."""
    summary = abschnitt.zusammenfassung
    if summary is None:
        return [(CHRONIK_ABSCHNITT, [_clock(abschnitt.beginn), _clock(abschnitt.ende),
                                     NICHT_GEMESSEN, NICHT_GEMESSEN, "", ""])]
    return [(CHRONIK_ABSCHNITT, [_clock(abschnitt.beginn), _clock(abschnitt.ende),
                                 summary.szene.eskalation, summary.szene.gefahr,
                                 summary.tendenz, summary.zusammenfassung])]


def empfehlung_messages(empfehlung: report.Empfehlung, nummer: int) -> list[Message]:
    urteil = empfehlung.urteil
    return [(LIVE_EMPFEHLUNG, [nummer, _clock(empfehlung.zeit), int(urteil.einschreiten),
                               urteil.szene.eskalation, urteil.szene.gefahr, urteil.lage,
                               urteil.empfehlung, empfehlung.anlass, empfehlung.latenz_s])]


class RosterStream:
    """Sends the tracker's roster to TouchDesigner at a fixed rate.

    Runs on its own thread, like the tracker it reads and the publisher beside
    it. Reads the tracker and never closes it.
    """

    def __init__(self, sender: Sender, tracker: presence.PresenceTracker, *,
                 interval: float = ROSTER_INTERVAL):
        self._sender = sender
        self._tracker = tracker
        self._interval = interval
        self._stop = threading.Event()
        self._thread = None
        self.ticks = 0

    def start(self) -> "RosterStream":
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        return self

    def _loop(self):
        while not self._stop.is_set():
            started = time.monotonic()
            self.publish()
            self._stop.wait(max(0.0, self._interval - (time.monotonic() - started)))

    def publish(self):
        """Send one reading. Public, so a caller can step the stream by hand."""
        self.ticks += 1
        self._sender.send_all(
            roster_messages(self._tracker.roster(), self.ticks, datetime.now()))

    def close(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5.0)

    def __enter__(self) -> "RosterStream":
        return self.start()

    def __exit__(self, *exception):
        self.close()
