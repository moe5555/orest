"""RTMO pose detection, loaded once and shared.

RTMO is one-stage: a frame goes in and every body's keypoints come out, with no
separate person detector to run first. That keeps the pipeline to a single ONNX
model, which matters because the same model has to run inside WISE's conda
environment and inside Orest's, and the two hold incompatible numpy versions.
An ONNX model is the only form that installs cleanly into both without dragging
a second torch stack behind it.

Verified on the test corpus: 43 ms per frame on CPU, two bodies resolved on a
wide outdoor stage shot, and a floor posture tracked correctly under a single
spotlight.
"""

import logging
import os
import threading

logger = logging.getLogger(__name__)

# RTMO-s, trained on body7, 640x640 input. The small build is chosen because
# pose runs on CPU here: ONNX Runtime resolves no CUDA provider in either
# environment (see hardware_issues.md). It is 35 MB and downloads on first use.
MODEL_URL = (
    "https://download.openmmlab.com/mmpose/v1/projects/rtmo/onnx_sdk/"
    "rtmo-s_8xb32-600e_body7-640x640-dac2bf74_20231211.zip"
)

# Detections below this are discarded by RTMO before keypoints are returned.
# Lower than the library default, which drops bodies that are small in frame —
# on a wide rehearsal stage most of them are.
SCORE_THRESHOLD = 0.3

_lock = threading.Lock()
_model = None


def device() -> str:
    """Execution provider to run pose detection on.

    Falls back to CPU, which is the live situation in both environments, but
    reads the provider list rather than assuming it.
    """
    override = os.environ.get("OREST_POSE_DEVICE")
    if override:
        return override
    try:
        import onnxruntime

        if "CUDAExecutionProvider" in onnxruntime.get_available_providers():
            return "cuda"
    except ImportError:
        pass
    return "cpu"


def load():
    """Return the shared RTMO instance, constructing it on first use.

    Loading is deferred because WISE constructs every feature extractor a
    project contains when the server starts, whether or not a search will use
    it. Deferring keeps a pose index from costing model load time on every
    `wise serve`.
    """
    global _model
    with _lock:
        if _model is None:
            from rtmlib import RTMO

            target = device()
            logger.info("Loading RTMO pose model on %s", target)
            _model = RTMO(MODEL_URL, backend="onnxruntime", device=target,
                          score_thr=SCORE_THRESHOLD)
        return _model


def detect(frame):
    """Detect every body in one BGR frame.

    Returns (keypoints, scores) shaped (people, 17, 2) and (people, 17).
    """
    return load()(frame)


def detect_segment(frames):
    """Detect bodies across a sequence of frames, in order."""
    model = load()
    return [model(frame) for frame in frames]
