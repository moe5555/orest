"""Loudness: how much louder than the session's normal speech, as a gain on Risiko.

The Audio route under "Calculating Values" in knowledge/components/02_processing.md:
higher loudness increases negative-coded values. Loudness amplifies the Risiko
evidence that pose (actions.py) and speech (speech.py) produce. It never adds
evidence of its own: a loud laugh is not a danger. It never lowers a value.
Menschlichkeit is left as it is.

Level. A window's audio is measured in FRAME steps as dBFS. The level of a
stretch of time is the PERCENTILE of its steps, so that the pauses
between words do not pull a line's level down.

Calibration. What counts as loud depends on the room, the microphone and the
actors, so each session calibrates itself on its first speech. After
PROVISIONAL seconds of detected speech, the levels heard give a provisional
normal level (mean and spread), and loudness takes effect. It goes on
learning until CALIBRATION seconds, then stays fixed for the session.
Silence is not counted, since it would make every spoken line look loud.
Before PROVISIONAL every gain is 1.

Gain. Speech varies within about one standard deviation of its mean without
being loud, so that much is ignored (QUIET). Beyond it, the gain rises by GAIN
per standard deviation, capped at MAX_GAIN. It multiplies positive Risiko
evidence, which is then rounded and clipped to 0-5 as before.
"""

import io
import threading
import wave
from datetime import datetime, timedelta

import numpy as np

# Seconds per level step.
FRAME = 0.1

# Percentile of a stretch's steps taken as its level.
PERCENTILE = 90

# Steps a stretch needs to have a level.
MIN_FRAMES = 3

# Seconds of detected speech after which the calibration takes effect, and
# after which it stops learning. A scene can open far below its usual level:
# the test corpus's "Four Dogs" opens at -38.8 dBFS against a median of -26,
# and calibrated on 30 s alone it marked 63 % of all lines as loud or
# shouted; calibrated on 120 s, 25 %.
PROVISIONAL = 30.0
CALIBRATION = 120.0

# Standard deviations above the normal level that still count as normal
# speech. On 5 min of the test corpus, without this nearly every line after
# calibration was amplified, by 1.1 to 1.3.
QUIET = 1.0

# Gain per standard deviation beyond QUIET, and its cap.
GAIN = 0.5
MAX_GAIN = 2.0

# Lowest spread assumed, in dB. A few calibration lines at one volume would
# otherwise make any small rise count as many deviations.
MIN_SPREAD = 3.0

SILENCE_DB = -120.0


def _levels(samples: np.ndarray, rate: int) -> np.ndarray:
    """dBFS of each whole FRAME step of the samples; a remainder is left out."""
    step = max(1, int(rate * FRAME))
    count = len(samples) // step
    if not count:
        return np.zeros(0)
    frames = samples[:count * step].reshape(count, step)
    rms = np.sqrt((frames ** 2).mean(axis=1))
    return 20 * np.log10(np.maximum(rms, 10 ** (SILENCE_DB / 20)))


def _level(levels: np.ndarray, start: datetime, begins: datetime, ends: datetime) -> float | None:
    first = int(np.floor((begins - start).total_seconds() / FRAME))
    last = int(np.ceil((ends - start).total_seconds() / FRAME))
    steps = levels[max(0, first):max(0, min(last, len(levels)))]
    if len(steps) < MIN_FRAMES:
        return None
    return float(np.percentile(steps, PERCENTILE))


class Timeline:
    """The level of one window's audio over time."""

    def __init__(self, wav: bytes, start: datetime):
        with wave.open(io.BytesIO(wav)) as handle:
            rate = handle.getframerate()
            samples = np.frombuffer(handle.readframes(handle.getnframes()), dtype=np.int16)
        self.start = start
        self.levels = _levels(samples.astype(np.float32) / 32768, rate)

    def level(self, begins: datetime, ends: datetime) -> float | None:
        """The level of a stretch in dBFS, or None if the audio does not cover it."""
        return _level(self.levels, self.start, begins, ends)


# Below this, sound is taken for no signal at all rather than a quiet room. An
# unfed audio device measured -96.7 dBFS; the test corpus's quiet opening
# through OBS's NDI output, -38.8 (2026-09-28).
STILL = -70.0

# Seconds of levels a Meter keeps: longer than the stretch any report or
# summary of the scene asks about (chronik.py).
KEEP = 600.0


class Meter:
    """The level of the live sound over time, measured as it arrives.

    Fed continuously by the sound's reader (utterances.py) and read by
    whatever needs the loudness of a moment: a line's, or the four seconds an
    action reading covers. Keeps the last KEEP seconds, as levels only: no
    sound is kept.
    """

    def __init__(self, keep: float = KEEP):
        self._keep = int(keep / FRAME)
        self._levels = np.zeros(0)
        self._start: datetime | None = None
        self._rest = np.zeros(0, dtype=np.float32)
        self._lock = threading.Lock()
        # When sound first arrived, and when it was last above STILL.
        self.first_sound: datetime | None = None
        self.last_sound: datetime | None = None

    def add(self, samples: np.ndarray, rate: int, ends: datetime):
        """Measure sound whose last sample was recorded at `ends`."""
        with self._lock:
            joined = np.concatenate([self._rest, samples])
            levels = _levels(joined, rate)
            step = max(1, int(rate * FRAME))
            self._rest = joined[len(levels) * step:]
            self.first_sound = self.first_sound or ends
            if not len(levels):
                return
            if levels.max() > STILL:
                self.last_sound = ends
            # The steps end where the kept remainder begins.
            last_ends = ends - timedelta(seconds=len(self._rest) / rate)
            start = last_ends - timedelta(seconds=len(levels) * FRAME)
            if self._start is None:
                self._start = start
                self._levels = levels
            else:
                self._levels = np.concatenate([self._levels, levels])
            # Anchored on the newest sound, so dropped samples do not shift
            # every later level.
            self._start = last_ends - timedelta(seconds=len(self._levels) * FRAME)
            if len(self._levels) > self._keep:
                self._levels = self._levels[-self._keep:]
                self._start = last_ends - timedelta(seconds=len(self._levels) * FRAME)

    def level(self, begins: datetime, ends: datetime) -> float | None:
        """The level of a stretch in dBFS, or None if the levels kept do not cover it."""
        with self._lock:
            if self._start is None:
                return None
            return _level(self._levels, self._start, begins, ends)

    def still_for(self, now: datetime) -> float | None:
        """Seconds the sound has been below STILL, or None before any sound arrived.

        A source that delivers only silence, such as an audio device nothing
        feeds, is otherwise indistinguishable from a quiet room."""
        with self._lock:
            if self.first_sound is None:
                return None
            return max(0.0, (now - (self.last_sound or self.first_sound)).total_seconds())

    def clear(self):
        with self._lock:
            self._levels = np.zeros(0)
            self._start = None
            self._rest = np.zeros(0, dtype=np.float32)
            self.first_sound = self.last_sound = None


class Calibration:
    """The session's normal speaking level, learnt from its first speech.

    Lives as long as a session: one room, one microphone, one cast.
    """

    def __init__(self, seconds: float = CALIBRATION, provisional: float = PROVISIONAL):
        self._seconds = seconds
        self._provisional = min(provisional, seconds)
        self._levels: list[float] = []
        self._weights: list[float] = []
        self._lock = threading.Lock()
        self.mean: float | None = None
        self.spread: float | None = None

    @property
    def calibrated(self) -> bool:
        """Whether loudness takes effect: provisionally or for good."""
        return self.mean is not None

    @property
    def settled(self) -> bool:
        """Whether the normal level is fixed for the rest of the session."""
        return self.heard >= self._seconds

    @property
    def heard(self) -> float:
        """Seconds of speech calibrated on so far."""
        with self._lock:
            return float(sum(self._weights))

    def learn(self, level: float | None, seconds: float):
        """Count one line of speech towards the normal level, until settled."""
        if level is None or self.settled:
            return
        with self._lock:
            self._levels.append(level)
            self._weights.append(seconds)
            if sum(self._weights) >= self._provisional:
                weights = np.asarray(self._weights)
                levels = np.asarray(self._levels)
                self.mean = float(np.average(levels, weights=weights))
                spread = float(np.sqrt(np.average((levels - self.mean) ** 2, weights=weights)))
                self.spread = max(spread, MIN_SPREAD)

    def gain(self, level: float | None) -> float:
        """The factor on Risiko for a stretch at this level: 1 until calibrated."""
        if level is None or not self.calibrated:
            return 1.0
        above = max(0.0, (level - self.mean) / self.spread - QUIET)
        return min(MAX_GAIN, 1.0 + GAIN * above)


# Standard deviations above the normal level at which a line is marked, for
# the model reading the transcript, as loud or as shouted.
LOUD = 1.5
SHOUTED = 2.5


def label(calibration: "Calibration | None", level: float | None) -> str:
    """How loud a line was, in the transcript's words: "", "laut" or "geschrien"."""
    if calibration is None or not calibration.calibrated or level is None:
        return ""
    above = (level - calibration.mean) / calibration.spread
    return "geschrien" if above >= SHOUTED else "laut" if above >= LOUD else ""


def amplified(evidence: float, gain: float) -> float:
    """Positive Risiko evidence times the gain; calming evidence is left as it is."""
    return evidence * gain if evidence > 0 else evidence


def gain_over(timeline: "Timeline | Meter | None", calibration: Calibration | None,
              begins: datetime, ends: datetime) -> float:
    """The gain for a stretch of time, 1 where there is no audio or no calibration."""
    if timeline is None or calibration is None:
        return 1.0
    return calibration.gain(timeline.level(begins, ends))


def seconds(begins: datetime, ends: datetime) -> float:
    return max(0.0, (ends - begins) / timedelta(seconds=1))
