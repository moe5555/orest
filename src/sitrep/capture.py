"""Capture loop: streams frames and audio windows as SITREP model input.

Implements step 3 of the Realtime-SITREP implementation steps in
knowledge/components/02_processing.md ("Capture one frame every x seconds"),
and buffers the matching audio so a window carries the material a SITREP
covers: several frames plus the sound recorded alongside them
(step 5, "Write SITREP report JSON format").

Nothing here is written to disk. A window holds encoded JPEG and WAV bytes,
handed straight to transcription and the model and then dropped; the raw A/V
recorder is a separate node in knowledge/source_of_truth/pipeline.md (REC,
feeding the rehearsal database), not part of the real-time path. The real-time
path retains nothing at all.

Frames are pulled continuously in the background and sampled from the newest
available data. A camera left idle keeps filling its buffer, and the next read
then returns whatever was queued rather than the current view of the room;
draining continuously keeps the sampled frame current, which 02_processing.md
asks for where it notes the Realtime-SITREP "prioritises low latency over
accuracy".

A `VideoStream` serves any number of readers, and `windows()` is the sampling
loop over one it does not own. DirectShow refuses a second process the camera,
so everything that watches the room during a rehearsal — this loop, the
presence tracker, the TouchDesigner feed — reads a single open stream.
`run()` is the standalone form that opens and closes a stream of its own.

Run directly to watch the capture loop without generating reports:

    python -m sitrep.capture --interval 5 --window 30
"""

import argparse
import io
import itertools
import math
import sys
import threading
import time
import wave
from collections import deque
from dataclasses import dataclass
from datetime import datetime

import cv2
import numpy as np
import sounddevice as sd

from . import cli, devices

# JPEG quality for sampled frames. High enough that compression artefacts do
# not reach the model, low enough to keep a window's payload small.
_JPEG_QUALITY = 90

# Delay before retrying a camera read that returned no frame.
_RETRY_SECONDS = 0.01

# How often the opening wait re-checks for the camera's first frame.
_FIRST_FRAME_POLL_SECONDS = 0.02


@dataclass(frozen=True)
class Window:
    """One SITREP interval: the frames sampled during it and its audio.

    Media is held in memory as encoded bytes, ready to hand to the model.
    """

    index: int
    started: datetime
    ended: datetime
    frames: list[bytes]
    audio: bytes
    audio_seconds: float

    @property
    def seconds(self) -> float:
        return (self.ended - self.started).total_seconds()


class VideoStream:
    """Reads a camera continuously so the newest frame is always available.

    A constructed stream has already delivered a frame, so latest() never
    returns nothing.
    """

    def __init__(self, device: devices.VideoDevice, width=None, height=None, timeout=5.0):
        # Kept so a caller sharing the stream can report which camera a run is
        # watching without holding the device alongside it.
        self.device = device
        self._capture = devices.open_video(device, width, height)
        self._frame = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._drain, daemon=True)
        self._thread.start()

        if not self._await_first_frame(timeout):
            self.close()
            raise RuntimeError(f"No frames from [{device.index}] {device.name!r}.")

    def _drain(self):
        while not self._stop.is_set():
            ok, frame = self._capture.read()
            if not ok:
                time.sleep(_RETRY_SECONDS)
                continue
            with self._lock:
                self._frame = frame

    def _await_first_frame(self, timeout: float) -> bool:
        # Cameras take up to a second to deliver after opening; sampling before
        # then would leave the first window a frame short.
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self._lock:
                if self._frame is not None:
                    return True
            time.sleep(_FIRST_FRAME_POLL_SECONDS)
        return False

    def latest(self):
        with self._lock:
            return self._frame.copy()

    def close(self):
        self._stop.set()
        self._thread.join(timeout=2.0)
        self._capture.release()


class AudioRing:
    """Fixed-duration rolling buffer of the most recent microphone input."""

    def __init__(self, samplerate: int, seconds: float):
        self.samplerate = samplerate
        self._capacity = int(samplerate * seconds)
        self._chunks = deque()
        self._samples = 0
        self._lock = threading.Lock()

    def add(self, chunk):
        with self._lock:
            self._chunks.append(chunk)
            self._samples += len(chunk)
            while self._chunks and self._samples - len(self._chunks[0]) >= self._capacity:
                self._samples -= len(self._chunks.popleft())

    def read(self):
        with self._lock:
            if not self._chunks:
                return np.zeros(0, dtype=np.float32)
            data = np.concatenate(list(self._chunks))
        return data[-self._capacity:]


def frames_per_window(window: float, interval: float) -> int:
    """How many frames run() samples in one window.

    Sampling starts at the top of the window and repeats every interval for as
    long as the window lasts, so a window always yields at least one frame.
    """
    return max(1, math.ceil(window / interval))


def encode_jpeg(frame) -> bytes:
    ok, buffer = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, _JPEG_QUALITY])
    if not ok:
        raise RuntimeError("JPEG encoding failed.")
    return buffer.tobytes()


def encode_wav(samples, samplerate: int) -> bytes:
    """Encode mono float samples as a 16-bit PCM WAV container."""
    pcm = (np.clip(samples, -1.0, 1.0) * 32767).astype(np.int16)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(samplerate)
        handle.writeframes(pcm.tobytes())
    return buffer.getvalue()


def windows(stream: VideoStream, audio: devices.AudioDevice, *,
            interval: float, window: float):
    """Sample an open camera and the microphone, one Window per interval.

    The stream is read, never opened or closed: its owner does that. This is
    what lets the presence tracker and the TouchDesigner feed read the same
    camera as the SITREP, which DirectShow would otherwise forbid by refusing
    a second process the device.

    Yields indefinitely; the caller decides how long a session runs.
    """
    samplerate = int(audio.samplerate)
    ring = AudioRing(samplerate, window)

    def on_audio(indata, frames, time_info, status):
        # Status flags mean dropped samples, which nothing downstream can see.
        if status:
            print(f"audio status: {status}", file=sys.stderr)
        ring.add(indata[:, 0].copy())

    def capture_window(index: int) -> Window:
        started = datetime.now()
        deadline = time.monotonic() + window
        next_sample = time.monotonic()
        frames = []

        while True:
            now = time.monotonic()
            if now >= deadline:
                break
            if now >= next_sample:
                frames.append(encode_jpeg(stream.latest()))
                next_sample += interval
                continue
            time.sleep(min(next_sample, deadline) - now)

        samples = ring.read()
        return Window(index, started, datetime.now(), frames,
                      encode_wav(samples, samplerate), len(samples) / samplerate)

    with sd.InputStream(device=audio.index, channels=1,
                        samplerate=samplerate, callback=on_audio):
        for index in itertools.count():
            yield capture_window(index)


def run(video: devices.VideoDevice, audio: devices.AudioDevice, *,
        interval: float, window: float, width=None, height=None):
    """Open a camera of this loop's own and sample it, releasing it at the end.

    The standalone form, for a caller with nothing else reading the camera.
    A session sharing one camera between several readers opens the stream
    itself and calls `windows()`.
    """
    stream = VideoStream(video, width, height)
    try:
        yield from windows(stream, audio, interval=interval, window=window)
    finally:
        stream.close()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__.splitlines()[0],
        parents=[cli.sources(), cli.timing(), cli.resolution()],
    )
    args = parser.parse_args(argv)

    try:
        video, audio = devices.resolve(args.video, args.audio, args.audio_api)
    except (ValueError, RuntimeError) as error:
        print(error, file=sys.stderr)
        return 1

    print(devices.describe(video, audio))
    print(f"sampling every {args.interval:g}s, window {args.window:g}s")

    windows = run(video, audio, interval=args.interval, window=args.window,
                  width=args.width, height=args.height)

    try:
        for captured in itertools.islice(windows, args.windows):
            payload = sum(len(f) for f in captured.frames) + len(captured.audio)
            print(
                f"window {captured.index}: {len(captured.frames)} frames, "
                f"{captured.audio_seconds:.1f}s audio, "
                f"{payload / 1024:.0f} KiB, {captured.seconds:.1f}s"
            )
    except KeyboardInterrupt:
        print()
    except (ValueError, RuntimeError) as error:
        print(error, file=sys.stderr)
        return 1
    finally:
        windows.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
