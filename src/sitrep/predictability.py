"""Vorhersehbarkeit: how closely a person's movement now resembles the rehearsals.

A person is predictable when the rehearsal corpus already holds a movement like the one
they are making, and unpredictable when it holds nothing like it. The score is
the distance to the nearest neighbour in the archive
(knowledge/background/agent_session_notes/bloom-wise-architecture.md, "Distance
to nearest neighbour is the unpredictability score"): a claim about the
archive, not about the person's state of mind.

Reference. The corpus is the pose index WISE builds over the rehearsals
(apollon_pose, extractor apollon/pose/rtmo-s/body7). Each indexed segment is
four seconds of one body's movement as a unit vector. The live side encodes
each body the action recogniser follows with the same encoder, over the same
four seconds, so both land in one space. The reference is fixed for a run:
the session's own movements are not added, so a value means the same in the
first minute as in the last. Every person is compared with the whole corpus,
not with their own rehearsals only: the index keeps one body per segment and
does not know whose it is.

Calibration. A raw similarity means nothing on its own, so it is read against
the corpus itself. Each corpus segment is matched against the rest of the
corpus, leaving out its own recording within EXCLUDE seconds (a held posture
otherwise finds itself in the overlapping segments beside it). The
distribution of those best matches says how alike a rehearsed movement
typically is to its nearest repetition. A live similarity is placed in that
distribution as a percentile, and the percentile is spread over -5 to +5
through the normal quantile: the corpus median reads 0, half the corpus lies
within about +-1.5, and only the outer EXTREME at either end reaches +-5. A
plain linear map of the percentile would put a rehearsed movement anywhere on
the scale with equal chance; this keeps ordinary rehearsed movement near 0
and the extremes for the clear cases.

Build the reference once per corpus, after WISE has extracted pose features:

    python -m sitrep.predictability --project hitl_database

which exports the vectors through WISE's environment
(src/scripts/export_pose_reference.py), calibrates them and writes REFERENCE.
A run loads it when it exists; without it, Vorhersehbarkeit is not measured.
"""

import argparse
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from statistics import NormalDist

import numpy as np
from apollon_pose import keypoints as pose

from action import tracking

REPO_ROOT = Path(__file__).resolve().parents[2]

# The calibrated reference a run loads.
REFERENCE = Path(os.environ.get("APOLLON_REFERENCE",
                                REPO_ROOT / "data" / "predictability" / "reference.npz"))

EXPORT_SCRIPT = REPO_ROOT / "src" / "scripts" / "export_pose_reference.py"

# The scale, -SCALE (nothing like it rehearsed) to +SCALE (rehearsed often).
SCALE = 5

# Share of corpus segments at each end of the scale: the best matches poorer
# than all but this share read -SCALE, those better than all but it +SCALE.
EXTREME = 0.01

# Seconds around a corpus segment, in its own recording, left out when it is
# matched against the corpus to calibrate. Segments are four seconds long and
# overlap by two, and a posture held for a while matches itself across them.
EXCLUDE = 30.0

# A corpus segment whose vector is shorter than this held no body; the
# encoder returns zeros for it.
MIN_NORM = 0.5

# Points at which the calibration distribution is kept.
QUANTILES = 1001

# Corpus segments matched at once while calibrating, bounding memory.
BATCH = 1024


@dataclass(frozen=True)
class Reference:
    """The rehearsal corpus as unit vectors, and how alike it is to itself."""

    vectors: np.ndarray     # (N, D) float32, unit length
    media: np.ndarray       # (N,) recording each segment was cut from
    start: np.ndarray       # (N,) seconds into that recording
    quantiles: np.ndarray   # (QUANTILES,) best-match similarity within the corpus
    source: str = ""        # what the corpus was built from, for the operator

    def similarity(self, queries: np.ndarray) -> np.ndarray:
        """Each query's similarity to its nearest corpus segment, -1 to 1."""
        queries = np.atleast_2d(np.asarray(queries, dtype=np.float32))
        return (queries @ self.vectors.T).max(axis=1)

    def score(self, similarity) -> np.ndarray:
        """Similarities on the -SCALE to +SCALE scale, as floats."""
        return score(np.asarray(similarity, dtype=np.float64), self.quantiles)

    def save(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        np.savez(path, vectors=self.vectors, media=self.media, start=self.start,
                 quantiles=self.quantiles, source=np.array(self.source))

    @classmethod
    def load(cls, path: Path) -> "Reference":
        with np.load(path) as stored:
            return cls(vectors=stored["vectors"].astype(np.float32), media=stored["media"],
                       start=stored["start"], quantiles=stored["quantiles"],
                       source=str(stored["source"]))


def score(similarity: np.ndarray, quantiles: np.ndarray) -> np.ndarray:
    """Similarities placed in the corpus distribution and spread over the scale."""
    share = np.interp(similarity, quantiles, np.linspace(0.0, 1.0, len(quantiles)))
    # The normal quantile is infinite at 0 and 1; the clip makes both ends
    # read +-SCALE, as anything beyond EXTREME does.
    share = np.clip(share, EXTREME / 10, 1 - EXTREME / 10)
    normal = NormalDist()
    spread = np.array([normal.inv_cdf(float(value)) for value in np.ravel(share)])
    scaled = SCALE * spread / normal.inv_cdf(1 - EXTREME)
    return np.clip(scaled, -SCALE, SCALE).reshape(np.shape(similarity))


def nearest_within(vectors: np.ndarray, media: np.ndarray, start: np.ndarray,
                   exclude: float = EXCLUDE, batch: int = BATCH) -> np.ndarray:
    """Each segment's similarity to its nearest other segment in the corpus,
    leaving out its own recording within `exclude` seconds."""
    best = np.empty(len(vectors), dtype=np.float32)
    for first in range(0, len(vectors), batch):
        rows = slice(first, first + batch)
        similarity = vectors[rows] @ vectors.T
        nearby = ((media[rows, None] == media[None, :])
                  & (np.abs(start[rows, None] - start[None, :]) < exclude))
        similarity[nearby] = -np.inf
        best[rows] = similarity.max(axis=1)
    return best


def calibrate(vectors: np.ndarray, media: np.ndarray, start: np.ndarray,
              source: str = "", exclude: float = EXCLUDE) -> Reference:
    """A reference from a corpus's segment vectors, empty segments dropped."""
    vectors = np.asarray(vectors, dtype=np.float32)
    norms = np.linalg.norm(vectors, axis=1)
    kept = norms >= MIN_NORM
    vectors = vectors[kept] / norms[kept, None]
    media, start = np.asarray(media)[kept], np.asarray(start, dtype=np.float64)[kept]
    best = nearest_within(vectors, media, start, exclude)
    # A segment alone in its recording, with nothing outside the excluded
    # span, has no match to measure.
    best = best[np.isfinite(best)]
    if len(best) == 0:
        raise ValueError("no corpus segment has a match outside its own span")
    quantiles = np.quantile(best, np.linspace(0.0, 1.0, QUANTILES))
    return Reference(vectors, media, start, quantiles, source)


def window_embedding(frames: list[tracking.Frame], track: int) -> np.ndarray | None:
    """One body's movement over a window of tracked frames, encoded as the
    corpus is (apollon_pose.keypoints.segment_embedding), or None if the body
    was never usable in it."""
    empty = (np.zeros((0, pose.NUM_KEYPOINTS, 2), np.float32),
             np.zeros((0, pose.NUM_KEYPOINTS), np.float32))
    detections = []
    for frame in frames:
        body = frame.bodies.get(track)
        detections.append(empty if body is None else (body.keypoints[None], body.scores[None]))
    vector = pose.segment_embedding(detections)
    return vector if np.linalg.norm(vector) > 0 else None


def available(path: Path = REFERENCE) -> bool:
    """Whether a reference has been built. Without it a run does not measure
    Vorhersehbarkeit."""
    return path.exists()


def load(path: Path = REFERENCE) -> Reference:
    return Reference.load(path)


def build(project: str, out: Path = REFERENCE, exclude: float = EXCLUDE) -> Reference:
    """Export a WISE project's pose vectors, calibrate them and save the reference."""
    from smartsearch import config

    project_dir = config.project_dir(project)
    with tempfile.TemporaryDirectory() as scratch:
        exported = Path(scratch) / "vectors.npz"
        subprocess.run([str(config.python()), str(EXPORT_SCRIPT), str(project_dir),
                        str(exported)], check=True)
        with np.load(exported) as stored:
            vectors, media, start = stored["vectors"], stored["media"], stored["start"]
            feature_id = str(stored["feature_id"])
    reference = calibrate(vectors, media, start, f"{project} · {feature_id}", exclude)
    reference.save(out)
    return reference


def describe(reference: Reference) -> str:
    """The reference's size and calibration, for the operator."""
    def at(share: float) -> float:
        return float(np.interp(share, np.linspace(0, 1, len(reference.quantiles)),
                               reference.quantiles))

    return (f"{len(reference.vectors)} segments from {len(np.unique(reference.media))} "
            f"recordings ({reference.source}); nearest repetition: median similarity "
            f"{at(0.5):.2f}, {EXTREME:.0%} below {at(EXTREME):.2f}, "
            f"{EXTREME:.0%} above {at(1 - EXTREME):.2f}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--project", required=True, help="WISE project with pose features")
    parser.add_argument("--out", type=Path, default=REFERENCE,
                        help=f"reference to write (default: {REFERENCE})")
    parser.add_argument("--exclude", type=float, default=EXCLUDE,
                        help=f"seconds around a segment left out when calibrating "
                             f"(default: {EXCLUDE:g})")
    args = parser.parse_args(argv)
    try:
        reference = build(args.project, args.out, args.exclude)
    except (subprocess.CalledProcessError, ValueError, RuntimeError) as error:
        print(error, file=sys.stderr)
        return 1
    print(describe(reference))
    print(f"written to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
