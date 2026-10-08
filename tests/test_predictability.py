"""Vorhersehbarkeit: live movement scored against a rehearsal corpus, on synthetic vectors."""

from datetime import datetime, timedelta

import numpy as np
import pytest
from apollon_pose import keypoints as pose

from action import recognizer, sitrep_map, tracking
from sitrep import actions, lage, predictability, report

T0 = datetime(2026, 10, 7, 20, 0, 0)

MAPPING = sitrep_map.load()


def unit(vectors) -> np.ndarray:
    vectors = np.asarray(vectors, dtype=np.float32)
    return vectors / np.linalg.norm(vectors, axis=-1, keepdims=True)


def corpus(count=400, dims=32, seed=0) -> predictability.Reference:
    """Segments in ten recordings, each a step along a slow random walk, so
    every segment has near neighbours outside its own span."""
    rng = np.random.default_rng(seed)
    vectors = unit(np.cumsum(rng.normal(size=(count, dims)), axis=0)
                   + rng.normal(scale=3.0, size=(count, dims)))
    media = np.arange(count) % 10
    start = (np.arange(count) // 10) * 2.0
    return predictability.calibrate(vectors, media, start, "synthetic")


def test_the_corpus_median_reads_zero_and_the_extremes_five():
    quantiles = np.linspace(0.2, 0.9, predictability.QUANTILES)
    median = quantiles[predictability.QUANTILES // 2]
    assert predictability.score(np.array(median), quantiles) == pytest.approx(0.0, abs=1e-6)
    assert predictability.score(np.array(0.95), quantiles) == predictability.SCALE
    assert predictability.score(np.array(0.1), quantiles) == -predictability.SCALE


def test_the_score_rises_with_similarity_and_stays_on_its_scale():
    quantiles = np.linspace(0.2, 0.9, predictability.QUANTILES)
    scores = predictability.score(np.linspace(0.0, 1.0, 50), quantiles)
    assert np.all(np.diff(scores) >= 0)
    assert scores.min() == -predictability.SCALE and scores.max() == predictability.SCALE


def test_ordinary_rehearsed_movement_lies_near_zero():
    """Half the corpus within about +-1.5: the quartiles of the calibration
    distribution, through the normal quantile."""
    quantiles = np.linspace(0.2, 0.9, predictability.QUANTILES)
    quartiles = quantiles[[predictability.QUANTILES // 4, 3 * predictability.QUANTILES // 4]]
    assert np.abs(predictability.score(quartiles, quantiles)) == pytest.approx([1.45, 1.45], abs=0.05)


def test_a_movement_from_the_corpus_is_predictable_and_a_new_one_is_not():
    reference = corpus()
    rng = np.random.default_rng(1)
    rehearsed = reference.vectors[17]
    unseen = unit(rng.normal(size=reference.vectors.shape[1]))
    rehearsed_score, unseen_score = reference.score(reference.similarity(np.stack([rehearsed, unseen])))
    assert rehearsed_score == predictability.SCALE
    assert unseen_score == -predictability.SCALE


def test_calibration_leaves_out_the_segments_beside_each_one():
    """A held posture repeats in the overlapping segments of its own span;
    matched against them it would always find itself."""
    vectors = unit([[1, 0], [1, 0], [0, 1], [0.6, 0.8]])
    media = np.array([1, 1, 2, 2])
    start = np.array([0.0, 2.0, 0.0, 100.0])
    best = predictability.nearest_within(vectors, media, start, exclude=30.0)
    # The first two lie within 30 s of each other in one recording: each
    # matches the nearer of the other recording's two segments instead.
    assert best[:2] == pytest.approx([0.6, 0.6])
    assert best[2] == pytest.approx(0.8)


def test_calibration_drops_segments_without_a_body():
    vectors = np.zeros((5, 4), dtype=np.float32)
    vectors[:4] = unit([[1, 0, 0, 0], [0.9, 0.1, 0, 0], [0, 1, 0, 0], [0, 0.9, 0.1, 0]])
    reference = predictability.calibrate(vectors, np.array([1, 2, 1, 2, 3]),
                                         np.array([0.0, 0, 60, 60, 0]), exclude=30.0)
    assert len(reference.vectors) == 4 and 3 not in reference.media


def test_a_reference_survives_saving(tmp_path):
    reference = corpus(count=60)
    path = tmp_path / "reference.npz"
    reference.save(path)
    loaded = predictability.load(path)
    assert np.array_equal(loaded.vectors, reference.vectors)
    assert np.array_equal(loaded.quantiles, reference.quantiles)
    assert loaded.source == "synthetic"
    assert "60 segments from 10 recordings" in predictability.describe(loaded)


def skeleton(shift: float, lift: float = 0.0) -> tuple[np.ndarray, np.ndarray]:
    """A standing body, its right wrist raised by `lift` torso lengths."""
    points = np.array([[0, -60], [-5, -65], [5, -65], [-10, -62], [10, -62],
                       [-20, -40], [20, -40], [-25, -15], [25, -15], [-28, 10], [28, 10],
                       [-12, 0], [12, 0], [-12, 40], [12, 40], [-12, 80], [12, 80]],
                      dtype=np.float32)
    points[pose.COCO_KEYPOINTS.index("right_wrist")] += [0, -40 * lift]
    return points + [shift, 0], np.ones(pose.NUM_KEYPOINTS, dtype=np.float32)


def test_a_body_is_encoded_live_as_the_corpus_encodes_it_alone():
    """The same movement must land on the same vector live and in the index,
    or the score measures the encoders rather than the movement."""
    frames, detections = [], []
    for index in range(100):
        points, scores = skeleton(300.0, lift=index / 99)
        bodies = {7: tracking.Body(points, scores, tracking.box(points, scores))}
        if index % 10 == 0:
            other, other_scores = skeleton(50.0)
            bodies[9] = tracking.Body(other, other_scores, tracking.box(other, other_scores))
        frames.append(tracking.Frame(index / 25, bodies))
        detections.append((points[None], scores[None]))
    live = predictability.window_embedding(frames, 7)
    assert live == pytest.approx(pose.segment_embedding(detections))


def test_a_body_absent_from_the_window_has_no_encoding():
    frames = [tracking.Frame(index / 25, {}) for index in range(100)]
    assert predictability.window_embedding(frames, 7) is None


def evidence(at, score, members=(1,)):
    return actions.Evidence(at, members, np.zeros(2), ("", ""), score)


def test_a_report_rates_a_person_on_the_mean_of_their_scores():
    records = [evidence(T0, -4.0), evidence(T0, -1.0), evidence(T0, 0.6),
               evidence(T0, None, members=(1, 2))]
    (klara,) = actions.rate(records, {1: "Klara", 2: "Orest"})[:1]
    assert klara.vorhersehbarkeit == -1


def test_without_scores_vorhersehbarkeit_is_not_measured():
    rated = actions.rate([evidence(T0, None)], {1: "Klara"})
    assert rated[0].vorhersehbarkeit is None


def test_only_bodies_classified_alone_carry_a_score():
    subject = actions.ActionRatings(source=None, faces=None, mapping=MAPPING)
    readings = [recognizer.Reading(0.0, (1,), np.full(120, 1 / 120)),
                recognizer.Reading(0.0, (1, 2), np.full(120, 1 / 120))]
    subject.record(readings, T0, {1: 2.5, 2: -3.0})
    records, _ = subject.since(T0 - timedelta(seconds=1))
    assert [record.vorhersehbarkeit for record in records] == [2.5, None]


def test_live_vorhersehbarkeit_is_the_mean_of_the_last_seconds():
    old = T0 - timedelta(seconds=lage.SMOOTHING + 1)
    readings = [evidence(old, -5.0), evidence(T0 - timedelta(seconds=2), 1.0),
                evidence(T0, 2.0)]
    wert = lage.stand(readings, {1: "Klara"}, [], T0).personen["Klara"][report.VORHERSEHBARKEIT]
    assert (wert.wert, wert.staerke, wert.zeit) == (2, 1.5, T0)


def test_live_vorhersehbarkeit_is_absent_without_recent_scores():
    readings = [evidence(T0 - timedelta(seconds=lage.SMOOTHING + 1), -5.0), evidence(T0, None)]
    werte = lage.stand(readings, {1: "Klara"}, [], T0).personen["Klara"]
    assert report.VORHERSEHBARKEIT not in werte
    assert set(werte) == set(report.GEMESSEN)


def test_vorhersehbarkeit_raises_no_alarm():
    readings = [evidence(T0, -5.0)]
    assert not lage.stand(readings, {1: "Klara"}, [], T0).alarm.aktiv
