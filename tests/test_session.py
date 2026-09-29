"""A run: one camera, several readers, and the order they are shut down in.

DirectShow refuses a second process the camera, so a reader that opens its own
or closes one it borrowed breaks the whole run rather than itself. None of that
raises on its own, so it is pinned here. Needs no camera, model, NDI or
TouchDesigner.
"""

import threading
import time
from datetime import datetime, timedelta

import numpy as np
import pytest

from sitrep import capture, devices, session

SAMPLERATE = 16000


class FakeCamera:
    """Stands in for cv2.VideoCapture, delivering frames at a plausible rate."""

    def __init__(self):
        self.released = False
        self.frame = np.zeros((48, 64, 3), dtype=np.uint8)

    def read(self):
        time.sleep(0.005)
        return True, self.frame

    def isOpened(self):
        return True

    def set(self, *args):
        return True

    def release(self):
        self.released = True


class FakeInputStream:
    """Stands in for sounddevice.InputStream, which never delivers audio here."""

    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def __enter__(self):
        return self

    def __exit__(self, *exception):
        return False


@pytest.fixture
def room(monkeypatch):
    """A fake camera and microphone, plus a record of what was closed when."""
    camera = FakeCamera()
    opened = []
    closed = []

    def open_video(device, width=None, height=None):
        opened.append(device)
        return camera

    monkeypatch.setattr(capture.devices, "open_video", open_video)
    monkeypatch.setattr(capture.sd, "InputStream", FakeInputStream)

    real_close = capture.VideoStream.close

    def note_close(self):
        closed.append("camera")
        real_close(self)

    monkeypatch.setattr(capture.VideoStream, "close", note_close)

    video = devices.VideoDevice(0, "Fake Camera")
    audio = devices.AudioDevice(0, "Fake Mic", "MME", 0, 1, float(SAMPLERATE))
    return video, audio, camera, opened, closed


class FakeReader:
    """A publisher, tracker or action recogniser, recording that it was started and closed."""

    def __init__(self, source, closed, label, faces=None, **kwargs):
        self.source = source
        self.faces = faces
        self._closed = closed
        self._label = label
        self.started = False
        self.cast = None

    def start(self):
        self.started = True
        return self

    def roster(self, since=None, until=None):
        """A tracker's reading, which the roster stream and the Chronik ask for."""
        return []

    def name_faces(self, frame):
        return []

    def since(self, since, until=None):
        """An action recogniser's readings, which the live values read."""
        return [], {}

    def between(self, since, until, gain=None):
        """An action recogniser's ratings over a stretch."""
        return []

    def names(self):
        return {}

    def clear(self):
        self.cleared = True

    def close(self):
        self._closed.append(self._label)


class FakeSpeakers:
    """Mouth measurement, without the landmark model."""

    cleared = False

    def clear(self):
        self.cleared = True

    def load(self):
        return self

    def observe(self, image, frame):
        pass

    def attribute(self, segments, audio_start, names):
        return []


@pytest.fixture(autouse=True)
def no_ollama(monkeypatch):
    """Every run checks its model with Ollama; no test here needs Ollama."""
    monkeypatch.setattr(session.llm, "pruefen", lambda model: None)


@pytest.fixture(autouse=True)
def no_whisper(monkeypatch):
    """Listening loads Whisper onto the GPU; no test here transcribes."""
    monkeypatch.setattr(session.transcribe, "load", lambda: None)


@pytest.fixture(autouse=True)
def no_face_models(monkeypatch):
    """Every session follows faces and bodies; no test here loads a model to do so."""
    monkeypatch.setattr(session.presence, "PresenceTracker",
                        lambda source, cast, **kwargs: FakeReader(source, [], "tracker"))
    monkeypatch.setattr(session.actions, "ActionRatings",
                        lambda source, faces, **kwargs: FakeReader(source, [], "actions", faces))
    monkeypatch.setattr(session.speakers, "Speakers", FakeSpeakers)


@pytest.fixture
def readers(monkeypatch, room):
    """Publisher and tracker fakes that share the room's close log."""
    _, _, _, _, closed = room
    made = {}

    def publisher(source, **kwargs):
        made["publisher"] = FakeReader(source, closed, "publisher")
        return made["publisher"]

    def tracker(source, cast, **kwargs):
        made["tracker"] = FakeReader(source, closed, "tracker")
        made["tracker"].cast = cast
        return made["tracker"]

    def action_ratings(source, faces, on_frame=None, **kwargs):
        made["actions"] = FakeReader(source, closed, "actions", faces)
        made["actions"].on_frame = on_frame
        return made["actions"]

    monkeypatch.setattr(session.feed, "Publisher", publisher)
    monkeypatch.setattr(session.presence, "PresenceTracker", tracker)
    monkeypatch.setattr(session.actions, "ActionRatings", action_ratings)
    monkeypatch.setattr(session.gallery, "enrol",
                        lambda root: (FakeGallery(), [root / "blurred.jpg"]))
    return made


class FakeGallery:
    names = ["klara", "moritz"]


class RecordingSender:
    def __init__(self, *args, **kwargs):
        self.sent = []
        self.host, self.port = "127.0.0.1", 10000

    def send(self, message):
        self.sent.append(message)

    def send_all(self, messages):
        for message in messages:
            self.send(message)


def test_a_bare_session_opens_the_camera_once(room):
    video, audio, camera, opened, _ = room
    with session.Session(video, audio):
        assert len(opened) == 1
    assert camera.released


def test_every_reader_is_given_the_one_open_camera(room, readers, tmp_path):
    """The whole point of the session: three readers, one device."""
    video, audio, _, opened, _ = room
    options = session.Options(cast=tmp_path, ndi="Orest Test")
    with session.Session(video, audio, options) as live:
        assert len(opened) == 1
        assert readers["publisher"].source is live.stream
        assert readers["tracker"].source is live.stream
        assert readers["actions"].source is live.stream
        assert readers["actions"].faces is readers["tracker"]
        # Mouths are measured on the frames the action recogniser tracks.
        assert readers["actions"].on_frame == live.speakers.observe


def test_readers_are_closed_before_the_camera(room, readers, tmp_path):
    """A reader sampling a released camera is the failure this order prevents."""
    video, audio, _, _, closed = room
    options = session.Options(cast=tmp_path, ndi="Orest Test")
    session.Session(video, audio, options).close()
    assert closed[-1] == "camera"
    assert set(closed[:-1]) == {"publisher", "actions", "tracker"}


def test_the_action_recogniser_stops_before_the_tracker_it_reads(room, readers):
    video, audio, _, _, closed = room
    session.Session(video, audio).close()
    assert closed.index("actions") < closed.index("tracker")


def test_without_actions_no_recogniser_runs(room, readers):
    video, audio, _, _, _ = room
    with session.Session(video, audio, session.Options(actions=False)) as live:
        assert live.actions is None
        assert "not measured" in live.describe()
        assert "actions" not in readers


def test_a_reader_that_fails_to_start_does_not_strand_the_camera(room, monkeypatch):
    """A half-built run would otherwise hold the device with no handle to it,
    and the next run could not acquire it without restarting the process."""
    video, audio, camera, _, _ = room

    def refuses(source, **kwargs):
        raise RuntimeError("Could not open the NDI source")

    monkeypatch.setattr(session.feed, "Publisher", refuses)
    with pytest.raises(RuntimeError, match="NDI"):
        session.Session(video, audio, session.Options(ndi="Orest Test"))
    assert camera.released


def test_closing_twice_is_harmless(room):
    video, audio, _, _, closed = room
    live = session.Session(video, audio)
    live.close()
    live.close()
    assert closed.count("camera") == 1


def test_faces_are_followed_with_or_without_a_cast(room, readers, tmp_path):
    """Every person in a report carries a name, so the tracker runs on every
    run; a cast only turns guesses into recognitions."""
    video, audio, _, _, _ = room
    with session.Session(video, audio) as live:
        assert live.tracker is readers["tracker"]
        assert live.tracker.cast is None

    with session.Session(video, audio, session.Options(cast=tmp_path)) as live:
        assert isinstance(live.tracker.cast, FakeGallery)


def test_the_models_frames_are_marked_with_the_trackers_names(monkeypatch, room, readers):
    video, audio, _, _, _ = room
    named = [(np.array([0, 0, 10, 10]), "klara")]
    drawn = {}

    def draw(frame, faces):
        drawn["faces"] = faces
        return frame

    monkeypatch.setattr(session.annotate, "draw_names", draw)
    with session.Session(video, audio) as live:
        live.tracker.name_faces = lambda frame: named
        live._name_faces(np.zeros((4, 4, 3), dtype=np.uint8))

    assert drawn["faces"] is named


def test_a_failed_naming_pass_sends_the_frame_unmarked(room, readers):
    """The pass runs inside the sampling loop; an error there must not end
    the session."""
    video, audio, _, _, _ = room
    frame = np.zeros((4, 4, 3), dtype=np.uint8)

    def fail(frame):
        raise RuntimeError("out of memory")

    with session.Session(video, audio) as live:
        live.tracker.name_faces = fail
        assert live._name_faces(frame) is frame


def test_the_roster_is_sent_whenever_touchdesigner_is(monkeypatch, room, readers):
    video, audio, _, _, _ = room
    monkeypatch.setattr(session.td, "Sender", RecordingSender)

    with session.Session(video, audio) as live:
        assert live.roster is None

    with session.Session(video, audio, session.Options(send_td=True)) as live:
        assert live.roster is not None


def test_options_carry_the_command_line_through(tmp_path):
    class Args:
        interval, window = 5.0, 20.0
        width, height = 1920, 1080
        model = "some-model:tag"
        language = "en"
        cast = tmp_path
        send_ndi, ndi_name, ndi_fps = True, "Orest Test", 15.0
        send_td = True
        no_actions = False

    options = session.Options.from_args(Args())
    assert options.language == "en"
    assert options.ndi == "Orest Test"
    assert options.ndi_fps == 15.0
    assert options.cast == tmp_path
    assert options.send_td


def test_ndi_is_off_unless_asked_for(tmp_path):
    class Args:
        interval, window = 5.0, 20.0
        width = height = None
        model = "some-model:tag"
        language = "de"
        cast = None
        send_ndi, ndi_name, ndi_fps = False, "Orest Test", 30.0
        send_td = False
        no_actions = True

    options = session.Options.from_args(Args())
    assert options.ndi is None
    assert not options.actions


def test_the_startup_lines_name_every_open_channel(room, readers, tmp_path, monkeypatch):
    video, audio, _, _, _ = room
    monkeypatch.setattr(session.td, "Sender", RecordingSender)
    options = session.Options(cast=tmp_path, ndi="Orest Test", send_td=True)
    with session.Session(video, audio, options) as live:
        described = live.describe()

    assert "Fake Camera" in described
    assert "Orest Test" in described
    assert "127.0.0.1:10000" in described
    assert "klara" in described


def test_the_startup_lines_say_when_every_name_will_be_a_guess(room, readers):
    video, audio, _, _, _ = room
    with session.Session(video, audio) as live:
        assert "every name is a guess" in live.describe()


def test_enrolment_images_without_a_face_are_reported(room, readers, tmp_path):
    """An image that contributes nothing is usually a photograph taken too far
    away, and the operator should know before the rehearsal."""
    video, audio, _, _, _ = room
    with session.Session(video, audio, session.Options(cast=tmp_path)) as live:
        assert live.missing_enrolment == [tmp_path / "blurred.jpg"]


def test_stopping_deletes_what_the_readers_hold(room, readers):
    video, audio, _, _, _ = room
    live = session.Session(video, audio)
    live.close()
    assert readers["actions"].cleared and readers["tracker"].cleared
    assert live.speakers.cleared
    assert not live.laut.calibrated


def test_stopping_deletes_what_the_live_part_holds(room, readers):
    video, audio, _, _, _ = room
    running = Running(session.Session(video, audio))
    line = spoken("Du lügst.")
    running.live._zeilen([line])
    running.live.frames.sample()
    running.stop()
    assert running.live.chronik.zeilen_seit(line.ende - timedelta(seconds=1)) == []
    assert running.live.frames.between(datetime.min, datetime.max, 10) == []
    assert running.live._events.empty()


class Running:
    """A session's live part on a thread, with every event it yields collected."""

    def __init__(self, live):
        self.live = live
        self.events = []
        self._thread = threading.Thread(target=self._follow, daemon=True)
        self._thread.start()
        assert wait_for(lambda: live.lage is not None and live._empfehlungen is not None)

    def _follow(self):
        for event in self.live.events():
            self.events.append(event)

    def of(self, kind):
        return [event for event in self.events if isinstance(event, kind)]

    def stop(self):
        self.live.close()
        self._thread.join(5)


def wait_for(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def spoken(text, name="Klara", risiko=0):
    now = datetime.now()
    return session.report.Aeusserung(name=name, text=text, beginn=now, ende=now, risiko=risiko,
                                     menschlichkeit=0)


def test_a_run_streams_without_writing_anything(monkeypatch, tmp_path, room, readers):
    """The live SITREP is streamed and not retained."""
    video, audio, _, _, _ = room
    monkeypatch.chdir(tmp_path)
    running = Running(session.Session(video, audio))
    running.live._zeilen([spoken("Noch einmal von vorne.")])
    assert wait_for(lambda: running.of(session.Zeilen))
    running.stop()
    assert list(tmp_path.rglob("*")) == []


def test_lines_reach_the_chronik_the_page_and_touchdesigner_at_once(monkeypatch, room, readers):
    video, audio, _, _, _ = room
    monkeypatch.setattr(session.td, "Sender", RecordingSender)
    running = Running(session.Session(video, audio, session.Options(send_td=True)))
    line = spoken("Du lügst.")
    running.live._zeilen([line])
    assert wait_for(lambda: running.of(session.Zeilen))
    assert running.live.chronik.zeilen_seit(line.ende - timedelta(seconds=1)) == [line]
    assert [address for address, _ in running.live.sender.sent
            if address == session.td.LIVE_ZEILE] == [session.td.LIVE_ZEILE]
    running.stop()


def test_a_report_is_made_only_when_asked_for(monkeypatch, room, readers, sitrep):
    video, audio, _, _, _ = room
    monkeypatch.setattr(session.td, "Sender", RecordingSender)
    given = {}

    def bericht(**kwargs):
        given.update(kwargs)
        return sitrep

    monkeypatch.setattr(session.report, "bericht", bericht)
    running = Running(session.Session(video, audio, session.Options(send_td=True)))
    line = spoken("Du lügst.")
    running.live._zeilen([line])
    time.sleep(0.2)
    assert not running.of(session.NeuerBericht)

    assert running.live.bericht()
    assert wait_for(lambda: running.of(session.NeuerBericht))
    [made] = running.of(session.NeuerBericht)
    assert (made.sitrep, made.nummer) == (sitrep, 1)
    assert running.of(session.Angefordert)[0].was == "bericht"
    assert given["aeusserungen"] == [line]
    assert given["kontext"] == running.live.chronik.kontext()
    assert given["laut"] is running.live.laut
    assert [arguments[1] for address, arguments in running.live.sender.sent
            if address == session.td.SITREP_BEGIN] == [1]
    running.stop()


def test_a_report_that_fails_is_announced_and_the_run_goes_on(monkeypatch, room, readers):
    video, audio, _, _, _ = room

    def bericht(**kwargs):
        raise ValueError("unparseable reply")

    monkeypatch.setattr(session.report, "bericht", bericht)
    running = Running(session.Session(video, audio))
    running.live.bericht()
    assert wait_for(lambda: running.of(session.Fehlgeschlagen))
    running.live._zeilen([spoken("Weiter.")])
    assert wait_for(lambda: running.of(session.Zeilen))
    running.stop()


def test_the_alarm_asks_for_one_recommendation_while_it_lasts(monkeypatch, room, readers):
    video, audio, _, _, _ = room
    made = []

    def empfehlen(**kwargs):
        made.append(kwargs["anlass"])
        return session.report.Empfehlung(
            zeit=datetime.now(), anlass=kwargs["anlass"], latenz_s=0.1,
            urteil=session.report.Urteil(lage="Drohung.", empfehlung="Probe unterbrechen.",
                                         szene=session.report.Szene(relevanz=8, eskalation=8,
                                                                    gefahr=7)))

    monkeypatch.setattr(session.report, "empfehlen", empfehlen)
    running = Running(session.Session(video, audio))
    running.live._zeilen([spoken("Ich bring dich um.", risiko=4)])
    assert wait_for(lambda: running.of(session.NeueEmpfehlung))
    time.sleep(3 * session.WERTE_TAKT)
    assert len(made) == 1
    assert made[0].startswith("Alarm: Klara, Risiko 4.")
    [alarm] = [event for event in running.of(session.Werte) if event.stand.alarm.aktiv][:1]
    assert alarm.stand.personen["Klara"]["risiko"].wert == 4
    running.stop()


def test_without_auto_empfehlung_the_alarm_asks_for_nothing(monkeypatch, room, readers):
    video, audio, _, _, _ = room
    monkeypatch.setattr(session.report, "empfehlen",
                        lambda **kwargs: pytest.fail("no recommendation expected"))
    running = Running(session.Session(video, audio, session.Options(auto_empfehlung=False)))
    running.live._zeilen([spoken("Ich bring dich um.", risiko=4)])
    assert wait_for(lambda: any(event.stand.alarm.aktiv for event in running.of(session.Werte)))
    time.sleep(2 * session.WERTE_TAKT)
    running.stop()


def test_a_request_while_one_is_made_is_made_once_more_after():
    started = threading.Event()
    release = threading.Event()
    made = []

    def make(anlass):
        made.append(anlass)
        started.set()
        release.wait(5)

    requests = session.Anfragen(make)
    assert requests.request("erste")
    assert started.wait(5)
    assert not requests.request("zweite")
    assert not requests.request("dritte")
    release.set()
    assert wait_for(lambda: made == ["erste", "dritte"] and not requests.running)
    requests.close()


def test_a_request_with_a_pause_waits_for_it():
    made = []
    requests = session.Anfragen(lambda anlass: made.append(time.monotonic()), pause=0.3)
    requests.request("a", pause=True)
    assert wait_for(lambda: len(made) == 1)
    requests.request("b", pause=True)
    assert wait_for(lambda: len(made) == 2)
    assert made[1] - made[0] >= 0.29
    requests.close()


def test_nothing_can_be_asked_for_before_the_run_listens(room, readers):
    video, audio, _, _, _ = room
    with session.Session(video, audio) as live:
        assert not live.bericht()
        assert not live.empfehlung()


def test_a_model_ollama_does_not_have_fails_the_run_before_the_camera_opens(room, monkeypatch):
    video, audio, _, opened, _ = room

    def pruefen(model):
        raise RuntimeError(f"Model {model!r} is not in Ollama.")

    monkeypatch.setattr(session.llm, "pruefen", pruefen)
    with pytest.raises(RuntimeError, match="other-model:7b"):
        session.Session(video, audio, session.Options(model="other-model:7b"))
    assert opened == []


def test_a_source_that_delivers_no_sound_is_reported_silent(monkeypatch, room, readers):
    """An unfed audio device left a run without a single line and no sign why."""
    video, audio, _, _, _ = room
    monkeypatch.setattr(session, "STUMM", 0.3)
    running = Running(session.Session(video, audio))
    assert wait_for(lambda: running.of(session.Ton))
    [ton] = running.of(session.Ton)
    assert ton.stumm and ton.quelle == "Fake Mic"
    assert running.live.ton()["stumm"]
    running.stop()
