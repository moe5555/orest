"""InsightFace ONNX models, downloaded once and shared.

Two models from the `buffalo_l` bundle: SCRFD-10GF for detection, which returns
a box and five landmarks per face, and ArcFace R50 for the 512-dimension
embedding that identity is measured in.

`buffalo_l` is chosen over the smaller bundles because it is also what WISE's
own face feature extractor uses (knowledge/background/wise_clip_as_query.md).
Nothing here depends on WISE, but should the Hindsight-SITREP ever index the
corpus by face, the same model means a vector measured live and a vector in
that index occupy one space rather than two.

The models are loaded from the ONNX files directly rather than through the
`insightface` package, which builds from source on Python 3.14 and pulls a
second numpy stack behind it. Only onnxruntime, numpy and cv2 are needed, all
three of which Orest already has.
"""

import logging
import os
import threading
import urllib.request
import zipfile
from pathlib import Path

import onnxruntime as ort

logger = logging.getLogger(__name__)

# The InsightFace model zoo bundle. 288 MB, of which the two models used here
# are 191 MB; the archive is kept so a re-extraction needs no second download.
BUNDLE_URL = (
    "https://github.com/deepinsight/insightface/releases/download/v0.7/buffalo_l.zip"
)

DETECTOR = "det_10g.onnx"
RECOGNISER = "w600k_r50.onnx"

# Threads per inference session on CPU. ONNX Runtime defaults to one thread per
# core, which for models this small costs more in synchronisation than it wins
# in parallelism, and costs more again when the detector and the recogniser are
# called alternately and contend for the machine. Measured on 32 cores: a
# detect-and-embed pass takes 802 ms at the default and 222 ms at four threads.
# Four also leaves the machine to Whisper and Ollama, which run in the same
# window.
THREADS = int(os.environ.get("OREST_FACE_THREADS", "4"))

_lock = threading.Lock()
_sessions = {}


def cache_dir() -> Path:
    """Directory holding the downloaded bundle and the extracted models.

    Outside the repository, so re-cloning or rebuilding the environment does
    not cost a 288 MB download.
    """
    return Path(os.environ.get("OREST_FACE_CACHE", Path.home() / ".cache" / "orest"))


def _add_cuda_libraries_to_path():
    """Make the CUDA runtime visible to ONNX Runtime's provider library.

    ONNX Runtime loads its CUDA provider as a separate DLL, whose own
    dependencies are resolved by the Windows loader against PATH.
    os.add_dll_directory() does not cover that second hop and the load still
    fails with cublasLt64_12.dll missing (hardware_issues.md H-10).

    The libraries are not installed on their own account: torch ships a
    complete CUDA 12 runtime, and pointing at it avoids a second multi-gigabyte
    copy. Absent in environments without torch, where inference runs on CPU.
    """
    try:
        import torch
    except ImportError:
        return

    libraries = os.path.join(os.path.dirname(torch.__file__), "lib")
    if os.path.isdir(libraries) and libraries not in os.environ.get("PATH", ""):
        os.environ["PATH"] = libraries + os.pathsep + os.environ["PATH"]


def device() -> str:
    """Execution provider to request for face inference.

    A listed CUDA provider is not necessarily a working one: ONNX Runtime
    advertises it from the package it was built as, then falls back to CPU at
    session creation if the matching CUDA runtime is missing. What was actually
    used is reported by `active_provider()` after loading.
    """
    override = os.environ.get("OREST_FACE_DEVICE")
    if override:
        return override

    _add_cuda_libraries_to_path()
    if "CUDAExecutionProvider" in ort.get_available_providers():
        return "cuda"
    return "cpu"


def _providers() -> list[str]:
    if device() == "cuda":
        return ["CUDAExecutionProvider", "CPUExecutionProvider"]
    return ["CPUExecutionProvider"]


def _fetch(name: str) -> Path:
    """Path to one extracted model, downloading the bundle if it is absent."""
    target = cache_dir() / "buffalo_l" / name
    if target.exists():
        return target

    cache_dir().mkdir(parents=True, exist_ok=True)
    archive = cache_dir() / "buffalo_l.zip"
    if not archive.exists():
        logger.info("Downloading %s to %s", BUNDLE_URL, archive)
        urllib.request.urlretrieve(BUNDLE_URL, archive)

    with zipfile.ZipFile(archive) as bundle:
        bundle.extract(name, target.parent)
    return target


def session(name: str) -> ort.InferenceSession:
    """Return a shared InferenceSession for one model, creating it on first use.

    Deferring keeps the 191 MB of models off the start-up path of anything
    that imports this package without recognising a face.
    """
    with _lock:
        if name not in _sessions:
            options = ort.SessionOptions()
            options.intra_op_num_threads = THREADS
            # The recogniser's graph declares a batch size of one for its
            # output while accepting any batch on its input, so every batched
            # call logs a shape mismatch that does not affect the result.
            options.log_severity_level = 3
            loaded = ort.InferenceSession(str(_fetch(name)), options,
                                          providers=_providers())
            running = loaded.get_providers()[0]
            logger.info("%s loaded on %s", name, running)
            _sessions[name] = loaded
        return _sessions[name]


def active_provider(name: str) -> str | None:
    """Execution provider a loaded session is really running on."""
    loaded = _sessions.get(name)
    return loaded.get_providers()[0] if loaded else None
