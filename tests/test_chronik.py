"""The Chronik: stretches of the scene summarised as they pass, older ones folded."""

import json
from datetime import datetime, timedelta

import pytest
from ollama import ResponseError

from sitrep import chronik, report

T0 = datetime(2026, 9, 29, 20, 0, 0)


class Reply:
    def __init__(self, content):
        self.message = type("Message", (), {"content": content})()


def summary(eskalation=3, gefahr=1, tendenz="zuspitzend", text="Streit am Tisch."):
    return json.dumps({"zusammenfassung": text,
                       "szene": {"relevanz": 5, "eskalation": eskalation, "gefahr": gefahr},
                       "tendenz": tendenz})


def line(text, seconds, name="Klara"):
    at = T0 + timedelta(seconds=seconds)
    return report.Aeusserung(name=name, text=text, beginn=at - timedelta(seconds=1), ende=at)


class Requests(list):
    """Requests made, and the replies to give them in turn."""

    def __init__(self):
        super().__init__()
        self.replies = []


@pytest.fixture
def asked(monkeypatch):
    """Every request the Chronik makes, answered in turn from `asked.replies`."""
    requests = Requests()

    def chat(**request):
        requests.append(request)
        reply = requests.replies.pop(0) if requests.replies else summary()
        if isinstance(reply, Exception):
            raise reply
        return Reply(reply)

    monkeypatch.setattr(chronik, "chat", chat)
    return requests


def test_an_abschnitt_holds_what_its_stretch_held(asked):
    seen = {}

    def roster(since, until):
        seen["roster"] = (since, until)
        return [type("Presence", (), {"label": "Klara", "known": True})()]

    def handlungen(since, until):
        seen["handlungen"] = (since, until)
        return [report.Handlung(name="Klara", risiko=3, menschlichkeit=0,
                                anlass_risiko="pushing other person 0.70", lesungen=30)]

    def bilder(since, until, count):
        seen["bilder"] = (since, until, count)
        return [b"a", b"b"]

    kept = chronik.Chronik(laenge=30, roster=roster, handlungen=handlungen, bilder=bilder,
                           began=T0)
    kept.add([line("Vorher.", -5), line("Du lügst.", 10), line("Danach.", 40)])
    abschnitt = kept.schneiden(T0 + timedelta(seconds=30))

    span = (T0, T0 + timedelta(seconds=30))
    assert seen == {"roster": span, "handlungen": span, "bilder": (*span, chronik.BILDER)}
    assert [spoken.text for spoken in abschnitt.aeusserungen] == ["Du lügst."]
    assert abschnitt.anwesend == [report.Anwesend(name="Klara", erkannt=True)]
    assert abschnitt.bilder == 2
    assert abschnitt.zusammenfassung.szene.eskalation == 3
    prompt = asked[0]["messages"][0]["content"]
    assert "Klara: Du lügst." in prompt
    assert "risiko 3 (pushing other person 0.70)" in prompt
    assert asked[0]["messages"][0]["images"] == [b"a", b"b"]


def test_each_abschnitt_begins_where_the_last_ended(asked):
    kept = chronik.Chronik(laenge=30, began=T0)
    first = kept.schneiden(T0 + timedelta(seconds=30))
    second = kept.schneiden(T0 + timedelta(seconds=60))
    assert (first.ende, second.beginn) == (T0 + timedelta(seconds=30),) * 2
    assert kept.cut == T0 + timedelta(seconds=60)


def test_the_next_abschnitt_is_summarised_with_the_chronik_so_far(asked):
    kept = chronik.Chronik(laenge=30, began=T0)
    kept.schneiden(T0 + timedelta(seconds=30))
    kept.schneiden(T0 + timedelta(seconds=60))
    prompt = asked[1]["messages"][0]["content"]
    assert "20:00:00-20:00:30 · Eskalation 3 · Gefahr 1 · zuspitzend: Streit am Tisch." in prompt


def test_an_abschnitt_the_model_could_not_summarise_keeps_its_lines(asked):
    asked.replies.append(ResponseError("rejected"))
    kept = chronik.Chronik(laenge=30, began=T0)
    kept.add([line("Raus hier!", 10, name=None)])
    abschnitt = kept.schneiden(T0 + timedelta(seconds=30))
    assert abschnitt.zusammenfassung is None
    assert kept.kurve == []
    assert "(ohne Zusammenfassung): (unklar): Raus hier!" in kept.kontext()


def test_the_kurve_keeps_the_scenes_ratings_per_abschnitt(asked):
    asked.replies += [summary(eskalation=2), summary(eskalation=5, gefahr=3)]
    kept = chronik.Chronik(laenge=30, began=T0)
    kept.schneiden(T0 + timedelta(seconds=30))
    kept.schneiden(T0 + timedelta(seconds=60))
    assert [(punkt.eskalation, punkt.gefahr) for punkt in kept.kurve] == [(2, 1), (5, 3)]
    assert "Eskalation je Abschnitt seit 20:00:30: 2 5" in kept.kontext()


def test_old_abschnitte_are_folded_into_the_rueckblick_and_their_words_deleted(asked):
    kept = chronik.Chronik(laenge=30, began=T0)
    for index in range(chronik.FALTEN):
        kept.add([line(f"Zeile {index}.", 30 * index + 10)])
        kept.schneiden(T0 + timedelta(seconds=30 * (index + 1)))
    assert kept.rueckblick == ""

    asked.replies += [summary(), json.dumps({"rueckblick": "Streit, dann Versöhnung."})]
    now = T0 + timedelta(seconds=30 * chronik.FALTEN + chronik.DETAIL + 1)
    kept.add([line("Jetzt.", (now - T0).total_seconds() - 1)])
    kept.schneiden(now)

    fold = asked[-1]["messages"][0]["content"]
    assert fold.count("\n- 20:0") == chronik.FALTEN
    assert kept.rueckblick == "Streit, dann Versöhnung."
    assert (kept.rueckblick_von, kept.rueckblick_bis) == (
        T0, T0 + timedelta(seconds=30 * chronik.FALTEN))
    assert len(kept.abschnitte) == 1
    assert [spoken.text for spoken in kept.zeilen_seit(T0)] == ["Jetzt."]
    assert len(kept.kurve) == chronik.FALTEN + 1
    assert kept.kontext().startswith("Rueckblick 20:00:00-20:02:00:\nStreit, dann Versöhnung.")


def test_abschnitte_stay_in_detail_when_folding_fails(asked):
    kept = chronik.Chronik(laenge=30, began=T0)
    for index in range(chronik.FALTEN):
        kept.schneiden(T0 + timedelta(seconds=30 * (index + 1)))
    asked.replies += [summary(), ResponseError("rejected")]
    kept.schneiden(T0 + timedelta(seconds=30 * chronik.FALTEN + chronik.DETAIL + 1))
    assert kept.rueckblick == ""
    assert len(kept.abschnitte) == chronik.FALTEN + 1


def test_a_report_is_given_the_last_abschnitt_word_for_word(asked):
    kept = chronik.Chronik(laenge=30, began=T0)
    assert kept.woertlich_seit() == T0
    kept.schneiden(T0 + timedelta(seconds=30))
    kept.schneiden(T0 + timedelta(seconds=60))
    assert kept.woertlich_seit() == T0 + timedelta(seconds=30)
    assert kept.von() == T0


def test_the_summaries_wait_behind_every_other_request(asked, monkeypatch):
    turns = []
    real = chronik.llm.turn

    def turn(priority):
        turns.append(priority)
        return real(priority)

    monkeypatch.setattr(chronik.llm, "turn", turn)
    chronik.Chronik(laenge=30, began=T0).schneiden(T0 + timedelta(seconds=30))
    assert turns == [chronik.llm.CHRONIK]


def test_a_line_rated_later_takes_the_place_of_the_line_as_transcribed():
    kept = chronik.Chronik(laenge=30, began=T0)
    transcribed = line("Du lügst.", 10)
    kept.add([transcribed])
    rated = transcribed.model_copy(update={"risiko": 2, "menschlichkeit": -2})
    kept.add([rated])
    assert kept.zeilen_seit(T0) == [rated]


def test_clearing_deletes_everything_kept(asked):
    kept = chronik.Chronik(laenge=30, began=T0)
    kept.add([line("Du lügst.", 10)])
    kept.schneiden(T0 + timedelta(seconds=30))
    kept.clear()
    assert (kept.zeilen_seit(T0), kept.abschnitte, kept.kurve, kept.rueckblick) == ([], [], [], "")
