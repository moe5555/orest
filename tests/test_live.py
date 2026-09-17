"""Live body capture: query windows, result merging, presses and the recorder."""

import io
import time

import numpy as np
import pytest
from pythonosc.udp_client import SimpleUDPClient

from smartsearch import live
from smartsearch.client import Hit


def make_hit(media_id="1", ts=0.0, te=4.0, score=0.9) -> Hit:
    return Hit(
        media_id=media_id, filename=f"{media_id}.mp4", ts=ts, te=te, score=score,
        target="video", vector_id="v", media_url=f"http://wise/p/media/{media_id}#t={ts},{te}",
        thumbnail_url="",
    )


# Query windows

def test_windows_have_the_shape_of_an_indexed_segment():
    assert live.WINDOW == 16
    assert live.STRIDE == 8
    assert live.SAMPLE_SECONDS == pytest.approx(0.25)


def test_a_capture_of_one_segment_is_searched_once():
    assert live.query_windows(list(range(16))) == [list(range(16))]


def test_a_longer_capture_steps_by_the_index_stride():
    windows = live.query_windows(list(range(32)))
    assert [window[0] for window in windows] == [0, 8, 16]
    assert all(len(window) == 16 for window in windows)


def test_the_last_window_always_reaches_the_end_of_the_capture():
    # 5 s at 4 fps: strides alone would leave the final second unsearched.
    windows = live.query_windows(list(range(20)))
    assert [window[0] for window in windows] == [0, 4]
    assert windows[-1][-1] == 19


# Merging and capping

def test_overlapping_hits_in_one_recording_become_one_spanning_both():
    merged = live.merge_hits([[make_hit(ts=10, te=18, score=0.8)],
                              [make_hit(ts=14, te=22, score=0.9)]])
    assert len(merged) == 1
    assert (merged[0].ts, merged[0].te, merged[0].score) == (10, 22, 0.9)


def test_a_merged_hit_links_to_its_new_range():
    merged = live.merge_hits([[make_hit(ts=10, te=18)], [make_hit(ts=14, te=22)]])
    assert merged[0].media_url.endswith("#t=10,22")


def test_separate_moments_stay_separate_and_are_ranked_by_score():
    merged = live.merge_hits([[make_hit(ts=10, te=14, score=0.5), make_hit(ts=100, te=104, score=0.9)]])
    assert [(hit.ts, hit.score) for hit in merged] == [(100, 0.9), (10, 0.5)]


def test_overlapping_ranges_in_different_recordings_are_not_merged():
    assert len(live.merge_hits([[make_hit("1", 10, 18)], [make_hit("2", 12, 20)]])) == 2


def test_segment_results_keep_neighbouring_segments_apart():
    # Adjacent segments would chain into one long span if merged.
    hits = live.best_per_window([[make_hit(ts=10, te=14, score=0.8)],
                                 [make_hit(ts=12, te=16, score=0.9)]])
    assert [(hit.ts, hit.te) for hit in hits] == [(12, 16), (10, 14)]


def test_a_segment_found_by_several_windows_is_kept_once_with_its_best_score():
    hits = live.best_per_window([[make_hit(ts=10, te=14, score=0.7)],
                                 [make_hit(ts=10, te=14, score=0.9)]])
    assert [(hit.ts, hit.score) for hit in hits] == [(10, 0.9)]


def test_a_cap_keeps_the_best_hits_of_each_recording():
    hits = [make_hit("1", 0, 4, 0.9), make_hit("1", 10, 14, 0.8), make_hit("2", 0, 4, 0.7),
            make_hit("1", 20, 24, 0.6)]
    assert [(hit.media_id, hit.score) for hit in live.cap_per_file(hits, 2)] == \
        [("1", 0.9), ("1", 0.8), ("2", 0.7)]


# Searching

class FakeWise:
    def __init__(self, hits):
        self.hits = hits
        self.calls = []

    def search_vector(self, vector, *, feature_extractor_id, limit, merged=True):
        self.calls.append(limit)
        return self.hits


def test_windows_without_a_body_are_not_searched(monkeypatch):
    embeddings = iter([np.zeros(4), np.ones(4)])
    monkeypatch.setattr(live.keypoints, "segment_embedding", lambda window: next(embeddings))
    wise = FakeWise([make_hit()])
    live.search(wise, list(range(24)), feature_id="pose", limit=5)
    assert len(wise.calls) == 1


def test_a_capture_with_no_body_anywhere_returns_nothing(monkeypatch):
    monkeypatch.setattr(live.keypoints, "segment_embedding", lambda window: np.zeros(4))
    assert live.search(FakeWise([make_hit()]), list(range(16)), feature_id="pose", limit=5) == []


def test_segment_mode_searches_without_merging(monkeypatch):
    monkeypatch.setattr(live.keypoints, "segment_embedding", lambda window: np.ones(4))
    wise = FakeWise([make_hit("1", 10, 14, 0.8), make_hit("1", 12, 16, 0.9)])
    hits = live.search(wise, list(range(24)), feature_id="pose", limit=5, merged=False)
    assert [(hit.ts, hit.te) for hit in hits] == [(12, 16), (10, 14)]


def test_a_per_file_cap_retrieves_more_candidates_to_fill_the_list(monkeypatch):
    monkeypatch.setattr(live.keypoints, "segment_embedding", lambda window: np.ones(4))
    wise = FakeWise([make_hit("1", 0, 4), make_hit("1", 10, 14), make_hit("2", 0, 4)])
    hits = live.search(wise, list(range(16)), feature_id="pose", limit=2, per_file=1)
    assert wise.calls == [2 * live._CAP_FETCH_FACTOR]
    assert [hit.media_id for hit in hits] == ["1", "2"]


# Presses

@pytest.mark.parametrize("recording, event, expected", [
    (False, live.START, True),
    (True, live.STOP, False),
    (False, live.TOGGLE, True),
    (True, live.TOGGLE, False),
    (True, live.START, True),
    (False, live.STOP, False),
])
def test_presses_move_between_idle_and_capturing(recording, event, expected):
    assert live.next_state(recording, event) is expected


def test_osc_presses_arrive_as_start_and_stop(monkeypatch):
    monkeypatch.setattr(live.sys, "stdin", io.StringIO(""))
    triggers = live.Triggers("127.0.0.1", 0)
    try:
        port = triggers._server.server_address[1]
        sender = SimpleUDPClient("127.0.0.1", port)
        sender.send_message(live.START_ADDRESS, [])
        sender.send_message(live.STOP_ADDRESS, 1)
        assert [triggers.next(), triggers.next()] == [live.START, live.STOP]
    finally:
        triggers.close()


def test_each_line_on_the_terminal_toggles(monkeypatch):
    monkeypatch.setattr(live.sys, "stdin", io.StringIO("\n\n"))
    triggers = live.Triggers("127.0.0.1", 0)
    try:
        assert [triggers.next(), triggers.next()] == [live.TOGGLE, live.TOGGLE]
    finally:
        triggers.close()


# Recorder

@pytest.fixture
def recorder(monkeypatch):
    counter = iter(range(10_000))
    monkeypatch.setattr(live.model, "load", lambda: None)
    monkeypatch.setattr(live.model, "detect", lambda frame: next(counter))
    monkeypatch.setattr(live, "SAMPLE_SECONDS", 0.005)
    recorder = live.PoseRecorder(lambda: None)
    yield recorder
    recorder.close()


def wait_until(condition, timeout=5.0):
    deadline = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < deadline
        time.sleep(0.005)


def test_a_short_capture_is_extended_back_to_a_full_segment(recorder):
    wait_until(lambda: recorder.ready)
    recorder.start()
    detections = recorder.stop()
    assert len(detections) == live.WINDOW
    assert detections == sorted(detections)


def test_a_long_capture_returns_everything_detected_during_it(recorder):
    wait_until(lambda: recorder.ready)
    recorder.start()
    before = recorder._recent[-1]
    wait_until(lambda: len(recorder._captured) >= 3 * live.WINDOW)
    detections = recorder.stop()
    assert len(detections) >= 3 * live.WINDOW
    assert detections[0] > before
    assert detections == list(range(detections[0], detections[0] + len(detections)))


def test_a_press_is_reported_as_coming_from_the_terminal_or_from_osc():
    assert live.source(live.TOGGLE) == "keyboard"
    assert live.source(live.START) == "osc"
    assert live.source(live.STOP) == "osc"


class Presses:
    """Trigger source that runs dry, ending the session loop."""

    def __init__(self, events):
        self._events = iter(events)

    def next(self):
        try:
            return next(self._events)
        except StopIteration:
            raise KeyboardInterrupt


def test_each_capture_is_told_which_press_started_and_ended_it(recorder):
    seen = []
    # A None in the middle is a poll that saw no press, and must not end the
    # capture it interrupts.
    presses = Presses([live.TOGGLE, None, live.STOP])
    with pytest.raises(KeyboardInterrupt):
        live.run(recorder, presses,
                 lambda event: seen.append(("start", event)),
                 lambda detections, event: seen.append(("stop", event)))
    assert seen == [("start", live.TOGGLE), ("stop", live.STOP)]
