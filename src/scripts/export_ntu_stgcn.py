"""Export the NTU120 ST-GCN action recogniser to ONNX, once, outside Orest.

MMAction2 needs a PyTorch stack that cannot live in Orest's Python 3.14
environment, so the model is converted here and Orest runs the resulting
.onnx file with onnxruntime, as it runs RTMO (changelog.md, 2026-09-28).

Runs in a conda environment of its own, `mmaction`:

    conda create -n mmaction -c conda-forge --override-channels python=3.10
    pip install torch==2.3.1 torchvision==0.18.1 --index-url https://download.pytorch.org/whl/cpu
    pip install "numpy<2" mmengine==0.10.7 mmcv-lite==2.1.0 onnx==1.16.2 onnxruntime==1.19.2 \
                importlib_metadata einops scipy "opencv-python-headless<4.11"
    git clone --depth 1 --branch v1.2.0 https://github.com/open-mmlab/mmaction2.git external/mmaction2
    pip install --no-deps -e external/mmaction2

MMAction2 is installed editable from the tagged source because its 1.2.0
package omits `mmaction/models/localizers/drn`, which has no __init__.py and
is skipped by the package build, and `import mmaction.models` fails without it.
torch stays at 2.3: from 2.6, torch.load defaults to weights_only, which the
checkpoints of this generation do not load under.

    python src/scripts/export_ntu_stgcn.py

Writes, next to the checkpoint:

    stgcn_ntu120_2d.onnx   the network: (batch, 2 people, 100 frames, 17 joints,
                           x y score) in, 120 logits out
    reference.npz          a synthetic two-person sequence, MMAction2's own
                           preprocessing of it and its prediction, and the
                           frames MMAction2 samples from longer sequences,
                           against which Orest's preprocessing is tested
                           (copied to tests/fixtures/ntu120_reference.npz)

The export covers the network only. MMAction2 applies softmax to each of its
10 test clips and averages them ('average_clips': 'prob'); that, and the
preprocessing, are Orest's to reproduce.
"""

import argparse
import sys
from pathlib import Path

import numpy as np
import onnx
import onnxruntime
import torch
from mmaction.apis import inference_skeleton, init_recognizer
from mmengine.dataset import Compose

REPO = Path(__file__).resolve().parents[2]
MODEL_DIR = REPO / "data" / "models" / "ntu120_stgcn"
NAME = "stgcn_8xb16-joint-u100-80e_ntu120-xsub-keypoint-2d"
CONFIG = REPO / "external" / "mmaction2" / "configs" / "skeleton" / "stgcn" / f"{NAME}.py"
CHECKPOINT = MODEL_DIR / f"{NAME}_20221129-612416c6.pth"

PEOPLE, FRAMES, JOINTS, CHANNELS = 2, 100, 17, 3
OPSET = 17

# Frame size and length of the synthetic reference sequence: 1080p at the
# 30 fps NTU was recorded at, 2.5 s long.
REFERENCE_SHAPE = (1080, 1920)
REFERENCE_FRAMES = 75

# Sequence lengths whose frame sampling is recorded as well: exactly one clip,
# between one and two clips, and more than two.
SAMPLED_LENGTHS = (100, 150, 250)

# A standing figure in COCO-17 order, in units of body height, feet at y = 0.
# nose, eyes, ears, shoulders, elbows, wrists, hips, knees, ankles.
STANDING = np.array([
    [0.00, -0.93], [-0.03, -0.95], [0.03, -0.95], [-0.06, -0.94], [0.06, -0.94],
    [-0.12, -0.80], [0.12, -0.80], [-0.15, -0.63], [0.15, -0.63],
    [-0.16, -0.47], [0.16, -0.47], [-0.09, -0.50], [0.09, -0.50],
    [-0.09, -0.27], [0.09, -0.27], [-0.09, -0.02], [0.09, -0.02],
], dtype=np.float32)


class Network(torch.nn.Module):
    """Backbone and classification head, without MMAction2's data handling."""

    def __init__(self, recognizer):
        super().__init__()
        self.backbone = recognizer.backbone
        self.head = recognizer.cls_head

    def forward(self, keypoints):
        return self.head(self.backbone(keypoints))


def reference_sequence():
    """Two people facing each other; the left one swings an arm at the right.

    Synthetic, so the fixture holds no footage of anyone. Its purpose is to
    pin preprocessing and numerics, not to be recognised correctly.
    """
    height, width = REFERENCE_SHAPE
    size = 520.0
    feet = height * 0.85
    left, right = STANDING * size, STANDING * size
    left = left + [width * 0.40, feet]
    right = right + [width * 0.58, feet]

    frames = []
    for index in range(REFERENCE_FRAMES):
        phase = np.sin(np.pi * index / (REFERENCE_FRAMES - 1))
        swinger = left.copy()
        # Right arm (elbow 8, wrist 10) sweeps up and across towards the other head.
        swinger[8] += phase * np.array([70.0, -60.0])
        swinger[10] += phase * np.array([190.0, -230.0])
        struck = right.copy()
        struck[:5] += phase * np.array([25.0, 8.0])
        keypoints = np.stack([swinger, struck])
        scores = np.full((PEOPLE, JOINTS), 0.9, dtype=np.float32)
        frames.append(dict(keypoints=keypoints.astype(np.float32), keypoint_scores=scores))
    return frames


def pipeline_inputs(model, frames):
    """The tensor MMAction2's test pipeline builds from a pose sequence."""
    height, width = REFERENCE_SHAPE
    keypoint = np.stack([frame["keypoints"] for frame in frames]).astype(np.float16)
    score = np.stack([frame["keypoint_scores"] for frame in frames]).astype(np.float16)
    sample = dict(frame_dict="", label=-1, img_shape=(height, width),
                  origin_shape=(height, width), start_index=0, modality="Pose",
                  total_frames=len(frames),
                  keypoint=keypoint.transpose((1, 0, 2, 3)),
                  keypoint_score=score.transpose((1, 0, 2)))
    packed = Compose(model.cfg.test_pipeline)(sample)
    return packed["inputs"].numpy()


def sampled_frames(model, num_frames):
    """Frame indices UniformSampleFrames draws for a sequence of this length.

    Covers the sampling branches the reference sequence does not reach: it is
    shorter than a clip, while live windows are one clip long or more.
    """
    sampler = next(step for step in Compose(model.cfg.test_pipeline).transforms
                   if type(step).__name__ == "UniformSampleFrames")
    keypoint = np.ones((1, num_frames, 17, 3), dtype=np.float16)
    return sampler.transform(dict(total_frames=num_frames, keypoint=keypoint))["frame_inds"]


def softmax(logits):
    shifted = np.exp(logits - logits.max(axis=-1, keepdims=True))
    return shifted / shifted.sum(axis=-1, keepdims=True)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=MODEL_DIR / "stgcn_ntu120_2d.onnx")
    parser.add_argument("--reference", type=Path, default=MODEL_DIR / "reference.npz")
    args = parser.parse_args(argv)

    recognizer = init_recognizer(str(CONFIG), str(CHECKPOINT), device="cpu")
    network = Network(recognizer).eval()

    example = torch.zeros(1, PEOPLE, FRAMES, JOINTS, CHANNELS)
    torch.onnx.export(network, example, str(args.out), opset_version=OPSET,
                      input_names=["keypoints"], output_names=["logits"],
                      dynamic_axes={"keypoints": {0: "batch"}, "logits": {0: "batch"}})
    onnx.checker.check_model(onnx.load(str(args.out)))
    session = onnxruntime.InferenceSession(str(args.out), providers=["CPUExecutionProvider"])

    # The network: PyTorch and ONNX Runtime on the same random input.
    generator = torch.Generator().manual_seed(0)
    random = torch.randn(4, PEOPLE, FRAMES, JOINTS, CHANNELS, generator=generator)
    with torch.no_grad():
        expected = network(random).numpy()
    actual = session.run(None, {"keypoints": random.numpy()})[0]
    network_error = float(np.abs(expected - actual).max())

    # The whole recogniser: MMAction2's inference against the ONNX network fed
    # MMAction2's own preprocessing, with softmax averaged over the clips.
    frames = reference_sequence()
    inputs = pipeline_inputs(recognizer, frames)
    predicted = inference_skeleton(recognizer, frames, REFERENCE_SHAPE).pred_score.numpy()
    reproduced = softmax(session.run(None, {"keypoints": inputs.astype(np.float32)})[0]).mean(axis=0)
    pipeline_error = float(np.abs(predicted - reproduced).max())

    np.savez_compressed(
        args.reference,
        keypoints=np.stack([frame["keypoints"] for frame in frames]),
        keypoint_scores=np.stack([frame["keypoint_scores"] for frame in frames]),
        img_shape=np.array(REFERENCE_SHAPE),
        inputs=inputs,
        pred_score=predicted,
        **{f"frame_inds_{length}": sampled_frames(recognizer, length)
           for length in SAMPLED_LENGTHS},
    )

    labels = (MODEL_DIR / "label_map_ntu120.txt").read_text(encoding="utf-8").splitlines()
    print(f"wrote {args.out} ({args.out.stat().st_size / 1e6:.1f} MB, opset {OPSET})")
    print(f"wrote {args.reference}")
    print(f"network, max |torch - onnx| over logits:          {network_error:.2e}")
    print(f"recogniser, max |mmaction2 - onnx| over the 120 probabilities: {pipeline_error:.2e}")
    print(f"pipeline input {inputs.shape}; top classes of the reference sequence:")
    for index in np.argsort(predicted)[::-1][:5]:
        print(f"  {predicted[index]:.3f}  A{index + 1} {labels[index]}")

    tolerance = 1e-4
    if network_error > tolerance or pipeline_error > tolerance:
        print(f"parity check failed (tolerance {tolerance:g})", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
