"""One live run: the camera and microphone, and everything reading them.

DirectShow refuses a second process the camera (devices.open_video), so
everything that watches the room during a rehearsal has to read one open
stream. A session opens it once and hands it to the sampling loop that feeds
the model, to the presence tracker that follows faces, and to the publisher
that sends the picture to TouchDesigner. None of the three opens or closes it.

The session is also the shape the localhost interface of
knowledge/components/02_processing.md needs: one object to start and one to
stop, holding everything a run consists of. main.py drives it from the command
line today; an HTTP service would hold the same object.

Nothing is written to disk. The real-time path retains nothing
(changelog.md, 2026-09-10), and neither NDI nor OSC is a file.
"""

import pathlib
from collections.abc import Iterator

from face import gallery
from pydantic import BaseModel

from . import capture, cli, devices, feed, presence, report, td


class Options(BaseModel):
    """Everything a run is configured with, from a command line or a request.

    A model rather than keyword arguments because the localhost interface will
    receive exactly this as its request body, and pydantic is already how the
    package describes a document (report.Sitrep).
    """

    interval: float = cli.INTERVAL
    window: float = cli.WINDOW
    width: int | None = None
    height: int | None = None
    model: str = report.MODEL

    # Enrolment folder. Given one, the session follows faces and can name them.
    cast: pathlib.Path | None = None

    # Publish the camera to TouchDesigner under this NDI source name.
    ndi: str | None = None
    ndi_fps: float = feed.FPS

    # Announce each report, and the roster when a tracker is running, over OSC.
    send_td: bool = False

    @classmethod
    def from_args(cls, args) -> "Options":
        """Read the options a parser built by cli.py produced."""
        return cls(
            interval=args.interval,
            window=args.window,
            width=args.width,
            height=args.height,
            model=args.model,
            cast=args.cast,
            ndi=args.ndi_name if args.send_ndi else None,
            ndi_fps=args.ndi_fps,
            send_td=args.send_td,
        )


class Session:
    """A run in progress: one camera, one microphone, and their readers.

    Constructing one starts everything; closing it stops everything in the
    reverse order, so no reader can sample a camera that has been released.
    """

    def __init__(self, video: devices.VideoDevice, audio: devices.AudioDevice,
                 options: Options | None = None):
        self.options = options or Options()
        self.audio = audio
        self.stream = capture.VideoStream(video, self.options.width, self.options.height)
        self.publisher = None
        self.tracker = None
        self.sender = None
        self.roster = None
        self.missing_enrolment: list[pathlib.Path] = []
        self._closed = False

        # A part that fails after the camera is open would otherwise leave it
        # held by a session nobody has a handle to, and the next run could not
        # acquire it without restarting the process.
        try:
            self._start_readers()
        except BaseException:
            self.close()
            raise

    def _start_readers(self):
        if self.options.ndi:
            self.publisher = feed.Publisher(
                self.stream, name=self.options.ndi, fps=self.options.ndi_fps).start()

        if self.options.cast:
            cast, self.missing_enrolment = gallery.enrol(self.options.cast)
            self.tracker = presence.PresenceTracker(self.stream, cast).start()

        if self.options.send_td:
            self.sender = td.Sender()
            if self.tracker:
                self.roster = td.RosterStream(self.sender, self.tracker).start()

    def reports(self) -> Iterator[report.Sitrep]:
        """Yield one SITREP per window, announcing each over OSC when asked to.

        The report number is supplied here rather than carried on the document:
        it counts reports within a run, which is a property of the session and
        not of what was observed.
        """
        windows = capture.windows(self.stream, self.audio,
                                  interval=self.options.interval,
                                  window=self.options.window)
        try:
            for number, document in enumerate(
                    report.sitreps(windows, model=self.options.model), start=1):
                if self.sender:
                    self.sender.send_all(td.messages(document, number))
                yield document
        finally:
            windows.close()

    def close(self):
        """Stop every reader, then release the camera.

        Idempotent: a run has two plausible closers, the command line's context
        manager and a later stop request, and both may arrive.
        """
        if self._closed:
            return
        self._closed = True
        for reader in (self.roster, self.publisher, self.tracker):
            if reader:
                reader.close()
        self.stream.close()

    def describe(self) -> str:
        """The channels this run is using, for the operator to read at startup."""
        lines = [devices.describe(self.stream.device, self.audio)]
        if self.publisher:
            lines.append(f"ndi:    {self.options.ndi} @ {self.options.ndi_fps:g} fps")
        if self.sender:
            lines.append(f"osc:    {self.sender.host}:{self.sender.port}")
        if self.tracker:
            names = ", ".join(self.tracker.cast.names)
            lines.append(f"cast:   {names}")
        return "\n".join(lines)

    def __enter__(self) -> "Session":
        return self

    def __exit__(self, *exception):
        self.close()
