"""Bodies followed from frame to frame.

RTMO detects every frame on its own (apollon_pose.model.detect), while the
action model needs the same person in the same slot for four seconds. Bodies
are linked by the overlap of their boxes between consecutive frames: at 25
frames a second a body moves a few pixels from one frame to the next, so the
greatest overlap is a reliable cue and needs no appearance model.

Before linking, detections that are not a second person are dropped: the pose
model boxing one person twice, and a person's shadow on a screen or wall
behind them (`without_ghosts`). Either would otherwise be followed, named and
classified as someone standing beside that person.

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

# Ghosts: detections that are not a second person. Each is measured against
# every more confident detection in the same frame, and dropped as either of
# two kinds.
#
# A duplicate: the pose model boxing one person twice. Its joints lie on the
# other detection's, on average less than DUPLICATE_APART of that body's height
# away. Measured on stage footage: duplicates up to 0.05, a second person
# overlapping another 0.36 and more.
DUPLICATE_APART = 0.06
#
# A shadow: a person's shadow on a projection screen or wall behind them,
# which the pose model reads as a body beside theirs. At least SHADOW_OVERLAP
# of its box lies inside the person's, its joints average below
# SHADOW_CONFIDENCE, and its pose is the person's own, shifted and scaled: the
# best such fit leaves a residual below SHADOW_COPY of the person's height.
# Measured on the Probebühne camera, a shadow scored 0.61-0.82 (p95 0.76) and
# fitted within 0.02-0.14 (p95 0.07); a real person kneeling beside a standing
# one, overlapping his box at a similar confidence, fitted no better than 0.13.
SHADOW_OVERLAP = 0.15
SHADOW_CONFIDENCE = 0.80
SHADOW_COPY = 0.10

# A fit needs at least this many joints visible in both detections.
MIN_SHARED = 4

# COCO-17 joint order with left and right exchanged. A shadow shows no face,
# and the pose model may read it as a body seen from behind, labelling its
# sides the other way round.
MIRRORED = [0, 2, 1, 4, 3, 6, 5, 8, 7, 10, 9, 12, 11, 14, 13, 16, 15]

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


def inside(a: np.ndarray, b: np.ndarray) -> float:
    """Share of box a that lies inside box b."""
    width = min(a[2], b[2]) - max(a[0], b[0])
    height = min(a[3], b[3]) - max(a[1], b[1])
    area = (a[2] - a[0]) * (a[3] - a[1])
    if width <= 0 or height <= 0 or area <= 0:
        return 0.0
    return float(width * height / area)


@dataclass
class Body:
    """One body in one frame."""

    keypoints: np.ndarray   # (17, 2), pixels
    scores: np.ndarray      # (17,)
    box: np.ndarray         # x1 y1 x2 y2

    @property
    def confidence(self) -> float:
        """Mean score of the visible joints."""
        return float(self.scores[self.scores >= VISIBLE].mean())


def apart(body: Body, other: Body) -> float:
    """Mean distance between the joints both show, as a share of `other`'s height."""
    shared = (body.scores >= VISIBLE) & (other.scores >= VISIBLE)
    height = other.box[3] - other.box[1]
    if shared.sum() < MIN_SHARED or height <= 0:
        return np.inf
    distances = np.linalg.norm(body.keypoints[shared] - other.keypoints[shared], axis=1)
    return float(distances.mean() / height)


def copy_residual(body: Body, other: Body) -> float:
    """How far `body`'s pose is from `other`'s, once shifted and scaled onto it.

    The root mean square joint distance left by the best such fit, as a share
    of `other`'s height, taking `body`'s sides as labelled or exchanged.
    """
    height = other.box[3] - other.box[1]
    best = np.inf
    for order in (slice(None), MIRRORED):
        keypoints, scores = body.keypoints[order], body.scores[order]
        shared = (scores >= VISIBLE) & (other.scores >= VISIBLE)
        if shared.sum() < MIN_SHARED or height <= 0:
            continue
        source = keypoints[shared] - keypoints[shared].mean(axis=0)
        target = other.keypoints[shared] - other.keypoints[shared].mean(axis=0)
        scale = (source * target).sum() / max((source * source).sum(), 1e-6)
        if scale <= 0:
            continue
        left = np.sqrt(((target - scale * source) ** 2).sum(axis=1).mean())
        best = min(best, float(left / height))
    return best


def ghost_of(body: Body, other: Body) -> bool:
    """Whether `body` is a duplicate or the shadow of the more confident `other`."""
    if other.confidence <= body.confidence:
        return False
    if apart(body, other) < DUPLICATE_APART:
        return True
    return (body.confidence < SHADOW_CONFIDENCE
            and inside(body.box, other.box) >= SHADOW_OVERLAP
            and copy_residual(body, other) < SHADOW_COPY)


def without_ghosts(bodies: list[Body]) -> list[Body]:
    """The bodies, less the duplicates and shadows of more confident ones."""
    return [body for body in bodies
            if not any(ghost_of(body, other) for other in bodies if other is not body)]


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
        detections = without_ghosts(detections)

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
