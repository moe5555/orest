"""The SITREP document: its shape on disk and the measured/generated split."""

import json
from datetime import datetime

import pytest
from ollama import ResponseError
from pydantic import ValidationError

from sitrep import capture, presence, report


def test_bewertungen_are_the_rating_fields_of_person_in_order():
    assert report.BEWERTUNGEN == (
        "kollaborativ", "relevanz", "verantwortungsvoll", "menschlich", "gefahr")


def test_every_rating_is_bounded_zero_to_five():
    for name in report.BEWERTUNGEN:
        with pytest.raises(ValidationError):
            report.Person(name="Klara", beschreibung="",
                          **{**dict.fromkeys(report.BEWERTUNGEN, 0), name: 6})


def test_measured_fields_stay_separate_from_the_generated_report(sitrep):
    """The model's Lagebericht is nested, so no generated field can take the
    place of a measured one however the schema grows."""
    document = json.loads(sitrep.model_dump_json())
    assert set(document) == {"zeitfenster", "quelle", "gesagt", "anwesend",
                             "latenz_s", "bericht"}
    assert set(document["bericht"]) == {"beschreibung", "personen", "szene", "prognose",
                                        "empfehlung", "einschreiten"}


def test_the_model_is_not_asked_whether_to_intervene():
    """Intervention follows from the scene ratings, so the model is never
    given a field in which to decide it."""
    assert "einschreiten" not in report.schema()["properties"]


def test_scene_ratings_run_from_zero_to_ten():
    report.Szene(relevanz=0, eskalation=10, gefahr=10)
    for field in ("relevanz", "eskalation", "gefahr"):
        with pytest.raises(ValidationError):
            report.Szene(**{**dict.fromkeys(("relevanz", "eskalation", "gefahr"), 0),
                            field: 11})


@pytest.mark.parametrize("eskalation, gefahr, einschreiten", [
    (6, 6, False),   # at the threshold: not above it
    (7, 0, True),
    (0, 7, True),
    (10, 10, True),
])
def test_intervention_follows_escalation_or_danger_above_six(
        bericht, eskalation, gefahr, einschreiten):
    szene = report.Szene(relevanz=5, eskalation=eskalation, gefahr=gefahr)
    assert bericht.model_copy(update={"szene": szene}).einschreiten is einschreiten


def test_a_measure_below_the_threshold_is_discarded(bericht):
    """Below the threshold the model's measure is not a recommendation."""
    calm = report.Lagebericht.model_validate({
        **bericht.model_dump(exclude={"einschreiten"}),
        "empfehlung": "Keine Massnahme."})
    assert not calm.einschreiten
    assert calm.empfehlung == ""


def test_a_measure_above_the_threshold_is_kept(eskaliert):
    assert eskaliert.einschreiten
    assert eskaliert.empfehlung == "Probe unterbrechen."


def test_a_serialised_sitrep_reads_back_identically(sitrep):
    assert report.Sitrep.model_validate_json(sitrep.model_dump_json()) == sitrep


def test_json_output_keeps_german_text_readable(sitrep):
    document = sitrep.model_copy(update={"gesagt": "Zurück an die Tür."})
    line = document.model_dump_json()
    assert "Tür" in line
    assert "\\u" not in line


def test_forecasts_are_ordered_most_likely_first(bericht):
    assert [verlauf.wahrscheinlichkeit for verlauf in bericht.prognose] == [60, 20, 15]


def test_a_report_carries_exactly_three_forecasts(bericht):
    for count in (2, 4):
        prognose = [report.Verlauf(verlauf="", wahrscheinlichkeit=10)] * count
        with pytest.raises(ValidationError):
            report.Lagebericht(beschreibung="", personen=[], szene=bericht.szene,
                               prognose=prognose, empfehlung="")


def test_a_probability_is_a_percentage():
    with pytest.raises(ValidationError):
        report.Verlauf(verlauf="", wahrscheinlichkeit=101)


def test_the_schema_limits_names_to_those_present():
    """The grammar is what stops the model inventing a name, so the list it is
    given must be exactly who is present, plus the one fallback."""
    anwesend = [report.Anwesend(name="Klara", erkannt=True),
                report.Anwesend(name="Vielleicht: Jakob", erkannt=False)]
    names = report.schema(anwesend)["$defs"]["Person"]["properties"]["name"]["enum"]
    assert names == ["Klara", "Vielleicht: Jakob", report.UNBEKANNT]


def test_with_nobody_present_the_only_name_is_unbekannt():
    names = report.schema([])["$defs"]["Person"]["properties"]["name"]["enum"]
    assert names == [report.UNBEKANNT]


def test_the_schema_asks_for_exactly_three_forecasts():
    prognose = report.schema()["properties"]["prognose"]
    assert prognose["minItems"] == prognose["maxItems"] == report.PROGNOSEN


def test_sitrep_marks_only_recognised_names_as_recognised(sitrep):
    assert sitrep.erkannt("Klara")
    assert not sitrep.erkannt("Vielleicht: Jakob")
    assert not sitrep.erkannt(report.UNBEKANNT)


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


def test_prompt_lists_who_is_present_and_how_certain_the_name_is():
    prompt = report._prompt("", [report.Anwesend(name="Klara", erkannt=True),
                                 report.Anwesend(name="Vielleicht: Jakob", erkannt=False)])
    assert "- Klara (erkannt)" in prompt
    assert "- Vielleicht: Jakob (vermutet)" in prompt


def test_prompt_tells_the_model_where_the_names_are_and_the_threshold():
    prompt = report._prompt("")
    assert "Schild ueber" in prompt
    assert f"ueber {report.SCHWELLE}" in prompt


def test_prompt_marks_an_empty_room_rather_than_leaving_it_blank():
    assert "(niemand erfasst)" in report._prompt("")


def test_sitrep_takes_who_is_present_from_the_tracker_for_its_own_window(
        monkeypatch, bericht):
    """The roster is asked for the window's own span, and every person on it
    reaches both the model and the document."""
    seen = []

    def roster(since, until):
        seen.append((since, until))
        return [presence.Presence(label="Klara", name="Klara", guess="Vielleicht: Ida",
                                  similarity=0.7, sightings=4, first_seen=since,
                                  last_seen=until)]

    given = {}

    def analyse(frames, transcript, anwesend, model=None):
        given["anwesend"] = anwesend
        return bericht

    monkeypatch.setattr(report.transcribe, "transcribe", lambda audio: "")
    monkeypatch.setattr(report, "analyse", analyse)
    window = window_at(0)

    document = report.sitrep(window, roster=roster)

    assert seen == [(window.started, window.ended)]
    assert given["anwesend"] == [report.Anwesend(name="Klara", erkannt=True)]
    assert document.anwesend == given["anwesend"]


def window_at(index: int) -> capture.Window:
    """A captured window carrying the shape the model is given."""
    return capture.Window(
        index=index,
        started=datetime(2026, 9, 10, 14, 30, 0),
        ended=datetime(2026, 9, 10, 14, 30, 30),
        frames=[b"jpeg"],
        audio=b"wav",
        audio_seconds=30.0,
    )


def test_sitreps_streams_without_writing_anything(monkeypatch, tmp_path, sitrep):
    """The live SITREP is streamed and not retained, so a run must leave
    nothing behind on disk."""
    monkeypatch.setattr(report, "sitrep", lambda window, model=None, roster=None: sitrep)
    monkeypatch.chdir(tmp_path)

    produced = list(report.sitreps([window_at(0)]))

    assert produced == [sitrep]
    assert list(tmp_path.rglob("*")) == []


def test_a_window_whose_reply_does_not_parse_is_skipped(monkeypatch, sitrep):
    """A truncated reply costs one window, not the session."""
    replies = iter([ValidationError.from_exception_data("Lagebericht", []), sitrep])

    def answer(window, model=None, roster=None):
        reply = next(replies)
        if isinstance(reply, Exception):
            raise reply
        return reply

    monkeypatch.setattr(report, "sitrep", answer)
    assert list(report.sitreps([window_at(0), window_at(1)])) == [sitrep]


def test_a_rejected_prompt_does_not_end_the_session(monkeypatch, sitrep):
    replies = iter([ResponseError("rejected"), sitrep])

    def answer(window, model=None, roster=None):
        reply = next(replies)
        if isinstance(reply, Exception):
            raise reply
        return reply

    monkeypatch.setattr(report, "sitrep", answer)
    assert list(report.sitreps([window_at(0), window_at(1)])) == [sitrep]
