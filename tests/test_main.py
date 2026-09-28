"""Console rendering of a SITREP."""

import re

from sitrep import main, report

ANSI_PATTERN = re.compile(r"\033\[[0-9;]*m")


def test_wrap_fits_the_column():
    text = "Zwei Personen im Raum, Probenarbeit an einer Szene."
    assert all(len(line) <= 20 for line in main._wrap(text, 20))


def test_wrap_collapses_whitespace_from_the_model():
    assert main._wrap("Erste  Zeile\nZweite Zeile", 40) == ["Erste Zeile Zweite Zeile"]


def test_wrap_keeps_a_long_word_intact():
    assert main._wrap("Verantwortungsbewusstsein", 10) == ["Verantwortungsbewusstsein"]


def test_wrap_of_empty_text_produces_no_lines():
    assert main._wrap("", 40) == []


def test_plain_output_carries_no_escape_codes(sitrep):
    assert not ANSI_PATTERN.search(main.format_sitrep(sitrep, use_colour=False))


def test_colour_output_carries_escape_codes(sitrep):
    assert ANSI_PATTERN.search(main.format_sitrep(sitrep, use_colour=True))


def test_block_shows_the_window_as_clock_times(sitrep):
    block = main.format_sitrep(sitrep, use_colour=False)
    assert "14:30:00 – 14:30:30" in block
    assert "(30.0s)" in block


def test_block_labels_every_populated_field(sitrep):
    block = main.format_sitrep(sitrep, use_colour=False)
    for label in ("BESCHREIBUNG", "PERSONEN", "GESAGT", "PROGNOSE", "EMPFEHLUNG"):
        assert label in block


def test_block_omits_the_transcript_when_nothing_was_said(sitrep):
    silent = sitrep.model_copy(update={"gesagt": ""})
    assert "GESAGT" not in main.format_sitrep(silent, use_colour=False)


def test_block_lists_every_person_with_every_rating(sitrep):
    block = main.format_sitrep(sitrep, use_colour=False)
    assert "Klara" in block and "Vielleicht: Jakob" in block
    for name in ("risiko", "menschlichkeit", "auffaelligkeit"):
        assert name in block


def test_block_shows_an_unmeasured_rating_as_a_dash(sitrep):
    block = main.format_sitrep(sitrep, use_colour=False)
    assert "risiko – · menschlichkeit – · auffaelligkeit 4" in block


def test_block_names_the_action_behind_a_measured_rating(sitrep):
    block = main.format_sitrep(sitrep, use_colour=False)
    assert "menschlichkeit: hugging other person 0.81" in block
    # A rating of 0 has no cause to show.
    assert "risiko:" not in block


def test_block_marks_a_guessed_name_and_not_a_recognised_one(sitrep):
    lines = main.format_sitrep(sitrep, use_colour=False).splitlines()
    assert any(line.rstrip().endswith("Vielleicht: Jakob (vermutet)") for line in lines)
    assert not any("Klara (vermutet)" in line for line in lines)


def test_block_does_not_call_an_unknown_person_a_guess(sitrep):
    bericht = sitrep.bericht.model_copy(update={"personen": [
        sitrep.bericht.personen[0].model_copy(update={"name": report.UNBEKANNT})]})
    block = main.format_sitrep(sitrep.model_copy(update={"bericht": bericht}),
                               use_colour=False)
    assert "Unbekannt" in block
    assert "(vermutet)" not in block


def test_block_shows_the_forecasts_most_likely_first_with_percentages(sitrep):
    block = main.format_sitrep(sitrep, use_colour=False)
    assert block.index(" 60 % Fortsetzung") < block.index(" 20 % Unterbrechung")
    assert block.index(" 20 % Unterbrechung") < block.index(" 15 % Wechsel")


def test_block_says_so_when_no_intervention_is_recommended(sitrep):
    assert "Kein Einschreiten" in main.format_sitrep(sitrep, use_colour=False)


def test_block_shows_the_measure_when_intervention_is_recommended(sitrep, eskaliert):
    block = main.format_sitrep(sitrep.model_copy(update={"bericht": eskaliert}),
                               use_colour=False)
    assert "EINSCHREITEN" in block
    assert "Probe unterbrechen." in block


def test_block_shows_the_scene_ratings(sitrep):
    block = main.format_sitrep(sitrep, use_colour=False)
    assert "relevanz 6 · eskalation 3 · gefahr 2" in block


def test_a_scene_rating_above_the_threshold_is_red():
    assert main._szene_colour(report.SCHWELLE + 1) == "red"
    assert main._szene_colour(report.SCHWELLE) == "amber"
    assert main._szene_colour(0) == "dim"


def test_footer_reports_the_source_and_the_latency(sitrep):
    block = main.format_sitrep(sitrep, use_colour=False)
    assert "3 Bilder" in block
    assert "30.0s Ton" in block
    assert "Latenz 5.8s" in block


def test_block_stays_within_the_requested_width(sitrep):
    for line in main.format_sitrep(sitrep, width=78, use_colour=False).splitlines():
        assert len(line) <= 78


def test_high_risiko_is_coloured_red():
    assert main._risiko_colour(5) == "red"
    assert main._risiko_colour(2) == "amber"
    assert main._risiko_colour(0) == "dim"


def test_block_lists_each_line_with_its_speaker(sitrep):
    at = sitrep.zeitfenster.beginn
    document = sitrep.model_copy(update={"aeusserungen": [
        report.Aeusserung(name="Klara", text="Noch einmal.", beginn=at, ende=at),
        report.Aeusserung(text="Von vorne.", beginn=at, ende=at)]})
    block = main.format_sitrep(document, use_colour=False)
    assert "Klara: “Noch einmal.”" in block
    assert "(unklar): “Von vorne.”" in block


def test_block_shows_a_lines_evidence(sitrep):
    at = sitrep.zeitfenster.beginn
    document = sitrep.model_copy(update={"aeusserungen": [
        report.Aeusserung(name="Klara", text="Ich hasse dich.", beginn=at, ende=at,
                          risiko=3, menschlichkeit=-3),
        report.Aeusserung(name="Klara", text="Äh.", beginn=at, ende=at,
                          risiko=0, menschlichkeit=0)]})
    block = main.format_sitrep(document, use_colour=False)
    assert "“Ich hasse dich.” [risiko +3, menschlichkeit -3]" in block
    assert "“Äh.”\n" in block + "\n" and "“Äh.” [" not in block


def test_block_shows_the_loudness_calibration_and_a_lines_gain(sitrep):
    at = sitrep.zeitfenster.beginn
    document = sitrep.model_copy(update={
        "pegel": report.Pegel(kalibriert=True, endgueltig=True, gehoert_s=120.0,
                              normal_db=-31.2, streuung_db=4.1),
        "aeusserungen": [report.Aeusserung(name="Klara", text="Raus!", beginn=at, ende=at,
                                           risiko=2, menschlichkeit=-1, verstaerkung=1.5)]})
    block = main.format_sitrep(document, use_colour=False)
    assert "Pegel normal -31 dBFS ±4" in block
    assert "[risiko +2 ×1.5, menschlichkeit -1]" in block
