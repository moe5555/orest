"""Speech rated per line, and combined with actions by maximum.

Needs no model: Ollama's reply is supplied by hand.
"""

import json
from datetime import datetime
from types import SimpleNamespace

import pytest
from ollama import ResponseError

from sitrep import report, speech

T0 = datetime(2026, 9, 28, 20, 0, 0)


def line(name, text, **rated) -> report.Aeusserung:
    return report.Aeusserung(name=name, text=text, beginn=T0, ende=T0, **rated)


def reply(*readings) -> SimpleNamespace:
    return SimpleNamespace(message=SimpleNamespace(content=json.dumps({"zeilen": [
        {"begruendung": reason, "risiko": risiko, "menschlichkeit": menschlichkeit}
        for reason, risiko, menschlichkeit in readings]})))


def test_the_reason_comes_before_the_scores_in_the_schema():
    """The model writes fields in schema order, so it reasons before it scores."""
    fields = list(speech.schema(2)["$defs"]["Einschaetzung"]["properties"])
    assert fields[0] == "begruendung"


def test_the_schema_holds_the_model_to_one_reading_per_line():
    zeilen = speech.schema(3)["properties"]["zeilen"]
    assert (zeilen["minItems"], zeilen["maxItems"]) == (3, 3)


def test_the_prompt_asks_for_a_literal_reading_with_the_examples():
    text = speech.prompt([line("Klara", "Ich hasse dich."), line(None, "Äh.")])
    assert "ernst gemeint" in text and "Redewendungen" in text
    assert '"Ich hasse dich." risiko 3, menschlichkeit -3' in text
    assert "1. Klara: Ich hasse dich.\n2. (unklar): Äh." in text


def test_each_line_gets_its_reading(monkeypatch):
    asked = {}

    def chat(**request):
        asked.update(request)
        return reply(("Hass auf das Gegenueber.", 3, -3), ("Fuellwort.", 0, 0))

    monkeypatch.setattr(speech, "chat", chat)
    rated = speech.rate([line("Klara", "Ich hasse dich."), line(None, "Äh.")])
    assert [(item.risiko, item.menschlichkeit) for item in rated] == [(3, -3), (0, 0)]
    assert rated[0].begruendung == "Hass auf das Gegenueber."
    # The report's context size, so Ollama keeps one loaded model for both.
    assert asked["options"]["num_ctx"] == report.CONTEXT
    assert "images" not in asked["messages"][0]


def test_a_failed_rating_leaves_the_lines_unrated(monkeypatch, capsys):
    def chat(**request):
        raise ResponseError("model not found")

    monkeypatch.setattr(speech, "chat", chat)
    lines = [line("Klara", "Ich hasse dich.")]
    assert speech.rate(lines) == lines
    assert "speech rating skipped" in capsys.readouterr().err


def test_no_lines_need_no_request(monkeypatch):
    monkeypatch.setattr(speech, "chat", lambda **request: pytest.fail("no request expected"))
    assert speech.rate([]) == []


def test_the_example_table_parses():
    assert speech.examples().count("\n") >= 5


# ---- combined with actions ------------------------------------------------------

def test_a_threat_raises_risiko_above_a_calm_body(sitrep):
    """Klara's body read risiko 0; her words say 3. The higher one counts."""
    document = sitrep.model_copy(update={"aeusserungen": [
        line("Klara", "Ich hasse dich.", begruendung="Hass.", risiko=3, menschlichkeit=-3)]})
    klara = document.bericht.personen[0]
    assert document.bewertungen(klara)["risiko"] == 3
    assert document.bewertung("Klara", "risiko") == (3, "„Ich hasse dich.“: Hass.")
    # Her action reading of menschlichkeit 4 still beats the insult.
    assert document.bewertungen(klara)["menschlichkeit"] == 4


def test_speech_alone_gives_a_person_measured_ratings(sitrep):
    """Jakob's body was never read; what he said still counts, clipped to 0-5."""
    document = sitrep.model_copy(update={"aeusserungen": [
        line("Jakob", "Beruhig dich.", begruendung="Beruhigt.", risiko=-2,
             menschlichkeit=2)]})
    jakob = document.bericht.personen[1]
    assert document.bewertungen(jakob)["risiko"] == 0
    assert document.bewertungen(jakob)["menschlichkeit"] == 2


def test_an_unattributed_line_counts_for_no_one(sitrep):
    document = sitrep.model_copy(update={"aeusserungen": [
        line(None, "Ich bring dich um.", risiko=5, menschlichkeit=-3)]})
    jakob = document.bericht.personen[1]
    assert document.bewertungen(jakob)["risiko"] is None
