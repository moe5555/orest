"""Risiko and Menschlichkeit per person, measured from what bodies do.

The Pose route under "Calculating Values" in
knowledge/components/02_processing.md. The action recogniser (src/action) runs
beside the SITREP as one more reader of the shared camera, and its readings
become the per-person ratings of the report. Pose runs at 25 frames a second,
so a blow struck between two of the model's sampled stills is still seen.

Three steps turn readings into ratings:

Naming. The recogniser follows bodies, while the report names people by face.
Each time the recogniser classifies, every body whose head joints lie in a
face box the presence tracker saw within FACE_AGE seconds takes that face's
name. A name belongs to one body in view: seen on a second body in the same
frame, it leaves the first. A body that has left the frame keeps its name for
what it did while it was there, so a camera cut or a lost track does not
unname its earlier readings. Readings are kept
under the body and named only when a report takes them, so a body named at
any point before then is rated on all its readings, including those made
before its face was seen. A body that never shows its face is not rated.

Evidence. A reading's 120 class probabilities are weighed with the
Action-to-SITREP table (action/sitrep_map.csv): the evidence for a rating is
sum over classes of P(class) x table value, its expected value under the
model's own uncertainty. A class the model is unsure of counts for
proportionally less, and the classes the table leaves at 0 count for nothing.
A pair reading counts for both people in it, since NTU does not say which of
them acts.

Rating. Each rating is the peak evidence among the readings a person took part
in, rounded and clipped to 0-5. The peak rather than the mean, because one
blow makes a person dangerous however calm the rest of the window was.

Readings are kept for KEEP seconds and read, never consumed: the live
values (lage.py) read the last few seconds, each stretch of the scene's
summary (chronik.py) and a report asked for read theirs.
"""

import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

import numpy as np

from action import model, recognizer, sitrep_map, tracking

from . import loudness, presence, report

# Seconds a face box stays usable for naming a body: two passes of the
# presence tracker, so one missed detection does not leave a body unnamed.
FACE_AGE = 2 * presence.INTERVAL

# How far a head may lie outside a face box, as a share of the box's size, and
# still be named by it. The box can be FACE_AGE old, and a person moves.
FACE_MARGIN = 0.5

# COCO-17 joints of the head: nose, eyes, ears.
HEAD = slice(0, 5)

RATING_MAX = 5

# Seconds of readings kept: as long as the summary of the scene may ask about
# (chronik.py), and the same as the loudness levels kept (loudness.KEEP).
KEEP = 600.0


def head(body: tracking.Body) -> np.ndarray | None:
    """Mean position of a body's visible head joints, or None if none is visible."""
    visible = body.scores[HEAD] >= tracking.VISIBLE
    if not visible.any():
        return None
    return body.keypoints[HEAD][visible].mean(axis=0)


def name_bodies(frame: tracking.Frame,
                faces: list[tuple[np.ndarray, str]]) -> dict[int, str]:
    """Each body whose head lies in a face box, with that face's name.

    One face names at most one body and one body takes at most one name. Where
    heads and faces overlap, the head nearest a face's centre is paired first.
    """
    candidates = []
    for track, body in frame.bodies.items():
        point = head(body)
        if point is None:
            continue
        for index, (box, _) in enumerate(faces):
            box = np.asarray(box, dtype=float)
            margin = FACE_MARGIN * max(box[2] - box[0], box[3] - box[1])
            if (box[0] - margin <= point[0] <= box[2] + margin
                    and box[1] - margin <= point[1] <= box[3] + margin):
                centre = (box[:2] + box[2:]) / 2
                candidates.append((float(np.linalg.norm(point - centre)), track, index))

    named: dict[int, str] = {}
    used: set[int] = set()
    for _, track, index in sorted(candidates):
        if track in named or index in used:
            continue
        named[track] = faces[index][1]
        used.add(index)
    return named


@dataclass(frozen=True)
class Evidence:
    """One reading, weighed, and the bodies it counts for."""

    at: datetime
    members: tuple[int, ...]        # body track ids
    values: np.ndarray              # (len(sitrep_map.RATINGS),)
    causes: tuple[str, ...]         # per rating: strongest class and its probability


@dataclass(frozen=True)
class Recognised:
    """What one person or pair is doing now, for watching the recogniser live."""

    who: tuple[str, ...]            # names, or "Körper <id>" for an unnamed body
    action: str                     # most probable class
    probability: float
    values: np.ndarray              # evidence per rating, as for Evidence


def weigh(probabilities: np.ndarray,
          mapping: sitrep_map.Mapping) -> tuple[np.ndarray, tuple[str, ...]]:
    """Expected evidence per rating, and the class contributing most to each."""
    contributions = probabilities[:, None] * mapping.evidence
    strongest = contributions.argmax(axis=0)
    causes = tuple(f"{mapping.names[index]} {probabilities[index]:.2f}" for index in strongest)
    return contributions.sum(axis=0), causes


# A gain on Risiko for a stretch of time (loudness.gain_over, for one report).
Gain = Callable[[datetime, datetime], float]


def rate(records: list[Evidence], names: dict[int, str],
         gain: Gain | None = None) -> list[report.Handlung]:
    """Ratings per named person over a stretch of readings, first seen first.

    `names` maps body track ids to people; readings of unnamed bodies count
    for no one. `gain` amplifies each reading's Risiko by how loud the room was
    over the seconds it covers (loudness.py), before the peak is taken.
    """
    people: dict[str, list[Evidence]] = {}
    for record in records:
        for name in dict.fromkeys(names[member] for member in record.members
                                  if member in names):
            people.setdefault(name, []).append(record)

    gains = {id(record): gain(record.at - timedelta(seconds=recognizer.WINDOW), record.at)
             if gain else 1.0 for record in records}
    risiko = sitrep_map.RATINGS.index("risiko")

    def evidence(record: Evidence, column: int) -> float:
        value = float(record.values[column])
        return loudness.amplified(value, gains[id(record)]) if column == risiko else value

    rated = []
    for name, own in people.items():
        fields = {}
        for column, rating in enumerate(sitrep_map.RATINGS):
            peak = max(own, key=lambda record: evidence(record, column))
            value = int(np.clip(np.floor(evidence(peak, column) + 0.5), 0, RATING_MAX))
            fields[rating] = value
            cause = peak.causes[column] if value else ""
            if cause and column == risiko:
                fields["verstaerkung"] = round(gains[id(peak)], 2)
                if gains[id(peak)] > 1.0:
                    cause += f" · laut ×{gains[id(peak)]:.1f}"
            fields[f"anlass_{rating}"] = cause
        rated.append(report.Handlung(name=name, lesungen=len(own), **fields))
    return rated


class ActionRatings:
    """The action recogniser on a shared camera, read as ratings per person.

    Reads the camera and the presence tracker and never closes either. The
    recogniser runs on its own thread; `name`, `record` and `take` can also be
    driven by hand.
    """

    def __init__(self, source, faces: presence.PresenceTracker,
                 mapping: sitrep_map.Mapping | None = None, on_frame=None):
        self.mapping = mapping or sitrep_map.load()
        self._faces = faces
        self._names: dict[int, str] = {}
        self._records: list[Evidence] = []
        self._lock = threading.Lock()
        # The last classification, every body included, and how many there
        # have been: a live view between reports.
        self.latest: list[Recognised] = []
        self.evaluations = 0
        # `on_frame` receives each camera frame with its tracked bodies, e.g.
        # for measuring mouths (speakers.py).
        self.recognizer = recognizer.ActionRecognizer(source, on_readings=self._on_readings,
                                                      on_frame=on_frame)

    def start(self) -> "ActionRatings":
        # Loaded before the thread starts, so a missing model fails the run at
        # its start rather than silently on the thread, and the first window
        # does not pay for the load.
        model.session()
        self.recognizer.start()
        return self

    def close(self):
        self.recognizer.close()

    def __enter__(self) -> "ActionRatings":
        return self.start()

    def __exit__(self, *exception):
        self.close()

    @property
    def error(self) -> Exception | None:
        """The exception that stopped recognition, if one did."""
        return self.recognizer.error

    def names(self) -> dict[int, str]:
        """The name each body carries, by track id."""
        with self._lock:
            return dict(self._names)

    def visible(self) -> list[tuple[np.ndarray, str]]:
        """Box and label of the tallest bodies in the latest tracked frame.

        The people the ratings and speaker attribution are about, labelled by
        name, or "Körper <id>" while no face has named them.
        """
        # The recogniser's thread only appends finished frames, so the newest
        # one can be read without its lock.
        frames = self.recognizer.tracker.frames
        if not frames:
            return []
        frame = frames[-1]
        names = self.names()
        return [(frame.bodies[track].box, names.get(track, f"Körper {track}"))
                for track in recognizer.tallest(frame)]

    def _on_readings(self, readings: list[recognizer.Reading]):
        # Runs on the recogniser's thread between two of its frames, so its
        # body tracker is not being updated meanwhile.
        frames = self.recognizer.tracker.frames
        if frames:
            self.name(frames[-1], self._faces.faces(FACE_AGE))
        self.record(readings, datetime.now())

    def name(self, frame: tracking.Frame, faces: list[tuple[np.ndarray, str]]):
        """Name the bodies in a frame from the faces seen around it."""
        named = name_bodies(frame, faces)
        with self._lock:
            for track, label in named.items():
                # A name belongs to one body in view: seen on this one, it
                # leaves any other body in the same frame.
                for other in [other for other, held in self._names.items()
                              if held == label and other != track and other in frame.bodies]:
                    del self._names[other]
                self._names[track] = label

    def record(self, readings: list[recognizer.Reading], at: datetime):
        """Weigh readings and keep them under the bodies they are of."""
        with self._lock:
            names = dict(self._names)
        kept, seen = [], []
        for reading in readings:
            values, causes = weigh(reading.probabilities, self.mapping)
            kept.append(Evidence(at, reading.members, values, causes))
            top = int(reading.probabilities.argmax())
            seen.append(Recognised(
                tuple(names.get(member, f"Körper {member}") for member in reading.members),
                self.mapping.names[top], float(reading.probabilities[top]), values))
        with self._lock:
            self._records.extend(kept)
            while self._records and at - self._records[0].at > timedelta(seconds=KEEP):
                self._records.pop(0)
            self.latest = seen
            self.evaluations += 1

    def clear(self):
        """Delete every reading, name and tracked pose held."""
        with self._lock:
            self._records = []
            self._names = {}
            self.latest = []
        self.recognizer.tracker.frames.clear()

    def between(self, since: datetime, until: datetime,
                gain: Gain | None = None) -> list[report.Handlung]:
        """Ratings from the readings made after `since` and up to `until`."""
        records, names = self.since(since, until)
        return rate(records, names, gain)

    def since(self, since: datetime,
              until: datetime | None = None) -> tuple[list[Evidence], dict[int, str]]:
        """The readings after `since` (up to `until`), and the name each body carries now.

        Names are resolved when asked for, so a body named at any point is
        rated on everything it did while it was kept.
        """
        with self._lock:
            return ([record for record in self._records
                     if record.at > since and (until is None or record.at <= until)],
                    dict(self._names))
