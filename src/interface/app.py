"""HTTP routes of the operator interface.

    /                        operator page
    /sitrep                  live SITREP page: camera feed, live values beneath it
    POST /api/sitrep/start   begin the run (a no-op while one is under way)
    POST /api/sitrep/stop    end it
    POST /api/sitrep/bericht     ask for a report (key R on the page)
    POST /api/sitrep/empfehlung  ask for a recommendation (key E on the page)
    POST /api/sitrep/override    set the recommendation aside (key X on the page);
                                 ?nummer=N only if it is still recommendation N
    POST /api/sitrep/assign      name a body in view as a cast member, or release
                                 it to the automatic naming (name null)
    /api/sitrep/state        the current snapshot, as JSON
    /api/sitrep/events       the snapshot as server-sent events, on every change
    /api/sitrep/video        the camera as an MJPEG stream; ?ratings=1 sets each
                             person's live values beside their box (Prototype 2),
                             with &strip=1 in slots beneath the picture (Prototype 3)
    /api/sources             the cameras and microphones on offer, and the selection
    POST /api/sources        select the camera and sound source of the next run
    /api/sources/ndi         the NDI sources on the network (takes two seconds)

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
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from sitrep import ndi_audio

from .live import LiveSitrep
from .sources import Selection, Sources, available, resolved

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


async def mjpeg(live: LiveSitrep, disconnected: Callable[[], Awaitable[bool]],
                ratings: bool = False, strip: bool = False):
    """The camera as multipart JPEG parts, until the viewer leaves or the run ends.

    Ends when no run holds the camera; the page reopens the feed when a new
    run starts. With `ratings`, the live values are drawn beside each box, or
    with `strip` on a strip beneath the picture (LiveSitrep.overlay).
    """
    while not await disconnected():
        frame = live.latest_frame()
        if frame is None:
            return
        # Marking and encoding both run off the event loop.
        jpeg = await asyncio.to_thread(lambda: _jpeg(live.overlay(frame, ratings, strip)))
        yield (b"--frame\r\nContent-Type: image/jpeg\r\n"
               b"Content-Length: " + str(len(jpeg)).encode() + b"\r\n\r\n"
               + jpeg + b"\r\n")
        await asyncio.sleep(1 / VIDEO_FPS)


class Assignment(BaseModel):
    """A body in view, by the recogniser's track id, and the cast name it is
    given; None releases it to the automatic naming."""

    body: int
    name: str | None = None


def create_app(live: LiveSitrep, selection: Selection | None = None) -> FastAPI:
    """The routes, around one run and the selection of the sources it opens.

    Without `selection`, the selection is kept in memory only.
    """
    selection = selection or Selection()
    app = FastAPI(title="Apollon", docs_url=None, redoc_url=None)
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

    @app.post("/api/sitrep/override")
    def override(nummer: int | None = None):
        uebergangen = live.uebergehen(nummer)
        return JSONResponse({"uebergangen": uebergangen, **live.snapshot()})

    @app.post("/api/sitrep/assign")
    def assign(assignment: Assignment):
        try:
            assigned = live.assign(assignment.body, assignment.name)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return JSONResponse({"assigned": assigned, **live.snapshot()})

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
    async def video(request: Request, ratings: bool = False, strip: bool = False):
        return StreamingResponse(mjpeg(live, request.is_disconnected, ratings, strip),
                                 media_type="multipart/x-mixed-replace; boundary=frame",
                                 headers={"Cache-Control": "no-store"})

    # Device enumeration blocks, so these are plain functions, which FastAPI
    # runs on its thread pool.
    @app.get("/api/sources")
    def sources():
        return JSONResponse({**available(), "selection": resolved(selection.sources)})

    @app.post("/api/sources")
    def choose(chosen: Sources):
        try:
            return JSONResponse({"selection": selection.choose(chosen)})
        except (ValueError, RuntimeError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @app.get("/api/sources/ndi")
    def ndi_sources():
        return JSONResponse({"sources": ndi_audio.sources()})

    return app
