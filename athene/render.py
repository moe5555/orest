"""Athene's renderer: the page drawn frame by frame at 3840 × 2160 and 50 fps.

The page (athene/page) draws a frame from its time and the clip's analysis
(athene/analyse.py). A local server hands it the page, the Seestone typeface
and mark, the analysis and the clip. For a render, Edge, driven headless by
Playwright, draws each frame and returns it as PNG, and ffmpeg joins the
frames with the clip's sound. The drawing surface is 4K on any monitor, no
frame is dropped however long one takes, and a render repeats exactly.

    python -m athene.render CLIP --preview          # in the browser, with sound
    python -m athene.render CLIP --still 1 41.2     # PNG frames at these seconds
    python -m athene.render CLIP                    # the whole clip as video
    python -m athene.render CLIP --span 40 50       # ten seconds of it
    python -m athene.render CLIP --design futurist  # another design (athene/page/designs)

Each run analyses the clip afresh. Everything is written to
athene/out/<clip>/, named with the design. The video is H.264 (4:2:0, BT.709, limited range, which
keeps the black ground at code 16, black on the wall) with the clip's sound
as AAC.
"""

import argparse
import base64
import math
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
DESIGNS = sorted(path.stem for path in (PAGE / "designs").glob("*.js"))
DEFAULT_DESIGN = "planetary"
FONTS = REPO_ROOT / "src" / "sitrep" / "fonts"
MARK = REPO_ROOT / "src" / "interface" / "static" / "seestone.png"
OUT = HERE / "out"

FPS = analyse.FPS
PREVIEW_PORT = 8765

# Set explicitly: on Windows, mimetypes reads the registry, which may call
# JavaScript text/plain.
CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".json": "application/json",
    ".png": "image/png",
    ".ttf": "font/ttf",
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".flac": "audio/flac",
    ".m4a": "audio/mp4",
}


def routes(clip, analysis_path):
    """URL path → file. Files are read on every request, so an edited page
    shows on reload."""
    table = {
        "/": PAGE / "index.html",
        "/athene.js": PAGE / "athene.js",
        "/seestone.png": MARK,
        "/clip.json": analysis_path,
        "/clip.audio": clip,
    }
    for design in (PAGE / "designs").glob("*.js"):
        table[f"/designs/{design.name}"] = design
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
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel="msedge")
        page = browser.new_page()
        page.goto(f"{url}&mode=render")
        page.wait_for_function("window.athene && window.athene.ready")
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
    parser.add_argument("--design", choices=DESIGNS, default=DEFAULT_DESIGN, help=f"the orb's design (default: {DEFAULT_DESIGN})")
    parser.add_argument("--port", type=int, help=f"server port (default: {PREVIEW_PORT} for the preview, any free one otherwise)")
    args = parser.parse_args()

    clip = args.clip.resolve()
    folder = OUT / clip.stem
    analysis = analyse.analyse(clip)
    analysis_path = folder / "analysis.json"
    analyse.write(analysis, analysis_path)
    print(analyse.summary(analysis))

    port = args.port if args.port is not None else (PREVIEW_PORT if args.preview else 0)
    server = serve(routes(clip, analysis_path), port)
    url = f"http://127.0.0.1:{server.server_address[1]}/?design={args.design}"
    name = f"{clip.stem}_{args.design}"

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
