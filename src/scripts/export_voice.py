"""Fetch the WeSpeaker voice model and write the reference Apollon is tested against, once.

The voice cue of the live SITREP (src/sitrep/voices.py) tells the cast apart by
how they sound: WeSpeaker's ResNet34-LM, trained on VoxCeleb2, turns a stretch
of speech into a 256-value voice vector. WeSpeaker publishes the network as
ONNX, which Apollon runs with onnxruntime as it runs its other models. Its
input, Kaldi filterbanks, is computed by torchaudio in WeSpeaker; Apollon's
Python 3.14 environment carries no torch, so voices.py computes them in numpy,
and this script writes the reference that port is tested against.

Runs in a throwaway environment that uv builds for the one call:

    uv run --no-project --python 3.12 --with torch==2.5.1 --with torchaudio==2.5.1 \\
        --with onnxruntime==1.20.1 --with "numpy<2.2" python src/scripts/export_voice.py

Writes to data/models/voice/:

    voxceleb_resnet34_LM.onnx    the network: (batch, frames, 80) filterbanks in,
                                 (batch, 256) voice vectors out
    config.yaml                  the training configuration, as published
    reference.npz                a synthetic voice, its filterbanks as WeSpeaker
                                 computes them and the network's vector for it
                                 (copied to tests/fixtures/voice_reference.npz)
"""

import argparse
import hashlib
import shutil
import sys
import urllib.request
from pathlib import Path

import numpy as np
import onnxruntime
import torch
import torchaudio

REPO_ROOT = Path(__file__).resolve().parents[2]
OUT = REPO_ROOT / "data" / "models" / "voice"
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "voice_reference.npz"

REPOSITORY = "Wespeaker/wespeaker-voxceleb-resnet34-LM"
REVISION = "f0c48c298fd835726c27956a5d617bad7115627e"
FILES = ("voxceleb_resnet34_LM.onnx", "config.yaml")

RATE = 16000


def fetch(name: str) -> Path:
    path = OUT / name
    if not path.exists():
        url = f"https://huggingface.co/{REPOSITORY}/resolve/{REVISION}/{name}"
        print(f"downloading {url}")
        with urllib.request.urlopen(url) as response, open(path, "wb") as handle:
            shutil.copyfileobj(response, handle)
    print(f"{name}  sha256 {hashlib.sha256(path.read_bytes()).hexdigest()}")
    return path


def synthetic_voice(seconds: float = 3.0, seed: int = 0) -> np.ndarray:
    """A voiced, speech-like signal in [-1, 1]: a gliding pitch with harmonics,
    syllable-like loudness and a little noise."""
    rng = np.random.default_rng(seed)
    t = np.arange(int(seconds * RATE)) / RATE
    pitch = 140 + 40 * np.sin(2 * np.pi * 0.7 * t)
    phase = 2 * np.pi * np.cumsum(pitch) / RATE
    voiced = sum(np.sin(k * phase) / k for k in range(1, 12))
    envelope = 0.5 + 0.5 * np.sin(2 * np.pi * 4 * t) ** 2
    signal = envelope * voiced + 0.02 * rng.standard_normal(len(t))
    return (0.3 * signal / np.abs(signal).max()).astype(np.float32)


def fbank(samples: np.ndarray) -> np.ndarray:
    """Filterbanks as WeSpeaker computes them for this model (wespeaker/cli/speaker.py):
    16-bit scale, Hamming window, no dither, mean-normalised over the clip."""
    waveform = torch.from_numpy(samples)[None] * (1 << 15)
    features = torchaudio.compliance.kaldi.fbank(
        waveform, num_mel_bins=80, frame_length=25, frame_shift=10,
        sample_frequency=RATE, window_type="hamming", dither=0.0)
    return (features - features.mean(dim=0)).numpy()


def main(argv=None) -> int:
    argparse.ArgumentParser(description=__doc__.split("\n")[0]).parse_args(argv)
    OUT.mkdir(parents=True, exist_ok=True)
    model = fetch(FILES[0])
    fetch(FILES[1])

    session = onnxruntime.InferenceSession(str(model), providers=["CPUExecutionProvider"])
    inputs, outputs = session.get_inputs(), session.get_outputs()
    print("inputs:", [(each.name, each.shape) for each in inputs])
    print("outputs:", [(each.name, each.shape) for each in outputs])

    samples = synthetic_voice()
    features = fbank(samples)
    vector = session.run(None, {inputs[0].name: features[None].astype(np.float32)})[0][0]
    print(f"filterbanks {features.shape}, vector {vector.shape}, norm {np.linalg.norm(vector):.3f}")

    np.savez(OUT / "reference.npz", samples=samples, fbank=features, vector=vector)
    FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(OUT / "reference.npz", FIXTURE)
    print(f"wrote {OUT / 'reference.npz'} and {FIXTURE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
