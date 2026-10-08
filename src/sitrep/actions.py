"""Risiko, Menschlichkeit and Vorhersehbarkeit per person, measured from what bodies do.

The Pose route under "Calculating Values" in
knowledge/components/02_processing.md. The action recogniser (src/action) runs
beside the SITREP as one more reader of the shared camera, and its readings
become the per-person ratings of the report. Pose runs at 25 frames a second,
so a blow struck between two of the model's sampled stills is still seen.

Three steps turn readings into ratings:

Naming. The recogniser follows bodies, while the report names people by face.
Each time the recogniser classifies, every body whose head joints lie in a
face box the presence tracker saw within FACE_AGE seconds is sighted as that
face's name. A body's cast name is weighed on its sightings rather than taken
from the latest: each sighting is a vote, votes fade with VOTE_HALF_LIFE, and
another cast name replaces the one a body carries only once it leads by SWITCH
votes. A single wrong face, a face track split by a turned head, or a guess
at an unrecognised face therefore does not rename a body the cast gallery
has named; a body the tracker has confused with another person is renamed
within a few seconds. A guess names a body only while no cast name does.
A cast name belongs to one body in view, the one that holds it unless
another leads it by SWITCH votes for that name. A body that has left the
frame keeps its name for what it did while it was there, so a camera cut or a
lost track does not unname its earlier readings. Readings are kept
under the body and named only when a report takes them, so a body named at
any point before then is rated on all its readings, including those made
before its face was seen. A body named neither by a face nor by its
appearance is not rated.

Appearance. Given a memory of appearances (appearance.Appearances), each
naming also describes the bodies in view, and a description that matches a
person adds APPEARANCE_VOTE for them to the same tally the faces vote in.
Face and appearance thus decide one name together: agreeing, they settle it
faster; disagreeing, the face wins, since it votes more per sighting. A name
needs MIN_NAME votes, so one appearance match alone names no one. The memory
learns from bodies whose name is sure, named by hand or confirmed by a cast
face within SURE_AGE seconds, never from appearance alone, so a mistake does
not teach itself.

The operator can name a body by hand (`assign`). The name is absolute: it
holds over every vote until released, and leaves any other body in view that
carried it. Since readings are named when taken, a body named by hand is
rated under that name on everything it did, including before. A face seen on
it in LEARN_SIGHTINGS namings in a row is passed to `on_learn` under that
name, so the face tracker can learn the person while the name holds.

Evidence. A reading's 120 class probabilities are weighed with the
Action-to-SITREP table (action/sitrep_map.csv): the evidence for a rating is
sum over classes of P(class) x table value, its expected value under the
model's own uncertainty. A class the model is unsure of counts for
proportionally less, and the classes the table leaves at 0 count for nothing.
A pair reading counts for both people in it, since NTU does not say which of
them acts.

Rating. Each rating is the peak evidence among the readings a person took part
in, rounded and clipped to 0-5. The peak rather than the mean, because one
blow makes a person dangerous however calm the rest of the window was.

Vorhersehbarkeit. Given a rehearsal reference (predictability.py), each
person classified alone is also encoded over the same window and scored
against the corpus, -5 to +5. A person's Vorhersehbarkeit over a stretch is
the mean of those scores, not a peak: it describes how the person moved over
the stretch, and a single window far from the corpus is as often a tracking
slip as a new movement.

Readings are kept for KEEP seconds and read, never consumed: the live
values (lage.py) read the last few seconds, each stretch of the scene's
summary (chronik.py) and a report asked for read theirs.
"""

import sys
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

import numpy as np

from action import model, recognizer, sitrep_map, tracking

from . import appearance, loudness, predictability, presence, report

# Seconds a face box stays usable for naming a body: two passes of the
# presence tracker, so one missed detection does not leave a body unnamed.
FACE_AGE = 2 * presence.INTERVAL

# How far a head may lie outside a face box, as a share of the box's size, and
# still be named by it. The box can be FACE_AGE old, and a person moves.
FACE_MARGIN = 0.5

# Seconds in which a body's votes for a cast name halve. At one sighting a
# naming step, a steadily named body settles at about five votes, which a
# contrary name overtakes by SWITCH only after five or six sightings in a row.
VOTE_HALF_LIFE = 3.0

# Votes by which another cast name must lead the one a body carries to take
# its place, on that body or on another body in view.
SWITCH = 2.0

# Namings in a row in which the same face must lie on a body named by hand
# before that face is learned under the name: about three seconds at the
# recogniser's step. A face crossing the body for a moment, as in an embrace,
# is not learned.
LEARN_SIGHTINGS = 3

# A matching appearance's vote, beside a face sighting's 1. Two matches in a
# row reach MIN_NAME, while a face seen steadily outweighs an appearance seen
# steadily by more than SWITCH.
APPEARANCE_VOTE = 0.6

# Votes a cast name needs before a body carries it. One face sighting reaches
# it; appearance alone needs two matches in a row.
MIN_NAME = 1.0

# Seconds after a cast face was sighted on a body during which the body's
# appearance is learned under that name.
SURE_AGE = 3.0

# Seconds a body's votes are kept after its last sighting in view. Longer than
# the body tracker's own FORGET, after which the track cannot return.
VOTES_KEPT = 10.0

# COCO-17 joints of the head: nose, eyes, ears.
HEAD = slice(0, 5)

RATING_MAX = 5

# Seconds of readings kept: as long as the summary of the scene may ask about
# (chronik.py), and the same as the loudness levels kept (loudness.KEEP).
KEEP = 600.0


def head(body: tracking.Body) -> np.ndarray | None:
    """Mean position of a body's visible head joints, or None if none is visible."""
    visible = body.scores[HEAD] >= tracking.VISIBLE
    if not visible.any():
        return None
    return body.keypoints[HEAD][visible].mean(axis=0)


def name_bodies(frame: tracking.Frame,
                faces: list[tuple[np.ndarray, str]]) -> dict[int, str]:
    """Each body whose head lies in a face box, with that face's name.

    One face names at most one body and one body takes at most one name. Where
    heads and faces overlap, the head nearest a face's centre is paired first.
    """
    candidates = []
    for track, body in frame.bodies.items():
        point = head(body)
        if point is None:
            continue
        for index, (box, _) in enumerate(faces):
            box = np.asarray(box, dtype=float)
            margin = FACE_MARGIN * max(box[2] - box[0], box[3] - box[1])
            if (box[0] - margin <= point[0] <= box[2] + margin
                    and box[1] - margin <= point[1] <= box[3] + margin):
                centre = (box[:2] + box[2:]) / 2
                candidates.append((float(np.linalg.norm(point - centre)), track, index))

    named: dict[int, str] = {}
    used: set[int] = set()
    for _, track, index in sorted(candidates):
        if track in named or index in used:
            continue
        named[track] = faces[index][1]
        used.add(index)
    return named


@dataclass(frozen=True)
class Evidence:
    """One reading, weighed, and the bodies it counts for."""

    at: datetime
    members: tuple[int, ...]        # body track ids
    values: np.ndarray              # (len(sitrep_map.RATINGS),)
    causes: tuple[str, ...]         # per rating: strongest class and its probability
    # A single person's movement scored against the rehearsals, -5 to +5;
    # None for a pair, or without a reference.
    vorhersehbarkeit: float | None = None


@dataclass(frozen=True)
class Recognised:
    """What one person or pair is doing now, for watching the recogniser live."""

    who: tuple[str, ...]            # names, or "Körper <id>" for an unnamed body
    action: str                     # most probable class
    probability: float
    values: np.ndarray              # evidence per rating, as for Evidence


def weigh(probabilities: np.ndarray,
          mapping: sitrep_map.Mapping) -> tuple[np.ndarray, tuple[str, ...]]:
    """Expected evidence per rating, and the class contributing most to each."""
    contributions = probabilities[:, None] * mapping.evidence
    strongest = contributions.argmax(axis=0)
    causes = tuple(f"{mapping.names[index]} {probabilities[index]:.2f}" for index in strongest)
    return contributions.sum(axis=0), causes


# A gain on Risiko for a stretch of time (loudness.gain_over, for one report).
Gain = Callable[[datetime, datetime], float]


def rate(records: list[Evidence], names: dict[int, str],
         gain: Gain | None = None) -> list[report.Handlung]:
    """Ratings per named person over a stretch of readings, first seen first.

    `names` maps body track ids to people; readings of unnamed bodies count
    for no one. `gain` amplifies each reading's Risiko by how loud the room was
    over the seconds it covers (loudness.py), before the peak is taken.
    """
    people: dict[str, list[Evidence]] = {}
    for record in records:
        for name in dict.fromkeys(names[member] for member in record.members
                                  if member in names):
            people.setdefault(name, []).append(record)

    gains = {id(record): gain(record.at - timedelta(seconds=recognizer.WINDOW), record.at)
             if gain else 1.0 for record in records}
    risiko = sitrep_map.RATINGS.index("risiko")

    def evidence(record: Evidence, column: int) -> float:
        value = float(record.values[column])
        return loudness.amplified(value, gains[id(record)]) if column == risiko else value

    rated = []
    for name, own in people.items():
        fields = {}
        for column, rating in enumerate(sitrep_map.RATINGS):
            peak = max(own, key=lambda record: evidence(record, column))
            value = int(np.clip(np.floor(evidence(peak, column) + 0.5), 0, RATING_MAX))
            fields[rating] = value
            cause = peak.causes[column] if value else ""
            if cause and column == risiko:
                fields["verstaerkung"] = round(gains[id(peak)], 2)
                if gains[id(peak)] > 1.0:
                    cause += f" · laut ×{gains[id(peak)]:.1f}"
            fields[f"anlass_{rating}"] = cause
        fields[report.VORHERSEHBARKEIT] = mean_predictability(own)
        rated.append(report.Handlung(name=name, lesungen=len(own), **fields))
    return rated


def mean_predictability(records: list[Evidence]) -> int | None:
    """The mean Vorhersehbarkeit of the readings that carry one, rounded, or
    None if none does."""
    scores = [record.vorhersehbarkeit for record in records
              if record.vorhersehbarkeit is not None]
    if not scores:
        return None
    return int(np.clip(np.floor(float(np.mean(scores)) + 0.5),
                       -predictability.SCALE, predictability.SCALE))


class ActionRatings:
    """The action recogniser on a shared camera, read as ratings per person.

    Reads the camera and the presence tracker and never closes either. The
    recogniser runs on its own thread; `name`, `record` and `take` can also be
    driven by hand.
    """

    def __init__(self, source, faces: presence.PresenceTracker,
                 mapping: sitrep_map.Mapping | None = None, on_frame=None,
                 on_learn: Callable[[int, str, str], None] | None = None,
                 appearances: appearance.Appearances | None = None,
                 reference: predictability.Reference | None = None):
        self.mapping = mapping or sitrep_map.load()
        # The rehearsal corpus each person's movement is scored against.
        self.reference = reference
        self._faces = faces
        self._names: dict[int, str] = {}
        # Per body, in recogniser time: votes for each cast name, when they
        # were last faded, the latest guess a face sighting made, and when a
        # face was last sighted on it.
        self._votes: dict[int, dict[str, float]] = {}
        self._voted_at: dict[int, float] = {}
        self._guesses: dict[int, str] = {}
        self._sighted_at: dict[int, float] = {}
        # Per body: the face label last sighted on it, and the name the
        # operator gave it.
        self._faces_seen: dict[int, str] = {}
        self._pinned: dict[int, str] = {}
        # Per body named by hand: the face lying on it, and in how many
        # namings in a row. `on_learn(body, face label, name)` receives a
        # face that stayed for LEARN_SIGHTINGS.
        self._steady: dict[int, tuple[str, int]] = {}
        self._on_learn = on_learn
        # Per body: the cast face last sighted on it, and when.
        self._face_sure: dict[int, tuple[str, float]] = {}
        # What each person looks like, and the frame the recogniser saw last,
        # which the bodies of a naming are described on.
        self.appearances = appearances
        self._latest = appearance.Latest() if appearances is not None else None
        self.appearance_error: Exception | None = None
        self._records: list[Evidence] = []
        self._lock = threading.Lock()
        # The last classification, every body included, and how many there
        # have been: a live view between reports.
        self.latest: list[Recognised] = []
        self.evaluations = 0
        # `on_frame` receives each camera frame with its tracked bodies, e.g.
        # for measuring mouths (speakers.py).
        if self._latest is not None:
            observers = [self._latest.observe] + ([on_frame] if on_frame else [])

            def on_frame(image, frame):
                for observe in observers:
                    observe(image, frame)
        self.recognizer = recognizer.ActionRecognizer(source, on_readings=self._on_readings,
                                                      on_frame=on_frame)

    def start(self) -> "ActionRatings":
        # Loaded before the thread starts, so a missing model fails the run at
        # its start rather than silently on the thread, and the first window
        # does not pay for the load.
        model.session()
        if self.appearances is not None:
            appearance.session()
        self.recognizer.start()
        return self

    def close(self):
        self.recognizer.close()

    def __enter__(self) -> "ActionRatings":
        return self.start()

    def __exit__(self, *exception):
        self.close()

    @property
    def error(self) -> Exception | None:
        """The exception that stopped recognition, if one did."""
        return self.recognizer.error

    def names(self) -> dict[int, str]:
        """The name each body carries, by track id."""
        with self._lock:
            return dict(self._names)

    def visible(self) -> list[tuple[np.ndarray, str]]:
        """Box and label of the tallest bodies in the latest tracked frame.

        The people the ratings and speaker attribution are about, labelled by
        name, or "Körper <id>" while no face has named them.
        """
        return [(box, label) for _, box, label, _ in self.in_view()]

    def in_view(self) -> list[tuple[int, np.ndarray, str, bool]]:
        """Track id, box, label and whether the operator named it, for each
        body `visible` reports."""
        # The recogniser's thread only appends finished frames, so the newest
        # one can be read without its lock.
        frames = self.recognizer.tracker.frames
        if not frames:
            return []
        frame = frames[-1]
        with self._lock:
            names, pinned = dict(self._names), set(self._pinned)
        return [(track, frame.bodies[track].box, names.get(track, f"Körper {track}"),
                 track in pinned)
                for track in recognizer.tallest(frame)]

    def assign(self, track: int, name: str | None) -> str | None:
        """Name a body by hand, or release it to the automatic naming with None.

        The name leaves every other body in view that carries it; bodies out
        of view keep theirs for what they did. Returns the face label last
        sighted on the body, if any, through which the face tracker can learn
        the person.
        """
        frames = self.recognizer.tracker.frames
        in_view = set(frames[-1].bodies) if frames else set()
        with self._lock:
            self._steady.pop(track, None)
            if name is None:
                self._pinned.pop(track, None)
                # The next naming pass names it from its votes or guess again.
                self._names.pop(track, None)
            else:
                for other in [other for other, pinned in self._pinned.items()
                              if pinned == name and other != track]:
                    del self._pinned[other]
                    self._names.pop(other, None)
                for other in [other for other, held in self._names.items()
                              if held == name and other != track and other in in_view]:
                    del self._names[other]
                self._pinned[track] = name
                self._names[track] = name
            return self._faces_seen.get(track)

    def pinned(self, track: int) -> str | None:
        """The name the operator gave a body, if any."""
        with self._lock:
            return self._pinned.get(track)

    def carried(self, since: datetime, until: datetime) -> list[str]:
        """Cast names carried by bodies in view or with readings in a stretch,
        however they were named: by face, by appearance or by hand."""
        frames = self.recognizer.tracker.frames
        in_view = set(frames[-1].bodies) if frames else set()
        with self._lock:
            active = {member for record in self._records if since < record.at <= until
                      for member in record.members}
            return sorted({name for track, name in self._names.items()
                           if (track in active or track in in_view)
                           and not presence.guessed(name)})

    def _on_readings(self, readings: list[recognizer.Reading]):
        # Runs on the recogniser's thread between two of its frames, so its
        # body tracker is not being updated meanwhile.
        frames = self.recognizer.tracker.frames
        if frames:
            self.name(frames[-1], self._faces.faces(FACE_AGE), self._describe(frames[-1]))
        self.record(readings, datetime.now(), self._predictability(readings))

    def _predictability(self, readings: list[recognizer.Reading]) -> dict[int, float]:
        """Vorhersehbarkeit of each body classified alone, by track id, over
        the window its reading covers."""
        alone = [reading.members[0] for reading in readings if len(reading.members) == 1]
        if self.reference is None or not alone:
            return {}
        at = readings[0].at
        frames = self.recognizer.tracker.window(at - recognizer.WINDOW, at)
        encoded = {track: predictability.window_embedding(frames, track) for track in alone}
        encoded = {track: vector for track, vector in encoded.items() if vector is not None}
        if not encoded:
            return {}
        scores = self.reference.score(self.reference.similarity(np.stack(list(encoded.values()))))
        return {track: float(value) for track, value in zip(encoded, scores)}

    def _describe(self, frame: tracking.Frame) -> dict[int, np.ndarray]:
        """Descriptions of the bodies in view, on the image the frame was tracked on.

        A failure stops the appearance cue alone, as a failed mouth
        measurement stops speaker attribution alone: on this thread it would
        otherwise stop action recognition.
        """
        if self._latest is None or self.appearance_error is not None:
            return {}
        taken = self._latest.take()
        if taken is None or taken[1].at != frame.at:
            return {}
        image, _ = taken
        try:
            return appearance.describe(
                image, {track: frame.bodies[track] for track in recognizer.tallest(frame)})
        except Exception as error:
            self.appearance_error = error
            print(f"appearance stopped: {error!r}", file=sys.stderr)
            return {}

    def name(self, frame: tracking.Frame, faces: list[tuple[np.ndarray, str]],
             descriptions: dict[int, np.ndarray] | None = None):
        """Name the bodies in a frame from the faces seen around it and, given
        their descriptions, from what they look like."""
        sighted = name_bodies(frame, faces)
        descriptions = descriptions or {}
        matched = {}
        if self.appearances is not None:
            for track, description in descriptions.items():
                person, _ = self.appearances.match(description)
                if person is not None:
                    matched[track] = person
        learned = []
        with self._lock:
            for track in frame.bodies:
                if track in self._votes:
                    self._fade(track, frame.at)
            for track, label in sighted.items():
                self._sighted_at[track] = frame.at
                self._faces_seen[track] = label
                pinned = self._pinned.get(track)
                if pinned is not None and label != pinned:
                    held, count = self._steady.get(track, (label, 0))
                    count = count + 1 if held == label else 1
                    self._steady[track] = (label, count)
                    if count == LEARN_SIGHTINGS:
                        learned.append((track, label, pinned))
                else:
                    self._steady.pop(track, None)
                if presence.guessed(label):
                    self._guesses[track] = label
                    continue
                if track not in self._votes:
                    self._votes[track] = {}
                    self._voted_at[track] = frame.at
                votes = self._votes[track]
                votes[label] = votes.get(label, 0.0) + 1.0
                self._face_sure[track] = (label, frame.at)
            for track, person in matched.items():
                if track not in frame.bodies:
                    continue
                if track not in self._votes:
                    self._votes[track] = {}
                    self._voted_at[track] = frame.at
                votes = self._votes[track]
                votes[person] = votes.get(person, 0.0) + APPEARANCE_VOTE

            chosen = {track: self._choose(track) for track in frame.bodies
                      if track in self._votes}
            self._one_body_per_name(chosen)

            # The operator's names hold over every vote, and no other body
            # carries them.
            pinned = set(self._pinned.values())
            for track in frame.bodies:
                cast = chosen.get(track)
                if track in self._pinned:
                    self._names[track] = self._pinned[track]
                elif cast is not None and cast not in pinned:
                    self._names[track] = cast
                elif track in self._guesses:
                    self._names[track] = self._guesses[track]
                elif track in self._votes:
                    # Its cast name went to another body in view.
                    self._names.pop(track, None)
            # A face must lie on the body in consecutive namings.
            for track in [track for track in self._steady if track not in sighted]:
                del self._steady[track]
            sure = {track: self._names[track] for track in descriptions
                    if track in self._names and self._sure(track, frame.at)}
            self._drop_stale_votes(frame)
        if self.appearances is not None:
            for track, name in sure.items():
                self.appearances.learn(name, descriptions[track], frame.at)
        # Outside the lock: the face tracker may take a moment to learn.
        if self._on_learn is not None:
            for track, label, name in learned:
                self._on_learn(track, label, name)

    def _sure(self, track: int, at: float) -> bool:
        """Whether a body's name is sure enough to learn its appearance from:
        given by hand, or its cast face sighted on it within SURE_AGE."""
        if track in self._pinned:
            return True
        face, when = self._face_sure.get(track, (None, -np.inf))
        return face == self._names.get(track) and at - when <= SURE_AGE

    def _fade(self, track: int, at: float):
        """Fade a body's votes to recogniser time `at`."""
        factor = 0.5 ** (max(0.0, at - self._voted_at[track]) / VOTE_HALF_LIFE)
        self._votes[track] = {name: votes * factor for name, votes in self._votes[track].items()}
        self._voted_at[track] = at

    def _choose(self, track: int) -> str | None:
        """The cast name a body's votes give it, keeping the one it carries until overtaken."""
        votes = self._votes[track]
        if not votes:
            return None
        leader = max(votes, key=votes.get)
        held = self._names.get(track)
        if held in votes and votes[leader] < votes[held] + SWITCH:
            return held
        if votes[leader] < MIN_NAME:
            return held if held in votes else None
        return leader

    def _one_body_per_name(self, chosen: dict[int, str | None]):
        """Leave each cast name on one body in view, unnaming the others in `chosen`."""
        claimants: dict[str, list[int]] = {}
        for track, cast in chosen.items():
            if cast is not None:
                claimants.setdefault(cast, []).append(track)
        for cast, tracks in claimants.items():
            if len(tracks) < 2:
                continue
            strongest = max(tracks, key=lambda track: self._votes[track][cast])
            holder = next((track for track in tracks if self._names.get(track) == cast), None)
            keeper = strongest
            if (holder is not None and self._votes[strongest][cast]
                    < self._votes[holder][cast] + SWITCH):
                keeper = holder
            for track in tracks:
                if track != keeper:
                    chosen[track] = None

    def _drop_stale_votes(self, frame: tracking.Frame):
        """Forget the votes and guess of bodies unsighted and out of view for VOTES_KEPT."""
        for track in [track for track, at in self._sighted_at.items()
                      if track not in frame.bodies and frame.at - at > VOTES_KEPT]:
            for kept in (self._sighted_at, self._votes, self._voted_at, self._guesses,
                         self._faces_seen, self._face_sure):
                kept.pop(track, None)

    def record(self, readings: list[recognizer.Reading], at: datetime,
               scores: dict[int, float] | None = None):
        """Weigh readings and keep them under the bodies they are of.

        `scores` holds the Vorhersehbarkeit of bodies classified alone, by
        track id.
        """
        scores = scores or {}
        with self._lock:
            names = dict(self._names)
        kept, seen = [], []
        for reading in readings:
            values, causes = weigh(reading.probabilities, self.mapping)
            alone = reading.members[0] if len(reading.members) == 1 else None
            kept.append(Evidence(at, reading.members, values, causes, scores.get(alone)))
            top = int(reading.probabilities.argmax())
            seen.append(Recognised(
                tuple(names.get(member, f"Körper {member}") for member in reading.members),
                self.mapping.names[top], float(reading.probabilities[top]), values))
        with self._lock:
            self._records.extend(kept)
            while self._records and at - self._records[0].at > timedelta(seconds=KEEP):
                self._records.pop(0)
            self.latest = seen
            self.evaluations += 1

    def clear(self):
        """Delete every reading, name and tracked pose held."""
        with self._lock:
            self._records = []
            self._names = {}
            self._votes = {}
            self._voted_at = {}
            self._guesses = {}
            self._sighted_at = {}
            self._faces_seen = {}
            self._pinned = {}
            self._steady = {}
            self._face_sure = {}
            self.latest = []
        self.recognizer.tracker.frames.clear()

    def between(self, since: datetime, until: datetime,
                gain: Gain | None = None) -> list[report.Handlung]:
        """Ratings from the readings made after `since` and up to `until`."""
        records, names = self.since(since, until)
        return rate(records, names, gain)

    def since(self, since: datetime,
              until: datetime | None = None) -> tuple[list[Evidence], dict[int, str]]:
        """The readings after `since` (up to `until`), and the name each body carries now.

        Names are resolved when asked for, so a body named at any point is
        rated on everything it did while it was kept.
        """
        with self._lock:
            return ([record for record in self._records
                     if record.at > since and (until is None or record.at <= until)],
                    dict(self._names))
