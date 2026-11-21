"""A scene's text: passages annotated, carried over to a revised text, and
recognised as they are said."""

from datetime import datetime, timedelta

import pytest

from sitrep import report, scenetext

T0 = datetime(2026, 11, 21, 20, 0, 0)

TEXT = ("ORESTES: Ich bin gekommen, um den Vater zu rächen.\n"
        "ELEKTRA: So geh und tu, was getan werden muss.\n"
        "ORESTES: Ich bin gekommen.\n")


def said(text, at, name="Orestes"):
    return report.Aeusserung(name=name, text=text, beginn=at - timedelta(seconds=2), ende=at)


def annotated(passage, values=None, text=TEXT, occurrence=0):
    held = scenetext.SceneText(text=text)
    start = -1
    for _ in range(occurrence + 1):
        start = text.index(passage, start + 1)
    held.annotate(start, start + len(passage),
                  {"Orestes": {"risiko": 4}} if values is None else values)
    return held


def test_a_passage_is_annotated_without_the_white_space_around_it():
    held = scenetext.SceneText(text=TEXT)
    start = TEXT.index("So geh")
    annotation = held.annotate(start - 1, start + len("So geh und tu"), {"Elektra": {"risiko": 2}})
    assert annotation.text == "So geh und tu"
    assert annotation.summary() == "Elektra: Risiko 2"


def test_an_overlapping_or_misplaced_passage_is_refused():
    held = annotated("um den Vater zu rächen")
    with pytest.raises(ValueError):
        held.annotate(TEXT.index("Vater"), TEXT.index("Vater") + 5, {})
    with pytest.raises(ValueError):
        held.annotate(len(TEXT) + 1, len(TEXT) + 5, {})
    with pytest.raises(ValueError):
        held.annotate(0, 7, {"Orestes": {"risiko": 9}})


def test_a_revised_text_keeps_the_annotations_of_unchanged_passages():
    held = annotated("um den Vater zu rächen")
    held.annotate(TEXT.index("So geh"), TEXT.index("So geh") + 6, {"Elektra": {"menschlichkeit": 3}})
    revised_text = "SZENE 3\n\n" + TEXT.replace("So geh", "Nun geh")
    revised, lost = scenetext.revise(held, revised_text)
    assert [annotation.text for annotation in revised.annotations] == ["um den Vater zu rächen"]
    [kept] = revised.annotations
    assert revised_text[kept.start:kept.end] == "um den Vater zu rächen"
    assert [annotation.text for annotation in lost] == ["So geh"]


def test_a_repeated_passage_keeps_its_annotation_where_its_surroundings_match():
    held = annotated("Ich bin gekommen", occurrence=1)
    revised_text = "Vorspiel.\n" + TEXT
    revised, lost = scenetext.revise(held, revised_text)
    [kept] = revised.annotations
    assert not lost
    assert kept.start == revised_text.rindex("Ich bin gekommen")


def test_a_passage_is_recognised_by_its_opening_words_across_two_lines():
    held = annotated("Ich bin gekommen, um den Vater zu rächen.")
    listener = scenetext.Listener()
    assert listener.heard([said("Ich bin gekommen", T0)], held.annotations) == []
    [cue] = listener.heard([said("um den Vater zu rechen", T0 + timedelta(seconds=3))],
                           held.annotations)
    assert cue.annotation.id == held.annotations[0].id


def test_a_passage_is_recognised_once_while_its_lines_are_heard():
    held = annotated("um den Vater zu rächen")
    listener = scenetext.Listener()
    line = said("Ich bin gekommen, um den Vater zu rächen.", T0)
    assert len(listener.heard([line], held.annotations)) == 1
    # The same line again, rated.
    assert listener.heard([line.model_copy(update={"risiko": 3})], held.annotations) == []
    soon = said("Um den Vater zu rächen!", T0 + timedelta(seconds=10))
    assert listener.heard([soon], held.annotations) == []
    later = said("Um den Vater zu rächen!", T0 + timedelta(seconds=scenetext.COOLDOWN_S + 1))
    assert len(listener.heard([later], held.annotations)) == 1


def test_other_words_recognise_no_passage():
    held = annotated("um den Vater zu rächen")
    listener = scenetext.Listener()
    assert listener.heard([said("Wo ist die Mutter?", T0)], held.annotations) == []


def test_a_passage_without_values_is_not_recognised():
    held = annotated("um den Vater zu rächen", values={})
    assert scenetext.Listener().heard([said("um den Vater zu rächen", T0)], held.annotations) == []


def test_each_scene_keeps_its_text_in_a_file_of_its_own(tmp_path):
    store = scenetext.Store(tmp_path)
    held = annotated("um den Vater zu rächen")
    held.initial = {"Orestes": {"risiko": 2}}
    store.put("Szene 1.2", held)
    assert (tmp_path / "szene_1_2.json").is_file()
    again = scenetext.Store(tmp_path).get("Szene 1.2")
    assert again == held
    assert scenetext.Store(tmp_path).get("Szene 3") == scenetext.SceneText()
