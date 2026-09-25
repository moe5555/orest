"""A run: one camera, several readers, and the order they are shut down in.

DirectShow refuses a second process the camera, so a reader that opens its own
or closes one it borrowed breaks the whole run rather than itself. None of that
raises on its own, so it is pinned here. Needs no camera, model, NDI or
TouchDesigner.
"""

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
    """A publisher or tracker, recording that it was started and closed."""

    def __init__(self, source, closed, label, **kwargs):
        self.source = source
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

    def close(self):
        self._closed.append(self._label)


@pytest.fixture(autouse=True)
def no_face_models(monkeypatch):
    """Every session follows faces; no test here loads the face models to do so."""
    monkeypatch.setattr(session.presence, "PresenceTracker",
                        lambda source, cast, **kwargs: FakeReader(source, [], "tracker"))


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

    monkeypatch.setattr(session.feed, "Publisher", publisher)
    monkeypatch.setattr(session.presence, "PresenceTracker", tracker)
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


def test_readers_are_closed_before_the_camera(room, readers, tmp_path):
    """A reader sampling a released camera is the failure this order prevents."""
    video, audio, _, _, closed = room
    options = session.Options(cast=tmp_path, ndi="Orest Test")
    session.Session(video, audio, options).close()
    assert closed[-1] == "camera"
    assert set(closed[:-1]) == {"publisher", "tracker"}


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


def test_each_report_is_given_the_trackers_roster(monkeypatch, room, readers, sitrep):
    video, audio, _, _, _ = room
    given = {}

    def sitreps(windows, model=None, roster=None):
        given["roster"] = roster
        return iter([sitrep])

    monkeypatch.setattr(session.report, "sitreps", sitreps)
    with session.Session(video, audio) as live:
        list(live.reports())
        assert given["roster"] == live.tracker.roster


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
        cast = tmp_path
        send_ndi, ndi_name, ndi_fps = True, "Orest Test", 15.0
        send_td = True

    options = session.Options.from_args(Args())
    assert options.ndi == "Orest Test"
    assert options.ndi_fps == 15.0
    assert options.cast == tmp_path
    assert options.send_td


def test_ndi_is_off_unless_asked_for(tmp_path):
    class Args:
        interval, window = 5.0, 20.0
        width = height = None
        model = "gemma4:e4b"
        cast = None
        send_ndi, ndi_name, ndi_fps = False, "Orest Test", 30.0
        send_td = False

    assert session.Options.from_args(Args()).ndi is None


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
