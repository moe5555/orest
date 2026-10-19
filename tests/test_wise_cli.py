"""The command lines Apollon builds for WISE.

WISE infers what it will do from the shape of its arguments, and several of its
options behave differently from what their names suggest, so the argument list
is worth checking on its own — a wrong one costs a full re-extraction.
"""

from pathlib import Path

import pytest

from smartsearch import config, wise_cli

PROJECT = Path("/projects/rehearsals")
MEDIA = Path("/footage")
LISTING = Path("/logs/wise-media.txt")

SIGLIP = wise_cli.Extractor("video", config.OPEN_CLIP_ID, segment_level=False)
CLAP = wise_cli.Extractor("audio", config.CLAP_ID, segment_level=False)
POSE = wise_cli.Extractor("video", "apollon/pose/rtmo-s/body7", segment_level=True)
QWEN = wise_cli.Extractor("video", config.QWEN_ID, segment_level=True)


def test_extraction_of_a_folder_names_the_project_and_the_folder():
    command = wise_cli.extract_command(PROJECT, [MEDIA])
    assert command[0] == "extract-features"
    assert str(MEDIA) in command
    assert command[command.index("--project-dir") + 1] == str(PROJECT)


def test_extraction_never_waits_for_a_prompt():
    # Updating an existing project asks for confirmation and aborts without it.
    assert "--yes" in wise_cli.extract_command(PROJECT, [MEDIA])


def test_omitting_media_folders_adds_an_extractor_to_existing_media():
    command = wise_cli.extract_command(PROJECT, video_ids=[config.QWEN_ID])
    assert command[1] == "--project-dir"
    assert command[command.index("--video-feature-id") + 1] == config.QWEN_ID


def test_each_extractor_is_repeated_under_its_own_option():
    command = wise_cli.extract_command(
        PROJECT, [MEDIA], video_ids=[config.OPEN_CLIP_ID, config.QWEN_ID],
        audio_ids=[config.CLAP_ID],
    )
    assert command.count("--video-feature-id") == 2
    assert command.count("--audio-feature-id") == 1


def test_include_patterns_are_passed_through_one_at_a_time():
    command = wise_cli.extract_command(PROJECT, [MEDIA], include=["*.mp4", "*.mov"])
    assert command.count("--media-include") == 2
    assert "*.mp4" in command and "*.mov" in command


def test_thumbnails_are_switched_off_by_the_negated_option():
    assert "--no-thumbnails" in wise_cli.extract_command(PROJECT, [MEDIA], thumbnails=False)
    assert "--thumbnails" in wise_cli.extract_command(PROJECT, [MEDIA])


def test_indexing_covers_every_extractor_unless_one_is_named():
    assert "--feature-id" not in wise_cli.index_command(PROJECT)
    named = wise_cli.index_command(PROJECT, feature_id=config.QWEN_ID)
    assert named[named.index("--feature-id") + 1] == config.QWEN_ID


def test_indexing_defaults_to_exact_search():
    command = wise_cli.index_command(PROJECT)
    assert command[command.index("--index-type") + 1] == "IndexFlatIP"


def test_serving_passes_the_frontend_assets_as_an_absolute_path():
    # WISE resolves its default asset directory against the working directory.
    command = wise_cli.serve_command(PROJECT)
    assets = Path(command[command.index("--theme-asset-dir") + 1])
    assert assets.is_absolute()
    assert assets == config.frontend_dist()


def test_the_listen_address_reaches_the_server_through_the_environment():
    # `wise serve` has no host or port option.
    environment = wise_cli.server_environment("127.0.0.1", 9671)
    assert environment["LISTEN_ADDRESS"] == "127.0.0.1"
    assert environment["PORT"] == "9671"


def test_the_server_loads_models_from_the_local_cache(monkeypatch):
    # The theatre machine has no internet during rehearsals.
    monkeypatch.delenv("HF_HUB_OFFLINE", raising=False)
    assert wise_cli.server_environment()["HF_HUB_OFFLINE"] == "1"


def test_an_explicit_hub_setting_overrides_offline_mode(monkeypatch):
    monkeypatch.setenv("HF_HUB_OFFLINE", "0")
    assert wise_cli.server_environment()["HF_HUB_OFFLINE"] == "0"


def test_metadata_import_defaults_to_time_ranges_rather_than_whole_files():
    command = wise_cli.import_metadata_command(
        PROJECT, metadata_id="hindsight", csv_path=Path("/tmp/h.csv")
    )
    assert command[:2] == ["media-metadata", "import"]
    assert command[command.index("--metadata-type") + 1] == "segment"


def test_a_log_file_is_named_after_the_subcommand():
    assert wise_cli.log_path(["extract-features"]).name.startswith("wise-extract-features-")


def test_a_file_list_replaces_include_patterns():
    command = wise_cli.extract_command(PROJECT, [MEDIA], files_from=LISTING)
    assert command[command.index("--media-files-from") + 1] == str(LISTING)
    assert "--media-include" not in command


def test_a_file_list_and_include_patterns_are_refused_together():
    # WISE rejects the combination only after it has started.
    with pytest.raises(ValueError):
        wise_cli.extract_command(PROJECT, [MEDIA], include=["*.mp4"], files_from=LISTING)


def test_only_files_directly_in_the_folder_are_listed(tmp_path):
    for name in ("b.mp4", "a.mp4", "notes.txt"):
        (tmp_path / name).touch()
    (tmp_path / "dontuse").mkdir()
    (tmp_path / "dontuse" / "c.mp4").touch()
    assert wise_cli.media_files(tmp_path) == ["a.mp4", "b.mp4", "notes.txt"]
    assert wise_cli.media_files(tmp_path, ["*.mp4"]) == ["a.mp4", "b.mp4"]


def test_the_file_list_holds_one_name_per_line_in_utf8(tmp_path):
    names = ["2026-10-12 16-34-42_Wächter.mp4", "2026-10-13 14-03-56.mp4"]
    text = wise_cli.write_media_list(names, tmp_path / "list.txt").read_text(encoding="utf-8")
    assert text.splitlines() == names
    assert text.endswith("\n")


def test_frame_level_extractors_share_a_pass_and_segment_level_ones_run_alone():
    # WISE refuses frame- and segment-level video extractors in one run.
    assert wise_cli.extraction_passes([POSE, SIGLIP, CLAP, QWEN]) == [[SIGLIP, CLAP], [POSE], [QWEN]]
    assert wise_cli.extraction_passes([POSE]) == [[POSE]]


def test_each_pass_names_only_its_own_extractors():
    frame = wise_cli.pass_command(PROJECT, MEDIA, [SIGLIP, CLAP], LISTING)
    assert frame[frame.index("--video-feature-id") + 1] == SIGLIP.id
    assert frame[frame.index("--audio-feature-id") + 1] == CLAP.id
    pose = wise_cli.pass_command(PROJECT, MEDIA, [POSE], LISTING)
    assert pose.count("--video-feature-id") == 1 and POSE.id in pose
    assert "--audio-feature-id" not in pose
    assert pose[pose.index("--media-files-from") + 1] == str(LISTING)


def test_thumbnails_come_from_the_frame_level_pass_only():
    # They are keyed by media and timestamp; a second pass would duplicate them.
    assert "--thumbnails" in wise_cli.pass_command(PROJECT, MEDIA, [SIGLIP, CLAP], LISTING)
    assert "--no-thumbnails" in wise_cli.pass_command(PROJECT, MEDIA, [POSE], LISTING)


def test_a_pass_rebuilds_the_existing_indices_of_its_extractors():
    commands = wise_cli.pass_index_commands(PROJECT, [SIGLIP, CLAP])
    assert [c[c.index("--feature-id") + 1] for c in commands] == [SIGLIP.id, CLAP.id]
    assert [c[c.index("--modality-type") + 1] for c in commands] == ["video", "audio"]
    assert all("--overwrite" in c for c in commands)


def test_naming_extractors_selects_among_those_the_project_holds():
    assert wise_cli.select_extractors([SIGLIP, CLAP, POSE], video_ids=[POSE.id]) == ([POSE], [])
    assert wise_cli.select_extractors([SIGLIP, CLAP, POSE]) == ([SIGLIP, CLAP, POSE], [])


def test_a_named_extractor_the_project_lacks_is_reported():
    _, missing = wise_cli.select_extractors([SIGLIP], video_ids=[config.QWEN_ID])
    assert missing == [f"video {config.QWEN_ID}"]


def test_an_empty_project_folder_is_created_rather_than_extended(tmp_path):
    assert not wise_cli.project_exists(tmp_path / "missing")
    assert not wise_cli.project_exists(tmp_path)
    (tmp_path / "metadata").mkdir()
    assert wise_cli.project_exists(tmp_path)


def _existing_project(tmp_path, monkeypatch, outcome):
    """An existing project and footage folder, with WISE replaced by `outcome`."""
    media = tmp_path / "footage"
    media.mkdir()
    (media / "a.mp4").touch()
    project = tmp_path / "project"
    (project / "metadata").mkdir(parents=True)
    monkeypatch.setattr(config, "LOGS_ROOT", tmp_path / "logs")
    monkeypatch.setattr(wise_cli, "project_extractors", lambda _: [POSE, SIGLIP, CLAP])
    calls = []

    def run(command, **_):
        calls.append(command)
        return outcome(command)

    monkeypatch.setattr(wise_cli, "run", run)
    return project, media, calls


def test_each_pass_is_indexed_before_the_next_begins(tmp_path, monkeypatch):
    project, media, calls = _existing_project(tmp_path, monkeypatch, lambda _: 0)
    assert wise_cli.extract_folder(project, media) == 0
    assert [(c[0], c[c.index("--feature-id") + 1] if "--feature-id" in c else None)
            for c in calls] == [
        ("extract-features", None),
        ("create-index", SIGLIP.id),
        ("create-index", CLAP.id),
        ("extract-features", None),
        ("create-index", POSE.id),
    ]


def test_a_failed_pass_stops_the_run_before_its_indices(tmp_path, monkeypatch):
    project, media, calls = _existing_project(
        tmp_path, monkeypatch,
        lambda command: int(command[0] == "extract-features" and POSE.id in command),
    )
    assert wise_cli.extract_folder(project, media) == 1
    assert [c[0] for c in calls] == ["extract-features", "create-index", "create-index",
                                     "extract-features"]
