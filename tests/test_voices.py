"""The voice cue: its filterbanks, enrolment and how a stretch of speech is matched.

Voices are synthetic unit vectors, so the rules are exercised without the
network; the filterbanks and the network are checked against the reference
src/scripts/export_voice.py wrote.
"""

import csv
from pathlib import Path

import numpy as np
import pytest

from sitrep import capture, transcribe, voices

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

def test_enrolment_reads_audio_beside_the_photos_and_in_the_voice_folder(tmp_path, monkeypatch):
    for name in ("Alex", "Lena", "Nils"):
        (tmp_path / name).mkdir()
        (tmp_path / name / "photo.jpg").write_bytes(b"")
    (tmp_path / "Alex" / voices.VOICE_FOLDER).mkdir()
    (tmp_path / "Alex" / voices.VOICE_FOLDER / "rehearsals.wav").write_bytes(b"Alex")
    (tmp_path / "Lena" / "Lena_Voice.mp3").write_bytes(b"Lena")
    (tmp_path / "Lena" / "notes.txt").write_text("")

    decoded = []
    monkeypatch.setattr(voices, "decode", lambda path: decoded.append(path.name) or path.read_bytes())
    monkeypatch.setattr(voices, "windows", lambda samples: [samples, samples])
    monkeypatch.setattr(voices, "embed", lambda samples: ALEX if samples == b"Alex" else LENA)

    enrolled = voices.Voices.enrol(tmp_path)
    assert enrolled.names == ["Alex", "Lena"]
    assert decoded == ["rehearsals.wav", "Lena_Voice.mp3"]
    assert enrolled.match(ALEX).name == "Alex"
    assert enrolled.match(LENA).name == "Lena"


def test_each_segment_of_an_utterance_is_named_by_its_own_voice(monkeypatch):
    """A quick exchange within one utterance: Alex, then Lena, then a word too short to tell."""
    rate = voices.RATE
    sound = np.concatenate([np.full(rate, 1.0), np.full(rate, 2.0), np.full(rate, 2.0)])
    monkeypatch.setattr(voices, "embed", lambda samples: ALEX if samples.mean() < 1.5 else LENA)
    segments = [transcribe.Segment(0.0, 1.0, "Halt."), transcribe.Segment(1.0, 2.0, "Nein."),
                transcribe.Segment(2.0, 2.5, "Ja.")]
    assert [verdict.name for verdict in cast().attribute(segments, sound, rate)] == [
        "Alex", "Lena", None]


def test_an_utterance_at_another_rate_is_brought_to_the_voice_rate(monkeypatch):
    decoded = []
    monkeypatch.setattr(voices, "decode",
                        lambda wav: decoded.append(wav[:4]) or np.ones(voices.RATE, np.float32))
    monkeypatch.setattr(voices, "embed", lambda samples: LENA)
    verdicts = cast().attribute([transcribe.Segment(0.0, 1.0, "Ja.")],
                                np.zeros(48000, np.float32), 48000)
    assert decoded == [b"RIFF"] and verdicts[0].name == "Lena"


# Harvesting -----------------------------------------------------------------

def line(vector, recording="a.mp4", begin=0.0, seconds=2.0) -> voices.Line:
    return voices.Line(Path(recording).resolve(), begin,
                       np.zeros(int(seconds * voices.RATE), np.float32), vector / np.linalg.norm(vector))


def test_a_voice_grows_from_its_anchor_over_the_lines_close_to_it():
    near = line(LENA + voice((2, 1.0)))
    # Too far from the anchor alone, close to it with the near lines taken.
    further = line(0.6 * LENA + voice((2, 1.0)))
    stranger = line(voice((3, 1.0)))
    taken = voices.harvest({"Lena": LENA}, [near, near, further, stranger])
    assert [item[0] for item in taken["Lena"]] == [near, near, further]


def test_a_line_between_two_voices_is_taken_for_neither():
    between = line(ALEX + LENA)
    taken = voices.harvest({"Alex": ALEX, "Lena": LENA}, [line(ALEX), between, line(LENA)])
    assert [len(lines) for lines in taken.values()] == [1, 1]


def test_lines_are_kept_in_turn_from_each_recording_up_to_the_limit():
    a1, a2, a3 = (line(LENA, "a.mp4", begin) for begin in (0, 5, 10))
    b1 = line(LENA, "b.mp4")
    kept = voices.keep([(a3, 0.7), (a1, 0.9), (b1, 0.6), (a2, 0.8)], seconds=5.0)
    assert kept == [(a1, 0.9), (b1, 0.6), (a2, 0.8)]


def test_the_line_spoken_at_a_moment_is_found():
    first, second = line(LENA, "a.mp4", 10.0), line(ALEX, "a.mp4", 20.0, 3.0)
    assert voices.line_at([first, second], Path("a.mp4"), 21.5) is second
    assert voices.line_at([first, second], Path("a.mp4"), 15.0) is None
    assert voices.line_at([first, second], Path("b.mp4"), 21.5) is None


def test_a_harvest_writes_one_clip_and_its_list_of_lines(tmp_path):
    kept = [(line(LENA, "a.mp4", 12.0, 1.5), 0.8), (line(LENA, "b.mp4", 3.0, 2.0), 0.7)]
    folder = tmp_path / "Lena" / voices.VOICE_FOLDER
    voices.write_harvest(folder, kept, ["Ich gieße dieses Wasser aus.", "Vater."])

    samples, rate = capture.decode_wav((folder / "rehearsals.wav").read_bytes())
    assert rate == voices.RATE
    assert len(samples) == int(1.5 * rate) + 2 * rate + 3 * int(voices.HARVEST_GAP * rate)
    with open(folder / "rehearsals.csv", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert [(row["recording"], row["begin"], row["text"]) for row in rows] == [
        ("a.mp4", "12.0", "Ich gieße dieses Wasser aus."), ("b.mp4", "3.0", "Vater.")]


def test_windows_cut_speech_into_line_lengths(monkeypatch):
    rate = voices.RATE
    monkeypatch.setattr(voices, "speech", lambda samples: [(0, int(0.5 * rate)),
                                                           (rate, int(6.2 * rate))])
    parts = voices.windows(np.zeros(7 * rate, dtype=np.float32))
    # 0.5 s is too short; 5.2 s becomes three parts of about 1.7 s.
    assert len(parts) == 3
    assert all(voices.MIN_VOICE * rate <= len(part) <= 3 * rate for part in parts)
