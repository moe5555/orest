"""Action recognition: preprocessing, body tracking and grouping.

A preprocessing error does not fail loudly: the model still returns 120
plausible probabilities for a sequence it was never trained on. The pipeline
is therefore pinned bit for bit against MMAction2's own output, saved by
src/scripts/export_ntu_stgcn.py. Needs no model, camera or GPU.
"""

from pathlib import Path

import numpy as np
import pytest

from action import model, preprocess, recognizer, tracking

REFERENCE = np.load(Path(__file__).parent / "fixtures" / "ntu120_reference.npz")

# A standing figure in COCO-17 order, in units of body height, feet at y = 0.
STANDING = np.array([
    [0.00, -0.93], [-0.03, -0.95], [0.03, -0.95], [-0.06, -0.94], [0.06, -0.94],
    [-0.12, -0.80], [0.12, -0.80], [-0.15, -0.63], [0.15, -0.63],
    [-0.16, -0.47], [0.16, -0.47], [-0.09, -0.50], [0.09, -0.50],
    [-0.09, -0.27], [0.09, -0.27], [-0.09, -0.02], [0.09, -0.02],
], dtype=np.float32)


def figure(x: float, y: float = 900.0, height: float = 500.0) -> np.ndarray:
    return STANDING * height + [x, y]


def detections(*figures):
    keypoints = np.stack(figures) if figures else np.zeros((0, 17, 2), np.float32)
    return keypoints, np.full(keypoints.shape[:2], 0.9, dtype=np.float32)


# ---- preprocessing ------------------------------------------------------------

def test_preprocessing_is_bit_identical_to_mmaction2():
    keypoints = REFERENCE["keypoints"].transpose(1, 0, 2, 3)
    scores = REFERENCE["keypoint_scores"].transpose(1, 0, 2)
    clips = preprocess.clips(keypoints, scores, tuple(REFERENCE["img_shape"]))
    assert clips.dtype == np.float32
    assert np.array_equal(clips, REFERENCE["inputs"])


@pytest.mark.parametrize("length", [100, 150, 250])
def test_frame_sampling_matches_mmaction2_for_longer_sequences(length):
    """Live windows are a full clip long, a branch the reference sequence,
    at 75 frames, does not reach."""
    assert np.array_equal(preprocess.sample_indices(length), REFERENCE[f"frame_inds_{length}"])


def test_sampling_does_not_disturb_numpys_global_generator():
    np.random.seed(7)
    expected = np.random.rand()
    np.random.seed(7)
    preprocess.sample_indices(150)
    assert np.random.rand() == expected


def test_a_short_sequence_is_looped_to_fill_a_clip():
    indices = preprocess.sample_indices(40)
    assert indices.shape == (preprocess.NUM_CLIPS * preprocess.CLIP_LEN,)
    assert indices.max() < 40
    assert np.array_equal(indices[:80], np.mod(np.arange(80), 40))


def test_one_person_is_padded_to_two_with_zeros():
    keypoints = np.full((1, 100, 17, 2), 500.0, dtype=np.float32)
    scores = np.full((1, 100, 17), 0.9, dtype=np.float32)
    clips = preprocess.clips(keypoints, scores, (1080, 1920))
    assert clips.shape == (preprocess.NUM_CLIPS, 2, preprocess.CLIP_LEN, 17, 3)
    assert not clips[:, 1].any()


def test_coordinates_are_normalised_about_the_image_centre():
    keypoints = np.zeros((1, 100, 17, 2), dtype=np.float32)
    keypoints[..., 0], keypoints[..., 1] = 960.0, 1080.0
    clips = preprocess.clips(keypoints, np.ones((1, 100, 17)), (1080, 1920))
    assert np.all(clips[:, 0, ..., 0] == 0.0)
    assert np.all(clips[:, 0, ..., 1] == 1.0)


# ---- tracking -----------------------------------------------------------------

def test_a_body_keeps_its_id_while_it_moves():
    tracker = tracking.BodyTracker()
    ids = []
    for step in range(10):
        frame = tracker.update(*detections(figure(500 + 8 * step)), at=step / 25)
        ids.append(next(iter(frame.bodies)))
    assert len(set(ids)) == 1


def test_two_bodies_are_not_swapped_when_listed_in_the_other_order():
    tracker = tracking.BodyTracker()
    first = tracker.update(*detections(figure(400), figure(1200)), at=0.0)
    second = tracker.update(*detections(figure(1205), figure(405)), at=0.04)
    left = next(track for track, body in first.bodies.items() if body.box[0] < 800)
    assert second.bodies[left].box[0] < 800


def test_a_body_gone_longer_than_the_forget_window_returns_as_someone_new():
    tracker = tracking.BodyTracker()
    before = next(iter(tracker.update(*detections(figure(500)), at=0.0).bodies))
    tracker.update(*detections(), at=0.5)
    after = next(iter(tracker.update(*detections(figure(500)), at=tracking.FORGET + 0.5).bodies))
    assert after != before


def test_a_body_hidden_briefly_keeps_its_id():
    tracker = tracking.BodyTracker()
    before = next(iter(tracker.update(*detections(figure(500)), at=0.0).bodies))
    tracker.update(*detections(), at=0.3)
    after = next(iter(tracker.update(*detections(figure(505)), at=0.6).bodies))
    assert after == before


def test_a_detection_with_too_few_visible_joints_is_not_followed():
    keypoints, scores = detections(figure(500))
    scores[0, tracking.MIN_JOINTS - 1:] = 0.0
    assert tracking.BodyTracker().update(keypoints, scores, at=0.0).bodies == {}


def test_old_frames_are_dropped():
    tracker = tracking.BodyTracker(history=1.0)
    for step in range(60):
        tracker.update(*detections(figure(500)), at=step / 25)
    assert tracker.frames[0].at >= tracker.frames[-1].at - 1.0


# ---- ghosts -------------------------------------------------------------------

# Kneeling upright: torso as standing, knees on the floor, shins behind.
KNEELING = STANDING.copy()
KNEELING[:13, 1] += 0.35
KNEELING[13:15] = [[-0.09, -0.02], [0.09, -0.02]]
KNEELING[15:17] = [[-0.30, -0.02], [-0.12, -0.02]]


def bodies_after(*people):
    """The bodies the tracker follows, given (keypoints, mean score, visible joints) per detection."""
    keypoints = np.stack([points for points, _, _ in people])
    scores = np.zeros(keypoints.shape[:2], dtype=np.float32)
    for row, (_, score, visible) in enumerate(people):
        scores[row, visible] = score
    return list(tracking.BodyTracker().update(keypoints, scores, at=0.0).bodies.values())


def shadow_of(points: np.ndarray, shift: float = 100.0, scale: float = 1.1) -> np.ndarray:
    """A person's pose cast onto a wall behind them: shifted aside and enlarged."""
    centre = points[:13].mean(axis=0)
    return (points - centre) * scale + centre + [shift, -20.0]


ALL = slice(None)
UPPER = slice(0, 13)


def test_one_person_boxed_twice_is_followed_once():
    person = figure(500)
    found = bodies_after((person, 0.95, ALL), (person + 4.0, 0.85, ALL))
    assert len(found) == 1
    assert found[0].confidence == pytest.approx(0.95)


def test_a_shadow_beside_a_person_is_not_followed():
    person = figure(500)
    found = bodies_after((person, 0.95, ALL), (shadow_of(person), 0.68, UPPER))
    assert len(found) == 1


def test_a_shadow_read_as_seen_from_behind_is_not_followed():
    person = figure(500)
    mirrored = shadow_of(person)[tracking.MIRRORED]
    assert len(bodies_after((person, 0.95, ALL), (mirrored, 0.68, UPPER))) == 1


def test_someone_kneeling_beside_a_standing_person_is_followed():
    """Overlapping and as unsure as a shadow, but in a pose of their own."""
    standing = figure(500)
    kneeling = KNEELING * 500 + [560, 900]
    assert len(bodies_after((standing, 0.95, ALL), (kneeling, 0.7, ALL))) == 2


def test_a_confident_person_overlapping_another_is_followed():
    person = figure(500)
    assert len(bodies_after((person, 0.95, ALL), (shadow_of(person), 0.9, ALL))) == 2


# ---- grouping -----------------------------------------------------------------

def track(frames_of_figures, fps=25.0):
    tracker = tracking.BodyTracker()
    for index, figures in enumerate(frames_of_figures):
        tracker.update(*detections(*figures), at=index / fps)
    return list(tracker.frames)


def test_people_standing_close_form_a_pair():
    frames = track([(figure(800), figure(1100))] * 50)
    assert sorted(recognizer.groups(frames), key=len) == [(1,), (2,), (1, 2)]


def test_people_far_apart_are_classified_alone():
    frames = track([(figure(200), figure(1700))] * 50)
    assert recognizer.groups(frames) == [(1,), (2,)]


def test_someone_seen_in_too_few_frames_is_left_out():
    frames = track([(figure(800), figure(1100))] * 10 + [(figure(800),)] * 40)
    assert recognizer.groups(frames) == [(1,)]


def test_a_sequence_is_zeros_wherever_a_member_is_absent():
    frames = track([(figure(800), figure(1100))] * 5 + [(figure(800),)] * 5)
    keypoints, scores = recognizer.sequence(frames, (1, 2))
    assert keypoints.shape == (2, 10, 17, 2) and scores.shape == (2, 10, 17)
    assert scores[1, :5].all() and not scores[1, 5:].any()
    assert not keypoints[1, 5:].any()


def test_evaluation_classifies_every_group_in_one_batch(monkeypatch):
    batches = []

    def classify(batch):
        batches.append(batch.shape)
        return np.tile(np.eye(120)[49], (len(batch), 1))

    monkeypatch.setattr(model, "classify", classify)
    monkeypatch.setattr(model, "labels", lambda: tuple(f"A{i + 1}" for i in range(120)))
    subject = recognizer.ActionRecognizer()
    subject.image_shape = (1080, 1920)
    for index in range(100):
        subject.tracker.update(*detections(figure(800), figure(1100)), at=index / 25)

    readings = subject.evaluate(at=99 / 25)

    assert batches == [(3, preprocess.NUM_CLIPS, 2, preprocess.CLIP_LEN, 17, 3)]
    assert [reading.members for reading in readings] == [(1,), (2,), (1, 2)]
    assert readings[2].top(1) == [("A50", 1.0)]


def test_classification_averages_the_softmax_of_each_clip(monkeypatch):
    """MMAction2 averages probabilities, not logits ('average_clips': 'prob')."""
    logits = np.zeros((2, 120), dtype=np.float32)
    logits[0, 0], logits[1, 1] = 10.0, 0.0

    class Session:
        def run(self, outputs, feeds):
            assert feeds["keypoints"].shape[0] == 2
            return [logits]

    monkeypatch.setattr(model, "session", lambda: Session())
    probabilities = model.classify(np.zeros((1, 2, 2, 100, 17, 3), dtype=np.float32))
    expected = (np.exp(10) / (np.exp(10) + 119) + 1 / 120) / 2
    assert probabilities.shape == (1, 120)
    assert probabilities[0, 0] == pytest.approx(expected)


def test_a_large_batch_runs_in_chunks_with_the_same_result(monkeypatch):
    """GPU memory grows with the batch sent to the network, so it is bounded."""
    sizes = []

    class Session:
        def run(self, outputs, feeds):
            flat = feeds["keypoints"]
            sizes.append(len(flat))
            # Logits that differ per clip, so a misaligned chunk would show.
            logits = np.zeros((len(flat), 120), dtype=np.float32)
            logits[np.arange(len(flat)), flat[:, 0, 0, 0, 0].astype(int)] = 5.0
            return [logits]

    monkeypatch.setattr(model, "session", lambda: Session())
    sequences = 2 * model.CHUNK + 1
    batch = np.zeros((sequences, 2, 2, 100, 17, 3), dtype=np.float32)
    batch[:, :, 0, 0, 0, 0] = np.arange(sequences)[:, None]

    probabilities = model.classify(batch)

    assert max(sizes) == model.CHUNK * 2 and sum(sizes) == sequences * 2
    assert list(probabilities.argmax(axis=1)) == list(range(sequences))


def test_only_the_largest_bodies_are_classified():
    """Performers near the camera, not an audience at the frame's edges."""
    near, far = figure(300, height=500.0), figure(1500, height=150.0)
    frames = track([(near, far)] * 50)
    assert recognizer.groups(frames, max_people=1) == [(1,)]
    assert recognizer.groups(frames, max_people=2) == [(1,), (2,)]


def test_four_people_are_classified_alone_and_in_their_pairs():
    """The cast on stage at once, with someone small at the back left out."""
    cast = [figure(x) for x in (200, 700, 1200, 1700)]
    frames = track([(*cast, figure(950, y=250.0, height=100.0))] * 50)
    found = recognizer.groups(frames)
    assert sorted(group for group in found if len(group) == 1) == [(1,), (2,), (3,), (4,)]
    assert sorted(group for group in found if len(group) == 2) == [(1, 2), (2, 3), (3, 4)]
