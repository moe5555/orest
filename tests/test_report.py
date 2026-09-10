"""The SITREP document: its shape on disk and the measured/generated split."""

import json
from datetime import datetime

import pytest
from pydantic import ValidationError

from sitrep import capture, report


def test_bewertungen_are_the_rating_fields_of_person():
    assert report.BEWERTUNGEN == (
        "verantwortungsvoll", "menschlich", "gefahr", "kollaborativ")


def test_every_rating_is_bounded_zero_to_five():
    for name in report.BEWERTUNGEN:
        with pytest.raises(ValidationError):
            report.Person(kennung="P-01", merkmale="", taetigkeit="",
                          **{**dict.fromkeys(report.BEWERTUNGEN, 0), name: 6})


def test_measured_fields_stay_separate_from_the_generated_report(sitrep):
    """The model's Lagebericht is nested, so no generated field can take the
    place of a measured one however the schema grows."""
    document = json.loads(sitrep.model_dump_json())
    assert set(document) == {"zeitfenster", "quelle", "gesagt", "latenz_s", "bericht"}
    assert set(document["bericht"]) == set(report.Lagebericht.model_fields)


def test_a_serialised_sitrep_reads_back_identically(sitrep):
    assert report.Sitrep.model_validate_json(sitrep.model_dump_json()) == sitrep


def test_json_output_keeps_german_text_readable(sitrep):
    line = sitrep.model_dump_json()
    assert "Massnahme" in line
    assert "\\u" not in line


def test_transcript_is_carried_verbatim(sitrep):
    """report.py writes what Whisper heard rather than what the model wrote,
    so the field has to survive the round trip untouched."""
    reloaded = report.Sitrep.model_validate_json(sitrep.model_dump_json())
    assert reloaded.gesagt == "Noch einmal von vorne, bitte."


def test_prompt_names_the_transcript():
    assert "Transkript:" in report._prompt("Guten Tag")
    assert "Guten Tag" in report._prompt("Guten Tag")


def test_prompt_marks_silence_rather_than_leaving_it_blank():
    assert "(keine Sprache erkannt)" in report._prompt("")


def test_run_live_streams_without_writing_anything(monkeypatch, tmp_path, sitrep):
    """The live SITREP is streamed and not retained, so a session must leave
    nothing behind on disk."""
    captured = capture.Window(
        index=0,
        started=datetime(2026, 9, 10, 14, 30, 0),
        ended=datetime(2026, 9, 10, 14, 30, 30),
        frames=[b"jpeg"],
        audio=b"wav",
        audio_seconds=30.0,
    )

    def one_window(*args, **kwargs):
        yield captured

    monkeypatch.setattr(report.capture, "run", one_window)
    monkeypatch.setattr(report, "sitrep", lambda window, model=None: sitrep)
    monkeypatch.chdir(tmp_path)

    produced = list(report.run_live(None, None, interval=10, window=30))

    assert produced == [sitrep]
    assert list(tmp_path.rglob("*")) == []
