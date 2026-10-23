"""Athene's renderer: the page drawn frame by frame at 3840 × 2160 and 50 fps.

The page (athene/page) draws a frame from its time and the clip's analysis
(athene/analyse.py). A local server hands it the page, the analysis and the
clip. For a render, Edge, driven headless by
Playwright, draws each frame and returns it as PNG, and ffmpeg joins the
frames with the clip's sound. The drawing surface is 4K on any monitor, no
frame is dropped however long one takes, and a render repeats exactly.

    python -m athene.render CLIP --preview          # in the browser, with sound
    python -m athene.render CLIP --still 1 41.2     # PNG frames at these seconds
    python -m athene.render CLIP                    # the whole clip as video
    python -m athene.render CLIP --span 40 50       # ten seconds of it
    python -m athene.render CLIP --design axes      # another design (athene/page/designs)
    python -m athene.render CLIP --archive --design futurist   # an archived design
    python -m athene.render CLIP --clips A B        # cluster clips from other folders

Designs that show clusters of clips (axes2 to axes4) take them as frame
sheets, in groups: by default 4-second clips of the death scene rehearsals
(data/clips/athene_deathscene), then of the play's end videos
(data/clips/athene_endvideos), both cut by athene/cut_clips.py. From each group
SHEET_CLIPS clips are picked and each is cut to the design's sheet shape
(SHEET_SHAPES) from the middle of the picture and tiled frame by frame into
one JPEG. The sheets are kept in athene/out/_sheets/ and reused; drawing a
clip's frame from a sheet keeps every render of a frame identical.

The Seestone-branded prototypes are kept in athene/archive with the page
they were drawn on; --archive serves that page, with the Seestone typeface
and mark, instead of the current one.

Each run analyses the clip afresh. Everything is written to
athene/out/<clip>/ (athene/archive/out/<clip>/ with --archive), named with
the design. The video is H.264 (4:2:0, BT.709, limited range, which
keeps the black ground at code 16, black on the wall) with the clip's sound
as AAC.
"""

import argparse
import base64
import json
import math
import random
import subprocess
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import analyse

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
PAGE = HERE / "page"
ARCHIVE_PAGE = HERE / "archive" / "page"
DEFAULT_DESIGN = {PAGE: "axes4", ARCHIVE_PAGE: "liquid"}
FONTS = REPO_ROOT / "src" / "sitrep" / "fonts"
MARK = REPO_ROOT / "src" / "interface" / "static" / "seestone.png"
OUT = HERE / "out"
ARCHIVE_OUT = HERE / "archive" / "out"
SHEETS = OUT / "_sheets"
CLIP_GROUPS = [
    REPO_ROOT / "data" / "clips" / "athene_deathscene",
    REPO_ROOT / "data" / "clips" / "athene_endvideos",
]

# Frame sheets of the cluster clips: up to SHEET_CLIPS clips per group,
# picked with SHEET_SEED, at SHEET_FPS, SHEET_COLUMNS frames to a row. Ten by
# ten holds a four-second clip. A frame is SHEET_SHAPES[design] px, or
# SHEET_SHAPE for designs not listed.
SHEET_CLIPS = 48
SHEET_SEED = 3
SHEET_FPS = 25
SHEET_SHAPE = (240, 240)
SHEET_SHAPES = {"axes4": (192, 108)}
SHEET_COLUMNS = 10
SHEET_ROWS = 10

FPS = analyse.FPS
PREVIEW_PORT = 8765

# Set explicitly: on Windows, mimetypes reads the registry, which may call
# JavaScript text/plain.
CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".json": "application/json",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".ttf": "font/ttf",
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".flac": "audio/flac",
    ".m4a": "audio/mp4",
    ".mp4": "video/mp4",
}


def frame_sheets(folders, shape):
    """[(sheet path, frame count, group)] for up to SHEET_CLIPS clips of each
    folder, cutting the sheets not yet in SHEETS. A folder without clips
    adds none."""
    width, height = shape
    SHEETS.mkdir(parents=True, exist_ok=True)
    sheets = []
    for group, folder in enumerate(folders):
        clips = sorted(folder.glob("*.mp4")) if folder.is_dir() else []
        picked = random.Random(SHEET_SEED).sample(clips, min(SHEET_CLIPS, len(clips)))
        for source in picked:
            path = SHEETS / f"{source.stem}_{width}x{height}.jpg"
            probe = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(source)],
                capture_output=True, text=True, check=True)
            frames = min(SHEET_COLUMNS * SHEET_ROWS, math.floor(float(probe.stdout) * SHEET_FPS))
            if not path.is_file():
                # The largest part of the picture in the frame's shape, from its middle.
                crop = f"crop='min(iw,ih*{width}/{height})':'min(ih,iw*{height}/{width})'"
                subprocess.run([
                    "ffmpeg", "-y", "-v", "error", "-i", str(source),
                    "-vf", f"fps={SHEET_FPS},{crop},scale={width}:{height},"
                           f"tile={SHEET_COLUMNS}x{SHEET_ROWS}",
                    "-frames:v", "1", "-q:v", "3", str(path),
                ], check=True)
            sheets.append((path, frames, group))
    return sheets


def write_sheet_list(sheets, shape, path):
    """The list the page reads from /clips.json."""
    width, height = shape
    listing = [{"src": f"/clips/{k}.jpg", "frames": frames, "fps": SHEET_FPS, "group": group,
                "width": width, "height": height, "columns": SHEET_COLUMNS}
               for k, (_, frames, group) in enumerate(sheets)]
    path.write_text(json.dumps(listing), encoding="utf-8")


def designs(page):
    return sorted(path.stem for path in (page / "designs").glob("*.js"))


def routes(page, clip, analysis_path, sheets, sheet_list_path):
    """URL path → file. Files are read on every request, so an edited page
    shows on reload."""
    table = {
        "/": page / "index.html",
        "/athene.js": page / "athene.js",
        "/clip.json": analysis_path,
        "/clip.audio": clip,
        "/clips.json": sheet_list_path,
    }
    for k, (sheet, _, _) in enumerate(sheets):
        table[f"/clips/{k}.jpg"] = sheet
    for design in (page / "designs").glob("*.js"):
        table[f"/designs/{design.name}"] = design
    if page == ARCHIVE_PAGE:
        table["/seestone.png"] = MARK
        for font in FONTS.glob("*.ttf"):
            table[f"/fonts/{font.name}"] = font
    return table


def serve(table, port):
    """Serve the table on 127.0.0.1 in a background thread; returns the server."""

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            path = table.get(self.path.split("?", 1)[0])
            if path is None or not path.is_file():
                self.send_error(404)
                return
            body = path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", CONTENT_TYPES.get(path.suffix.lower(), "application/octet-stream"))
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def frames(url, indices):
    """PNG bytes of each frame index, drawn by headless Edge from the page at url."""
    from playwright.sync_api import TimeoutError, sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel="msedge")
        page = browser.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(f"{url}&mode=render")
        try:
            page.wait_for_function("window.athene && window.athene.ready")
        except TimeoutError:
            sys.exit("the page did not get ready" + "".join(f"\n{e}" for e in errors))
        for i in indices:
            data_url = page.evaluate("i => window.athene.frame(i)", i)
            yield base64.b64decode(data_url.split(",", 1)[1])
        browser.close()


def write_stills(url, seconds, folder, name):
    for s, png in zip(seconds, frames(url, [round(s * FPS) for s in seconds])):
        path = folder / f"{name}_{s:06.2f}s.png"
        path.write_bytes(png)
        print(f"written {path}")


def write_video(url, clip, first, last, path):
    """Frames first..last-1 piped into ffmpeg, joined with that stretch of sound."""
    command = [
        "ffmpeg", "-y", "-v", "error",
        "-f", "image2pipe", "-framerate", str(FPS), "-c:v", "png", "-i", "-",
        "-ss", f"{first / FPS:.3f}", "-t", f"{(last - first) / FPS:.3f}", "-i", str(clip),
        "-map", "0:v", "-map", "1:a",
        "-vf", "scale=out_color_matrix=bt709:out_range=tv,format=yuv420p",
        "-c:v", "libx264", "-preset", "slow", "-crf", "12", "-profile:v", "high",
        "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", "-color_range", "tv",
        "-c:a", "aac", "-b:a", "320k",
        "-movflags", "+faststart", str(path),
    ]
    encoder = subprocess.Popen(command, stdin=subprocess.PIPE)
    total = last - first
    began = time.monotonic()
    for n, png in enumerate(frames(url, range(first, last)), 1):
        encoder.stdin.write(png)
        if n % 50 == 0 or n == total:
            spent = time.monotonic() - began
            print(f"\r{n}/{total} frames, {n / spent:.1f} fps, "
                  f"{(total - n) * spent / n / 60:.1f} min left", end="", flush=True)
    print()
    encoder.stdin.close()
    if encoder.wait() != 0:
        sys.exit(f"ffmpeg failed with code {encoder.returncode}")
    print(f"written {path}")


def main():
    parser = argparse.ArgumentParser(description="Render Athene speaking a clip.")
    parser.add_argument("clip", type=Path)
    parser.add_argument("--preview", action="store_true", help="open the page in the browser, with sound")
    parser.add_argument("--still", type=float, nargs="+", metavar="SECONDS", help="write PNG frames at these times")
    parser.add_argument("--span", type=float, nargs=2, metavar=("START", "END"), help="render only these seconds")
    parser.add_argument("--design", help=f"the design (default: {DEFAULT_DESIGN[PAGE]}, "
                                          f"or {DEFAULT_DESIGN[ARCHIVE_PAGE]} with --archive)")
    parser.add_argument("--archive", action="store_true", help="draw an archived design (athene/archive)")
    parser.add_argument("--clips", type=Path, nargs="+", default=CLIP_GROUPS, metavar="FOLDER",
                        help="folders of the cluster clips, one group each (default: athene_deathscene, then athene_endvideos)")
    parser.add_argument("--port", type=int, help=f"server port (default: {PREVIEW_PORT} for the preview, any free one otherwise)")
    args = parser.parse_args()
    page = ARCHIVE_PAGE if args.archive else PAGE
    design = args.design or DEFAULT_DESIGN[page]
    if design not in designs(page):
        parser.error(f"--design must be one of {', '.join(designs(page))}")

    clip = args.clip.resolve()
    folder = (ARCHIVE_OUT if args.archive else OUT) / clip.stem
    analysis = analyse.analyse(clip)
    analysis_path = folder / "analysis.json"
    analyse.write(analysis, analysis_path)
    print(analyse.summary(analysis))

    shape = SHEET_SHAPES.get(design, SHEET_SHAPE)
    sheets = [] if args.archive else frame_sheets(args.clips, shape)
    sheet_list_path = folder / "clips.json"
    write_sheet_list(sheets, shape, sheet_list_path)

    port = args.port if args.port is not None else (PREVIEW_PORT if args.preview else 0)
    server = serve(routes(page, clip, analysis_path, sheets, sheet_list_path), port)
    url = f"http://127.0.0.1:{server.server_address[1]}/?design={design}"
    name = f"{clip.stem}_{design}"

    if args.preview:
        print(f"preview at {url}  (Ctrl+C to stop)")
        webbrowser.open(url)
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
    elif args.still:
        write_stills(url, args.still, folder, name)
    else:
        first, last = 0, analysis["frames"]
        video = f"{name}.mp4"
        if args.span:
            first = max(0, round(args.span[0] * FPS))
            last = min(last, math.ceil(args.span[1] * FPS))
            video = f"{name}_{args.span[0]:g}-{args.span[1]:g}s.mp4"
        write_video(url, clip, first, last, folder / video)
    server.shutdown()


if __name__ == "__main__":
    main()
