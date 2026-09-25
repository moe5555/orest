"""Track association and the window roster.

The tracker fails quietly: a wrong association produces a plausible roster in
which two people have been merged, and a dropped track renumbers someone who
never left. These tests pin the behaviour the SITREP roster depends on, and
need no model, camera or video.
"""

from datetime import datetime, timedelta

import numpy as np
import pytest

from face import gallery
from sitrep import presence

START = datetime(2026, 9, 24, 19, 0, 0)


def unit(*values) -> np.ndarray:
    """A normalised embedding pointing in a named direction."""
    vector = np.zeros(8, dtype=np.float32)
    for index, value in values:
        vector[index] = value
    return vector / np.linalg.norm(vector)


class Face:
    """Stands in for a detection, which the tracker asks for its size and box."""

    def __init__(self, size=80.0, bbox=(10.0, 20.0, 90.0, 100.0)):
        self.size = size
        self.bbox = np.array(bbox, dtype=np.float32)


def tracker(cast=None) -> presence.PresenceTracker:
    """A tracker with no source; passes are driven through `_link` directly."""
    return presence.PresenceTracker(source=None, cast=cast)


def pass_of(subject, vectors, faces=None, at=START):
    """Run one association pass with the given embeddings.

    Mirrors `observe` with the detection and embedding steps replaced, so the
    association logic is exercised without a model.
    """
    faces = faces or [Face() for _ in vectors]
    stacked = np.stack(vectors)
    matches = subject.cast.match(stacked, threshold=subject._threshold) if subject.cast else []
    with subject._lock:
        subject._forget(at)
        touched = subject._link(faces, stacked, matches, at)
        subject._adopt(touched, matches)
        subject._merge_by_name()
    return touched


def test_a_track_keeps_the_box_of_its_latest_sighting():
    """The box is where the name is drawn, so it must follow the person."""
    subject = tracker()
    face = unit((0, 1.0))
    pass_of(subject, [face], faces=[Face(bbox=(0, 0, 50, 50))])
    touched = pass_of(subject, [face], faces=[Face(bbox=(100, 0, 150, 50))],
                      at=START + timedelta(seconds=1))
    assert touched[0].box.tolist() == [100, 0, 150, 50]


def test_naming_a_frame_pairs_each_face_with_its_track_label(monkeypatch):
    """name_faces is what annotate.py draws, so each box must carry the name
    of the track its face joined, in detection order."""
    subject = tracker(cast_of("klara"))
    faces = [Face(bbox=(0, 0, 50, 50)), Face(bbox=(100, 0, 150, 50))]
    monkeypatch.setattr(presence.detect, "detect", lambda frame, size: faces)
    monkeypatch.setattr(presence.embed, "embed",
                        lambda frame, found: np.stack([unit((0, 1.0)), unit((5, 1.0))]))

    named = subject.name_faces(np.zeros((200, 200, 3), dtype=np.uint8))

    assert [box.tolist() for box, _ in named] == [[0, 0, 50, 50], [100, 0, 150, 50]]
    assert named[0][1] == "klara"
    assert named[1][1].startswith(presence.UNSURE)
    assert subject.passes == 1


def test_each_new_face_starts_its_own_track():
    subject = tracker()
    touched = pass_of(subject, [unit((0, 1.0)), unit((1, 1.0))])
    assert len({track.guess for track in touched}) == 2


def test_an_unrecognised_face_is_guessed_at_rather_than_numbered():
    subject = tracker(cast_of("klara"))
    track = pass_of(subject, [unit((6, 1.0))])[0]
    assert track.name is None
    assert track.guess.startswith(presence.UNSURE)
    assert track.guess.removeprefix(presence.UNSURE).strip() in presence.NAMES
    assert track.label == track.guess


def test_a_guess_holds_for_the_life_of_the_track():
    subject = tracker()
    first = pass_of(subject, [unit((0, 1.0))])[0]
    guess = first.guess
    pass_of(subject, [unit((0, 1.0))], at=START + timedelta(seconds=1))
    assert first.guess == guess


def test_two_people_are_never_guessed_at_alike_at_once():
    subject = tracker()
    touched = pass_of(subject, [unit(*[(index, 1.0)]) for index in range(8)])
    assert len({track.guess for track in touched}) == 8


def test_a_guess_gives_way_to_the_real_name():
    subject = tracker()
    track = pass_of(subject, [unit((0, 1.0))])[0]
    assert track.label == track.guess

    subject.cast = cast_of("klara")
    pass_of(subject, [unit((0, 1.0))], at=START + timedelta(seconds=1))
    assert track.name == "klara"
    assert track.label == "klara"


def test_the_same_face_rejoins_its_track():
    subject = tracker()
    first = pass_of(subject, [unit((0, 1.0))])[0]
    again = pass_of(subject, [unit((0, 1.0), (1, 0.2))], at=START + timedelta(seconds=1))[0]
    assert again is first
    assert first.sightings == 2


def test_a_different_face_does_not_join_an_existing_track():
    """Different people sit far below the link threshold and must stay apart."""
    subject = tracker()
    pass_of(subject, [unit((0, 1.0))])
    first = subject._tracks[0]
    second = pass_of(subject, [unit((3, 1.0))], at=START + timedelta(seconds=1))[0]
    assert second is not first
    assert second.sightings == 1


def test_two_people_are_not_swapped_when_both_are_present():
    subject = tracker()
    first, second = pass_of(subject, [unit((0, 1.0)), unit((3, 1.0))])
    again = pass_of(subject, [unit((3, 1.0), (4, 0.1)), unit((0, 1.0), (1, 0.1))],
                    at=START + timedelta(seconds=1))
    assert again[0] is second
    assert again[1] is first


def test_one_face_cannot_claim_two_tracks():
    """Near-identical detections of one person must not absorb a second track."""
    subject = tracker()
    pass_of(subject, [unit((0, 1.0)), unit((0, 1.0), (1, 0.05))])
    touched = pass_of(subject, [unit((0, 1.0))], at=START + timedelta(seconds=1))
    assert len(touched) == 1
    assert len({id(track) for track in subject._tracks}) == 2


def test_a_track_is_closed_once_it_has_not_been_seen_for_long_enough():
    subject = tracker()
    pass_of(subject, [unit((0, 1.0))])
    first = subject._tracks[0]
    later = START + timedelta(seconds=presence.FORGET + 1)
    returned = pass_of(subject, [unit((0, 1.0))], at=later)[0]
    assert returned is not first
    assert returned.sightings == 1


def test_a_track_survives_a_gap_shorter_than_the_forget_window():
    subject = tracker()
    first = pass_of(subject, [unit((0, 1.0))])[0]
    later = START + timedelta(seconds=presence.FORGET - 1)
    assert pass_of(subject, [unit((0, 1.0))], at=later)[0] is first


def test_a_track_keeps_its_clearest_faces():
    """The vectors kept have to be the largest faces, not the most recent."""
    subject = tracker()
    track = pass_of(subject, [unit((0, 1.0))], faces=[Face(200.0)])[0]
    for index in range(presence.TRACK_VECTORS + 3):
        track.observe(unit((0, 1.0), (1, 0.01 * index)), 20.0 + index, START)
    assert len(track.vectors) == presence.TRACK_VECTORS
    assert max(track.sizes) == 200.0
    assert min(track.sizes) > 20.0


def cast_of(*names) -> gallery.Gallery:
    """A gallery with one enrolled face per name, each in its own direction."""
    vectors = [unit((index, 1.0)) for index in range(len(names))]
    return gallery.Gallery(list(names), np.stack(vectors),
                           np.arange(len(names)), [None] * len(names))


def test_a_track_takes_the_name_its_face_matches():
    subject = tracker(cast_of("klara", "moritz"))
    track = pass_of(subject, [unit((1, 1.0), (5, 0.3))])[0]
    assert track.name == "moritz"
    assert track.label == "moritz"


def test_a_name_improves_when_the_person_turns_towards_the_camera():
    """A distant sighting names the track; a closer one raises its confidence."""
    subject = tracker(cast_of("klara"))
    track = pass_of(subject, [unit((0, 1.0), (6, 1.6))])[0]
    distant = track.similarity
    pass_of(subject, [unit((0, 1.0), (6, 0.2))], at=START + timedelta(seconds=1))
    assert track.name == "klara"
    assert track.similarity > distant


def test_a_named_track_is_not_renamed_by_a_weaker_match():
    subject = tracker(cast_of("klara", "moritz"))
    track = pass_of(subject, [unit((0, 1.0))])[0]
    assert track.similarity == pytest.approx(1.0, abs=1e-5)
    pass_of(subject, [unit((0, 1.0), (1, 0.9))], at=START + timedelta(seconds=1))
    assert track.name == "klara"


def test_the_roster_reports_everyone_currently_tracked():
    subject = tracker(cast_of("klara"))
    pass_of(subject, [unit((0, 1.0)), unit((5, 1.0))])
    roster = subject.roster()
    assert [person.known for person in roster] == [True, False]
    assert roster[0].label == "klara"
    assert roster[1].label.startswith(presence.UNSURE)


def test_the_roster_excludes_people_who_left_before_the_window():
    subject = tracker()
    pass_of(subject, [unit((0, 1.0))])
    window = START + timedelta(seconds=10)
    pass_of(subject, [unit((5, 1.0))], at=window)
    roster = subject.roster(since=window)
    assert [person.guess for person in roster] == [subject._tracks[-1].guess]


def test_the_roster_clips_times_to_the_window_it_reports_on():
    """A person present before the window opened is reported from its start."""
    subject = tracker()
    pass_of(subject, [unit((0, 1.0))])
    window = START + timedelta(seconds=5)
    pass_of(subject, [unit((0, 1.0))], at=window + timedelta(seconds=20))
    person = subject.roster(since=window, until=window + timedelta(seconds=30))[0]
    assert person.first_seen == window
    assert person.seconds == 20.0


def test_the_roster_is_ordered_by_first_appearance():
    subject = tracker()
    pass_of(subject, [unit((3, 1.0))])
    pass_of(subject, [unit((3, 1.0)), unit((0, 1.0))], at=START + timedelta(seconds=1))
    assert [person.guess for person in subject.roster()] == [track.guess for track in subject._tracks]


def test_every_face_reaches_the_roster_at_once():
    """Everyone in the room is accounted for, including on their first sighting."""
    subject = tracker()
    pass_of(subject, [unit((0, 1.0))])
    roster = subject.roster()
    assert len(roster) == 1
    assert roster[0].sightings == 1


def test_a_name_reunites_a_person_whose_track_was_split():
    """Two views of one face can fall below the link threshold; the name cannot.

    This is what the enrolment photographs buy beyond identification: a
    gallery holding several angles of a person recognises a view their own
    track has never seen, and the name carries the track across the turn.
    """
    frontal, profile = unit((0, 1.0)), unit((6, 1.0))
    klara = gallery.Gallery(["klara"], np.stack([frontal, profile]),
                            np.array([0, 0]), [None, None])
    subject = tracker(klara)

    track = pass_of(subject, [frontal])[0]
    assert track.name == "klara"
    assert float(track.vectors[0] @ profile) < presence.LINK

    again = pass_of(subject, [profile], at=START + timedelta(seconds=1))[0]
    assert again is track
    assert again.sightings == 2


def test_two_tracks_that_turn_out_to_be_one_person_are_merged():
    subject = tracker()
    first = pass_of(subject, [unit((0, 1.0))], faces=[Face(40.0)])[0]
    second = pass_of(subject, [unit((4, 1.0))], at=START + timedelta(seconds=1))[0]
    assert len(subject._tracks) == 2

    # Both tracks turn out to be the same cast member once the gallery is known.
    subject.cast = cast_of("klara")
    first.name = second.name = "klara"
    first.similarity, second.similarity = 0.5, 0.7
    with subject._lock:
        subject._merge_by_name()

    assert len(subject._tracks) == 1
    survivor = subject._tracks[0]
    assert survivor is first
    assert survivor.guess == first.guess
    assert survivor.sightings == 2
    assert survivor.similarity == 0.7
    assert survivor.last_seen == second.last_seen


def test_merging_keeps_the_absorbed_track_faces():
    subject = tracker()
    first = pass_of(subject, [unit((0, 1.0))], faces=[Face(40.0)])[0]
    second = pass_of(subject, [unit((4, 1.0))], faces=[Face(90.0)],
                     at=START + timedelta(seconds=1))[0]
    first.name = second.name = "klara"
    with subject._lock:
        subject._merge_by_name()
    assert 90.0 in subject._tracks[0].sizes


def test_a_replay_starting_at_the_beginning_can_age_its_tracks(tmp_path):
    """Footage time is counted from a reference the forget window cannot
    underflow, so a replay from the first frame is not a special case."""
    at = presence.REPLAY_EPOCH
    assert at - timedelta(seconds=presence.FORGET) > datetime.min

    subject = tracker()
    first = pass_of(subject, [unit((0, 1.0))], at=at)[0]
    assert pass_of(subject, [unit((0, 1.0))], at=at + timedelta(seconds=1))[0] is first
