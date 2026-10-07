"""The appearance cue: its memory of people, and how it names bodies beside faces.

Descriptions are synthetic unit vectors, so the rules are exercised without
the network; the network itself is checked against the export's reference.
"""

from pathlib import Path

import numpy as np
import pytest

from action import sitrep_map, tracking
from sitrep import actions, appearance

REFERENCE = Path(__file__).parent / "fixtures" / "osnet_reference.npz"


def look(*values) -> np.ndarray:
    """A unit-length description pointing in a named direction."""
    vector = np.zeros(8, dtype=np.float32)
    for index, value in values:
        vector[index] = value
    return vector / np.linalg.norm(vector)


KLARA, JAKOB = look((0, 1.0)), look((1, 1.0))


def memory(**kwargs) -> appearance.Appearances:
    return appearance.Appearances(**{"threshold": 0.6, "margin": 0.05, **kwargs})


# The memory ------------------------------------------------------------------

def test_a_person_is_matched_by_their_appearance():
    known = memory()
    known.learn("Klara", KLARA, 0.0)
    known.learn("Jakob", JAKOB, 0.0)
    assert known.match(look((0, 1.0), (2, 0.4)))[0] == "Klara"


def test_an_appearance_like_no_one_is_matched_to_no_one():
    known = memory()
    known.learn("Klara", KLARA, 0.0)
    assert known.match(look((3, 1.0)))[0] is None


def test_two_people_looking_alike_match_neither():
    known = memory()
    known.learn("Klara", look((0, 1.0), (1, 0.98)), 0.0)
    known.learn("Jakob", look((0, 0.98), (1, 1.0)), 0.0)
    assert known.match(look((0, 1.0), (1, 1.0)))[0] is None


def test_views_are_learned_at_most_once_an_interval_and_the_oldest_go():
    known = memory(keep=3, interval=1.0)
    for at in (0.0, 0.5, 1.0, 2.0, 3.0, 4.0):
        known.learn("Klara", KLARA, at)
    assert known.counts() == {"Klara": 3}


def test_clearing_forgets_everyone():
    known = memory()
    known.learn("Klara", KLARA, 0.0)
    known.clear()
    assert known.match(KLARA)[0] is None


# Crops and the network -------------------------------------------------------

def test_a_body_too_small_to_describe_is_left_out():
    image = np.zeros((1080, 1920, 3), dtype=np.uint8)
    assert appearance.crop(image, (100, 100, 140, 100 + appearance.MIN_HEIGHT - 1)) is None


def test_a_crop_at_the_frame_edge_stays_inside_the_frame():
    image = np.zeros((400, 600, 3), dtype=np.uint8)
    cropped = appearance.crop(image, (0, 0, 100, 390))
    assert cropped.shape[0] == 400 and cropped.shape[1] <= 600


def test_preprocessing_matches_the_export():
    reference = np.load(REFERENCE)
    assert np.allclose(appearance.preprocess(reference["crop"]), reference["tensor"], atol=1e-6)


@pytest.mark.skipif(not appearance.available(), reason="appearance model not installed")
def test_the_network_matches_the_export():
    reference = np.load(REFERENCE)
    features = appearance.session().run(None, {"images": reference["tensor"][None]})[0][0]
    assert np.allclose(features, reference["features"], atol=1e-3)


# Naming with face and appearance together ------------------------------------

MAPPING = sitrep_map.load()


def body(head_x: float) -> tracking.Body:
    keypoints = np.tile([head_x, 400.0], (17, 1)).astype(np.float32)
    keypoints[actions.HEAD] = [head_x, 100.0]
    scores = np.ones(17, dtype=np.float32)
    return tracking.Body(keypoints, scores, tracking.box(keypoints, scores))


def face(x: float, name: str):
    return np.array([x - 20, 80, x + 20, 120]), name


@pytest.fixture
def ratings():
    known = memory()
    known.learn("Klara", KLARA, -10.0)
    known.learn("Jakob", JAKOB, -10.0)
    return actions.ActionRatings(source=None, faces=None, mapping=MAPPING, appearances=known)


def naming(ratings, steps, track=1):
    """The name a body carries after each step, a step being (faces, description)."""
    shown = []
    for second, (labels, description) in enumerate(steps):
        frame = tracking.Frame(float(second), {track: body(100)})
        ratings.name(frame, [face(100, label) for label in labels],
                     {track: description} if description is not None else {})
        shown.append(ratings.names().get(track))
    return shown


def test_appearance_alone_names_a_body_after_two_matches(ratings):
    assert naming(ratings, [([], KLARA), ([], KLARA)]) == [None, "Klara"]


def test_a_face_outweighs_an_appearance_that_disagrees(ratings):
    shown = naming(ratings, [(["Klara"], JAKOB)] * 8)
    assert set(shown) == {"Klara"}


def test_a_person_seen_from_behind_keeps_the_name_their_face_gave(ratings):
    shown = naming(ratings, [(["Klara"], KLARA)] * 2 + [([], KLARA)] * 6)
    assert set(shown) == {"Klara"}


def test_appearance_is_learned_from_a_body_its_face_names():
    known = memory()
    subject = actions.ActionRatings(source=None, faces=None, mapping=MAPPING, appearances=known)
    naming(subject, [(["Klara"], KLARA)])
    assert known.counts() == {"Klara": 1}


def test_appearance_is_not_learned_from_appearance_alone(ratings):
    naming(ratings, [([], KLARA)] * 4)
    assert ratings.appearances.counts()["Klara"] == 1


def test_a_body_named_by_hand_teaches_its_appearance():
    known = memory()
    subject = actions.ActionRatings(source=None, faces=None, mapping=MAPPING, appearances=known)
    subject.assign(1, "Jakob")
    naming(subject, [([], JAKOB)])
    assert known.counts() == {"Jakob": 1}
