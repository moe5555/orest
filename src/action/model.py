"""The NTU120 ST-GCN network, run with ONNX Runtime.

The weights are not in the repository: data/models/ntu120_stgcn/ holds the
exported network and the class list, with their provenance in SOURCE.md
there. The model is research-licensed (NTU RGB+D terms), which Orest's
research context covers (changelog.md, 2026-09-28).

Runs on the GPU where ONNX Runtime's CUDA provider works, found the same way
as for pose detection, whose model it is fed from. TF32 is switched off: at
under 4 ms for a whole window the precision costs nothing, and it keeps the
output identical to MMAction2's rather than within 10^-3 of it.
"""

import os
import threading
from functools import cache
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]

MODEL_DIR = Path(os.environ.get("OREST_ACTION_MODEL_DIR",
                                REPO_ROOT / "data" / "models" / "ntu120_stgcn"))
MODEL_FILE = "stgcn_ntu120_2d.onnx"
LABELS_FILE = "label_map_ntu120.txt"

# Sequences sent to the network per run. GPU memory grows with the batch, by
# roughly 250 MB per sequence of 10 clips, and ONNX Runtime keeps what it has
# once taken. A fixed chunk bounds that at about 1 GB however many people are
# in frame, leaving the GPU to the SITREP's language model.
CHUNK = 4

_lock = threading.Lock()
_session = None


@cache
def labels() -> tuple[str, ...]:
    """The 120 NTU class names, in the order the network scores them."""
    return tuple((MODEL_DIR / LABELS_FILE).read_text(encoding="utf-8").splitlines())


def _providers() -> list:
    # Imported here: orest_pose's device() also puts the CUDA libraries on
    # PATH, which has to happen before the session is created.
    from orest_pose import model as pose_model

    if pose_model.device() == "cuda":
        # kSameAsRequested grows the memory arena by what a run needs rather
        # than doubling it.
        return [("CUDAExecutionProvider", {"use_tf32": 0,
                                           "arena_extend_strategy": "kSameAsRequested"}),
                "CPUExecutionProvider"]
    return ["CPUExecutionProvider"]


def session():
    """The shared inference session, created on first use."""
    global _session
    with _lock:
        if _session is None:
            import onnxruntime

            path = MODEL_DIR / MODEL_FILE
            if not path.exists():
                raise RuntimeError(
                    f"No action model at {path}. Export it with "
                    f"src/scripts/export_ntu_stgcn.py, or set OREST_ACTION_MODEL_DIR.")
            _session = onnxruntime.InferenceSession(str(path), providers=_providers())
        return _session


def active_provider() -> str | None:
    """Execution provider the loaded session is really running on."""
    return _session.get_providers()[0] if _session else None


def classify(batch: np.ndarray) -> np.ndarray:
    """Class probabilities for each pose sequence in a batch.

    batch: (sequences, NUM_CLIPS, 2, 100, 17, 3), as preprocess.clips()
    returns one sequence. Each clip is scored separately and the softmax
    probabilities averaged over a sequence's clips, as MMAction2 does
    ('average_clips': 'prob'). Returns (sequences, 120).
    """
    sequences, clips = batch.shape[:2]
    flat = batch.reshape((sequences * clips,) + batch.shape[2:]).astype(np.float32)
    step = CHUNK * clips
    logits = np.concatenate([session().run(None, {"keypoints": flat[start:start + step]})[0]
                             for start in range(0, len(flat), step)])
    shifted = np.exp(logits - logits.max(axis=-1, keepdims=True))
    probabilities = shifted / shifted.sum(axis=-1, keepdims=True)
    return probabilities.reshape(sequences, clips, -1).mean(axis=1)
