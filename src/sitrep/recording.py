"""Recordings played into a run as if they were the room: picture and sound in real time.

Two uses. replay.py plays a test recording through a whole run to measure it.
A scene plays a pre-recorded video in place of the camera ("Pre-recorded" and
"Record-Feed Transition" under "Scene Configurations" in
knowledge/components/02_processing.md): the run reads a `Switch`, which
serves the camera's newest frame or the video's, and everything reading the
picture analyses the video as it would the room. While the video plays, its
sound replaces the microphone's.

The picture is decoded at its own pace and served as a camera's newest frame;
the sound is fed in real time, as a microphone delivers it. A video that has
ended holds its last frame and falls silent.
"""

import pathlib
import sys
import threading
import time

import cv2
import numpy as np
from faster_whisper.audio import decode_audio

from . import devices

# Sound is fed in chunks of this many seconds, about what a sound card hands over.
CHUNK = 0.02

# Sample rate a replayed recording's sound is decoded at.
SAMPLERATE = 48000.0


class Wiedergabe:
    """The playback's clock: where in the recording the room is now.

    It starts when the sound starts, so that picture and sound stay together
    however long the models take to load; until then the picture holds its
    first frame.
    """

    def __init__(self, start: float):
        self.start = start
        self._began: float | None = None

    def begin(self):
        if self._began is None:
            self._began = time.monotonic()

    @property
    def position(self) -> float:
        """Seconds into the recording."""
        return self.start + (0.0 if self._began is None else time.monotonic() - self._began)

    @property
    def elapsed(self) -> float:
        return self.position - self.start


class Bild:
    """The recording's picture, served as a camera's newest frame."""

    def __init__(self, path: pathlib.Path, uhr: Wiedergabe):
        self.device = devices.VideoDevice(-1, f"Aufnahme {path.name}")
        self._capture = cv2.VideoCapture(str(path))
        if not self._capture.isOpened():
            raise RuntimeError(f"Could not open {path}")
        self._capture.set(cv2.CAP_PROP_POS_MSEC, uhr.start * 1000)
        self._uhr = uhr
        ok, self._frame = self._capture.read()
        if not ok:
            raise RuntimeError(f"No picture in {path} at {uhr.start:g} s")
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._play, daemon=True)
        self._thread.start()

    def _play(self):
        while not self._stop.is_set():
            shown = self._capture.get(cv2.CAP_PROP_POS_MSEC) / 1000
            if shown >= self._uhr.position:
                self._stop.wait(0.005)
                continue
            ok, frame = self._capture.read()
            if not ok:
                return
            with self._lock:
                self._frame = frame

    def latest(self):
        with self._lock:
            return self._frame.copy()

    def close(self):
        self._stop.set()
        self._thread.join(timeout=2.0)
        self._capture.release()


class Ton:
    """The recording's sound, delivered in real time like a microphone's."""

    def __init__(self, path: pathlib.Path, uhr: Wiedergabe, dauer: float | None,
                 samplerate: float = SAMPLERATE):
        self.name = f"Aufnahme {path.name}"
        self.samplerate = samplerate
        self._uhr = uhr
        rate = int(samplerate)
        samples = decode_audio(str(path), sampling_rate=rate)
        first = int(uhr.start * rate)
        last = len(samples) if dauer is None else first + int(dauer * rate)
        self.samples = samples[first:last].astype(np.float32)
        self.seconds = len(self.samples) / rate

    def receiving(self, on_audio):
        """A context manager that feeds the sound to `on_audio` while entered
        (capture.listen)."""
        return _Feeding(self.samples, self.samplerate, self._uhr, on_audio)


class _Feeding:
    """Feeds samples to `on_audio` as the clock passes them, from entering on."""

    def __init__(self, samples: np.ndarray, samplerate: float, uhr: Wiedergabe, on_audio):
        self._samples = samples
        self._rate = int(samplerate)
        self._uhr = uhr
        self._on_audio = on_audio
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._feed, daemon=True)

    def __enter__(self):
        self._uhr.begin()
        self._thread.start()
        return self

    def _feed(self):
        fed = 0
        while not self._stop.is_set() and fed < len(self._samples):
            due = min(len(self._samples), int(self._uhr.elapsed * self._rate))
            if due > fed:
                self._on_audio(self._samples[fed:due])
                fed = due
            self._stop.wait(CHUNK)

    def __exit__(self, *exception):
        self._stop.set()
        self._thread.join(timeout=2.0)


class Recording:
    """A video file, played from its start each time it is asked for.

    The sound is decoded once, at the sample rate of the run's microphone, so
    it can take the microphone's place. A video without a sound track plays
    silent.
    """

    def __init__(self, path: pathlib.Path, samplerate: float):
        self.path = path
        self.samplerate = samplerate
        probe = cv2.VideoCapture(str(path))
        opened = probe.isOpened()
        probe.release()
        if not opened:
            raise RuntimeError(f"Video lässt sich nicht öffnen: {path}")
        try:
            self.samples = decode_audio(str(path), sampling_rate=int(samplerate)).astype(np.float32)
        except Exception as error:
            print(f"{path.name}: no sound decoded, playing silent: {error!r}", file=sys.stderr)
            self.samples = np.zeros(0, dtype=np.float32)

    def play(self, on_audio) -> "Playback":
        """Start the video from its beginning, its sound fed to `on_audio`."""
        return Playback(self, on_audio)


class Playback:
    """One playing of a recording: its picture as a camera's, its sound fed on."""

    def __init__(self, recording: Recording, on_audio):
        self.path = recording.path
        self.name = f"Aufnahme {recording.path.name}"
        uhr = Wiedergabe(0.0)
        self._bild = Bild(recording.path, uhr)
        self.device = self._bild.device
        self._feeding = _Feeding(recording.samples, recording.samplerate, uhr, on_audio)
        self._feeding.__enter__()

    def latest(self):
        return self._bild.latest()

    def close(self):
        self._feeding.__exit__(None, None, None)
        self._bild.close()


class Switch:
    """The picture a run reads: the camera's, or a recording's played in its place.

    Readers call `latest()` as they would a camera's; the source changes
    under them. Closing it closes the camera and any recording playing.
    """

    def __init__(self, camera):
        self.camera = camera
        self._playing: Playback | None = None
        self._lock = threading.Lock()

    @property
    def device(self) -> devices.VideoDevice:
        with self._lock:
            return (self._playing or self.camera).device

    @property
    def playing(self) -> Playback | None:
        with self._lock:
            return self._playing

    def latest(self):
        with self._lock:
            source = self._playing or self.camera
        return source.latest()

    def play(self, playback: Playback | None):
        """Show a playback in place of the camera, or the camera again with
        None. The playback shown before is closed."""
        with self._lock:
            previous, self._playing = self._playing, playback
        if previous is not None:
            previous.close()

    def close(self):
        self.play(None)
        self.camera.close()
