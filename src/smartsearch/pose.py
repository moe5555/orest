"""Encoding a video clip as a pose query.

The query half of body search in knowledge/components/02_processing.md: a few
seconds of movement become the search term, and the corpus answers with
segments that match. The clip is read from a file here; a live capture is the
same operation on frames held in memory, which is the next step.

The embedding is computed in this process rather than by WISE. WISE's search
path decodes every visual query as a still image and cannot embed a clip at
all, but its /search_with_feature endpoint accepts a finished vector, so the
encoder that built the index is simply run again on the query. Both sides
import the same `apollon_pose` package, which is what keeps the two in the same
space.
"""

import cv2
import numpy as np
from apollon_pose import keypoints, model

# Seconds of movement a query covers, matching the indexed segment length.
# A query spanning a different duration describes a differently paced movement
# and retrieves poorly, so this is not an independent knob.
CLIP_SECONDS = keypoints.SEGMENT_DURATION


def encode_frames(frames) -> np.ndarray:
    """Encode BGR frames spanning one clip as a pose query vector."""
    return keypoints.segment_embedding(model.detect_segment(frames))


def read_clip(path, start: float = 0.0, seconds: float = CLIP_SECONDS,
              count: int = keypoints.FRAMES_PER_SEGMENT) -> list:
    """Sample evenly spaced frames from a span of a video file.

    Seeking per frame rather than decoding the span sequentially: a query clip
    is a handful of frames and may start anywhere in a long recording, so the
    seek is cheaper than decoding up to it.
    """
    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        raise RuntimeError(f"Could not open {path}")

    frames = []
    try:
        for index in range(count):
            capture.set(cv2.CAP_PROP_POS_MSEC, (start + index * seconds / count) * 1000)
            ok, frame = capture.read()
            if not ok:
                break
            frames.append(frame)
    finally:
        capture.release()

    if not frames:
        raise RuntimeError(f"No frames read from {path} at {start:g}s")
    return frames


def encode_clip(path, start: float = 0.0, seconds: float = CLIP_SECONDS) -> np.ndarray:
    """Encode a span of a video file as a pose query vector."""
    return encode_frames(read_clip(path, start, seconds))
