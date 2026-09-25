"""Names drawn onto the model's frames, checked on synthetic frames."""

import numpy as np

from sitrep import annotate


def frame(height=360, width=640) -> np.ndarray:
    return np.full((height, width, 3), 60, dtype=np.uint8)


def box(x1, y1, x2, y2) -> np.ndarray:
    return np.array([x1, y1, x2, y2], dtype=np.float32)


def changed(before, after) -> np.ndarray:
    """Mask of pixels the drawing touched."""
    return np.any(before != after, axis=2)


def test_a_frame_with_no_faces_is_returned_unmarked():
    original = frame()
    assert annotate.draw_names(original, []) is original


def test_the_source_frame_is_not_drawn_on():
    """The camera frame is shared with the NDI feed, which stays clean."""
    original = frame()
    copy = original.copy()
    annotate.draw_names(original, [(box(200, 150, 260, 220), "Klara")])
    assert np.array_equal(original, copy)


def test_the_name_is_set_above_the_face():
    original = frame()
    marked = annotate.draw_names(original, [(box(200, 150, 260, 220), "Klara")])
    touched = changed(original, marked)
    assert touched[:150, 200:260].any()          # tag above the box
    assert not touched[230:, :].any()             # nothing below the face


def test_a_face_at_the_top_edge_gets_its_name_below():
    original = frame()
    marked = annotate.draw_names(original, [(box(200, 2, 260, 60), "Klara")])
    assert changed(original, marked)[61:120, 200:260].any()


def test_a_name_with_umlauts_is_drawn():
    """OpenCV's fonts would drop these; the name on the frame has to match
    the name list exactly."""
    original = frame()
    marked = annotate.draw_names(original, [(box(200, 150, 260, 220), "Jürgen Öß")])
    assert changed(original, marked).any()
    assert marked.shape == original.shape and marked.dtype == original.dtype


def test_a_tag_near_the_right_edge_stays_inside_the_frame():
    original = frame()
    marked = annotate.draw_names(original, [(box(600, 150, 639, 220), "Vielleicht: Valentina")])
    assert changed(original, marked)[:150, :600].any()
