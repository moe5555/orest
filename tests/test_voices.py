"""The voice cue: its filterbanks, enrolment and how a stretch of speech is matched.

Voices are synthetic unit vectors, so the rules are exercised without the
network; the filterbanks and the network are checked against the reference
src/scripts/export_voice.py wrote.
"""

from pathlib import Path

import numpy as np
import pytest

from sitrep import voices

REFERENCE = Path(__file__).parent / "fixtures" / "voice_reference.npz"


def voice(*values) -> np.ndarray:
    """A unit-length voice vector pointing in a named direction."""
    vector = np.zeros(8, dtype=np.float32)
    for index, value in values:
        vector[index] = value
    return vector / np.linalg.norm(vector)


ALEX, LENA = voice((0, 1.0)), voice((1, 1.0))


def cast(**kwargs) -> voices.Voices:
    return voices.Voices({"Alex": ALEX, "Lena": LENA}, **{"threshold": 0.5, "margin": 0.1, **kwargs})


# Filterbanks and network -----------------------------------------------------

def test_filterbanks_match_torchaudio():
    reference = np.load(REFERENCE)
    features = voices.fbank(reference["samples"])
    assert features.shape == reference["fbank"].shape
    assert np.allclose(features, reference["fbank"], atol=1e-3)


def test_too_short_a_stretch_has_no_filterbanks():
    assert voices.fbank(np.zeros(voices.FRAME - 1, dtype=np.float32)).shape == (0, voices.MEL_BINS)


@pytest.mark.skipif(not voices.available(), reason="voice model not installed")
def test_the_network_matches_the_reference():
    reference = np.load(REFERENCE)
    expected = reference["vector"] / np.linalg.norm(reference["vector"])
    assert float(voices.embed(reference["samples"]) @ expected) > 0.9999


# Matching --------------------------------------------------------------------

def test_the_closest_voice_names_a_stretch():
    verdict = cast().match(voice((0, 1.0), (1, 0.2)))
    assert verdict.name == "Alex"
    assert verdict.closest == "Alex"
    assert verdict.margin > 0.1


def test_a_voice_between_two_people_names_no_one():
    verdict = cast().match(voice((0, 1.0), (1, 0.9)))
    assert verdict.name is None
    assert verdict.closest == "Alex"


def test_a_voice_far_from_everyone_names_no_one():
    assert cast().match(voice((2, 1.0), (0, 0.3))).name is None


def test_threshold_and_margin_can_be_given_per_match():
    between = voice((0, 1.0), (1, 0.9))
    assert cast().match(between, threshold=0.5, margin=0.0).name == "Alex"


def test_a_short_stretch_is_not_matched(monkeypatch):
    monkeypatch.setattr(voices, "embed", lambda samples: pytest.fail("embedded"))
    short = np.zeros(int(0.5 * voices.RATE), dtype=np.float32)
    assert cast().identify(short).name is None


def test_without_enrolled_voices_no_one_is_named():
    assert voices.Voices({}).identify(np.zeros(2 * voices.RATE, dtype=np.float32)).name is None


def test_clear_forgets_the_voices():
    enrolled = cast()
    enrolled.clear()
    assert enrolled.names == []
    assert enrolled.match(ALEX).name is None


# Enrolment -------------------------------------------------------------------

def test_enrolment_reads_only_the_voice_folder(tmp_path, monkeypatch):
    for name in ("Alex", "Lena", "Nils"):
        (tmp_path / name).mkdir()
        (tmp_path / name / "photo.jpg").write_bytes(b"")
    for name in ("Alex", "Lena"):
        (tmp_path / name / voices.VOICE_FOLDER).mkdir()
        (tmp_path / name / voices.VOICE_FOLDER / "clip.wav").write_bytes(name.encode())
    (tmp_path / "Lena" / voices.VOICE_FOLDER / "notes.txt").write_text("")

    decoded = []
    monkeypatch.setattr(voices, "decode", lambda path: decoded.append(path.name) or path.read_bytes())
    monkeypatch.setattr(voices, "windows", lambda samples: [samples, samples])
    monkeypatch.setattr(voices, "embed", lambda samples: ALEX if samples == b"Alex" else LENA)

    enrolled = voices.Voices.enrol(tmp_path)
    assert enrolled.names == ["Alex", "Lena"]
    assert decoded == ["clip.wav", "clip.wav"]
    assert enrolled.match(ALEX).name == "Alex"
    assert enrolled.match(LENA).name == "Lena"


def test_windows_cut_speech_into_line_lengths(monkeypatch):
    rate = voices.RATE
    monkeypatch.setattr(voices, "speech", lambda samples: [(0, int(0.5 * rate)),
                                                           (rate, int(6.2 * rate))])
    parts = voices.windows(np.zeros(7 * rate, dtype=np.float32))
    # 0.5 s is too short; 5.2 s becomes three parts of about 1.7 s.
    assert len(parts) == 3
    assert all(voices.MIN_VOICE * rate <= len(part) <= 3 * rate for part in parts)
