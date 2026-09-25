"""The operator interface: its pages, and the run it starts and stops.

A stand-in session replaces the camera, the models and the microphone, so the
run's life cycle is exercised as the page drives it without any hardware.
"""

import asyncio
import threading
import time

import numpy as np
import pytest
from fastapi.testclient import TestClient

from interface import app as app_module
from interface import live as live_module
from interface.app import create_app
from interface.live import LiveSitrep
from sitrep import devices, report, session


def wait_for(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


class FakeStream:
    def __init__(self):
        self.device = devices.VideoDevice(0, "Fake Camera")

    def latest(self):
        return np.zeros((36, 64, 3), dtype=np.uint8)


class FakeTracker:
    cast = None


class FakeSession:
    """Yields the given reports, one per release of its gate, until closed."""

    def __init__(self, documents):
        self.options = session.Options(model="gemma4:26b", window=15.0)
        self.audio = devices.AudioDevice(0, "Fake Mic", "MME", 0, 1, 16000.0)
        self.stream = FakeStream()
        self.tracker = FakeTracker()
        self.gate = threading.Semaphore(0)
        self.closed = threading.Event()
        self._documents = documents

    def reports(self):
        for document in self._documents:
            while not self.gate.acquire(timeout=0.05):
                if self.closed.is_set():
                    return
            yield document
        self.closed.wait()

    def close(self):
        self.closed.set()


@pytest.fixture
def run(sitrep):
    return FakeSession([sitrep, sitrep])


@pytest.fixture
def live(run):
    controller = LiveSitrep(lambda: run)
    yield controller
    controller.stop()


@pytest.fixture
def client(live):
    return TestClient(create_app(live))


def test_the_operator_page_opens_the_live_sitrep_in_a_new_tab(client):
    page = client.get("/").text
    assert 'href="/sitrep"' in page
    assert 'target="_blank"' in page
    assert "Start live SITREP" in page


def test_the_sitrep_page_is_served_with_its_script(client):
    response = client.get("/sitrep")
    assert response.status_code == 200
    assert "/static/sitrep.js" in response.text
    assert client.get("/static/sitrep.js").status_code == 200


def test_a_run_starts_and_each_report_reaches_the_snapshot(client, live, run):
    assert client.post("/api/sitrep/start").json()["started"]
    assert wait_for(lambda: live.status == live_module.RUNNING)
    assert live.snapshot()["quelle"]["kamera"] == "Fake Camera"
    assert live.snapshot()["report"] is None

    run.gate.release()
    assert wait_for(lambda: live.report is not None)
    assert client.get("/api/sitrep/state").json()["report"]["nummer"] == 1

    run.gate.release()
    assert wait_for(lambda: live.report["nummer"] == 2)


def test_starting_twice_does_not_open_a_second_run(client, live):
    assert client.post("/api/sitrep/start").json()["started"]
    assert not client.post("/api/sitrep/start").json()["started"]


def test_every_change_raises_the_version(live, run):
    before = live.version
    live.start()
    assert wait_for(lambda: live.status == live_module.RUNNING)
    running = live.version
    run.gate.release()
    assert wait_for(lambda: live.report is not None)
    assert before < running < live.version


def test_stopping_releases_the_session_and_keeps_the_last_report(client, live, run):
    client.post("/api/sitrep/start")
    assert wait_for(lambda: live.status == live_module.RUNNING)
    run.gate.release()
    assert wait_for(lambda: live.report is not None)

    client.post("/api/sitrep/stop")

    assert run.closed.is_set()
    assert wait_for(lambda: live.status == live_module.IDLE)
    assert live.latest_frame() is None
    assert live.snapshot()["report"]["nummer"] == 1


def test_a_session_that_cannot_open_shows_its_error(sitrep):
    def refuses():
        raise ValueError("No video device matches 'Webcam'.")

    controller = LiveSitrep(refuses)
    controller.start()
    assert wait_for(lambda: controller.status == live_module.ERROR)
    assert "Webcam" in controller.snapshot()["error"]
    # An error does not block the next attempt.
    assert controller.start()


def test_a_run_can_start_again_after_it_stopped(sitrep):
    sessions = []

    def open_session():
        sessions.append(FakeSession([sitrep]))
        return sessions[-1]

    controller = LiveSitrep(open_session)
    controller.start()
    assert wait_for(lambda: controller.status == live_module.RUNNING)
    controller.stop()
    assert wait_for(lambda: controller.status == live_module.IDLE)
    assert controller.start()
    assert wait_for(lambda: controller.status == live_module.RUNNING)
    assert len(sessions) == 2
    controller.stop()


def test_the_video_feed_ends_when_no_run_holds_the_camera(client):
    response = client.get("/api/sitrep/video")
    assert response.status_code == 200
    assert response.content == b""


def test_the_video_feed_sends_jpeg_frames_until_the_run_stops(live, run):
    """Stopping the run is what ends a feed; the page reopens it on the next.

    Driven directly rather than through the test client, which buffers a whole
    response and so never returns from an open-ended stream.
    """
    live.start()
    assert wait_for(lambda: live.status == live_module.RUNNING)

    async def still_connected():
        return False

    async def watch():
        parts = []
        async for part in app_module.mjpeg(live, still_connected):
            parts.append(part)
            if len(parts) == 2:
                live.stop()
        return parts

    parts = asyncio.run(asyncio.wait_for(watch(), timeout=5))
    assert 2 <= len(parts) <= 3
    assert all(part.startswith(b"--frame\r\nContent-Type: image/jpeg") for part in parts)
    assert b"\xff\xd8" in parts[0]           # JPEG start-of-image marker


def test_the_video_feed_ends_when_the_viewer_leaves(live, run):
    live.start()
    assert wait_for(lambda: live.status == live_module.RUNNING)

    async def gone():
        return True

    async def watch():
        return [part async for part in app_module.mjpeg(live, gone)]

    assert asyncio.run(asyncio.wait_for(watch(), timeout=5)) == []


def test_the_page_payload_marks_guessed_names_only(sitrep):
    guessed = report.Person(name=report.UNBEKANNT, beschreibung="", kollaborativ=0,
                            relevanz=0, verantwortungsvoll=0, menschlich=0, gefahr=0)
    document = sitrep.model_copy(update={"bericht": sitrep.bericht.model_copy(update={
        "personen": [*sitrep.bericht.personen, guessed]})})

    rendered = live_module.payload(document, 3)

    assert rendered["nummer"] == 3
    assert rendered["schwelle"] == report.SCHWELLE
    assert [person["vermutet"] for person in rendered["bericht"]["personen"]] == [
        False, True, False]
    assert "einschreiten" in rendered["bericht"]
