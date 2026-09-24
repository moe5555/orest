"""Face alignment and gallery matching, the two places identity can go wrong quietly.

A misfitted alignment still produces a 512-vector and a gallery still returns a
name; neither raises. These tests pin the properties identification depends on,
and need no model, GPU or video.
"""

import numpy as np
import pytest

from face import embed, gallery

# Five landmarks in the canonical positions ArcFace expects.
REFERENCE = embed.REFERENCE


def rotate(points, degrees, scale=1.0, shift=(0.0, 0.0)):
    """Apply a similarity transform to landmark points."""
    angle = np.radians(degrees)
    matrix = scale * np.array([[np.cos(angle), -np.sin(angle)],
                               [np.sin(angle), np.cos(angle)]])
    return (points @ matrix.T + np.array(shift)).astype(np.float32)


def test_reference_landmarks_map_to_themselves():
    matrix = embed._similarity_transform(REFERENCE, REFERENCE)
    assert matrix[:, :2] == pytest.approx(np.eye(2), abs=1e-4)
    assert matrix[:, 2] == pytest.approx(np.zeros(2), abs=1e-3)


@pytest.mark.parametrize("degrees", [-30, -5, 0, 5, 30])
@pytest.mark.parametrize("scale", [0.25, 1.0, 4.0])
def test_a_tilted_face_is_warped_back_onto_the_reference(degrees, scale):
    """A head tilted or seen from further away lands in the same crop position."""
    observed = rotate(REFERENCE, degrees, scale, shift=(120.0, -40.0))
    matrix = embed._similarity_transform(observed, REFERENCE)

    homogeneous = np.hstack([observed, np.ones((5, 1))])
    assert homogeneous @ matrix.T == pytest.approx(REFERENCE, abs=1e-3)


def test_the_transform_does_not_mirror():
    """A face must not be flipped to fit; a mirrored crop embeds as someone else."""
    mirrored = REFERENCE.copy()
    mirrored[:, 0] = embed.CROP_SIZE - mirrored[:, 0]
    matrix = embed._similarity_transform(mirrored, REFERENCE)
    assert np.linalg.det(matrix[:, :2]) > 0


def unit(*values) -> np.ndarray:
    """A normalised embedding pointing in a named direction."""
    vector = np.zeros(8, dtype=np.float32)
    for index, value in values:
        vector[index] = value
    return vector / np.linalg.norm(vector)


def small_gallery() -> gallery.Gallery:
    """Two people, two enrolment faces each, in a toy embedding space."""
    return gallery.Gallery(
        names=["klara", "moritz"],
        vectors=np.stack([unit((0, 1.0)), unit((0, 1.0), (1, 0.3)),
                          unit((2, 1.0)), unit((2, 1.0), (3, 0.3))]),
        owners=np.array([0, 0, 1, 1]),
        sources=[None] * 4,
    )


def test_a_probe_is_named_from_its_closest_enrolment():
    matches = small_gallery().match(np.stack([unit((0, 1.0), (1, 0.2)), unit((2, 1.0))]))
    assert [match.name for match in matches] == ["klara", "moritz"]


def test_an_unenrolled_face_is_unknown_rather_than_the_nearest_name():
    matches = small_gallery().match(unit((5, 1.0))[None, :])
    assert matches[0].name is None
    assert not matches[0].known


def test_the_threshold_is_what_decides_a_name():
    probe = unit((0, 1.0), (4, 1.4))[None, :]
    assert small_gallery().match(probe, threshold=0.9)[0].name is None
    assert small_gallery().match(probe, threshold=0.4)[0].name == "klara"


def test_a_person_is_matched_on_their_best_enrolment_not_their_average():
    """One usable enrolment image is enough, and adding images cannot hurt."""
    people = small_gallery()
    probe = people.vectors[1][None, :]
    assert people.match(probe)[0].similarity == pytest.approx(1.0, abs=1e-5)


def test_counts_report_the_enrolment_per_person():
    assert small_gallery().counts() == {"klara": 2, "moritz": 2}


def test_separation_excludes_a_face_matching_itself():
    """The diagonal has to measure enrolment consistency, not the identity 1.0."""
    pairs = small_gallery().separation()
    assert pairs[0, 0] < 1.0
    assert pairs[0, 1] < pairs[0, 0]
