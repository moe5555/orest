"""Write a WISE project's pose vectors to a numpy file Apollon can read.

The reference corpus of Vorhersehbarkeit (src/sitrep/predictability.py) is the
pose index WISE builds over the rehearsals. WISE keeps it as Faiss shards, and
Apollon's environment carries no Faiss, so this script reads the shards inside
WISE's conda environment and writes plain arrays. Apollon calibrates them.

Runs with the WISE environment's Python; `python -m sitrep.predictability`
calls it so:

    <wise env>/python src/scripts/export_pose_reference.py PROJECT_DIR OUT.npz

Writes OUT.npz:

    vectors     (N, D) float32, one row per indexed segment
    media       (N,) int, the WISE media id each segment was cut from
    start       (N,) float, where the segment starts in its recording, seconds
    paths       (M,) str, the recording behind each media id in `media_ids`
    media_ids   (M,) int
    feature_id  the extractor the vectors came from
"""

import argparse
import glob
import sqlite3
from pathlib import Path

import faiss
import numpy as np

# apollon_pose.EXTRACTOR_ID. Not imported: the package is not needed in WISE's
# environment to read a finished index.
POSE_ID = "apollon/pose/rtmo-s/body7"


def read_store(project: Path, feature_id: str) -> tuple[np.ndarray, np.ndarray]:
    """Every vector a project holds for one extractor, and its vector id."""
    pattern = str(project / "store" / feature_id / "features" / "video-*.faiss")
    shards = sorted(glob.glob(pattern))
    if not shards:
        raise SystemExit(f"no features of {feature_id} under {project}")
    ids, vectors = [], []
    for shard in shards:
        index = faiss.read_index(shard, faiss.IO_FLAG_MMAP | faiss.IO_FLAG_READ_ONLY)
        shard_ids = faiss.vector_to_array(index.id_map)
        ids.append(shard_ids)
        vectors.append(index.reconstruct_batch(shard_ids))
    return np.concatenate(ids), np.concatenate(vectors).astype(np.float32)


def read_segments(project: Path, feature_id: str) -> tuple[dict, dict]:
    """Per vector id its (media id, start), and per media id its recording."""
    database = sqlite3.connect(f"file:{project / 'metadata' / 'internal.db'}?mode=ro", uri=True)
    try:
        segments = {row[0]: (row[1], row[2] or 0.0) for row in database.execute(
            "SELECT id, media_id, timestamp FROM vectors WHERE feature_extractor_id = ?",
            (feature_id,))}
        paths = dict(database.execute("SELECT id, path FROM media"))
    finally:
        database.close()
    return segments, paths


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("project", type=Path, help="WISE project directory")
    parser.add_argument("out", type=Path, help="numpy file to write")
    parser.add_argument("--feature-id", default=POSE_ID)
    args = parser.parse_args(argv)

    ids, vectors = read_store(args.project, args.feature_id)
    segments, paths = read_segments(args.project, args.feature_id)
    known = np.array([int(vector_id) in segments for vector_id in ids])
    if not known.all():
        print(f"{int((~known).sum())} vectors without a segment row skipped")
    ids, vectors = ids[known], vectors[known]

    media = np.array([segments[int(vector_id)][0] for vector_id in ids], dtype=np.int64)
    start = np.array([segments[int(vector_id)][1] for vector_id in ids], dtype=np.float64)
    media_ids = np.array(sorted(paths), dtype=np.int64)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    np.savez(args.out, vectors=vectors, media=media, start=start, media_ids=media_ids,
             paths=np.array([paths[media_id] for media_id in media_ids]),
             feature_id=np.array(args.feature_id))
    print(f"{len(vectors)} vectors of {args.feature_id} from {len(set(media.tolist()))} "
          f"recordings written to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
