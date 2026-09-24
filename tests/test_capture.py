"""Capture buffering and the sampling loop, exercised without hardware."""

import io
import time
import wave

import numpy as np
import pytest

from sitrep import capture, devices

SAMPLERATE = 16000


class FakeCamera:
    """Stands in for cv2.VideoCapture, delivering frames at a plausible rate."""

    def __init__(self):
        self.released = False
        self.frame = np.zeros((8, 8, 3), dtype=np.uint8)

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

    def __exit__(self, *exc):
        return False


@pytest.fixture
def sources(monkeypatch):
    camera = FakeCamera()
    monkeypatch.setattr(capture.devices, "open_video", lambda *a, **k: camera)
    monkeypatch.setattr(capture.sd, "InputStream", FakeInputStream)
    return (devices.VideoDevice(0, "Fake Camera"),
            devices.AudioDevice(0, "Fake Mic", "MME", 0, 1, float(SAMPLERATE)))


@pytest.mark.parametrize("window, interval, expected", [
    (10, 5, 2),
    (30, 10, 3),
    (30, 5, 6),
    (60, 15, 4),
    (30, 7, 5),
    (5, 10, 1),
])
def test_frames_per_window_counts_the_samples_taken(window, interval, expected):
    assert capture.frames_per_window(window, interval) == expected


def test_sampling_loop_yields_the_predicted_frame_count(sources):
    """frames_per_window() is what benchmark.py sizes its input by, so it has
    to agree with the loop rather than approximate it."""
    video, audio = sources
    windows = capture.run(video, audio, interval=0.3, window=1.0)
    try:
        first = next(windows)
    finally:
        windows.close()

    assert len(first.frames) == capture.frames_per_window(1.0, 0.3) == 4
    assert first.seconds == pytest.approx(1.0, abs=0.2)
    assert first.index == 0


def test_windows_are_numbered_in_order(sources):
    video, audio = sources
    windows = capture.run(video, audio, interval=0.2, window=0.4)
    try:
        indices = [next(windows).index for _ in range(3)]
    finally:
        windows.close()
    assert indices == [0, 1, 2]


def test_camera_is_released_when_the_caller_stops(sources):
    video, audio = sources
    camera = capture.devices.open_video(video)
    windows = capture.run(video, audio, interval=0.2, window=0.4)
    next(windows)
    windows.close()
    assert camera.released


def test_a_caller_owned_camera_is_left_open(sources):
    """The sampling loop reads a shared stream; closing it is its owner's job,
    since the presence tracker and the TouchDesigner feed read the same one."""
    video, audio = sources
    camera = capture.devices.open_video(video)
    stream = capture.VideoStream(video)
    try:
        windows = capture.windows(stream, audio, interval=0.2, window=0.4)
        next(windows)
        windows.close()
        assert not camera.released
    finally:
        stream.close()
    assert camera.released


def test_the_sampling_loop_is_the_same_whoever_owns_the_camera(sources):
    """Splitting camera ownership out of the loop must not change what it
    samples, which benchmark.py's latency figures are measured against."""
    video, audio = sources
    owned = capture.run(video, audio, interval=0.3, window=1.0)
    try:
        by_run = next(owned)
    finally:
        owned.close()

    stream = capture.VideoStream(video)
    try:
        shared = capture.windows(stream, audio, interval=0.3, window=1.0)
        try:
            by_windows = next(shared)
        finally:
            shared.close()
    finally:
        stream.close()

    assert len(by_windows.frames) == len(by_run.frames)
    assert by_windows.index == by_run.index == 0


def test_audio_ring_keeps_the_most_recent_samples():
    ring = capture.AudioRing(samplerate=10, seconds=1.0)
    for start in (0, 6, 12):
        ring.add(np.arange(start, start + 6, dtype=np.float32))

    data = ring.read()
    assert len(data) == 10
    assert data[-1] == 17
    assert data[0] == 8


def test_audio_ring_is_empty_before_any_input():
    ring = capture.AudioRing(samplerate=10, seconds=1.0)
    assert len(ring.read()) == 0


def test_audio_ring_holds_short_input_whole():
    ring = capture.AudioRing(samplerate=10, seconds=1.0)
    ring.add(np.arange(4, dtype=np.float32))
    assert len(ring.read()) == 4


def test_encode_wav_produces_a_readable_mono_clip():
    tone = np.sin(np.linspace(0, 40 * np.pi, SAMPLERATE)).astype(np.float32)
    payload = capture.encode_wav(tone, SAMPLERATE)

    with wave.open(io.BytesIO(payload)) as handle:
        assert handle.getnchannels() == 1
        assert handle.getsampwidth() == 2
        assert handle.getframerate() == SAMPLERATE
        decoded = np.frombuffer(handle.readframes(handle.getnframes()), dtype=np.int16)

    assert len(decoded) == SAMPLERATE
    assert decoded.astype(np.float32) / 32767 == pytest.approx(tone, abs=1e-3)


def test_encode_wav_clips_rather_than_wrapping():
    loud = np.array([-4.0, 4.0], dtype=np.float32)
    payload = capture.encode_wav(loud, SAMPLERATE)

    with wave.open(io.BytesIO(payload)) as handle:
        decoded = np.frombuffer(handle.readframes(handle.getnframes()), dtype=np.int16)

    assert decoded.tolist() == [-32767, 32767]


def test_encode_jpeg_returns_jpeg_bytes():
    frame = np.zeros((8, 8, 3), dtype=np.uint8)
    payload = capture.encode_jpeg(frame)
    assert payload[:2] == b"\xff\xd8"
