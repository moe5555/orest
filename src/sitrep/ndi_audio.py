"""Sound from an NDI source, in place of a microphone.

A rehearsal's sound may reach this machine as an NDI stream rather than an
audio device: OBS publishes its programme output over NDI (DistroAV), and so
can the Probebühne's cameras. Receiving it directly needs no virtual audio
device in between, such as NDI Webcam, whose source has to be chosen by hand.

The source is received on a thread of its own and delivered as mono float32
chunks to the same buffer a microphone fills (capture.AudioBuffer), so a
window's audio is the same whichever way the sound arrived.

    orest-sitrep --audio-ndi "VSH-ARLT-5090 (OBS PGM)"
"""

import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

# NDI carries audio at 48 kHz by convention, and OBS sends it at that rate. A
# source at another rate is resampled to it, so the buffer has one rate.
SAMPLERATE = 48000

# Seconds to look for the source before giving up. Discovery on a local
# machine takes one to two seconds.
FIND_TIMEOUT = 10.0

# Milliseconds one receive call waits for a frame, and so how quickly the
# receiving thread notices it has been asked to stop.
RECEIVE_MS = 200


@dataclass(frozen=True)
class NdiAudio:
    """An NDI source to take the room's sound from."""

    source: str
    samplerate: float = SAMPLERATE

    @property
    def name(self) -> str:
        return f"NDI {self.source}"


def mono(data: np.ndarray, rate: int) -> np.ndarray:
    """Channels (channels, samples) mixed down to one, at SAMPLERATE."""
    mixed = np.asarray(data, dtype=np.float32).mean(axis=0)
    if rate == SAMPLERATE or not len(mixed):
        return mixed
    length = round(len(mixed) * SAMPLERATE / rate)
    positions = np.linspace(0, len(mixed) - 1, length)
    return np.interp(positions, np.arange(len(mixed)), mixed).astype(np.float32)


class Receiving:
    """Receives an NDI source's audio and hands each chunk to `add` until closed.

    A context manager, as sounddevice's InputStream is, so capture.Recorder opens
    either the same way. Fails on entry if the source cannot be found.
    """

    def __init__(self, audio: NdiAudio, add: Callable[[np.ndarray], None]):
        self._audio = audio
        self._add = add
        self._stop = threading.Event()
        self._thread = None
        self._finder = None
        self._receiver = None

    def __enter__(self) -> "Receiving":
        from cyndilib.audio_frame import AudioRecvFrame
        from cyndilib.finder import Finder
        from cyndilib.receiver import Receiver
        from cyndilib.wrapper import RecvBandwidth, RecvColorFormat

        self._finder = Finder()
        self._finder.open()
        deadline = time.monotonic() + FIND_TIMEOUT
        source = None
        while source is None and time.monotonic() < deadline:
            source = self._finder.get_source(self._audio.source)
            if source is None:
                time.sleep(0.2)
        if source is None:
            found = ", ".join(self._finder.get_source_names()) or "none"
            self._finder.close()
            raise RuntimeError(f"NDI source {self._audio.source!r} not found "
                               f"(sources seen: {found}).")

        self._receiver = Receiver(color_format=RecvColorFormat.fastest,
                                  bandwidth=RecvBandwidth.audio_only)
        self._frame = AudioRecvFrame()
        self._receiver.set_audio_frame(self._frame)
        self._receiver.set_source(source)
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        return self

    def _loop(self):
        from cyndilib.receiver import ReceiveFrameType

        try:
            while not self._stop.is_set():
                received = self._receiver.receive(ReceiveFrameType.recv_audio, RECEIVE_MS)
                if received & ReceiveFrameType.recv_audio:
                    data, _ = self._frame.get_all_read_data()
                    self._add(mono(data, int(self._frame.sample_rate)))
        except Exception as error:
            # An exception on this thread reaches no caller; windows would
            # carry silence from here on, which the transcript shows as empty.
            print(f"NDI audio stopped: {error!r}", file=sys.stderr)

    def __exit__(self, *exception):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2.0)
        if self._receiver:
            self._receiver.disconnect()
        if self._finder:
            self._finder.close()
