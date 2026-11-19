"""Who is on the Podest, judged from tracked poses against its polygon,
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
ON = (800.0, 700.0)
IN_FRONT = (800.0, 820.0)
BEHIND = (800.0, 610.0)
BESIDE = (1150.0, 700.0)


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
    assert podest.on_podest(body(ON), REGION) is True


@pytest.mark.parametrize("foot", [IN_FRONT, BEHIND, BESIDE])
def test_a_person_standing_on_the_floor_around_it_is_not(foot):
    assert podest.on_podest(body(foot), REGION) is False


@pytest.mark.parametrize("thigh, shin", [(0.0, 0.25), (0.25, 0.0), (-0.3, 0.5)])
def test_sitting_kneeling_or_lying_on_it_is_on_it(thigh, shin):
    assert podest.on_podest(body(ON, thigh=thigh, shin=shin), REGION) is True


def test_sitting_on_its_edge_with_the_legs_hanging_off_is_on_it():
    # Hips on the top surface, thighs level, feet on the floor in front.
    sitting = body(IN_FRONT, height=300.0, thigh=0.0, shin=0.4)
    assert podest._inside(REGION, sitting.keypoints[podest.HIPS].mean(axis=0))
    assert podest.on_podest(sitting, REGION) is True


def test_standing_in_front_of_it_with_the_hips_over_its_top_is_off_it():
    # From the camera, the hips of someone standing in front lie over the top surface.
    standing = body((800.0, 900.0), height=500.0)
    assert podest._inside(REGION, standing.keypoints[podest.HIPS].mean(axis=0))
    assert podest.on_podest(standing, REGION) is False


def test_a_body_without_visible_ankles_is_judged_by_its_hips_or_not_at_all():
    assert podest.on_podest(body(ON, hidden=tuple(podest.ANKLES)), REGION) is None
    # Hips on the top surface, thighs level, the legs hidden below its front.
    seated = body((800.0, 775.0), height=300.0, thigh=0.0, hidden=tuple(podest.ANKLES))
    assert podest._inside(REGION, seated.keypoints[podest.HIPS].mean(axis=0))
    assert podest.on_podest(seated, REGION) is True


def test_the_polygon_is_relative_to_the_image():
    smaller = podest.pixels(podest.POLYGON, (720, 1280))
    foot = (ON[0] * 1280 / 1920, ON[1] * 720 / 1080)
    assert podest.on_podest(body(foot, height=270.0), smaller) is True


def follow(*stances, stance=None):
    """A Stance after the frames, and the steps each frame completed."""
    stance = stance or podest.Stance()
    return stance, [stance.observe(frame, SHAPE) for frame in frames(*stances)]


def test_a_stance_is_taken_after_halten_frames_in_a_row():
    up, down = body(ON), body(IN_FRONT)
    stance, steps = follow(*[{1: up}] * podest.HALTEN, *[{1: down}] * podest.HALTEN)
    assert [step for completed in steps for step in completed] == [(1, False)]
    assert steps[2 * podest.HALTEN - 1] == [(1, False)]
    assert stance.now() == {1: False}


def test_a_single_frame_of_the_other_stance_is_no_step():
    up, down = body(ON), body(IN_FRONT)
    stance, steps = follow(*[{1: up}] * podest.HALTEN, {1: down}, *[{1: up}] * podest.HALTEN)
    assert not any(steps)
    assert stance.now() == {1: True}


def test_frames_that_cannot_be_judged_neither_confirm_nor_break_a_run():
    up, down, unseen = body(ON), body(IN_FRONT), body(ON, hidden=tuple(podest.ANKLES))
    stance, steps = follow(*[{1: up}] * podest.HALTEN, *[{1: down}, {1: unseen}] * podest.HALTEN)
    assert [step for completed in steps for step in completed] == [(1, False)]


def test_a_body_first_seen_is_off_until_it_takes_a_stance_and_that_is_no_step():
    stance, _ = follow(*[{1: body(ON)}] * (podest.HALTEN - 1))
    assert stance.now() == {1: False}
    steps = stance.observe(tracking.Frame(1.0, {1: body(ON)}), SHAPE)
    assert stance.now() == {1: True} and steps == []


def test_a_body_keeps_its_stance_while_out_of_view_and_its_step_counts_on_return():
    stance, _ = follow(*[{1: body(ON)}] * podest.HALTEN)
    stance.observe(tracking.Frame(1.0, {}), SHAPE)
    assert stance.now() == {}
    steps = [stance.observe(tracking.Frame(1.5 + i / 25, {1: body(IN_FRONT)}), SHAPE)
             for i in range(podest.HALTEN)]
    assert steps[-1] == [(1, False)]


def test_each_step_reaches_on_step():
    seen = []
    up, down = body(ON), body(IN_FRONT)
    follow(*[{7: up}] * podest.HALTEN, *[{7: down}] * podest.HALTEN, *[{7: up}] * podest.HALTEN,
           stance=podest.Stance(on_step=lambda track, up: seen.append((track, up))))
    assert seen == [(7, False), (7, True)]


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
