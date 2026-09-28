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

import glob
import logging
import os
import sysconfig
import threading

logger = logging.getLogger(__name__)

# RTMO-s, trained on body7, 640x640 input. The small build was chosen while
# pose ran on the CPU (hardware_issues.md H-10); it is 35 MB and downloads on
# first use.
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


def _add_cuda_libraries_to_path():
    """Make the CUDA runtime visible to ONNX Runtime's provider library.

    ONNX Runtime loads its CUDA provider as a separate DLL, whose own
    dependencies are resolved by the Windows loader against PATH.
    os.add_dll_directory() does not cover that second hop and the load still
    fails with cublasLt64_12.dll missing — the same behaviour CTranslate2 shows
    in sitrep/transcribe.py.

    Where torch is installed, as in WISE's environment, its complete CUDA 12
    runtime is used, avoiding a second multi-gigabyte copy. Elsewhere the
    runtime comes from NVIDIA's pip packages (nvidia-*-cu12), which Orest's
    environment installs with onnxruntime-gpu. Their folders go on PATH rather
    than being preloaded, because cuDNN loads its sub-libraries by name on
    first use, which only a search path satisfies.
    """
    try:
        import torch
        folders = [os.path.join(os.path.dirname(torch.__file__), "lib")]
    except ImportError:
        nvidia = os.path.join(sysconfig.get_paths()["purelib"], "nvidia")
        folders = sorted(glob.glob(os.path.join(nvidia, "*", "bin")))

    path = os.environ.get("PATH", "")
    missing = [folder for folder in folders if os.path.isdir(folder) and folder not in path]
    if missing:
        os.environ["PATH"] = os.pathsep.join(missing) + os.pathsep + path


def device() -> str:
    """Execution provider to request for pose detection.

    A listed CUDA provider is not necessarily a working one — ONNX Runtime
    advertises it from the package it was built as, then falls back to CPU at
    session creation if the matching CUDA runtime is missing. What was actually
    used is reported by `active_provider()` after loading.
    """
    override = os.environ.get("OREST_POSE_DEVICE")
    if override:
        return override

    _add_cuda_libraries_to_path()
    try:
        import onnxruntime

        if "CUDAExecutionProvider" in onnxruntime.get_available_providers():
            return "cuda"
    except ImportError:
        pass
    return "cpu"


def active_provider() -> str | None:
    """Execution provider the loaded session is really running on."""
    if _model is None:
        return None
    return _model.session.get_providers()[0]


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
            _model = RTMO(MODEL_URL, backend="onnxruntime", device=target,
                          score_thr=SCORE_THRESHOLD)
            running = _model.session.get_providers()[0]
            logger.info("RTMO pose model loaded on %s", running)
            if target == "cuda" and running != "CUDAExecutionProvider":
                logger.warning(
                    "CUDA was requested but the session runs on %s. Pose "
                    "detection is roughly four times slower; see "
                    "hardware_issues.md H-10.", running,
                )
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
