"""Who stands on the Podest, judged from tracked poses against its polygon,
and the Risiko it counts for each person.

Needs no model or camera: bodies are built by hand on a 1920x1080 image, the
Probebühne camera's, on which podest.POLYGON was measured.
"""

from datetime import datetime, timedelta

import numpy as np
import pytest

from action import tracking
from sitrep import podest

SHAPE = (1080, 1920)
REGION = podest.pixels(podest.POLYGON, SHAPE)

# Feet on the top surface, on the floor in front of it, behind it and beside it.
ON = (920.0, 650.0)
IN_FRONT = (920.0, 790.0)
BEHIND = (920.0, 575.0)
BESIDE = (1150.0, 650.0)


def body(foot: tuple[float, float], height: float = 400.0, thigh: float = 0.25,
         shin: float = 0.25, hidden: tuple[int, ...] = ()) -> tracking.Body:
    """A person whose ankles are at `foot`, their hips `thigh` and knees `shin`
    of their height above the joint below."""
    x, y = foot
    keypoints = np.zeros((17, 2), dtype=np.float32)
    keypoints[:5] = [x, y - height]
    keypoints[5:11] = [x, y - 0.75 * height]
    keypoints[podest.ANKLES] = [x, y]
    keypoints[podest.KNEES] = [x, y - shin * height]
    keypoints[podest.HIPS] = [x, y - (shin + thigh) * height]
    keypoints[:, 0] += np.tile([-10.0, 10.0], 9)[:17]
    scores = np.full(17, 0.9, dtype=np.float32)
    scores[list(hidden)] = 0.0
    return tracking.Body(keypoints, scores, tracking.box(keypoints, scores))


def frames(*stances: dict[int, tracking.Body]) -> list[tracking.Frame]:
    return [tracking.Frame(index / 25, bodies) for index, bodies in enumerate(stances)]


def test_a_person_standing_on_the_top_surface_is_on_the_podest():
    assert podest.steht_auf(body(ON), REGION) is True


@pytest.mark.parametrize("foot", [IN_FRONT, BEHIND, BESIDE])
def test_a_person_standing_on_the_floor_around_it_is_not(foot):
    assert podest.steht_auf(body(foot), REGION) is False


@pytest.mark.parametrize("thigh, shin", [(0.0, 0.25), (0.25, 0.0), (-0.3, 0.5)])
def test_sitting_kneeling_or_lying_on_it_is_not_standing(thigh, shin):
    assert podest.steht_auf(body(ON, thigh=thigh, shin=shin), REGION) is False


def test_a_body_without_visible_legs_cannot_be_judged():
    assert podest.steht_auf(body(ON, hidden=tuple(podest.ANKLES)), REGION) is None
    assert podest.steht_auf(body(ON, hidden=tuple(podest.KNEES)), REGION) is None


def test_the_polygon_is_relative_to_the_image():
    smaller = podest.pixels(podest.POLYGON, (720, 1280))
    foot = (ON[0] * 1280 / 1920, ON[1] * 720 / 1080)
    assert podest.steht_auf(body(foot, height=270.0), smaller) is True


def test_a_body_is_up_when_it_stood_there_in_half_the_judged_frames():
    up, down, unseen = body(ON), body(IN_FRONT), body(ON, hidden=tuple(podest.ANKLES))
    assert podest.oben(frames({1: up}, {1: down}, {1: unseen}, {1: up}), SHAPE) == {1}
    assert podest.oben(frames({1: up}, {1: down}, {1: down}), SHAPE) == set()


def test_a_body_out_of_view_is_not_up():
    assert podest.oben(frames({1: body(ON)}, {1: body(ON)}, {2: body(IN_FRONT)}), SHAPE) == set()
    assert podest.oben([], SHAPE) == set()


def test_a_polygon_is_written_and_read_as_points():
    text = podest.format_polygon(podest.POLYGON)
    assert podest.parse_polygon(text) == podest.POLYGON
    with pytest.raises(ValueError):
        podest.parse_polygon("0.1,0.1 0.2,0.2")
    with pytest.raises(ValueError):
        podest.parse_polygon("0.1,0.1 0.2,0.2 640,480")
    with pytest.raises(ValueError):
        podest.parse_polygon("0.1;0.1 0.2,0.2 0.3,0.3")


def test_stepping_off_raises_the_count_and_stepping_on_lowers_it():
    counter = podest.Counter(step=1, floor=0)
    now = datetime(2026, 10, 13, 20, 0, 0)
    assert counter.update({"Klara": True}, {}, now) == {"Klara": (0, now)}
    later = now + timedelta(seconds=3)
    assert counter.update({"Klara": False}, {}, later) == {"Klara": (1, later)}
    assert counter.update({"Klara": True}, {}, later)["Klara"][0] == 0


def test_off_the_podest_the_count_keeps_risiko_at_the_floor():
    counter = podest.Counter(step=1, floor=2)
    now = datetime(2026, 10, 13, 20, 0, 0)
    assert counter.update({"Klara": False}, {"Klara": 0}, now)["Klara"][0] == 2
    assert counter.update({"Klara": True}, {"Klara": 0}, now)["Klara"][0] == 1
    assert counter.update({"Klara": False}, {"Klara": 0}, now)["Klara"][0] == 2
    # Measured Risiko of 3 is above the floor already: the count is not raised.
    fresh = podest.Counter(step=1, floor=2)
    assert fresh.update({"Lena": False}, {"Lena": 3}, now)["Lena"][0] == 0


def test_the_count_of_a_person_out_of_view_is_kept_and_their_return_counts_as_one_step():
    counter = podest.Counter(step=1, floor=0)
    now = datetime(2026, 10, 13, 20, 0, 0)
    counter.update({"Klara": True}, {}, now)
    assert counter.update({}, {}, now) == {"Klara": (0, now)}
    assert counter.update({"Klara": False}, {}, now)["Klara"][0] == 1
