"""A body search wall rendered to one video: a grid of tiles, each playing
its clips one after the other.

A picks file names the grid as columns and rows, the length of every clip in
seconds, and for each tile, left to right and top to bottom, its clips in
order: the recording's file name, the start in seconds and a note of what it
shows. Every tile holds the same number of clips, so all tiles cut at the
same moments and the wall runs clips x clip_seconds long. An optional
"query" notes how the clips were found:

    {"grid": [3, 3], "clip_seconds": 4.0, "query": "...",
     "tiles": [[{"file": "2026-10-15 15-01-44_LAWS.mp4", "start": 1633.5,
                 "shows": "woman in a red top walks right"}, ...], ...]}

The clips are cut from the rehearsal recordings, scaled to fill a tile
(the wall's size divided by the grid) and encoded as H.264 at 25 fps
without sound, as the walls TouchDesigner loops.

    python src/scripts/bodysearch_wall.py src/scripts/bodysearch_picks/walk_female_2b.json ~/Desktop/bodysearch_2b_1911.mp4
"""

import argparse
import json
import subprocess
from pathlib import Path

DEFAULT_SOURCE = Path.home() / "Desktop" / "HITL_Database"
FPS = 25


def load_picks(path):
    picks = json.loads(Path(path).read_text(encoding="utf-8"))
    columns, rows = picks["grid"]
    tiles = picks["tiles"]
    if len(tiles) != columns * rows:
        raise SystemExit(f"{path}: {len(tiles)} tiles for a {columns}x{rows} grid")
    if len({len(tile) for tile in tiles}) != 1:
        raise SystemExit(f"{path}: tiles hold different numbers of clips")
    return columns, rows, float(picks["clip_seconds"]), tiles


def command(columns, rows, seconds, tiles, source, output, width, height, crf):
    tile_w, tile_h = width // columns, height // rows
    args = ["ffmpeg", "-v", "error", "-y"]
    for tile in tiles:
        for clip in tile:
            recording = source / clip["file"]
            if not recording.exists():
                raise SystemExit(f"missing recording: {recording}")
            args += ["-ss", f"{clip['start']:.3f}", "-t", f"{seconds:.3f}", "-i", str(recording)]

    # Each clip is cut to exactly its length in frames, so tiles stay in step
    # whatever the recording's own timestamps.
    frames = round(seconds * FPS)
    graph, index = [], 0
    for t, tile in enumerate(tiles):
        names = []
        for _ in tile:
            graph.append(
                f"[{index}:v]fps={FPS},scale={tile_w}:{tile_h}:force_original_aspect_ratio=increase,"
                f"crop={tile_w}:{tile_h},setsar=1,trim=end_frame={frames},setpts=PTS-STARTPTS[c{index}]")
            names.append(f"[c{index}]")
            index += 1
        graph.append(f"{''.join(names)}concat=n={len(names)}:v=1:a=0[t{t}]")
    layout = "|".join(f"{(t % columns) * tile_w}_{(t // columns) * tile_h}" for t in range(len(tiles)))
    graph.append(f"{''.join(f'[t{t}]' for t in range(len(tiles)))}xstack=inputs={len(tiles)}:layout={layout}[wall]")

    args += ["-filter_complex", ";".join(graph), "-map", "[wall]", "-an",
             "-c:v", "libx264", "-preset", "medium", "-crf", str(crf), "-pix_fmt", "yuv420p",
             "-r", str(FPS), "-movflags", "+faststart", str(output)]
    return args


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("picks", help="picks file: grid, clip length and each tile's clips")
    parser.add_argument("output", help="video to write")
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE,
                        help=f"folder of the recordings (default: {DEFAULT_SOURCE})")
    parser.add_argument("--size", default="1920x1080", help="size of the wall (default: 1920x1080)")
    parser.add_argument("--crf", type=int, default=18, help="x264 quality (default: 18)")
    args = parser.parse_args()

    width, height = (int(v) for v in args.size.lower().split("x"))
    columns, rows, seconds, tiles = load_picks(args.picks)
    subprocess.run(command(columns, rows, seconds, tiles, args.source, Path(args.output),
                           width, height, args.crf), check=True)
    print(f"{args.output}: {columns}x{rows} tiles, {len(tiles[0])} clips of {seconds:g} s each")


if __name__ == "__main__":
    main()
