"""WISE feature extractor that indexes the corpus by body movement.

Registered with WISE through its feature extractor factory, which is a prefix
chain that the upstream documentation names as the extension point
(external/wise/docs/FeatureExtractor.md). WISE then handles decoding, segment
windowing, vector storage and index building; this class only turns frames into
a vector.

Imported only inside WISE's environment. The embedding itself lives in
`keypoints`, which Apollon imports separately to encode a live query into the
same space.

Segment-level rather than frame-level, so WISE hands over a whole window of
frames at once and stores one vector per window. Frame-level and segment-level
extractors cannot be combined in one extraction run, so this is added to an
existing project on its own:

    apollon-search add-extractor --video-id apollon/pose/rtmo-s/body7
"""

import logging

import numpy as np
import torch

from wise.feature.feature_extractor import FeatureExtractor, Features

from . import keypoints, model

logger = logging.getLogger(__name__)


class PoseSegmentFeatureExtractor(FeatureExtractor):
    """Encodes a video segment as the movement of the body it contains.

    See apollon_pose.keypoints for what the vector represents.
    """

    ID_PREFIX = "apollon/pose/"
    DESCRIPTION = "RTMO body keypoints, normalised and concatenated over a segment"

    # Only whole segments are meaningful here. A still frame carries a posture
    # but not a movement, and text has no path into keypoint space at all, so
    # both are declared unsupported rather than answered badly.
    preprocess_image = None
    extract_image_features = None
    extract_image_region_features = None
    preprocess_audio = None
    extract_audio_features = None
    preprocess_text = None
    extract_text_features = None

    def __init__(self, model_id: str, *, device=None, warmup: bool = False,
                 config=None, **kwargs):
        super().__init__(model_id, device=device)
        if warmup:
            self.warmup()

    def warmup(self):
        model.load()

    def get_output_dim(self) -> int:
        return keypoints.EMBEDDING_DIMS

    def preprocess_video_segment(self, frames: torch.Tensor) -> torch.Tensor:
        """No preprocessing: RTMO takes full-resolution frames and letterboxes.

        Resizing here would discard detail the detector uses to resolve bodies
        that are small in frame, which on a wide stage shot is most of them.
        """
        return frames

    @torch.inference_mode()
    def extract_video_segment_features(self, frames: torch.Tensor) -> Features:
        """Encode one segment as a single unit-length vector."""
        detections = model.detect_segment(_as_bgr_frames(frames))
        vector = keypoints.segment_embedding(detections)
        return Features(metadata=None, vectors=vector.reshape(1, -1))


def _as_bgr_frames(frames: torch.Tensor) -> list[np.ndarray]:
    """Convert a (N, C, H, W) RGB tensor to the BGR images RTMO expects."""
    array = frames.detach().cpu().numpy()
    if array.ndim != 4:
        raise ValueError(f"Expected a (N, C, H, W) segment, got shape {array.shape}")
    array = np.ascontiguousarray(array.transpose(0, 2, 3, 1))
    if array.dtype != np.uint8:
        array = np.clip(array, 0, 255).astype(np.uint8)
    return [frame[:, :, ::-1] for frame in array]
