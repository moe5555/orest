"""The live SITREP run behind the interface.

At most one run exists at a time: there is one camera, and DirectShow gives it
to one process (sitrep/session.py). The run lives on a thread of its own,
which follows what the session produces, while the web server keeps answering
the page.

The page is fed from a snapshot rather than from the session directly: status,
the live values and alarm, the latest lines, the Chronik, the latest
recommendation and report, the action recogniser's latest readings, the names
of the people boxed on the video, and a
version number that rises with every change of the run's state, so a page
polling or streaming the state knows whether anything is new.
"""

import threading
import time
from collections import deque
from collections.abc import Callable
from datetime import datetime, timedelta

from sitrep import annotate, chronik, lage, report, session

# Run states, as the page shows them.
IDLE, STARTING, RUNNING, STOPPING, ERROR = "idle", "starting", "running", "stopping", "error"


def payload(document: report.Sitrep, nummer: int) -> dict:
    """A report as the page renders it.

    The document as JSON, plus what the page cannot work out for itself: the
    report's number within the run, each person's
    ratings joined from what was measured and what was generated (null where
    nothing was measured), and the threshold the scene ratings are read
    against.
    """
    rendered = document.model_dump(mode="json")
    rendered["nummer"] = nummer
    rendered["schwelle"] = report.SCHWELLE
    for person, source in zip(rendered["bericht"]["personen"], document.bericht.personen):
        person.update(document.bewertungen(source))
        person["anlass"] = [f"{name}: {document.bewertung(source.name, name)[1]}"
                            for name in report.GEMESSEN
                            if document.bewertung(source.name, name)[1]]
    return rendered


# Live action readings shown at once, strongest evidence first. The audience
# at the frame's edges is classified too, and would otherwise fill the list.
AKTIONEN_SHOWN = 12


def aktionen(ratings) -> dict:
    """The action recogniser's last classification, as the page shows it live.

    `stand` counts classifications, so the page can tell a new one from a
    repeat of the last.
    """
    if ratings is None:
        return {"aktiv": False}
    latest = sorted(ratings.latest, key=lambda seen: -float(abs(seen.values).max()))
    return {
        "aktiv": True,
        "fehler": repr(ratings.error) if ratings.error else None,
        "stand": ratings.evaluations,
        "lesungen": [
            {"wer": list(seen.who), "handlung": seen.action,
             "wahrscheinlichkeit": round(seen.probability, 2),
             **{name: round(float(value), 1)
                for name, value in zip(report.GEMESSEN, seen.values)}}
            for seen in latest[:AKTIONEN_SHOWN]
        ],
    }


def zeile(line: report.Aeusserung) -> dict:
    """A line as the page lists it."""
    return {"zeit": line.ende.isoformat(timespec="seconds"),
            "beginn": line.beginn.isoformat(timespec="milliseconds"), "name": line.name,
            "text": line.text, "lautstaerke": line.lautstaerke,
            "risiko": line.risiko, "menschlichkeit": line.menschlichkeit,
            "verstaerkung": line.verstaerkung, "begruendung": line.begruendung}


def werte(stand: lage.Stand) -> dict:
    """The live values as the page shows them: whole numbers and their causes."""
    return {
        "zeit": stand.zeit.isoformat(timespec="seconds"),
        "personen": [{"name": name,
                      **{rating: wert.wert for rating, wert in ratings.items()},
                      **{f"anlass_{rating}": wert.anlass for rating, wert in ratings.items()}}
                     for name, ratings in stand.personen.items()],
        "alarm": {"aktiv": stand.alarm.aktiv, "wert": stand.alarm.wert,
                  "wer": stand.alarm.wer, "anlass": stand.alarm.anlass},
    }


def im_bild(visible: list[tuple]) -> list[str]:
    """The names on the video's boxes, ordered left to right by box centre.

    Takes what `actions.ActionRatings.visible()` returns, the same boxes and labels
    the overlay draws, so a page can place each person where they stand.
    """
    return [name for box, name in sorted(visible, key=lambda seen: float(seen[0][0] + seen[0][2]))]


def in_view(seen: list[tuple]) -> list[dict]:
    """The bodies in view, left to right, as the page offers them for naming.

    Takes what `actions.ActionRatings.in_view()` returns. `body` is the
    recogniser's track id, which an assignment names; `assigned` marks a name
    the operator gave.
    """
    ordered = sorted(seen, key=lambda body: float(body[1][0] + body[1][2]))
    return [{"body": int(track), "label": label, "assigned": assigned}
            for track, _, label, assigned in ordered]


def chronik_payload(kept: chronik.Chronik) -> dict:
    """The Chronik as the page shows it: the Rueckblick, the Abschnitte, the Kurve."""
    return {
        "rueckblick": kept.rueckblick,
        "rueckblick_bis": kept.rueckblick_bis.isoformat(timespec="seconds")
                          if kept.rueckblick_bis else None,
        "abschnitte": [abschnitt.model_dump(mode="json", include={
                           "beginn", "ende", "zusammenfassung", "latenz_s"})
                       for abschnitt in kept.abschnitte],
        "kurve": [punkt.model_dump(mode="json") for punkt in kept.kurve],
        "naechster": (kept.cut + timedelta(seconds=kept.laenge)).isoformat(timespec="seconds"),
    }


# Lines the page lists, newest last.
ZEILEN_SHOWN = 12

# The live ratings drawn beside each person on Prototype 2's picture, with the
# names the page gives them.
RATING_LABELS = {"risiko": "Risiko", "menschlichkeit": "Menschlichkeit",
                 "vorhersehbarkeit": "Vorhersehbarkeit"}


def rating_level(name: str, value: int) -> str:
    """A person's rating as the page colours it (sitrep.js, personLevel):
    Risiko amber from 2 and red from 4 on its 0-5 scale, Vorhersehbarkeit
    likewise from -2 and -4 on its -5 to +5, the rest neutral."""
    if name == "risiko":
        return "red" if value >= 4 else "amber" if value >= 2 else "calm"
    if name == "vorhersehbarkeit":
        return "red" if value <= -4 else "amber" if value <= -2 else "calm"
    return "calm"


def latest_scene(kept: chronik.Chronik | None, bericht: dict | None,
                 empfehlung: dict | None) -> dict | None:
    """The newest rating of the scene as a whole, with its time and source.

    Three things rate the scene, each at its own rhythm: the Chronik once per
    Abschnitt, a Lagebericht on request, a recommendation on request or alarm.
    None is continuous, so the newest stands for the scene now. `bericht` and
    `empfehlung` are as the page receives them (payload, LiveSitrep._take).
    """
    candidates = []
    if kept is not None:
        summarised = [abschnitt for abschnitt in kept.abschnitte if abschnitt.zusammenfassung]
        if summarised:
            candidates.append(("chronik", summarised[-1].ende,
                               summarised[-1].zusammenfassung.szene.model_dump()))
    if bericht is not None:
        candidates.append(("bericht", datetime.fromisoformat(bericht["zeitfenster"]["ende"]),
                           bericht["bericht"]["szene"]))
    if empfehlung is not None:
        candidates.append(("empfehlung", datetime.fromisoformat(empfehlung["zeit"]),
                           empfehlung["urteil"]["szene"]))
    if not candidates:
        return None
    source, time, szene = max(candidates, key=lambda candidate: candidate[1])
    return {**szene, "source": source, "time": time.isoformat(timespec="seconds"),
            "threshold": report.SCHWELLE}


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
        self.empfehlung: dict | None = None
        self.werte: dict | None = None
        self.zeilen: deque[dict] = deque(maxlen=ZEILEN_SHOWN)
        # The last request that failed, until the next of its kind succeeds.
        self.fehler: dict[str, str] = {}
        self.started: datetime | None = None
        self.version = 0
        # Prototype 3's slots on the strip beneath the picture, by person.
        self.slots = annotate.Slots()

    def start(self) -> bool:
        """Begin a run. Returns False if one is already under way."""
        with self._lock:
            if self.status in (STARTING, RUNNING, STOPPING):
                return False
            self._stop = threading.Event()
            self.status, self.error = STARTING, None
            self.report, self.empfehlung, self.werte = None, None, None
            self.zeilen.clear()
            self.fehler = {}
            self.started = datetime.now()
            self.slots = annotate.Slots()
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
            for event in run.events():
                if stop.is_set():
                    break
                with self._lock:
                    self._take(event)
                    self.version += 1
        except Exception as error:
            run.close()
            self._finish(ERROR, error)
            return
        run.close()
        self._finish(IDLE, None)

    def _take(self, event):
        """Keep what the page shows of one of the run's events."""
        if isinstance(event, session.Zeilen):
            # A rated line takes the place of the line as it was transcribed.
            shown = {(held["beginn"], held["text"]): index for index, held in enumerate(self.zeilen)}
            for line in event.zeilen:
                row = {**zeile(line), "bewertet": event.bewertet}
                index = shown.get((row["beginn"], row["text"]))
                if index is None:
                    self.zeilen.append(row)
                else:
                    self.zeilen[index] = row
        elif isinstance(event, session.Werte):
            self.werte = werte(event.stand)
        elif isinstance(event, session.NeuerBericht):
            self.report = payload(event.sitrep, event.nummer)
            self.fehler.pop("bericht", None)
        elif isinstance(event, session.NeueEmpfehlung):
            self.empfehlung = {**event.empfehlung.model_dump(mode="json"),
                               "nummer": event.nummer, "schwelle": report.SCHWELLE}
            self.fehler.pop("empfehlung", None)
        elif isinstance(event, session.Fehlgeschlagen):
            self.fehler[event.was] = event.fehler

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

        The camera, tracker and feeds are released at once. A report or
        summary being generated cannot be interrupted; it finishes on its own
        thread and is dropped, and a new run can start meanwhile.
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

    def bericht(self) -> bool:
        """Ask the run for a report. False when none runs, or one is being made."""
        run = self.session
        return run.bericht() if run is not None and self.status == RUNNING else False

    def empfehlen(self) -> bool:
        """Ask the run for a recommendation now."""
        run = self.session
        return run.empfehlung() if run is not None and self.status == RUNNING else False

    def assign(self, body: int, name: str | None) -> bool:
        """Name a body in view by hand, or release it with None
        (session.Session.assign). False while no run is live; a name outside
        the cast raises ValueError."""
        run = self.session
        if run is None or self.status != RUNNING:
            return False
        run.assign(body, name)
        with self._lock:
            self.version += 1
        return True

    def uebergehen(self, nummer: int | None = None) -> bool:
        """Set the recommendation aside, so the page returns to its regular view.

        With `nummer`, only that recommendation is set aside: one that arrived
        after the operator decided stays on screen. The run is not told; the
        next recommendation shows as usual.
        """
        with self._lock:
            if self.empfehlung is None:
                return False
            if nummer is not None and self.empfehlung["nummer"] != nummer:
                return False
            self.empfehlung = None
            self.version += 1
            return True

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
                    "aktionen": run.actions is not None,
                    "auto_empfehlung": run.options.auto_empfehlung,
                    "besetzung": list(run.tracker.cast.names) if run.tracker.cast else [],
                }
            return {
                "status": self.status,
                "error": self.error,
                "version": self.version,
                "gestartet": self.started.isoformat(timespec="seconds") if self.started else None,
                "quelle": quelle,
                "aktionen": aktionen(run.actions) if run is not None else None,
                "im_bild": (im_bild(run.actions.visible())
                            if run is not None and run.actions is not None else []),
                "in_view": (in_view(run.actions.in_view())
                            if run is not None and run.actions is not None else []),
                "ton": run.ton() if run is not None and run.meter is not None else None,
                "werte": self.werte,
                "zeilen": list(self.zeilen),
                "chronik": (chronik_payload(run.chronik)
                            if run is not None and run.chronik is not None else None),
                "scene": latest_scene(run.chronik if run is not None else None,
                                      self.report, self.empfehlung),
                "laeuft": run.laeuft if run is not None else {},
                "fehler": dict(self.fehler),
                "empfehlung": self.empfehlung,
                "report": self.report,
            }

    def latest_frame(self):
        """The camera's newest frame, or None when no run holds the camera."""
        run = self.session
        if run is None or self.status != RUNNING:
            return None
        return run.stream.latest()

    def overlay(self, frame, ratings: bool = False, strip: bool = False):
        """The frame with the people the run tracks boxed and named.

        With `ratings`, each recognised person's live values are set beside
        their box (Prototype 2); a recognised person with no recent evidence
        reads 0, as on Prototype 1. A body not carrying a cast name is boxed
        and labelled "Körper <id>", without values. With
        `strip` as well, the values stand in fixed slots on a strip beneath
        the picture, each tied to its box by a line (Prototype 3).
        """
        run = self.session
        if run is None:
            return frame
        if not ratings or run.actions is None:
            return run.overlay(frame)
        with self._lock:
            live = {person["name"]: person for person in (self.werte or {}).get("personen", [])}
        cast = set(run.tracker.cast.names) if run.tracker.cast else set()
        rated = []
        for box, name in run.actions.visible():
            values = live.get(name, {})
            rows = [(RATING_LABELS[rating], values.get(rating, 0),
                     rating_level(rating, values.get(rating, 0)))
                    for rating in report.BEWERTUNGEN] if name in cast else []
            rated.append((box, name, rows))
        if not strip:
            return annotate.draw_ratings(frame, rated)
        width = frame.shape[1]
        slots = self.slots.assign([(name, float(box[0] + box[2]) / 2 / width)
                                   for box, name, rows in rated if rows], time.monotonic())
        return annotate.draw_ratings_strip(frame, rated, slots,
                                           [RATING_LABELS[rating] for rating in report.BEWERTUNGEN])
