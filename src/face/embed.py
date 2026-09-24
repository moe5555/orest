"""ArcFace embedding: a detected face becomes a 512-dimension vector.

Two faces are compared by the cosine similarity of their vectors. Vectors are
returned L2-normalised, so the comparison is a dot product and similarities are
directly comparable across faces of different sizes and lighting.

Alignment is what makes the comparison meaningful. ArcFace was trained on faces
warped so that the eyes, nose and mouth corners sit at fixed positions, and an
unaligned crop embeds as a different person. The warp is a similarity transform
(rotation, uniform scale, translation) fitted to the detector's five landmarks
by the Umeyama least-squares solution.
"""

import cv2
import numpy as np

from . import detect, model

# Side of the square ArcFace consumes.
CROP_SIZE = 112

# Canonical landmark positions for a 112x112 crop: left eye, right eye, nose,
# left mouth corner, right mouth corner. These are the positions ArcFace was
# trained against and are not a free parameter.
REFERENCE = np.array([
    [38.2946, 51.6963],
    [73.5318, 51.5014],
    [56.0252, 71.7366],
    [41.5493, 92.3655],
    [70.7299, 92.2041],
], dtype=np.float32)

# Recogniser normalisation, as the model was trained.
_MEAN = 127.5
_SCALE = 1.0 / 127.5


def _similarity_transform(source: np.ndarray, target: np.ndarray) -> np.ndarray:
    """Least-squares similarity transform mapping source points onto target.

    The Umeyama solution: the rotation comes from the SVD of the cross-
    covariance, and the scale from the ratio of variances. Returns the 2x3
    matrix cv2.warpAffine takes.
    """
    source_mean, target_mean = source.mean(axis=0), target.mean(axis=0)
    source_centred, target_centred = source - source_mean, target - target_mean

    covariance = target_centred.T @ source_centred / len(source)
    unitary, singular, transposed = np.linalg.svd(covariance)

    # Reflections are not similarity transforms; flipping the sign of the
    # smallest singular direction keeps the result a rotation.
    signs = np.ones(2)
    if np.linalg.det(covariance) < 0:
        signs[1] = -1

    rotation = unitary @ np.diag(signs) @ transposed
    scale = (singular @ signs) / source_centred.var(axis=0).sum()

    matrix = np.empty((2, 3), dtype=np.float32)
    matrix[:, :2] = rotation * scale
    matrix[:, 2] = target_mean - scale * (rotation @ source_mean)
    return matrix


def align(frame: np.ndarray, face: detect.Face) -> np.ndarray:
    """Warp a detected face to the canonical 112x112 crop."""
    matrix = _similarity_transform(face.keypoints.astype(np.float32), REFERENCE)
    return cv2.warpAffine(frame, matrix, (CROP_SIZE, CROP_SIZE))


def embed_crops(crops: list[np.ndarray]) -> np.ndarray:
    """Embed aligned crops as L2-normalised vectors, shaped (n, 512)."""
    blob = cv2.dnn.blobFromImages(crops, _SCALE, (CROP_SIZE, CROP_SIZE),
                                  (_MEAN, _MEAN, _MEAN), swapRB=True)
    recogniser = model.session(model.RECOGNISER)
    vectors = recogniser.run(None, {recogniser.get_inputs()[0].name: blob})[0]
    return vectors / np.linalg.norm(vectors, axis=1, keepdims=True)


def embed(frame: np.ndarray, faces: list[detect.Face]) -> np.ndarray:
    """Embed every given face of one frame."""
    if not faces:
        return np.zeros((0, 512), dtype=np.float32)
    return embed_crops([align(frame, face) for face in faces])


def similarity(left: np.ndarray, right: np.ndarray) -> np.ndarray:
    """Cosine similarity between normalised embeddings, as a matrix."""
    return np.atleast_2d(left) @ np.atleast_2d(right).T
