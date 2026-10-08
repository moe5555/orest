"""Who is in the room: continuous face tracking behind the SITREP.

Answers the "who is in the scene" of knowledge/components/02_processing.md by
measuring it rather than asking the model to read it off the frames, in the
same way transcribe.py took speech out of the model's hands.

Runs at its own rate, independent of the SITREP window. A window delivers
frames to the model every five or ten seconds, which is far too sparse to
follow a person across; this reads the camera several times a second, so an
actor only has to face it once to be named for as long as their track lives.

Tracks are linked by the face embedding first. Across two hours of stage
footage no two different people ever exceeded 0.35 cosine similarity, while the
same person across that whole span sat at a median of 0.60, so an embedding is
a stronger association cue than proximity and costs nothing extra: the vector
is already computed in order to identify the face. Box position links only the
faces the embedding leaves unplaced, which are the turned, covered and badly
lit views where the embedding is weakest.

A track that matches the enrolled cast carries that name. A track the cast
gallery does not match carries no name, only a key (UNNAMED) by which the
operator can name it. Unrecognised people are shown by their body instead
("Körper <id>", actions.py) and reported as Unbekannt.

The operator can name a track by hand (`teach`). The name is final for that
track, and its faces join the cast gallery for the rest of the run, so the
person is recognised again after leaving the picture. The lesson follows the
track: as it keeps clearer faces, the gallery learns those. Nothing learned is
written to disk.

Nothing is written to disk, in line with the non-recording real-time path.

Watch the tracker without generating reports:

    python -m sitrep.presence --cast data/cast
    python -m sitrep.presence --cast data/cast --recording rehearsal.mp4
"""

import argparse
import itertools
import math
import pathlib
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import cv2
import numpy as np

from action import tracking
from face import detect, embed, gallery

from . import capture, cli, devices

# Seconds between passes. Two passes a second costs about a tenth of the
# machine at the measured 222 ms per pass, leaving the rest to Whisper and
# Ollama, which run in the same window.
INTERVAL = 0.5

# Faces smaller than this are ignored. Below 30 pixels identification recall
# falls to roughly one in two, so a smaller face mostly adds a weak vector to a
# track rather than information.
MIN_FACE = 30.0

# Cosine similarity at which a new sighting joins an existing track. Set above
# the highest different-person similarity measured anywhere in the corpus
# (0.35) and well below what the same face scores half a second apart.
LINK = 0.45

# A face that no track's embedding claims continues the track whose latest box
# it overlaps by at least PLACE_LINK (intersection over union), provided that
# track was sighted within PLACE_AGE seconds: two passes. A turned head or a
# covered face scores low against the person's own stored faces, but a face
# in the place another face was half a second ago is almost always the same
# person.
PLACE_LINK = 0.3
PLACE_AGE = 2 * INTERVAL

# A track with no sighting for this long is closed. Matches the default SITREP
# window, so a person seen at the start of a window is still on its roster
# after turning away for the rest of it.
FORGET = 30.0

# Prefix of the key an unrecognised track is held under ("#7"). The key
# identifies the track for `teach` and is never shown as a name.
UNNAMED = "#"


def unnamed(label: str) -> bool:
    """Whether a label is the key of an unrecognised track rather than a cast name."""
    return label.startswith(UNNAMED)

# Arbitrary reference a replay counts footage time from, so that a position in
# a recording becomes a datetime the tracker can age a track against. Only
# differences matter; the date itself is never shown. Far enough from
# datetime.min that subtracting the forget window cannot underflow.
REPLAY_EPOCH = datetime(2000, 1, 1)

# Similarity of a track the operator has named. Above any match, so the
# gallery never renames it (_adopt keeps a track's strongest match).
TAUGHT = math.inf

# Sightings kept per track, largest face first. A track is matched on its best
# stored vector, exactly as an enrolled person is, so keeping several covers
# the angles a person turns through; keeping more than this buys little.
TRACK_VECTORS = 8


@dataclass
class Track:
    """One person, followed across passes for as long as they keep appearing."""

    key: str
    first_seen: datetime
    last_seen: datetime
    sightings: int = 1
    name: str | None = None
    similarity: float = 0.0
    vectors: list[np.ndarray] = field(default_factory=list)
    sizes: list[float] = field(default_factory=list)
    # Face box of the latest sighting, x1 y1 x2 y2 in source-frame pixels.
    box: np.ndarray | None = None

    @property
    def label(self) -> str:
        """The track's name, or its key while the cast gallery has not named it."""
        return self.name or self.key

    def remember(self, vector: np.ndarray, size: float):
        """Keep a face, discarding the smallest once the track is full."""
        self.vectors.append(vector)
        self.sizes.append(size)
        if len(self.vectors) > TRACK_VECTORS:
            smallest = int(np.argmin(self.sizes))
            self.vectors.pop(smallest)
            self.sizes.pop(smallest)

    def observe(self, vector: np.ndarray, size: float, at: datetime):
        """Record one sighting, keeping the clearest faces seen so far."""
        self.last_seen = at
        self.sightings += 1
        self.remember(vector, size)

    def similarity_to(self, vector: np.ndarray) -> float:
        """Best match between a new face and the faces this track has seen."""
        return float(max(stored @ vector for stored in self.vectors))


@dataclass
class Lesson:
    """A track the operator named, and the faces learned from it."""

    name: str
    track: Track
    vectors: np.ndarray


@dataclass(frozen=True)
class Presence:
    """One person's presence over a stretch of time."""

    label: str
    name: str | None
    similarity: float
    sightings: int
    first_seen: datetime
    last_seen: datetime

    @property
    def seconds(self) -> float:
        return (self.last_seen - self.first_seen).total_seconds()

    @property
    def known(self) -> bool:
        return self.name is not None


class PresenceTracker:
    """Follows every face a camera shows and names the ones the cast gallery knows.

    The source is anything with a `latest()` returning the current BGR frame,
    which is how capture.VideoStream presents the camera. The tracker never
    opens or closes the source, so it can share one with the capture loop.
    """

    def __init__(self, source, cast: gallery.Gallery | None = None, *,
                 interval: float = INTERVAL, min_face: float = MIN_FACE,
                 threshold: float = gallery.THRESHOLD,
                 detector_size: int = detect.INPUT_SIZE):
        self._source = source
        # Public: a run reports which cast it was given. Faces the operator
        # taught are added to it; the enrolled gallery is kept apart, so a
        # lesson can be taken back.
        self.cast = cast
        self._enrolled = cast
        self._lessons: dict[int, Lesson] = {}
        self._lesson_ids = itertools.count(1)
        self._interval = interval
        self._min_face = min_face
        self._threshold = threshold
        self._detector_size = detector_size

        self._tracks: list[Track] = []
        self._track_ids = itertools.count(1)
        self._lock = threading.Lock()
        # Serialises whole passes. The tracker's own thread and a caller naming
        # a frame both run passes; interleaved, each could see a new face as
        # unknown and start a track for it, leaving one person tracked twice.
        # Re-entrant, since name_faces holds it
        # across the pass it runs.
        self._pass = threading.RLock()
        self._stop = threading.Event()
        self._thread = None
        self.passes = 0
        self.durations: list[float] = []

    def start(self):
        """Begin observing on a background thread."""
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        return self

    def close(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5.0)

    def __enter__(self):
        return self.start()

    def __exit__(self, *exception):
        self.close()

    def _loop(self):
        while not self._stop.is_set():
            started = time.monotonic()
            self.observe(self._source.latest())
            self.durations.append(time.monotonic() - started)
            self._stop.wait(max(0.0, self._interval - (time.monotonic() - started)))

    def observe(self, frame, at: datetime | None = None) -> list[Track]:
        """Run one pass over a frame and return the tracks it touched.

        Public so the tracker can be driven frame by frame over a recording or
        in a test, rather than only by its own thread.
        """
        with self._pass:
            at = at or datetime.now()
            faces = [face for face in detect.detect(frame, size=self._detector_size)
                     if face.size >= self._min_face]
            vectors = embed.embed(frame, faces)
            matches = (self.cast.match(vectors, threshold=self._threshold)
                       if self.cast is not None and len(vectors) else [])

            with self._lock:
                self._forget(at)
                touched = self._link(faces, vectors, matches, at)
                self._adopt(touched, matches)
                self._merge_by_name()
                if any(track.similarity == TAUGHT for track in touched):
                    self._refresh_lessons()
                self.passes += 1
                return touched

    def name_faces(self, frame) -> list[tuple[np.ndarray, str]]:
        """Each recognised face in a frame with the name its track carries.

        Runs a full pass over this exact frame rather than reusing the boxes of
        the tracker's last pass, so every box lies on the face it names even
        when people have moved since. The pass also counts as a sighting.
        """
        with self._pass:
            touched = self.observe(frame)
            with self._lock:
                return [(track.box, track.name) for track in touched if track.name]

    def clear(self):
        """Delete every track and every lesson, with the face embeddings they hold."""
        with self._pass, self._lock:
            self._tracks = []
            self._lessons = {}
            self.cast = self._enrolled

    def teach(self, label: str, name: str) -> int | None:
        """Name the live track called `label` as `name`, for good, and learn its faces.

        Returns the lesson's id, for `unteach`, or None when no live track
        carries the label.
        """
        with self._pass, self._lock:
            track = next((track for track in self._tracks if track.label == label), None)
            if track is None or not track.vectors:
                return None
            track.name, track.similarity = name, TAUGHT
            lesson = next(self._lesson_ids)
            self._lessons[lesson] = Lesson(name, track, np.array(track.vectors))
            self._merge_by_name()
            self._relearn()
            return lesson

    def unteach(self, lesson: int):
        """Take a lesson back: forget its faces, and let the gallery name its track again."""
        with self._pass, self._lock:
            taken = self._lessons.pop(lesson, None)
            if taken is None:
                return
            # A merge may have moved the name to another track of the person.
            if not any(kept.name == taken.name for kept in self._lessons.values()):
                for track in self._tracks:
                    if track.name == taken.name and track.similarity == TAUGHT:
                        track.name, track.similarity = None, 0.0
            self._relearn()

    def _refresh_lessons(self):
        """Learn the faces each taught track keeps now, its clearest so far."""
        live = {id(track) for track in self._tracks}
        for lesson in self._lessons.values():
            if id(lesson.track) in live:
                lesson.vectors = np.array(lesson.track.vectors)
        self._relearn()

    def _relearn(self):
        """The enrolled gallery with every lesson's faces added."""
        additions = [(lesson.name, lesson.vectors) for lesson in self._lessons.values()]
        if not additions:
            self.cast = self._enrolled
            return
        base = self._enrolled
        if base is None:
            width = additions[0][1].shape[1]
            base = gallery.Gallery([], np.empty((0, width), dtype=np.float32),
                                   np.empty(0, dtype=np.int64), [])
        self.cast = base.extended(additions)

    def faces(self, within: float, at: datetime | None = None) -> list[tuple[np.ndarray, str]]:
        """The face box and label of every track sighted in the `within` seconds before `at`.

        Reads the boxes of past passes without running one, for a reader that
        needs to know where each named person is but cannot afford a pass of
        its own. `at` defaults to now; a replay passes its footage time.
        """
        cutoff = (at or datetime.now()) - timedelta(seconds=within)
        with self._lock:
            return [(track.box, track.label) for track in self._tracks
                    if track.box is not None and track.last_seen >= cutoff]

    def _forget(self, at: datetime):
        cutoff = at - timedelta(seconds=FORGET)
        self._tracks = [track for track in self._tracks if track.last_seen >= cutoff]

    def _link(self, faces, vectors, matches, at: datetime) -> list[Track]:
        """Attach each face to a track, starting a new one where none fits.

        Three cues, strongest first. A face close enough to a track's own
        stored faces joins it; assignment is greedy on similarity, so the most
        confident pairing is taken first and both sides leave the pool.

        A face the cast gallery names then joins whichever live track already
        carries that name. This second cue is what keeps a person whole across
        a turn of the head: their own two views can sit below the link
        threshold, since the same person across a long stretch of footage drops
        to 0.39 at the fifth percentile, while the gallery holds several angles
        of them and recognises both.

        A face neither cue placed then continues the recently sighted track
        whose box it overlaps most (PLACE_LINK), unless the gallery names the
        face as someone other than that track. This covers the views neither
        the track's stored faces nor the gallery recognise: a profile, a hand
        across the face, a change of light.
        """
        assigned = {}
        claimed = set()
        if self._tracks and len(vectors):
            scores = np.array([[track.similarity_to(vector) for track in self._tracks]
                               for vector in vectors])
            while True:
                row, column = np.unravel_index(scores.argmax(), scores.shape)
                if scores[row, column] < LINK:
                    break
                assigned[int(row)] = self._tracks[int(column)]
                claimed.add(int(column))
                scores[row, :] = -np.inf
                scores[:, column] = -np.inf

        if matches:
            named = {track.name: index for index, track in enumerate(self._tracks)
                     if track.name is not None and index not in claimed}
            unassigned = [row for row in range(len(vectors))
                          if row not in assigned and matches[row].known]
            for row in sorted(unassigned, key=lambda row: -matches[row].similarity):
                column = named.pop(matches[row].name, None)
                if column is not None:
                    assigned[row] = self._tracks[column]
                    claimed.add(column)

        recent = at - timedelta(seconds=PLACE_AGE)
        candidates = []
        for row, face in enumerate(faces):
            if row in assigned:
                continue
            face_name = matches[row].name if matches and matches[row].known else None
            for column, track in enumerate(self._tracks):
                if (column in claimed or track.box is None or track.last_seen < recent
                        or (face_name is not None and track.name not in (None, face_name))):
                    continue
                overlap = tracking.overlap(np.asarray(face.bbox, dtype=float),
                                           np.asarray(track.box, dtype=float))
                if overlap >= PLACE_LINK:
                    candidates.append((overlap, row, column))
        for _, row, column in sorted(candidates, reverse=True):
            if row in assigned or column in claimed:
                continue
            assigned[row] = self._tracks[column]
            claimed.add(column)

        touched = []
        for row, (face, vector) in enumerate(zip(faces, vectors)):
            track = assigned.get(row)
            if track is None:
                track = Track(f"{UNNAMED}{next(self._track_ids)}", at, at,
                              vectors=[vector], sizes=[face.size])
                self._tracks.append(track)
            else:
                track.observe(vector, face.size, at)
            track.box = face.bbox
            touched.append(track)
        return touched

    def _adopt(self, tracks: list[Track], matches):
        """Give each track the enrolled name its clearest face matches.

        Matched on every pass rather than once: a track named from a distant
        face is re-matched when the person turns towards the camera, and the
        strongest match the track has ever produced is the one kept.
        """
        for track, match in zip(tracks, matches):
            if match.known and match.similarity > track.similarity:
                track.name = match.name
                track.similarity = match.similarity

    def _merge_by_name(self):
        """Fold together live tracks that carry the same name.

        One person cannot be in two places, so two tracks naming the same cast
        member are one person whose track was split — typically because they
        were first seen too small to recognise and were named only later, by
        which time a second track had formed. The earliest track absorbs the
        others, keeping its key and its first sighting.
        """
        keepers: dict[str, Track] = {}
        survivors = []
        for track in self._tracks:
            if track.name is None:
                survivors.append(track)
                continue
            keeper = keepers.get(track.name)
            if keeper is None:
                keepers[track.name] = track
                survivors.append(track)
                continue
            keeper.sightings += track.sightings
            keeper.last_seen = max(keeper.last_seen, track.last_seen)
            keeper.similarity = max(keeper.similarity, track.similarity)
            for vector, size in zip(track.vectors, track.sizes):
                keeper.remember(vector, size)
        self._tracks = survivors

    def roster(self, since: datetime | None = None,
               until: datetime | None = None) -> list[Presence]:
        """Who was present over a stretch of time, first appearance first.

        With no bounds this is everyone currently tracked. A SITREP window
        passes its own start and end and gets the people seen inside it, with
        their times clipped to the window they are reported against.
        """
        with self._lock:
            tracks = [track for track in self._tracks
                      if (since is None or track.last_seen >= since)
                      and (until is None or track.first_seen <= until)]
            return [Presence(track.label, track.name,
                             round(track.similarity, 3), track.sightings,
                             max(track.first_seen, since) if since else track.first_seen,
                             min(track.last_seen, until) if until else track.last_seen)
                    for track in sorted(tracks, key=lambda track: track.first_seen)]


class Recording:
    """Replays a video file as if it were a camera, for driving the tracker.

    Presents the same `latest()` a VideoStream does, but advances by the
    tracker's interval rather than in real time, so a recording can be walked
    through faster or slower than it was shot.
    """

    def __init__(self, path, interval: float = INTERVAL, start: float = 0.0):
        self._capture = cv2.VideoCapture(str(path))
        if not self._capture.isOpened():
            raise RuntimeError(f"Could not open {path}")
        self._interval = interval
        self._duration = (self._capture.get(cv2.CAP_PROP_FRAME_COUNT)
                          / self._capture.get(cv2.CAP_PROP_FPS))
        self.seconds = start
        self.timestamp = start
        self.finished = False

    def latest(self):
        self._capture.set(cv2.CAP_PROP_POS_MSEC, self.seconds * 1000)
        ok, frame = self._capture.read()
        self.timestamp = self.seconds
        self.seconds += self._interval
        self.finished = not ok or self.seconds >= self._duration
        return frame

    def at(self) -> datetime:
        """Position of the last frame read, as the time the tracker should use.

        A replay has to age its tracks by how far the footage advanced, not by
        how long the machine took to process it, or a recording walked through
        faster than real time never forgets anyone. Counted from REPLAY_EPOCH,
        so the printed time reads as the position in the recording.
        """
        return REPLAY_EPOCH + timedelta(seconds=self.timestamp)

    def close(self):
        self._capture.release()


def format_roster(roster: list[Presence], at: datetime) -> str:
    """The current roster on one line, for watching the tracker run."""
    if not roster:
        return f"{at:%H:%M:%S}  (niemand)"
    people = "  ".join(
        person.label
        + (f" {person.similarity:.2f}" if person.known else "")
        + f" ({person.sightings}x, {person.seconds:.0f}s)"
        for person in roster
    )
    return f"{at:%H:%M:%S}  {people}"


def _source_from(args):
    """Open the camera, or a recording when one was named."""
    if args.recording:
        print(f"replaying {args.recording} from {args.start:g}s")
        return Recording(args.recording, interval=args.interval, start=args.start)

    video, _ = devices.resolve(args.video, None, args.audio_api)
    print(f"camera [{video.index}] {video.name}")
    return capture.VideoStream(video, args.width, args.height)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                     parents=[cli.sources(), cli.resolution()])
    parser.add_argument("--cast", type=pathlib.Path,
                        help="folder holding one folder of images per person")
    parser.add_argument("--recording", help="replay a video file instead of the camera")
    parser.add_argument("--start", type=float, default=0.0,
                        help="seconds into the recording to start at")
    parser.add_argument("--interval", type=float, default=INTERVAL,
                        help=f"seconds between passes (default: {INTERVAL:g})")
    parser.add_argument("--passes", type=int, help="stop after this many passes")
    parser.add_argument("--threshold", type=float, default=gallery.THRESHOLD,
                        help=f"similarity needed to name a face (default: {gallery.THRESHOLD:g})")
    parser.add_argument("--detector-size", type=int, default=detect.INPUT_SIZE,
                        help="square the frame is fitted into before detection")
    args = parser.parse_args(argv)

    cast = None
    if args.cast:
        cast, skipped = gallery.enrol(args.cast)
        print("cast: " + ", ".join(f"{name} ({count})"
                                   for name, count in cast.counts().items()))
        for path in skipped:
            print(f"no face found in {path}", file=sys.stderr)

    try:
        source = _source_from(args)
    except (ValueError, RuntimeError) as error:
        print(error, file=sys.stderr)
        return 1

    replay = isinstance(source, Recording)
    tracker = PresenceTracker(source, cast, interval=args.interval,
                              threshold=args.threshold,
                              detector_size=args.detector_size)
    previous = None
    try:
        for index in itertools.count():
            if args.passes is not None and index >= args.passes:
                break
            if replay and source.finished:
                break

            started = time.monotonic()
            frame = source.latest()
            at = source.at() if replay else datetime.now()
            tracker.observe(frame, at=at)
            tracker.durations.append(time.monotonic() - started)

            # Printed only when the roster changes: at two passes a second an
            # unchanged room would otherwise scroll the interesting lines away.
            roster = tracker.roster()
            current = [(person.label, round(person.similarity, 2)) for person in roster]
            if current != previous:
                print(format_roster(roster, at), flush=True)
                previous = current
    except KeyboardInterrupt:
        print()
    finally:
        source.close()

    if tracker.durations:
        print(f"\n{tracker.passes} passes, "
              f"p50 {np.median(tracker.durations) * 1000:.0f}ms, "
              f"p95 {np.percentile(tracker.durations, 95) * 1000:.0f}ms")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
