"""The operator interface: its pages, and the run it starts and stops.

A stand-in session replaces the camera, the models and the microphone, so the
run's life cycle is exercised as the page drives it without any hardware.
"""

import asyncio
import threading
import time
from datetime import datetime

import numpy as np
import pytest
from fastapi.testclient import TestClient

from interface import app as app_module
from interface import live as live_module
from interface.app import create_app
from interface.live import LiveSitrep
from sitrep import actions, devices, lage, report, session


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
    """Yields the given events, one per release of its gate, until closed.

    A report is made when asked for: `bericht()` queues the next of the given
    documents as a new report.
    """

    def __init__(self, documents):
        self.options = session.Options(model="gemma4:26b", window=15.0)
        self.audio = devices.AudioDevice(0, "Fake Mic", "MME", 0, 1, 16000.0)
        self.stream = FakeStream()
        self.tracker = FakeTracker()
        self.actions = None
        self.chronik = None
        self.meter = None
        self.laeuft = {"bericht": False, "empfehlung": False}
        self.gate = threading.Semaphore(0)
        self.closed = threading.Event()
        self._documents = list(documents)
        self._pending = []
        self.asked = []

    def bericht(self):
        self.asked.append("bericht")
        nummer = len(self.asked)
        self._pending.append(session.NeuerBericht(self._documents[(nummer - 1) % len(self._documents)],
                                                  nummer))
        self.gate.release()
        return True

    def empfehlung(self):
        self.asked.append("empfehlung")
        return True

    def emit(self, event):
        self._pending.append(event)
        self.gate.release()

    def events(self):
        while True:
            while not self.gate.acquire(timeout=0.05):
                if self.closed.is_set():
                    return
            yield self._pending.pop(0)

    def overlay(self, frame):
        return frame

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


def test_the_sitrep_page_offers_prototype_1_as_a_tab(client):
    page = client.get("/sitrep").text
    assert 'data-ansicht="uebersicht"' in page and 'data-ansicht="p1"' in page
    assert "/static/prototyp1.js" in page
    assert client.get("/static/prototyp1.js").status_code == 200


def test_the_people_in_view_are_named_left_to_right():
    visible = [(np.array([400, 10, 500, 300]), "Klara"),
               (np.array([20, 40, 120, 310]), "Körper 3")]
    assert live_module.im_bild(visible) == ["Körper 3", "Klara"]
    assert live_module.im_bild([]) == []


def test_nobody_is_in_view_without_action_recognition(live, run):
    live.start()
    assert wait_for(lambda: live.status == live_module.RUNNING)
    assert live.snapshot()["im_bild"] == []


def test_a_report_is_made_when_asked_for_and_reaches_the_snapshot(client, live, run):
    assert client.post("/api/sitrep/start").json()["started"]
    assert wait_for(lambda: live.status == live_module.RUNNING)
    assert live.snapshot()["quelle"]["kamera"] == "Fake Camera"
    assert live.snapshot()["report"] is None

    assert client.post("/api/sitrep/bericht").json()["angefordert"]
    assert wait_for(lambda: live.report is not None)
    assert client.get("/api/sitrep/state").json()["report"]["nummer"] == 1

    client.post("/api/sitrep/bericht")
    assert wait_for(lambda: live.report["nummer"] == 2)
    assert run.asked == ["bericht", "bericht"]


def test_a_recommendation_is_asked_for_through_the_page(client, live, run):
    client.post("/api/sitrep/start")
    assert wait_for(lambda: live.status == live_module.RUNNING)
    assert client.post("/api/sitrep/empfehlung").json()["angefordert"]
    assert run.asked == ["empfehlung"]


def test_nothing_is_asked_for_while_no_run_is_live(client):
    assert not client.post("/api/sitrep/bericht").json()["angefordert"]
    assert not client.post("/api/sitrep/empfehlung").json()["angefordert"]


def test_lines_live_values_and_recommendations_reach_the_snapshot(live, run):
    live.start()
    assert wait_for(lambda: live.status == live_module.RUNNING)
    now = datetime(2026, 9, 29, 20, 0, 5)
    line = report.Aeusserung(name="Klara", text="Raus hier!", beginn=now, ende=now, risiko=4,
                             menschlichkeit=0, lautstaerke="geschrien")
    run.emit(session.Zeilen([line]))
    run.emit(session.Werte(lage.Stand(now, {"Klara": {
        "risiko": lage.Wert(4, 4.0, "„Raus hier!“: Drohung.", now),
        "menschlichkeit": lage.Wert(0, 0.0)}}, lage.Alarm(True, 4, "Klara", "„Raus hier!“"))))
    run.emit(session.NeueEmpfehlung(report.Empfehlung(
        zeit=now, anlass="Alarm", latenz_s=1.1, urteil=report.Urteil(
            lage="Drohung.", empfehlung="Probe unterbrechen.",
            szene=report.Szene(relevanz=8, eskalation=8, gefahr=7))), 1))
    assert wait_for(lambda: live.empfehlung is not None)

    snapshot = live.snapshot()
    assert snapshot["zeilen"][0]["text"] == "Raus hier!"
    assert snapshot["zeilen"][0]["lautstaerke"] == "geschrien"
    assert snapshot["werte"]["personen"] == [{"name": "Klara", "risiko": 4, "menschlichkeit": 0,
                                              "anlass_risiko": "„Raus hier!“: Drohung.",
                                              "anlass_menschlichkeit": ""}]
    assert snapshot["werte"]["alarm"]["aktiv"]
    assert snapshot["empfehlung"]["urteil"]["einschreiten"]
    assert snapshot["empfehlung"]["nummer"] == 1


def _empfehlung(nummer):
    now = datetime(2026, 9, 29, 20, 0, 5)
    return session.NeueEmpfehlung(report.Empfehlung(
        zeit=now, anlass="Alarm", latenz_s=1.1, urteil=report.Urteil(
            lage="Drohung.", empfehlung="Probe unterbrechen.",
            szene=report.Szene(relevanz=8, eskalation=8, gefahr=7))), nummer)


def test_an_override_sets_the_recommendation_aside(client, live, run):
    client.post("/api/sitrep/start")
    assert wait_for(lambda: live.status == live_module.RUNNING)
    run.emit(_empfehlung(1))
    assert wait_for(lambda: live.empfehlung is not None)
    version = live.version

    answer = client.post("/api/sitrep/override", params={"nummer": 1}).json()
    assert answer["uebergangen"]
    assert answer["empfehlung"] is None
    assert live.version > version
    assert not client.post("/api/sitrep/override").json()["uebergangen"]


def test_an_override_keeps_a_recommendation_that_arrived_meanwhile(client, live, run):
    client.post("/api/sitrep/start")
    assert wait_for(lambda: live.status == live_module.RUNNING)
    run.emit(_empfehlung(1))
    run.emit(_empfehlung(2))
    assert wait_for(lambda: live.empfehlung is not None and live.empfehlung["nummer"] == 2)

    answer = client.post("/api/sitrep/override", params={"nummer": 1}).json()
    assert not answer["uebergangen"]
    assert answer["empfehlung"]["nummer"] == 2


def test_prototype_1_offers_the_override_on_x(client):
    page = client.get("/sitrep").text
    assert 'id="p1-override"' in page and "<kbd>X</kbd> Override" in page
    script = client.get("/static/prototyp1.js").text
    assert "/api/sitrep/override?nummer=" in script and 'key === "x"' in script


def test_starting_twice_does_not_open_a_second_run(client, live):
    assert client.post("/api/sitrep/start").json()["started"]
    assert not client.post("/api/sitrep/start").json()["started"]


def test_every_change_raises_the_version(live, run):
    before = live.version
    live.start()
    assert wait_for(lambda: live.status == live_module.RUNNING)
    running = live.version
    run.bericht()
    assert wait_for(lambda: live.report is not None)
    assert before < running < live.version


def test_stopping_releases_the_session_and_keeps_the_last_report(client, live, run):
    client.post("/api/sitrep/start")
    assert wait_for(lambda: live.status == live_module.RUNNING)
    client.post("/api/sitrep/bericht")
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
    guessed = report.Person(name=report.UNBEKANNT, beschreibung="", auffaelligkeit=0)
    document = sitrep.model_copy(update={"bericht": sitrep.bericht.model_copy(update={
        "personen": [*sitrep.bericht.personen, guessed]})})

    rendered = live_module.payload(document, 3)

    assert rendered["nummer"] == 3
    assert rendered["schwelle"] == report.SCHWELLE
    assert [person["vermutet"] for person in rendered["bericht"]["personen"]] == [
        False, True, False]
    assert "einschreiten" in rendered["bericht"]


def test_the_page_payload_joins_measured_and_generated_ratings(sitrep):
    klara, jakob = live_module.payload(sitrep, 1)["bericht"]["personen"]
    assert (klara["risiko"], klara["menschlichkeit"], klara["auffaelligkeit"]) == (0, 4, 3)
    assert klara["anlass"] == ["menschlichkeit: hugging other person 0.81"]
    assert (jakob["risiko"], jakob["menschlichkeit"], jakob["auffaelligkeit"]) == (None, None, 4)
    assert jakob["anlass"] == []


class FakeRatings:
    """An action recogniser's live state, as sitrep.actions.ActionRatings keeps it."""

    error = None
    evaluations = 7
    latest = [
        actions.Recognised(("Klara",), "reading", 0.41, np.array([0.2, 0.1])),
        actions.Recognised(("Klara", "Körper 9"), "pushing other person", 0.8,
                           np.array([2.4, -1.6])),
    ]


def test_the_live_action_readings_show_the_strongest_evidence_first():
    shown = live_module.aktionen(FakeRatings())
    assert shown["aktiv"] and shown["stand"] == 7 and shown["fehler"] is None
    first = shown["lesungen"][0]
    assert first == {"wer": ["Klara", "Körper 9"], "handlung": "pushing other person",
                     "wahrscheinlichkeit": 0.8, "risiko": 2.4, "menschlichkeit": -1.6}


def test_a_run_without_action_recognition_says_so(live, run):
    live.start()
    assert wait_for(lambda: live.status == live_module.RUNNING)
    assert live.snapshot()["aktionen"] == {"aktiv": False}
    assert live.snapshot()["quelle"]["aktionen"] is False


def test_a_stopped_recogniser_reports_its_error():
    class Failed(FakeRatings):
        error = RuntimeError("CUDA out of memory")

    assert "CUDA out of memory" in live_module.aktionen(Failed())["fehler"]


def test_the_page_and_its_script_are_revalidated_on_every_load(client):
    """A cached page paired with a newer script renders nothing."""
    for path in ("/", "/sitrep", "/static/sitrep.js", "/static/prototyp1.js", "/static/style.css"):
        assert client.get(path).headers["cache-control"] == "no-cache"


def test_a_rated_line_takes_the_place_of_the_line_as_transcribed(live, run):
    live.start()
    assert wait_for(lambda: live.status == live_module.RUNNING)
    now = datetime(2026, 9, 29, 20, 0, 5)
    line = report.Aeusserung(name=None, text="Raus hier!", beginn=now, ende=now)
    run.emit(session.Zeilen([line], bewertet=False))
    run.emit(session.Zeilen([line.model_copy(update={"risiko": 3, "menschlichkeit": -2})]))
    assert wait_for(lambda: live.zeilen and live.zeilen[-1]["bewertet"])
    [shown] = live.snapshot()["zeilen"]
    assert (shown["risiko"], shown["bewertet"]) == (3, True)
