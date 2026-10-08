"""Embodied search: a movement performed live becomes the query.

The "body" half of embodied search in knowledge/components/02_processing.md:
"press a button, then press a button again after a few seconds to capture that
live sequence and then that gets used to do the retrieval". Phase 3 in
progress_tracker.md.

Bodies are detected while the movement happens rather than after it: frames are
sampled at the index's own rate, four per second, and only the keypoints are
kept. A capture of any length therefore costs next to no memory, and its query
is ready the moment the stop press arrives.

The query must have the shape of what was indexed, since a sequence spanning a
different duration describes a differently paced movement
(smartsearch/pose.py). A capture is therefore cut into windows of one indexed
segment, 16 detections over four seconds, stepped by the index's own two-second
stride, and each window is searched on its own. A capture shorter than one
segment is extended backwards from the stop press to a full segment, which is
how the index saw a short movement: wholly inside a four-second window
(apollon_pose.keypoints, SEGMENT_OVERLAP).

Presses arrive from the terminal (Enter toggles) and over OSC, so a button in
TouchDesigner or a QLab cue can start and stop a capture.
"""

import queue
import sys
import threading
import time
from collections import defaultdict, deque
from dataclasses import replace
from pathlib import Path
from typing import Callable, Iterable

import cv2
import numpy as np
from apollon_pose import keypoints, model
from pythonosc.dispatcher import Dispatcher
from pythonosc.osc_server import ThreadingOSCUDPServer

from . import config
from .client import Hit, Wise

# Seconds between sampled frames: the index's rate of 16 frames per 4 s segment.
SAMPLE_SECONDS = keypoints.SEGMENT_DURATION / keypoints.FRAMES_PER_SEGMENT

# Detections per query window, and how far consecutive windows step.
WINDOW = keypoints.FRAMES_PER_SEGMENT
STRIDE = round(keypoints.SEGMENT_OVERLAP / SAMPLE_SECONDS)

START_ADDRESS = "/apollon/body/start"
STOP_ADDRESS = "/apollon/body/stop"

START, STOP, TOGGLE = "start", "stop", "toggle"

# Results from one recording closer together than this many seconds count as
# the same moment found again, and only the best of them is kept. Without it,
# 7 to 10 of the top 16 results on hitl_database came from one recording,
# many of them neighbouring windows of one moment.
MIN_GAP_SECONDS = 30.0

# How many moments to retrieve when results are thinned out per recording or
# in time, the most the client asks WISE for. On hitl_database, 16 results 30 s
# apart and at most 3 per recording needed up to 400 candidates; 1000 cost
# under 90 ms per query window.
_SPREAD_FETCH = 1000

# How long a trigger wait blocks before checking again. A blocking queue read
# with no timeout does not see Ctrl+C on Windows.
_POLL_SECONDS = 0.5


def query_windows(detections: list) -> list[list]:
    """Cut a captured sequence into windows the shape of one indexed segment.

    The last window is aligned to the end of the capture, so the final moments of
    a movement are always searched even when the capture is not a whole number of
    strides long.
    """
    if len(detections) <= WINDOW:
        return [detections]
    starts = list(range(0, len(detections) - WINDOW + 1, STRIDE))
    if starts[-1] != len(detections) - WINDOW:
        starts.append(len(detections) - WINDOW)
    return [detections[start:start + WINDOW] for start in starts]


def merge_hits(hit_lists: Iterable[list[Hit]]) -> list[Hit]:
    """Combine the results of several windows into one ranked list.

    Neighbouring windows of one movement tend to find the same moment with
    slightly different ranges. Hits in the same recording whose ranges overlap
    become one hit spanning both, carrying the better score.
    """
    by_media = defaultdict(list)
    for hits in hit_lists:
        for hit in hits:
            by_media[hit.media_id].append(hit)

    merged = []
    for hits in by_media.values():
        hits.sort(key=lambda hit: hit.ts)
        current = hits[0]
        for hit in hits[1:]:
            if hit.ts <= current.te:
                current = _span(max(current, hit, key=lambda h: h.score),
                                current.ts, max(current.te, hit.te))
            else:
                merged.append(current)
                current = hit
        merged.append(current)

    merged.sort(key=lambda hit: hit.score, reverse=True)
    return merged


def _span(hit: Hit, ts: float, te: float) -> Hit:
    base = hit.media_url.split("#", 1)[0]
    return replace(hit, ts=ts, te=te, media_url=f"{base}#t={ts},{te}")


def best_per_window(hit_lists: Iterable[list[Hit]]) -> list[Hit]:
    """Combine the results of several windows without joining neighbours.

    The counterpart of merge_hits for segment results: windows of one movement
    retrieve the same segments, so a segment found by several windows is kept
    once with its best score. Ranges are left alone — joining neighbouring
    segments here would rebuild the long spans that segment results exist to
    avoid.
    """
    best = {}
    for hits in hit_lists:
        for hit in hits:
            key = (hit.media_id, hit.ts, hit.te)
            if key not in best or hit.score > best[key].score:
                best[key] = hit
    return sorted(best.values(), key=lambda hit: hit.score, reverse=True)


def cap_per_file(hits: list[Hit], per_file: int) -> list[Hit]:
    """Keep at most `per_file` hits from each recording, in rank order."""
    counts = defaultdict(int)
    kept = []
    for hit in hits:
        if counts[hit.media_id] < per_file:
            counts[hit.media_id] += 1
            kept.append(hit)
    return kept


def spread_in_time(hits: list[Hit], min_gap: float) -> list[Hit]:
    """Keep hits in rank order, dropping any that lies within `min_gap`
    seconds of a better hit in the same recording."""
    kept = []
    for hit in hits:
        if all(other.media_id != hit.media_id or _distance(other, hit) >= min_gap
               for other in kept):
            kept.append(hit)
    return kept


def _distance(a: Hit, b: Hit) -> float:
    """Seconds between two ranges in one recording; 0 if they overlap."""
    return max(0.0, max(a.ts, b.ts) - min(a.te, b.te))


def search(wise: Wise, detections: list, *, feature_id: str, limit: int,
           per_file: int | None = None, min_gap: float = 0.0,
           merged: bool = True) -> list[Hit]:
    """Search the pose index with a captured movement.

    Windows in which no body was found are skipped. Returns an empty list when
    none of the capture contained a body.
    """
    fetch = max(limit, _SPREAD_FETCH) if per_file or min_gap else limit
    hit_lists = []
    for window in query_windows(detections):
        vector = keypoints.segment_embedding(window)
        if vector.any():
            hit_lists.append(wise.search_vector(
                vector, feature_extractor_id=feature_id, limit=fetch, merged=merged))

    hits = merge_hits(hit_lists) if merged else best_per_window(hit_lists)
    if min_gap:
        hits = spread_in_time(hits, min_gap)
    if per_file:
        hits = cap_per_file(hits, per_file)
    return hits[:limit]


class PoseRecorder:
    """Detects bodies in a video source at the index's frame rate.

    Always keeps the most recent segment's worth of detections, so a capture
    shorter than one segment can be extended backwards, and everything detected
    between start() and stop().
    """

    def __init__(self, latest: Callable[[], np.ndarray]):
        # Loaded before sampling starts, so the first sample is not late by the
        # model's load time.
        model.load()
        self._latest = latest
        self._recent = deque(maxlen=WINDOW)
        self._captured = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        next_sample = time.monotonic()
        while not self._stop.is_set():
            detection = model.detect(self._latest())
            with self._lock:
                self._recent.append(detection)
                if self._captured is not None:
                    self._captured.append(detection)

            next_sample += SAMPLE_SECONDS
            delay = next_sample - time.monotonic()
            if delay > 0:
                self._stop.wait(delay)
            else:
                # Detection is slower than the sampling rate, so the captured
                # movement is spread over fewer frames than the index expects.
                # Nothing downstream can tell.
                print(f"pose detection running {-delay:.2f}s behind the "
                      f"{SAMPLE_SECONDS:g}s sampling interval", file=sys.stderr)
                next_sample = time.monotonic()

    @property
    def ready(self) -> bool:
        """Whether a full segment has been detected since the source opened."""
        with self._lock:
            return len(self._recent) == WINDOW

    def start(self):
        with self._lock:
            self._captured = []

    def stop(self) -> list:
        """End a capture and return its detections, at least one segment long."""
        with self._lock:
            captured, self._captured = self._captured, None
            if len(captured) < WINDOW:
                return list(self._recent)
            return captured

    def close(self):
        self._stop.set()
        self._thread.join(timeout=2.0)


class FilePlayback:
    """Plays a recording in real time in place of a camera.

    Lets the live path be rehearsed and tested against footage whose content is
    known, from any point in the file.
    """

    def __init__(self, path: Path, start: float = 0.0):
        self._capture = cv2.VideoCapture(str(path))
        if not self._capture.isOpened():
            raise RuntimeError(f"Could not open {path}")
        self._capture.set(cv2.CAP_PROP_POS_MSEC, start * 1000)
        self._fps = self._capture.get(cv2.CAP_PROP_FPS)
        self._start = start
        self._frames = 0
        self._frame = None
        self._lock = threading.Lock()
        self._first = threading.Event()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        self._first.wait()

    def _run(self):
        began = time.monotonic()
        while not self._stop.is_set():
            ok, frame = self._capture.read()
            if not ok:
                break
            with self._lock:
                self._frame = frame
                self._frames += 1
            self._first.set()
            self._stop.wait(max(0.0, began + self._frames / self._fps - time.monotonic()))
        self._first.set()

    def latest(self) -> np.ndarray:
        with self._lock:
            return self._frame

    def position(self) -> float:
        """Seconds into the recording of the frame currently showing."""
        with self._lock:
            return self._start + self._frames / self._fps

    def close(self):
        self._stop.set()
        self._thread.join(timeout=2.0)
        self._capture.release()


class Triggers:
    """Start and stop presses from the terminal and from OSC, in arrival order."""

    def __init__(self, host: str = config.CONTROL_HOST, port: int = config.CONTROL_PORT):
        self._events = queue.Queue()

        dispatcher = Dispatcher()
        dispatcher.map(START_ADDRESS, lambda *_: self._events.put(START))
        dispatcher.map(STOP_ADDRESS, lambda *_: self._events.put(STOP))
        self._server = ThreadingOSCUDPServer((host, port), dispatcher)
        threading.Thread(target=self._server.serve_forever, daemon=True).start()
        threading.Thread(target=self._read_keyboard, daemon=True).start()

    def _read_keyboard(self):
        for _ in sys.stdin:
            self._events.put(TOGGLE)

    def next(self) -> str | None:
        """The next press, or None if none arrived within the poll interval."""
        try:
            return self._events.get(timeout=_POLL_SECONDS)
        except queue.Empty:
            return None

    def close(self):
        self._server.shutdown()
        self._server.server_close()


def next_state(recording: bool, event: str) -> bool:
    """Whether a capture is running after a press.

    Start while recording and stop while idle change nothing, so a doubled
    button press cannot cut a capture short or search with nothing.
    """
    if event == TOGGLE:
        return not recording
    return event == START


def source(event: str) -> str:
    """Where a press came from. The terminal only ever toggles."""
    return "keyboard" if event == TOGGLE else "osc"


def run(recorder: PoseRecorder, triggers: Triggers,
        on_start: Callable[[str], None], on_capture: Callable[[list, str], None]):
    """Turn presses into captures until interrupted.

    Each callback is told which press caused the transition, so a capture that
    began or ended unexpectedly can be traced to the terminal or to OSC.
    """
    recording = False
    while True:
        event = triggers.next()
        if event is None:
            continue
        wanted = next_state(recording, event)
        if wanted == recording:
            continue
        recording = wanted
        if recording:
            recorder.start()
            on_start(event)
        else:
            on_capture(recorder.stop(), event)
