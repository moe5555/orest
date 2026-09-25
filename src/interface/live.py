"""The live SITREP run behind the interface.

At most one run exists at a time: there is one camera, and DirectShow gives it
to one process (sitrep/session.py). The run lives on a thread of its own,
because a session yields a report only once per window and generation blocks,
while the web server has to keep answering the page in the meantime.

The page is fed from a snapshot rather than from the session directly: status,
the latest report and a version number that rises with every change, so a page
polling or streaming the state knows whether anything is new.
"""

import threading
from collections.abc import Callable
from datetime import datetime

from sitrep import report, session

# Run states, as the page shows them.
IDLE, STARTING, RUNNING, STOPPING, ERROR = "idle", "starting", "running", "stopping", "error"


def payload(document: report.Sitrep, nummer: int) -> dict:
    """A report as the page renders it.

    The document as JSON, plus what the page cannot work out for itself: the
    report's number within the run, which names are guesses, and the
    threshold the scene ratings are read against.
    """
    rendered = document.model_dump(mode="json")
    rendered["nummer"] = nummer
    rendered["schwelle"] = report.SCHWELLE
    for person in rendered["bericht"]["personen"]:
        person["vermutet"] = (person["name"] != report.UNBEKANNT
                              and not document.erkannt(person["name"]))
    return rendered


class LiveSitrep:
    """Starts, stops and observes the one live SITREP run.

    `open_session` builds the session when a run starts, so that the devices
    are resolved and opened on the operator's request rather than at server
    start, and a missing camera shows on the page instead of in a terminal.
    """

    def __init__(self, open_session: Callable[[], session.Session]):
        self._open_session = open_session
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None
        self.session: session.Session | None = None
        self.status = IDLE
        self.error: str | None = None
        self.report: dict | None = None
        self.started: datetime | None = None
        self.version = 0

    def start(self) -> bool:
        """Begin a run. Returns False if one is already under way."""
        with self._lock:
            if self.status in (STARTING, RUNNING, STOPPING):
                return False
            self._stop = threading.Event()
            self.status, self.error, self.report = STARTING, None, None
            self.started = datetime.now()
            self.version += 1
            self._thread = threading.Thread(target=self._run, args=(self._stop,),
                                            daemon=True)
            self._thread.start()
            return True

    def _run(self, stop: threading.Event):
        try:
            run = self._open_session()
        except Exception as error:
            self._finish(ERROR, error)
            return

        with self._lock:
            if stop.is_set():
                run.close()
                self._finish_locked(IDLE, None)
                return
            self.session = run
            self.status = RUNNING
            self.version += 1

        try:
            for nummer, document in enumerate(run.reports(), start=1):
                if stop.is_set():
                    break
                with self._lock:
                    self.report = payload(document, nummer)
                    self.version += 1
        except Exception as error:
            run.close()
            self._finish(ERROR, error)
            return
        run.close()
        self._finish(IDLE, None)

    def _finish(self, status: str, error: Exception | None):
        with self._lock:
            self._finish_locked(status, error)

    def _finish_locked(self, status: str, error: Exception | None):
        self.session = None
        self.status = status
        self.error = str(error) if error else None
        self.version += 1

    def stop(self):
        """End the run.

        The camera, tracker and feeds are released at once. The run's thread
        finishes the window it is in, since generation cannot be interrupted,
        and a new run can start once it has.
        """
        with self._lock:
            if self.status not in (STARTING, RUNNING):
                return
            self._stop.set()
            self.status = STOPPING
            self.version += 1
            run = self.session
        if run:
            run.close()

    def snapshot(self) -> dict:
        """Everything the page shows, at one moment."""
        with self._lock:
            run = self.session
            quelle = None
            if run is not None:
                quelle = {
                    "kamera": run.stream.device.name,
                    "mikrofon": run.audio.name,
                    "modell": run.options.model,
                    "fenster_s": run.options.window,
                    "besetzung": list(run.tracker.cast.names) if run.tracker.cast else [],
                }
            return {
                "status": self.status,
                "error": self.error,
                "version": self.version,
                "gestartet": self.started.isoformat(timespec="seconds") if self.started else None,
                "quelle": quelle,
                "report": self.report,
            }

    def latest_frame(self):
        """The camera's newest frame, or None when no run holds the camera."""
        run = self.session
        if run is None or self.status != RUNNING:
            return None
        return run.stream.latest()
