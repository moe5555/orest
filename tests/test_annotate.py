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


RATED = [("Risiko", 4, "red"), ("Menschlichkeit", 1, "calm")]


def test_a_frame_with_nobody_to_rate_is_returned_unmarked():
    original = frame()
    assert annotate.draw_ratings(original, []) is original


def test_ratings_are_set_beside_the_box_and_the_source_frame_stays_clean():
    original = frame()
    copy = original.copy()
    marked = annotate.draw_ratings(original, [(box(100, 150, 160, 300), "Klara", RATED)])
    assert np.array_equal(original, copy)
    touched = changed(original, marked)
    assert touched[150:300, 165:].any()          # panel right of the box
    assert not touched[:, :95].any()             # nothing left of it


def test_ratings_of_a_box_at_the_right_edge_are_set_left_of_it():
    original = frame()
    marked = annotate.draw_ratings(original, [(box(560, 150, 639, 300), "Klara", RATED)])
    assert changed(original, marked)[150:300, :555].any()


def test_a_high_risiko_is_drawn_in_red():
    original = frame()
    marked = annotate.draw_ratings(original, [(box(100, 150, 160, 300), "Klara", RATED)])
    red = annotate.LEVEL["red"]
    rgb = marked[..., ::-1]
    assert np.all(rgb == red, axis=2).any()


LABELS = ["Risiko", "Menschlichkeit"]


def test_the_strip_lies_beneath_the_picture_and_keeps_its_height():
    """The picture keeps its size whether or not anyone is rated."""
    original = frame()
    empty = annotate.draw_ratings_strip(original, [], {}, LABELS)
    rated = annotate.draw_ratings_strip(original, [(box(100, 150, 160, 300), "Klara", RATED)],
                                        {"Klara": 0}, LABELS)
    assert empty.shape == rated.shape
    assert empty.shape[0] > original.shape[0] and empty.shape[1] == original.shape[1]
    assert np.array_equal(empty[:360], original)


def test_ratings_in_the_strip_stand_in_their_slot_tied_to_the_box_by_a_white_line():
    original = frame()
    marked = annotate.draw_ratings_strip(original, [(box(400, 150, 460, 300), "Klara", RATED)],
                                         {"Klara": 3}, LABELS)
    strip = marked[360:]
    assert np.any(strip[:, 480:] != 0)                       # slot 3 of 4
    assert not np.any(strip[:, :480] != 0)                   # the others stay empty
    white = np.all(marked[301:360] == 255, axis=2)           # between box foot and strip
    assert white.any()


def test_a_person_without_ratings_gets_no_slot_panel():
    original = frame()
    marked = annotate.draw_ratings_strip(original, [(box(100, 150, 160, 300), "Körper 7", [])],
                                         {}, LABELS)
    assert not np.any(marked[360:] != 0)
    assert changed(original, marked[:360]).any()             # boxed and named in the picture


def test_a_person_keeps_their_slot_while_in_view():
    slots = annotate.Slots()
    assert slots.assign([("Klara", 0.1)], now=0) == {"Klara": 0}
    assert slots.assign([("Klara", 0.9)], now=1) == {"Klara": 0}


def test_a_new_person_takes_the_free_slot_nearest_their_place():
    slots = annotate.Slots()
    assert slots.assign([("Klara", 0.1), ("Orest", 0.8)], now=0) == {"Klara": 0, "Orest": 3}


def test_a_slot_is_held_for_a_person_who_left_a_moment_ago():
    slots = annotate.Slots(hold=5)
    slots.assign([("Klara", 0.1)], now=0)
    assert slots.assign([("Orest", 0.1)], now=1) == {"Orest": 1}
    assert slots.assign([("Klara", 0.1), ("Orest", 0.1)], now=2) == {"Klara": 0, "Orest": 1}
    slots.assign([], now=3)
    assert slots.assign([("Elektra", 0.1)], now=10) == {"Elektra": 0}
