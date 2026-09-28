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


class Timeline:
    """The level of one window's audio over time."""

    def __init__(self, wav: bytes, start: datetime):
        with wave.open(io.BytesIO(wav)) as handle:
            rate = handle.getframerate()
            samples = np.frombuffer(handle.readframes(handle.getnframes()), dtype=np.int16)
        samples = samples.astype(np.float32) / 32768
        step = max(1, int(rate * FRAME))
        count = len(samples) // step
        frames = samples[:count * step].reshape(count, step) if count else np.zeros((0, step))
        rms = np.sqrt((frames ** 2).mean(axis=1)) if count else np.zeros(0)
        self.start = start
        self.levels = 20 * np.log10(np.maximum(rms, 10 ** (SILENCE_DB / 20)))

    def level(self, begins: datetime, ends: datetime) -> float | None:
        """The level of a stretch in dBFS, or None if the audio does not cover it."""
        first = int(np.floor((begins - self.start).total_seconds() / FRAME))
        last = int(np.ceil((ends - self.start).total_seconds() / FRAME))
        steps = self.levels[max(0, first):max(0, min(last, len(self.levels)))]
        if len(steps) < MIN_FRAMES:
            return None
        return float(np.percentile(steps, PERCENTILE))


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


def gain_over(timeline: Timeline | None, calibration: Calibration | None,
              begins: datetime, ends: datetime) -> float:
    """The gain for a stretch of time, 1 where there is no audio or no calibration."""
    if timeline is None or calibration is None:
        return 1.0
    return calibration.gain(timeline.level(begins, ends))


def seconds(begins: datetime, ends: datetime) -> float:
    return max(0.0, (ends - begins) / timedelta(seconds=1))
