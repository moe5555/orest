"""Turning a WISE search response into a single ranked list of moments.

The response body below is the shape WISE returns for a video search: results
split across one block per modality, each with its own table of media
descriptions, and hits carrying relative URLs. Everything downstream of search
consumes Hit instead.
"""

import pytest

from smartsearch import client

PROJECT = "rehearsals"
BASE = "http://127.0.0.1:9670"

RESPONSE = {
    "time": 0.04,
    "query": [],
    "video_results": {
        "total": 300,
        "unmerged_windows": [
            {"vector_id": "0/1/900", "media_id": "1", "link": "media/1#t=450.0,454.0",
             "thumbnail": "thumbnail?media_id=1&timestamp=450.0", "distance": -4.9,
             "ts": 450.0, "te": 454.0, "thumbnail_ts": 450.0},
        ],
        "merged_windows": [
            {"vector_id": "0/1/269", "media_id": "1", "link": "media/1#t=134.5,157.0",
             "thumbnail": "thumbnail?media_id=1&timestamp=134.5", "distance": -3.993,
             "ts": 134.5, "te": 157.0, "thumbnail_ts": 134.5},
            {"vector_id": "0/2/635", "media_id": "2", "link": "media/2#t=317.5,322.0",
             "thumbnail": "thumbnail?media_id=2&timestamp=317.5", "distance": -4.816,
             "ts": 317.5, "te": 322.0, "thumbnail_ts": 317.5},
        ],
        "videos": {
            "1": {"id": "1", "filename": "Othello 2022.mp4", "duration": 13054.0,
                  "media_type": "video", "timeline_hover_thumbnails": "storyboard/1.vtt"},
            "2": {"id": "2", "filename": "Theaterprobe.mp4", "duration": 1140.0,
                  "media_type": "video", "timeline_hover_thumbnails": "storyboard/2.vtt"},
        },
    },
    "video_audio_results": None,
    "image_results": None,
}


@pytest.fixture
def wise():
    return client.Wise(PROJECT, base_url=BASE)


@pytest.fixture
def hits(wise):
    return wise._hits(RESPONSE)


def test_merged_moments_are_returned_rather_than_single_frames(hits):
    # Consecutive frames of one moment are collapsed by the server; the merged
    # form is the range that plays back.
    assert len(hits) == 2
    assert (hits[0].ts, hits[0].te) == (134.5, 157.0)


def test_hits_are_ranked_with_the_best_score_first(hits):
    assert [hit.score for hit in hits] == sorted((h.score for h in hits), reverse=True)


def test_a_hit_carries_the_filename_from_the_media_table(hits):
    assert hits[0].filename == "Othello 2022.mp4"
    assert hits[1].filename == "Theaterprobe.mp4"


def test_relative_urls_are_resolved_against_the_project(hits):
    assert hits[0].media_url == f"{BASE}/{PROJECT}/media/1#t=134.5,157.0"
    assert hits[0].thumbnail_url == f"{BASE}/{PROJECT}/thumbnail?media_id=1&timestamp=134.5"


def test_hit_duration_is_the_length_of_the_moment(hits):
    assert hits[0].seconds == pytest.approx(22.5)


def test_empty_result_blocks_are_skipped(wise):
    assert wise._hits({"video_results": None, "image_results": None}) == []


def test_audio_and_video_results_arrive_in_one_list(wise):
    payload = dict(RESPONSE)
    payload["video_audio_results"] = {
        "total": 300,
        "merged_windows": [
            {"vector_id": "0/1/12", "media_id": "1", "link": "media/1#t=508.0,512.0",
             "thumbnail": "thumbnail?media_id=1&timestamp=508.0", "distance": 2.9,
             "ts": 508.0, "te": 512.0, "thumbnail_ts": 508.0},
        ],
        "videos": RESPONSE["video_results"]["videos"],
    }
    hits = wise._hits(payload)
    assert len(hits) == 3
    assert {hit.target for hit in hits} == {client.VIDEO, client.AUDIO}


def test_more_vectors_are_retrieved_than_moments_requested(wise):
    # Merging collapses runs of frames, so retrieving one vector per wanted
    # moment would return a fraction of them.
    assert wise._window(limit=10, candidates=None) == 100
    assert wise._window(limit=1, candidates=None) == 50


def test_the_retrieval_window_stays_within_the_server_limit(wise):
    assert wise._window(limit=500, candidates=None) == 1000
    assert wise._window(limit=10, candidates=9999) == 1000


def test_an_explicit_candidate_count_is_honoured(wise):
    assert wise._window(limit=10, candidates=25) == 25


def test_timecode_reads_as_a_position_in_a_recording():
    assert client.timecode(0) == "0:00:00"
    assert client.timecode(134.5) == "0:02:14"
    assert client.timecode(13054) == "3:37:34"
