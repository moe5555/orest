"""One live run: the camera and microphone, and everything reading them.

DirectShow refuses a second process the camera (devices.open_video), so
everything that watches the room during a rehearsal has to read one open
stream. A session opens it once and hands it to the presence tracker that
follows faces, to the action recogniser that rates what bodies do, to the
stills kept for the model, and to the publisher that sends the picture to
TouchDesigner. None of them opens or closes it.

A run has three speeds (knowledge/background/live_sitrep_latency.md, and the
architecture in knowledge/background/live_distillation.md):

- The fast lane, within seconds and without waiting for anything: each line
  as its utterance ends (utterances.py), and each person's live Risiko and
  Menschlichkeit (lage.py), with the alarm raised by rule.
- The Chronik, every `window` seconds in the background: a summary of the
  stretch just passed and of the scene so far (chronik.py).
- Reports, only when the operator asks (`bericht`), and recommendations
  (`empfehlung`), when the alarm is raised or the operator asks. Both read
  the Chronik, so they cover the last minutes, not only the last seconds.

`events()` runs the live part and yields what each of them produces, in the
order it is ready. The session is also the shape the localhost interface of
knowledge/components/02_processing.md needs: one object to start and one to
stop, holding everything a run consists of.

Nothing is written to disk. The real-time path retains nothing
(changelog.md, 2026-09-10), and neither NDI nor OSC is a file.
"""

import pathlib
import queue
import sys
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta

from face import gallery
from pydantic import BaseModel

from . import (actions, annotate, capture, chronik, cli, devices, feed, lage, llm, loudness,
               ndi_audio, presence, report, speakers, speech, td, transcribe, utterances)
from . import appearance, predictability


def resolve_sources(args) -> tuple[devices.VideoDevice, devices.AudioDevice | ndi_audio.NdiAudio]:
    """The camera, and the microphone or NDI source to take sound from."""
    video = devices.resolve_video_device(args.video)
    if args.audio_ndi:
        return video, ndi_audio.NdiAudio(args.audio_ndi)
    return video, devices.resolve_audio_device(args.audio, args.audio_api)


class Options(BaseModel):
    """Everything a run is configured with, from a command line or a request.

    A model rather than keyword arguments because the localhost interface will
    receive exactly this as its request body, and pydantic is already how the
    package describes a document (report.Sitrep).
    """

    # Seconds between stills kept for the model, and the length of each
    # stretch the Chronik summarises.
    interval: float = cli.INTERVAL
    window: float = cli.WINDOW
    width: int | None = None
    height: int | None = None
    model: str = report.MODEL

    # Language of the speech in the room, as a Whisper code. The production
    # speaks German; test footage in another language needs its own code.
    language: str = transcribe.LANGUAGE

    # Enrolment folder. Enrolled people are recognised by name; everyone else
    # is "Körper <id>" in the picture and Unbekannt in the report.
    cast: pathlib.Path | None = None

    # Rate Risiko and Menschlichkeit from the action recogniser. Off, they are
    # not measured and every person's are None.
    actions: bool = True

    # Publish the camera to TouchDesigner under this NDI source name.
    ndi: str | None = None
    ndi_fps: float = feed.FPS

    # Announce each report, the live values, lines and Chronik, and the
    # roster when a tracker is running, over OSC.
    send_td: bool = False

    # Ask the model for a recommendation whenever the live values raise the
    # alarm. Off, a recommendation is made only when the operator asks.
    auto_empfehlung: bool = True

    @classmethod
    def from_args(cls, args) -> "Options":
        """Read the options a parser built by cli.py produced."""
        return cls(
            interval=args.interval,
            window=args.window,
            width=args.width,
            height=args.height,
            model=args.model,
            language=args.language,
            cast=args.cast,
            actions=not args.no_actions,
            ndi=args.ndi_name if args.send_ndi else None,
            ndi_fps=args.ndi_fps,
            send_td=args.send_td,
            auto_empfehlung=not getattr(args, "no_auto_empfehlung", False),
        )


# What a run produces, as `events()` yields it.

@dataclass(frozen=True)
class Zeilen:
    """Lines just said: first as transcribed, then again once rated."""
    zeilen: list[report.Aeusserung]
    bewertet: bool = True


@dataclass(frozen=True)
class Werte:
    """The live values changed as an operator sees them, or the alarm did."""
    stand: lage.Stand


@dataclass(frozen=True)
class Ton:
    """The sound source went silent, or came back.

    `stumm` after STUMM seconds below loudness.STILL, or with no sound
    arriving at all: most likely a source nothing feeds, which would
    otherwise leave the run without a single line and no sign why.
    """
    stumm: bool
    quelle: str


@dataclass(frozen=True)
class NeuerAbschnitt:
    """A stretch of the scene was summarised into the Chronik."""
    abschnitt: chronik.Abschnitt


@dataclass(frozen=True)
class Angefordert:
    """A report ("bericht") or recommendation ("empfehlung") is being made."""
    was: str
    anlass: str = ""


@dataclass(frozen=True)
class NeuerBericht:
    sitrep: report.Sitrep
    nummer: int


@dataclass(frozen=True)
class NeueEmpfehlung:
    empfehlung: report.Empfehlung
    nummer: int


@dataclass(frozen=True)
class Fehlgeschlagen:
    """A report or recommendation could not be made."""
    was: str
    fehler: str


# Seconds without sound after which the source is reported silent.
STUMM = 10.0

# Seconds between two readings of the live values. Action readings arrive
# once a second and lines as they end, so this adds at most half a second.
WERTE_TAKT = 0.5

# Stills a report is shown, from the last BERICHT_SEKUNDEN. The Chronik's
# Abschnitte have seen the earlier ones; these show where people are now.
BERICHT_BILDER = 2
BERICHT_SEKUNDEN = 15.0

# Seconds between two recommendations asked for by the alarm. An alarm
# raised again meanwhile is answered once the pause is over.
EMPFEHLUNG_PAUSE = 15.0

# Seconds of stills kept: the Abschnitt under way and a report's last seconds.
BILDER_KEEP = 120.0


class Anfragen:
    """Requests of one kind, made one at a time on a thread of their own.

    A request while one is being made is not queued a second time: one more
    is made once the running one is done, for the newest reason given. A
    request with `pause` waits until `pause` seconds after the last one.
    """

    def __init__(self, make, pause: float = 0.0):
        self._make = make
        self._pause = pause
        self._condition = threading.Condition()
        self._pending: str | None = None
        self._pending_pauses = False
        self._last = -float("inf")
        self.running = False
        self._stop = False
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def request(self, anlass: str, *, pause: bool = False) -> bool:
        """Ask for one. Returns False if one is already being made."""
        with self._condition:
            busy = self.running
            self._pending = anlass
            self._pending_pauses = pause
            self._condition.notify_all()
            return not busy

    def _loop(self):
        while True:
            with self._condition:
                while not self._stop:
                    if self._pending is None:
                        self._condition.wait()
                        continue
                    wait = (self._last + self._pause - time.monotonic()
                            if self._pending_pauses else 0.0)
                    if wait <= 0:
                        break
                    self._condition.wait(wait)
                if self._stop:
                    return
                anlass, self._pending = self._pending, None
                self.running = True
            try:
                self._make(anlass)
            except Exception as error:
                print(f"request failed: {error!r}", file=sys.stderr)
            finally:
                with self._condition:
                    self.running = False
                    self._last = time.monotonic()

    def close(self):
        with self._condition:
            self._stop = True
            self._condition.notify_all()


class Session:
    """A run in progress: one camera, one microphone, and their readers.

    Constructing one starts the readers of the camera; `events()` starts
    listening, the stills and the Chronik. Closing stops everything in the
    reverse order, so no reader can sample a camera that has been released.
    """

    def __init__(self, video: devices.VideoDevice,
                 audio: devices.AudioDevice | ndi_audio.NdiAudio,
                 options: Options | None = None, *, stream=None):
        self.options = options or Options()
        # Before the camera is opened, so that a missing model holds nothing.
        llm.pruefen(self.options.model)
        self.audio = audio
        # A stream given ready-made, e.g. a recording replayed (replay.py), is
        # read like a camera and closed with the session.
        self.stream = stream or capture.VideoStream(video, self.options.width, self.options.height)
        self.publisher = None
        self.tracker = None
        self.actions = None
        self.speakers = None
        self.reference = None
        self.frames = None
        self.utterances = None
        self.chronik = None
        self.lage = None
        self.meter = loudness.Meter()
        # Learns this run's normal speaking level from its first speech.
        self.laut = loudness.Calibration()
        self.sender = None
        self.roster = None
        self.missing_enrolment: list[pathlib.Path] = []
        # Bodies the operator named: the face lessons each one taught, and the
        # label it carried before, which the model is told it now means.
        self._lessons: dict[int, list[int]] = {}
        self._umbenannt: dict[int, tuple[str, str]] = {}
        self._assigning = threading.Lock()
        self._events: queue.Queue = queue.Queue()
        self._berichte = None
        self._empfehlungen = None
        self._berichte_gemacht = 0
        self._empfehlungen_gemacht = 0
        self._stop = threading.Event()
        # When listening began: a source that delivers nothing is silent from then.
        self._listening: datetime | None = None
        self._closed = False

        # A part that fails after the camera is open would otherwise leave it
        # held by a session nobody has a handle to, and the next run could not
        # acquire it without restarting the process.
        try:
            self._start_readers()
        except BaseException:
            self.close()
            raise

    def _start_readers(self):
        if self.options.ndi:
            self.publisher = feed.Publisher(
                self.stream, name=self.options.ndi, fps=self.options.ndi_fps).start()

        cast = None
        if self.options.cast:
            cast, self.missing_enrolment = gallery.enrol(self.options.cast)
        self.tracker = presence.PresenceTracker(self.stream, cast).start()

        if self.options.actions:
            # Speakers are told apart by the lips of the people the action
            # recogniser follows, on the frames it tracks.
            self.speakers = speakers.Speakers().load()
            # Appearance names people the faces cannot, where its model is
            # installed (appearance.py); without it, faces name them alone.
            appearances = appearance.Appearances() if appearance.available() else None
            if appearances is None:
                print("appearance model missing: people are named by face alone "
                      "(src/scripts/export_osnet.py)", file=sys.stderr)
            # Vorhersehbarkeit is measured where a rehearsal reference has
            # been built (predictability.py), as appearance is used where its
            # model is installed.
            self.reference = predictability.load() if predictability.available() else None
            if self.reference is None:
                print("no rehearsal reference: vorhersehbarkeit not measured "
                      "(python -m sitrep.predictability --project ...)", file=sys.stderr)
            self.actions = actions.ActionRatings(self.stream, self.tracker,
                                                 on_frame=self.speakers.observe,
                                                 on_learn=self._learn,
                                                 appearances=appearances,
                                                 reference=self.reference).start()

        if self.options.send_td:
            self.sender = td.Sender()
            self.roster = td.RosterStream(self.sender, self.tracker).start()

    # The live part ----------------------------------------------------------

    def events(self) -> Iterator:
        """Listen, keep the Chronik and the live values, and yield what they produce.

        Runs until the session is closed or the caller stops consuming. A
        sound source that cannot be opened, e.g. an NDI source not found,
        raises here.
        """
        self._start_live()
        try:
            with capture.listen(self.audio, self.utterances.feed):
                self._listening = datetime.now()
                while not self._stop.is_set():
                    try:
                        yield self._events.get(timeout=0.1)
                    except queue.Empty:
                        continue
        finally:
            self._stop_live()

    def _start_live(self):
        options = self.options
        self.chronik = chronik.Chronik(
            laenge=options.window, model=options.model,
            roster=self._roster,
            handlungen=self._handlungen if self.actions else None,
            bilder=self._bilder,
            on_abschnitt=self._abschnitt)
        with self._assigning:
            self.chronik.zuordnen(self._zuordnungen())
        self.frames = capture.FrameRing(self.stream, interval=options.interval,
                                        keep=max(BILDER_KEEP, 2 * options.window),
                                        annotate=self._name_faces).start()
        self.lage = lage.Lage(self.actions.since if self.actions else None,
                              self.chronik.zeilen_seit, self._gain)
        self.utterances = utterances.Utterances(
            int(self.audio.samplerate), self._zeilen, language=options.language,
            meter=self.meter, laut=self.laut,
            sprecher=self._sprecher if self.speakers else None,
            einschaetzen=self._einschaetzen).start()
        self.chronik.start()
        self._berichte = Anfragen(self._bericht)
        self._empfehlungen = Anfragen(self._empfehlung, pause=EMPFEHLUNG_PAUSE)
        threading.Thread(target=self._watch, daemon=True).start()

    def _stop_live(self):
        self._stop.set()
        for part in (self.utterances, self.chronik, self.frames, self._berichte,
                     self._empfehlungen):
            if part:
                part.close()

    def _emit(self, event):
        self._events.put(event)

    def _send(self, messages):
        if self.sender:
            self.sender.send_all(messages)

    def _zeilen(self, lines: list[report.Aeusserung], bewertet: bool = True):
        """Lines transcribed or rated: into the Chronik, and out to the page
        and over OSC at once."""
        self.chronik.add(lines)
        self._emit(Zeilen(lines, bewertet))
        self._send(td.zeilen_messages(lines, bewertet))

    def _abschnitt(self, abschnitt: chronik.Abschnitt):
        self._emit(NeuerAbschnitt(abschnitt))
        self._send(td.abschnitt_messages(abschnitt))
        summary = abschnitt.zusammenfassung
        # A stretch the Chronik rated past the threshold asks for a
        # recommendation as the live alarm does: the Chronik sees what the
        # fast lane cannot, such as a scene sharpening without one loud line.
        if summary and report.ueber_schwelle(summary.szene) and self.options.auto_empfehlung:
            self._empfehlungen.request(
                f"Abschnitt {abschnitt.beginn:%H:%M:%S}-{abschnitt.ende:%H:%M:%S}: "
                f"Eskalation {summary.szene.eskalation}, Gefahr {summary.szene.gefahr}, "
                f"{summary.tendenz}.", pause=True)

    def _watch(self):
        """Read the live values every WERTE_TAKT and announce every visible change.

        The alarm's rising edge asks for a recommendation.
        """
        shown = None
        alarm = False
        stumm = False
        tick = 0
        while not self._stop.wait(WERTE_TAKT):
            if self.ton()["stumm"] != stumm:
                stumm = not stumm
                self._emit(Ton(stumm, self.audio.name))
            try:
                stand = self.lage.jetzt()
            except Exception as error:
                print(f"live values: {error!r}", file=sys.stderr)
                continue
            if stand.gerundet() != shown:
                shown = stand.gerundet()
                tick += 1
                self._emit(Werte(stand))
                self._send(td.werte_messages(stand, tick))
            if stand.alarm.aktiv and not alarm and self.options.auto_empfehlung:
                wer = stand.alarm.wer or report.UNKLAR
                self._empfehlungen.request(
                    f"Alarm: {wer}, Risiko {stand.alarm.wert}. {stand.alarm.anlass}", pause=True)
            alarm = stand.alarm.aktiv

    # Requests ---------------------------------------------------------------

    def bericht(self) -> bool:
        """Ask for a report. False while the live part is not running, or
        while a report is being made (it is then made once more after)."""
        if self._berichte is None:
            return False
        return self._berichte.request("Vom Operator angefordert.")

    def empfehlung(self) -> bool:
        """Ask for a recommendation now."""
        if self._empfehlungen is None:
            return False
        return self._empfehlungen.request("Vom Operator angefordert.")

    def assign(self, body: int, name: str | None):
        """Name a body in view by hand, or release it to the automatic naming.

        The name is absolute for that body (actions.ActionRatings.assign). If
        a face was seen on the body, its face track takes the name too and
        its faces are learned for the rest of the run
        (presence.PresenceTracker.teach), so the person is recognised after
        leaving the picture. Faces seen on the body later are learned as they
        appear (`_learn`). Releasing takes every lesson of the body back. The
        model is told which earlier label now means whom, since the Chronik
        already written still uses it.
        """
        if self.actions is None:
            raise ValueError("Ohne Aktionserkennung werden keine Körper verfolgt.")
        cast = self.tracker.cast
        if name is not None and (cast is None or name not in cast.names):
            raise ValueError(f"{name!r} gehört nicht zur Besetzung.")
        with self._assigning:
            before = self.actions.names().get(body, f"Körper {body}")
            face = self.actions.assign(body, name)
            for lesson in self._lessons.pop(body, []):
                self.tracker.unteach(lesson)
            first, _ = self._umbenannt.pop(body, (before, None))
            if name is not None:
                if face is not None and face != name:
                    self._teach(body, face, name)
                if first != name:
                    self._umbenannt[body] = (first, name)
            if self.chronik is not None:
                self.chronik.zuordnen(self._zuordnungen())

    def _learn(self, body: int, face: str, name: str):
        """Learn a face that stayed on a body named by hand, under its name.

        Called by the action recogniser, from its thread, while the name
        holds; an assignment changed meanwhile wins.
        """
        with self._assigning:
            if self.actions.pinned(body) == name:
                self._teach(body, face, name)

    def _teach(self, body: int, face: str, name: str):
        lesson = self.tracker.teach(face, name)
        if lesson is not None:
            self._lessons.setdefault(body, []).append(lesson)

    def _zuordnungen(self) -> list[str]:
        """The operator's reassignments, as the Chronik tells the model of them."""
        return [f"{alt} ist {neu}" for alt, neu in self._umbenannt.values()]

    def _roster(self, since: datetime, until: datetime) -> list[presence.Presence]:
        """Who was present: the cast faces recognised, and cast members named
        on a body without a face recognised, by appearance or by hand, so the
        report may name them. Unrecognised people are reported as Unbekannt."""
        roster = [person for person in self.tracker.roster(since, until) if person.known]
        if self.actions is not None:
            present = {person.label for person in roster}
            roster += [presence.Presence(name, name, 1.0, 0, since, until)
                       for name in self.actions.carried(since, until) if name not in present]
        return roster

    def _bericht(self, anlass: str):
        started = time.monotonic()
        now = datetime.now()
        self._emit(Angefordert("bericht", anlass))
        seit = self.chronik.woertlich_seit()
        try:
            document = report.bericht(
                beginn=self.chronik.von(), ende=now,
                frames=self.frames.between(now - timedelta(seconds=BERICHT_SEKUNDEN), now,
                                           BERICHT_BILDER),
                aeusserungen=self.chronik.zeilen_seit(seit),
                anwesend=self._anwesend(seit, now),
                handlungen=self._handlungen(seit, now) if self.actions else [],
                kontext=self.chronik.kontext(), werte=self.lage.jetzt(now).beschreiben(),
                abschnitte=len(self.chronik.abschnitte), laut=self.laut,
                model=self.options.model, started=started)
        except Exception as error:
            # A reply cut off at the token cap does not parse; a rejected
            # prompt returns an error. The run goes on either way.
            print(f"report failed: {error!r}", file=sys.stderr)
            self._emit(Fehlgeschlagen("bericht", str(error)))
            return
        self._berichte_gemacht += 1
        self._emit(NeuerBericht(document, self._berichte_gemacht))
        self._send(td.messages(document, self._berichte_gemacht))

    def _empfehlung(self, anlass: str):
        started = time.monotonic()
        now = datetime.now()
        self._emit(Angefordert("empfehlung", anlass))
        seit = self.chronik.woertlich_seit()
        try:
            empfehlung = report.empfehlen(
                anlass=anlass,
                frames=self.frames.between(now - timedelta(seconds=BERICHT_SEKUNDEN), now, 1),
                aeusserungen=self.chronik.zeilen_seit(seit),
                anwesend=self._anwesend(seit, now),
                kontext=self.chronik.kontext(), werte=self.lage.jetzt(now).beschreiben(),
                model=self.options.model, started=started)
        except Exception as error:
            print(f"recommendation failed: {error!r}", file=sys.stderr)
            self._emit(Fehlgeschlagen("empfehlung", str(error)))
            return
        self._empfehlungen_gemacht += 1
        self._emit(NeueEmpfehlung(empfehlung, self._empfehlungen_gemacht))
        self._send(td.empfehlung_messages(empfehlung, self._empfehlungen_gemacht))

    def ton(self, now: datetime | None = None) -> dict:
        """The sound as it arrives: its level over the last 2 s, and whether
        the source has gone silent (STUMM)."""
        now = now or datetime.now()
        still = self.meter.still_for(now)
        if still is None:
            # Nothing arrived yet; silent once the run has listened STUMM seconds.
            still = (now - self._listening).total_seconds() if self._listening else 0.0
        return {"quelle": self.audio.name,
                "pegel_db": self.meter.level(now - timedelta(seconds=2), now),
                "stumm": still >= STUMM, "still_s": round(still, 1)}

    @property
    def laeuft(self) -> dict[str, bool]:
        """Which kinds of request are being made now."""
        return {"bericht": bool(self._berichte and self._berichte.running),
                "empfehlung": bool(self._empfehlungen and self._empfehlungen.running)}

    # Sources the parts read -------------------------------------------------

    def _gain(self, begins: datetime, ends: datetime) -> float:
        return loudness.gain_over(self.meter, self.laut, begins, ends)

    def _handlungen(self, since: datetime, until: datetime) -> list[report.Handlung]:
        return self.actions.between(since, until, self._gain)

    def _bilder(self, since: datetime, until: datetime, count: int) -> list[bytes]:
        return self.frames.between(since, until, count)

    def _anwesend(self, since: datetime, until: datetime) -> list[report.Anwesend]:
        return [report.Anwesend(name=person.label)
                for person in self._roster(since, until)]

    def _einschaetzen(self, aeusserungen, vorher):
        """The lines rated by the run's model."""
        return speech.rate(aeusserungen, model=self.options.model, vorher=vorher)

    def _sprecher(self, segmente, audio_start):
        """Who said each segment, with the names the bodies carry now."""
        return self.speakers.attribute(segmente, audio_start, self.actions.names())

    def overlay(self, frame):
        """A copy of a frame with the tracked people boxed and named.

        For the operator's view only: the model's frames carry face tags
        (annotate.py), and the NDI feed stays unmarked.
        """
        if not self.actions:
            return frame
        return annotate.draw_names(frame, self.actions.visible())

    def _name_faces(self, frame):
        """The model's copy of a frame, with the tracker's name on each face.

        A failed naming pass yields the frame unmarked, and the model names
        the people in it "Unbekannt". This runs inside the stills' sampling
        loop, so letting the error through would stop the stills.
        """
        try:
            named = self.tracker.name_faces(frame)
        except Exception as error:
            print(f"naming pass failed, frame sent unmarked: {error!r}", file=sys.stderr)
            return frame
        return annotate.draw_names(frame, named)

    def close(self):
        """Stop every reader, delete what they hold, then release the camera.

        Listening stops first. What the parts keep about the people in the
        room, such as sound, lines, the Chronik, stills, faces, poses, mouth
        measurements and readings, is deleted here rather than left for the
        memory to be reclaimed at some later point. A report or summary still
        being generated finishes, and is dropped.

        Idempotent: a run has two plausible closers, the command line's context
        manager and a later stop request, and both may arrive.
        """
        if self._closed:
            return
        self._closed = True
        self._stop_live()
        # The action recogniser reads the tracker's faces, so it stops first.
        for reader in (self.roster, self.publisher, self.actions, self.tracker):
            if reader:
                reader.close()
        for holder in (self.utterances, self.chronik, self.frames, self.actions,
                       self.speakers, self.tracker, self.meter):
            if holder:
                holder.clear()
        while True:
            try:
                self._events.get_nowait()
            except queue.Empty:
                break
        self.laut = loudness.Calibration()
        self.stream.close()

    def describe(self) -> str:
        """The channels this run is using, for the operator to read at startup."""
        lines = [devices.describe(self.stream.device, self.audio),
                 f"speech: {self.options.language} ({transcribe.MODEL}), per utterance",
                 f"chronik: every {self.options.window:g}s, stills every "
                 f"{self.options.interval:g}s; reports when asked for"]
        if not self.options.auto_empfehlung:
            lines.append("empfehlung: only when asked for")
        if self.publisher:
            lines.append(f"ndi:    {self.options.ndi} @ {self.options.ndi_fps:g} fps")
        if self.sender:
            lines.append(f"osc:    {self.sender.host}:{self.sender.port}")
        if self.actions:
            lines.append(f"action: NTU120 ST-GCN on {actions.model.active_provider()}")
            if self.reference is not None:
                lines.append(f"vorhersehbarkeit: {predictability.describe(self.reference)}")
        else:
            lines.append("action: off, risiko, menschlichkeit and vorhersehbarkeit "
                         "not measured")
        if self.tracker.cast:
            lines.append(f"cast:   {', '.join(self.tracker.cast.names)}")
        else:
            lines.append("cast:   none, nobody is recognised")
        return "\n".join(lines)

    def __enter__(self) -> "Session":
        return self

    def __exit__(self, *exception):
        self.close()
