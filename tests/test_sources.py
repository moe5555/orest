"""Choosing the camera and sound source on the operator page.

DirectShow and PortAudio are replaced by fixed device lists, so what the page
offers and what a run would open are checked without hardware.
"""

import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from interface.app import create_app
from interface.live import LiveSitrep
from interface.sources import Selection, Sources
from sitrep import devices, ndi_audio, session

CAMERAS = ["NDI Webcam Video 1", "SandbergCapture", "vMix Video External 3",
           "vMix Video External 3 YV12", "OBS Virtual Camera"]

HOSTAPIS = [
    {"name": "MME", "default_input_device": 0},
    {"name": "Windows WASAPI", "default_input_device": 3},
]

MICROPHONES = [
    devices.AudioDevice(0, "Microsoft Sound Mapper - Input", "MME", 0, 2, 44100.0),
    devices.AudioDevice(1, "Digitale Audioschnittstelle (US", "MME", 0, 2, 44100.0),
    devices.AudioDevice(2, "Webcam 4 (NDI Webcam Audio)", "Windows WASAPI", 1, 2, 48000.0),
    devices.AudioDevice(3, "Digitale Audioschnittstelle (USB3.0 Audio)", "Windows WASAPI", 1, 2, 48000.0),
]


@pytest.fixture(autouse=True)
def machine(monkeypatch):
    monkeypatch.setattr(devices, "list_video_devices",
                        lambda: [devices.VideoDevice(i, name) for i, name in enumerate(CAMERAS)])
    monkeypatch.setattr(devices, "list_audio_devices", lambda: list(MICROPHONES))
    monkeypatch.setattr(devices.sd, "query_hostapis", lambda: HOSTAPIS)
    monkeypatch.setattr(devices.sd, "default", SimpleNamespace(device=[0, 0]))
    monkeypatch.setattr(ndi_audio, "sources", lambda: ["VSH-ARLT-5090 (OBS PGM)"])


@pytest.fixture
def selection(tmp_path):
    return Selection(Sources(), tmp_path / "sources.json")


@pytest.fixture
def client(selection):
    live = LiveSitrep(lambda: None)
    return TestClient(create_app(live, selection))


def test_the_operator_page_offers_a_camera_and_a_sound_source(client):
    page = client.get("/").text
    assert 'id="camera"' in page
    assert 'id="sound"' in page
    assert "/static/operator.js" in page


def test_the_page_lists_every_device_and_marks_what_a_run_would_open(client):
    offered = client.get("/api/sources").json()

    assert offered["cameras"] == CAMERAS
    assert {"name": "Webcam 4 (NDI Webcam Audio)", "api": "Windows WASAPI"} in offered["microphones"]
    # Nothing selected: the first camera and PortAudio's default input.
    assert offered["selection"] == {
        "camera": "NDI Webcam Video 1",
        "sound": {"kind": "microphone", "name": "Microsoft Sound Mapper - Input", "api": "MME"},
        "errors": [],
    }


def test_ndi_sources_are_listed_separately(client):
    assert client.get("/api/sources/ndi").json() == {"sources": ["VSH-ARLT-5090 (OBS PGM)"]}


def test_a_selection_is_kept_saved_and_opened_by_the_next_run(client, selection, tmp_path):
    chosen = {"video": "vMix Video External 3",
              "audio": "Digitale Audioschnittstelle (USB3.0 Audio)",
              "audio_api": "Windows WASAPI"}

    response = client.post("/api/sources", json=chosen)

    assert response.status_code == 200
    assert response.json()["selection"]["camera"] == "vMix Video External 3"
    assert json.loads((tmp_path / "sources.json").read_text())["video"] == "vMix Video External 3"
    video, audio = session.resolve_sources(selection.sources)
    assert video.name == "vMix Video External 3"
    assert (audio.name, audio.hostapi) == ("Digitale Audioschnittstelle (USB3.0 Audio)",
                                           "Windows WASAPI")


def test_an_ndi_source_replaces_the_microphone(client, selection):
    client.post("/api/sources", json={"video": "OBS Virtual Camera",
                                      "audio_ndi": "VSH-ARLT-5090 (OBS PGM)"})

    assert client.get("/api/sources").json()["selection"]["sound"] == {
        "kind": "ndi", "name": "VSH-ARLT-5090 (OBS PGM)"}
    _, audio = session.resolve_sources(selection.sources)
    assert audio == ndi_audio.NdiAudio("VSH-ARLT-5090 (OBS PGM)")


def test_a_device_not_on_this_machine_is_refused_and_the_selection_stands(client, selection):
    client.post("/api/sources", json={"video": "SandbergCapture"})

    response = client.post("/api/sources", json={"video": "Blackmagic"})

    assert response.status_code == 400
    assert "Blackmagic" in response.json()["detail"]
    assert selection.sources.video == "SandbergCapture"


def test_the_saved_selection_returns_after_a_restart(tmp_path):
    path = tmp_path / "sources.json"
    Selection(Sources(), path).choose(Sources(video="SandbergCapture", audio_ndi="OBS"))

    assert Selection.load(path, Sources()).sources == Sources(video="SandbergCapture",
                                                              audio_ndi="OBS")


def test_command_line_sources_override_the_saved_selection(tmp_path):
    path = tmp_path / "sources.json"
    path.write_text(Sources(video="SandbergCapture", audio_ndi="OBS").model_dump_json())

    camera_only = Selection.load(path, Sources(video="OBS Virtual Camera")).sources
    microphone = Selection.load(path, Sources(audio="USB3.0", audio_api="WASAPI")).sources

    assert camera_only == Sources(video="OBS Virtual Camera", audio_ndi="OBS")
    # The sound is replaced as a whole: a microphone ends the NDI source.
    assert microphone == Sources(video="SandbergCapture", audio="USB3.0", audio_api="WASAPI")


def test_an_unreadable_saved_selection_starts_from_the_command_line(tmp_path):
    path = tmp_path / "sources.json"
    path.write_text("{ not json")

    assert Selection.load(path, Sources(video="OBS")).sources == Sources(video="OBS")
