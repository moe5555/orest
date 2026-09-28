"""Continuous action recognition: pose at a steady rate, a window every second.

The camera is read at FPS and every frame goes through pose detection and the
body tracker. Every STEP seconds the last WINDOW seconds are cut out and
classified, once per person and once per pair of people standing close
enough to be interacting.

FPS and WINDOW are chosen together: 25 frames a second for 4 seconds is 100
frames, one full clip of the model's. NTU clips are mostly longer than 100
frames and span a whole action, so the model learned actions spread over 100
sampled frames. A window shorter than a clip would be looped to fill it
instead (preprocess.sample_indices), showing the action faster and repeated.

Singles and pairs are both classified. NTU's mutual actions ("punching/
slapping other person") were recorded with both people in the clip, its
single-person ones ("falling") with one and an empty second slot, and the
model has seen each only in that form.

Watch it over a recording, walked through at the pose rate rather than in
real time:

    python -m action --recording rehearsal.mp4 --start 120 --duration 60
"""

import argparse
import itertools
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

import cv2
import numpy as np

from . import model, preprocess, tracking

FPS = 25.0
WINDOW = 4.0
STEP = 1.0

# Share of a window's frames a person must appear in to be classified. Below
# it, most of the sequence would be the zeros that stand for "absent".
MIN_PRESENCE = 0.5

# Two people form a pair when their box centres are, on average over the
# frames they share, closer than this many mean body heights. Touching
# distance with an outstretched arm is about one; a little more keeps an
# approach or a step back in.
PAIR_DISTANCE = 1.5


@dataclass(frozen=True)
class Reading:
    """What one person or pair was doing over one window."""

    at: float                       # end of the window, in the recogniser's clock
    members: tuple[int, ...]        # track ids; one for a person, two for a pair
    probabilities: np.ndarray       # (120,), NTU class order

    def top(self, count: int = 3) -> list[tuple[str, float]]:
        names = model.labels()
        best = np.argsort(self.probabilities)[::-1][:count]
        return [(names[index], float(self.probabilities[index])) for index in best]


def _centre_and_height(body: tracking.Body) -> tuple[np.ndarray, float]:
    x1, y1, x2, y2 = body.box
    return np.array([(x1 + x2) / 2, (y1 + y2) / 2]), float(y2 - y1)


def groups(frames: list[tracking.Frame], *, min_presence: float = MIN_PRESENCE,
           pair_distance: float = PAIR_DISTANCE) -> list[tuple[int, ...]]:
    """The people and the pairs of people in a window worth classifying."""
    if not frames:
        return []
    needed = min_presence * len(frames)
    counts: dict[int, int] = {}
    for frame in frames:
        for track in frame.bodies:
            counts[track] = counts.get(track, 0) + 1
    present = sorted(track for track, count in counts.items() if count >= needed)

    found: list[tuple[int, ...]] = [(track,) for track in present]
    for first, second in itertools.combinations(present, 2):
        distances = []
        for frame in frames:
            if first in frame.bodies and second in frame.bodies:
                (a, height_a), (b, height_b) = (_centre_and_height(frame.bodies[first]),
                                                _centre_and_height(frame.bodies[second]))
                distances.append(np.linalg.norm(a - b) / max((height_a + height_b) / 2, 1.0))
        if len(distances) >= needed and np.mean(distances) < pair_distance:
            found.append((first, second))
    return found


def sequence(frames: list[tracking.Frame], members: tuple[int, ...]):
    """The members' poses over a window, zeros wherever one is absent.

    Returns keypoints (people, frames, 17, 2) and scores (people, frames, 17),
    the layout preprocess.clips() takes.
    """
    keypoints = np.zeros((len(members), len(frames), 17, 2), dtype=np.float32)
    scores = np.zeros((len(members), len(frames), 17), dtype=np.float32)
    for column, frame in enumerate(frames):
        for row, track in enumerate(members):
            body = frame.bodies.get(track)
            if body is not None:
                keypoints[row, column] = body.keypoints
                scores[row, column] = body.scores
    return keypoints, scores


class ActionRecognizer:
    """Pose detection, tracking and classification over a live source.

    The source is anything with `latest()` returning the current BGR frame, as
    capture.VideoStream does; it is read, never opened or closed. Runs on its
    own thread; `observe` and `evaluate` can also be driven by hand, which is
    how a recording is walked through.
    """

    def __init__(self, source=None, *, fps: float = FPS, window: float = WINDOW,
                 step: float = STEP, on_readings: Callable[[list[Reading]], None] | None = None):
        self._source = source
        self._fps = fps
        self._window = window
        self._step = step
        self._on_readings = on_readings
        self.tracker = tracking.BodyTracker(history=max(tracking.HISTORY, 2 * window))
        self.image_shape: tuple[int, int] | None = None
        self.readings: list[Reading] = []
        self.pose_seconds: list[float] = []
        self.classify_seconds: list[float] = []
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None

    def observe(self, frame: np.ndarray, at: float) -> tracking.Frame:
        """Detect and track the bodies in one frame."""
        from orest_pose import model as pose_model

        started = time.perf_counter()
        keypoints, scores = pose_model.detect(frame)
        self.pose_seconds.append(time.perf_counter() - started)
        self.image_shape = frame.shape[:2]
        with self._lock:
            return self.tracker.update(np.asarray(keypoints), np.asarray(scores), at)

    def evaluate(self, at: float) -> list[Reading]:
        """Classify every person and pair over the window ending at `at`."""
        with self._lock:
            frames = self.tracker.window(at - self._window, at)
        found = groups(frames)
        if not found or self.image_shape is None:
            return []

        batch = np.stack([preprocess.clips(*sequence(frames, members), self.image_shape)
                          for members in found])
        started = time.perf_counter()
        probabilities = model.classify(batch)
        self.classify_seconds.append(time.perf_counter() - started)
        readings = [Reading(at, members, row) for members, row in zip(found, probabilities)]
        self.readings = readings
        if self._on_readings:
            self._on_readings(readings)
        return readings

    def start(self) -> "ActionRecognizer":
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        return self

    def _loop(self):
        interval = 1.0 / self._fps
        origin = time.monotonic()
        next_evaluation = origin + self._window
        while not self._stop.is_set():
            started = time.monotonic()
            self.observe(self._source.latest(), started - origin)
            if started >= next_evaluation:
                self.evaluate(started - origin)
                next_evaluation += self._step
            self._stop.wait(max(0.0, interval - (time.monotonic() - started)))

    def close(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5.0)

    def __enter__(self) -> "ActionRecognizer":
        return self.start()

    def __exit__(self, *exception):
        self.close()


def replay(path: str, start: float, duration: float | None, fps: float):
    """Frames of a recording at `fps`, with their position in seconds.

    Reads sequentially and keeps the frames that fall on the sampling grid,
    which is far faster than seeking to each one.
    """
    capture = cv2.VideoCapture(path)
    if not capture.isOpened():
        raise RuntimeError(f"Could not open {path}")
    capture.set(cv2.CAP_PROP_POS_MSEC, start * 1000)
    next_sample = start
    end = start + duration if duration else float("inf")
    try:
        while True:
            ok, frame = capture.read()
            if not ok:
                return
            position = capture.get(cv2.CAP_PROP_POS_MSEC) / 1000
            if position > end:
                return
            if position + 1e-6 >= next_sample:
                yield position, frame
                next_sample += 1.0 / fps
    finally:
        capture.release()


def format_reading(reading: Reading, count: int) -> str:
    who = "+".join(str(member) for member in reading.members)
    classes = " · ".join(f"{name} {probability:.2f}" for name, probability in reading.top(count))
    return f"{reading.at:7.1f}s  [{who:>5}]  {classes}"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--recording", required=True, help="video file to walk through")
    parser.add_argument("--start", type=float, default=0.0, help="seconds into the recording")
    parser.add_argument("--duration", type=float, help="seconds to process (default: to the end)")
    parser.add_argument("--fps", type=float, default=FPS)
    parser.add_argument("--window", type=float, default=WINDOW)
    parser.add_argument("--step", type=float, default=STEP)
    parser.add_argument("--top", type=int, default=3, help="classes shown per reading")
    parser.add_argument("--pairs-only", action="store_true", help="show pairs, not single people")
    args = parser.parse_args(argv)

    recognizer = ActionRecognizer(fps=args.fps, window=args.window, step=args.step)
    next_evaluation = args.start + args.window
    try:
        for position, frame in replay(args.recording, args.start, args.duration, args.fps):
            recognizer.observe(frame, position)
            if position + 1e-6 >= next_evaluation:
                for reading in recognizer.evaluate(position):
                    if not args.pairs_only or len(reading.members) == 2:
                        print(format_reading(reading, args.top), flush=True)
                next_evaluation += args.step
    except KeyboardInterrupt:
        print()
    except RuntimeError as error:
        print(error, file=sys.stderr)
        return 1

    from orest_pose import model as pose_model

    if recognizer.pose_seconds:
        print(f"\npose on {pose_model.active_provider()}: "
              f"{np.median(recognizer.pose_seconds) * 1000:.1f} ms per frame; "
              f"action model on {model.active_provider()}: "
              f"{np.median(recognizer.classify_seconds or [0]) * 1000:.1f} ms per window")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
