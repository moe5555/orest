"""The SITREP document: its shape on disk and the measured/generated split."""

import json
from datetime import datetime

import pytest
from ollama import ResponseError
from pydantic import ValidationError

from action import sitrep_map
import numpy as np

from sitrep import capture, presence, report


def test_bewertungen_are_the_rating_fields_of_person_in_order():
    assert report.BEWERTUNGEN == ("risiko", "menschlichkeit", "auffaelligkeit")


def test_bewertungen_are_the_measured_ratings_then_the_generated_ones():
    assert report.GEMESSEN == ("risiko", "menschlichkeit")
    assert report.GENERIERT == ("auffaelligkeit",)
    assert report.BEWERTUNGEN == report.GEMESSEN + report.GENERIERT


def test_the_action_table_carries_exactly_the_measured_ratings():
    assert sitrep_map.RATINGS == report.GEMESSEN


def test_the_model_is_not_asked_for_a_measured_rating():
    person = report.schema()["$defs"]["Person"]["properties"]
    assert not set(report.GEMESSEN) & set(person)


def test_every_rating_is_bounded_zero_to_five():
    for name in report.GENERIERT:
        with pytest.raises(ValidationError):
            report.Person(name="Klara", beschreibung="",
                          **{**dict.fromkeys(report.GENERIERT, 0), name: 6})
    for name in report.GEMESSEN:
        with pytest.raises(ValidationError):
            report.Handlung(name="Klara", lesungen=1,
                            **{**dict.fromkeys(report.GEMESSEN, 0), name: 6})


def test_a_persons_ratings_join_what_was_measured_and_what_was_generated(sitrep):
    klara, jakob = sitrep.bericht.personen
    assert sitrep.bewertungen(klara) == {"risiko": 0, "menschlichkeit": 4, "auffaelligkeit": 3}
    # Nothing measured is not a measurement of 0.
    assert sitrep.bewertungen(jakob) == {"risiko": None, "menschlichkeit": None,
                                         "auffaelligkeit": 4}


def test_an_unknown_person_is_never_given_someone_elses_measurement(sitrep):
    document = sitrep.model_copy(update={"handlungen": [
        report.Handlung(name=report.UNBEKANNT, risiko=5, menschlichkeit=0, lesungen=1)]})
    assert document.handlung(report.UNBEKANNT) is None


def test_the_measured_ratings_are_taken_up_to_the_end_of_the_window(monkeypatch, sitrep):
    monkeypatch.setattr(report.transcribe, "segments", lambda audio, **kwargs: [])
    monkeypatch.setattr(report, "analyse", lambda *args, **kwargs: sitrep.bericht)
    asked = []

    def handlungen(until, gain=None):
        asked.append(until)
        return sitrep.handlungen

    window = window_at(0)
    document = report.sitrep(window, handlungen=handlungen)
    assert asked == [window.ended]
    assert document.handlungen == sitrep.handlungen


def test_measured_fields_stay_separate_from_the_generated_report(sitrep):
    """The model's Lagebericht is nested, so no generated field can take the
    place of a measured one however the schema grows."""
    document = json.loads(sitrep.model_dump_json())
    assert set(document) == {"zeitfenster", "quelle", "gesagt", "anwesend",
                             "handlungen", "aeusserungen", "pegel", "latenz_s", "bericht"}
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

    def analyse(frames, transcript, anwesend, model=None, vorher=""):
        given["anwesend"] = anwesend
        return bericht

    monkeypatch.setattr(report.transcribe, "segments", lambda audio, **kwargs: [])
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
    monkeypatch.setattr(report, "_sitrep", lambda window, **kwargs: (sitrep, None))
    monkeypatch.chdir(tmp_path)

    produced = list(report.sitreps([window_at(0)]))

    assert produced == [sitrep]
    assert list(tmp_path.rglob("*")) == []


def test_a_window_whose_reply_does_not_parse_is_skipped(monkeypatch, sitrep):
    """A truncated reply costs one window, not the session."""
    replies = iter([ValidationError.from_exception_data("Lagebericht", []), sitrep])

    def answer(window, **kwargs):
        reply = next(replies)
        if isinstance(reply, Exception):
            raise reply
        return reply, None

    monkeypatch.setattr(report, "_sitrep", answer)
    assert list(report.sitreps([window_at(0), window_at(1)])) == [sitrep]


def test_a_rejected_prompt_does_not_end_the_session(monkeypatch, sitrep):
    replies = iter([ResponseError("rejected"), sitrep])

    def answer(window, **kwargs):
        reply = next(replies)
        if isinstance(reply, Exception):
            raise reply
        return reply, None

    monkeypatch.setattr(report, "_sitrep", answer)
    assert list(report.sitreps([window_at(0), window_at(1)])) == [sitrep]


def test_the_transcript_is_made_in_the_language_asked_for(monkeypatch, sitrep):
    asked = {}

    def segments(audio, language):
        asked["language"] = language
        return []

    monkeypatch.setattr(report.transcribe, "segments", segments)
    monkeypatch.setattr(report, "analyse", lambda *args, **kwargs: sitrep.bericht)
    report.sitrep(window_at(0), language="en")
    assert asked == {"language": "en"}


def test_the_model_reads_who_said_each_line(monkeypatch, bericht):
    """Speakers come from measurement; the model is told them, line by line."""
    spoken = [report.transcribe.Segment(0.0, 2.0, "Noch einmal."),
              report.transcribe.Segment(3.0, 4.0, "Von vorne.")]
    monkeypatch.setattr(report.transcribe, "segments", lambda audio, **kwargs: spoken)
    given = {}

    def analyse(frames, transcript, anwesend, model=None, vorher=""):
        given["transcript"] = transcript
        return bericht

    monkeypatch.setattr(report, "analyse", analyse)

    def sprecher(segmente, audio_start):
        return [report.Aeusserung(name=name, text=segment.text,
                                  beginn=audio_start, ende=audio_start)
                for name, segment in zip(("Klara", None), segmente)]

    window = window_at(0)
    document = report.sitrep(window, sprecher=sprecher)

    assert given["transcript"] == "Klara: Noch einmal.\n(unklar): Von vorne."
    assert document.gesagt == "Noch einmal. Von vorne."
    assert [line.name for line in document.aeusserungen] == ["Klara", None]


def test_segments_are_placed_in_time_from_the_end_of_the_window(monkeypatch, bericht):
    """Without attribution, lines still carry when they were said."""
    monkeypatch.setattr(report.transcribe, "segments", lambda audio, **kwargs: [
        report.transcribe.Segment(1.0, 2.5, "Halt.")])
    monkeypatch.setattr(report, "analyse", lambda *args, **kwargs: bericht)
    window = window_at(0)
    [line] = report.sitrep(window).aeusserungen
    audio_start = window.ended - report.timedelta(seconds=window.audio_seconds)
    assert line.name is None
    assert line.beginn == audio_start + report.timedelta(seconds=1.0)


def test_rated_lines_reach_the_document(monkeypatch, bericht):
    monkeypatch.setattr(report.transcribe, "segments", lambda audio, **kwargs: [
        report.transcribe.Segment(0.0, 1.0, "Ich hasse dich.")])
    monkeypatch.setattr(report, "analyse", lambda *args, **kwargs: bericht)

    def einschaetzen(lines):
        return [line.model_copy(update={"risiko": 3, "menschlichkeit": -3}) for line in lines]

    [line] = report.sitrep(window_at(0), einschaetzen=einschaetzen).aeusserungen
    assert (line.risiko, line.menschlichkeit) == (3, -3)


# ---- continuity between reports -------------------------------------------------

def _window(index, seconds=10.0, value=0.1):
    at = datetime(2026, 9, 28, 20, 0, 0) + report.timedelta(seconds=index * seconds)
    return capture.Window(index, at, at + report.timedelta(seconds=seconds), [],
                          capture.encode_wav(np.full(int(16000 * seconds), value, dtype=np.float32),
                                             16000), seconds)


def test_a_line_cut_off_by_the_window_end_is_held_back_with_its_sound():
    window = _window(0)
    kept, carry = report._held_back([report.transcribe.Segment(1.0, 3.0, "Erst."),
                                     report.transcribe.Segment(7.0, 9.8, "Dann wurde")], window)
    assert [segment.text for segment in kept] == ["Erst."]
    assert len(carry) / 16000 == pytest.approx(10.0 - 7.0 + report.CARRY_LEAD, abs=0.01)


def test_a_finished_line_or_a_long_one_is_reported_as_it_stands():
    window = _window(0)
    finished = [report.transcribe.Segment(7.0, 8.0, "Fertig.")]
    assert report._held_back(finished, window) == (finished, None)
    monologue = [report.transcribe.Segment(2.0, 14.9, "Und so weiter")]
    assert report._held_back(monologue, _window(0, seconds=15.0)) == (monologue, None)


def test_the_held_back_line_is_reported_whole_with_the_next_window(monkeypatch, bericht):
    heard = []

    def segments(audio, **kwargs):
        seconds = capture.decode_wav(audio)[0].size / 16000
        heard.append(round(seconds, 1))
        if len(heard) == 1:
            return [report.transcribe.Segment(8.0, seconds - 0.1, "Ich werde dich")]
        return [report.transcribe.Segment(0.1, 4.0, "Ich werde dich finden.")]

    monkeypatch.setattr(report.transcribe, "segments", segments)
    monkeypatch.setattr(report, "analyse", lambda *args, **kwargs: bericht)
    first, second = report.sitreps([_window(0), _window(1)])
    assert first.aeusserungen == []
    assert heard == [10.0, round(10.0 + 2.0 + report.CARRY_LEAD, 1)]
    assert [line.text for line in second.aeusserungen] == ["Ich werde dich finden."]


def test_each_report_is_shown_the_previous_reports_last_lines(monkeypatch, bericht):
    lines = iter([[report.transcribe.Segment(1.0, 2.0, "Du lügst.")],
                  [report.transcribe.Segment(1.0, 2.0, "Raus hier!")]])
    monkeypatch.setattr(report.transcribe, "segments", lambda audio, **kwargs: next(lines))
    shown = []

    def analyse(frames, transcript, anwesend, model=None, vorher=""):
        shown.append(vorher)
        return bericht

    monkeypatch.setattr(report, "analyse", analyse)
    list(report.sitreps([_window(0), _window(1)]))
    assert shown == ["", "(unklar): Du lügst."]
    assert "Zuvor gesagt:\n(unklar): Du lügst." in report._prompt("", [], shown[1])


def test_a_line_that_stood_out_is_marked_for_the_model():
    at = datetime(2026, 9, 28, 20, 0, 0)
    lines = [report.Aeusserung(name="Klara", text="Raus!", beginn=at, ende=at,
                               lautstaerke="geschrien"),
             report.Aeusserung(text="Ja.", beginn=at, ende=at)]
    assert report.protokoll(lines) == "Klara (geschrien): Raus!\n(unklar): Ja."
