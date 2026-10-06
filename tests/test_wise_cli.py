"""The command lines Apollon builds for WISE.

WISE infers what it will do from the shape of its arguments, and several of its
options behave differently from what their names suggest, so the argument list
is worth checking on its own — a wrong one costs a full re-extraction.
"""

from pathlib import Path

from smartsearch import config, wise_cli

PROJECT = Path("/projects/rehearsals")
MEDIA = Path("/footage")


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


def test_metadata_import_defaults_to_time_ranges_rather_than_whole_files():
    command = wise_cli.import_metadata_command(
        PROJECT, metadata_id="hindsight", csv_path=Path("/tmp/h.csv")
    )
    assert command[:2] == ["media-metadata", "import"]
    assert command[command.index("--metadata-type") + 1] == "segment"


def test_a_log_file_is_named_after_the_subcommand():
    assert wise_cli.log_path(["extract-features"]).name.startswith("wise-extract-features-")
