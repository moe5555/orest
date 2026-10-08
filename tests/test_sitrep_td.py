"""The SITREP and roster messages TouchDesigner lays out as tables.

A wrong column order reaches TouchDesigner as a plausible table with the
ratings shifted, not as an error, so the order is pinned here rather than
discovered on stage. Needs no camera, model or TouchDesigner.
"""

import threading
from datetime import datetime, timedelta

import pytest
from pythonosc.dispatcher import Dispatcher
from pythonosc.osc_server import BlockingOSCUDPServer

from sitrep import chronik, lage, presence, report
from sitrep import td as sitrep_td

AT = datetime(2026, 9, 24, 19, 30, 0)


def addresses(built):
    return [address for address, _ in built]


def only(built, address):
    return [arguments for sent, arguments in built if sent == address]


def test_a_report_is_framed_by_a_begin_and_an_end(sitrep):
    built = sitrep_td.messages(sitrep, 1)
    assert addresses(built)[0] == sitrep_td.SITREP_BEGIN
    assert addresses(built)[-1] == sitrep_td.SITREP_END


def test_begin_carries_the_window_its_material_and_the_row_counts(sitrep):
    arguments = only(sitrep_td.messages(sitrep, 7), sitrep_td.SITREP_BEGIN)[0]
    assert arguments[1] == 7
    assert arguments[2].startswith("2026-09-10T14:30:00")
    assert arguments[4] == sitrep.zeitfenster.dauer_s
    assert arguments[5] == sitrep.quelle.bilder
    assert arguments[8] == len(sitrep.bericht.personen)
    assert arguments[9] == len(sitrep.bericht.prognose)


def test_begin_carries_how_much_of_the_chronik_the_report_read(sitrep):
    arguments = only(sitrep_td.messages(sitrep, 1), sitrep_td.SITREP_BEGIN)[0]
    assert arguments[6] == sitrep.quelle.abschnitte


def test_the_development_is_sent_before_the_description(sitrep):
    built = addresses(sitrep_td.messages(sitrep, 1))
    assert built.index(sitrep_td.SITREP_VERLAUF) < built.index(sitrep_td.SITREP_BESCHREIBUNG)
    assert only(sitrep_td.messages(sitrep, 1), sitrep_td.SITREP_VERLAUF)[0][1] == \
        sitrep.bericht.verlauf


def live_stand(aktiv=True):
    return lage.Stand(AT, {"Klara": {"risiko": lage.Wert(4, 4.0, "kicking other person 0.90", AT),
                                     "menschlichkeit": lage.Wert(0, 0.0)}},
                      lage.Alarm(aktiv, 4 if aktiv else 0, "Klara" if aktiv else None,
                                 "kicking other person 0.90" if aktiv else ""))


def test_the_live_values_are_framed_by_their_tick():
    built = sitrep_td.werte_messages(live_stand(), 12)
    assert addresses(built) == [sitrep_td.LIVE_BEGIN, sitrep_td.LIVE_PERSON, sitrep_td.LIVE_END]
    assert only(built, sitrep_td.LIVE_BEGIN)[0][2:] == [1, 1, 4, "Klara",
                                                         "kicking other person 0.90"]
    assert only(built, sitrep_td.LIVE_PERSON)[0] == [12, 1, "Klara", 4, 0,
                                                      "kicking other person 0.90", "",
                                                      sitrep_td.NOT_MEASURED_SIGNED]


def test_no_alarm_is_sent_as_zero_with_nobody_named():
    begin = only(sitrep_td.werte_messages(live_stand(aktiv=False), 1), sitrep_td.LIVE_BEGIN)[0]
    assert begin[3:6] == [0, 0, ""]


def test_each_line_is_sent_as_transcribed_and_again_once_rated():
    lines = [report.Aeusserung(name=None, text="Raus!", beginn=AT, ende=AT, risiko=3,
                               menschlichkeit=-2, lautstaerke="geschrien"),
             report.Aeusserung(name="Klara", text="Ja.", beginn=AT, ende=AT)]
    built = sitrep_td.zeilen_messages(lines)
    assert only(built, sitrep_td.LIVE_ZEILE) == [
        ["2026-09-24T19:30:00", "2026-09-24T19:30:00", "", "Raus!", "geschrien", 3, -2, 1],
        ["2026-09-24T19:30:00", "2026-09-24T19:30:00", "Klara", "Ja.", "", 0, 0, 1]]
    unrated = only(sitrep_td.zeilen_messages(lines[1:], bewertet=False), sitrep_td.LIVE_ZEILE)
    assert unrated[0][-1] == 0


def test_a_summarised_stretch_is_one_message():
    abschnitt = chronik.Abschnitt(beginn=AT, ende=AT + timedelta(seconds=30),
                                  zusammenfassung=chronik.Zusammenfassung(
                                      zusammenfassung="Streit.", tendenz="zuspitzend",
                                      szene=report.Szene(relevanz=5, eskalation=6, gefahr=2)))
    [(address, arguments)] = sitrep_td.abschnitt_messages(abschnitt)
    assert address == sitrep_td.CHRONIK_ABSCHNITT
    assert arguments[2:] == [6, 2, "zuspitzend", "Streit."]
    unsummarised = abschnitt.model_copy(update={"zusammenfassung": None})
    assert sitrep_td.abschnitt_messages(unsummarised)[0][1][2:4] == [-1, -1]


def test_a_recommendation_is_one_message_with_its_flag():
    empfehlung = report.Empfehlung(zeit=AT, anlass="Alarm", latenz_s=1.2, urteil=report.Urteil(
        lage="Drohung.", empfehlung="Probe unterbrechen.",
        szene=report.Szene(relevanz=8, eskalation=8, gefahr=4)))
    [(address, arguments)] = sitrep_td.empfehlung_messages(empfehlung, 3)
    assert address == sitrep_td.LIVE_EMPFEHLUNG
    assert arguments == [3, "2026-09-24T19:30:00", 1, 8, 4, "Drohung.", "Probe unterbrechen.",
                         "Alarm", 1.2]


def test_every_person_and_every_forecast_becomes_one_row(sitrep):
    built = sitrep_td.messages(sitrep, 1)
    assert len(only(built, sitrep_td.SITREP_PERSON)) == len(sitrep.bericht.personen)
    assert len(only(built, sitrep_td.SITREP_PROGNOSE)) == len(sitrep.bericht.prognose)


def test_rows_are_numbered_from_one_in_document_order(sitrep):
    built = sitrep_td.messages(sitrep, 1)
    assert [arguments[1] for arguments in only(built, sitrep_td.SITREP_PERSON)] == [1, 2]
    assert [arguments[2] for arguments in only(built, sitrep_td.SITREP_PERSON)] == [
        person.name for person in sitrep.bericht.personen]


def test_a_person_row_marks_only_unbekannt_as_not_recognised(sitrep):
    unbekannt = report.Person(name=report.UNBEKANNT, beschreibung="")
    document = sitrep.model_copy(update={"bericht": sitrep.bericht.model_copy(update={
        "personen": [*sitrep.bericht.personen, unbekannt]})})
    rows = only(sitrep_td.messages(document, 1), sitrep_td.SITREP_PERSON)
    assert [row[3] for row in rows] == [0, 0, 1]


def test_forecasts_are_ranked_most_likely_first(sitrep):
    rows = only(sitrep_td.messages(sitrep, 1), sitrep_td.SITREP_PROGNOSE)
    assert [row[1] for row in rows] == [1, 2, 3]
    assert [row[2] for row in rows] == [60, 20, 15]
    assert rows[0][3] == "Fortsetzung der Szene."


def test_the_recommendation_is_one_row_with_a_flag(sitrep, eskaliert):
    rows = only(sitrep_td.messages(sitrep, 1), sitrep_td.SITREP_EMPFEHLUNG)
    assert rows == [[rows[0][0], 0, ""]]

    intervening = sitrep.model_copy(update={"bericht": eskaliert})
    row = only(sitrep_td.messages(intervening, 1), sitrep_td.SITREP_EMPFEHLUNG)[0]
    assert row[1:] == [1, "Probe unterbrechen."]


def test_the_scene_ratings_are_one_row(sitrep):
    row = only(sitrep_td.messages(sitrep, 1), sitrep_td.SITREP_SZENE)[0]
    assert row[1:] == [6, 3, 2]


def test_the_description_is_sent_on_its_own(sitrep):
    row = only(sitrep_td.messages(sitrep, 1), sitrep_td.SITREP_BESCHREIBUNG)[0]
    assert row[1] == sitrep.bericht.beschreibung


def test_a_person_row_carries_the_ratings_in_the_order_bewertungen_names(sitrep):
    """Renaming a category must fail here rather than silently shift a column
    in TouchDesigner."""
    person = sitrep.bericht.personen[0]
    arguments = only(sitrep_td.messages(sitrep, 1), sitrep_td.SITREP_PERSON)[0]
    assert arguments[-len(report.BEWERTUNGEN):] == list(sitrep.bewertungen(person).values())
    assert arguments[-1] == -2


def test_a_rating_that_was_not_measured_is_sent_as_a_marker_off_its_scale(sitrep):
    """-1 is off the 0-5 scales but a value of Vorhersehbarkeit's -5 to +5."""
    jakob = only(sitrep_td.messages(sitrep, 1), sitrep_td.SITREP_PERSON)[1]
    assert jakob[-len(report.BEWERTUNGEN):] == [
        sitrep_td.NICHT_GEMESSEN, sitrep_td.NICHT_GEMESSEN, sitrep_td.NOT_MEASURED_SIGNED]


def test_one_report_shares_one_id(sitrep):
    built = sitrep_td.messages(sitrep, 1)
    assert len({arguments[0] for _, arguments in built}) == 1


def test_two_reports_do_not_share_an_id(sitrep):
    first = sitrep_td.messages(sitrep, 1)[0][1][0]
    second = sitrep_td.messages(sitrep, 2)[0][1][0]
    assert first != second


def test_the_transcript_is_sent_even_when_nothing_was_said(sitrep):
    """The table keeps its shape whether or not the room spoke."""
    silent = sitrep.model_copy(update={"gesagt": ""})
    assert only(sitrep_td.messages(silent, 1), sitrep_td.SITREP_GESAGT)[0][1] == ""


def person(label="klara", name="klara", similarity=0.72, sightings=9,
           seconds=4.0) -> presence.Presence:
    return presence.Presence(
        label=label, name=name, similarity=similarity,
        sightings=sightings, first_seen=AT, last_seen=AT + timedelta(seconds=seconds))


def test_a_roster_reading_is_framed_by_its_tick():
    built = sitrep_td.roster_messages([person()], 4, AT)
    assert addresses(built) == [sitrep_td.PRESENCE_BEGIN,
                                sitrep_td.PRESENCE_PERSON,
                                sitrep_td.PRESENCE_END]
    assert {arguments[0] for _, arguments in built} == {4}


def test_a_roster_begin_counts_the_people_in_the_room():
    built = sitrep_td.roster_messages([person(), person()], 1, AT)
    assert only(built, sitrep_td.PRESENCE_BEGIN)[0][2] == 2


def test_a_recognised_person_carries_their_name():
    arguments = only(sitrep_td.roster_messages([person()], 1, AT),
                     sitrep_td.PRESENCE_PERSON)[0]
    assert arguments[2] == "klara"
    assert arguments[3] == "klara"
    assert arguments[4] == 0


def test_an_unrecognised_face_is_left_off_the_roster():
    unrecognised = person(label="#4", name=None, similarity=0.0)
    built = sitrep_td.roster_messages([person(), unrecognised], 1, AT)
    assert only(built, sitrep_td.PRESENCE_BEGIN)[0][2] == 1
    assert [arguments[2] for arguments in only(built, sitrep_td.PRESENCE_PERSON)] == ["klara"]


def test_a_roster_row_carries_how_long_the_person_has_been_seen():
    arguments = only(sitrep_td.roster_messages([person(seconds=12.0)], 1, AT),
                     sitrep_td.PRESENCE_PERSON)[0]
    assert arguments[6] == 9
    assert arguments[8] == 12.0


class StubTracker:
    def __init__(self, roster):
        self._roster = roster

    def roster(self):
        return self._roster


class RecordingSender:
    def __init__(self):
        self.sent = []

    def send(self, message):
        self.sent.append(message)

    def send_all(self, messages):
        for message in messages:
            self.send(message)


def test_roster_ticks_increase():
    sender = RecordingSender()
    stream = sitrep_td.RosterStream(sender, StubTracker([person()]))
    stream.publish()
    stream.publish()
    ticks = [arguments[0] for address, arguments in sender.sent
             if address == sitrep_td.PRESENCE_BEGIN]
    assert ticks == [1, 2]


def test_an_empty_room_still_sends_a_reading():
    """Silence has to be distinguishable from the stream having stopped."""
    sender = RecordingSender()
    sitrep_td.RosterStream(sender, StubTracker([])).publish()
    assert addresses(sender.sent) == [sitrep_td.PRESENCE_BEGIN, sitrep_td.PRESENCE_END]


@pytest.fixture
def receiver():
    """A loopback OSC server that collects one message."""
    received = []
    dispatcher = Dispatcher()
    dispatcher.map("/apollon/*",
                   lambda address, *arguments: received.append((address, list(arguments))))
    server = BlockingOSCUDPServer(("127.0.0.1", 0), dispatcher)
    thread = threading.Thread(target=server.handle_request)
    thread.start()
    yield server.server_address[1], received, thread
    server.server_close()


def test_a_person_row_arrives_over_udp_as_sent(receiver, sitrep):
    port, received, thread = receiver
    message = only(sitrep_td.messages(sitrep, 1), sitrep_td.SITREP_PERSON)[0]
    sitrep_td.Sender("127.0.0.1", port).send((sitrep_td.SITREP_PERSON, message))
    thread.join(timeout=5)

    address, arguments = received[0]
    assert address == sitrep_td.SITREP_PERSON
    assert arguments[2] == sitrep.bericht.personen[0].name
    assert arguments[-len(report.BEWERTUNGEN):] == message[-len(report.BEWERTUNGEN):]


def test_german_text_survives_the_round_trip(receiver):
    """The report is written in German; umlauts must reach TouchDesigner intact."""
    port, received, thread = receiver
    sitrep_td.Sender("127.0.0.1", port).send(
        (sitrep_td.SITREP_BESCHREIBUNG, ["q1","Persönliche Übergabe, dreißig Sekunden"]))
    thread.join(timeout=5)
    assert received[0][1][1] == "Persönliche Übergabe, dreißig Sekunden"
