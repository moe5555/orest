"""What a person looks like from any side: the second identity cue beside the face.

Faces name people only while a face is visible and large enough
(presence.MIN_FACE). Seen from behind, turned away or far off, a person is a
"Körper", and since body tracks end a second after a person is lost
(action/tracking.FORGET), someone who leaves and returns comes back unnamed.
Their appearance, the clothes, colours and build, is visible from every side.

OSNet-AIN x1.0, a person re-identification network trained on MSMT17 for use
on footage it was not trained on (data/models/osnet/SOURCE.md), turns a body's
crop into a 512-value description in which two views of the same person lie
close together. `describe` measures the bodies in a frame; `Appearances` is a
run's memory of what each named person looks like and matches a description
against it. The action recogniser weighs a match as one more vote for a name
beside the faces (actions.ActionRatings), so face and appearance decide one
name together.

The memory learns only from bodies whose name is sure (actions.py says which)
and holds the latest views of each person, so a costume change is picked up
once the person is named again. Nothing is written to disk.

Measure how well appearance tells the people of a recording apart:

    python -m sitrep.appearance recording.mp4 [recording.mp4 ...]
"""

import argparse
import os
import sys
import threading
import time
from collections import deque
from pathlib import Path

import cv2
import numpy as np

from action import model as action_model
from action import recognizer, tracking

REPO_ROOT = Path(__file__).resolve().parents[2]

MODEL_DIR = Path(os.environ.get("APOLLON_REID_MODEL_DIR",
                                REPO_ROOT / "data" / "models" / "osnet"))
MODEL_FILE = "osnet_ain_x1_0_msmt17.onnx"

# The network's input and the normalisation it was trained with
# (src/scripts/export_osnet.py, whose preprocessing this repeats).
HEIGHT, WIDTH = 256, 128
MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)

# Margin added around a body's box, as a share of its height. The pose box
# runs from joint to joint; the head, feet and the clothes' outline lie
# slightly outside it.
PAD = 0.08

# Bodies shorter than this many pixels are not described: a crop that small
# is mostly upscaled blur.
MIN_HEIGHT = 80

# Views kept per person, the latest first to go, and at most one learned per
# LEARN_INTERVAL seconds of recogniser time, so the memory spans minutes of a
# scene rather than a few seconds of one pose.
KEEP = 30
LEARN_INTERVAL = 1.0

# A description is matched to a person when its closest view of them reaches
# THRESHOLD and beats every other person's by MARGIN. Two people dressed alike
# then match no one rather than the wrong one. Measured on four two-person
# scenes of the corpus, matching each view against views of the same people on
# other body tracks at least 10 s earlier: 89-98 % right, 0-1 % wrong, the
# rest unnamed (changelog.md, 2026-10-06).
THRESHOLD = 0.65
MARGIN = 0.05

_lock = threading.Lock()
_session = None


def available() -> bool:
    """Whether the model is installed. Without it a run names people by face alone."""
    return (MODEL_DIR / MODEL_FILE).exists()


def session():
    """The shared inference session, created on first use."""
    global _session
    with _lock:
        if _session is None:
            import onnxruntime

            path = MODEL_DIR / MODEL_FILE
            if not path.exists():
                raise RuntimeError(
                    f"No appearance model at {path}. Export it with "
                    f"src/scripts/export_osnet.py, or set APOLLON_REID_MODEL_DIR.")
            _session = onnxruntime.InferenceSession(str(path), providers=action_model.providers())
        return _session


def preprocess(crop: np.ndarray) -> np.ndarray:
    """A BGR crop as the network takes it, (3, HEIGHT, WIDTH)."""
    resized = cv2.resize(crop, (WIDTH, HEIGHT), interpolation=cv2.INTER_LINEAR)
    rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
    return ((rgb - MEAN) / STD).transpose(2, 0, 1)


def crop(image: np.ndarray, box) -> np.ndarray | None:
    """A body's box from a frame with PAD around it, or None if too small."""
    x1, y1, x2, y2 = (float(value) for value in box)
    if y2 - y1 < MIN_HEIGHT:
        return None
    margin = PAD * (y2 - y1)
    height, width = image.shape[:2]
    left, top = max(0, int(x1 - margin)), max(0, int(y1 - margin))
    right, bottom = min(width, int(x2 + margin)), min(height, int(y2 + margin))
    if right - left < 2 or bottom - top < 2:
        return None
    return image[top:bottom, left:right]


def embed(crops: list[np.ndarray]) -> np.ndarray:
    """Unit-length descriptions of BGR crops, (len(crops), 512)."""
    batch = np.stack([preprocess(each) for each in crops]).astype(np.float32)
    features = session().run(None, {"images": batch})[0]
    return features / np.linalg.norm(features, axis=1, keepdims=True)


def describe(image: np.ndarray, bodies: dict[int, tracking.Body]) -> dict[int, np.ndarray]:
    """A description of each body large enough to describe, by track id."""
    crops = {track: crop(image, body.box) for track, body in bodies.items()
             if body.box is not None}
    crops = {track: each for track, each in crops.items() if each is not None}
    if not crops:
        return {}
    return dict(zip(crops, embed(list(crops.values()))))


class Latest:
    """The newest camera frame and the bodies tracked in it.

    Fed by the recogniser's `on_frame` at the pose rate; read once per naming
    step, so describing costs one network call a second rather than one per
    frame.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._latest: tuple[np.ndarray, tracking.Frame] | None = None

    def observe(self, image: np.ndarray, frame: tracking.Frame):
        with self._lock:
            self._latest = (image, frame)

    def take(self) -> tuple[np.ndarray, tracking.Frame] | None:
        with self._lock:
            return self._latest

    def clear(self):
        with self._lock:
            self._latest = None


class Appearances:
    """A run's memory of what each named person looks like."""

    def __init__(self, keep: int = KEEP, interval: float = LEARN_INTERVAL,
                 threshold: float = THRESHOLD, margin: float = MARGIN):
        self._keep = keep
        self._interval = interval
        self._threshold = threshold
        self._margin = margin
        self._views: dict[str, deque[np.ndarray]] = {}
        self._learned_at: dict[str, float] = {}
        self._lock = threading.Lock()

    def learn(self, name: str, description: np.ndarray, at: float):
        """Keep a view of `name`, unless one was kept less than the interval ago."""
        with self._lock:
            if at - self._learned_at.get(name, -np.inf) < self._interval:
                return
            self._learned_at[name] = at
            self._views.setdefault(name, deque(maxlen=self._keep)).append(description)

    def match(self, description: np.ndarray) -> tuple[str | None, float]:
        """The person a description is of, and its similarity to their closest view.

        None when no one reaches the threshold, or when a second person comes
        within the margin of the first.
        """
        with self._lock:
            scores = {name: float(np.max(np.stack(views) @ description))
                      for name, views in self._views.items() if views}
        if not scores:
            return None, 0.0
        ranked = sorted(scores.items(), key=lambda item: -item[1])
        name, best = ranked[0]
        runner_up = ranked[1][1] if len(ranked) > 1 else -1.0
        if best < self._threshold or best - runner_up < self._margin:
            return None, best
        return name, best

    def counts(self) -> dict[str, int]:
        with self._lock:
            return {name: len(views) for name, views in self._views.items()}

    def clear(self):
        """Forget every view."""
        with self._lock:
            self._views = {}
            self._learned_at = {}


# Measurement ------------------------------------------------------------------

# Face similarity at which a face joins an identity in the measurement: the
# face tracker's own link threshold (presence.LINK). Identities whose mean
# faces still reach MERGE are one person seen from two angles: across two
# hours of stage footage no two different people exceeded 0.35 (presence.py).
FACE_LINK = 0.45
MERGE = 0.35

# An identity counts as one of the scene's people when it holds at least this
# share of the samples with a face; the rest are bystanders and stray faces.
PERSON_SHARE = 0.1

# Seconds between the samples the measurement takes, and the separation in
# time below which two samples are not compared: views a second apart are
# nearly the same picture and say nothing about recognising someone later.
SAMPLE_EVERY = 1.0
APART = 10.0


def _samples(path: str, fps: float, start: float, seconds: float | None):
    """(time, body track, face vector or None, description) per body per sample.

    The face on a body stands in for the name an enrolled cast would give
    (`_identities`).
    """
    from face import detect, embed as face_embed

    from . import actions, presence

    tracker = recognizer.ActionRecognizer()
    rows = []
    next_sample = start
    for position, frame in recognizer.replay(path, start, seconds, fps):
        tracked = tracker.observe(frame, position)
        if position < next_sample:
            continue
        next_sample += SAMPLE_EVERY
        bodies = {track: tracked.bodies[track] for track in recognizer.tallest(tracked)}
        faces = [face for face in detect.detect(frame) if face.size >= presence.MIN_FACE]
        vectors = face_embed.embed(frame, faces) if faces else np.empty((0, 512))
        on_body = actions.name_bodies(tracking.Frame(position, bodies),
                                      [(face.bbox, str(index)) for index, face in enumerate(faces)])
        for track, description in describe(frame, bodies).items():
            index = on_body.get(track)
            rows.append((position, track, vectors[int(index)] if index is not None else None,
                         description))
    return rows


def _identities(vectors: list[np.ndarray]) -> list[int]:
    """One identity per face: faces linked greedily, then identities merged
    whose mean faces are as close as only one person's are."""
    sums: list[np.ndarray] = []
    labels = []
    for vector in vectors:
        scores = [float(total @ vector / np.linalg.norm(total)) for total in sums]
        if scores and max(scores) >= FACE_LINK:
            index = int(np.argmax(scores))
            sums[index] = sums[index] + vector
        else:
            index = len(sums)
            sums.append(vector.copy())
        labels.append(index)
    parent = list(range(len(sums)))

    def root(index):
        while parent[index] != index:
            index = parent[index]
        return index

    merged = True
    while merged:
        merged = False
        roots = sorted({root(index) for index in range(len(sums))})
        totals = {r: sum(sums[i] for i in range(len(sums)) if root(i) == r) for r in roots}
        for left in roots:
            for right in roots:
                if left < right and root(left) != root(right):
                    a, b = totals[left], totals[right]
                    if float(a @ b / (np.linalg.norm(a) * np.linalg.norm(b))) >= MERGE:
                        parent[root(right)] = root(left)
                        merged = True
    return [root(label) for label in labels]


def _report(rows) -> str:
    faced = [row for row in rows if row[2] is not None]
    identities = _identities([row[2] for row in faced])
    counts = {}
    for identity in identities:
        counts[identity] = counts.get(identity, 0) + 1
    people = {identity for identity, count in counts.items()
              if count >= PERSON_SHARE * len(faced)}
    labelled = [(row[0], row[1], identity, row[3])
                for row, identity in zip(faced, identities) if identity in people]
    sizes = sorted((counts[person] for person in people), reverse=True)
    lines = [f"  {len(rows)} body samples, {len(faced)} with a face; {len(people)} people "
             f"({', '.join(map(str, sizes))} samples), {len(rows) - len(labelled)} unlabelled"]
    if len(people) < 2:
        return "\n".join(lines + ["  fewer than two people with faces: nothing to compare"])

    times = np.array([row[0] for row in labelled])
    who = np.array([row[2] for row in labelled])
    tracks = np.array([row[1] for row in labelled])
    descriptions = np.stack([row[3] for row in labelled])
    similarity = descriptions @ descriptions.T
    apart = np.abs(times[:, None] - times[None, :]) >= APART
    same = (who[:, None] == who[None, :]) & apart
    different = (who[:, None] != who[None, :]) & apart
    for title, mask in (("same person", same), ("different people", different)):
        values = similarity[np.triu(mask, 1)]
        if values.size:
            p5, p50, p95 = np.percentile(values, [5, 50, 95])
            lines.append(f"  {title:<17} p5 {p5:.2f}  median {p50:.2f}  p95 {p95:.2f}  ({values.size} pairs)")

    # Recognising someone on a body track other than the ones they were
    # learned on, as after leaving and returning: each sample is matched
    # against the latest KEEP views of each person on other tracks, at least
    # APART seconds earlier.
    lines.append("  threshold margin   right  wrong  none")
    for threshold in (0.5, 0.55, 0.6, 0.65, 0.7, 0.75):
        for margin in (0.0, 0.05, 0.1):
            right = wrong = none = 0
            for index in range(len(labelled)):
                earlier = (times < times[index] - APART) & (tracks != tracks[index])
                best = {}
                for person in people:
                    mask = earlier & (who == person)
                    if mask.any():
                        best[person] = float(similarity[index, mask][-KEEP:].max())
                if not best:
                    continue
                ranked = sorted(best.values(), reverse=True)
                top = max(best, key=best.get)
                runner_up = ranked[1] if len(ranked) > 1 else -1.0
                if best[top] < threshold or best[top] - runner_up < margin:
                    none += 1
                elif top == who[index]:
                    right += 1
                else:
                    wrong += 1
            total = max(1, right + wrong + none)
            lines.append(f"  {threshold:9.2f} {margin:6.2f}  {right / total:6.1%} "
                         f"{wrong / total:6.1%} {none / total:6.1%}")
    return "\n".join(lines)


def _save(rows, path: Path):
    np.savez_compressed(
        path, times=np.array([row[0] for row in rows]), tracks=np.array([row[1] for row in rows]),
        faced=np.array([row[2] is not None for row in rows]),
        faces=np.stack([row[2] if row[2] is not None else np.zeros(512) for row in rows]),
        descriptions=np.stack([row[3] for row in rows]))


def _load(path: str):
    saved = np.load(path)
    return [(float(t), int(track), face if has else None, description)
            for t, track, has, face, description in zip(
                saved["times"], saved["tracks"], saved["faced"], saved["faces"],
                saved["descriptions"])]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("recordings", nargs="+",
                        help="video files, or samples saved with --save (.npz)")
    parser.add_argument("--fps", type=float, default=5.0,
                        help="pose tracking rate over the recording (default: 5)")
    parser.add_argument("--start", type=float, default=0.0)
    parser.add_argument("--seconds", type=float, help="length to measure (default: all)")
    parser.add_argument("--save", type=Path, metavar="DIR",
                        help="keep each recording's samples here, to report on again")
    args = parser.parse_args(argv)

    for path in args.recordings:
        started = time.monotonic()
        if path.endswith(".npz"):
            rows = _load(path)
        else:
            rows = _samples(path, args.fps, args.start, args.seconds)
            if args.save:
                args.save.mkdir(parents=True, exist_ok=True)
                _save(rows, args.save / f"{Path(path).stem}.npz")
        print(f"{Path(path).name}  ({time.monotonic() - started:.0f} s)")
        print(_report(rows), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
