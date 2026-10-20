"""Athene live: the scenes of the play, performed from the keyboard in rehearsals.

Serves the rehearsal design (athene/page/designs/rehearsal.js) in live mode
with the voice clips of the scenes and the clip groups of the clusters, and
opens it in the browser. Each voice clip is analysed once (athene/analyse.py)
and the analysis kept next to the others in athene/out/live/; it is redone
when the clip is newer. The clusters play the renderer's picks of each clip
group (athene/render.py) as small looping videos, CLIP_WIDTH px wide and
without sound, cut once into athene/out/live/clips/.

    python -m athene.live
    python -m athene.live --voices FOLDER --res 1

Keys on the page: N next scene, B previous, Space restart the scene, P play
or stop the scene's next voice clip, R and O a rehearsal or online cluster in
the death scene, E the ending, S the strobe and V the straight variant in the
growth scene, 0 the zero turning into a one at the straight variant's end,
H the help line.
"""

import argparse
import json
import random
import subprocess
import time
import webbrowser
from pathlib import Path

from . import analyse, render

HERE = Path(__file__).resolve().parent
VOICES = HERE / "example_audio" / "athene_voice_placeholder"
OUT = render.OUT / "live"
CLIPS_OUT = OUT / "clips"
CLIP_WIDTH = 480
DESIGN = "rehearsal"
PORT = 8766
AUDIO = (".mp3", ".wav", ".flac", ".m4a")


def analysed(voice):
    """The path of the voice clip's analysis, written if missing or older than the clip."""
    path = OUT / f"{voice.stem}.json"
    if not path.is_file() or path.stat().st_mtime < voice.stat().st_mtime:
        analysis = analyse.analyse(voice)
        analyse.write(analysis, path)
        print(analyse.summary(analysis))
    return path


def live_clips(folders):
    """[(video path, group)]: the renderer's picks of each clip folder as
    small videos, cut into CLIPS_OUT where missing."""
    CLIPS_OUT.mkdir(parents=True, exist_ok=True)
    picked = []
    for group, folder in enumerate(folders):
        clips = sorted(folder.glob("*.mp4")) if folder.is_dir() else []
        for source in random.Random(render.SHEET_SEED).sample(clips, min(render.SHEET_CLIPS, len(clips))):
            path = CLIPS_OUT / f"{source.stem}_{CLIP_WIDTH}.mp4"
            if not path.is_file():
                subprocess.run([
                    "ffmpeg", "-y", "-v", "error", "-i", str(source), "-an",
                    "-vf", f"scale={CLIP_WIDTH}:-2", "-c:v", "libx264", "-preset", "veryfast",
                    "-crf", "23", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(path),
                ], check=True)
            picked.append((path, group))
    return picked


def main():
    parser = argparse.ArgumentParser(description="Perform Athene's scenes live from the keyboard.")
    parser.add_argument("--voices", type=Path, default=VOICES, help="folder of the scenes' voice clips")
    parser.add_argument("--clips", type=Path, nargs="+", default=render.CLIP_GROUPS, metavar="FOLDER",
                        help="folders of the cluster clips, one group each (default: rehearsal, then online)")
    parser.add_argument("--res", type=float, help="drawing resolution as a share of 3840 × 2160 (default: fitted to the screen)")
    parser.add_argument("--port", type=int, default=PORT)
    args = parser.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    voices = sorted(p for p in args.voices.iterdir() if p.suffix.lower() in AUDIO)
    listing = []
    # The live page plays no single clip: /clip.json and /clip.audio are not served.
    table = render.routes(render.PAGE, OUT / "none", OUT / "none", [], OUT / "none")
    for k, voice in enumerate(voices):
        table[f"/voices/{k}{voice.suffix.lower()}"] = voice
        table[f"/voices/{k}.json"] = analysed(voice)
        listing.append({"name": voice.stem, "audio": f"/voices/{k}{voice.suffix.lower()}",
                        "analysis": f"/voices/{k}.json"})
    voice_list = OUT / "voices.json"
    voice_list.write_text(json.dumps(listing), encoding="utf-8")
    table["/voices.json"] = voice_list

    clips = live_clips(args.clips)
    clip_list = OUT / "clips.json"
    clip_list.write_text(json.dumps([{"src": f"/clips/{k}.mp4", "group": group}
                                     for k, (_, group) in enumerate(clips)]), encoding="utf-8")
    table["/clips.json"] = clip_list
    # The straight growth variant ends in digits set in Michroma.
    table["/fonts/Michroma-Regular.ttf"] = render.FONTS / "Michroma-Regular.ttf"
    for k, (path, _) in enumerate(clips):
        table[f"/clips/{k}.mp4"] = path

    server = render.serve(table, args.port)
    url = f"http://127.0.0.1:{server.server_address[1]}/?design={DESIGN}&mode=live"
    if args.res:
        url += f"&res={args.res:g}"
    print(f"{len(voices)} voice clips, {len(clips)} cluster clips")
    print(f"live at {url}  (Ctrl+C to stop)")
    webbrowser.open(url)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    server.shutdown()


if __name__ == "__main__":
    main()
