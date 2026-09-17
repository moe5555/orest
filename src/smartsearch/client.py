"""Retrieval against a running WISE server.

Covers the query half of Smart Search in knowledge/components/02_processing.md.
WISE's search API is unauthenticated JSON over HTTP, which is the boundary
between Orest's environment and WISE's.

Every search returns a flat list of Hit. WISE splits its response by modality —
the visual stream of videos, the audio stream of videos, still images — each
with its own result block and a separate table of media descriptions; a single
ranked list is what the operator UI, the OSC bridge and hybrid ranking all
consume (knowledge/components/02_processing.md, "UI for Rehearsals &
Performances").
"""

import base64
from dataclasses import dataclass
from typing import Sequence

import httpx
import numpy as np

from . import config

# Search targets, as WISE names them. "video" is the visual stream of video
# files and "av" their audio stream; the two are indexed by different models and
# are searched separately.
VIDEO = "video"
AUDIO = "av"
IMAGE = "image"

# Which modality each search target draws its feature extractors from.
_MODALITY = {VIDEO: "video", AUDIO: "audio", "audio": "audio", IMAGE: "image"}

# The two forms every result block carries: neighbouring matches merged into one
# playable moment, and the individual indexed windows behind them. A window is
# 4 seconds in both indices. Merged spans are what browsing wants, but a long
# run of matching windows collapses into one span of a minute or more, and the
# span's bounds shift with the query, so a moment found twice is described
# differently each time (changelog.md, 2026-09-17).
MERGED = "merged_windows"
UNMERGED = "unmerged_windows"

# Result blocks in a search response, and the media table each one refers to.
_BLOCKS = (
    ("video_results", "videos", VIDEO),
    ("video_audio_results", "videos", AUDIO),
    ("image_results", "images", IMAGE),
)

# How many vectors to retrieve per moment asked for. WISE ranks individual
# vectors — one per sampled frame — and merges neighbouring hits into playable
# segments afterwards, so a run of frames from one moment collapses to a single
# result. Retrieving only as many vectors as the caller wants moments therefore
# returns far fewer. Measured at roughly 7 vectors per moment on rehearsal
# footage at the default 2 fps sampling.
_CANDIDATES_PER_HIT = 10

# Fewest vectors worth retrieving, so a small request still spans a few moments.
_MIN_CANDIDATES = 50

# WISE's own ceiling on results per request (max_search_results).
_MAX_CANDIDATES = 1000


@dataclass(frozen=True)
class Hit:
    """One retrieved moment: a time range in a media file, and its score."""

    media_id: str
    filename: str
    ts: float
    te: float
    score: float
    target: str
    vector_id: str
    media_url: str
    thumbnail_url: str

    @property
    def seconds(self) -> float:
        return self.te - self.ts


def timecode(seconds: float) -> str:
    """Format a position in a recording as H:MM:SS."""
    total = int(seconds)
    return f"{total // 3600}:{total % 3600 // 60:02d}:{total % 60:02d}"


class Wise:
    """Client for one WISE project.

    The project name is the basename of its directory and is a required segment
    of every URL path.
    """

    def __init__(self, project: str | None = None, base_url: str | None = None,
                 timeout: float = 120.0):
        self.project = project or config.DEFAULT_PROJECT
        self.base_url = (base_url or config.base_url()).rstrip("/")
        self.root = f"{self.base_url}/{self.project}"
        self._client = httpx.Client(timeout=timeout)

    def close(self):
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        self.close()

    def info(self) -> dict:
        """Project statistics and the feature extractors available per modality.

        Worth reading before anything else: a project whose extraction produced
        nothing still serves, reporting zero vectors and no search targets
        (knowledge/background/wise_learnings.md, section 6).
        """
        response = self._client.get(f"{self.root}/info")
        response.raise_for_status()
        return response.json()

    def extractors(self, target: str = VIDEO) -> list[str]:
        """Feature extractor ids indexed for a search target, best default first."""
        return self.info().get("search_targets", {}).get(_MODALITY[target], [])

    def _resolve_extractor(self, target: str, feature_extractor_id: str | None) -> str:
        if feature_extractor_id:
            return feature_extractor_id
        available = self.extractors(target)
        if not available:
            raise RuntimeError(
                f"Project {self.project!r} has no search index for {target!r}. "
                f"Run extraction and create-index first."
            )
        return available[0]

    def _window(self, limit: int, candidates: int | None, merged: bool = True) -> int:
        """How many vectors to retrieve to yield `limit` results.

        Unmerged results are one per vector, so no allowance for collapsing is
        needed.
        """
        if candidates is None:
            candidates = (max(limit * _CANDIDATES_PER_HIT, _MIN_CANDIDATES) if merged
                          else limit)
        return min(candidates, _MAX_CANDIDATES)

    def search(
        self,
        text: str | Sequence[str] | None = None,
        *,
        images: Sequence[bytes] = (),
        audio: Sequence[bytes] = (),
        negative_text: str | Sequence[str] | None = None,
        target: str = VIDEO,
        feature_extractor_id: str | None = None,
        limit: int = 20,
        candidates: int | None = None,
        metadata_filter: Sequence[str] = (),
        add_prefix: bool = True,
        merged: bool = True,
    ) -> list[Hit]:
        """Search one index by text, uploaded stills, uploaded audio, or a mix.

        Returns at most `limit` moments, drawn from `candidates` retrieved
        vectors.

        Several query terms are combined as a weighted average of their vectors,
        with text weighted above media and negative terms subtracted; the
        weights are server configuration. WISE accepts at most five terms.

        add_prefix wraps text in the server's caption template, which matches how
        the default CLIP model was trained. It is not appropriate for every
        model indexed in a project.
        """
        params: list[tuple[str, str]] = [
            ("search_in", target),
            ("feature_extractor_id", self._resolve_extractor(target, feature_extractor_id)),
            ("start", "0"),
            ("end", str(self._window(limit, candidates, merged))),
            ("add_prefix", str(bool(add_prefix)).lower()),
        ]
        params += [("text_queries", value) for value in _as_sequence(text)]
        params += [("negative_text_queries", value) for value in _as_sequence(negative_text)]
        params += [("metadata_filter", value) for value in metadata_filter]

        files = [("image_file_queries", (f"image-{i}", data)) for i, data in enumerate(images)]
        files += [("audio_file_queries", (f"audio-{i}", data)) for i, data in enumerate(audio)]

        response = self._client.post(f"{self.root}/search", params=params, files=files or None)
        response.raise_for_status()
        return self._hits(response.json(), merged)[:limit]

    def search_vector(
        self,
        vector: np.ndarray,
        *,
        target: str = VIDEO,
        feature_extractor_id: str | None = None,
        limit: int = 20,
        candidates: int | None = None,
        metadata_filter: Sequence[str] = (),
        merged: bool = True,
    ) -> list[Hit]:
        """Search with an embedding computed outside WISE.

        The vector must lie in the space of the named extractor's index, which
        in practice means it was produced by the same model.
        """
        query = np.ascontiguousarray(vector, dtype=np.float32).reshape(1, -1)
        params: list[tuple[str, str]] = [
            ("search_in", target),
            ("feature_extractor_id", self._resolve_extractor(target, feature_extractor_id)),
            ("start", "0"),
            ("end", str(self._window(limit, candidates, merged))),
        ]
        params += [("metadata_filter", value) for value in metadata_filter]

        body = {
            "term_id": "query",
            "is_negative": False,
            "vector": {
                "content": base64.b64encode(query.tobytes()).decode("ascii"),
                "shape": list(query.shape),
            },
        }
        response = self._client.post(
            f"{self.root}/search_with_feature", params=params, json=body
        )
        response.raise_for_status()
        return self._hits(response.json(), merged)[:limit]

    def _hits(self, payload: dict, merged: bool = True) -> list[Hit]:
        """Flatten a search response into one list, ranked by score."""
        hits = []
        for block_name, media_name, target in _BLOCKS:
            block = payload.get(block_name)
            if not block:
                continue
            media = block.get(media_name, {})
            rows = block.get(MERGED if merged else UNMERGED) or []
            for row in rows:
                media_id = str(row["media_id"])
                hits.append(Hit(
                    media_id=media_id,
                    filename=media.get(media_id, {}).get("filename", ""),
                    ts=float(row.get("ts", 0.0)),
                    te=float(row.get("te", 0.0)),
                    score=float(row["distance"]),
                    target=target,
                    vector_id=str(row["vector_id"]),
                    media_url=f"{self.root}/{row['link']}",
                    thumbnail_url=f"{self.root}/{row['thumbnail']}",
                ))
        hits.sort(key=lambda hit: hit.score, reverse=True)
        return hits


def _as_sequence(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    return list(value)
