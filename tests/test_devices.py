"""Device selection rules, which decide what the SITREP actually looks at."""

from types import SimpleNamespace

import pytest

from sitrep import devices

CAMERAS = [
    devices.VideoDevice(0, "FHD WebCam"),
    devices.VideoDevice(1, "OBS Virtual Camera"),
    devices.VideoDevice(2, "Meta Quest 3"),
    devices.VideoDevice(3, "Meta Quest 3S"),
]


def select(spec, cameras=CAMERAS):
    return devices._select(spec, cameras, "video", devices.format_video_devices)


def test_no_spec_takes_the_first_device():
    assert select(None) is CAMERAS[0]


def test_numeric_spec_matches_the_device_index():
    assert select("1") is CAMERAS[1]


def test_name_fragment_is_case_insensitive():
    assert select("obs") is CAMERAS[1]


def test_unknown_index_lists_what_is_available():
    with pytest.raises(ValueError, match="No video device with index 9"):
        select("9")


def test_unknown_name_lists_what_is_available():
    with pytest.raises(ValueError, match="No video device matching"):
        select("Blackmagic")


def test_ambiguous_fragment_is_refused_rather_than_guessed():
    with pytest.raises(ValueError, match="matches 2 video devices"):
        select("Meta Quest")


def test_full_name_selects_its_device_beside_a_longer_name():
    assert select("Meta Quest 3") is CAMERAS[2]
    assert select("meta quest 3s") is CAMERAS[3]


def test_empty_device_list_is_an_error():
    with pytest.raises(RuntimeError, match="No video input devices found"):
        select(None, cameras=[])


# A single microphone is published once per host API, so the WASAPI view here
# is what --audio-api WASAPI narrows the list down to.
WASAPI = [
    devices.AudioDevice(25, "Virtual Cable", "Windows WASAPI", 0, 2, 48000.0),
    devices.AudioDevice(26, "Mikrofonarray (Senary Audio)", "Windows WASAPI", 0, 2, 48000.0),
]


def fake_portaudio(monkeypatch, default_input_device, portaudio_default=25):
    monkeypatch.setattr(devices, "list_audio_devices", lambda: list(WASAPI))
    monkeypatch.setattr(devices.sd, "query_hostapis", lambda: [
        {"name": "Windows WASAPI", "default_input_device": default_input_device},
    ])
    monkeypatch.setattr(devices.sd, "default",
                        SimpleNamespace(device=[portaudio_default, 0]))


def test_host_api_default_input_wins_over_enumeration_order(monkeypatch):
    fake_portaudio(monkeypatch, default_input_device=26)
    assert devices.resolve_audio_device(hostapi="WASAPI").index == 26


def test_host_api_without_a_default_input_is_reported(monkeypatch):
    """PortAudio answers -1 here; picking the first device would take the
    virtual cable without saying so."""
    fake_portaudio(monkeypatch, default_input_device=-1)
    with pytest.raises(ValueError, match="no default input device"):
        devices.resolve_audio_device(hostapi="WASAPI")


def test_named_device_is_selected_even_without_a_default(monkeypatch):
    fake_portaudio(monkeypatch, default_input_device=-1)
    assert devices.resolve_audio_device("Senary", hostapi="WASAPI").index == 26


def test_unknown_host_api_is_reported(monkeypatch):
    fake_portaudio(monkeypatch, default_input_device=26)
    with pytest.raises(ValueError, match="No audio host API matching"):
        devices.resolve_audio_device(hostapi="CoreAudio")


def test_describe_names_both_sources():
    line = devices.describe(CAMERAS[0], WASAPI[1])
    assert "[0] FHD WebCam" in line
    assert "[26] Mikrofonarray (Senary Audio) (Windows WASAPI)" in line
