"""Clip naming and the ffmpeg command lines that cut search results."""

import sqlite3
from pathlib import Path

import pytest

from smartsearch import clips
from smartsearch.client import Hit

DESTINATION = Path("/clips/probe/out.mp4.part")


def make_hit(**changes) -> Hit:
    fields = dict(
        media_id="1", filename="Othello 2022.mp4", ts=2093.0, te=2101.5, score=0.97,
        target="video", vector_id="0/1/12",
        media_url="http://127.0.0.1:9670/probe/media/1#t=2093.0,2101.5",
        thumbnail_url="http://127.0.0.1:9670/probe/thumbnail?media_id=1&timestamp=2093.0",
    )
    return Hit(**{**fields, **changes})


def test_the_source_is_wises_media_route_without_the_browser_fragment():
    assert clips.source_url(make_hit()) == "http://127.0.0.1:9670/probe/media/1"


def make_project(root: Path, location: Path, recordings: dict[int, str]) -> Path:
    """A WISE project database holding only the tables the path lookup reads."""
    project = root / "probe"
    (project / "metadata").mkdir(parents=True)
    database = sqlite3.connect(project / "metadata" / "internal.db")
    database.execute("CREATE TABLE source_collections (id INTEGER, location TEXT, type TEXT)")
    database.execute("CREATE TABLE media (id INTEGER, source_collection_id INTEGER, path TEXT)")
    database.execute("INSERT INTO source_collections VALUES (1, ?, 'DIR')", (str(location),))
    database.executemany("INSERT INTO media VALUES (?, 1, ?)", recordings.items())
    database.commit()
    database.close()
    return project


def test_recordings_are_found_under_the_folder_they_were_added_from(tmp_path):
    project = make_project(tmp_path, tmp_path / "footage", {1: "Othello 2022.mp4", 2: "week1/day2.mp4"})
    assert clips.recording_paths(project) == {
        "1": tmp_path / "footage" / "Othello 2022.mp4",
        "2": tmp_path / "footage" / "week1" / "day2.mp4",
    }


def test_a_project_without_a_local_database_has_no_recordings(tmp_path):
    assert clips.recording_paths(tmp_path / "elsewhere") == {}


def test_a_recording_on_disk_is_read_directly(tmp_path):
    recording = tmp_path / "Othello 2022.mp4"
    recording.write_bytes(b"")
    assert clips.source(make_hit(), {"1": recording}) == str(recording)


def test_a_recording_missing_from_disk_is_read_through_wise(tmp_path):
    missing = {"1": tmp_path / "moved.mp4"}
    assert clips.source(make_hit(), missing) == "http://127.0.0.1:9670/probe/media/1"
    assert clips.source(make_hit(), {}) == "http://127.0.0.1:9670/probe/media/1"


def test_the_same_moment_always_maps_to_the_same_clip():
    assert clips.clip_name(make_hit(), clips.FAST) == clips.clip_name(make_hit(score=0.5), clips.FAST)


def test_clip_names_carry_recording_range_and_mode():
    assert clips.clip_name(make_hit(), clips.PRECISE) == "1-Othello 2022-2093000-2101500-precise.mp4"


def test_recordings_sharing_a_file_name_get_different_clips():
    assert clips.clip_name(make_hit(media_id="1"), clips.FAST) != \
        clips.clip_name(make_hit(media_id="2"), clips.FAST)


def test_fast_and_precise_clips_of_one_moment_are_kept_apart():
    assert clips.clip_name(make_hit(), clips.FAST) != clips.clip_name(make_hit(), clips.PRECISE)


def test_a_recording_in_a_subfolder_names_its_clip_by_the_file_alone():
    assert "/" not in clips.clip_name(make_hit(filename="week1/day2.mp4"), clips.FAST)


def test_seeking_happens_before_the_input_in_both_modes():
    # After the input, ffmpeg would decode from the start of the recording.
    for mode in clips.MODES:
        command = clips.cut_command("src", 2093.0, 8.5, DESTINATION, mode)
        assert command.index("-ss") < command.index("-i")


def test_the_clip_covers_exactly_the_hit_range():
    command = clips.cut_command("src", 2093.0, 8.5, DESTINATION, clips.PRECISE)
    assert command[command.index("-ss") + 1] == "2093.000"
    assert command[command.index("-t") + 1] == "8.500"


def test_fast_mode_copies_every_stream_without_encoding():
    command = clips.cut_command("src", 0.0, 8.0, DESTINATION, clips.FAST)
    assert command[command.index("-c") + 1] == "copy"
    assert "-c:v" not in command


@pytest.mark.parametrize("encoder", clips.ENCODERS)
def test_precise_mode_encodes_h264_with_the_chosen_encoder(encoder):
    command = clips.cut_command("src", 0.0, 8.0, DESTINATION, clips.PRECISE, encoder)
    assert command[command.index("-c:v") + 1] == encoder
    assert command[command.index("-pix_fmt") + 1] == "yuv420p"


def test_the_container_is_named_explicitly_for_the_temporary_file():
    # A ".part" suffix gives ffmpeg no container to infer.
    command = clips.cut_command("src", 0.0, 8.0, DESTINATION, clips.FAST)
    assert command[command.index("-f") + 1] == "mp4"
    assert command[-1] == str(DESTINATION)


def test_the_preroll_is_read_from_the_first_video_packet_only():
    command = clips.preroll_command(Path("clip.mp4"))
    assert command[command.index("-select_streams") + 1] == "v:0"
    assert command[command.index("-read_intervals") + 1] == "%+#1"


def test_a_negative_first_timestamp_is_the_preroll():
    # ffprobe's reading of a clip cut at 13 s from a source with a keyframe at 10 s.
    assert clips.parse_preroll("-3.000000\r\n") == pytest.approx(3.0)


def test_a_clip_starting_on_its_first_frame_has_no_preroll():
    assert clips.parse_preroll("0.000000\n") == 0.0


def test_a_clip_already_on_disk_is_reused_without_running_ffmpeg(tmp_path, monkeypatch):
    hit = make_hit()
    existing = tmp_path / clips.clip_name(hit, clips.FAST)
    existing.write_bytes(b"clip")
    monkeypatch.setattr(clips.subprocess, "run", lambda *a, **k: pytest.fail("ffmpeg ran"))
    monkeypatch.setattr(clips, "preroll", lambda path: 0.5)
    assert clips.cut(hit, clips.FAST, tmp_path) == clips.Clip(existing, 0.5)


def test_a_clip_appears_under_its_final_name_only_once_ffmpeg_succeeds(tmp_path, monkeypatch):
    hit = make_hit()
    seen = {}

    def fake_ffmpeg(argv, check):
        partial = Path(argv[-1])
        seen["final_during_write"] = (tmp_path / clips.clip_name(hit, clips.FAST)).exists()
        partial.write_bytes(b"clip")

    monkeypatch.setattr(clips.config, "ffmpeg", lambda: Path("ffmpeg"))
    monkeypatch.setattr(clips.subprocess, "run", fake_ffmpeg)
    monkeypatch.setattr(clips, "preroll", lambda path: 0.0)
    clip = clips.cut(hit, clips.FAST, tmp_path)
    assert seen["final_during_write"] is False
    assert clip.path.read_bytes() == b"clip"
    assert not list(tmp_path.glob("*.part"))


def test_a_clip_is_cut_from_the_recording_on_disk(tmp_path, monkeypatch):
    recording = tmp_path / "Othello 2022.mp4"
    recording.write_bytes(b"")
    inputs = []

    def fake_ffmpeg(argv, check):
        inputs.append(argv[argv.index("-i") + 1])
        Path(argv[-1]).write_bytes(b"clip")

    monkeypatch.setattr(clips.config, "ffmpeg", lambda: Path("ffmpeg"))
    monkeypatch.setattr(clips.subprocess, "run", fake_ffmpeg)
    monkeypatch.setattr(clips, "preroll", lambda path: 0.0)
    clips.cut(make_hit(), clips.FAST, tmp_path / "clips", recordings={"1": recording})
    assert inputs == [str(recording)]


def test_clips_are_cut_and_yielded_in_rank_order(tmp_path, monkeypatch):
    order = []
    monkeypatch.setattr(clips, "cut", lambda hit, *a: order.append(hit.ts) or tmp_path / str(hit.ts))
    hits = [make_hit(ts=10.0), make_hit(ts=5.0), make_hit(ts=30.0)]
    ranks = [rank for rank, _, _ in clips.cut_all(hits, clips.FAST, tmp_path)]
    assert ranks == [1, 2, 3]
    assert order == [10.0, 5.0, 30.0]
