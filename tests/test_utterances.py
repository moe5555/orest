"""Speech cut into utterances as it arrives, and each line handed out as it ends."""

from datetime import datetime, timedelta

import numpy as np
import pytest
from faster_whisper.vad import get_vad_model

from sitrep import loudness, report, transcribe, utterances

T0 = datetime(2026, 9, 29, 20, 0, 0)
STEP = utterances.STEP


def spans(probabilities, **options):
    return utterances.Segmenter(**options).push(probabilities)


def seconds(count: float) -> int:
    """Chunks in so many seconds."""
    return round(count / STEP)


# ---- where an utterance begins and ends ---------------------------------------

def test_speech_followed_by_silence_is_one_utterance():
    probabilities = [0.0] * 10 + [0.9] * seconds(2) + [0.0] * seconds(1)
    assert spans(probabilities) == [(10, 10 + seconds(2))]


def test_an_utterance_ends_only_after_enough_silence():
    """A breath between words does not end the line."""
    probabilities = [0.9] * seconds(1) + [0.0] * seconds(0.3) + [0.9] * seconds(1)
    segmenter = utterances.Segmenter()
    assert segmenter.push(probabilities) == []
    assert segmenter.speaking
    assert segmenter.push([0.0] * seconds(utterances.END_SILENCE)) == [
        (0, seconds(1) + seconds(0.3) + seconds(1))]


def test_a_click_is_not_an_utterance():
    assert spans([0.9] * 3 + [0.0] * seconds(1)) == []


def test_a_wavering_probability_keeps_speech_going():
    """Between the two thresholds, a chunk counts as speech once speech has begun."""
    probabilities = [0.9] * seconds(1) + [0.4] * seconds(1) + [0.0] * seconds(1)
    assert spans(probabilities) == [(0, seconds(2))]


def test_a_long_utterance_ends_at_the_next_break_between_phrases():
    """In a quarrel speech rarely falls silent; a short pause after a few
    seconds is where the line ends."""
    first = seconds(4)
    probabilities = [0.9] * first + [0.0] * seconds(utterances.PHRASE_PAUSE) + [0.9] * seconds(2)
    segmenter = utterances.Segmenter()
    assert segmenter.push(probabilities) == [(0, first)]
    assert segmenter.speaking


def test_a_short_utterance_does_not_end_at_a_break_between_phrases():
    first = seconds(1)
    probabilities = [0.9] * first + [0.0] * seconds(utterances.PHRASE_PAUSE) + [0.9] * seconds(1)
    assert spans(probabilities) == []


def test_an_utterance_without_a_break_between_phrases_is_cut_at_its_last_pause():
    first = seconds(6)
    pause = seconds(utterances.PAUSE) + 1
    assert pause < seconds(utterances.PHRASE_PAUSE)
    probabilities = [0.9] * first + [0.2] * pause + [0.9] * seconds(8)
    [(start, end)] = spans(probabilities)
    assert (start, end) == (0, first)


def test_a_long_utterance_without_a_pause_is_cut_where_it_stands():
    probabilities = [0.9] * seconds(25)
    longest = seconds(utterances.MAX_UTTERANCE)
    assert spans(probabilities) == [(0, longest), (longest, 2 * longest)]


def test_utterances_span_several_pushes():
    segmenter = utterances.Segmenter()
    assert segmenter.push([0.9] * seconds(1)) == []
    assert segmenter.push([0.9] * seconds(1)) == []
    assert segmenter.push([0.0] * seconds(1)) == [(0, seconds(2))]


# ---- the stream ------------------------------------------------------------

def test_voice_activity_run_in_pieces_equals_one_pass():
    """Silero carries its state between chunks, so a live stream is rated as a
    recording would be."""
    rng = np.random.default_rng(0)
    sound = (0.1 * rng.standard_normal(utterances.CHUNK * 100)).astype(np.float32)
    whole = get_vad_model()(sound).reshape(-1)
    vad = utterances.Vad()
    pieces, position = [], 0
    for size in (100, 3000, 1, 777, 16000, 31322):
        pieces.append(vad(sound[position:position + size]))
        position += size
    assert np.allclose(np.concatenate(pieces), whole[:sum(len(piece) for piece in pieces)])


def test_resampling_in_pieces_equals_resampling_at_once():
    rate = 44100
    sound = np.sin(np.linspace(0, 200, rate)).astype(np.float32)
    whole = utterances.Resampler(rate)(sound)
    resample = utterances.Resampler(rate)
    pieces = np.concatenate([resample(sound[start:start + 1234])
                             for start in range(0, len(sound), 1234)])
    assert len(pieces) == len(whole) == pytest.approx(16000, abs=2)
    assert np.allclose(pieces, whole, atol=1e-5)


def test_the_clock_counts_samples_and_resets_after_dropped_sound():
    clock = utterances.Clock(16000)
    clock.advance(16000, T0 + timedelta(seconds=1))
    assert clock.at(0) == T0
    clock.advance(16000, T0 + timedelta(seconds=2, milliseconds=100))
    assert clock.at(16000) == T0 + timedelta(seconds=1)
    # Two seconds of sound went missing.
    clock.advance(16000, T0 + timedelta(seconds=5))
    assert clock.at(clock.samples) == T0 + timedelta(seconds=5)


def test_the_ring_hands_out_the_samples_asked_for():
    ring = utterances.Ring(10, keep=100)
    for start in range(0, 50, 7):
        ring.add(np.arange(start, min(start + 7, 50), dtype=np.float32))
    assert ring.between(12, 30).tolist() == list(range(12, 30))


def test_the_ring_forgets_sound_older_than_it_keeps():
    ring = utterances.Ring(10, keep=2)
    for start in range(0, 100, 10):
        ring.add(np.arange(start, start + 10, dtype=np.float32))
    assert ring.between(0, 50).size == 0
    assert ring.between(85, 95).tolist() == list(range(85, 95))


class ScriptedVad:
    """Speech probabilities by position in the stream, instead of Silero."""

    def __init__(self, speech: tuple[float, float]):
        self._speech = speech
        self._done = 0

    def __call__(self, samples):
        count = (self._done + len(samples)) // utterances.CHUNK - self._done // utterances.CHUNK
        first = self._done // utterances.CHUNK
        self._done += len(samples)
        return np.array([0.9 if self._speech[0] <= (first + i) * STEP < self._speech[1] else 0.0
                         for i in range(count)])


def test_an_utterance_is_queued_with_its_sound_and_its_time(monkeypatch):
    rate = 16000
    subject = utterances.Utterances(rate, lambda lines, bewertet: None)
    subject._vad = ScriptedVad((1.0, 3.0))
    for second in range(5):
        subject.process(np.full(rate, 0.1, dtype=np.float32),
                        T0 + timedelta(seconds=second + 1))
    sound, begins, ends = subject._jobs.get_nowait()
    assert begins == pytest.approx(T0 + timedelta(seconds=1.0 - utterances.PAD),
                                   abs=timedelta(milliseconds=40))
    assert ends == pytest.approx(T0 + timedelta(seconds=3.0 + utterances.PAD),
                                 abs=timedelta(milliseconds=40))
    assert len(sound) / rate == pytest.approx(2.0 + 2 * utterances.PAD, abs=0.04)
    assert subject._jobs.empty()


def test_the_level_of_the_sound_is_measured_as_it_arrives():
    meter = loudness.Meter()
    subject = utterances.Utterances(16000, lambda lines, bewertet: None, meter=meter)
    subject._vad = ScriptedVad((99.0, 99.0))
    subject.process(np.full(16000, 0.1, dtype=np.float32), T0 + timedelta(seconds=1))
    assert meter.level(T0, T0 + timedelta(seconds=1)) == pytest.approx(-20.0, abs=0.1)


# ---- from utterance to line ---------------------------------------------------

class Handed(list):
    """Lines handed out, each call as (texts, bewertet)."""

    def __call__(self, lines, bewertet):
        self.append((lines, bewertet))


def test_a_line_is_handed_out_as_transcribed_before_it_is_rated(monkeypatch):
    heard = []

    def segments(wav, language):
        heard.append(language)
        return [transcribe.Segment(0.2, 1.0, f"Zeile {len(heard)}.")]

    monkeypatch.setattr(utterances.transcribe, "segments", segments)
    handed = Handed()
    subject = utterances.Utterances(16000, handed, language="en",
                                    einschaetzen=lambda lines, vorher: pytest.fail("not yet"))
    sound = np.zeros(16000, dtype=np.float32)
    subject.transcribe(sound, T0, T0 + timedelta(seconds=1))

    assert heard == ["en"]
    [(lines, bewertet)] = handed
    assert not bewertet
    assert [line.beginn for line in lines] == [T0 + timedelta(seconds=0.2)]
    assert lines[0].risiko is None
    assert len(subject.latenzen) == 1
    assert subject._unrated.qsize() == 1


def test_lines_waiting_are_rated_together_with_the_lines_before_as_context(monkeypatch):
    monkeypatch.setattr(utterances.transcribe, "segments", lambda wav, language: [
        transcribe.Segment(0.0, 1.0, "Zeile.")])
    rated = []

    def einschaetzen(lines, vorher):
        rated.append(([line.beginn for line in lines], [line.beginn for line in vorher]))
        return [line.model_copy(update={"risiko": 2, "menschlichkeit": 0}) for line in lines]

    handed = Handed()
    subject = utterances.Utterances(16000, handed, einschaetzen=einschaetzen)
    sound = np.zeros(16000, dtype=np.float32)
    for second in (0, 5, 9):
        subject.transcribe(sound, T0 + timedelta(seconds=second),
                           T0 + timedelta(seconds=second + 1))
    first = [subject._unrated.get_nowait(), subject._unrated.get_nowait()]
    subject.rate_lines(first)
    subject.rate_lines([subject._unrated.get_nowait()])

    at = [T0 + timedelta(seconds=second) for second in (0, 5, 9)]
    assert rated == [(at[:2], []), (at[2:], at[:2])]
    assert [bewertet for _, bewertet in handed] == [False, False, False, True, True]
    assert all(line.risiko == 2 for line in handed[3][0] + handed[4][0])
    assert len(subject.bewertet) == len(subject.stufen) == 3


def test_a_line_is_attributed_from_the_start_of_its_own_utterance(monkeypatch):
    monkeypatch.setattr(utterances.transcribe, "segments",
                        lambda wav, language: [transcribe.Segment(0.5, 1.5, "Halt.")])
    asked = []

    def sprecher(segmente, begins):
        asked.append(begins)
        return [report.Aeusserung(name="Klara", text=segment.text, beginn=begins, ende=begins)
                for segment in segmente]

    handed = Handed()
    subject = utterances.Utterances(16000, handed, sprecher=sprecher)
    subject.transcribe(np.zeros(16000, dtype=np.float32), T0, T0 + timedelta(seconds=1))
    assert asked == [T0]
    assert handed[0][0][0].name == "Klara"


def test_silence_that_whisper_hears_nothing_in_hands_out_nothing(monkeypatch):
    monkeypatch.setattr(utterances.transcribe, "segments", lambda wav, language: [])
    handed = Handed()
    subject = utterances.Utterances(16000, handed,
                                    einschaetzen=lambda lines, vorher: pytest.fail("no rating"))
    subject.transcribe(np.zeros(16000, dtype=np.float32), T0, T0 + timedelta(seconds=1))
    assert handed == [] and subject._unrated.empty()


def test_a_line_carries_its_loudness_and_teaches_the_session_its_normal_level(monkeypatch):
    monkeypatch.setattr(utterances.transcribe, "segments",
                        lambda wav, language: [transcribe.Segment(0.0, 20.0, "Lange Rede.")])
    meter = loudness.Meter()
    meter.add(np.full(16000 * 20, 0.1, dtype=np.float32), 16000, T0 + timedelta(seconds=20))
    laut = loudness.Calibration(seconds=120, provisional=30)
    handed = Handed()
    subject = utterances.Utterances(16000, handed, meter=meter, laut=laut)
    subject.transcribe(np.zeros(16000, dtype=np.float32), T0, T0 + timedelta(seconds=20))
    [([line], _)] = handed
    assert line.pegel_db == pytest.approx(-20.0, abs=0.1)
    assert line.verstaerkung == 1.0
    assert laut.heard == pytest.approx(20.0)
    assert not laut.calibrated
