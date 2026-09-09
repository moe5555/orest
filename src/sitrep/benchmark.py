"""Latency benchmark: which window and sampling interval can Gemma keep up with?

Implements the measurement step 6 of knowledge/components/02_processing.md asks
for: "X is dependent on latency - do a p95, p99 test and make sure that the
system only processes as many seconds as it can keep up with."

A configuration is sustainable when generation finishes inside the window it
describes. If a 30s window takes 40s to report on, every window arrives later
than the last and the SITREP drifts away from the live feed. The verdict column
compares p95 latency against the window length, not the mean: the system has to
keep up in the bad case, not on average.

Frames are grabbed once from the live camera and reused, so every configuration
sees the same picture and only the frame count and audio length vary. Audio
comes from a speech recording rather than an empty room, since both length and
content drive token count and rehearsals will contain speech.

    python src/sitrep/benchmark.py --runs 10
"""

import argparse
import statistics
import sys
import time
import wave
from pathlib import Path

import numpy as np
from ollama import ResponseError
from pydantic import ValidationError

import capture
import devices
import report

# window seconds, interval seconds between sampled frames
CONFIGURATIONS = [
    (10, 5),
    (15, 5),
    (20, 5),
    (30, 10),
    (30, 5),
    (60, 15),
]

SPEECH = Path("src/data/test01_20s.wav")


def read_wav(path: Path):
    with wave.open(str(path)) as handle:
        data = np.frombuffer(handle.readframes(handle.getnframes()), dtype=np.int16)
        return data.astype(np.float32) / 32767, handle.getframerate()


def speech_of_length(samples, samplerate: int, seconds: float) -> bytes:
    """Encode a speech clip of the requested length, repeating it if needed."""
    wanted = int(seconds * samplerate)
    repeated = np.tile(samples, int(np.ceil(wanted / len(samples))))
    return capture.encode_wav(
        capture.clip_for_encoder(repeated[:wanted], samplerate), samplerate)


def grab_frames(count: int, video_spec=None, width=None, height=None) -> list[bytes]:
    """Take a set of stills from the camera to benchmark against."""
    device = devices.resolve_video_device(video_spec)
    print(f"frames from [{device.index}] {device.name}")
    stream = capture.VideoStream(device, width, height)
    try:
        frames = []
        for _ in range(count):
            frames.append(capture.encode_jpeg(stream.latest()))
            time.sleep(0.2)
        return frames
    finally:
        stream.close()


def percentile(values, fraction: float) -> float:
    return float(np.percentile(values, fraction * 100))


def run(frames_pool: list[bytes], runs: int, model: str, configurations=CONFIGURATIONS):
    speech, samplerate = read_wav(SPEECH)

    print(f"model {model}, {runs} runs per configuration")
    print("warming up...", flush=True)
    report.analyse(frames_pool[:1], model=model)

    header = (f"{'window':>7} {'ivl':>4} {'frames':>7} {'audio':>6} "
              f"{'p50':>7} {'p95':>7} {'p99':>7} {'max':>7} {'bad':>4}  verdict")
    print(f"\n{header}\n{'-' * len(header)}")

    results = []
    for window_s, interval_s in configurations:
        frame_count = max(1, int(window_s / interval_s))
        frames = [frames_pool[i % len(frames_pool)] for i in range(frame_count)]
        audio = speech_of_length(speech, samplerate, window_s)

        # A reply that runs into the token cap is truncated and unparseable.
        # Those attempts still cost their full time, so they are timed here
        # rather than inside analyse() and counted separately: a configuration
        # that is fast but often unusable is not sustainable.
        latencies, failures = [], 0
        for _ in range(runs):
            started = time.monotonic()
            try:
                report.analyse(frames, audio, model=model)
            except (ValidationError, ResponseError):
                failures += 1
            latencies.append(time.monotonic() - started)

        p50 = statistics.median(latencies)
        p95 = percentile(latencies, 0.95)
        p99 = percentile(latencies, 0.99)
        headroom = (window_s - p95) / window_s * 100
        if p95 >= window_s:
            verdict = f"FALLS BEHIND (+{p95 - window_s:.0f}s per window)"
        elif failures:
            verdict = f"OK but {failures}/{runs} unusable"
        else:
            verdict = f"OK  ({headroom:+.0f}% headroom)"

        print(f"{window_s:>6}s {interval_s:>3}s {frame_count:>7} {window_s:>5}s "
              f"{p50:>6.1f}s {p95:>6.1f}s {p99:>6.1f}s {max(latencies):>6.1f}s "
              f"{failures:>4}  {verdict}", flush=True)
        results.append((window_s, interval_s, p95, failures))

    return results


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--video", help="camera index or name fragment")
    parser.add_argument("--runs", type=int, default=10,
                        help="generations per configuration (default: 10)")
    parser.add_argument("--model", default=report.MODEL)
    args = parser.parse_args(argv)

    if not SPEECH.exists():
        raise SystemExit(f"Speech sample {SPEECH} not found.")

    needed = max(int(w / i) for w, i in CONFIGURATIONS)
    frames = grab_frames(needed, args.video)

    started = time.monotonic()
    results = run(frames, args.runs, args.model)

    sustainable = [(w, i) for w, i, p95, bad in results if p95 < w and not bad]
    print(f"\ntotal {time.monotonic() - started:.0f}s")
    if sustainable:
        window_s, interval_s = min(sustainable)
        print(f"smallest sustainable setting: --window {window_s} --interval {interval_s}")
    else:
        print("no configuration keeps up; reduce frames, shorten audio or use a smaller model",
              file=sys.stderr)
    if args.runs < 20:
        print(f"note: p99 from {args.runs} runs is effectively the maximum observed; "
              f"raise --runs for a real tail estimate", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
