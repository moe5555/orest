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
camera on 2026-10-12. The Podest is moved between rehearsals: on 2026-09-30
it stood at the back left, on 2026-10-06 about 120 px right of where it
stands now. A run can therefore be given another polygon (--podest,
session.Options.podest), and the operator's picture outlines the one in use.

Standing. A body stands on the Podest when the point between its visible
ankles lies inside the polygon and its legs are upright: hip above knee above
ankle, each by at least STEHEND of the body's height. Measured on 150 frames
of 2026-10-06: ankles on the top surface lay between y 600 and 690 px (1080p),
a person sitting on its edge has their feet on the floor in front of it
(760 px and more), and kneeling, crawling or lying leaves a thigh or shin
level. A body whose ankles, knees or hips are not seen cannot be judged.

Back edge. In one camera image, feet at the very back of the Podest and feet
on the floor a step behind it lie on the same line; both were seen between
580 and 600 px. The polygon begins at the back edge of the top surface, so a
person standing right at its back may go uncounted, rather than every actor
waiting behind the Podest counting as on it.

Steadiness. Pose and tracking flicker at an edge. A body is up when its stance
was judged on the Podest in at least half the frames of the last FENSTER
seconds in which it could be judged, and it is still in view.

Counting. The count belongs to a person, not to a body, and lasts for the
scene: a person who leaves the picture keeps it, and on their return a change
of stance since they were last seen counts as one step. The floor is kept by
raising the count, so it is part of what the next step adds to or takes from:
someone with nothing measured who steps down reads 2 and, stepping back up, 1.
"""

from collections.abc import Sequence
from datetime import datetime

import cv2
import numpy as np

from action import tracking

# The cause shown with the Risiko the count adds, followed by the count.
ANLASS = "Podest"

# Largest count either way: the Risiko scale's whole range.
GRENZE = 5

# Top surface of the Podest, clockwise from the back left, as shares of the
# image's width and height. Probebühne camera, 2026-10-12, 1920x1080: two
# platforms side by side, top surface from x 527 to 1050 px, its front edge
# at y 702-720 px.
POLYGON: tuple[tuple[float, float], ...] = (
    (0.350, 0.556), (0.549, 0.556), (0.532, 0.674), (0.270, 0.659))

# Seconds of tracked frames a body's stance is judged over: at 25 frames a
# second, 25 frames, and a step up or down shows within about a second.
FENSTER = 1.0

# Least drop from hip to knee and from knee to ankle, as a share of the body's
# box height. Standing measured 0.16-0.32 for each; a level thigh or shin
# (sitting, kneeling, lying) stays near 0 or turns negative.
STEHEND = 0.1

# Share of the judged frames in which the body must stand on the Podest.
MEHRHEIT = 0.5

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


def steht_auf(body: tracking.Body, region: np.ndarray) -> bool | None:
    """Whether a body stands on the region, a polygon in pixels; None when
    its hips, knees or ankles are not seen."""
    hip, knee, ankle = (_mean_height(body, joints) for joints in (HIPS, KNEES, ANKLES))
    if hip is None or knee is None or ankle is None:
        return None
    feet = [joint for joint in ANKLES if body.scores[joint] >= tracking.VISIBLE]
    foot = body.keypoints[feet].mean(axis=0)
    if cv2.pointPolygonTest(region, (float(foot[0]), float(foot[1])), False) < 0:
        return False
    height = float(body.box[3] - body.box[1])
    return knee - hip >= STEHEND * height and ankle - knee >= STEHEND * height


def oben(frames: list[tracking.Frame], shape: tuple[int, int],
         polygon: Sequence[tuple[float, float]] = POLYGON) -> set[int]:
    """Track ids of the bodies standing on the Podest over `frames`, oldest
    first, from an image of `shape` (height, width)."""
    if not frames:
        return set()
    region = pixels(polygon, shape)
    judged: dict[int, list[bool]] = {}
    for frame in frames:
        for track, body in frame.bodies.items():
            stance = steht_auf(body, region)
            if stance is not None:
                judged.setdefault(track, []).append(stance)
    in_view = frames[-1].bodies
    return {track for track, stances in judged.items()
            if track in in_view and sum(stances) >= MEHRHEIT * len(stances)}


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
