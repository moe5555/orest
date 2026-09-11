"""Batch operations on a WISE project: extraction, indexing, serving.

Covers the offline half of Smart Search in knowledge/components/02_processing.md
("Process rehearsal footage from folder on computer", "Feature embedding that
WISE offers out of the box") — the PROCESSING mode of
knowledge/source_of_truth/pipeline.md that fills the search index.

Each operation is a command builder plus a thin runner, so the argument lists
can be checked without launching a subprocess. Output is written to the terminal
and to a log file simultaneously: a run over a rehearsal season lasts hours and
has previously failed while exiting 0 (changelog.md, 2026-09-08).
"""

import os
import shlex
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from . import config

# Read size for forwarding subprocess output. One read returns whatever has
# arrived rather than waiting for a full buffer, so progress bars that redraw
# with a carriage return stay live on the terminal.
_CHUNK = 4096


def _repeated(option: str, values) -> list[str]:
    """Expand an option that WISE accepts once per value."""
    return [argument for value in values for argument in (option, str(value))]


def extract_command(
    project: Path,
    media_dirs=(),
    *,
    video_ids=(),
    audio_ids=(),
    image_ids=(),
    include=(),
    num_workers: int = 0,
    thumbnails: bool = True,
    autocast: bool = False,
    shard_maxcount: int | None = None,
) -> list[str]:
    """Build an `extract-features` command line.

    WISE infers its mode from the arguments: media directories with a fresh
    project create it, media directories with an existing project add media
    under the extractors already registered, and no media directories at all
    re-embed the existing media with a newly named extractor
    (knowledge/background/wise_learnings.md, section 5).

    Naming any extractor suppresses the defaults for the other modalities, so
    callers that want audio alongside a non-default visual model must name both.
    """
    command = ["extract-features", *[str(path) for path in media_dirs]]
    command += ["--project-dir", str(project)]
    command += _repeated("--media-include", include)
    command += _repeated("--video-feature-id", video_ids)
    command += _repeated("--audio-feature-id", audio_ids)
    command += _repeated("--image-feature-id", image_ids)
    command += ["--num-workers", str(num_workers)]
    command += ["--thumbnails" if thumbnails else "--no-thumbnails"]
    if autocast:
        command += ["--enable-autocast"]
    if shard_maxcount is not None:
        command += ["--shard-maxcount", str(shard_maxcount)]
    # Updating an existing project is an interactive prompt that aborts on any
    # answer but "y", which would hang an unattended batch run.
    command += ["--yes"]
    return command


def index_command(
    project: Path,
    *,
    index_type: str = "IndexFlatIP",
    modalities=(),
    feature_id: str | None = None,
    overwrite: bool = False,
    fts_config: Path | None = None,
) -> list[str]:
    """Build a `create-index` command line.

    Modalities and extractors are discovered from the project's store directory,
    so an index covering everything extracted so far needs no arguments beyond
    the project.
    """
    command = ["create-index", "--project-dir", str(project)]
    command += ["--index-type", index_type]
    command += _repeated("--modality-type", modalities)
    if feature_id:
        command += ["--feature-id", feature_id]
    if overwrite:
        command += ["--overwrite"]
    if fts_config is not None:
        command += ["--fts-config", str(fts_config)]
    return command


def import_metadata_command(
    project: Path,
    *,
    metadata_id: str,
    csv_path: Path,
    metadata_type: str = "segment",
) -> list[str]:
    """Build a `media-metadata import` command line.

    Segment metadata carries a media id and a time range, which is the shape
    Hindsight-SITREP judgements and transcripts need to join onto footage
    (external/wise/docs/Metadata.md).
    """
    return [
        "media-metadata", "import",
        "--metadata-id", metadata_id,
        "--from-csv", str(csv_path),
        "--metadata-type", metadata_type,
        "--project-dir", str(project),
    ]


def serve_command(project: Path, *, index_type: str | None = None) -> list[str]:
    """Build a `serve` command line.

    The frontend asset directory is passed as an absolute path because WISE
    resolves its default relative to the working directory.
    """
    command = ["serve", "--project-dir", str(project)]
    command += ["--theme-asset-dir", str(config.frontend_dist())]
    if index_type:
        command += ["--index-type", index_type]
    return command


def server_environment(host: str = config.HOST, port: int = config.PORT) -> dict[str, str]:
    """Environment for `wise serve`, which takes its address only from there."""
    return {**os.environ, "LISTEN_ADDRESS": host, "PORT": str(port)}


def log_path(command: list[str]) -> Path:
    """Timestamped log file named after the WISE subcommand being run."""
    config.LOGS_ROOT.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    return config.LOGS_ROOT / f"wise-{command[0]}-{stamp}.log"


def run(command: list[str], *, env: dict[str, str] | None = None, log: bool = True) -> int:
    """Run a WISE subcommand, forwarding its output to the terminal and a log.

    Returns the exit code rather than raising, so a caller running several
    operations in sequence decides what a failure means.
    """
    executable = config.executable()
    argv = [str(executable), *command]
    destination = log_path(command) if log else None

    print(f"$ {shlex.join(argv)}", flush=True)
    if destination:
        print(f"  logging to {destination}", flush=True)

    # WISE writes progress bars to stderr; merging the streams keeps the log in
    # the order the run actually happened.
    process = subprocess.Popen(
        argv,
        cwd=config.REPO_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=0,
    )

    handle = destination.open("wb") if destination else None
    try:
        while True:
            chunk = process.stdout.read(_CHUNK)
            if not chunk:
                break
            sys.stdout.buffer.write(chunk)
            sys.stdout.buffer.flush()
            if handle:
                # Flushed per chunk so the log survives a run that is
                # interrupted, which is the case it exists for.
                handle.write(chunk)
                handle.flush()
    finally:
        if handle:
            handle.close()
        process.stdout.close()

    return process.wait()


def extract(project: Path, media_dirs=(), **kwargs) -> int:
    # WISE creates the project directory itself but requires its parent to
    # exist, and extraction is the only operation that creates a project.
    project.parent.mkdir(parents=True, exist_ok=True)
    return run(extract_command(project, media_dirs, **kwargs))


def create_index(project: Path, **kwargs) -> int:
    return run(index_command(project, **kwargs))


def import_metadata(project: Path, **kwargs) -> int:
    return run(import_metadata_command(project, **kwargs))


def serve(project: Path, *, host: str = config.HOST, port: int = config.PORT,
          index_type: str | None = None) -> int:
    """Run the WISE server in the foreground until interrupted."""
    return run(
        serve_command(project, index_type=index_type),
        env=server_environment(host, port),
        log=False,
    )
