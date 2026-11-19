"""Who stands on the Podest, and the Risiko it counts for each person.

A rule of the production, not a measurement, set per scene
(scenes.PodestRule; "Scene 1" in knowledge/components/02_processing.md):
stepping off the Podest in the middle of the Probebühne raises a person's
Risiko by one, stepping onto it lowers it by one, and off it their Risiko
never reads below two. It is a running count over the scene (Counter), added
to the evidence of the live values (lage.py). It reads the poses the action
recogniser already tracks (actions.py), so it costs no model of its own.

Region. The Podest is the polygon of its top surface in the camera image, in
coordinates relative to the image's width and height (0-1), so that it holds
at any capture resolution. POLYGON was measured on the live Probebühne
camera on 2026-11-19. The Podest is moved between rehearsals: on 2026-09-30
it stood at the back left, on 2026-10-06 and 2026-10-12 further back in the
picture (front edge at y 702-720 px on 2026-10-12). A run can therefore be given another polygon (--podest,
session.Options.podest), and the operator's picture outlines the one in use.

On the Podest. A body is on the Podest in any posture, standing, kneeling,
sitting or lying, when the point between its visible ankles lies inside the
polygon, or when its hips do and it is not standing, as when sitting on an
edge with the legs hanging off. Standing is hip above knee by at least
STEHEND of the body's height: a person standing on the floor in front of the
Podest has their hips over the top surface in the camera image, and is off
it. A body whose ankles are not seen, and whose hips do not place it on the
Podest, cannot be judged. On 2026-11-19 (7 min, 1920x1080) a person sitting
on the back edge facing upstage counted as off by the earlier upright rule
and as on by this one; for every body standing, both agree.

Back edge. In one camera image, feet at the very back of the Podest and feet
on the floor a step behind it lie on the same line; both were seen between
580 and 600 px. The polygon begins at the back edge of the top surface, so a
person standing right at its back may go uncounted, rather than every actor
waiting behind the Podest counting as on it.

Steadiness. Pose and tracking flicker at an edge. A body takes a stance once
HALTEN judged frames in a row show it, followed frame by frame on the action
recogniser's thread (Stance), so a step is known about 0.16 s after the feet
cross. On 2026-11-19 this reported the steps 0.56 s (median) earlier than a
majority over the last second read every 0.5 s, with fewer reversed within a
second (1 against 3 of 28).

Counting. The count belongs to a person, not to a body, and lasts for the
scene: a person who leaves the picture keeps it, and on their return a change
of stance since they were last seen counts as one step. The floor is kept by
raising the count, so it is part of what the next step adds to or takes from:
someone with nothing measured who steps down reads 2 and, stepping back up, 1.
"""

import threading
from collections.abc import Callable, Sequence
from datetime import datetime

import cv2
import numpy as np

from action import tracking

# The cause shown with the Risiko the count adds, followed by the count.
ANLASS = "Podest"

# Largest count either way: the Risiko scale's whole range.
GRENZE = 5

# Top surface of the Podest, clockwise from the back left, as shares of the
# image's width and height. Probebühne camera, 2026-11-19, 1920x1080: two
# platforms side by side, top surface from x 500 to 1065 px, its back edge
# at y 638-642 px and its front edge at y 762-780 px.
POLYGON: tuple[tuple[float, float], ...] = (
    (0.338, 0.591), (0.555, 0.594), (0.543, 0.722), (0.260, 0.706))

# Judged frames in a row that show a body's new stance before it is taken: at
# 25 frames a second, 0.16 s.
HALTEN = 4

# Least drop from hip to knee, as a share of the body's box height, of a body
# standing. Standing measured 0.16-0.32; a level thigh (sitting, kneeling,
# lying) stays near 0 or turns negative.
STEHEND = 0.1

# COCO-17 joints, left and right.
HIPS = [11, 12]
KNEES = [13, 14]
ANKLES = [15, 16]


def parse_polygon(text: str) -> tuple[tuple[float, float], ...]:
    """A polygon written as "x,y x,y x,y ...", in shares of the image (0-1)."""
    try:
        points = tuple((float(x), float(y))
                       for x, y in (point.split(",") for point in text.split()))
    except ValueError:
        raise ValueError(f"expected points as x,y separated by spaces: {text!r}") from None
    if len(points) < 3 or not all(0 <= value <= 1 for point in points for value in point):
        raise ValueError(f"expected at least three points between 0 and 1: {text!r}")
    return points


def format_polygon(polygon: Sequence[tuple[float, float]]) -> str:
    """A polygon as parse_polygon reads it."""
    return " ".join(f"{x:g},{y:g}" for x, y in polygon)


def pixels(polygon: Sequence[tuple[float, float]], shape: tuple[int, int]) -> np.ndarray:
    """A relative polygon in pixels of an image of `shape` (height, width)."""
    height, width = shape
    return (np.asarray(polygon, dtype=np.float32) * [width, height]).astype(np.float32)


def _mean_height(body: tracking.Body, joints: list[int]) -> float | None:
    visible = [joint for joint in joints if body.scores[joint] >= tracking.VISIBLE]
    if not visible:
        return None
    return float(body.keypoints[visible, 1].mean())


def _mean_point(body: tracking.Body, joints: list[int]) -> np.ndarray | None:
    visible = [joint for joint in joints if body.scores[joint] >= tracking.VISIBLE]
    return body.keypoints[visible].mean(axis=0) if visible else None


def _inside(region: np.ndarray, point: np.ndarray) -> bool:
    return cv2.pointPolygonTest(region, (float(point[0]), float(point[1])), False) >= 0


def on_podest(body: tracking.Body, region: np.ndarray) -> bool | None:
    """Whether a body is on the region, a polygon in pixels, in any posture;
    None when its ankles are not seen and its hips do not place it there."""
    foot, hip = _mean_point(body, ANKLES), _mean_point(body, HIPS)
    if foot is not None and _inside(region, foot):
        return True
    if hip is not None and _inside(region, hip):
        knee = _mean_height(body, KNEES)
        height = float(body.box[3] - body.box[1])
        if knee is not None and knee - float(hip[1]) < STEHEND * height:
            return True
    return False if foot is not None else None


class Stance:
    """Each tracked body's stance on the Podest, followed frame by frame.

    A body takes a stance once HALTEN judged frames in a row show it; a frame
    in which it cannot be judged neither confirms nor breaks the run. Until it
    has taken one it counts as off the Podest. A body keeps its stance while
    out of view, so a step taken while the tracker briefly lost it counts on
    its return, and is forgotten once the tracker would have (tracking.FORGET).

    `on_step(track, up)` receives every step, True onto the Podest and False
    off it, on the thread that calls `observe`. A body's first stance is no
    step. Frames arrive on the action recogniser's thread and the stance is
    read from others, so both hold a lock.
    """

    def __init__(self, polygon: Sequence[tuple[float, float]] = POLYGON,
                 on_step: Callable[[int, bool], None] | None = None):
        self.polygon = polygon
        self._on_step = on_step
        self._shape: tuple[int, int] | None = None
        self._region: np.ndarray | None = None
        # Per body: its stance, the stance of its latest judged frames and
        # how many in a row, and when it was last in view.
        self._up: dict[int, bool] = {}
        self._run: dict[int, tuple[bool, int]] = {}
        self._seen: dict[int, float] = {}
        self._in_view: list[int] = []
        self._lock = threading.Lock()

    def observe(self, frame: tracking.Frame, shape: tuple[int, int]) -> list[tuple[int, bool]]:
        """Take one tracked frame of an image of `shape` (height, width).
        Returns the steps it completed."""
        if shape != self._shape:
            self._shape, self._region = shape, pixels(self.polygon, shape)
        steps = []
        with self._lock:
            for track, body in frame.bodies.items():
                self._seen[track] = frame.at
                judged = on_podest(body, self._region)
                if judged is None:
                    continue
                stance, count = self._run.get(track, (judged, 0))
                count = count + 1 if stance == judged else 1
                self._run[track] = (judged, count)
                if count >= HALTEN and self._up.get(track) != judged:
                    if track in self._up:
                        steps.append((track, judged))
                    self._up[track] = judged
            self._in_view = sorted(frame.bodies)
            for track in [track for track, at in self._seen.items()
                          if frame.at - at > tracking.FORGET]:
                for held in (self._up, self._run, self._seen):
                    held.pop(track, None)
        if self._on_step is not None:
            for track, up in steps:
                self._on_step(track, up)
        return steps

    def now(self) -> dict[int, bool]:
        """Each body in the latest frame, by track id, and whether it is on
        the Podest."""
        with self._lock:
            return {track: self._up.get(track, False) for track in self._in_view}

    def clear(self):
        with self._lock:
            self._up, self._run, self._seen, self._in_view = {}, {}, {}, []


class Counter:
    """Each person's Risiko from the Podest, counted over a scene.

    `step` is added on stepping off and taken off on stepping on; off the
    Podest the count is raised as far as needed for the person's Risiko, their
    measured value plus the count, to reach `floor`. Not thread-safe: the live
    values update it under their own lock.
    """

    def __init__(self, step: int, floor: int):
        self.step, self.floor = step, floor
        self._up: dict[str, bool] = {}
        self._count: dict[str, int] = {}
        self._changed: dict[str, datetime] = {}

    def update(self, stance: dict[str, bool], measured: dict[str, int],
               now: datetime) -> dict[str, tuple[int, datetime]]:
        """Take the stance of the people in view now, by name (True on the
        Podest), and their measured Risiko. Returns every person's count and
        when it last changed, out of view included."""
        for name, up in stance.items():
            before = self._up.get(name)
            count = self._count.get(name, 0)
            if before is True and not up:
                count += self.step
            elif before is False and up:
                count -= self.step
            if not up:
                count = max(count, self.floor - measured.get(name, 0))
            count = int(np.clip(count, -GRENZE, GRENZE))
            if count != self._count.get(name, 0):
                self._changed[name] = now
            self._count[name] = count
            self._up[name] = up
        return {name: (count, self._changed.get(name, now))
                for name, count in self._count.items()}
