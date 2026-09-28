"""Bodies followed from frame to frame.

RTMO detects every frame on its own (orest_pose.model.detect), while the
action model needs the same person in the same slot for four seconds. Bodies
are linked by the overlap of their boxes between consecutive frames: at 25
frames a second a body moves a few pixels from one frame to the next, so the
greatest overlap is a reliable cue and needs no appearance model.

The tracker also keeps the recent frames themselves, each as the bodies it
held, so a window can be cut out of them for any group of people.
"""

from collections import deque
from dataclasses import dataclass, field

import numpy as np

# Joints scoring at least this count towards a body's box.
VISIBLE = 0.3

# A detection with fewer visible joints than this is not followed: too little
# of a body to box reliably, and too little for the action model to read.
MIN_JOINTS = 5

# Box overlap (intersection over union) at which a detection continues a body.
LINK = 0.3

# Seconds a body may go undetected and keep its identity, e.g. behind another
# actor. Longer, and a person walking out and another walking in could be
# taken for one.
FORGET = 1.0

# Seconds of frames kept; at least the longest window cut from them.
HISTORY = 10.0


def box(keypoints: np.ndarray, scores: np.ndarray) -> np.ndarray | None:
    """x1 y1 x2 y2 around a body's visible joints, or None if too few are visible."""
    visible = keypoints[scores >= VISIBLE]
    if len(visible) < MIN_JOINTS:
        return None
    return np.concatenate([visible.min(axis=0), visible.max(axis=0)])


def overlap(a: np.ndarray, b: np.ndarray) -> float:
    """Intersection over union of two boxes."""
    width = min(a[2], b[2]) - max(a[0], b[0])
    height = min(a[3], b[3]) - max(a[1], b[1])
    if width <= 0 or height <= 0:
        return 0.0
    shared = width * height
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - shared
    return float(shared / union) if union > 0 else 0.0


@dataclass
class Body:
    """One body in one frame."""

    keypoints: np.ndarray   # (17, 2), pixels
    scores: np.ndarray      # (17,)
    box: np.ndarray         # x1 y1 x2 y2


@dataclass
class Frame:
    """The bodies seen at one moment, by track id."""

    at: float
    bodies: dict[int, Body] = field(default_factory=dict)


class BodyTracker:
    """Gives each body a stable id for as long as it keeps being detected."""

    def __init__(self, *, link: float = LINK, forget: float = FORGET,
                 history: float = HISTORY):
        self._link = link
        self._forget = forget
        self._history = history
        self._last: dict[int, tuple[np.ndarray, float]] = {}   # id -> box, last seen
        self._next_id = 1
        self.frames: deque[Frame] = deque()

    def update(self, keypoints: np.ndarray, scores: np.ndarray, at: float) -> Frame:
        """Add one frame's detections, (people, 17, 2) and (people, 17)."""
        detections = []
        for points, confidence in zip(keypoints, scores):
            around = box(points, confidence)
            if around is not None:
                detections.append(Body(points, confidence, around))

        self._last = {track: (last_box, seen) for track, (last_box, seen) in self._last.items()
                      if at - seen <= self._forget}

        # Greedy on overlap: the most certain pairing is taken first and both
        # sides leave the pool, so two bodies can never swap onto one track.
        candidates = sorted(
            ((overlap(body.box, last_box), row, track)
             for row, body in enumerate(detections)
             for track, (last_box, _) in self._last.items()),
            reverse=True)
        assigned: dict[int, int] = {}
        for score, row, track in candidates:
            if score < self._link:
                break
            if row in assigned or track in assigned.values():
                continue
            assigned[row] = track

        frame = Frame(at)
        for row, body in enumerate(detections):
            track = assigned.get(row)
            if track is None:
                track = self._next_id
                self._next_id += 1
            self._last[track] = (body.box, at)
            frame.bodies[track] = body

        self.frames.append(frame)
        while self.frames and at - self.frames[0].at > self._history:
            self.frames.popleft()
        return frame

    def window(self, since: float, until: float) -> list[Frame]:
        """The kept frames from `since` to `until`, inclusive."""
        return [frame for frame in self.frames if since <= frame.at <= until]
