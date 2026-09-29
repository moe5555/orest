"""What was said, as soon as it was said: the live sound cut into utterances.

Fix 1 of knowledge/background/live_sitrep_latency.md ("Speech per
utterance"). Speech used to be transcribed once a window had closed, so a line
reached the operator 6 to 21 s after it was spoken. Here the sound is watched
as it arrives, and each utterance is transcribed, attributed and rated as soon
as it ends.

Voice activity. Silero VAD, the model faster-whisper already ships, rates
every 32 ms of sound at 16 kHz for speech. It runs chunk by chunk and carries
its state from one chunk to the next, which gives the same probabilities as
running it over the whole recording (checked on "Four Dogs", 150-170 s).

Utterances. Speech begins where a chunk reaches THRESHOLD and ends after
END_SILENCE of chunks below NEG_THRESHOLD (`Segmenter`). Once it has run for
LONG_UTTERANCE, a pause of PHRASE_PAUSE ends it too. An utterance that runs
for MAX_UTTERANCE without either is cut at its last pause, or where it stands
if it had none, so a monologue still arrives in pieces. Shorter than
MIN_SPEECH, it is taken for a click or a breath and dropped.

Each utterance then goes through the steps a window's speech went through
before: Whisper on the utterance's own sound (transcribe.py), attribution by
lip movement (speakers.py) and loudness against the session's normal speech
(loudness.py). Its lines are handed out at once, unrated: text follows speech
within about a second. The rating (speech.py) follows on a thread of its own,
so that a rating under way never holds up the next line; lines handed out
while one is being rated are rated together in the next request. The rating
request goes first to the model (llm.ZEILEN).

Sound is kept for KEEP seconds, as long as the longest utterance needs, and
nothing is written to disk.
"""

import queue
import sys
import threading
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

import numpy as np
from faster_whisper.vad import get_vad_model

from . import capture, loudness, report, transcribe

# Silero's rate and step: 512 samples at 16 kHz, 32 ms, each seen with the
# 64 samples before it.
VAD_RATE = 16000
CHUNK = 512
CONTEXT = 64

# Speech probability at which an utterance begins, and below which a chunk
# counts as silence. faster-whisper's defaults.
THRESHOLD = 0.5
NEG_THRESHOLD = 0.35

# Silence that ends an utterance (live_sitrep_latency.md: "silence of ~0.5 s").
END_SILENCE = 0.5

# An utterance that has run this long ends at the next pause of PHRASE_PAUSE,
# a break between phrases. In a quarrel speech rarely falls silent for
# END_SILENCE; without this, lines waited for MAX_UTTERANCE and were then cut
# at a pause seconds in the past (replay of "Four Dogs", 150-240 s: 3.2 s p95
# from a line's end to its transcription).
LONG_UTTERANCE = 3.0
PHRASE_PAUSE = 0.2

# The longest utterance transcribed in one piece (live_sitrep_latency.md:
# "or has run for 10 s").
MAX_UTTERANCE = 10.0

# A pause at least this long is where an utterance at MAX_UTTERANCE is cut.
PAUSE = 0.1

MIN_SPEECH = 0.25

# Sound kept around an utterance, so that its first and last words are whole.
PAD = 0.2

# Seconds of sound kept: the longest utterance with its padding, and more.
KEEP = 30.0

# Arrival times that stray this far from the sample count mean sound was
# dropped; the clock is then set anew from the arrival time.
REANCHOR = 0.5

# Lines of context given with each rating request.
VORHER = 4

STEP = CHUNK / VAD_RATE


class Vad:
    """Silero VAD over a stream, one probability per CHUNK of 16 kHz sound."""

    def __init__(self):
        self._session = get_vad_model().session
        self.reset()

    def reset(self):
        self._h = np.zeros((1, 1, 128), dtype=np.float32)
        self._c = np.zeros((1, 1, 128), dtype=np.float32)
        self._context = np.zeros(CONTEXT, dtype=np.float32)
        self._pending = np.zeros(0, dtype=np.float32)

    def __call__(self, samples: np.ndarray) -> np.ndarray:
        """Speech probabilities of every chunk the new samples complete."""
        joined = np.concatenate([self._pending, samples.astype(np.float32)])
        count = len(joined) // CHUNK
        if not count:
            self._pending = joined
            return np.zeros(0, dtype=np.float32)
        chunks = joined[:count * CHUNK].reshape(count, CHUNK)
        self._pending = joined[count * CHUNK:]
        contexts = np.vstack([self._context[None], chunks[:-1, -CONTEXT:]])
        self._context = chunks[-1, -CONTEXT:].copy()
        probabilities, self._h, self._c = self._session.run(
            None, {"input": np.concatenate([contexts, chunks], axis=1),
                   "h": self._h, "c": self._c})
        return probabilities.reshape(-1)


class Resampler:
    """A stream resampled to VAD_RATE by linear interpolation, continuous
    across chunks. Good enough for voice activity; Whisper is given the sound
    at its own rate."""

    def __init__(self, rate: int):
        self._step = rate / VAD_RATE
        self._position = 0.0
        self._previous = np.zeros(0, dtype=np.float32)

    def __call__(self, chunk: np.ndarray) -> np.ndarray:
        if self._step == 1.0:
            return chunk
        joined = np.concatenate([self._previous, chunk])
        positions = np.arange(self._position, len(joined) - 1, self._step)
        resampled = np.interp(positions, np.arange(len(joined)), joined).astype(np.float32)
        following = self._position + len(positions) * self._step
        self._previous = joined[-1:]
        self._position = following - (len(joined) - 1)
        return resampled


class Segmenter:
    """Speech probabilities in, finished utterances out, as chunk index spans."""

    def __init__(self, *, threshold: float = THRESHOLD, neg_threshold: float = NEG_THRESHOLD,
                 end_silence: float = END_SILENCE, long_utterance: float = LONG_UTTERANCE,
                 phrase_pause: float = PHRASE_PAUSE, max_utterance: float = MAX_UTTERANCE,
                 min_speech: float = MIN_SPEECH, pause: float = PAUSE, step: float = STEP):
        self._threshold = threshold
        self._neg = neg_threshold
        self._end = max(1, round(end_silence / step))
        self._long = max(1, round(long_utterance / step))
        self._phrase = max(1, round(phrase_pause / step))
        self._max = max(1, round(max_utterance / step))
        self._min = max(1, round(min_speech / step))
        self._pause = max(1, round(pause / step))
        self._count = 0
        self._start: int | None = None
        self._silent = 0
        # The last pause within the current utterance: where it began and
        # where speech resumed.
        self._last_pause: tuple[int, int] | None = None

    def push(self, probabilities) -> list[tuple[int, int]]:
        """Utterances ended by these probabilities, as [first, after-last) chunk indices."""
        found = []
        for probability in probabilities:
            index = self._count
            self._count += 1
            if self._start is None:
                if probability >= self._threshold:
                    self._start, self._silent, self._last_pause = index, 0, None
                continue

            if probability < self._neg:
                self._silent += 1
            else:
                if self._silent >= self._pause:
                    self._last_pause = (index - self._silent, index)
                self._silent = 0

            spoken = index + 1 - self._silent - self._start
            if (self._silent >= self._end
                    or (self._silent >= self._phrase and spoken >= self._long)):
                self._emit(found, self._start, index - self._silent + 1)
                self._start = None
            elif index + 1 - self._start >= self._max:
                if self._silent:
                    self._emit(found, self._start, index - self._silent + 1)
                    self._start = None
                elif self._last_pause and self._last_pause[0] - self._start >= self._min:
                    self._emit(found, self._start, self._last_pause[0])
                    self._start = self._last_pause[1]
                else:
                    self._emit(found, self._start, index + 1)
                    self._start = index + 1
                self._last_pause = None
        return found

    def _emit(self, found: list, first: int, after: int):
        if after - first >= self._min:
            found.append((first, after))

    @property
    def speaking(self) -> bool:
        return self._start is not None


class Clock:
    """The time each sample of a live stream was recorded.

    Counts samples from the first chunk's arrival. Where arrivals drift from
    the count by more than REANCHOR, e.g. after dropped sound, it is set anew.
    """

    def __init__(self, rate: int):
        self.rate = rate
        self._origin: datetime | None = None
        self.samples = 0

    def advance(self, count: int, arrived: datetime):
        if self._origin is None:
            self._origin = arrived - timedelta(seconds=count / self.rate)
        self.samples += count
        drift = (arrived - self.at(self.samples)).total_seconds()
        if abs(drift) > REANCHOR:
            self._origin += timedelta(seconds=drift)

    def at(self, sample: float) -> datetime:
        return self._origin + timedelta(seconds=sample / self.rate)


class Ring:
    """The last KEEP seconds of a stream's samples, addressed by sample index."""

    def __init__(self, rate: int, keep: float = KEEP):
        self._keep = int(keep * rate)
        self._chunks: deque[tuple[int, np.ndarray]] = deque()
        self._end = 0

    def add(self, chunk: np.ndarray):
        self._chunks.append((self._end, chunk))
        self._end += len(chunk)
        while self._chunks and self._chunks[0][0] + len(self._chunks[0][1]) < self._end - self._keep:
            self._chunks.popleft()

    def between(self, first: int, after: int) -> np.ndarray:
        parts = [chunk[max(0, first - start):max(0, after - start)]
                 for start, chunk in self._chunks
                 if start < after and start + len(chunk) > first]
        return np.concatenate(parts) if parts else np.zeros(0, dtype=np.float32)

    def clear(self):
        self._chunks.clear()


@dataclass(frozen=True)
class Stufen:
    """Where one utterance's latency went, in seconds: from its end until
    transcription began (the silence that ends it, and any utterance before
    it), transcription and attribution, and the rating request."""

    warten: float
    whisper: float
    bewerten: float


# Who spoke each segment (report.Sprecher), and the lines rated with a few
# earlier ones as context (speech.rate).
Sprecher = Callable[[list[transcribe.Segment], datetime], list[report.Aeusserung]]
Einschaetzen = Callable[[list[report.Aeusserung], list[report.Aeusserung]], list[report.Aeusserung]]


class Utterances:
    """The live sound in, lines out: each as soon as its utterance ends, and
    again with its rating once the model has read it.

    `feed` takes the sound as the microphone or NDI source delivers it and
    returns at once. Three threads follow one another: one cuts the sound
    into utterances; one transcribes, attributes and measures them and hands
    out their lines unrated; one rates the lines waiting, together in one
    request, and hands them out again. `on_lines(lines, bewertet)` is called
    for both.
    """

    def __init__(self, rate: int, on_lines: Callable[[list[report.Aeusserung], bool], None], *,
                 language: str = transcribe.LANGUAGE,
                 meter: loudness.Meter | None = None,
                 laut: loudness.Calibration | None = None,
                 sprecher: Sprecher | None = None,
                 einschaetzen: Einschaetzen | None = None):
        self.rate = rate
        self._on_lines = on_lines
        self._language = language
        self._meter = meter
        self._laut = laut
        self._sprecher = sprecher
        self._einschaetzen = einschaetzen
        self._sound: queue.Queue = queue.Queue()
        self._jobs: queue.Queue = queue.Queue()
        self._unrated: queue.Queue = queue.Queue()
        self._clock = Clock(rate)
        self._ring = Ring(rate)
        self._resample = Resampler(rate)
        self._vad = None
        self._segmenter = Segmenter()
        self._vorher: deque[report.Aeusserung] = deque(maxlen=VORHER)
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        # Seconds from the end of each utterance to its lines on screen and
        # to their rating, and where the time went, for measuring the fast
        # lane (live_sitrep_latency.md, "How to measure it").
        self.latenzen: deque[float] = deque(maxlen=500)
        self.bewertet: deque[float] = deque(maxlen=500)
        self.stufen: deque[Stufen] = deque(maxlen=500)
        # The exception that stopped a thread, if one did.
        self.error: Exception | None = None

    def start(self) -> "Utterances":
        """Load the models and start the threads."""
        self._vad = Vad()
        transcribe.load()
        for target in (self._cut, self._transcribe, self._rate):
            thread = threading.Thread(target=target, daemon=True)
            thread.start()
            self._threads.append(thread)
        return self

    def feed(self, samples: np.ndarray, arrived: datetime | None = None):
        """Sound as it arrives, mono float samples at `rate`."""
        self._sound.put((samples, arrived or datetime.now()))

    def _cut(self):
        try:
            while not self._stop.is_set():
                try:
                    samples, arrived = self._sound.get(timeout=0.1)
                except queue.Empty:
                    continue
                self.process(samples, arrived)
        except Exception as error:
            self._fail(error)

    def process(self, samples: np.ndarray, arrived: datetime):
        """Take in one chunk of sound: measure it, and queue any utterance it ends.

        Runs on the cutting thread; public so that a test can drive it."""
        self._clock.advance(len(samples), arrived)
        self._ring.add(samples)
        if self._meter is not None:
            self._meter.add(samples, self.rate, self._clock.at(self._clock.samples))
        for first, after in self._segmenter.push(self._vad(self._resample(samples))):
            self._queue_utterance(first, after)

    def _queue_utterance(self, first: int, after: int):
        pad = int(PAD * self.rate)
        begins = max(0, int(first * CHUNK * self.rate / VAD_RATE) - pad)
        ends = min(self._clock.samples, int(after * CHUNK * self.rate / VAD_RATE) + pad)
        sound = self._ring.between(begins, ends)
        if len(sound):
            self._jobs.put((sound, self._clock.at(begins), self._clock.at(ends)))

    def _transcribe(self):
        try:
            while not self._stop.is_set():
                try:
                    job = self._jobs.get(timeout=0.1)
                except queue.Empty:
                    continue
                self.transcribe(*job)
        except Exception as error:
            self._fail(error)

    def transcribe(self, sound: np.ndarray, begins: datetime, ends: datetime):
        """Transcribe, attribute and measure one utterance, and hand out its lines unrated.

        Runs on the transcribing thread; public so that a test can drive it."""
        started = datetime.now()
        spoken = ends - timedelta(seconds=PAD)
        segmente = transcribe.segments(capture.encode_wav(sound, self.rate),
                                       language=self._language)
        lines = (self._sprecher(segmente, begins) if self._sprecher else
                 [report.Aeusserung(text=segment.text,
                                    beginn=begins + timedelta(seconds=segment.start),
                                    ende=begins + timedelta(seconds=segment.end))
                  for segment in segmente])
        if not lines:
            return
        lines = [self._measure(line) for line in lines]
        now = datetime.now()
        self.latenzen.append((now - spoken).total_seconds())
        self._on_lines(lines, False)
        if self._einschaetzen:
            self._unrated.put((lines, spoken, (started - spoken).total_seconds(),
                               (now - started).total_seconds()))

    def _rate(self):
        try:
            while not self._stop.is_set():
                try:
                    batch = [self._unrated.get(timeout=0.1)]
                except queue.Empty:
                    continue
                # Lines handed out meanwhile are rated with these.
                while True:
                    try:
                        batch.append(self._unrated.get_nowait())
                    except queue.Empty:
                        break
                self.rate_lines(batch)
        except Exception as error:
            self._fail(error)

    def rate_lines(self, batch: list[tuple[list[report.Aeusserung], datetime, float, float]]):
        """Rate the lines of several utterances in one request and hand them out again.

        Runs on the rating thread; public so that a test can drive it."""
        lines = [line for utterance, *_ in batch for line in utterance]
        asked = datetime.now()
        rated = self._einschaetzen(lines, list(self._vorher))
        self._vorher.extend(rated)
        now = datetime.now()
        for _, spoken, warten, whisper in batch:
            self.bewertet.append((now - spoken).total_seconds())
            self.stufen.append(Stufen(warten=warten, whisper=whisper,
                                      bewerten=(now - asked).total_seconds()))
        self._on_lines(rated, True)

    def _measure(self, line: report.Aeusserung) -> report.Aeusserung:
        """The line with its loudness, learning the session's normal speech from it."""
        if self._meter is None or self._laut is None:
            return line
        level = self._meter.level(line.beginn, line.ende)
        self._laut.learn(level, loudness.seconds(line.beginn, line.ende))
        return line.model_copy(update={
            "pegel_db": level,
            "verstaerkung": round(self._laut.gain(level), 2),
            "lautstaerke": loudness.label(self._laut, level)})

    def _fail(self, error: Exception):
        self.error = error
        print(f"speech stopped: {error!r}", file=sys.stderr)

    @property
    def speaking(self) -> bool:
        """Whether an utterance is under way now."""
        return self._segmenter.speaking

    def clear(self):
        """Delete the sound and the lines held."""
        self._ring.clear()
        self._vorher.clear()
        for waiting in (self._sound, self._jobs, self._unrated):
            while True:
                try:
                    waiting.get_nowait()
                except queue.Empty:
                    break

    def close(self):
        self._stop.set()
        for thread in self._threads:
            thread.join(timeout=5.0)
