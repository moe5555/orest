"""The pose embedding, which has to mean the same thing on both sides of a search.

Indexing runs inside WISE's environment and live queries inside Orest's. A
difference between the two would not raise anything; it would quietly retrieve
nothing useful. These tests pin the properties retrieval depends on, and need no
model, GPU or video.
"""

import numpy as np
import pytest

from orest_pose import keypoints

# A plausible standing skeleton in pixel coordinates, COCO-17 order.
STANDING = np.array([
    [500, 100],                                # nose
    [495, 95], [505, 95], [488, 98], [512, 98],  # eyes, ears
    [470, 140], [530, 140],                    # shoulders
    [455, 200], [545, 200],                    # elbows
    [450, 260], [550, 260],                    # wrists
    [480, 250], [520, 250],                    # hips
    [478, 350], [522, 350],                    # knees
    [476, 450], [524, 450],                    # ankles
], dtype=np.float32)

CONFIDENT = np.ones(17, dtype=np.float32) * 0.9


def frames_of(pose, scores=CONFIDENT, count=keypoints.FRAMES_PER_SEGMENT):
    """A segment in which one body holds the same pose throughout."""
    return [(pose[None, :, :], scores[None, :]) for _ in range(count)]


def test_embedding_has_the_declared_width():
    vector = keypoints.segment_embedding(frames_of(STANDING))
    assert vector.shape == (keypoints.EMBEDDING_DIMS,)
    assert vector.dtype == np.float32


def test_embedding_is_unit_length_for_the_inner_product_index():
    vector = keypoints.segment_embedding(frames_of(STANDING))
    assert float(np.linalg.norm(vector)) == pytest.approx(1.0, abs=1e-5)


def test_the_same_movement_across_the_stage_gives_the_same_vector():
    # Otherwise the index retrieves by where a body stood, not what it did.
    moved = STANDING + np.array([900, -60], dtype=np.float32)
    here = keypoints.segment_embedding(frames_of(STANDING))
    there = keypoints.segment_embedding(frames_of(moved))
    assert float(np.dot(here, there)) == pytest.approx(1.0, abs=1e-5)


def test_the_same_movement_near_and_far_gives_the_same_vector():
    # A body twice as close fills twice the pixels and must still match.
    closer = STANDING * 2.0
    near = keypoints.segment_embedding(frames_of(closer))
    far = keypoints.segment_embedding(frames_of(STANDING))
    assert float(np.dot(near, far)) == pytest.approx(1.0, abs=1e-5)


def test_a_different_posture_gives_a_different_vector():
    raised = STANDING.copy()
    raised[9] = [450, 40]   # left wrist above the head
    raised[10] = [550, 40]  # right wrist above the head
    assert float(np.dot(
        keypoints.segment_embedding(frames_of(STANDING)),
        keypoints.segment_embedding(frames_of(raised)),
    )) < 0.99


def test_segments_of_different_frame_counts_stay_comparable():
    # WISE's decoder does not always deliver a full window at a file's end.
    short = keypoints.segment_embedding(frames_of(STANDING, count=5))
    full = keypoints.segment_embedding(frames_of(STANDING))
    assert short.shape == full.shape
    assert float(np.dot(short, full)) == pytest.approx(1.0, abs=1e-5)


def test_a_segment_with_no_body_retrieves_nothing():
    empty = [(np.zeros((0, 17, 2), np.float32), np.zeros((0, 17), np.float32))
             for _ in range(keypoints.FRAMES_PER_SEGMENT)]
    assert not keypoints.segment_embedding(empty).any()


def test_unseen_keypoints_do_not_contribute():
    scores = CONFIDENT.copy()
    scores[15:] = 0.0  # ankles out of shot
    vector = keypoints.segment_embedding(frames_of(STANDING, scores))
    per_frame = vector[:keypoints.FRAME_DIMS]
    assert per_frame[30:34].tolist() == [0.0, 0.0, 0.0, 0.0]


def test_a_barely_detected_body_is_discarded():
    scores = np.zeros(17, dtype=np.float32)
    scores[:3] = 0.9  # a face and nothing else
    assert not keypoints.segment_embedding(frames_of(STANDING, scores)).any()


def test_the_largest_body_represents_the_segment():
    # One vector per segment, so the nearest body stands for the frame.
    small = STANDING * 0.25
    two = [(np.stack([small, STANDING]), np.stack([CONFIDENT, CONFIDENT]))
           for _ in range(keypoints.FRAMES_PER_SEGMENT)]
    assert float(np.dot(
        keypoints.segment_embedding(two),
        keypoints.segment_embedding(frames_of(STANDING)),
    )) == pytest.approx(1.0, abs=1e-5)


def test_scale_comes_from_the_torso_not_the_limbs():
    # A raised arm enlarges the bounding box but not the body, and must not
    # rescale the whole skeleton.
    seen = np.ones(17, dtype=bool)
    reaching = STANDING.copy()
    reaching[9] = [450, -200]
    assert keypoints.body_scale(reaching, seen) == pytest.approx(
        keypoints.body_scale(STANDING, seen)
    )
