"""Who said what: speech attributed to the two most visible people by their lips.

The speaker diarisation that the sentiment analysis of
knowledge/components/02_processing.md ("Calculating Values") depends on. The
people are the ones the action recogniser already follows: the two tallest
bodies (action.recognizer.MAX_PEOPLE), named by the faces the presence tracker
recognises (actions.py). No voice is identified; a line goes to the person
whose lips moved while it was spoken.

Mouths. On every frame the recogniser tracks, the head of each of the two
tallest bodies is located from its pose (nose, eyes, ears) and cropped, and
the 106-point landmark model from the buffalo_l bundle that also detects and
recognises faces (face/model.py) finds the lips. The mouth's opening is the gap
between the inner lip centres divided by the mouth's width, so it does not
depend on how large the face appears.

Attribution. Over each Whisper segment, a person's lip movement is the
standard deviation of their mouth opening. The segment goes to the person
whose lips moved at least RATIO times as much as the other's. It stays
unattributed when fewer than two mouths were seen, since the other person may
be speaking while turned away, or when neither clearly moved more.

Measured on 5 min of the test corpus ("Boom", edited footage with frequent
cuts and close-ups), with both mouths visible in 107 segments: 69 were
attributed at a RATIO of 1.5. How many of those are right is unmeasured.
"""

import sys
import threading
from collections import deque
from datetime import datetime, timedelta

import cv2
import numpy as np

from action import recognizer, tracking
from face import model as face_model

from . import report, transcribe

LANDMARKS = "2d106det.onnx"
INPUT = 192

# The landmark model's input is a crop this many times the face's size, as
# insightface feeds it.
CROP = 1.5

# Joints of the head in COCO-17 order.
NOSE, EYES, EARS = 0, (1, 2), (3, 4)

# Lip landmarks of the 106-point layout: the mouth's corners, and the centres
# of the inner upper and lower lip.
CORNERS = (52, 61)
INNER = (62, 60)

# How many times as much one person's lips must move as the other's for a
# segment to be theirs.
RATIO = 1.5

# Mouth measurements a person needs within a segment to be compared: about
# 0.2 s at the recogniser's 25 frames a second.
MIN_SAMPLES = 5

# Seconds of measurements kept: longer than a window and the report after it.
KEEP = 120.0


def head(body: tracking.Body) -> tuple[float, float, float] | None:
    """Centre and side of a face box, from the head joints of a body's pose.

    The face's width is taken from the ears where both are visible, or from
    the eyes; the centre sits a little below the nose, as a face's does. None
    when fewer than two head joints are visible.
    """
    points, scores = body.keypoints, body.scores
    visible = [joint for joint in range(5) if scores[joint] >= tracking.VISIBLE]
    if len(visible) < 2:
        return None
    if all(scores[joint] >= tracking.VISIBLE for joint in EARS):
        size = 1.1 * float(np.linalg.norm(points[EARS[0]] - points[EARS[1]]))
    elif all(scores[joint] >= tracking.VISIBLE for joint in EYES):
        size = 2.6 * float(np.linalg.norm(points[EYES[0]] - points[EYES[1]]))
    else:
        size = 2.0 * float(np.ptp(points[visible, 0])) + 1.0
    anchor = points[NOSE] if scores[NOSE] >= tracking.VISIBLE else points[visible].mean(axis=0)
    return float(anchor[0]), float(anchor[1]) + 0.1 * size, size


def mouth_opening(image: np.ndarray, centre_x: float, centre_y: float, size: float) -> float:
    """Gap between the inner lips as a share of the mouth's width."""
    scale = INPUT / (size * CROP)
    affine = np.array([[scale, 0, INPUT / 2 - centre_x * scale],
                       [0, scale, INPUT / 2 - centre_y * scale]], dtype=np.float32)
    crop = cv2.warpAffine(image, affine, (INPUT, INPUT), borderValue=0.0)
    blob = cv2.dnn.blobFromImage(crop, 1.0, (INPUT, INPUT), (0, 0, 0), swapRB=True)
    session = face_model.session(LANDMARKS)
    points = session.run(None, {session.get_inputs()[0].name: blob})[0].reshape(-1, 2)
    width = float(np.linalg.norm(points[CORNERS[1]] - points[CORNERS[0]]))
    return float(np.linalg.norm(points[INNER[1]] - points[INNER[0]])) / max(width, 1e-6)


class Speakers:
    """Mouth movement of the two most visible people, and the lines it attributes.

    `observe` is given every frame the action recogniser tracks, on its thread;
    `attribute` is asked for each report.
    """

    def __init__(self, count: int = recognizer.MAX_PEOPLE):
        self._count = count
        self._samples: deque[tuple[datetime, int, float]] = deque()
        self._lock = threading.Lock()
        # The exception that stopped mouth measurement, if one did.
        self.error: Exception | None = None

    def load(self) -> "Speakers":
        """Load the landmark model now rather than on the first frame."""
        face_model.session(LANDMARKS)
        return self

    def observe(self, image: np.ndarray, frame: tracking.Frame, at: datetime | None = None):
        """Measure the mouths of the tallest bodies in one tracked frame."""
        if self.error:
            return
        at = at or datetime.now()
        try:
            measured = []
            for track in recognizer.tallest(frame, self._count):
                located = head(frame.bodies[track])
                if located:
                    measured.append((at, track, mouth_opening(image, *located)))
        except Exception as error:
            # Runs on the recogniser's thread: a failure here would stop action
            # recognition too, so mouth measurement alone stops.
            self.error = error
            print(f"mouth measurement stopped: {error!r}", file=sys.stderr)
            return
        with self._lock:
            self._samples.extend(measured)
            while self._samples and at - self._samples[0][0] > timedelta(seconds=KEEP):
                self._samples.popleft()

    def clear(self):
        """Delete every mouth measurement held."""
        with self._lock:
            self._samples.clear()

    def attribute(self, segments: list[transcribe.Segment], audio_start: datetime,
                  names: dict[int, str]) -> list[report.Aeusserung]:
        """Each segment with its speaker's name where the lips show who it was.

        `audio_start` is the moment the audio's first sample was recorded, and
        `names` maps body track ids to people (actions.ActionRatings.names). A
        speaker whose body carries no name is reported as UNBEKANNT; a segment
        whose speaker cannot be told has no name.
        """
        with self._lock:
            samples = list(self._samples)

        lines = []
        for segment in segments:
            begins = audio_start + timedelta(seconds=segment.start)
            ends = audio_start + timedelta(seconds=segment.end)
            openings: dict[int, list[float]] = {}
            for at, track, opening in samples:
                if begins <= at <= ends:
                    openings.setdefault(track, []).append(opening)

            speaker = None
            seen = sorted((values for values in openings.items() if len(values[1]) >= MIN_SAMPLES),
                          key=lambda values: -len(values[1]))[:2]
            if len(seen) == 2:
                (first, first_values), (second, second_values) = seen
                movement = {first: float(np.std(first_values)), second: float(np.std(second_values))}
                louder, quieter = sorted(movement, key=movement.get, reverse=True)
                if movement[louder] >= RATIO * movement[quieter] and movement[louder] > 0:
                    speaker = names.get(louder, report.UNBEKANNT)
            lines.append(report.Aeusserung(name=speaker, text=segment.text,
                                           beginn=begins, ende=ends))
        return lines
