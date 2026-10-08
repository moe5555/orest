"""Who is speaking, by voice: the cast told apart by how they sound.

Lines are attributed by lip movement (speakers.py), which needs a visible,
large enough mouth. On a wide stage shot the lips are a few pixels, and someone
turned away has none. Their voice reaches the microphone from any side.

WeSpeaker's ResNet34-LM, a speaker-verification network trained on VoxCeleb2
(data/models/voice/SOURCE.md), turns a stretch of speech into a 256-value voice
vector in which two stretches of the same voice lie close together. Each cast
member's voice is enrolled from clips in data/cast/<Name>/voice/: the clips are
cut into windows of speech the length of a spoken line, and the person's voice
is the mean of the windows' vectors. A line is matched against every enrolled
voice and named when one is clearly closest (`Voices.identify`); overlapping
speech and voices not enrolled match no one.

The network's input, Kaldi filterbanks, is computed here in numpy as torchaudio
computes it for WeSpeaker; src/scripts/export_voice.py writes the reference it
is tested against. Nothing is written to disk.

Measure how well the cast's voices are told apart, on clips held out from the
enrolment and on a dialogue labelled by hand:

    python -m sitrep.voices data/cast --test held_out/
    python -m sitrep.voices data/cast --dialogue dialog.wav --write-labels dialog.csv
    python -m sitrep.voices data/cast --dialogue dialog.wav --labels dialog.csv

`held_out/` holds one folder per person, named as in the cast. In the labels
file, Moe fills in the `speaker` column: a cast name, or any other word for
someone not enrolled.
"""

import argparse
import csv
import io
import os
import sys
import threading
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from action import model as action_model

from . import capture, transcribe, utterances

REPO_ROOT = Path(__file__).resolve().parents[2]

MODEL_DIR = Path(os.environ.get("APOLLON_VOICE_MODEL_DIR",
                                REPO_ROOT / "data" / "models" / "voice"))
MODEL_FILE = "voxceleb_resnet34_LM.onnx"

# Each person's enrolment clips, inside their cast folder beside the photos.
VOICE_FOLDER = "voice"
AUDIO_SUFFIXES = {".wav", ".flac", ".mp3", ".m4a", ".ogg"}

# Filterbanks as WeSpeaker computes them for this model
# (wespeaker/cli/speaker.py): 16 kHz sound at 16-bit scale, 25 ms Hamming
# frames every 10 ms, 80 mel bins from 20 Hz to the Nyquist frequency, no
# dither, the mean over the stretch subtracted.
RATE = 16000
FRAME = 400
SHIFT = 160
FFT = 512
MEL_BINS = 80
LOW_FREQ = 20.0
PREEMPHASIS = 0.97
EPSILON = float(np.finfo(np.float32).eps)

# Stretches shorter than this many seconds are not matched: a voice vector
# from under a second of speech is unreliable. Provisional until measured on
# the cast's clips.
MIN_VOICE = 1.0

# Enrolment windows: each stretch of speech in a clip is cut into parts of
# about WINDOW seconds, the length of a spoken line.
WINDOW = 2.0

# A line is named when its vector's cosine to a person's voice reaches
# THRESHOLD and beats every other person's by MARGIN. Provisional until
# measured on the cast's clips.
THRESHOLD = 0.5
MARGIN = 0.1

_lock = threading.Lock()
_session = None


def available() -> bool:
    """Whether the model is installed. Without it lines are attributed by lips alone."""
    return (MODEL_DIR / MODEL_FILE).exists()


def session():
    """The shared inference session, created on first use."""
    global _session
    with _lock:
        if _session is None:
            import onnxruntime

            path = MODEL_DIR / MODEL_FILE
            if not path.exists():
                raise RuntimeError(
                    f"No voice model at {path}. Fetch it with "
                    f"src/scripts/export_voice.py, or set APOLLON_VOICE_MODEL_DIR.")
            _session = onnxruntime.InferenceSession(str(path), providers=action_model.providers())
        return _session


def active_provider() -> str:
    """Where the voice model runs, e.g. "CUDAExecutionProvider"."""
    return session().get_providers()[0]


def decode(data: bytes | str | Path) -> np.ndarray:
    """Sound from a file or WAV bytes as mono float samples at RATE, decoded
    as Whisper decodes it."""
    from faster_whisper import decode_audio

    source = io.BytesIO(data) if isinstance(data, bytes) else str(data)
    return decode_audio(source, sampling_rate=RATE).astype(np.float32)


def _mel(frequency):
    return 1127.0 * np.log(1.0 + np.asarray(frequency) / 700.0)


def _mel_banks() -> np.ndarray:
    """Triangular mel filters over the FFT bins, (MEL_BINS, FFT // 2 + 1)."""
    low, high = _mel(LOW_FREQ), _mel(RATE / 2)
    delta = (high - low) / (MEL_BINS + 1)
    left = low + delta * np.arange(MEL_BINS)[:, None]
    centre, right = left + delta, left + 2 * delta
    mel = _mel(RATE / FFT * np.arange(FFT // 2))[None, :]
    rising = (mel - left) / (centre - left)
    falling = (right - mel) / (right - centre)
    banks = np.maximum(0.0, np.minimum(rising, falling))
    # The Nyquist bin carries no filter weight.
    return np.pad(banks, ((0, 0), (0, 1)))


_BANKS = _mel_banks()
_WINDOW = np.hamming(FRAME)


def fbank(samples: np.ndarray) -> np.ndarray:
    """Log mel filterbanks of mono samples at RATE, mean-normalised, (frames, MEL_BINS)."""
    scaled = np.asarray(samples, dtype=np.float64) * (1 << 15)
    count = 1 + (len(scaled) - FRAME) // SHIFT
    if count < 1:
        return np.zeros((0, MEL_BINS), dtype=np.float32)
    frames = np.lib.stride_tricks.sliding_window_view(scaled, FRAME)[::SHIFT][:count]
    frames = frames - frames.mean(axis=1, keepdims=True)
    previous = np.concatenate([frames[:, :1], frames[:, :-1]], axis=1)
    frames = (frames - PREEMPHASIS * previous) * _WINDOW
    power = np.abs(np.fft.rfft(frames, n=FFT)) ** 2
    features = np.log(np.maximum(power @ _BANKS.T, EPSILON))
    return (features - features.mean(axis=0)).astype(np.float32)


def embed(samples: np.ndarray) -> np.ndarray:
    """The unit-length voice vector of a stretch of speech at RATE, (256,)."""
    features = fbank(samples)
    vector = session().run(None, {"feats": features[None]})[0][0]
    return vector / max(float(np.linalg.norm(vector)), 1e-12)


def speech(samples: np.ndarray) -> list[tuple[int, int]]:
    """Stretches of speech in a recording at RATE, as [first, after) sample
    indices, cut as the live run cuts utterances (utterances.Segmenter)."""
    vad, segmenter = utterances.Vad(), utterances.Segmenter()
    spans = segmenter.push(vad(samples))
    # Silence after the recording ends the last stretch.
    spans += segmenter.push(np.zeros(round(1.0 / utterances.STEP), dtype=np.float32))
    return [(first * utterances.CHUNK, min(after * utterances.CHUNK, len(samples)))
            for first, after in spans]


def windows(samples: np.ndarray) -> list[np.ndarray]:
    """A recording's speech in parts of about WINDOW seconds, none shorter than MIN_VOICE."""
    parts = []
    for first, after in speech(samples):
        length = (after - first) / RATE
        if length < MIN_VOICE:
            continue
        count = max(1, round(length / WINDOW))
        edges = np.linspace(first, after, count + 1).astype(int)
        parts += [samples[start:end] for start, end in zip(edges[:-1], edges[1:])]
    return parts


@dataclass(frozen=True)
class Verdict:
    """Whose voice a stretch is: `name`, or None when no voice is clearly
    closest. `score` is the cosine to the closest voice, `margin` its lead
    over the next."""

    name: str | None
    score: float
    margin: float
    closest: str | None = None


class Voices:
    """The cast's enrolled voices, and the matching of a stretch of speech against them."""

    def __init__(self, voices: dict[str, np.ndarray], *,
                 threshold: float = THRESHOLD, margin: float = MARGIN):
        self._names = list(voices)
        self._voices = (np.stack([value / np.linalg.norm(value) for value in voices.values()])
                        if voices else np.zeros((0, 0), dtype=np.float32))
        self.threshold = threshold
        self.margin = margin

    @classmethod
    def enrol(cls, root: Path, **options) -> "Voices":
        """Every person in a cast folder with clips in their `voice` folder."""
        found = {}
        for person in sorted(path for path in Path(root).iterdir() if path.is_dir()):
            clips = sorted(path for path in (person / VOICE_FOLDER).glob("*")
                           if path.suffix.lower() in AUDIO_SUFFIXES)
            parts = [part for clip in clips for part in windows(decode(clip))]
            if parts:
                found[person.name] = np.mean([embed(part) for part in parts], axis=0)
        return cls(found, **options)

    @property
    def names(self) -> list[str]:
        return list(self._names)

    def scores(self, vector: np.ndarray) -> dict[str, float]:
        """Cosine of a unit voice vector to each enrolled voice."""
        return dict(zip(self._names, (self._voices @ vector).tolist())) if self._names else {}

    def similarities(self) -> dict[tuple[str, str], float]:
        """Cosine between every two enrolled voices."""
        matrix = self._voices @ self._voices.T
        return {(first, second): float(matrix[i, j])
                for i, first in enumerate(self._names)
                for j, second in enumerate(self._names) if i < j}

    def match(self, vector: np.ndarray, threshold: float | None = None,
              margin: float | None = None) -> Verdict:
        """Whose voice a unit voice vector is, at the set or the given threshold and margin."""
        threshold = self.threshold if threshold is None else threshold
        margin = self.margin if margin is None else margin
        ranked = sorted(self.scores(vector).items(), key=lambda item: item[1], reverse=True)
        if not ranked:
            return Verdict(None, 0.0, 0.0)
        closest, score = ranked[0]
        lead = score - ranked[1][1] if len(ranked) > 1 else score
        sure = score >= threshold and lead >= margin
        return Verdict(closest if sure else None, score, lead, closest)

    def identify(self, samples: np.ndarray) -> Verdict:
        """Whose voice a stretch of speech at RATE is; no one under MIN_VOICE seconds."""
        if len(samples) < MIN_VOICE * RATE or not self._names:
            return Verdict(None, 0.0, 0.0)
        return self.match(embed(samples))

    def clear(self):
        """Delete the enrolled voices held."""
        self._names, self._voices = [], np.zeros((0, 0), dtype=np.float32)


# Measurement ----------------------------------------------------------------

LENGTHS = ((0.0, 1.0), (1.0, 2.0), (2.0, 4.0), (4.0, float("inf")))
THRESHOLDS = (0.3, 0.4, 0.5, 0.6, 0.7)
MARGINS = (0.0, 0.05, 0.1, 0.15, 0.2)


def _bucket(seconds: float) -> str:
    for low, high in LENGTHS:
        if low <= seconds < high:
            return f"{low:g}-{high:g} s" if high != float("inf") else f"over {low:g} s"
    return "?"


def _evaluate(voices: Voices, rows: list[tuple[str, float, np.ndarray]]):
    """Print how stretches with known speakers are matched.

    `rows` are (true speaker, seconds, unit vector). A speaker not enrolled
    counts as right when no one is named.
    """
    enrolled = set(voices.names)
    same = [voices.scores(vector)[speaker] for speaker, _, vector in rows if speaker in enrolled]
    other = [score for speaker, _, vector in rows
             for name, score in voices.scores(vector).items() if name != speaker]
    for label, values in (("same person", same), ("other person", other)):
        if values:
            p5, p50, p95 = np.percentile(values, [5, 50, 95])
            print(f"cosine, {label}: p5 {p5:.2f}  median {p50:.2f}  p95 {p95:.2f}  (n={len(values)})")

    def tally(subset, threshold, margin):
        right = wrong = unsure = 0
        for speaker, _, vector in subset:
            verdict = voices.match(vector, threshold, margin)
            if verdict.name is None:
                if speaker in enrolled:
                    unsure += 1
                else:
                    right += 1
            elif verdict.name == speaker:
                right += 1
            else:
                wrong += 1
        total = max(1, len(subset))
        return f"{100 * right / total:3.0f} /{100 * wrong / total:3.0f} /{100 * unsure / total:3.0f}"

    print(f"\nat THRESHOLD {voices.threshold} / MARGIN {voices.margin}, % right / wrong / unsure")
    for speaker in sorted({row[0] for row in rows}):
        subset = [row for row in rows if row[0] == speaker]
        tag = "" if speaker in enrolled else "  (not enrolled: right = no name)"
        print(f"  {speaker:<12} {tally(subset, voices.threshold, voices.margin)}  n={len(subset)}{tag}")
    for low, high in LENGTHS:
        subset = [row for row in rows if low <= row[1] < high]
        if subset:
            print(f"  {_bucket(low):<12} {tally(subset, voices.threshold, voices.margin)}  n={len(subset)}")

    print("\nstretches of at least MIN_VOICE, % right / wrong / unsure")
    long_enough = [row for row in rows if row[1] >= MIN_VOICE]
    print("  threshold \\ margin" + "".join(f"{margin:>16}" for margin in MARGINS))
    for threshold in THRESHOLDS:
        print(f"  {threshold:<18}" + "".join(f"{tally(long_enough, threshold, margin):>16}"
                                             for margin in MARGINS))


def _held_out(voices: Voices, folder: Path) -> list[tuple[str, float, np.ndarray]]:
    rows = []
    for person in sorted(path for path in folder.iterdir() if path.is_dir()):
        for clip in sorted(path for path in person.glob("*") if path.suffix.lower() in AUDIO_SUFFIXES):
            samples = decode(clip)
            for first, after in speech(samples):
                if after - first >= FRAME:
                    rows.append((person.name, (after - first) / RATE, embed(samples[first:after])))
    return rows


def _write_labels(dialogue: Path, path: Path, language: str):
    samples = decode(dialogue)
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["begin", "end", "text", "speaker"])
        for first, after in speech(samples):
            offset, length = first / RATE, (after - first) / RATE
            for segment in transcribe.segments(capture.encode_wav(samples[first:after], RATE),
                                               language=language):
                # Whisper reads a stretch padded to 30 s, and may time a
                # segment past the stretch's end.
                end = min(segment.end, length)
                writer.writerow([f"{offset + segment.start:.2f}", f"{offset + end:.2f}",
                                 segment.text, ""])
    print(f"wrote {path}: fill in the speaker column")


def _labelled(dialogue: Path, path: Path) -> list[tuple[str, float, np.ndarray]]:
    samples = decode(dialogue)
    rows = []
    with open(path, encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            speaker = (row.get("speaker") or "").strip()
            if not speaker:
                continue
            first, after = int(float(row["begin"]) * RATE), int(float(row["end"]) * RATE)
            if after - first >= FRAME:
                rows.append((speaker, (after - first) / RATE, embed(samples[first:after])))
    return rows


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m sitrep.voices",
        description="Measure how well the cast's voices are told apart.")
    parser.add_argument("cast", type=Path, help="cast folder with <Name>/voice/ clips")
    parser.add_argument("--test", type=Path, help="held-out clips, one folder per person")
    parser.add_argument("--dialogue", type=Path, help="a recorded dialogue")
    parser.add_argument("--labels", type=Path, help="the dialogue's labelled lines (CSV)")
    parser.add_argument("--write-labels", type=Path,
                        help="transcribe the dialogue into a CSV whose speakers are to be filled in")
    parser.add_argument("--language", default=transcribe.LANGUAGE)
    args = parser.parse_args(argv)

    if args.dialogue and args.write_labels:
        _write_labels(args.dialogue, args.write_labels, args.language)
        return 0

    voices = Voices.enrol(args.cast)
    if not voices.names:
        print(f"no voice clips under {args.cast}/*/{VOICE_FOLDER}/", file=sys.stderr)
        return 1
    print(f"enrolled: {', '.join(voices.names)}  ({active_provider()})")
    for (first, second), similarity in voices.similarities().items():
        print(f"  {first} - {second}: cosine {similarity:.2f}")

    if args.test:
        print(f"\nheld out: {args.test}")
        _evaluate(voices, _held_out(voices, args.test))
    if args.dialogue and args.labels:
        print(f"\ndialogue: {args.dialogue}")
        _evaluate(voices, _labelled(args.dialogue, args.labels))
    return 0


if __name__ == "__main__":
    sys.exit(main())
