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
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

import cv2
import numpy as np
import sounddevice as sd

from . import cli, devices, ndi_audio

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


class AudioBuffer:
    """Everything the microphone delivered since the buffer was last emptied.

    Windows are cut from it back to back, so no sound falls between two
    windows, however long a report takes to make.
    """

    def __init__(self):
        self._chunks: list[np.ndarray] = []
        self._lock = threading.Lock()

    def add(self, chunk):
        with self._lock:
            self._chunks.append(chunk)

    def take(self) -> np.ndarray:
        """All samples since the last take, emptying the buffer."""
        with self._lock:
            chunks, self._chunks = self._chunks, []
        return np.concatenate(chunks) if chunks else np.zeros(0, dtype=np.float32)

    def clear(self):
        with self._lock:
            self._chunks = []

    def __len__(self) -> int:
        with self._lock:
            return sum(len(chunk) for chunk in self._chunks)


def listen(audio: devices.AudioDevice | ndi_audio.NdiAudio, on_audio: Callable[[np.ndarray], None]):
    """A microphone or an NDI source's sound, handing each chunk of mono float
    samples to `on_audio` as it arrives. A context manager: sound flows while
    it is entered.

    A source that delivers its sound itself, such as a recording replayed
    (replay.py), provides `receiving(on_audio)`."""
    if isinstance(audio, ndi_audio.NdiAudio):
        return ndi_audio.Receiving(audio, on_audio)
    if hasattr(audio, "receiving"):
        return audio.receiving(on_audio)

    def callback(indata, frames, time_info, status):
        # Status flags mean dropped samples, which nothing downstream can see.
        if status:
            print(f"audio status: {status}", file=sys.stderr)
        on_audio(indata[:, 0].copy())

    return sd.InputStream(device=audio.index, channels=1,
                          samplerate=int(audio.samplerate), callback=callback)


@dataclass(frozen=True)
class Still:
    """One sampled frame, encoded for the model, and when it was taken."""

    at: datetime
    jpeg: bytes


class FrameRing:
    """Frames sampled every interval and kept for the last `keep` seconds.

    The stills the model is shown come from here: the summary of each stretch
    of the scene (chronik.py) and a report asked for (session.py) take the
    ones taken during the time they cover. `annotate` marks each frame before
    it is encoded, which is how the names of the people in it reach the model
    (annotate.py). Nothing is written to disk.
    """

    def __init__(self, stream: VideoStream, *, interval: float, keep: float,
                 annotate: Callable[[np.ndarray], np.ndarray] | None = None):
        self._stream = stream
        self._interval = interval
        self._keep = timedelta(seconds=keep)
        self._annotate = annotate
        self._stills: deque[Still] = deque()
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None

    def start(self) -> "FrameRing":
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        return self

    def _loop(self):
        while not self._stop.is_set():
            started = time.monotonic()
            self.sample()
            self._stop.wait(max(0.0, self._interval - (time.monotonic() - started)))

    def sample(self, at: datetime | None = None):
        """Take one still now. Public, so a caller can step the ring by hand."""
        frame = self._stream.latest()
        still = Still(at or datetime.now(),
                      encode_jpeg(self._annotate(frame) if self._annotate else frame))
        with self._lock:
            self._stills.append(still)
            while self._stills and still.at - self._stills[0].at > self._keep:
                self._stills.popleft()

    def between(self, begins: datetime, ends: datetime, count: int) -> list[bytes]:
        """At most `count` stills taken in a stretch, spread evenly, the last one included."""
        with self._lock:
            found = [still.jpeg for still in self._stills if begins <= still.at <= ends]
        if len(found) <= count:
            return found
        return [found[round(position)] for position in np.linspace(0, len(found) - 1, count)]

    def clear(self):
        with self._lock:
            self._stills.clear()

    def close(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5.0)


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


def decode_wav(wav: bytes) -> tuple[np.ndarray, int]:
    """Mono float samples and their rate, from encode_wav's container."""
    with wave.open(io.BytesIO(wav)) as handle:
        rate = handle.getframerate()
        pcm = np.frombuffer(handle.readframes(handle.getnframes()), dtype=np.int16)
    return pcm.astype(np.float32) / 32767, rate


def prepend(samples: np.ndarray, window: Window) -> Window:
    """The window with earlier sound in front of its own.

    The window keeps its end, so its audio now begins that much earlier
    (report.py places sound in time from the window's end).
    """
    own, rate = decode_wav(window.audio)
    joined = np.concatenate([samples, own])
    return Window(window.index, window.started, window.ended, window.frames,
                  encode_wav(joined, rate), len(joined) / rate)


# Seconds of recording that may wait for a report. Further behind, the oldest
# sound is dropped, so that a stalled model cannot make memory grow without
# bound or reports fall ever further behind the room.
MAX_BACKLOG = 60.0


def merge(waiting: list[Window], frames: int, max_seconds: float = MAX_BACKLOG) -> Window:
    """Windows that waited for a report, as one.

    The sound is joined whole, up to `max_seconds`; of the frames, `frames`
    are kept, spread evenly, so the model is shown as many stills as usual.
    """
    if len(waiting) == 1:
        return waiting[0]
    parts = [decode_wav(window.audio) for window in waiting]
    rate = parts[0][1]
    samples = np.concatenate([part for part, _ in parts])
    started = waiting[0].started
    if len(samples) > max_seconds * rate:
        dropped = len(samples) / rate - max_seconds
        print(f"reports {dropped:.0f}s behind the room: oldest sound dropped", file=sys.stderr)
        samples = samples[-int(max_seconds * rate):]
        started = waiting[-1].ended - timedelta(seconds=max_seconds)
    stills = [still for window in waiting for still in window.frames]
    if len(stills) > frames:
        stills = [stills[round(position)]
                  for position in np.linspace(0, len(stills) - 1, frames)]
    return Window(waiting[-1].index, started, waiting[-1].ended, stills,
                  encode_wav(samples, rate), len(samples) / rate)


class Closed(Exception):
    """The recorder was closed while a window was awaited."""


class Recorder:
    """Records windows back to back on its own thread, while reports are made.

    Recording never pauses for a report: sound is cut into windows without a
    gap, and frames are sampled every interval throughout. A report takes the
    windows that have waited for it, merged into one (`merge`), so it catches
    up rather than falling behind window by window.

    The stream is read, never opened or closed: its owner does that. This is
    what lets the presence tracker and the TouchDesigner feed read the same
    camera as the SITREP, which DirectShow would otherwise forbid by refusing
    a second process the device.

    `annotate` marks each sampled frame before it is encoded, which is how the
    names of the people in it reach the model (annotate.py).

    Nothing is written to disk. Closing drops every window still waiting and
    the sound not yet cut, at once.
    """

    def __init__(self, stream: VideoStream, audio: devices.AudioDevice | ndi_audio.NdiAudio, *,
                 interval: float, window: float,
                 annotate: Callable[[np.ndarray], np.ndarray] | None = None):
        self._stream = stream
        self._audio = audio
        self._interval = interval
        self._window = window
        self._annotate = annotate
        self._frames = frames_per_window(window, interval)
        self._samplerate = int(audio.samplerate)
        self._buffer = AudioBuffer()
        self._waiting: deque[Window] = deque()
        self._ready = threading.Condition()
        self._stop = threading.Event()
        self._error: Exception | None = None
        self._thread = None

    def start(self) -> "Recorder":
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        return self

    def _loop(self):
        try:
            with listen(self._audio, self._buffer.add):
                for index in itertools.count():
                    captured = self._record(index)
                    if captured is None:
                        return
                    with self._ready:
                        self._waiting.append(captured)
                        self._ready.notify()
        except Exception as error:
            # Raised to whoever awaits the next window, e.g. an NDI source
            # that cannot be found.
            with self._ready:
                self._error = error
                self._ready.notify()

    def _record(self, index: int) -> Window | None:
        started = datetime.now()
        deadline = time.monotonic() + self._window
        next_sample = time.monotonic()
        frames = []
        while not self._stop.is_set():
            now = time.monotonic()
            if now >= deadline:
                samples = self._buffer.take()
                return Window(index, started, datetime.now(), frames,
                              encode_wav(samples, self._samplerate),
                              len(samples) / self._samplerate)
            if now >= next_sample:
                frame = self._stream.latest()
                frames.append(encode_jpeg(self._annotate(frame) if self._annotate else frame))
                next_sample += self._interval
                continue
            self._stop.wait(min(next_sample, deadline) - now)
        return None

    def next(self) -> Window:
        """Every window recorded since the last call, merged; waits for one."""
        with self._ready:
            while not self._waiting and self._error is None and not self._stop.is_set():
                self._ready.wait(0.1)
            if self._error is not None:
                raise self._error
            if not self._waiting:
                raise Closed()
            waiting = list(self._waiting)
            self._waiting.clear()
        return merge(waiting, self._frames)

    def __iter__(self):
        while True:
            try:
                yield self.next()
            except Closed:
                return

    @property
    def held(self) -> tuple[int, int]:
        """Windows waiting and audio samples not yet cut: what closing drops."""
        with self._ready:
            return len(self._waiting), len(self._buffer)

    def close(self):
        """Stop recording and drop everything not yet handed out."""
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5.0)
        with self._ready:
            self._waiting.clear()
            self._ready.notify_all()
        self._buffer.clear()


def windows(stream: VideoStream, audio: devices.AudioDevice | ndi_audio.NdiAudio, *,
            interval: float, window: float,
            annotate: Callable[[np.ndarray], np.ndarray] | None = None):
    """Windows from a Recorder, closed with the generator.

    Yields indefinitely; the caller decides how long a session runs.
    """
    recorder = Recorder(stream, audio, interval=interval, window=window,
                        annotate=annotate).start()
    try:
        yield from recorder
    finally:
        recorder.close()


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
