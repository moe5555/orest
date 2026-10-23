"""Four-second clips cut from other footage, for Athene's clusters.

Each video in the source folder gives PER_VIDEO clips of CLIP_SECONDS, their
starts spread evenly between MARGIN seconds after its start and MARGIN
seconds before its end. With --picks, the clips start where a picks file
says instead, and only the videos it lists are cut. The clips are
re-encoded to H.264 at most 1080 lines high, without sound, and named after
the video and their start in seconds. The renderer (athene/render.py) and
the live page (athene/live.py) serve them as the second clip group, the
clusters of key O.

A picks file maps a video's file name to its clips, each with its start in
seconds, a note of what it shows and optionally the part of the picture to
keep, as x, y, width and height in the video's pixels (16:9, like the
clusters' clips). athene/endvideo_picks.json holds the picks from the end
videos of the play, athene/deathscene_picks.json those from the death scene
rehearsals:

    {"02_Andoril.mp4": [{"start": 2.6, "shows": "missile launch"}, ...], ...}
    {"2026-10-07 11-12-31_DeathScene.mp4":
        [{"start": 612.0, "shows": "...", "crop": [320, 180, 1120, 630]}, ...], ...}

    python -m athene.cut_clips ~/Desktop/04_Endvideos --picks athene/endvideo_picks.json
    python -m athene.cut_clips ~/Desktop/HITL_Database --picks athene/deathscene_picks.json --destination data/clips/athene_deathscene
    python -m athene.cut_clips ~/Desktop/other_footage --destination data/clips/other
"""

import argparse
import json
import re
import subprocess
import unicodedata
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DESTINATION = REPO_ROOT / "data" / "clips" / "athene_endvideos"

CLIP_SECONDS = 4.0
PER_VIDEO = 24
MARGIN = 4.0
VIDEOS = (".mp4", ".mov", ".mkv", ".webm")
UMLAUTS = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "Ä": "Ae", "Ö": "Oe", "Ü": "Ue", "ß": "ss"})


def duration(path):
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True)
    return float(probe.stdout)


def nfc(name):
    """The name in composed Unicode: files copied from macOS spell umlauts as two code points."""
    return unicodedata.normalize("NFC", name)


def safe_name(stem):
    """The stem with umlauts spelt out and everything else but letters, digits
    and hyphens turned into underscores."""
    return re.sub(r"[^A-Za-z0-9-]+", "_", nfc(stem).translate(UMLAUTS)).strip("_")


def spread(source, per_video):
    """Starts of `per_video` clips spread evenly over the video, none if it is too short."""
    usable = duration(source) - 2 * MARGIN - CLIP_SECONDS
    if usable <= 0:
        print(f"skipped {source.name}: shorter than {2 * MARGIN + CLIP_SECONDS:g} s")
        return []
    return [MARGIN + usable * (k + 0.5) / per_video for k in range(per_video)]


def cut(source, destination, picks):
    """Cuts the picks ({"start", optional "crop"}) of the video not yet in `destination`."""
    for pick in picks:
        start = pick["start"]
        path = destination / f"{safe_name(source.stem)}-{start:07.2f}s.mp4"
        if path.is_file():
            continue
        crop = "crop={2}:{3}:{0}:{1},".format(*pick["crop"]) if "crop" in pick else ""
        subprocess.run([
            "ffmpeg", "-y", "-v", "error", "-ss", f"{start:.3f}", "-i", str(source),
            "-t", f"{CLIP_SECONDS:.3f}", "-an", "-vf", f"{crop}scale=-2:'min(1080,ih)'",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
            str(path),
        ], check=True)
        print(f"written {path}")


def main():
    parser = argparse.ArgumentParser(description="Cut four-second clips for Athene's clusters.")
    parser.add_argument("source", type=Path, help="folder of videos")
    parser.add_argument("--destination", type=Path, default=DESTINATION)
    parser.add_argument("--per-video", type=int, default=PER_VIDEO)
    parser.add_argument("--picks", type=Path, help="JSON file of the clips to cut, by video file name")
    args = parser.parse_args()
    args.destination.mkdir(parents=True, exist_ok=True)
    videos = {nfc(p.name): p for p in sorted(args.source.iterdir()) if p.suffix.lower() in VIDEOS}
    if args.picks:
        picks = json.loads(args.picks.read_text(encoding="utf-8"))
        missing = [name for name in picks if nfc(name) not in videos]
        if missing:
            raise SystemExit(f"not in {args.source}: {', '.join(missing)}")
        for name, clips in picks.items():
            cut(videos[nfc(name)], args.destination, clips)
    else:
        for source in videos.values():
            cut(source, args.destination, [{"start": start} for start in spread(source, args.per_video)])


if __name__ == "__main__":
    main()
