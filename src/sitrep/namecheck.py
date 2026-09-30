"""Replay check for naming: how steadily a recording's people keep their names.

A name reaches the operator's video in two steps. The presence tracker names
faces (presence.py), and each body the action recogniser follows takes the
name of the face its head lies in (actions.py). This walks a recording through
both, wired as a live run wires them, and reports every moment a name is
made, lost or changed, then a summary of how often each kind of change
happened.

The recording is walked on its own clock rather than in real time: pose at
the recogniser's rate, a face pass every presence.INTERVAL and a naming step
every recognizer.STEP of footage, however long the machine takes. Two runs over
the same stretch therefore see the same frames and can be compared.

    python -m sitrep.namecheck --recording probe.mp4 --cast ../data/cast
    python -m sitrep.namecheck --recording probe.mp4 --cast ../data/cast --start 60 --duration 120

Nothing is written to disk.
"""

import argparse
import pathlib
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import timedelta

import numpy as np

from action import recognizer, tracking
from face import gallery

from . import actions, presence

# A new face track whose box overlaps a track sighted within this many seconds
# is counted as a fragment of that track: the same person, split off.
NEIGHBOUR_AGE = 1.5

# Face similarities this close to the naming threshold are reported apart:
# faces that land here are named or not by chance.
MARGIN = 0.05


class WatchedGallery:
    """A cast gallery that remembers the verdict of its latest match.

    Stands in for the gallery the tracker is given, so the check sees each
    face's best similarity without matching every face a second time.
    """

    def __init__(self, cast: gallery.Gallery):
        self._cast = cast
        self.names = cast.names
        self.latest: list[gallery.Match] = []

    def match(self, probes, threshold=gallery.THRESHOLD):
        self.latest = self._cast.match(probes, threshold=threshold)
        return self.latest


def kind(label: str, cast: set[str]) -> str:
    """Whether a label is a cast name, a guess, or an unnamed body."""
    if label in cast:
        return "cast"
    if label.startswith(presence.UNSURE):
        return "guess"
    return "unnamed"


def overlaps(a: np.ndarray, b: np.ndarray) -> bool:
    return tracking.overlap(np.asarray(a, float), np.asarray(b, float)) > 0.0


@dataclass
class Tally:
    """What the replay saw, for the summary."""

    similarities: list[float] = field(default_factory=list)
    named_faces: int = 0
    face_tracks: int = 0
    fragments: int = 0
    face_renames: Counter = field(default_factory=Counter)
    body_steps: Counter = field(default_factory=Counter)
    body_changes: Counter = field(default_factory=Counter)
    bodies: dict[int, list[str]] = field(default_factory=dict)


def face_pass(tracker: presence.PresenceTracker, watched: WatchedGallery | None,
              frame, position: float, tally: Tally, cast: set[str], verbose: bool):
    """One presence pass, reporting tracks that begin or change label."""
    at = presence.REPLAY_EPOCH + timedelta(seconds=position)
    before = {id(track): (track.label, track.box, track.last_seen)
              for track in tracker._tracks}
    touched = tracker.observe(frame, at=at)
    matches = watched.latest if watched else [None] * len(touched)

    for track, match in zip(touched, matches):
        if match is not None:
            tally.similarities.append(match.similarity)
            tally.named_faces += match.known
        verdict = (f"gallery {match.similarity:.2f}"
                   + (f" {match.name}" if match.known else "")) if match else ""
        earlier = before.get(id(track))
        if earlier is None:
            tally.face_tracks += 1
            beside = [label for label, box, seen in before.values()
                      if box is not None and (at - seen).total_seconds() <= NEIGHBOUR_AGE
                      and overlaps(box, track.box)]
            if beside:
                tally.fragments += 1
            print(f"{position:7.1f}s  face  new track {track.label!r}  {verdict}"
                  + (f"  beside {beside[0]!r}" if beside else ""))
        elif earlier[0] != track.label:
            tally.face_renames[(kind(earlier[0], cast), kind(track.label, cast))] += 1
            print(f"{position:7.1f}s  face  {earlier[0]!r} -> {track.label!r}  {verdict}")
        elif verbose:
            print(f"{position:7.1f}s  face  {track.label!r}  {verdict}")


def naming_step(ratings: actions.ActionRatings, tracker: presence.PresenceTracker,
                frame: tracking.Frame, position: float, tally: Tally,
                cast: set[str], verbose: bool):
    """Name the bodies in view, reporting every visible body whose label changes."""
    at = presence.REPLAY_EPOCH + timedelta(seconds=position)
    ratings.name(frame, tracker.faces(actions.FACE_AGE, at=at))
    names = ratings.names()
    for track in recognizer.tallest(frame):
        label = names.get(track, f"Körper {track}")
        history = tally.bodies.setdefault(track, [])
        tally.body_steps[kind(label, cast)] += 1
        if history and history[-1] != label:
            tally.body_changes[(kind(history[-1], cast), kind(label, cast))] += 1
            print(f"{position:7.1f}s  body  {track}: {history[-1]!r} -> {label!r}")
        elif not history:
            print(f"{position:7.1f}s  body  {track} appears as {label!r}")
        elif verbose:
            print(f"{position:7.1f}s  body  {track}: {label!r}")
        history.append(label)


def summary(tally: Tally, seconds: float) -> list[str]:
    lines = [f"\n{seconds:.0f}s of footage"]
    if tally.similarities:
        values = np.array(tally.similarities)
        near = np.abs(values - gallery.THRESHOLD) <= MARGIN
        lines.append(
            f"faces: {len(values)} seen, {tally.named_faces} named by the gallery "
            f"({tally.named_faces / len(values):.0%}); best cast similarity "
            f"p10 {np.percentile(values, 10):.2f} p50 {np.median(values):.2f} "
            f"p90 {np.percentile(values, 90):.2f}; {near.mean():.0%} within "
            f"{MARGIN:g} of the threshold {gallery.THRESHOLD:g}")
    lines.append(f"face tracks started: {tally.face_tracks}, "
                 f"{tally.fragments} of them beside a live track")
    if tally.face_renames:
        lines.append("face track label changes: " + ", ".join(
            f"{a}->{b} {count}" for (a, b), count in sorted(tally.face_renames.items())))
    steps = sum(tally.body_steps.values())
    if steps:
        lines.append("visible body labels: " + ", ".join(
            f"{name} {count / steps:.0%}" for name, count in sorted(tally.body_steps.items()))
            + f" of {steps} body-seconds")
    changes = sum(tally.body_changes.values())
    lines.append(f"body label changes: {changes}"
                 + (" (" + ", ".join(f"{a}->{b} {count}" for (a, b), count
                                     in sorted(tally.body_changes.items())) + ")"
                    if changes else "")
                 + (f", {changes / seconds * 60:.1f} a minute" if seconds else ""))
    lines.append(f"bodies seen: {len(tally.bodies)}")
    for track, history in tally.bodies.items():
        shown = Counter(history).most_common(3)
        lines.append(f"  {track:>4}: {len(history)}s  "
                     + ", ".join(f"{label} {count}" for label, count in shown))
    return lines


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--recording", required=True, help="video file to walk through")
    parser.add_argument("--cast", type=pathlib.Path,
                        help="folder holding one folder of images per person")
    parser.add_argument("--start", type=float, default=0.0, help="seconds into the recording")
    parser.add_argument("--duration", type=float, help="seconds to walk (default: to the end)")
    parser.add_argument("--verbose", action="store_true",
                        help="print every pass and step, not only changes")
    args = parser.parse_args(argv)

    cast, watched = None, None
    if args.cast:
        cast, skipped = gallery.enrol(args.cast)
        for path in skipped:
            print(f"no face found in {path}", file=sys.stderr)
        watched = WatchedGallery(cast)
        print("cast: " + ", ".join(f"{name} ({count})" for name, count in cast.counts().items()))
    names = set(cast.names) if cast else set()

    tracker = presence.PresenceTracker(None, watched)
    ratings = actions.ActionRatings(None, tracker)
    tally = Tally()
    next_face = next_name = args.start
    position = args.start
    try:
        for position, image in recognizer.replay(args.recording, args.start,
                                                 args.duration, recognizer.FPS):
            frame = ratings.recognizer.observe(image, position)
            if position + 1e-6 >= next_face:
                face_pass(tracker, watched, image, position, tally, names, args.verbose)
                next_face += presence.INTERVAL
            if position + 1e-6 >= next_name:
                naming_step(ratings, tracker, frame, position, tally, names, args.verbose)
                next_name += recognizer.STEP
    except KeyboardInterrupt:
        print()
    except RuntimeError as error:
        print(error, file=sys.stderr)
        return 1

    print("\n".join(summary(tally, position - args.start)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
