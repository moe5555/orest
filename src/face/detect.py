"""SCRFD face detection.

One pass over a frame returns every face with a box, a confidence and the five
landmarks (eyes, nose, mouth corners) that `embed` aligns on. The landmarks are
why a face detector is used at all rather than the body keypoints the pose
encoder already produces: a COCO-17 skeleton locates a head, but ArcFace needs
the face squared up to a canonical position, which takes eye and mouth points.

SCRFD is anchor-based and emits its predictions as distances from anchor
centres, at three strides. Decoding is the usual distance-to-box conversion,
done here rather than pulled in with the `insightface` package.
"""

import cv2
import numpy as np

from . import model

# Side of the square the detector runs on. Faces on a wide rehearsal stage are
# small in frame, and detection recall falls off sharply once a face is under
# roughly 20 pixels; 640 is the size SCRFD was trained at, and larger inputs
# are how distant faces are reached (see `detect(..., size=)`).
INPUT_SIZE = 640

# Feature map strides, in the order the model emits them.
STRIDES = (8, 16, 32)

# Anchors per feature map cell.
ANCHORS = 2

# Detections below this are discarded. Higher than a general-purpose default:
# a weak detection produces a poorly aligned crop and therefore an embedding
# that matches nothing, so admitting it only adds noise.
#
# Measured on stage footage, 341 detections: 4.1% scored between 0.50 and 0.60,
# and that band holds the stage fabric and backs of heads the detector mistakes
# for faces, along with some real faces covered by a hand. Everything the
# detector returns becomes a person on the SITREP roster, so a panel of
# patterned cloth entering the report costs more than an occluded face leaving
# it.
SCORE_THRESHOLD = 0.6

# Boxes overlapping more than this are treated as the same face.
NMS_THRESHOLD = 0.4

# Detector normalisation, as the model was trained.
_MEAN = 127.5
_SCALE = 1.0 / 128.0


class Face:
    """One detected face, in the coordinates of the frame it was found in."""

    __slots__ = ("bbox", "score", "keypoints")

    def __init__(self, bbox: np.ndarray, score: float, keypoints: np.ndarray):
        self.bbox = bbox            # (4,) x1, y1, x2, y2
        self.score = score
        self.keypoints = keypoints  # (5, 2)

    @property
    def size(self) -> float:
        """Length of the longer box side, in pixels of the source frame."""
        x1, y1, x2, y2 = self.bbox
        return float(max(x2 - x1, y2 - y1))

    def __repr__(self) -> str:
        x1, y1, x2, y2 = (round(float(v)) for v in self.bbox)
        return f"Face({x1},{y1},{x2},{y2} {self.size:.0f}px score={self.score:.2f})"


def _anchor_centres(height: int, width: int, stride: int) -> np.ndarray:
    """Centres of every anchor on one feature map, in input-image pixels."""
    y, x = np.mgrid[:height, :width]
    centres = np.stack([x, y], axis=-1).astype(np.float32) * stride
    return np.repeat(centres.reshape(-1, 2), ANCHORS, axis=0)


def _distance_to_box(centres: np.ndarray, distances: np.ndarray) -> np.ndarray:
    """Convert left/top/right/bottom distances into corner coordinates."""
    return np.stack([
        centres[:, 0] - distances[:, 0],
        centres[:, 1] - distances[:, 1],
        centres[:, 0] + distances[:, 2],
        centres[:, 1] + distances[:, 3],
    ], axis=-1)


def _distance_to_points(centres: np.ndarray, distances: np.ndarray) -> np.ndarray:
    """Convert per-landmark offsets into coordinates."""
    points = distances.reshape(len(centres), -1, 2) + centres[:, None, :]
    return points


def _nms(boxes: np.ndarray, scores: np.ndarray) -> list[int]:
    """Greedy non-maximum suppression, highest score first."""
    x1, y1, x2, y2 = boxes.T
    areas = (x2 - x1 + 1) * (y2 - y1 + 1)
    order = scores.argsort()[::-1]

    keep = []
    while order.size:
        best = order[0]
        keep.append(int(best))
        overlap_x1 = np.maximum(x1[best], x1[order[1:]])
        overlap_y1 = np.maximum(y1[best], y1[order[1:]])
        overlap_x2 = np.minimum(x2[best], x2[order[1:]])
        overlap_y2 = np.minimum(y2[best], y2[order[1:]])
        width = np.maximum(0.0, overlap_x2 - overlap_x1 + 1)
        height = np.maximum(0.0, overlap_y2 - overlap_y1 + 1)
        intersection = width * height
        iou = intersection / (areas[best] + areas[order[1:]] - intersection)
        order = order[1:][iou <= NMS_THRESHOLD]
    return keep


def _letterbox(frame: np.ndarray, size: int) -> tuple[np.ndarray, float]:
    """Fit a frame into a square input, preserving aspect ratio.

    The scaled image sits at the top left of the square and the remainder is
    left black, which is how SCRFD expects padding, so a detection maps back to
    the frame by a single scale factor.
    """
    height, width = frame.shape[:2]
    scale = min(size / width, size / height)
    resized = cv2.resize(frame, (int(round(width * scale)), int(round(height * scale))))
    canvas = np.zeros((size, size, 3), dtype=np.uint8)
    canvas[:resized.shape[0], :resized.shape[1]] = resized
    return canvas, scale


def detect(frame: np.ndarray, size: int = INPUT_SIZE,
           threshold: float = SCORE_THRESHOLD) -> list[Face]:
    """Detect every face in one BGR frame, largest first.

    `size` is the square the frame is fitted into before inference. Raising it
    keeps distant faces above the detector's minimum pixel size at the cost of
    quadratic run time.
    """
    canvas, scale = _letterbox(frame, size)
    blob = cv2.dnn.blobFromImage(canvas, _SCALE, (size, size),
                                 (_MEAN, _MEAN, _MEAN), swapRB=True)

    detector = model.session(model.DETECTOR)
    outputs = detector.run(None, {detector.get_inputs()[0].name: blob})

    boxes, scores, landmarks = [], [], []
    for index, stride in enumerate(STRIDES):
        confidence = outputs[index].ravel()
        chosen = np.flatnonzero(confidence >= threshold)
        if not chosen.size:
            continue

        side = size // stride
        centres = _anchor_centres(side, side, stride)[chosen]
        boxes.append(_distance_to_box(centres, outputs[index + 3][chosen] * stride))
        landmarks.append(_distance_to_points(centres, outputs[index + 6][chosen] * stride))
        scores.append(confidence[chosen])

    if not boxes:
        return []

    boxes = np.concatenate(boxes) / scale
    landmarks = np.concatenate(landmarks) / scale
    scores = np.concatenate(scores)

    keep = _nms(boxes, scores)
    faces = [Face(boxes[i], float(scores[i]), landmarks[i]) for i in keep]
    return sorted(faces, key=lambda face: face.size, reverse=True)
