"""Athene's ear: a recorded voice turned into the values that move the sphere.

The clip is decoded by ffmpeg and measured once per video frame, at the LED
wall's 50 fps, each measurement over a 43 ms window centred on the frame's
time. The page (athene/page/athene.js) takes these values, and nothing else,
from the sound, so the preview and the render move identically.

Per frame:
  level   loudness of the voice, 0 (silence) to 1 (the clip's loud passages),
          on a 40 dB scale below them. It falls back slowly after a sound and
          rises shortly before one: the whole clip is known, so the sphere
          can draw breath ahead of a line instead of reacting after it.
  tone    how bright the voice sounds, 0 (dark vowels) to 1 (sibilants), from
          the spectral centroid; held through silence.
Per syllable:
  onsets  [time, strength]: where energy rises across the speech band
          (spectral flux), at least 120 ms apart.

    python -m athene.analyse athene/example_audio/Human_Lena_Voice.mp3
"""

import argparse
import json
import math
import subprocess
from pathlib import Path

import numpy as np

RATE = 48000
FPS = 50
HOP = RATE // FPS
WINDOW = 2048

# Speech band for loudness and the centroid.
SPEECH_HZ = (80.0, 10000.0)
# Level: the clip's loud passages (98th percentile) are 1, 40 dB below is 0.
LOUD_PERCENTILE = 98
LEVEL_RANGE_DB = 40.0
# Fall-back time after a sound, and the lead before one, in seconds.
RELEASE = 0.20
ANTICIPATION = 0.08

# Tone: magnitude-weighted centroids from 500 Hz to 5 kHz, on a log scale,
# smoothed over 150 ms. Lena's voiced frames lie at 540 to 1400 Hz (5th to
# 75th percentile), her sibilants above 5 kHz.
TONE_HZ = (500.0, 5000.0)
TONE_SMOOTH = 0.15
# Frames below this raw level count as silence and hold the last tone.
VOICED = 0.25

# Onsets: spectral flux from 150 Hz to 5 kHz, a peak above the 0.5 s moving
# mean by ONSET_DELTA, and the largest within ±120 ms.
FLUX_HZ = (150.0, 5000.0)
ONSET_GAP = 0.12
ONSET_DELTA = 0.10
ONSET_CONTEXT = 0.5
ONSET_MIN_LEVEL = 0.15


def decode(path):
    """The clip as mono float samples at RATE, decoded by ffmpeg."""
    command = ["ffmpeg", "-v", "error", "-i", str(path),
               "-ac", "1", "-ar", str(RATE), "-f", "f32le", "-"]
    raw = subprocess.run(command, check=True, capture_output=True).stdout
    return np.frombuffer(raw, np.float32)


def spectra(sound):
    """Magnitude spectra of Hann windows centred on each frame's time i / FPS."""
    count = math.ceil(len(sound) / HOP)
    padded = np.pad(sound, (WINDOW // 2, WINDOW // 2 + HOP))
    index = np.arange(WINDOW)[None, :] + HOP * np.arange(count)[:, None]
    return np.abs(np.fft.rfft(padded[index] * np.hanning(WINDOW), axis=1))


def follow(x, release):
    """Peak follower: takes every rise at once, decays with the time constant."""
    keep = math.exp(-1.0 / (release * FPS))
    out = np.empty_like(x)
    y = 0.0
    for i, v in enumerate(x):
        y = max(v, y * keep)
        out[i] = y
    return out


def smooth(x, seconds):
    """Centred moving average, the edges extended."""
    n = max(1, round(seconds * FPS))
    padded = np.pad(x, (n // 2, n - 1 - n // 2), mode="edge")
    return np.convolve(padded, np.ones(n) / n, mode="valid")


def band(freqs, hz):
    return (freqs >= hz[0]) & (freqs <= hz[1])


def loudness(mag, freqs):
    """Level before the follower: 0 to 1 on the clip's 40 dB scale."""
    power = (mag[:, band(freqs, SPEECH_HZ)] ** 2).sum(axis=1)
    db = 10.0 * np.log10(power + 1e-12)
    loud = np.percentile(db, LOUD_PERCENTILE)
    return np.clip((db - (loud - LEVEL_RANGE_DB)) / LEVEL_RANGE_DB, 0.0, 1.0)


def brightness(mag, freqs, raw):
    """Tone: log-scaled spectral centroid, held through silence and smoothed."""
    inside = band(freqs, SPEECH_HZ)
    weight = mag[:, inside]
    centroid = (weight * freqs[inside]).sum(axis=1) / (weight.sum(axis=1) + 1e-12)
    low, high = TONE_HZ
    tone = np.clip(np.log(np.maximum(centroid, 1.0) / low) / math.log(high / low), 0.0, 1.0)
    voiced = raw > VOICED
    if voiced.any():
        held = np.maximum.accumulate(np.where(voiced, np.arange(len(tone)), -1))
        held[held < 0] = np.argmax(voiced)
        tone = tone[held]
    return smooth(tone, TONE_SMOOTH)


def syllables(mag, freqs, raw):
    """Onset times and strengths (0 to 1) from peaks of the spectral flux."""
    spectrum = np.log1p(mag[:, band(freqs, FLUX_HZ)] / (mag.max() + 1e-12) * 1000.0)
    flux = np.maximum(np.diff(spectrum, axis=0, prepend=spectrum[:1]), 0.0).sum(axis=1)
    flux /= np.percentile(flux, 99) + 1e-12
    threshold = smooth(flux, ONSET_CONTEXT) + ONSET_DELTA
    gap = round(ONSET_GAP * FPS)
    padded = np.pad(flux, gap, mode="constant", constant_values=-1.0)
    local_max = np.lib.stride_tricks.sliding_window_view(padded, 2 * gap + 1).max(axis=1)
    peaks = np.flatnonzero((flux >= local_max) & (flux > threshold) & (raw > ONSET_MIN_LEVEL))
    if len(peaks) == 0:
        return []
    strength = np.clip(flux[peaks] / np.percentile(flux[peaks], 90), 0.0, 1.0)
    return [[round(i / FPS, 3), round(float(s), 3)] for i, s in zip(peaks, strength)]


def analyse(path):
    """The clip's per-frame values and onsets, as the page reads them."""
    sound = decode(path)
    mag = spectra(sound)
    freqs = np.fft.rfftfreq(WINDOW, 1.0 / RATE)
    raw = loudness(mag, freqs)
    level = np.maximum(follow(raw, RELEASE), follow(raw[::-1], ANTICIPATION)[::-1])
    return {
        "clip": Path(path).name,
        "fps": FPS,
        "frames": len(raw),
        "duration": round(len(sound) / RATE, 3),
        "level": [round(float(v), 4) for v in level],
        "tone": [round(float(v), 4) for v in brightness(mag, freqs, raw)],
        "onsets": syllables(mag, freqs, raw),
    }


def write(analysis, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(analysis, separators=(",", ":")), encoding="utf-8")


def summary(analysis):
    level = np.asarray(analysis["level"])
    return (f"{analysis['clip']}: {analysis['duration']:.1f} s, {analysis['frames']} frames, "
            f"voice in {np.mean(level > 0.1):.0%} of them, {len(analysis['onsets'])} onsets")


def main():
    parser = argparse.ArgumentParser(description="Measure a voice clip for Athene.")
    parser.add_argument("clip", type=Path)
    parser.add_argument("--out", type=Path, help="JSON file (default: athene/out/<clip>/analysis.json)")
    args = parser.parse_args()
    analysis = analyse(args.clip)
    out = args.out or Path(__file__).parent / "out" / args.clip.stem / "analysis.json"
    write(analysis, out)
    print(summary(analysis))
    print(f"written to {out}")


if __name__ == "__main__":
    main()
