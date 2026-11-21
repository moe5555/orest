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
         ("Berechenbarkeit", -3, "amber", 5)]


def test_pips_fill_by_the_share_of_the_values_scale():
    """One pip per point on a scale of 5; on Aggression's -10 to 10, one per
    two, rounded up so that any value but 0 shows."""
    assert [annotate._filled(value, 5) for value in (0, 1, 3, -3, 5)] == [0, 1, 3, 3, 5]
    assert [annotate._filled(value, 10) for value in (0, 1, 2, 3, 4, -7, 10, -10)] == \
        [0, 1, 1, 2, 2, 4, 5, 5]


LABELS = ["Risiko", "Menschlichkeit", "Berechenbarkeit"]


def test_a_value_of_two_digits_and_a_sign_fits_its_card():
    original = frame(720, 1280)
    rows = [("Aggression", -10, "calm", 10)]
    marked = annotate.draw_ratings_sides(original, [(box(800, 300, 920, 600), "Alex", rows)],
                                         {"Alex": 0}, ["Aggression"], widest=10)
    band = band_width(marked)
    gap = round(1280 * annotate.SIDE_GAP_SHARE)
    panel = np.array(annotate.PANEL[::-1])
    card = np.flatnonzero(np.all(marked[:, :band] == panel, axis=2).any(axis=0))
    assert card.size and card[-1] < band - gap


def test_the_source_frame_stays_clean_when_ratings_are_drawn():
    original = frame(720, 1280)
    copy = original.copy()
    annotate.draw_ratings_sides(original, [(box(800, 300, 920, 600), "Klara", RATED)],
                                {"Klara": 0}, LABELS)
    assert np.array_equal(original, copy)


def test_a_high_risiko_is_drawn_in_red():
    original = frame(720, 1280)
    marked = annotate.draw_ratings_sides(original, [(box(800, 300, 920, 600), "Klara", RATED)],
                                         {"Klara": 0}, LABELS)
    red = annotate.LEVEL["red"]
    rgb = marked[..., ::-1]
    assert np.all(rgb == red, axis=2).any()


def test_a_bodys_ratings_stand_above_its_head_and_take_no_band():
    original = frame(720, 1280)
    marked = annotate.draw_ratings_sides(original, [(box(600, 400, 700, 700), "Körper 7", RATED)],
                                         {"Körper 7": 0}, LABELS, overhead={"Körper 7"})
    band = band_width(marked)
    ground = np.array(annotate.DISPLAY.tag[::-1])
    assert np.all(marked[:, :band] == ground)                            # the bands stay empty
    assert np.all(marked[:, band + 1280:] == ground)
    picture = marked[:400, band:band + 1280]
    card = np.all(picture == np.array(annotate.PANEL[::-1]), axis=2)
    rows, columns = np.nonzero(card)
    assert rows.max() < 400 - 20                                         # above the name's tag
    assert columns.min() < 650 < columns.max()                           # centred on the body


def band_width(marked, picture_width=1280) -> int:
    """Width of each band of a frame from draw_ratings_sides."""
    return (marked.shape[1] - picture_width) // 2


def test_the_picture_keeps_its_size_between_the_bands():
    """The frame is the picture widened by a band to each side, whether or not anyone is rated."""
    original = frame(720, 1280)
    empty = annotate.draw_ratings_sides(original, [], {}, LABELS)
    rated = annotate.draw_ratings_sides(original, [(box(800, 300, 920, 600), "Klara", RATED)],
                                        {"Klara": 1}, LABELS)
    band = round(1280 * annotate.SIDE_BAND_SHARE)
    assert empty.shape == rated.shape == (720, 1280 + 2 * band, 3)
    # Inside its frame, the picture is the camera's.
    assert np.array_equal(empty[30:-30, band + 30:band + 1280 - 30], original[30:-30, 30:-30])


def test_the_picture_is_framed_and_the_cards_stand_clear_of_the_frame():
    original = frame(720, 1280)
    marked = annotate.draw_ratings_sides(original, [(box(800, 300, 920, 600), "Klara", RATED)],
                                         {"Klara": 0}, LABELS)
    band = band_width(marked)
    gap = round(1280 * annotate.SIDE_GAP_SHARE)
    rule, panel = np.array(annotate.RULE[::-1]), np.array(annotate.PANEL[::-1])
    assert np.all(marked[[0, -1], band:band + 1280] == rule)        # top and bottom edges
    assert np.mean(np.all(marked[:, band] == rule, axis=1)) > 0.95  # left edge, crossed by the line
    card = np.flatnonzero(np.all(marked[:, :band] == panel, axis=2).any(axis=0))
    assert card.size and card[-1] < band - gap
    assert not np.all(marked[:, band - gap:band] == rule, axis=2).any()


def test_ratings_on_the_sides_stand_in_their_band_tied_to_the_box_by_a_white_line():
    original = frame(720, 1280)
    marked = annotate.draw_ratings_sides(original, [(box(800, 300, 920, 600), "Klara", RATED)],
                                         {"Klara": 0}, LABELS)
    band = band_width(marked)
    ground = np.array(annotate.DISPLAY.tag[::-1])
    assert np.any(marked[:, :band] != ground)                       # the left band's card
    assert np.all(marked[:, band + 1280:] == ground)                # the right band stays empty
    left_of_box = marked[:, band:band + 800 - 2]
    assert np.all(left_of_box == annotate.LINK[::-1], axis=2).any()


def test_a_person_without_ratings_or_a_side_gets_no_card():
    original = frame(720, 1280)
    marked = annotate.draw_ratings_sides(
        original, [(box(100, 150, 160, 300), "Körper 7", []),
                   (box(800, 300, 920, 600), "Klara", RATED)], {"Klara": 2}, LABELS)
    band = band_width(marked)
    ground = np.array(annotate.DISPLAY.tag[::-1])
    assert np.all(marked[:, :band] == ground)
    assert np.all(marked[:, band + 1280:] == ground)


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
    assert slots.assign([("Orest", 0.8)], now=0) == {"Orest": 1}


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
