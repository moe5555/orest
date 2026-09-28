"""Sound from an NDI source: mixed to mono at one rate, selected from the command line."""

from types import SimpleNamespace

import numpy as np
import pytest

from sitrep import devices, ndi_audio, session


def test_channels_are_mixed_down_to_one():
    stereo = np.array([[1.0, 0.0, 0.5], [0.0, 1.0, 0.5]], dtype=np.float32)
    assert ndi_audio.mono(stereo, ndi_audio.SAMPLERATE).tolist() == [0.5, 0.5, 0.5]


def test_another_rate_is_resampled_to_ndis():
    one_second = np.zeros((2, 44100), dtype=np.float32)
    assert len(ndi_audio.mono(one_second, 44100)) == ndi_audio.SAMPLERATE


def test_an_ndi_source_replaces_the_microphone(monkeypatch):
    monkeypatch.setattr(devices, "resolve_video_device", lambda spec: devices.VideoDevice(0, "Cam"))
    monkeypatch.setattr(devices, "resolve_audio_device",
                        lambda *args: pytest.fail("no microphone should be opened"))
    args = SimpleNamespace(video=None, audio=None, audio_api=None,
                           audio_ndi="HOST (OBS PGM)")
    _, audio = session.resolve_sources(args)
    assert audio == ndi_audio.NdiAudio("HOST (OBS PGM)")


def test_the_startup_line_names_the_ndi_source():
    described = devices.describe(devices.VideoDevice(0, "Cam"),
                                 ndi_audio.NdiAudio("HOST (OBS PGM)"))
    assert "audio:  NDI HOST (OBS PGM)" in described
