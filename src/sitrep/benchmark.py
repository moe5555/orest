"""Latency benchmark: which window and sampling interval can the SITREP keep up with?

Implements the measurement step 6 of knowledge/components/02_processing.md asks
for: "X is dependent on latency - do a p95, p99 test and make sure that the
system only processes as many seconds as it can keep up with."

A configuration is sustainable when a window's report — transcription and
generation together — finishes inside the window it describes. If a 30s window
takes 40s to report on, every window arrives later than the last and the SITREP
drifts away from the live feed. The verdict column compares p95 latency against
the window length, not the mean: the system has to keep up in the bad case, not
on average.

Generation blocks the next capture window, so the gap between reports is the
latency and the share of rehearsal actually observed is W/(W+latency). That
coverage, not headroom, is what distinguishes two configurations that both keep
up, so it is reported per configuration and drives the recommendation.

Frames are grabbed once from the live camera and reused, so every configuration
sees the same picture and only the frame count and audio length vary. The audio
must contain speech: the voice-activity filter skips silence almost for free, so
benchmarking on room tone would understate transcription cost.

    python -m sitrep.benchmark --speech path/to/speech.wav --runs 10
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

from . import capture, cli, devices, report, transcribe

# window seconds, interval seconds between sampled frames
CONFIGURATIONS = [
    (10, 5),
    (15, 5),
    (20, 5),
    (30, 10),
    (30, 5),
    (60, 15),
]


def read_wav(path: Path):
    with wave.open(str(path)) as handle:
        data = np.frombuffer(handle.readframes(handle.getnframes()), dtype=np.int16)
        return data.astype(np.float32) / 32767, handle.getframerate()


def speech_of_length(samples, samplerate: int, seconds: float) -> bytes:
    """Encode a speech clip of the requested length, repeating it if needed."""
    wanted = int(seconds * samplerate)
    repeated = np.tile(samples, int(np.ceil(wanted / len(samples))))
    return capture.encode_wav(repeated[:wanted], samplerate)


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


def coverage(window_s: float, latency_s: float) -> float:
    """Share of rehearsal time a configuration observes, as a percentage."""
    return window_s / (window_s + latency_s) * 100


def run(frames_pool: list[bytes], speech: Path, runs: int, model: str,
        configurations=CONFIGURATIONS):
    samples, samplerate = read_wav(speech)

    print(f"model {model}, whisper {transcribe.MODEL}, {runs} runs per configuration")
    print("warming up...", flush=True)
    report.analyse(frames_pool[:1], transcribe.transcribe(
        speech_of_length(samples, samplerate, 5)), model=model)

    header = (f"{'window':>7} {'ivl':>4} {'frames':>7} {'trans':>6} {'gen':>6} "
              f"{'p50':>7} {'p95':>7} {'p99':>7} {'max':>7} {'bad':>4} {'cover':>6}  verdict")
    print(f"\n{header}\n{'-' * len(header)}")

    results = []
    for window_s, interval_s in configurations:
        frame_count = capture.frames_per_window(window_s, interval_s)
        frames = [frames_pool[i % len(frames_pool)] for i in range(frame_count)]
        audio = speech_of_length(samples, samplerate, window_s)

        # An unusable reply still costs its full time, so every attempt is
        # timed and failures are counted separately: a configuration that is
        # fast but often unusable is not sustainable.
        totals, transcription, generation, failures = [], [], [], 0
        for _ in range(runs):
            started = time.monotonic()
            transcript = transcribe.transcribe(audio)
            transcribed = time.monotonic()
            try:
                report.analyse(frames, transcript, model=model)
            except (ValidationError, ResponseError):
                failures += 1
            finished = time.monotonic()
            transcription.append(transcribed - started)
            generation.append(finished - transcribed)
            totals.append(finished - started)

        p50 = statistics.median(totals)
        p95 = percentile(totals, 0.95)
        p99 = percentile(totals, 0.99)
        observed = coverage(window_s, p95)
        if p95 >= window_s:
            verdict = f"FALLS BEHIND (+{p95 - window_s:.0f}s per window)"
        elif failures:
            verdict = f"OK but {failures}/{runs} unusable"
        else:
            verdict = "OK"

        print(f"{window_s:>6}s {interval_s:>3}s {frame_count:>7} "
              f"{statistics.median(transcription):>5.1f}s {statistics.median(generation):>5.1f}s "
              f"{p50:>6.1f}s {p95:>6.1f}s {p99:>6.1f}s {max(totals):>6.1f}s "
              f"{failures:>4} {observed:>5.0f}%  {verdict}", flush=True)
        results.append((window_s, interval_s, p95, failures))

    return results


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__.splitlines()[0],
        parents=[cli.sources()],
    )
    parser.add_argument("--speech", type=Path, required=True,
                        help="WAV file containing speech, used as the window audio")
    parser.add_argument("--runs", type=int, default=10,
                        help="reports per configuration (default: 10)")
    parser.add_argument("--model", default=report.MODEL)
    args = parser.parse_args(argv)

    if not args.speech.exists():
        raise SystemExit(f"Speech file {args.speech} not found.")

    needed = max(capture.frames_per_window(w, i) for w, i in CONFIGURATIONS)
    frames = grab_frames(needed, args.video)

    started = time.monotonic()
    results = run(frames, args.speech, args.runs, args.model)

    sustainable = [(w, i, p95) for w, i, p95, bad in results if p95 < w and not bad]
    print(f"\ntotal {time.monotonic() - started:.0f}s")
    if sustainable:
        window_s, interval_s, p95 = max(sustainable, key=lambda r: coverage(r[0], r[2]))
        print(f"best coverage: --window {window_s} --interval {interval_s} "
              f"({coverage(window_s, p95):.0f}% of rehearsal time observed)")
        print("every configuration marked OK keeps up; shorter windows report "
              "more often and observe less.")
    else:
        print("no configuration keeps up; reduce frames, use a smaller model, "
              "or a smaller Whisper model", file=sys.stderr)
    if args.runs < 20:
        print(f"note: p99 from {args.runs} runs is effectively the maximum observed; "
              f"raise --runs for a real tail estimate", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
