"""The NDI publisher: frame packing, and the camera it must not close.

A wrongly packed buffer reaches TouchDesigner as a picture with swapped
channels rather than as an error, and a publisher that closes the camera it
borrowed takes the SITREP down with it. These tests pin both, and need no NDI,
no camera and no TouchDesigner.
"""

import threading
import time

import numpy as np
import pytest

from sitrep import feed


class FakeSource:
    """Stands in for a VideoStream, handing out a new frame on every read."""

    def __init__(self, width=64, height=48):
        self.width, self.height = width, height
        self.reads = 0
        self.closed = False

    def latest(self):
        frame = np.full((self.height, self.width, 3), self.reads % 251, dtype=np.uint8)
        self.reads += 1
        return frame

    def close(self):
        self.closed = True


class FakeSink:
    """Records what a publisher sent instead of opening an NDI source."""

    def __init__(self, name, width, height, fps):
        self.opened_with = (name, width, height, fps)
        self.buffers = []
        self.closed = False
        self._lock = threading.Lock()

    def send(self, buffer):
        with self._lock:
            self.buffers.append(buffer.copy())

    def close(self):
        self.closed = True


@pytest.fixture
def sink_factory():
    """A sink factory that keeps the sink it made, for the test to inspect."""
    made = []

    def factory(name, width, height, fps):
        made.append(FakeSink(name, width, height, fps))
        return made[-1]

    factory.made = made
    return factory


def test_bgrx_puts_blue_green_red_and_an_opaque_byte_in_that_order():
    """OpenCV frames are BGR; NDI reads the buffer as BGRX. A swap here would
    reach TouchDesigner as a picture with red and blue exchanged."""
    frame = np.zeros((1, 1, 3), dtype=np.uint8)
    frame[0, 0] = (10, 20, 30)          # B, G, R as OpenCV orders them
    assert list(feed.bgrx(frame)) == [10, 20, 30, 255]


def test_bgrx_is_flat_contiguous_and_sized_for_the_frame():
    packed = feed.bgrx(np.zeros((48, 64, 3), dtype=np.uint8))
    assert packed.shape == (64 * 48 * 4,)
    assert packed.dtype == np.uint8
    assert packed.flags.c_contiguous


def test_the_sink_is_opened_at_the_camera_resolution(sink_factory):
    source = FakeSource(width=320, height=180)
    publisher = feed.Publisher(source, name="Orest Test", fps=25, sink=sink_factory)
    publisher.start()
    try:
        assert sink_factory.made[0].opened_with == ("Orest Test", 320, 180, 25)
    finally:
        publisher.close()


def test_each_pass_sends_the_newest_frame(sink_factory):
    source = FakeSource()
    publisher = feed.Publisher(source, sink=sink_factory)
    publisher.sink = sink_factory("test", 64, 48, 30)
    publisher.publish(source.latest())
    publisher.publish(source.latest())

    sent = sink_factory.made[0].buffers
    assert len(sent) == 2
    assert not np.array_equal(sent[0], sent[1])
    assert publisher.frames == 2


def test_the_publisher_keeps_sending_on_its_own_thread(sink_factory):
    publisher = feed.Publisher(FakeSource(), fps=50, sink=sink_factory)
    publisher.start()
    time.sleep(0.2)
    publisher.close()
    # A lower bound rather than an exact count: a loaded machine sends fewer.
    assert publisher.frames >= 2


def test_closing_the_publisher_closes_its_sink(sink_factory):
    publisher = feed.Publisher(FakeSource(), sink=sink_factory)
    publisher.start()
    publisher.close()
    assert sink_factory.made[0].closed


def test_closing_the_publisher_leaves_the_camera_open(sink_factory):
    """The camera is the session's, shared with the capture loop and the
    tracker; a publisher that closed it would end the run."""
    source = FakeSource()
    publisher = feed.Publisher(source, sink=sink_factory)
    publisher.start()
    publisher.close()
    assert not source.closed


def test_a_missing_publisher_package_names_the_install(monkeypatch):
    def unavailable(*arguments):
        raise ImportError("No module named 'cyndilib'")

    monkeypatch.setattr(feed, "Sink", unavailable)
    with pytest.raises(RuntimeError, match="cyndilib"):
        feed.open_sink("Orest Test", 64, 48, 30)


def test_a_missing_ndi_runtime_is_reported_like_a_missing_package(monkeypatch):
    """The package can import while the NDI library it loads is absent; the
    operator's fix is the same kind of install either way."""
    def unavailable(*arguments):
        raise OSError("Processing.NDI.Lib.x64.dll not found")

    monkeypatch.setattr(feed, "Sink", unavailable)
    with pytest.raises(RuntimeError, match="NDI runtime"):
        feed.open_sink("Orest Test", 64, 48, 30)


def test_publishing_writes_nothing_to_disk(monkeypatch, tmp_path, sink_factory):
    """The real-time path retains nothing; a video channel must not change that."""
    monkeypatch.chdir(tmp_path)
    with feed.Publisher(FakeSource(), fps=50, sink=sink_factory):
        time.sleep(0.1)
    assert list(tmp_path.rglob("*")) == []
