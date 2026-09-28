"""A run: one camera, several readers, and the order they are shut down in.

DirectShow refuses a second process the camera, so a reader that opens its own
or closes one it borrowed breaks the whole run rather than itself. None of that
raises on its own, so it is pinned here. Needs no camera, model, NDI or
TouchDesigner.
"""

import threading
import time
from datetime import datetime

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

    def roster(self):
        """A tracker's reading, which the roster stream asks for on its thread."""
        return []

    def take(self, until, gain=None):
        """An action recogniser's ratings, which each report asks for."""
        return []

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


def test_a_run_streams_without_writing_anything(monkeypatch, tmp_path, room, sitrep):
    """The live SITREP is streamed and not retained."""
    video, audio, _, _, _ = room
    monkeypatch.setattr(session.report, "sitreps", lambda windows, **kwargs: iter([sitrep]))
    monkeypatch.chdir(tmp_path)

    with session.Session(video, audio) as live:
        produced = list(live.reports())

    assert produced == [sitrep]
    assert list(tmp_path.rglob("*")) == []


def test_every_report_is_announced_over_osc(monkeypatch, room, sitrep):
    video, audio, _, _, _ = room
    monkeypatch.setattr(session.td, "Sender", RecordingSender)
    monkeypatch.setattr(session.report, "sitreps",
                        lambda windows, **kwargs: iter([sitrep, sitrep]))

    with session.Session(video, audio, session.Options(send_td=True)) as live:
        list(live.reports())
        begins = [arguments for address, arguments in live.sender.sent
                  if address == session.td.SITREP_BEGIN]

    assert [arguments[1] for arguments in begins] == [1, 2]


def test_a_run_without_send_td_announces_nothing(monkeypatch, room, sitrep):
    video, audio, _, _, _ = room
    monkeypatch.setattr(session.report, "sitreps", lambda windows, **kwargs: iter([sitrep]))
    with session.Session(video, audio) as live:
        list(live.reports())
        assert live.sender is None


def test_faces_are_followed_with_or_without_a_cast(room, readers, tmp_path):
    """Every person in a report carries a name, so the tracker runs on every
    run; a cast only turns guesses into recognitions."""
    video, audio, _, _, _ = room
    with session.Session(video, audio) as live:
        assert live.tracker is readers["tracker"]
        assert live.tracker.cast is None

    with session.Session(video, audio, session.Options(cast=tmp_path)) as live:
        assert isinstance(live.tracker.cast, FakeGallery)


def test_each_report_is_given_the_roster_and_the_action_ratings(
        monkeypatch, room, readers, sitrep):
    video, audio, _, _, _ = room
    given = {}

    def sitreps(windows, model=None, roster=None, handlungen=None, sprecher=None,
                einschaetzen=None, laut=None, language=None):
        given.update(roster=roster, handlungen=handlungen, sprecher=sprecher,
                     einschaetzen=einschaetzen, laut=laut, language=language)
        return iter([sitrep])

    monkeypatch.setattr(session.report, "sitreps", sitreps)
    with session.Session(video, audio) as live:
        list(live.reports())
        assert given["roster"] == live.tracker.roster
        assert given["handlungen"] == live.actions.take
        assert given["language"] == "de"
        assert given["sprecher"] == live._sprecher
        assert given["einschaetzen"] == live._einschaetzen
        # One loudness calibration for the whole run.
        assert given["laut"] is live.laut


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


def test_the_roster_is_sent_whenever_reports_are(monkeypatch, room, readers):
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
        model = "gemma4:e4b"
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
        model = "gemma4:e4b"
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


def test_stopping_drops_the_windows_waiting_for_a_report(room, readers, monkeypatch):
    """A report still being generated must not keep the recording alive."""
    video, audio, _, _, _ = room
    started = threading.Event()

    def sitreps(windows, **kwargs):
        started.set()
        yield from ()

    monkeypatch.setattr(session.report, "sitreps", sitreps)
    live = session.Session(video, audio, session.Options(interval=0.1, window=0.2))
    reports = live.reports()
    thread = threading.Thread(target=lambda: list(reports), daemon=True)
    thread.start()
    assert started.wait(5)
    time.sleep(0.5)
    live.close()
    assert live.recorder.held == (0, 0)
