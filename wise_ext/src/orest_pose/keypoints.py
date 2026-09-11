"""Turning detected skeletons into a vector that can be compared by cosine.

Pure numpy, no model and no video. This is the half of the pose pipeline that
has to behave identically when indexing the corpus and when encoding a live
capture, so it is kept free of anything environment-specific and is covered by
tests that need neither a GPU nor a camera.

The embedding describes a movement rather than a posture. A single frame's
skeleton is noisy and semantically thin, and the specification asks for a
captured sequence as the query — "press a button, then press a button again
after a few seconds to capture that live sequence"
(knowledge/components/02_processing.md). Frames spanning the segment are
therefore normalised individually and concatenated, so what is compared is the
shape of the movement over several seconds.
"""

import numpy as np

# COCO-17 keypoint order, as RTMO emits it.
COCO_KEYPOINTS = (
    "nose", "left_eye", "right_eye", "left_ear", "right_ear",
    "left_shoulder", "right_shoulder", "left_elbow", "right_elbow",
    "left_wrist", "right_wrist", "left_hip", "right_hip",
    "left_knee", "right_knee", "left_ankle", "right_ankle",
)

NUM_KEYPOINTS = len(COCO_KEYPOINTS)

LEFT_SHOULDER, RIGHT_SHOULDER = 5, 6
LEFT_HIP, RIGHT_HIP = 11, 12

# Frames sampled across one segment. Sixteen over four seconds is 4 fps, fine
# enough to separate a fall from a slow descent, which 2 fps blurs together.
FRAMES_PER_SEGMENT = 16

# Seconds spanned by one indexed segment, and the gap between consecutive ones.
# The overlap guarantees any movement shorter than the stride falls wholly
# inside at least one segment rather than being split across two.
SEGMENT_DURATION = 4.0
SEGMENT_OVERLAP = 2.0

# Below this, a keypoint is treated as not seen.
MIN_KEYPOINT_SCORE = 0.3

# A skeleton carrying fewer confident keypoints than this is not a usable body.
MIN_VISIBLE_KEYPOINTS = 4

# Guards the division when a body is so foreshortened that its torso projects to
# almost nothing, which would otherwise magnify pixel noise without limit.
MIN_SCALE_PIXELS = 1e-3

# Length of one frame's contribution: x and y per keypoint.
FRAME_DIMS = NUM_KEYPOINTS * 2

# Length of a complete segment embedding.
EMBEDDING_DIMS = FRAME_DIMS * FRAMES_PER_SEGMENT


def visible(scores: np.ndarray) -> np.ndarray:
    """Mask of keypoints confident enough to use."""
    return scores >= MIN_KEYPOINT_SCORE


def body_scale(keypoints: np.ndarray, seen: np.ndarray) -> float:
    """Size of a skeleton in pixels, used to make the embedding scale-free.

    Torso length is preferred because it is the most rigid measurement on the
    body: unlike a bounding box it does not grow when an arm is raised or a leg
    extended, so the same posture measures the same whether or not the limbs are
    spread. The bounding box is the fallback for skeletons whose shoulders or
    hips were not seen.
    """
    shoulders = _midpoint(keypoints, seen, LEFT_SHOULDER, RIGHT_SHOULDER)
    hips = _midpoint(keypoints, seen, LEFT_HIP, RIGHT_HIP)
    if shoulders is not None and hips is not None:
        torso = float(np.linalg.norm(shoulders - hips))
        if torso > MIN_SCALE_PIXELS:
            return torso

    points = keypoints[seen]
    if len(points) < 2:
        return 0.0
    return float(np.linalg.norm(points.max(axis=0) - points.min(axis=0)))


def _midpoint(keypoints: np.ndarray, seen: np.ndarray, left: int, right: int):
    """Centre of a symmetric pair, or of whichever side was seen."""
    pair = [index for index in (left, right) if seen[index]]
    if not pair:
        return None
    return keypoints[pair].mean(axis=0)


def _origin(keypoints: np.ndarray, seen: np.ndarray) -> np.ndarray:
    """Point the skeleton is centred on, so position in frame drops out.

    The hips are the body's root. Where they were not seen, the centroid of what
    was keeps the skeleton near the origin rather than letting it drift by the
    full width of the image.
    """
    hips = _midpoint(keypoints, seen, LEFT_HIP, RIGHT_HIP)
    return hips if hips is not None else keypoints[seen].mean(axis=0)


def normalise_pose(keypoints: np.ndarray, scores: np.ndarray) -> np.ndarray:
    """Express one skeleton as 34 numbers, free of position and size.

    Two people performing the same action at opposite ends of the stage, one
    near the camera and one far from it, must produce nearly the same vector;
    otherwise the index retrieves by where a body was rather than what it did.

    Keypoints that were not seen are set to the origin. That conflates an
    unobserved joint with one resting at hip height, which is the cost of
    keeping the vector to two numbers per keypoint.
    """
    seen = visible(scores)
    if seen.sum() < MIN_VISIBLE_KEYPOINTS:
        return np.zeros(FRAME_DIMS, dtype=np.float32)

    scale = body_scale(keypoints, seen)
    if scale <= MIN_SCALE_PIXELS:
        return np.zeros(FRAME_DIMS, dtype=np.float32)

    centred = (keypoints - _origin(keypoints, seen)) / scale
    centred[~seen] = 0.0
    return centred.astype(np.float32).reshape(FRAME_DIMS)


def primary_body(keypoints: np.ndarray, scores: np.ndarray) -> int | None:
    """Index of the body a segment is represented by, or None if there is none.

    WISE stores one vector per segment, so one skeleton per frame has to stand
    for the frame. The largest is chosen: on a rehearsal stage the nearest body
    is the one the camera was pointed at. Everyone else in shot is dropped,
    which is the main known limitation of this extractor.
    """
    best, best_scale = None, 0.0
    for index in range(len(keypoints)):
        seen = visible(scores[index])
        if seen.sum() < MIN_VISIBLE_KEYPOINTS:
            continue
        scale = body_scale(keypoints[index], seen)
        if scale > best_scale:
            best, best_scale = index, scale
    return best


def segment_embedding(frames) -> np.ndarray:
    """Encode a sequence of detections as one unit-length vector.

    Each element of `frames` is the (keypoints, scores) detected in one frame,
    shaped (people, 17, 2) and (people, 17). Frames are resampled to a fixed
    count so that segments of slightly different length stay comparable, and the
    result is L2-normalised because the index compares by inner product.

    A segment in which no body was ever found returns zeros, which retrieves
    nothing rather than matching arbitrarily.
    """
    chosen = []
    for keypoints, scores in frames:
        keypoints = np.asarray(keypoints, dtype=np.float32)
        scores = np.asarray(scores, dtype=np.float32)
        if keypoints.ndim != 3 or len(keypoints) == 0:
            chosen.append(np.zeros(FRAME_DIMS, dtype=np.float32))
            continue
        index = primary_body(keypoints, scores)
        chosen.append(
            np.zeros(FRAME_DIMS, dtype=np.float32) if index is None
            else normalise_pose(keypoints[index], scores[index])
        )

    if not chosen:
        return np.zeros(EMBEDDING_DIMS, dtype=np.float32)

    vector = np.concatenate(_resample(chosen, FRAMES_PER_SEGMENT))
    norm = float(np.linalg.norm(vector))
    return vector / norm if norm > 0 else vector


def _resample(items: list, count: int) -> list:
    """Pick `count` entries spread evenly across `items`, repeating if short."""
    if len(items) == count:
        return items
    positions = np.linspace(0, len(items) - 1, count).round().astype(int)
    return [items[position] for position in positions]
