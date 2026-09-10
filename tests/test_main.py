"""Console rendering of a SITREP."""

import re

from sitrep import main

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
    for label in ("LAGE", "PERSONEN", "EREIGNIS", "GESAGT", "PROGNOSE", "EMPFEHLUNG"):
        assert label in block


def test_block_omits_the_transcript_when_nothing_was_said(sitrep):
    silent = sitrep.model_copy(update={"gesagt": ""})
    assert "GESAGT" not in main.format_sitrep(silent, use_colour=False)


def test_block_lists_every_person_with_every_rating(sitrep):
    block = main.format_sitrep(sitrep, use_colour=False)
    assert "P-01" in block and "P-02" in block
    for name in ("verantwortungsvoll", "menschlich", "gefahr", "kollaborativ"):
        assert name in block


def test_block_omits_merkmale_that_the_model_left_empty(sitrep):
    block = main.format_sitrep(sitrep, use_colour=False)
    assert "Dunkles Hemd, kurze Haare" in block
    # P-02 has no merkmale; its rating line must still follow its activity.
    assert "Sitzt am Tisch, notiert" in block


def test_footer_reports_the_source_and_the_latency(sitrep):
    block = main.format_sitrep(sitrep, use_colour=False)
    assert "3 Bilder" in block
    assert "30.0s Ton" in block
    assert "Latenz 5.8s" in block
    assert "Vertrauen 3/5" in block


def test_block_stays_within_the_requested_width(sitrep):
    for line in main.format_sitrep(sitrep, width=78, use_colour=False).splitlines():
        assert len(line) <= 78


def test_high_gefahr_is_coloured_red():
    assert main._gefahr_colour(5) == "red"
    assert main._gefahr_colour(2) == "amber"
    assert main._gefahr_colour(0) == "dim"
