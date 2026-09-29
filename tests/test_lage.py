"""The live values: decaying evidence per person, and the alarm raised by rule."""

from datetime import datetime, timedelta

import numpy as np
import pytest

from sitrep import actions, lage, report

T0 = datetime(2026, 9, 29, 20, 0, 0)


def evidence(at, risiko=0.0, menschlichkeit=0.0, members=(1,), cause="kicking other person 0.90"):
    return actions.Evidence(at, members, np.array([risiko, menschlichkeit]), (cause, cause))


def line(text, at, name="Klara", risiko=0, menschlichkeit=0, verstaerkung=1.0):
    return report.Aeusserung(name=name, text=text, beginn=at - timedelta(seconds=1), ende=at,
                             risiko=risiko, menschlichkeit=menschlichkeit,
                             verstaerkung=verstaerkung, begruendung="Drohung.")


def test_evidence_counts_half_after_one_half_life():
    assert lage.abklingen(4.0, T0, T0) == 4.0
    assert lage.abklingen(4.0, T0, T0 + timedelta(seconds=lage.HALBWERTSZEIT)) == pytest.approx(2.0)
    assert lage.abklingen(-3.0, T0, T0) == 0.0


def test_a_blow_shows_at_once_and_falls_back_as_the_moment_passes():
    readings = [evidence(T0, risiko=5.0)]
    names = {1: "Klara"}
    now = lage.stand(readings, names, [], T0)
    assert now.personen["Klara"]["risiko"].wert == 5
    assert now.personen["Klara"]["risiko"].anlass == "kicking other person 0.90"
    later = lage.stand(readings, names, [], T0 + timedelta(seconds=2 * lage.HALBWERTSZEIT))
    assert later.personen["Klara"]["risiko"].wert == 1


def test_a_person_is_rated_on_the_strongest_of_actions_and_lines():
    readings = [evidence(T0, risiko=1.0, menschlichkeit=4.0)]
    lines = [line("Ich bring dich um.", T0, risiko=4, menschlichkeit=-3)]
    werte = lage.stand(readings, {1: "Klara"}, lines, T0).personen["Klara"]
    assert (werte["risiko"].wert, werte["menschlichkeit"].wert) == (4, 4)
    assert werte["risiko"].anlass.startswith("„Ich bring dich um.“")


def test_loudness_amplifies_the_risiko_of_a_line():
    lines = [line("Raus!", T0, risiko=2, verstaerkung=2.0)]
    assert lage.stand([], {}, lines, T0).personen["Klara"]["risiko"].wert == 4


def test_loudness_amplifies_the_risiko_of_an_action():
    readings = [evidence(T0, risiko=2.0)]
    stand = lage.stand(readings, {1: "Klara"}, [], T0, gain=lambda begins, ends: 1.5)
    assert stand.personen["Klara"]["risiko"].wert == 3
    assert "laut ×1.5" in stand.personen["Klara"]["risiko"].anlass


def test_a_body_without_a_name_is_not_rated():
    assert lage.stand([evidence(T0, risiko=5.0, members=(7,))], {1: "Klara"}, [], T0).personen == {}


def test_the_alarm_is_raised_by_a_persons_risiko():
    stand = lage.stand([evidence(T0, risiko=3.0)], {1: "Klara"}, [], T0)
    assert stand.alarm == lage.Alarm(True, 3, "Klara", "kicking other person 0.90")
    calm = lage.stand([evidence(T0, risiko=2.0)], {1: "Klara"}, [], T0)
    assert not calm.alarm.aktiv


def test_a_threat_of_unknown_speaker_raises_the_alarm_without_rating_anyone():
    """Most lines on the corpus stay unattributed; a threat is a threat still."""
    stand = lage.stand([], {}, [line("Ich bring dich um.", T0, name=None, risiko=4)], T0)
    assert stand.personen == {}
    assert stand.alarm.aktiv and stand.alarm.wer is None and stand.alarm.wert == 4


def test_an_unrated_line_counts_for_nothing():
    unrated = report.Aeusserung(name="Klara", text="…", beginn=T0, ende=T0)
    assert lage.stand([], {}, [unrated], T0).personen == {}


def test_what_an_operator_sees_changes_only_with_whole_numbers():
    readings = [evidence(T0, risiko=4.0)]
    names = {1: "Klara"}
    first = lage.stand(readings, names, [], T0 + timedelta(seconds=1))
    second = lage.stand(readings, names, [], T0 + timedelta(seconds=2))
    assert first.gerundet() == second.gerundet()
    assert first.personen["Klara"]["risiko"].staerke != second.personen["Klara"]["risiko"].staerke


def test_the_model_reads_the_values_with_their_cause_and_age():
    stand = lage.stand([evidence(T0, risiko=4.0)], {1: "Klara"}, [], T0 + timedelta(seconds=5))
    assert stand.beschreiben() == ("- Klara: risiko 3 (kicking other person 0.90, vor 5 s), "
                                   "menschlichkeit 0")
    assert lage.stand([], {}, [], T0).beschreiben() == "(niemand gemessen)"


def test_the_live_values_read_only_the_recent_past():
    asked = {}

    def readings(since):
        asked["readings"] = since
        return [], {}

    def lines(since):
        asked["lines"] = since
        return []

    lage.Lage(readings, lines).jetzt(T0)
    horizon = T0 - timedelta(seconds=lage.HORIZONT * lage.HALBWERTSZEIT)
    assert asked == {"readings": horizon, "lines": horizon}
