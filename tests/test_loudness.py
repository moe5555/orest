"""Loudness: the session's normal speaking level, and the gain it puts on Risiko."""

from datetime import datetime, timedelta

import numpy as np
import pytest

from sitrep import actions, capture, loudness, report

T0 = datetime(2026, 9, 28, 20, 0, 0)
RATE = 16000


def wav(*parts: tuple[float, float]) -> bytes:
    """Seconds of a tone at an amplitude, one after another."""
    samples = np.concatenate([
        amplitude * np.sin(np.linspace(0, 2 * np.pi * 220 * seconds, int(RATE * seconds)))
        for seconds, amplitude in parts])
    return capture.encode_wav(samples.astype(np.float32), RATE)


def calibrated(level_db: float, spread_db: float = 0.0) -> loudness.Calibration:
    subject = loudness.Calibration(seconds=10, provisional=10)
    subject.learn(level_db - spread_db, 5)
    subject.learn(level_db + spread_db, 5)
    return subject


def test_a_stretch_has_the_level_of_its_loud_part():
    timeline = loudness.Timeline(wav((1.0, 0.01), (1.0, 0.5)), T0)
    quiet = timeline.level(T0, T0 + timedelta(seconds=1))
    loud = timeline.level(T0 + timedelta(seconds=1), T0 + timedelta(seconds=2))
    assert loud - quiet == pytest.approx(20 * np.log10(50), abs=0.5)


def test_a_stretch_outside_the_audio_has_no_level():
    timeline = loudness.Timeline(wav((1.0, 0.1)), T0)
    assert timeline.level(T0 - timedelta(seconds=5), T0 - timedelta(seconds=4)) is None


def test_nothing_is_amplified_until_the_session_has_heard_enough_speech():
    subject = loudness.Calibration(seconds=120, provisional=30)
    subject.learn(-30.0, 20)
    assert not subject.calibrated and subject.heard == 20
    assert subject.gain(-5.0) == 1.0
    subject.learn(-30.0, 15)
    assert subject.calibrated and not subject.settled


def test_the_normal_level_goes_on_learning_until_it_settles():
    """A quiet opening does not fix the level for the whole session."""
    subject = loudness.Calibration(seconds=120, provisional=30)
    subject.learn(-40.0, 30)
    assert subject.mean == pytest.approx(-40.0)
    subject.learn(-26.0, 90)
    assert subject.settled
    assert subject.mean == pytest.approx(-29.5)
    subject.learn(-10.0, 60)
    assert subject.mean == pytest.approx(-29.5)


def test_louder_than_normal_raises_the_gain_and_quieter_leaves_it():
    subject = calibrated(-30.0)
    # The spread is at least MIN_SPREAD, so 6 dB above is two deviations, the
    # first of which is ordinary variation.
    assert subject.gain(-24.0) == pytest.approx(1 + (2 - loudness.QUIET) * loudness.GAIN)
    assert subject.gain(-28.0) == 1.0
    assert subject.gain(-40.0) == 1.0
    assert subject.gain(0.0) == loudness.MAX_GAIN


def test_calibration_stops_learning_once_it_is_set():
    subject = calibrated(-30.0)
    subject.learn(-10.0, 100)
    assert subject.mean == pytest.approx(-30.0)


def test_only_risiko_that_points_to_danger_is_amplified():
    assert loudness.amplified(3, 1.5) == 4.5
    assert loudness.amplified(-2, 1.5) == -2


def test_a_loud_line_raises_its_speakers_risiko(sitrep):
    at = sitrep.zeitfenster.beginn
    shouted = report.Aeusserung(name="Vielleicht: Jakob", text="Ich hasse dich.", beginn=at,
                                ende=at, begruendung="Hass.", risiko=3, menschlichkeit=-3,
                                verstaerkung=1.5)
    document = sitrep.model_copy(update={"aeusserungen": [shouted]})
    value, cause = document.bewertung("Vielleicht: Jakob", "risiko")
    assert value == 5 and cause.endswith("laut ×1.5")
    # Menschlichkeit is left as the model read it.
    assert document.bewertung("Vielleicht: Jakob", "menschlichkeit")[0] == 0


def test_a_loud_moment_raises_the_risiko_of_an_action_in_it():
    push = np.zeros(120)
    push[51] = 0.8                          # pushing other person: risiko +3
    record = actions.Evidence(T0, (1,), *actions.weigh(push, actions.sitrep_map.load()))
    quiet = actions.rate([record], {1: "Klara"})[0]
    loud = actions.rate([record], {1: "Klara"}, gain=lambda begins, ends: 2.0)[0]
    assert (quiet.risiko, loud.risiko) == (2, 5)
    assert loud.verstaerkung == 2.0 and loud.anlass_risiko.endswith("laut ×2.0")


def test_a_report_calibrates_on_its_speech_and_records_the_state(monkeypatch, bericht):
    monkeypatch.setattr(report.transcribe, "segments", lambda audio, **kwargs: [
        report.transcribe.Segment(0.0, 20.0, "Lange Rede.")])
    monkeypatch.setattr(report, "analyse", lambda *args, **kwargs: bericht)
    window = capture.Window(0, T0, T0 + timedelta(seconds=20), [], wav((20.0, 0.1)), 20.0)
    laut = loudness.Calibration(seconds=120, provisional=30)

    document = report.sitrep(window, laut=laut)

    assert document.pegel.kalibriert is False
    assert document.pegel.gehoert_s == pytest.approx(20.0)
    assert document.aeusserungen[0].verstaerkung == 1.0
    # A sine's RMS is its amplitude over the square root of two.
    assert document.aeusserungen[0].pegel_db == pytest.approx(20 * np.log10(0.1 / np.sqrt(2)), abs=0.5)


def test_lines_are_labelled_by_how_far_they_stand_out():
    subject = calibrated(-30.0)               # spread 3 dB
    assert loudness.label(subject, -28.0) == ""
    assert loudness.label(subject, -25.0) == "laut"
    assert loudness.label(subject, -22.0) == "geschrien"
    assert loudness.label(loudness.Calibration(), -10.0) == ""
