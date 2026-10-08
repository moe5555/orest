"""The SITREP document: its shape on disk and the measured/generated split."""

import json
from datetime import datetime, timedelta

import pytest
from pydantic import ValidationError

from action import sitrep_map

from sitrep import loudness, report


def test_bewertungen_are_the_rating_fields_of_person_in_order():
    assert report.BEWERTUNGEN == ("risiko", "menschlichkeit", "vorhersehbarkeit")


def test_bewertungen_are_the_evidence_ratings_then_vorhersehbarkeit():
    assert report.GEMESSEN == ("risiko", "menschlichkeit")
    assert report.BEWERTUNGEN == report.GEMESSEN + (report.VORHERSEHBARKEIT,)


def test_the_action_table_carries_exactly_the_measured_ratings():
    assert sitrep_map.RATINGS == report.GEMESSEN


def test_the_model_is_not_asked_for_a_measured_rating():
    person = report.schema()["$defs"]["Person"]["properties"]
    assert not set(report.BEWERTUNGEN) & set(person)


def test_every_rating_is_bounded_to_its_scale():
    for value in (-6, 6):
        with pytest.raises(ValidationError):
            report.Handlung(name="Klara", lesungen=1, risiko=0, menschlichkeit=0,
                            vorhersehbarkeit=value)
    for name in report.GEMESSEN:
        with pytest.raises(ValidationError):
            report.Handlung(name="Klara", lesungen=1,
                            **{**dict.fromkeys(report.GEMESSEN, 0), name: 6})


def test_a_persons_ratings_are_what_was_measured_of_them(sitrep):
    klara, jakob = sitrep.bericht.personen
    assert sitrep.bewertungen(klara) == {"risiko": 0, "menschlichkeit": 4, "vorhersehbarkeit": -2}
    # Nothing measured is not a measurement of 0.
    assert sitrep.bewertungen(jakob) == {"risiko": None, "menschlichkeit": None,
                                         "vorhersehbarkeit": None}


def test_an_unknown_person_is_never_given_someone_elses_measurement(sitrep):
    document = sitrep.model_copy(update={"handlungen": [
        report.Handlung(name=report.UNBEKANNT, risiko=5, menschlichkeit=0, lesungen=1)]})
    assert document.handlung(report.UNBEKANNT) is None


def test_measured_fields_stay_separate_from_the_generated_report(sitrep):
    """The model's Lagebericht is nested, so no generated field can take the
    place of a measured one however the schema grows."""
    document = json.loads(sitrep.model_dump_json())
    assert set(document) == {"zeitfenster", "quelle", "gesagt", "anwesend",
                             "handlungen", "aeusserungen", "pegel", "latenz_s", "bericht"}
    assert set(document["bericht"]) == {"verlauf", "beschreibung", "personen", "szene",
                                        "prognose", "empfehlung", "einschreiten"}


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
            report.Lagebericht(verlauf="", beschreibung="", personen=[], szene=bericht.szene,
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
    prompt = report._prompt(report.ANWEISUNG, "Guten Tag")
    assert "Transkript:\nGuten Tag" in prompt


def test_prompt_marks_silence_rather_than_leaving_it_blank():
    assert "(keine Sprache erkannt)" in report._prompt(report.ANWEISUNG, "")


def test_prompt_lists_who_is_present_and_how_certain_the_name_is():
    prompt = report._prompt(report.ANWEISUNG, "",
                            [report.Anwesend(name="Klara", erkannt=True),
                             report.Anwesend(name="Vielleicht: Jakob", erkannt=False)])
    assert "- Klara (erkannt)" in prompt
    assert "- Vielleicht: Jakob (vermutet)" in prompt


def test_prompt_tells_the_model_where_the_names_are_and_the_threshold():
    prompt = report._prompt(report.ANWEISUNG, "")
    assert "Schild ueber" in prompt
    assert f"ueber {report.SCHWELLE}" in prompt


def test_prompt_marks_an_empty_room_rather_than_leaving_it_blank():
    assert "(niemand erfasst)" in report._prompt(report.ANWEISUNG, "")


def test_prompt_puts_what_changes_least_first():
    """Ollama reuses its cache for an identical opening (live_sitrep_latency.md, fix 4)."""
    prompt = report._prompt(report.ANWEISUNG, "Klara: Raus!", [],
                            kontext="Abschnitte:\n- 20:00:00-20:00:30 ...",
                            werte="- Klara: risiko 4", anlass="Alarm")
    assert prompt.startswith(report.ANWEISUNG)
    after = len(report.ANWEISUNG)
    order = [prompt.index(part, after) for part in ("Anwesenheitsliste:\n", "Abschnitte:\n",
                                                    "Gemessen jetzt:\n", "Anlass:\n",
                                                    "Transkript:\n")]
    assert order == sorted(order)


def test_the_report_and_the_recommendation_share_their_opening():
    assert report.ANWEISUNG.startswith(report.QUELLEN)
    assert report.ANWEISUNG_EMPFEHLUNG.startswith(report.QUELLEN)


T0 = datetime(2026, 9, 29, 20, 0, 0)


def line(text, seconds, name="Klara", **fields):
    at = T0 + timedelta(seconds=seconds)
    return report.Aeusserung(name=name, text=text, beginn=at, ende=at + timedelta(seconds=2),
                             **fields)


def test_a_report_asked_for_reads_the_chronik_and_the_last_lines(monkeypatch, bericht):
    given = {}

    def analyse(frames, transcript, anwesend, model=None, kontext="", werte=""):
        given.update(frames=frames, transcript=transcript, anwesend=anwesend,
                     kontext=kontext, werte=werte)
        return bericht

    monkeypatch.setattr(report, "analyse", analyse)
    lines = [line("Du lügst.", 10), line("Raus hier!", 20, name=None, lautstaerke="geschrien")]
    anwesend = [report.Anwesend(name="Klara", erkannt=True)]

    document = report.bericht(beginn=T0, ende=T0 + timedelta(seconds=300), frames=[b"a", b"b"],
                              aeusserungen=lines, anwesend=anwesend,
                              kontext="Rueckblick ...", werte="- Klara: risiko 2",
                              abschnitte=9)

    assert given == {"frames": [b"a", b"b"],
                     "transcript": "Klara: Du lügst.\n(unklar) (geschrien): Raus hier!",
                     "anwesend": anwesend, "kontext": "Rueckblick ...",
                     "werte": "- Klara: risiko 2"}
    assert document.zeitfenster.dauer_s == 300.0
    assert document.quelle == report.Quelle(bilder=2, abschnitte=9, woertlich_s=4.0)
    assert document.gesagt == "Du lügst. Raus hier!"
    assert document.aeusserungen == lines
    assert document.bericht is bericht


def test_a_reports_latency_runs_from_the_request(monkeypatch, bericht):
    monkeypatch.setattr(report, "analyse", lambda *args, **kwargs: bericht)
    document = report.bericht(beginn=T0, ende=T0, frames=[], aeusserungen=[],
                              started=report.time.monotonic() - 3.0)
    assert document.latenz_s >= 3.0


def test_the_report_carries_the_loudness_calibration_as_it_stands(monkeypatch, bericht):
    monkeypatch.setattr(report, "analyse", lambda *args, **kwargs: bericht)
    laut = loudness.Calibration(seconds=120, provisional=30)
    laut.learn(-30.0, 40.0)
    document = report.bericht(beginn=T0, ende=T0, frames=[], aeusserungen=[], laut=laut)
    assert document.pegel.kalibriert and not document.pegel.endgueltig
    assert document.pegel.gehoert_s == 40.0


class Reply:
    def __init__(self, content):
        self.message = type("Message", (), {"content": content})()


def test_a_recommendation_reads_the_anlass_and_follows_the_threshold(monkeypatch):
    asked = {}

    def chat(**request):
        asked.update(request)
        return Reply(json.dumps({"lage": "Klara bedroht Jakob.",
                                 "szene": {"relevanz": 8, "eskalation": 8, "gefahr": 5},
                                 "empfehlung": "Probe unterbrechen."}))

    monkeypatch.setattr(report, "chat", chat)
    empfehlung = report.empfehlen(anlass="Alarm: Klara, Risiko 4.", frames=[b"a"],
                                  aeusserungen=[line("Ich bring dich um.", 0)],
                                  kontext="Abschnitte: ...", werte="- Klara: risiko 4")

    prompt = asked["messages"][0]["content"]
    assert "Anlass:\nAlarm: Klara, Risiko 4." in prompt
    assert "Klara: Ich bring dich um." in prompt
    assert asked["options"]["num_predict"] == report.EMPFEHLUNG_TOKENS
    assert empfehlung.urteil.einschreiten
    assert empfehlung.urteil.empfehlung == "Probe unterbrechen."
    assert empfehlung.anlass == "Alarm: Klara, Risiko 4."


def test_a_recommendation_below_the_threshold_carries_no_measure():
    urteil = report.Urteil(lage="Ruhig.", szene=report.Szene(relevanz=2, eskalation=6, gefahr=6),
                           empfehlung="Beobachten.")
    assert not urteil.einschreiten
    assert urteil.empfehlung == ""


def test_the_model_is_not_asked_whether_a_recommendation_intervenes():
    assert "einschreiten" not in report.Urteil.model_json_schema()["properties"]


def test_reports_wait_behind_recommendations_and_lines_at_the_model():
    assert report.llm.ZEILEN < report.llm.EMPFEHLUNG < report.llm.BERICHT < report.llm.CHRONIK


def test_a_line_that_stood_out_is_marked_for_the_model():
    at = datetime(2026, 9, 28, 20, 0, 0)
    lines = [report.Aeusserung(name="Klara", text="Raus!", beginn=at, ende=at,
                               lautstaerke="geschrien"),
             report.Aeusserung(text="Ja.", beginn=at, ende=at)]
    assert report.protokoll(lines) == "Klara (geschrien): Raus!\n(unklar): Ja."


def test_the_schema_lists_each_person_at_most_once():
    """Without the cap the model was seen to list "Unbekannt" until the token
    cap cut the reply off."""
    anwesend = [report.Anwesend(name="Klara", erkannt=True)]
    assert report.schema(anwesend)["properties"]["personen"]["maxItems"] == 2
