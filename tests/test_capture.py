"""Capture buffering and the sampling loop, exercised without hardware."""

import io
import time
import wave

import cv2
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


def test_every_sampled_frame_is_annotated_before_encoding(sources):
    """The model's frames carry the names; an unmarked frame would leave it
    guessing who is who."""
    video, audio = sources
    marked = []

    def annotate(frame):
        marked.append(frame.shape)
        return np.full_like(frame, 255)

    stream = capture.VideoStream(video)
    windows = capture.windows(stream, audio, interval=0.3, window=1.0, annotate=annotate)
    try:
        first = next(windows)
    finally:
        windows.close()
        stream.close()

    # Recording goes on after the first window, so more frames may be marked.
    assert len(marked) >= len(first.frames)
    for still in first.frames:
        decoded = cv2.imdecode(np.frombuffer(still, np.uint8), cv2.IMREAD_COLOR)
        assert decoded.mean() > 250


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


def test_the_audio_buffer_hands_over_everything_since_the_last_take():
    buffer = capture.AudioBuffer()
    for start in (0, 6):
        buffer.add(np.arange(start, start + 6, dtype=np.float32))
    assert buffer.take().tolist() == list(range(12))
    assert len(buffer.take()) == 0


def test_windows_that_waited_are_merged_whole_with_the_usual_frame_count():
    at = capture.datetime(2026, 9, 28, 20, 0, 0)
    waiting = [capture.Window(index, at + capture.timedelta(seconds=5 * index),
                              at + capture.timedelta(seconds=5 * index + 5),
                              [bytes([index, still]) for still in range(3)],
                              capture.encode_wav(np.full(5 * 100, 0.1 * index), 100), 5.0)
               for index in range(3)]
    merged = capture.merge(waiting, frames=3)
    assert merged.audio_seconds == pytest.approx(15.0)
    assert merged.index == 2 and merged.started == waiting[0].started
    assert merged.frames == [bytes([0, 0]), bytes([1, 1]), bytes([2, 2])]


def test_a_backlog_beyond_its_limit_drops_the_oldest_sound():
    at = capture.datetime(2026, 9, 28, 20, 0, 0)
    waiting = [capture.Window(index, at, at + capture.timedelta(seconds=10),
                              [], capture.encode_wav(np.zeros(1000), 100), 10.0)
               for index in range(3)]
    assert capture.merge(waiting, frames=3, max_seconds=15).audio_seconds == pytest.approx(15.0)


def test_earlier_sound_is_put_in_front_and_the_window_keeps_its_end():
    at = capture.datetime(2026, 9, 28, 20, 0, 0)
    window = capture.Window(0, at, at + capture.timedelta(seconds=1), [],
                            capture.encode_wav(np.full(100, 0.5), 100), 1.0)
    joined = capture.prepend(np.full(50, -0.5, dtype=np.float32), window)
    samples, _ = capture.decode_wav(joined.audio)
    assert joined.audio_seconds == pytest.approx(1.5) and joined.ended == window.ended
    assert samples[0] < 0 < samples[-1]


def test_recording_does_not_pause_while_a_window_is_being_reported(sources):
    """A slow consumer gets the windows it missed, merged, rather than gaps."""
    video, audio = sources
    stream = capture.VideoStream(video)
    recorder = capture.Recorder(stream, audio, interval=0.1, window=0.3).start()
    try:
        first = recorder.next()
        time.sleep(1.0)                     # a report being made
        caught_up = recorder.next()
    finally:
        recorder.close()
        stream.close()
    assert first.index == 0
    assert caught_up.index >= 3
    assert caught_up.seconds >= 0.9


def test_closing_drops_everything_not_yet_handed_out(sources):
    video, audio = sources
    stream = capture.VideoStream(video)
    recorder = capture.Recorder(stream, audio, interval=0.1, window=0.2).start()
    try:
        time.sleep(0.7)
        recorder._buffer.add(np.zeros(10, dtype=np.float32))
        recorder.close()
        assert recorder.held == (0, 0)
        assert list(recorder) == []
    finally:
        stream.close()


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


def test_a_window_can_take_its_sound_from_an_ndi_source(sources, monkeypatch):
    """The NDI receiver fills the same buffer a microphone does."""
    video, _ = sources
    opened = []

    class FakeReceiving:
        def __init__(self, audio, add):
            opened.append(audio)
            self._add = add

        def __enter__(self):
            self._add(np.full(48000, 0.25, dtype=np.float32))
            return self

        def __exit__(self, *exception):
            return False

    monkeypatch.setattr(capture.ndi_audio, "Receiving", FakeReceiving)
    audio = capture.ndi_audio.NdiAudio("HOST (OBS PGM)")
    windows = capture.run(video, audio, interval=0.2, window=0.4)
    try:
        first = next(windows)
    finally:
        windows.close()

    assert opened == [audio]
    # All the sound the source delivered, at NDI's rate.
    assert first.audio_seconds == pytest.approx(1.0)
    with wave.open(io.BytesIO(first.audio)) as recorded:
        assert recorded.getframerate() == 48000
