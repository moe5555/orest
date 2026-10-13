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
    marked = annotate.draw_names(original, [(box(600, 150, 639, 220), "Valentina Hoffmann")])
    assert changed(original, marked)[:150, :600].any()


RATED = [("Risiko", 4, "red", 5), ("Menschlichkeit", 1, "calm", 5),
         ("Vorhersehbarkeit", -3, "amber", 5)]


def test_pips_fill_by_the_share_of_the_values_scale():
    """One pip per point on a scale of 5; on Aggression's -10 to 10, one per
    two, rounded up so that any value but 0 shows."""
    assert [annotate._filled(value, 5) for value in (0, 1, 3, -3, 5)] == [0, 1, 3, 3, 5]
    assert [annotate._filled(value, 10) for value in (0, 1, 2, 3, 4, -7, 10, -10)] == \
        [0, 1, 1, 2, 2, 4, 5, 5]


def test_a_value_of_two_digits_and_a_sign_fits_its_panel():
    original = frame()
    rows = [("Aggression", -10, "calm", 10)]
    marked = annotate.draw_ratings(original, [(box(100, 150, 160, 300), "Alex", rows)])
    assert changed(original, marked)[150:300, 165:].any()
    assert marked.shape == original.shape


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


LABELS = ["Risiko", "Menschlichkeit", "Vorhersehbarkeit"]


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
    # 720p: at 640 px a slot is narrower than three rating rows at the
    # smallest legible size.
    original = frame(720, 1280)
    marked = annotate.draw_ratings_strip(original, [(box(800, 300, 920, 600), "Klara", RATED)],
                                         {"Klara": 3}, LABELS)
    strip = marked[720:]
    ground = np.array(annotate.DISPLAY.tag[::-1])
    assert np.any(strip[:, 960:] != ground)                  # slot 3 of 4
    assert np.all(strip[:, :960] == ground)                  # the others stay empty
    line = np.all(marked[601:720] == annotate.LINK[::-1], axis=2)  # between box foot and strip
    assert line.any()


def test_a_person_without_ratings_gets_no_slot_panel():
    original = frame()
    marked = annotate.draw_ratings_strip(original, [(box(100, 150, 160, 300), "Körper 7", [])],
                                         {}, LABELS)
    assert np.all(marked[360:] == np.array(annotate.DISPLAY.tag[::-1]))
    assert changed(original, marked[:360]).any()             # boxed and named in the picture


def test_the_models_frames_keep_the_yellow_box_and_the_operators_follow_the_ci():
    """The model reads names off the plain tag; the CI applies to the operator's picture only."""
    original = frame()
    named = [(box(200, 150, 260, 220), "Klara")]
    model = annotate.draw_names(original, named)[..., ::-1]
    display = annotate.draw_names(original, named, annotate.DISPLAY)[..., ::-1]
    assert np.all(model == annotate.MODEL.box, axis=2).any()
    assert not np.all(display == annotate.MODEL.box, axis=2).any()
    assert np.all(display == annotate.DISPLAY.box, axis=2).any()
    assert changed(original, model[..., ::-1])[220, 218:242].any()        # a closed box
    assert not changed(original, display[..., ::-1])[220, 218:242].any()  # its corners only


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


def test_a_region_is_outlined_on_a_copy():
    frame = np.zeros((100, 100, 3), dtype=np.uint8)
    marked = annotate.draw_region(frame, np.array([[10, 10], [90, 10], [90, 90], [10, 90]]))
    assert not frame.any()
    assert marked[10, 50].any() and not marked[50, 50].any()
