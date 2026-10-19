"""Batch operations on a WISE project: extraction, indexing, serving.

Covers the offline half of Smart Search in knowledge/components/02_processing.md
("Process rehearsal footage from folder on computer", "Feature embedding that
WISE offers out of the box") — the PROCESSING mode of
knowledge/source_of_truth/pipeline.md that fills the search index.

Each operation is a command builder plus a thin runner, so the argument lists
can be checked without launching a subprocess. Output is written to the terminal
and to a log file simultaneously: a run over a rehearsal season lasts hours and
has previously failed while exiting 0 (changelog.md, 2026-09-08).

New recordings are added to an existing project with WISE patch 0007
(knowledge/source_of_truth/versions.md): files the project holds are skipped,
the extractors are named per run, and each finished file is saved as it
completes, so an interrupted run continues where it stopped.
"""

import fnmatch
import json
import os
import shlex
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from . import config

# Lists a project's extractors from inside WISE's environment.
EXTRACTORS_SCRIPT = config.REPO_ROOT / "src" / "scripts" / "wise_extractors.py"


@dataclass(frozen=True)
class Extractor:
    """A feature extractor a project holds features from, for one modality."""

    modality: str  # "video", "audio" or "image"
    id: str
    segment_level: bool

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
    files_from: Path | None = None,
    num_workers: int = 0,
    thumbnails: bool = True,
    autocast: bool = False,
    shard_maxcount: int | None = None,
) -> list[str]:
    """Build an `extract-features` command line.

    WISE infers its mode from the arguments: media directories with a fresh
    project create it, media directories with an existing project add media,
    and no media directories at all re-embed the existing media with a newly
    named extractor (knowledge/background/wise_learnings.md, section 5). When
    adding media, the named extractors select among those the project holds.

    Naming any extractor suppresses the defaults for the other modalities, so
    callers that want audio alongside a non-default visual model must name both.

    `files_from` names a file listing media paths relative to the single media
    directory; WISE accepts it only without include patterns.
    """
    if files_from is not None and include:
        raise ValueError("WISE takes either include patterns or a file list, not both")
    command = ["extract-features", *[str(path) for path in media_dirs]]
    command += ["--project-dir", str(project)]
    command += _repeated("--media-include", include)
    if files_from is not None:
        command += ["--media-files-from", str(files_from)]
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


def project_exists(project: Path) -> bool:
    """Whether WISE treats the project as existing, and so adds media to it."""
    return project.is_dir() and any(project.iterdir())


def media_files(folder: Path, include=()) -> list[str]:
    """Names of the files directly inside `folder` that match any include glob.

    Subfolders are not searched: OBS records into one flat folder, and
    recordings set aside are moved into a subfolder of it.
    """
    patterns = list(include) or ["*"]
    return sorted(
        path.name for path in folder.iterdir()
        if path.is_file() and any(fnmatch.fnmatch(path.name, pattern) for pattern in patterns)
    )


def write_media_list(names, destination: Path) -> Path:
    """Write file names one per line, as UTF-8, for `--media-files-from`."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text("".join(f"{name}\n" for name in names), encoding="utf-8")
    return destination


def select_extractors(extractors, *, video_ids=(), audio_ids=(), image_ids=()):
    """The project's extractors among those named, and the named ones it lacks.

    Naming none selects every extractor the project holds.
    """
    named = ({("video", id_) for id_ in video_ids} | {("audio", id_) for id_ in audio_ids}
             | {("image", id_) for id_ in image_ids})
    if not named:
        return list(extractors), []
    held = {(extractor.modality, extractor.id) for extractor in extractors}
    selected = [extractor for extractor in extractors
                if (extractor.modality, extractor.id) in named]
    missing = sorted(f"{modality} {id_}" for modality, id_ in named - held)
    return selected, missing


def extraction_passes(extractors) -> list[list[Extractor]]:
    """Group extractors into the WISE runs that add media to a project.

    WISE cannot combine frame-level and segment-level video extractors in one
    run, and a segment-level run takes its segment length from its first
    extractor. Frame-level video, audio and image extractors therefore share
    the first pass, which decodes each file once, and every segment-level
    extractor runs on its own.
    """
    frame = [extractor for extractor in extractors if not extractor.segment_level]
    segment = [[extractor] for extractor in extractors if extractor.segment_level]
    return ([frame] if frame else []) + segment


def pass_command(
    project: Path,
    media_dir: Path,
    extractors,
    files_from: Path,
    *,
    thumbnails: bool = True,
    num_workers: int = 0,
    autocast: bool = False,
) -> list[str]:
    """The `extract-features` command for one pass over a list of recordings.

    Thumbnails come from the frame-level pass only. They are keyed by media and
    timestamp, not by extractor, so a second pass would store a duplicate set.
    """
    ids = {modality: [extractor.id for extractor in extractors if extractor.modality == modality]
           for modality in ("video", "audio", "image")}
    segment_level = any(extractor.segment_level for extractor in extractors)
    return extract_command(
        project, [media_dir],
        video_ids=ids["video"], audio_ids=ids["audio"], image_ids=ids["image"],
        files_from=files_from, num_workers=num_workers,
        thumbnails=thumbnails and not segment_level, autocast=autocast,
    )


def pass_index_commands(project: Path, extractors) -> list[list[str]]:
    """Rebuild the index of each extractor in a pass over all of its features.

    Overwriting is required: WISE otherwise keeps an existing index as it is,
    without the vectors just added.
    """
    return [
        index_command(project, modalities=[extractor.modality],
                      feature_id=extractor.id, overwrite=True)
        for extractor in extractors
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
    """Environment for `wise serve`, which takes its address only from there.

    The server only constructs extractors the project already holds features
    for, so their weights and tokenizers are in the Hugging Face cache from
    extraction. Hub offline mode loads them from there without network: online,
    every file is first checked against the Hub, and the tokenizer load in
    transformers 4.57 raises outright when huggingface.co cannot be resolved.
    An HF_HUB_OFFLINE already set in the environment takes precedence.
    """
    return {"HF_HUB_OFFLINE": "1", **os.environ, "LISTEN_ADDRESS": host, "PORT": str(port)}


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
    except KeyboardInterrupt:
        # The console delivers Ctrl+C to WISE as well. Waiting lets it discard
        # the file in progress before the prompt returns.
        process.wait()
        raise
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


def project_extractors(project: Path) -> list[Extractor]:
    """The extractors a project holds, read through WISE's environment.

    Apollon's environment has neither WISE's store reader nor its model
    registry, which records whether an extractor embeds frames or segments.
    """
    result = subprocess.run(
        [str(config.python()), str(EXTRACTORS_SCRIPT), str(project)],
        stdout=subprocess.PIPE, text=True, check=True,
    )
    return [Extractor(**entry) for entry in json.loads(result.stdout)]


def extract_folder(
    project: Path,
    media_dir: Path,
    *,
    include=(),
    video_ids=(),
    audio_ids=(),
    image_ids=(),
    num_workers: int = 0,
    thumbnails: bool = True,
    autocast: bool = False,
) -> int:
    """Embed the recordings in a folder, then rebuild the indices over them.

    A new project is created from every file directly in the folder. An
    existing project receives the files it lacks, one pass per group of
    extractors (`extraction_passes`), each pass followed by its indices, so an
    interrupted run leaves the completed passes searchable. Running the same
    command again continues where it stopped.
    """
    # WISE stores the folder as given, and resolves registered files against it.
    media_dir = media_dir.resolve()
    names = media_files(media_dir, include)
    if not names:
        print(f"No files in {media_dir}", file=sys.stderr)
        return 1
    listing = write_media_list(names, log_path(["media"]).with_suffix(".txt"))
    print(f"{len(names)} files from {media_dir} listed in {listing}", flush=True)
    options = {"num_workers": num_workers, "autocast": autocast}

    if not project_exists(project):
        code = extract(project, [media_dir], video_ids=video_ids, audio_ids=audio_ids,
                       image_ids=image_ids, files_from=listing, thumbnails=thumbnails,
                       **options)
        return code or create_index(project)

    extractors, missing = select_extractors(
        project_extractors(project),
        video_ids=video_ids, audio_ids=audio_ids, image_ids=image_ids,
    )
    if missing:
        print(f"{project.name} holds no features from: {', '.join(missing)}. "
              f"Add an extractor with add-extractor.", file=sys.stderr)
        return 1
    if not extractors:
        print(f"{project} holds no features. Remove it to create it anew.", file=sys.stderr)
        return 1

    passes = extraction_passes(extractors)
    for number, extractors_of_pass in enumerate(passes, 1):
        print(f"pass {number} of {len(passes)}: "
              f"{', '.join(extractor.id for extractor in extractors_of_pass)}", flush=True)
        code = run(pass_command(project, media_dir, extractors_of_pass, listing,
                                thumbnails=thumbnails, **options))
        for command in pass_index_commands(project, extractors_of_pass):
            if code:
                break
            code = run(command)
        if code:
            return code
    return 0


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
