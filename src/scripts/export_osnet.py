"""Export the OSNet-AIN person re-identification network to ONNX, once, outside Apollon.

The appearance cue of the live SITREP (src/sitrep/appearance.py) runs OSNet-AIN
x1.0 trained on all of MSMT17, the Torchreid model zoo's cross-domain model:
trained on one dataset and evaluated on others, as a stage is to it. Torchreid
needs PyTorch, which Apollon's Python 3.14 environment does not carry, so the
network is converted here and Apollon runs the .onnx file with onnxruntime, as
it runs RTMO and the action model.

Runs in a throwaway environment that uv builds for the one call:

    uv run --no-project --python 3.12 --with torch==2.5.1 --with onnx==1.17.0 \\
        --with onnxruntime==1.20.1 --with gdown==5.2.0 --with opencv-python-headless \\
        --with pillow --with "numpy<2.2" python src/scripts/export_osnet.py

Only the network's definition is taken from Torchreid, from a pinned commit;
the package itself, which builds a Cython extension for evaluation, is not
installed.

Writes to data/models/osnet/:

    osnet_ain_x1_0_msmt17.pth    the checkpoint, as downloaded
    osnet_ain_x1_0_msmt17.onnx   the network: (batch, 3, 256, 128) RGB, ImageNet-
                                 normalised, in; (batch, 512) features out
    reference.npz                a synthetic crop, its preprocessing and the
                                 network's features for it, against which
                                 Apollon's preprocessing and the ONNX file are
                                 tested (copied to tests/fixtures/osnet_reference.npz)
"""

import argparse
import hashlib
import importlib.util
import sys
import urllib.request
from pathlib import Path

import cv2
import gdown
import numpy as np
import onnxruntime
import torch
from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[2]
OUT = REPO_ROOT / "data" / "models" / "osnet"

COMMIT = "f8cd150fdf77e8d9e1ed143b7f308c2c609ded50"
DEFINITION = (f"https://raw.githubusercontent.com/KaiyangZhou/deep-person-reid/{COMMIT}"
              "/torchreid/models/osnet_ain.py")

# Model zoo, "MSMT17 (combineall=True) -> Market1501 & DukeMTMC-reID", osnet_ain_x1_0.
CHECKPOINT_ID = "1SigwBE6mPdqiJMqhuIY4aqC7--5CsMal"
CHECKPOINT = "osnet_ain_x1_0_msmt17.pth"
ONNX_FILE = "osnet_ain_x1_0_msmt17.onnx"

HEIGHT, WIDTH = 256, 128
MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)


def preprocess(crop_bgr: np.ndarray) -> np.ndarray:
    """A BGR crop as the network takes it, (3, 256, 128).

    The same steps as Apollon's (appearance.preprocess): bilinear resize with
    OpenCV, RGB, scaled to 0-1, ImageNet mean and deviation.
    """
    resized = cv2.resize(crop_bgr, (WIDTH, HEIGHT), interpolation=cv2.INTER_LINEAR)
    rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
    return ((rgb - MEAN) / STD).transpose(2, 0, 1)


def preprocess_torchreid(crop_bgr: np.ndarray) -> np.ndarray:
    """The crop as Torchreid's test transform prepares it: PIL bilinear resize."""
    image = Image.fromarray(cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2RGB)).resize(
        (WIDTH, HEIGHT), Image.BILINEAR)
    rgb = np.asarray(image, dtype=np.float32) / 255.0
    return ((rgb - MEAN) / STD).transpose(2, 0, 1)


def reference_crop() -> np.ndarray:
    """A deterministic person-sized BGR crop with structure in every channel."""
    rows, cols = np.mgrid[0:300, 0:140]
    crop = np.stack([(rows * 0.8) % 256, (cols * 1.7) % 256,
                     ((rows + cols) * 0.6) % 256], axis=2)
    return crop.astype(np.uint8)


def load_definition():
    path = OUT / "osnet_ain.py"
    if not path.exists():
        urllib.request.urlretrieve(DEFINITION, path)
    spec = importlib.util.spec_from_file_location("osnet_ain", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def build(definition) -> torch.nn.Module:
    model = definition.osnet_ain_x1_0(num_classes=1, pretrained=False, loss="softmax")
    checkpoint = torch.load(OUT / CHECKPOINT, map_location="cpu", weights_only=False)
    state = checkpoint.get("state_dict", checkpoint)
    state = {key.removeprefix("module."): value for key, value in state.items()}
    own = model.state_dict()
    # The classifier is sized for MSMT17's identities and is not used: in
    # evaluation the network returns the 512-d feature before it.
    usable = {key: value for key, value in state.items()
              if key in own and own[key].shape == value.shape}
    skipped = sorted(set(state) - set(usable))
    if any(not key.startswith("classifier") for key in skipped):
        raise RuntimeError(f"Checkpoint keys not loaded: {skipped}")
    model.load_state_dict(usable, strict=False)
    return model.eval()


def main(argv=None) -> int:
    argparse.ArgumentParser(description=__doc__.splitlines()[0]).parse_args(argv)
    OUT.mkdir(parents=True, exist_ok=True)

    if not (OUT / CHECKPOINT).exists():
        gdown.download(id=CHECKPOINT_ID, output=str(OUT / CHECKPOINT), quiet=False)
    digest = hashlib.sha256((OUT / CHECKPOINT).read_bytes()).hexdigest()
    print(f"checkpoint sha256 {digest}")

    model = build(load_definition())
    dummy = torch.zeros(1, 3, HEIGHT, WIDTH)
    torch.onnx.export(model, dummy, OUT / ONNX_FILE, input_names=["images"],
                      output_names=["features"], opset_version=17,
                      dynamic_axes={"images": {0: "batch"}, "features": {0: "batch"}})

    crop = reference_crop()
    tensor = preprocess(crop)
    with torch.no_grad():
        expected = model(torch.from_numpy(tensor[None])).numpy()[0]
        torchreid_way = model(torch.from_numpy(preprocess_torchreid(crop)[None])).numpy()[0]
    session = onnxruntime.InferenceSession(str(OUT / ONNX_FILE), providers=["CPUExecutionProvider"])
    exported = session.run(None, {"images": tensor[None]})[0][0]

    def cosine(a, b):
        return float(a @ b / (np.linalg.norm(a) * np.linalg.norm(b)))

    deviation = float(np.abs(exported - expected).max())
    print(f"onnx vs torch: max abs deviation {deviation:.2e}, cosine {cosine(exported, expected):.6f}")
    print(f"opencv vs pil resize: cosine {cosine(expected, torchreid_way):.4f}")
    if deviation > 1e-3:
        print("ONNX output deviates from torch", file=sys.stderr)
        return 1

    np.savez_compressed(OUT / "reference.npz", crop=crop, tensor=tensor, features=expected)
    print(f"wrote {OUT / ONNX_FILE} and {OUT / 'reference.npz'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
