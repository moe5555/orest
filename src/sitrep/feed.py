"""The live camera as an NDI source, for TouchDesigner to display.

The pixel half of the two-channel interface in
knowledge/components/03_render.md: "OSC carries messages, not pixels." Stored
footage reaches TouchDesigner as cut clips on disk; live frames reach it as a
video stream, which that file names as Spout or NDI.

NDI rather than Spout because Orest runs on Python 3.14, for which SpoutGL
publishes no wheel; rather than TouchDesigner's own shared memory because that
operator requires a licence above Non-Commercial. TouchDesigner receives with
its native NDI In TOP and needs no addition to run.

The publisher reads the shared camera and never opens or closes it, the same
contract the presence tracker keeps. It sends the newest drained frame at its
own rate, independent of the SITREP window: a camera that stalls leaves
TouchDesigner holding the last frame, which the operator can see on stage.

Nothing is written to disk; the real-time path retains nothing
(changelog.md, 2026-09-10).
"""

import os
import threading
import time
from collections.abc import Callable
from fractions import Fraction

import cv2
import numpy as np

# Name TouchDesigner's NDI In TOP lists this source under. A rehearsal may run
# more than one machine, and sources are chosen by name.
NAME = os.environ.get("OREST_NDI_NAME", "Orest SITREP")

# Frames per second sent. Independent of the camera's rate and of the SITREP
# interval; the publisher always sends the newest frame the stream has drained.
FPS = float(os.environ.get("OREST_NDI_FPS", "30"))


def bgrx(frame: np.ndarray) -> np.ndarray:
    """Pack an OpenCV BGR frame into the flat BGRX buffer NDI sends.

    BGRX is the format that costs a single conversion from OpenCV's native BGR;
    RGBA or UYVY would each add a channel swap or a colour-space conversion on
    every frame. The X byte is ignored by the receiver, so no alpha is computed.
    """
    return cv2.cvtColor(frame, cv2.COLOR_BGR2BGRA).reshape(-1)


class Sink:
    """An NDI source frames are written to.

    Wraps cyndilib so that the transport is one class. TouchDesigner's shared
    memory, or an ffmpeg process serving SRT, would substitute here without
    anything above this line changing.
    """

    def __init__(self, name: str, width: int, height: int, fps: float):
        from cyndilib.sender import Sender
        from cyndilib.video_frame import VideoSendFrame
        from cyndilib.wrapper.ndi_structs import FourCC

        self._frame = VideoSendFrame()
        self._frame.set_resolution(width, height)
        # NDI declares frame rate as a ratio, so that 29.97 travels exactly.
        self._frame.set_frame_rate(Fraction(fps).limit_denominator(1001))
        self._frame.set_fourcc(FourCC.BGRX)

        self._sender = Sender(name)
        self._sender.set_video_frame(self._frame)
        self._sender.open()

    def send(self, buffer: np.ndarray):
        self._sender.write_video(buffer)

    def receivers(self) -> int:
        """How many receivers are connected, TouchDesigner among them."""
        return self._sender.get_num_connections(0)

    def close(self):
        self._sender.close()


def open_sink(name: str, width: int, height: int, fps: float) -> Sink:
    """Open an NDI source TouchDesigner can receive.

    Imported here rather than at module scope so that nothing pays for the NDI
    library unless a run asks to publish, as smartsearch does with the pose
    model. A missing package and a missing NDI runtime surface differently and
    are reported the same way, since the fix is the same kind of install.
    """
    try:
        return Sink(name, width, height, fps)
    except (ImportError, OSError) as error:
        raise RuntimeError(
            f"Could not open the NDI source {name!r}: {error}. "
            f"Install the publisher with `uv pip install cyndilib`; if that is "
            f"present, the NDI runtime is missing."
        ) from error


class Publisher:
    """Sends the newest camera frame to TouchDesigner as an NDI source.

    The source is anything with a `latest()` returning the current BGR frame,
    which is how capture.VideoStream presents the camera. The publisher never
    opens or closes the source.
    """

    def __init__(self, source, *, name: str = NAME, fps: float = FPS,
                 sink: Callable[[str, int, int, float], Sink] = open_sink):
        self._source = source
        self._open_sink = sink
        self.name = name
        self.fps = fps
        self.sink = None
        self._stop = threading.Event()
        self._thread = None
        self.frames = 0
        self.durations: list[float] = []

    def start(self) -> "Publisher":
        """Open the sink at the camera's resolution, then begin sending.

        The resolution is read now rather than on the first frame: a
        constructed VideoStream has already delivered one, so a sink that
        cannot be opened fails before the run begins rather than during it.
        """
        height, width = self._source.latest().shape[:2]
        self.sink = self._open_sink(self.name, width, height, self.fps)
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        return self

    def _loop(self):
        interval = 1.0 / self.fps
        while not self._stop.is_set():
            started = time.monotonic()
            self.publish(self._source.latest())
            self.durations.append(time.monotonic() - started)
            self._stop.wait(max(0.0, interval - (time.monotonic() - started)))

    def publish(self, frame):
        """Send one frame. Public, so a caller can step the publisher by hand."""
        self.sink.send(bgrx(frame))
        self.frames += 1

    def close(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5.0)
        if self.sink:
            self.sink.close()
            self.sink = None

    def __enter__(self) -> "Publisher":
        return self.start()

    def __exit__(self, *exception):
        self.close()
