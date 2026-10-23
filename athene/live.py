"""Athene live: the scenes of the play, performed from the keyboard in rehearsals.

Serves the rehearsal design (athene/page/designs/rehearsal.js) in live mode
with the voice clips of the scenes and the clip groups of the clusters, and
opens it in the browser. Each voice clip is analysed once (athene/analyse.py)
and the analysis kept next to the others in athene/out/live/; it is redone
when the clip is newer. Whisper finds the last "von null auf eins" a clip
says, kept and redone the same way; the page blinks the growth scene's zero
into a one on its words. The clusters play the clips of the clip groups
(athene/render.py's CLIP_GROUPS: the death scene rehearsals and the end
videos), mixed by the page, as small looping videos without sound, CLIP_WIDTH
px wide. The strip, where hundreds of clips stand at once, each at most
140 px wide, draws them from frame sheets instead (STRIP_CELL px a frame,
STRIP_FPS frames a second): drawing from an image costs the browser far less
than fetching a video's picture. Both are cut once into athene/out/live/clips/.

Athene is drawn in a 9:1 world, in two views: the 16:9 wall, its middle
section, and the 9:1 strip, all of it. The wall's page conducts the
performance; the strip's page follows it in the same browser (?follow).
Without --obs the wall opens in the default browser, and the strip's address
is printed for a second window. With --obs no browser opens, and the two
addresses are printed for two OBS Browser Sources, each sent out by a
DistroAV Dedicated NDI Output filter. With --rehearsal the world is the 16:9
frame itself, as before the strip: one page, the wall, with the clusters
across it.

    python -m athene.live
    python -m athene.live --obs
    python -m athene.live --rehearsal
    python -m athene.live --voices FOLDER --res 1

Keys on the page: N next scene, B previous, Space restart the scene, P play
or stop the scene's next voice clip, C a cluster in the death scene, E the
ending, S the strobe, L automatic or manual strikes and T (held) the manual
strikes in the growth scene, 0 the zero turning into a one at its end, H the
help line.
"""

import argparse
import functools
import json
import random
import subprocess
import time
import webbrowser
from pathlib import Path

from . import analyse, render

HERE = Path(__file__).resolve().parent
VOICES = HERE / "example_audio" / "athene_voice_2110"
OUT = render.OUT / "live"
CLIPS_OUT = OUT / "clips"
# The width of the end videos, about that of a clip at its largest on the wall.
CLIP_WIDTH = 640
# The strip's frame sheets: frames of STRIP_CELL px at STRIP_FPS, tiled
# STRIP_COLUMNS to a row, as many as four seconds hold.
STRIP_CELL = (128, 72)
STRIP_FPS = 12.5
STRIP_COLUMNS = 10
STRIP_FRAMES = 50
# Clips per group the page loads. A run of the death scene shows each clip
# once at most, so the groups together bound its clusters.
GROUP_CLIPS = 160
DESIGN = "rehearsal"
PORT = 8766
AUDIO = (".mp3", ".wav", ".flac", ".m4a")
# The sentence the growth scene ends on, word by word, in the forms Whisper
# writes it (the numbers also as digits).
ZERO_TO_ONE = (("von",), ("null", "0"), ("auf",), ("eins", "1"))
WHISPER = "large-v3-turbo"
# Seconds within which a word's start moves to the voice's nearest syllable
# onset (analyse.py), so that a blink falls on the word's audible attack.
SNAP = 0.2


def analysed(voice):
    """The path of the voice clip's analysis, written if missing or older than the clip."""
    path = OUT / f"{voice.stem}.json"
    if not path.is_file() or path.stat().st_mtime < voice.stat().st_mtime:
        analysis = analyse.analyse(voice)
        analyse.write(analysis, path)
        print(analyse.summary(analysis))
    return path


@functools.cache
def whisper(device):
    from faster_whisper import WhisperModel

    return WhisperModel(WHISPER, device=device, compute_type="float16" if device == "cuda" else "int8")


def spoken_words(voice):
    """[(word, start in seconds)] of the clip, lower case and without
    punctuation, by Whisper in German; on the GPU, else the CPU. None if
    neither works."""
    for device in ("cuda", "cpu"):
        try:
            segments, _ = whisper(device).transcribe(str(voice), language="de", word_timestamps=True)
            return [(w.word.strip(" .,;:!?\"'").lower(), w.start) for s in segments for w in s.words]
        except RuntimeError as error:
            print(f"Whisper on {device} failed: {error}")
    return None


def zero_to_one(voice, analysis_path):
    """The start times in seconds of the words of the last "von null auf eins"
    the clip says, each moved to the nearest syllable onset within SNAP, or
    None. Kept in OUT and redone when the clip is newer."""
    path = OUT / f"{voice.stem}_zero_to_one.json"
    if path.is_file() and path.stat().st_mtime >= voice.stat().st_mtime:
        return json.loads(path.read_text(encoding="utf-8"))
    words = spoken_words(voice)
    if words is None:
        return None
    times = None
    n = len(ZERO_TO_ONE)
    for k in range(len(words) - n, -1, -1):
        if all(words[k + i][0] in forms for i, forms in enumerate(ZERO_TO_ONE)):
            times = [start for _, start in words[k:k + n]]
            break
    if times:
        onsets = [t for t, _ in json.loads(analysis_path.read_text(encoding="utf-8"))["onsets"]]
        snapped = []
        for t in times:
            near = [o for o in onsets if abs(o - t) <= SNAP and (not snapped or o > snapped[-1])]
            snapped.append(min(near, key=lambda o: abs(o - t)) if near else t)
        times = [round(t, 3) for t in snapped]
        print(f"{voice.stem}: \"von null auf eins\" at {', '.join(f'{t:.2f}' for t in times)} s")
    path.write_text(json.dumps(times), encoding="utf-8")
    return times


def spread_order(clips, seed):
    """The clips in an order that spreads each source video's clips evenly
    over it, so that the clips of a cluster come from as many videos as
    possible. A clip's source is its name up to the last hyphen (the names
    athene/cut_clips.py gives). The k-th of a source's n clips is placed at
    (k + u) / n of the order, u random."""
    rng = random.Random(seed)
    sources = {}
    for clip in rng.sample(clips, len(clips)):
        sources.setdefault(clip.stem.rsplit("-", 1)[0], []).append(clip)
    placed = [((k + rng.random()) / len(own), clip) for own in sources.values() for k, clip in enumerate(own)]
    return [clip for _, clip in sorted(placed, key=lambda p: p[0])]


def strip_sheet(video):
    """The strip's frame sheet of a clip's video and its frame count, cut
    into CLIPS_OUT where missing."""
    width, height = STRIP_CELL
    path = CLIPS_OUT / f"{video.stem}_sheet{width}.jpg"
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(video)],
        capture_output=True, text=True, check=True)
    frames = min(STRIP_FRAMES, int(float(probe.stdout) * STRIP_FPS))
    if not path.is_file():
        rows = -(-STRIP_FRAMES // STRIP_COLUMNS)
        subprocess.run([
            "ffmpeg", "-y", "-v", "error", "-i", str(video),
            "-vf", f"fps={STRIP_FPS},scale={width}:{height},tile={STRIP_COLUMNS}x{rows}",
            "-frames:v", "1", "-q:v", "4", str(path),
        ], check=True)
    return path, frames


def live_clips(folders):
    """[(video path, sheet path, frames in the sheet, group)]: up to
    GROUP_CLIPS clips of each clip folder, in the order the clusters take
    them (spread_order), as videos CLIP_WIDTH px wide and the strip's frame
    sheets, cut into CLIPS_OUT where missing."""
    CLIPS_OUT.mkdir(parents=True, exist_ok=True)
    picked = []
    for group, folder in enumerate(folders):
        clips = sorted(folder.glob("*.mp4")) if folder.is_dir() else []
        for source in spread_order(clips, render.SHEET_SEED)[:GROUP_CLIPS]:
            path = CLIPS_OUT / f"{source.stem}_{CLIP_WIDTH}.mp4"
            if not path.is_file():
                subprocess.run([
                    "ffmpeg", "-y", "-v", "error", "-i", str(source), "-an",
                    "-vf", f"scale={CLIP_WIDTH}:-2", "-c:v", "libx264", "-preset", "veryfast",
                    "-crf", "23", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(path),
                ], check=True)
            picked.append((path, *strip_sheet(path), group))
    return picked


def main():
    parser = argparse.ArgumentParser(description="Perform Athene's scenes live from the keyboard.")
    parser.add_argument("--voices", type=Path, default=VOICES, help="folder of the scenes' voice clips")
    parser.add_argument("--clips", type=Path, nargs="+", default=render.CLIP_GROUPS, metavar="FOLDER",
                        help="folders of the cluster clips, one group each (default: rehearsal, then online)")
    parser.add_argument("--res", type=float, help="drawing resolution as a share of the view's full size (default: fitted to the screen)")
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument("--obs", action="store_true",
                        help="open no browser; print the addresses of the two OBS Browser Sources")
    parser.add_argument("--rehearsal", action="store_true",
                        help="the 16:9 world as before the strip: one page, the wall, no strip")
    args = parser.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    voices = sorted(p for p in args.voices.iterdir() if p.suffix.lower() in AUDIO)
    listing = []
    # The live page plays no single clip: /clip.json and /clip.audio are not served.
    table = render.routes(render.PAGE, OUT / "none", OUT / "none", [], OUT / "none")
    for k, voice in enumerate(voices):
        analysis = analysed(voice)
        table[f"/voices/{k}{voice.suffix.lower()}"] = voice
        table[f"/voices/{k}.json"] = analysis
        listing.append({"name": voice.stem, "audio": f"/voices/{k}{voice.suffix.lower()}",
                        "analysis": f"/voices/{k}.json", "zeroToOne": zero_to_one(voice, analysis)})
    voice_list = OUT / "voices.json"
    voice_list.write_text(json.dumps(listing), encoding="utf-8")
    table["/voices.json"] = voice_list

    clips = live_clips(args.clips)
    clip_list = OUT / "clips.json"
    clip_list.write_text(json.dumps([
        {"src": f"/clips/{k}.mp4", "group": group,
         "sheet": {"src": f"/clips/{k}_sheet.jpg", "frames": frames, "fps": STRIP_FPS,
                   "cell": STRIP_CELL, "columns": STRIP_COLUMNS}}
        for k, (_, _, frames, group) in enumerate(clips)]), encoding="utf-8")
    table["/clips.json"] = clip_list
    for k, (path, sheet, _, _) in enumerate(clips):
        table[f"/clips/{k}.mp4"] = path
        table[f"/clips/{k}_sheet.jpg"] = sheet

    server = render.serve(table, args.port)
    url = f"http://127.0.0.1:{server.server_address[1]}/?design={DESIGN}&mode=live"
    if args.res:
        url += f"&res={args.res:g}"
    if args.rehearsal:
        url += "&rehearsal"
    # The wall conducts; in OBS its help line would go out to the wall, so it
    # starts hidden there (H shows it).
    wall = f"{url}&view=wall" + ("&hint=0" if args.obs else "")
    strip = f"{url}&view=strip&follow"
    print(f"{len(voices)} voice clips, {len(clips)} cluster clips")
    if args.rehearsal:
        print(f"wall  (16:9, 3840 x 2160, the whole world): {wall}")
    else:
        print(f"wall  (16:9, 3840 x 2160, conducts): {wall}")
        print(f"strip (9:1, 3840 x 427, follows):    {strip}")
    print("Ctrl+C to stop")
    if not args.obs:
        webbrowser.open(wall)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    server.shutdown()


if __name__ == "__main__":
    main()
