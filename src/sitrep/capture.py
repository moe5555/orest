"""Capture loop: streams frames and audio windows as SITREP model input.

Implements step 3 of the Realtime-SITREP implementation steps in
knowledge/components/02_processing.md ("Capture one frame every x seconds"),
and buffers the matching audio so a window carries the material a SITREP
covers: several frames plus the sound recorded alongside them
(step 5, "Write SITREP report JSON format").

Nothing here is written to disk. A window holds encoded JPEG and WAV bytes and
is handed straight to the model; the raw A/V recorder is a separate node in
knowledge/source_of_truth/pipeline.md (REC, feeding the rehearsal database),
not part of the real-time path. Only the SITREP text is logged, by report.py.

Frames are pulled continuously in the background and sampled from the newest
available data. A camera left idle keeps filling its buffer, and the next read
then returns whatever was queued rather than the current view of the room;
draining continuously keeps the sampled frame current, which 02_processing.md
asks for where it notes the Realtime-SITREP "prioritises low latency over
accuracy".

Run directly to watch the capture loop without generating reports:

    python src/sitrep/capture.py --interval 5 --window 30
"""

import argparse
import io
import itertools
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

import devices

# JPEG quality for sampled frames. High enough that compression artefacts do
# not reach the model, low enough to keep a window's payload small.
_JPEG_QUALITY = 90

# How often the sampling loop checks whether the next frame is due.
_POLL_SECONDS = 0.01

# The model's audio encoder works in 30-second chunks. A clip whose length
# lands on a chunk boundary, or a hair past one, leaves a final chunk with no
# usable samples and the request fails with "Failed to tokenize prompt".
# Measured on gemma4:e4b: 29.99998s and 30.01s are accepted, 30.0s and
# 30.00002s are not. Clips are trimmed clear of the boundary.
_ENCODER_CHUNK_SECONDS = 30
_BOUNDARY_MARGIN_SECONDS = 0.05


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
                time.sleep(_POLL_SECONDS)
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
            time.sleep(0.02)
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


def encode_jpeg(frame) -> bytes:
    ok, buffer = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, _JPEG_QUALITY])
    if not ok:
        raise RuntimeError("JPEG encoding failed.")
    return buffer.tobytes()


def clip_for_encoder(samples, samplerate: int):
    """Shorten a clip that ends too close to an audio encoder chunk boundary."""
    margin = int(_BOUNDARY_MARGIN_SECONDS * samplerate)
    remainder = len(samples) % (_ENCODER_CHUNK_SECONDS * samplerate)
    if remainder < margin:
        return samples[: len(samples) - margin]
    return samples


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


def run(video_spec=None, audio_spec=None, hostapi=None,
        interval=5.0, window=30.0, width=None, height=None):
    """Sample frames and audio, yielding one Window per SITREP interval.

    Yields indefinitely; the caller decides how long a session runs.
    """
    video_device = devices.resolve_video_device(video_spec)
    audio_device = devices.resolve_audio_device(audio_spec, hostapi)
    samplerate = int(audio_device.samplerate)

    print(f"video:  [{video_device.index}] {video_device.name}")
    print(f"audio:  [{audio_device.index}] {audio_device.name} ({audio_device.hostapi})")
    print(f"sampling every {interval:g}s, window {window:g}s")

    ring = AudioRing(samplerate, window)

    def on_audio(indata, frames, time_info, status):
        # Status flags mean dropped samples, which nothing downstream can see.
        if status:
            print(f"audio status: {status}", file=sys.stderr)
        ring.add(indata[:, 0].copy())

    stream = VideoStream(video_device, width, height)

    def capture_window(index: int) -> Window:
        started = datetime.now()
        deadline = time.monotonic() + window
        next_sample = time.monotonic()
        frames = []

        while time.monotonic() < deadline:
            if time.monotonic() >= next_sample:
                frames.append(encode_jpeg(stream.latest()))
                next_sample += interval
            time.sleep(_POLL_SECONDS)

        samples = clip_for_encoder(ring.read(), samplerate)
        return Window(index, started, datetime.now(), frames,
                      encode_wav(samples, samplerate), len(samples) / samplerate)

    try:
        with sd.InputStream(device=audio_device.index, channels=1,
                            samplerate=samplerate, callback=on_audio):
            for index in itertools.count():
                yield capture_window(index)
    finally:
        stream.close()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--video", help="camera index or name fragment")
    parser.add_argument("--audio", help="microphone index or name fragment")
    parser.add_argument("--audio-api", help="host API filter, e.g. WASAPI, MME")
    parser.add_argument("--interval", type=float, default=5.0,
                        help="seconds between sampled frames (default: 5)")
    parser.add_argument("--window", type=float, default=30.0,
                        help="seconds per SITREP window (default: 30)")
    parser.add_argument("--width", type=int, help="requested capture width")
    parser.add_argument("--height", type=int, help="requested capture height")
    parser.add_argument("--windows", type=int, help="stop after this many windows")
    args = parser.parse_args(argv)

    windows = run(
        video_spec=args.video,
        audio_spec=args.audio,
        hostapi=args.audio_api,
        interval=args.interval,
        window=args.window,
        width=args.width,
        height=args.height,
    )

    try:
        for captured in itertools.islice(windows, args.windows):
            payload = sum(len(f) for f in captured.frames) + len(captured.audio)
            print(
                f"window {captured.index}: {len(captured.frames)} frames, "
                f"{captured.audio_seconds:.1f}s audio, "
                f"{payload / 1024:.0f} KiB, {captured.seconds:.1f}s"
            )
    except KeyboardInterrupt:
        print("\nstopped")
    except (ValueError, RuntimeError) as error:
        print(error, file=sys.stderr)
        return 1
    finally:
        windows.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
