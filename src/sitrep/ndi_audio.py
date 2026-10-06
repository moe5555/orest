"""Sound from an NDI source, in place of a microphone.

A rehearsal's sound may reach this machine as an NDI stream rather than an
audio device: OBS publishes its programme output over NDI (DistroAV), and so
can the Probebühne's cameras. Receiving it directly needs no virtual audio
device in between, such as NDI Webcam, whose source has to be chosen by hand.

The source is received in a child process (`Receiving` says why) and
delivered as mono float32 chunks to whatever a microphone's sound goes to
(capture.listen), so the run is the same whichever way the sound arrived.

    apollon-sitrep --audio-ndi "VSH-ARLT-5090 (OBS PGM)"
"""

import multiprocessing
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
# receiving process notices it has been asked to stop. With this wait NDI
# reported no dropped frame (2026-09-29); waits of 1-20 ms received fewer.
RECEIVE_MS = 200

# Seconds allowed for the receiving process to start and import cyndilib,
# on top of FIND_TIMEOUT.
START_TIMEOUT = 20.0


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


def _receive(source_name: str, conn, stop):
    """The child process: find the source, then send its sound as mono float32 bytes.

    The first message is "ok", or the error that stopped the search. A receive
    call waits for its frame holding the child's interpreter lock, which here
    blocks nothing else.
    """
    from cyndilib.audio_frame import AudioRecvFrame
    from cyndilib.finder import Finder
    from cyndilib.receiver import Receiver, ReceiveFrameType
    from cyndilib.wrapper import RecvBandwidth, RecvColorFormat

    finder = Finder()
    finder.open()
    receiver = None
    try:
        deadline = time.monotonic() + FIND_TIMEOUT
        source = None
        while source is None and time.monotonic() < deadline:
            source = finder.get_source(source_name)
            if source is None:
                time.sleep(0.2)
        if source is None:
            found = ", ".join(finder.get_source_names()) or "none"
            conn.send(f"NDI source {source_name!r} not found (sources seen: {found}).")
            return
        receiver = Receiver(color_format=RecvColorFormat.fastest,
                            bandwidth=RecvBandwidth.audio_only)
        frame = AudioRecvFrame()
        receiver.set_audio_frame(frame)
        receiver.set_source(source)
        conn.send("ok")
        while not stop.is_set():
            if receiver.receive(ReceiveFrameType.recv_audio, RECEIVE_MS) & ReceiveFrameType.recv_audio:
                data, _ = frame.get_all_read_data()
                conn.send_bytes(mono(data, int(frame.sample_rate)).astype(np.float32).tobytes())
    except (BrokenPipeError, EOFError, OSError):
        # The parent is gone or has stopped listening.
        pass
    finally:
        if receiver is not None:
            receiver.disconnect()
        finder.close()


class Receiving:
    """An NDI source's audio, handed to `add` as mono float32 chunks while entered.

    A context manager, as sounddevice's InputStream is, so capture.listen
    opens either the same way. Fails on entry if the source cannot be found.

    The source is received in a child process. cyndilib holds Python's
    interpreter lock while a receive call waits for a frame: received on a
    thread of the run's own process, every other thread woke about 40 times
    a second instead of 600, and the live SITREP's speech fell ever further
    behind (2026-09-29). Shorter waits freed the lock but lost frames. The
    child keeps the long wait; a thread here reads what it sends, and waiting
    on the pipe releases the lock.
    """

    def __init__(self, audio: NdiAudio, add: Callable[[np.ndarray], None]):
        self._audio = audio
        self._add = add
        self._stop = None
        self._process = None
        self._conn = None
        self._thread = None
        self._closing = threading.Event()

    def __enter__(self) -> "Receiving":
        context = multiprocessing.get_context("spawn")
        self._conn, child = context.Pipe(duplex=False)
        self._stop = context.Event()
        self._process = context.Process(target=_receive, args=(self._audio.source, child, self._stop),
                                        daemon=True)
        self._process.start()
        child.close()
        # The child's start, imports and source search.
        if not self._conn.poll(FIND_TIMEOUT + START_TIMEOUT):
            self._shutdown()
            raise RuntimeError(f"NDI source {self._audio.source!r}: no answer from the receiver.")
        answer = self._conn.recv()
        if answer != "ok":
            self._shutdown()
            raise RuntimeError(answer)
        self._thread = threading.Thread(target=self._read, daemon=True)
        self._thread.start()
        return self

    def _read(self):
        try:
            while not self._closing.is_set():
                if self._conn.poll(0.2):
                    self._add(np.frombuffer(self._conn.recv_bytes(), dtype=np.float32))
        except (EOFError, OSError) as error:
            if not self._closing.is_set():
                # Reaches no caller: the run's sound stops here, which the
                # silence warning then shows (session.Ton).
                print(f"NDI audio stopped: {error!r}", file=sys.stderr)

    def _shutdown(self):
        self._closing.set()
        if self._stop is not None:
            self._stop.set()
        if self._process is not None:
            self._process.join(timeout=2.0)
            if self._process.is_alive():
                self._process.terminate()
        if self._conn is not None:
            self._conn.close()

    def __exit__(self, *exception):
        self._closing.set()
        if self._thread:
            self._thread.join(timeout=2.0)
        self._shutdown()
