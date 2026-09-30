"""Action readings turned into ratings per person: naming, weighing, rating.

Needs no model, camera or GPU: readings are built by hand from probabilities.
"""

from datetime import datetime, timedelta

import numpy as np
import pytest

from action import recognizer, sitrep_map, tracking
from sitrep import actions

MAPPING = sitrep_map.load()
CLASSES = {name: index for index, name in enumerate(MAPPING.names)}
T0 = datetime(2026, 9, 28, 20, 0, 0)
EARLIER = T0 - timedelta(seconds=1)


def body(head_x: float, head_y: float, head_visible: bool = True) -> tracking.Body:
    """A body whose head joints sit at one point, the rest a metre below."""
    keypoints = np.tile([head_x, head_y + 300.0], (17, 1)).astype(np.float32)
    keypoints[actions.HEAD] = [head_x, head_y]
    scores = np.ones(17, dtype=np.float32)
    if not head_visible:
        scores[actions.HEAD] = 0.0
    return tracking.Body(keypoints, scores, tracking.box(keypoints, scores))


def face(x: float, y: float, name: str, size: float = 40.0):
    return np.array([x - size / 2, y - size / 2, x + size / 2, y + size / 2]), name


def probabilities(**classes: float) -> np.ndarray:
    """A reading's 120 probabilities: the given classes, the rest on drinking water."""
    row = np.zeros(sitrep_map.CLASSES)
    for name, probability in classes.items():
        row[CLASSES[name.replace("_", " ")]] = probability
    row[CLASSES["drink water"]] += 1.0 - row.sum()
    return row


def reading(*members: int, **classes: float) -> recognizer.Reading:
    return recognizer.Reading(0.0, members, probabilities(**classes))


@pytest.fixture
def ratings():
    """Ratings over no camera; driven by hand, never started."""
    return actions.ActionRatings(source=None, faces=None, mapping=MAPPING)


def test_a_body_takes_the_name_of_the_face_its_head_is_in():
    frame = tracking.Frame(0.0, {1: body(100, 100), 2: body(500, 100)})
    assert actions.name_bodies(frame, [face(505, 95, "Klara")]) == {2: "Klara"}


def test_a_face_box_from_a_moment_ago_still_names_a_head_just_outside_it():
    frame = tracking.Frame(0.0, {1: body(130, 100)})
    assert actions.name_bodies(frame, [face(100, 100, "Klara")]) == {1: "Klara"}
    frame = tracking.Frame(0.0, {1: body(200, 100)})
    assert actions.name_bodies(frame, [face(100, 100, "Klara")]) == {}


def test_a_body_without_a_visible_head_is_not_named():
    frame = tracking.Frame(0.0, {1: body(100, 100, head_visible=False)})
    assert actions.name_bodies(frame, [face(100, 100, "Klara")]) == {}


def test_close_heads_each_take_the_nearer_face():
    frame = tracking.Frame(0.0, {1: body(100, 100), 2: body(130, 100)})
    faces = [face(135, 100, "Jakob"), face(95, 100, "Klara")]
    assert actions.name_bodies(frame, faces) == {1: "Klara", 2: "Jakob"}


def test_evidence_is_expected_under_the_models_uncertainty():
    values, causes = actions.weigh(
        probabilities(**{"punching/slapping_other_person": 0.6}), MAPPING)
    assert values == pytest.approx([0.6 * 5, 0.6 * -3])
    assert causes[0] == "punching/slapping other person 0.60"


def test_a_rating_is_the_peak_over_the_window_clipped_to_zero_to_five(ratings):
    ratings.name(tracking.Frame(0.0, {1: body(100, 100)}), [face(100, 100, "Klara")])
    ratings.record([reading(1, hugging_other_person=0.2)], T0)
    ratings.record([reading(1, hugging_other_person=0.9)], T0 + timedelta(seconds=1))
    ratings.record([reading(1)], T0 + timedelta(seconds=2))

    [klara] = ratings.between(EARLIER, T0 + timedelta(seconds=2))
    assert (klara.name, klara.risiko, klara.menschlichkeit, klara.lesungen) == ("Klara", 0, 4, 3)
    assert klara.anlass_menschlichkeit == "hugging other person 0.90"
    assert klara.anlass_risiko == ""


def test_negative_evidence_floors_a_rating_at_zero(ratings):
    ratings.name(tracking.Frame(0.0, {1: body(100, 100)}), [face(100, 100, "Klara")])
    ratings.record([reading(1, kicking_other_person=1.0)], T0)
    [klara] = ratings.between(EARLIER, T0)
    assert (klara.risiko, klara.menschlichkeit) == (5, 0)


def test_a_pair_reading_counts_for_both_people(ratings):
    frame = tracking.Frame(0.0, {1: body(100, 100), 2: body(400, 100)})
    ratings.name(frame, [face(100, 100, "Klara"), face(400, 100, "Jakob")])
    ratings.record([reading(1, 2, pushing_other_person=1.0)], T0)
    assert {handlung.name: handlung.risiko for handlung in ratings.between(EARLIER, T0)} == {
        "Klara": 3, "Jakob": 3}


def test_an_unnamed_body_is_not_rated(ratings):
    ratings.record([reading(7, kicking_other_person=1.0)], T0)
    assert ratings.between(EARLIER, T0) == []


def test_a_name_seen_steadily_on_a_second_body_in_view_leaves_the_first(ratings):
    ratings.name(tracking.Frame(0.0, {1: body(100, 100)}), [face(100, 100, "Klara")])
    for second in range(1, 5):
        ratings.name(tracking.Frame(float(second), {1: body(100, 100), 2: body(400, 100)}),
                     [face(400, 100, "Klara")])
    ratings.record([reading(1, kicking_other_person=1.0), reading(2)], T0)
    [klara] = ratings.between(EARLIER, T0)
    assert (klara.risiko, klara.lesungen) == (0, 1)
    assert 1 not in ratings.names()


def test_a_name_held_steadily_is_not_taken_by_one_sighting_on_another_body(ratings):
    """A duplicate detection or a misplaced face box must not move a name."""
    for second in range(4):
        ratings.name(tracking.Frame(float(second), {1: body(100, 100)}),
                     [face(100, 100, "Klara")])
    ratings.name(tracking.Frame(4.0, {1: body(100, 100), 2: body(400, 100)}),
                 [face(400, 100, "Klara")])
    assert ratings.names() == {1: "Klara"}


def names_after(ratings, sightings: list[str], track: int = 1) -> list[str]:
    """The name a body carries after each of a series of face sightings, one a second."""
    shown = []
    for second, label in enumerate(sightings):
        ratings.name(tracking.Frame(float(second), {track: body(100, 100)}),
                     [face(100, 100, label)])
        shown.append(ratings.names().get(track))
    return shown


def test_a_body_named_by_the_cast_is_not_renamed_by_a_single_other_name(ratings):
    shown = names_after(ratings, ["Klara"] * 4 + ["Jakob"] + ["Klara"] * 2)
    assert set(shown) == {"Klara"}


def test_a_guess_does_not_replace_a_cast_name(ratings):
    shown = names_after(ratings, ["Klara", "Vielleicht: Theo", "Vielleicht: Rosa"])
    assert shown == ["Klara"] * 3


def test_a_guess_names_a_body_the_cast_has_not(ratings):
    shown = names_after(ratings, ["Vielleicht: Theo", "Vielleicht: Rosa", "Klara"])
    assert shown == ["Vielleicht: Theo", "Vielleicht: Rosa", "Klara"]


def test_a_body_seen_steadily_as_someone_else_is_renamed(ratings):
    """The body tracker can carry one person's track over to another."""
    shown = names_after(ratings, ["Klara"] * 5 + ["Jakob"] * 8)
    assert shown[5] == "Klara"
    assert shown[-1] == "Jakob"


def test_a_body_that_left_keeps_its_name_for_what_it_did(ratings):
    """A camera cut or a lost track gives the same person a new body."""
    ratings.name(tracking.Frame(0.0, {1: body(100, 100)}), [face(100, 100, "Klara")])
    ratings.name(tracking.Frame(1.0, {2: body(400, 100)}), [face(400, 100, "Klara")])
    ratings.record([reading(1, kicking_other_person=1.0), reading(2)], T0)
    [klara] = ratings.between(EARLIER, T0)
    assert (klara.risiko, klara.lesungen) == (5, 2)


def test_a_stretch_is_rated_on_its_own_readings_and_leaves_them_for_others(ratings):
    """The Chronik's Abschnitt, a report and the live values read the same readings."""
    ratings.name(tracking.Frame(0.0, {1: body(100, 100)}), [face(100, 100, "Klara")])
    ratings.record([reading(1, kicking_other_person=1.0)], T0)
    ratings.record([reading(1, hugging_other_person=1.0)], T0 + timedelta(seconds=40))

    [first] = ratings.between(EARLIER, T0 + timedelta(seconds=30))
    assert (first.risiko, first.menschlichkeit) == (5, 0)
    [again] = ratings.between(EARLIER, T0 + timedelta(seconds=30))
    assert again == first
    [second] = ratings.between(T0 + timedelta(seconds=30), T0 + timedelta(seconds=60))
    assert (second.risiko, second.menschlichkeit) == (0, 4)


def test_readings_older_than_keep_are_deleted(ratings):
    ratings.name(tracking.Frame(0.0, {1: body(100, 100)}), [face(100, 100, "Klara")])
    ratings.record([reading(1, kicking_other_person=1.0)], T0)
    ratings.record([reading(1)], T0 + timedelta(seconds=actions.KEEP + 1))
    records, _ = ratings.since(EARLIER)
    assert [record.at for record in records] == [T0 + timedelta(seconds=actions.KEEP + 1)]


def test_the_live_view_keeps_every_body_and_labels_the_unnamed(ratings):
    ratings.name(tracking.Frame(0.0, {1: body(100, 100)}), [face(100, 100, "Klara")])
    ratings.record([reading(1, 7, pushing_other_person=0.8)], T0)
    [seen] = ratings.latest
    assert seen.who == ("Klara", "Körper 7")
    assert (seen.action, seen.probability) == ("pushing other person", pytest.approx(0.8))
    assert ratings.evaluations == 1


def test_readings_made_before_a_body_is_named_count_once_it_is(ratings):
    """A face is often seen only after its body has been classified a few times."""
    ratings.record([reading(1, kicking_other_person=1.0)], T0)
    ratings.name(tracking.Frame(1.0, {1: body(100, 100)}), [face(100, 100, "Klara")])
    ratings.record([reading(1)], T0 + timedelta(seconds=1))
    [klara] = ratings.between(EARLIER, T0 + timedelta(seconds=1))
    assert (klara.name, klara.risiko, klara.lesungen) == ("Klara", 5, 2)
