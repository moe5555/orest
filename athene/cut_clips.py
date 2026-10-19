"""Four-second clips cut from other footage, for Athene's clusters.

Each video in the source folder gives PER_VIDEO clips of CLIP_SECONDS, their
starts spread evenly between MARGIN seconds after its start and MARGIN
seconds before its end. The clips are re-encoded to H.264 at most 1080 lines
high, without sound, and named after the video and their start in seconds.
The renderer (athene/render.py) serves them as the second clip group.

    python -m athene.cut_clips ~/Desktop/athene_online_clips
"""

import argparse
import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DESTINATION = REPO_ROOT / "data" / "clips" / "athene_online"

CLIP_SECONDS = 4.0
PER_VIDEO = 24
MARGIN = 4.0
VIDEOS = (".mp4", ".mov", ".mkv", ".webm")


def duration(path):
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True)
    return float(probe.stdout)


def safe_name(stem):
    """The stem with everything but letters, digits and hyphens turned into underscores."""
    return re.sub(r"[^A-Za-z0-9-]+", "_", stem).strip("_")


def cut(source, destination, per_video):
    length = duration(source)
    usable = length - 2 * MARGIN - CLIP_SECONDS
    if usable <= 0:
        print(f"skipped {source.name}: shorter than {2 * MARGIN + CLIP_SECONDS:g} s")
        return
    for k in range(per_video):
        start = MARGIN + usable * (k + 0.5) / per_video
        path = destination / f"{safe_name(source.stem)}-{start:07.2f}s.mp4"
        if path.is_file():
            continue
        subprocess.run([
            "ffmpeg", "-y", "-v", "error", "-ss", f"{start:.3f}", "-i", str(source),
            "-t", f"{CLIP_SECONDS:.3f}", "-an", "-vf", "scale=-2:'min(1080,ih)'",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
            str(path),
        ], check=True)
        print(f"written {path}")


def main():
    parser = argparse.ArgumentParser(description="Cut four-second clips for Athene's clusters.")
    parser.add_argument("source", type=Path, help="folder of videos")
    parser.add_argument("--destination", type=Path, default=DESTINATION)
    parser.add_argument("--per-video", type=int, default=PER_VIDEO)
    args = parser.parse_args()
    args.destination.mkdir(parents=True, exist_ok=True)
    for source in sorted(args.source.iterdir()):
        if source.suffix.lower() in VIDEOS:
            cut(source, args.destination, args.per_video)


if __name__ == "__main__":
    main()
