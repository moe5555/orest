"""Speech attributed by lip movement: head boxes from pose, and who moved their lips.

Needs no model: mouth openings are fed in by hand, or the landmark step is
replaced.
"""

from datetime import datetime, timedelta

import numpy as np
import pytest

from action import tracking
from sitrep import actions, report, speakers, transcribe

T0 = datetime(2026, 9, 28, 20, 0, 0)


def body(x: float, height: float = 400.0, head_visible: bool = True) -> tracking.Body:
    """A standing body whose head joints sit at its top, ears 60 px apart."""
    keypoints = np.tile([x, 100 + height / 2], (17, 1)).astype(np.float32)
    keypoints[:5] = [[x, 110], [x - 15, 100], [x + 15, 100], [x - 30, 105], [x + 30, 105]]
    keypoints[15:] = [[x - 20, 100 + height], [x + 20, 100 + height]]
    scores = np.ones(17, dtype=np.float32)
    if not head_visible:
        scores[:5] = 0.0
    return tracking.Body(keypoints, scores, tracking.box(keypoints, scores))


def feed(subject, track_openings: dict[int, list[float]], start=T0, fps=25.0):
    """Mouth openings per track, one per frame from `start`."""
    for track, openings in track_openings.items():
        for index, opening in enumerate(openings):
            subject._samples.append((start + timedelta(seconds=index / fps), track, opening))


def test_a_face_box_is_placed_from_the_head_joints():
    centre_x, centre_y, size = speakers.head(body(300))
    assert size == pytest.approx(1.1 * 60)
    assert centre_x == pytest.approx(300)
    assert centre_y == pytest.approx(110 + 0.1 * size)


def test_a_turned_away_head_has_no_face_box():
    assert speakers.head(body(300, head_visible=False)) is None


def test_a_line_goes_to_the_person_whose_lips_moved():
    subject = speakers.Speakers()
    moving = [0.1, 0.4] * 25
    still = [0.1, 0.12] * 25
    feed(subject, {1: moving, 2: still})
    [line] = subject.attribute([transcribe.Segment(0.0, 2.0, "Halt.")], T0, {1: "Klara", 2: "Jakob"})
    assert (line.name, line.text) == ("Klara", "Halt.")
    assert line.beginn == T0 and line.ende == T0 + timedelta(seconds=2)


def test_a_line_goes_to_the_one_speaker_among_several():
    subject = speakers.Speakers()
    feed(subject, {1: [0.1, 0.12] * 25, 2: [0.1, 0.11] * 25, 3: [0.1, 0.4] * 25})
    [line] = subject.attribute([transcribe.Segment(0.0, 2.0, "Halt.")], T0,
                               {1: "Klara", 2: "Jakob", 3: "Lena"})
    assert line.name == "Lena"


def test_a_line_stays_unattributed_when_two_of_several_moved_alike():
    subject = speakers.Speakers()
    feed(subject, {1: [0.1, 0.4] * 25, 2: [0.1, 0.11] * 25, 3: [0.1, 0.35] * 25})
    [line] = subject.attribute([transcribe.Segment(0.0, 2.0, "Ja.")], T0,
                               {1: "Klara", 2: "Jakob", 3: "Lena"})
    assert line.name is None


def test_a_line_stays_unattributed_when_both_moved_alike():
    subject = speakers.Speakers()
    feed(subject, {1: [0.1, 0.4] * 25, 2: [0.1, 0.35] * 25})
    [line] = subject.attribute([transcribe.Segment(0.0, 2.0, "Ja.")], T0, {1: "Klara", 2: "Jakob"})
    assert line.name is None


def test_a_line_stays_unattributed_with_only_one_mouth_in_view():
    """The other person may be speaking while turned away."""
    subject = speakers.Speakers()
    feed(subject, {1: [0.1, 0.4] * 25})
    [line] = subject.attribute([transcribe.Segment(0.0, 2.0, "Ja.")], T0, {1: "Klara"})
    assert line.name is None


def test_a_speaker_without_a_name_is_unknown_rather_than_unattributed():
    subject = speakers.Speakers()
    feed(subject, {1: [0.1, 0.4] * 25, 2: [0.1, 0.1] * 25})
    [line] = subject.attribute([transcribe.Segment(0.0, 2.0, "Ja.")], T0, {2: "Jakob"})
    assert line.name == report.UNBEKANNT


def test_only_the_segments_own_moments_count():
    subject = speakers.Speakers()
    feed(subject, {1: [0.1, 0.4] * 25, 2: [0.1, 0.1] * 25})
    feed(subject, {1: [0.1, 0.1] * 25, 2: [0.1, 0.4] * 25}, start=T0 + timedelta(seconds=3))
    lines = subject.attribute([transcribe.Segment(0.0, 2.0, "Erst ich."),
                               transcribe.Segment(3.0, 5.0, "Dann ich.")],
                              T0, {1: "Klara", 2: "Jakob"})
    assert [line.name for line in lines] == ["Klara", "Jakob"]


def test_only_the_tallest_bodies_are_measured(monkeypatch):
    measured = []
    monkeypatch.setattr(speakers, "mouth_opening",
                        lambda image, x, y, size: measured.append(round(x)) or 0.2)
    frame = tracking.Frame(0.0, {1: body(100, 400), 2: body(300, 150), 3: body(500, 380),
                                 4: body(700, 390), 5: body(900, 410)})
    speakers.Speakers().observe(np.zeros((1080, 1920, 3), np.uint8), frame, T0)
    assert sorted(measured) == [100, 500, 700, 900]


def test_a_failing_measurement_stops_mouths_but_not_the_recogniser(monkeypatch, capsys):
    def broken(*args):
        raise RuntimeError("CUDA out of memory")

    monkeypatch.setattr(speakers, "mouth_opening", broken)
    subject = speakers.Speakers()
    frame = tracking.Frame(0.0, {1: body(100)})
    subject.observe(np.zeros((1080, 1920, 3), np.uint8), frame, T0)
    subject.observe(np.zeros((1080, 1920, 3), np.uint8), frame, T0)
    assert isinstance(subject.error, RuntimeError)
    assert capsys.readouterr().err.count("mouth measurement stopped") == 1


def test_the_overlay_boxes_the_tallest_bodies_by_name():
    ratings = actions.ActionRatings(source=None, faces=None)
    frame = tracking.Frame(0.0, {1: body(100, 400), 2: body(300, 150), 3: body(500, 380),
                                 4: body(700, 390), 5: body(900, 410)})
    ratings.recognizer.tracker.frames.append(frame)
    ratings.name(frame, [(np.array([85, 95, 115, 125]), "Klara")])
    assert [label for _, label in ratings.visible()] == ["Körper 5", "Klara", "Körper 4", "Körper 3"]
