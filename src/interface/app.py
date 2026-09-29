"""HTTP routes of the operator interface.

    /                        operator page
    /sitrep                  live SITREP page: camera feed, live values beneath it
    POST /api/sitrep/start   begin the run (a no-op while one is under way)
    POST /api/sitrep/stop    end it
    POST /api/sitrep/bericht     ask for a report (key R on the page)
    POST /api/sitrep/empfehlung  ask for a recommendation (key E on the page)
    /api/sitrep/state        the current snapshot, as JSON
    /api/sitrep/events       the snapshot as server-sent events, on every change
    /api/sitrep/video        the camera as an MJPEG stream

The camera travels as MJPEG because a browser plays it in a plain <img> with
no script or codec, and on the loopback interface its bandwidth costs
nothing. The report travels as server-sent events: one direction, text, and
reconnecting on its own if the server restarts.
"""

import asyncio
import json
from collections.abc import Awaitable, Callable
from pathlib import Path

import cv2
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .live import LiveSitrep

STATIC = Path(__file__).parent / "static"

# Frame rate of the browser feed. The page only watches; the SITREP samples
# the camera itself, so a lower rate here costs nothing but smoothness.
VIDEO_FPS = 15

# JPEG quality of the browser feed.
VIDEO_QUALITY = 80

# How often the event stream checks the snapshot for a change.
EVENT_POLL_S = 0.25


def _jpeg(frame) -> bytes:
    ok, buffer = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, VIDEO_QUALITY])
    return buffer.tobytes() if ok else b""


async def mjpeg(live: LiveSitrep, disconnected: Callable[[], Awaitable[bool]]):
    """The camera as multipart JPEG parts, until the viewer leaves or the run ends.

    Ends when no run holds the camera; the page reopens the feed when a new
    run starts.
    """
    while not await disconnected():
        frame = live.latest_frame()
        if frame is None:
            return
        # Marking and encoding both run off the event loop.
        jpeg = await asyncio.to_thread(lambda: _jpeg(live.overlay(frame)))
        yield (b"--frame\r\nContent-Type: image/jpeg\r\n"
               b"Content-Length: " + str(len(jpeg)).encode() + b"\r\n\r\n"
               + jpeg + b"\r\n")
        await asyncio.sleep(1 / VIDEO_FPS)


def create_app(live: LiveSitrep) -> FastAPI:
    app = FastAPI(title="Orest", docs_url=None, redoc_url=None)
    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    @app.middleware("http")
    async def revalidate(request: Request, call_next):
        # The page and its script change together. A browser left to its own
        # caching can keep one while fetching the other, and a page whose
        # markup lacks what the script expects renders nothing. no-cache makes
        # every load ask; an unchanged file costs a 304. Streams keep no-store.
        response = await call_next(request)
        response.headers.setdefault("Cache-Control", "no-cache")
        return response

    @app.get("/")
    def operator():
        return FileResponse(STATIC / "operator.html")

    @app.get("/sitrep")
    def sitrep_page():
        return FileResponse(STATIC / "sitrep.html")

    @app.post("/api/sitrep/start")
    def start():
        started = live.start()
        return JSONResponse({"started": started, **live.snapshot()})

    @app.post("/api/sitrep/stop")
    def stop():
        live.stop()
        return JSONResponse(live.snapshot())

    @app.post("/api/sitrep/bericht")
    def bericht():
        angefordert = live.bericht()
        return JSONResponse({"angefordert": angefordert, **live.snapshot()})

    @app.post("/api/sitrep/empfehlung")
    def empfehlung():
        angefordert = live.empfehlen()
        return JSONResponse({"angefordert": angefordert, **live.snapshot()})

    @app.get("/api/sitrep/state")
    def state():
        return JSONResponse(live.snapshot())

    @app.get("/api/sitrep/events")
    async def events(request: Request):
        async def stream():
            seen = None
            while not await request.is_disconnected():
                # Compared whole, not by version: live action readings change
                # every second without being a change of the run's state.
                snapshot = live.snapshot()
                if snapshot != seen:
                    seen = snapshot
                    yield f"data: {json.dumps(snapshot, ensure_ascii=False)}\n\n"
                await asyncio.sleep(EVENT_POLL_S)

        return StreamingResponse(stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-store"})

    @app.get("/api/sitrep/video")
    async def video(request: Request):
        return StreamingResponse(mjpeg(live, request.is_disconnected),
                                 media_type="multipart/x-mixed-replace; boundary=frame",
                                 headers={"Cache-Control": "no-store"})

    return app
