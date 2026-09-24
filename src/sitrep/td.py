"""Announcing the live SITREP and the presence roster to TouchDesigner over OSC.

The control half of the live interface in knowledge/components/03_render.md:
pixels travel as an NDI source (feed.py), and OSC carries the text. Addresses
are namespaced beside the search results `smartsearch/td.py` sends, so one OSC
In DAT receives both and routes on the prefix.

A report is framed by a begin and an end, with one message per table row
between them:

    /orest/sitrep/begin     <id> <nummer> <beginn> <ende> <dauer_s> <bilder>
                            <ton_s> <latenz_s> <personen> <ereignisse>
    /orest/sitrep/lage      <id> <lage> <prognose> <empfehlung> <vertrauen>
    /orest/sitrep/gesagt    <id> <gesagt>
    /orest/sitrep/person    <id> <zeile> <kennung> <merkmale> <taetigkeit>
                            <verantwortungsvoll> <menschlich> <gefahr> <kollaborativ>
    /orest/sitrep/ereignis  <id> <zeile> <text>
    /orest/sitrep/end       <id>

`begin` carries the row counts so TouchDesigner can size its tables before the
rows arrive, as `/orest/results/begin` does for a search. The report id tells
one report's rows from the previous report's.

The roster is a second, faster stream. It is not folded into the report
because the two move at very different rates: a report arrives once a window,
while the tracker follows the room twice a second, and carrying the roster on
the report would make "who is on stage now" lag by up to a whole window —
exactly what presence.py exists to avoid.

    /orest/presence/begin   <tick> <zeit> <anwesend>
    /orest/presence/person  <tick> <zeile> <label> <name> <vermutet>
                            <aehnlichkeit> <sichtungen> <seit> <dauer_s>
    /orest/presence/end     <tick>

`tick` counts upward rather than being a random id: a periodic stream over UDP
can arrive out of order, and a receiver keeps the highest tick it has seen
complete.
"""

import threading
import time
import uuid
from datetime import datetime

from osc import Message, Sender  # noqa: F401  (Sender is re-exported)

from . import presence, report

SITREP_BEGIN = "/orest/sitrep/begin"
SITREP_LAGE = "/orest/sitrep/lage"
SITREP_GESAGT = "/orest/sitrep/gesagt"
SITREP_PERSON = "/orest/sitrep/person"
SITREP_EREIGNIS = "/orest/sitrep/ereignis"
SITREP_END = "/orest/sitrep/end"

PRESENCE_BEGIN = "/orest/presence/begin"
PRESENCE_PERSON = "/orest/presence/person"
PRESENCE_END = "/orest/presence/end"

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
                        zeit.dauer_s, quelle.bilder, quelle.ton_s, document.latenz_s,
                        len(bericht.personen), len(bericht.ereignisse)]),
        (SITREP_LAGE, [sitrep_id, bericht.lage, bericht.prognose,
                       bericht.empfehlung, bericht.vertrauen]),
        # Sent even when nothing was said, so the table keeps its shape.
        (SITREP_GESAGT, [sitrep_id, document.gesagt]),
    ]

    for zeile, person in enumerate(bericht.personen, start=1):
        # Ratings are read off BEWERTUNGEN rather than named here, so renaming
        # a category cannot leave TouchDesigner reading a column that no longer
        # exists -- the reason report.py derives them in the first place.
        ratings = [getattr(person, name) for name in report.BEWERTUNGEN]
        built.append((SITREP_PERSON, [sitrep_id, zeile, person.kennung,
                                      person.merkmale, person.taetigkeit, *ratings]))

    for zeile, ereignis in enumerate(bericht.ereignisse, start=1):
        built.append((SITREP_EREIGNIS, [sitrep_id, zeile, ereignis]))

    built.append((SITREP_END, [sitrep_id]))
    return built


def roster_messages(roster: list[presence.Presence], tick: int,
                    at: datetime) -> list[Message]:
    """One reading of who is in the room."""
    built = [(PRESENCE_BEGIN, [tick, _clock(at), len(roster)])]
    for zeile, person in enumerate(roster, start=1):
        # A guessed name is not a recognition, and TouchDesigner should be able
        # to set the two differently: `name` is empty unless the cast matched.
        built.append((PRESENCE_PERSON, [
            tick, zeile, person.label, person.name or "", int(not person.known),
            person.similarity, person.sightings, _clock(person.first_seen),
            round(person.seconds, 1),
        ]))
    built.append((PRESENCE_END, [tick]))
    return built


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
