"""Cutting search results into clips for playback.

The HITS -> CUT step of the RENDER graph in knowledge/source_of_truth/pipeline.md:
a hit is a time range inside a recording that may be several hours long, and
TouchDesigner plays a short file far more reliably than it seeks inside a long
one (knowledge/components/03_render.md, "Pixels: cut clips on disk").

Two modes, sharing file naming and delivery:

- fast copies the compressed stream without decoding it, at about 0.1s per
  clip regardless of resolution. The clip file begins at the keyframe before the
  hit. The frames ahead of the hit are marked with negative timestamps and
  hidden by an MP4 edit list, which ffmpeg-based players honour and
  TouchDesigner does not, so every clip reports this pre-roll for the player to
  skip. The picture is the recording's own codec and resolution.
- precise decodes and re-encodes to H.264, so the clip begins with its own
  keyframe on the exact frame in any player. Measured at about 1s per 8 seconds
  of 1080p and 3.5s per 8 seconds of 4K on the development laptop.

The source is read from disk, at the path the WISE project registered for the
recording in its metadata database, so nothing about where recordings live
needs configuring. Reading through WISE's media route instead costs one HTTP
request per seek, and ffmpeg seeks between the audio and video samples of an
interleaved recording hundreds of times per clip: 3.4 s against 0.15 s for a
four-second clip of a 1080p OBS recording, 28.5 s against 0.3 s for an
84-second one. The media route remains the fallback when the project database
or the recording is not on this machine.
"""

import os
import sqlite3
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator

from . import config
from .client import Hit

FAST = "fast"
PRECISE = "precise"
MODES = (FAST, PRECISE)

# H.264 encoders for precise mode. libx264 runs on the CPU and is the default:
# during a performance the GPU is occupied by live pose encoding and Whisper.
# NVENC is about 1.4x faster where the GPU is free.
LIBX264 = "libx264"
NVENC = "h264_nvenc"
ENCODERS = (LIBX264, NVENC)

_ENCODER_OPTIONS = {
    LIBX264: ["-c:v", LIBX264, "-preset", "veryfast", "-crf", "20"],
    NVENC: ["-c:v", NVENC, "-cq", "20"],
}


@dataclass(frozen=True)
class Clip:
    """A clip on disk, and how far into the file the hit begins.

    `preroll` is in seconds and is zero for precise clips.
    """

    path: Path
    preroll: float


def source_url(hit: Hit) -> str:
    """WISE's media route for a hit's recording, without the media fragment.

    WISE appends `#t=start,end` for browsers; ffmpeg would send it as part of
    the request.
    """
    return hit.media_url.split("#", 1)[0]


def recording_paths(project: Path) -> dict[str, Path]:
    """Every recording a WISE project indexes, by media id.

    WISE stores each recording's path relative to the folder it was added from,
    and that folder as a source collection. Empty when the project's database
    is not on this machine.
    """
    database_path = project / "metadata" / "internal.db"
    if not database_path.exists():
        return {}
    database = sqlite3.connect(f"file:{database_path.as_posix()}?mode=ro", uri=True)
    try:
        rows = database.execute(
            "SELECT media.id, source_collections.location, media.path FROM media "
            "JOIN source_collections ON media.source_collection_id = source_collections.id")
        return {str(media_id): Path(location) / path for media_id, location, path in rows}
    finally:
        database.close()


def source(hit: Hit, recordings: dict[str, Path]) -> str:
    """What ffmpeg reads a hit's recording from: the file on disk if present,
    otherwise WISE's media route."""
    path = recordings.get(hit.media_id)
    if path is not None and path.is_file():
        return str(path)
    return source_url(hit)


def clip_name(hit: Hit, mode: str) -> str:
    """File name of a hit's clip.

    Derived from the recording and the time range, so the same moment found by
    a later search maps to the clip already on disk. The media id keeps
    recordings with the same file name apart.
    """
    stem = Path(hit.filename).stem
    return f"{hit.media_id}-{stem}-{round(hit.ts * 1000)}-{round(hit.te * 1000)}-{mode}.mp4"


def cut_command(source: str, start: float, duration: float, destination: Path,
                mode: str, encoder: str = LIBX264) -> list[str]:
    """Build the ffmpeg arguments that cut one clip, without the executable.

    Seeking is placed before the input in both modes: ffmpeg jumps to the
    keyframe before `start` rather than decoding from the beginning of the
    recording. In precise mode it then decodes up to `start` and discards
    those frames; in fast mode it keeps them as edit-listed pre-roll.
    """
    command = ["-hide_banner", "-v", "error", "-y"]
    command += ["-ss", f"{start:.3f}", "-i", source, "-t", f"{duration:.3f}"]
    if mode == FAST:
        command += ["-c", "copy"]
    else:
        # yuv420p is the only pixel format every H.264 decoder accepts; a
        # 10-bit or 4:2:2 recording would otherwise carry its format through.
        command += [*_ENCODER_OPTIONS[encoder], "-pix_fmt", "yuv420p", "-c:a", "aac"]
    # The container index goes at the front, so playback can begin before the
    # whole file is read.
    command += ["-movflags", "+faststart", "-f", "mp4", str(destination)]
    return command


def preroll_command(clip: Path) -> list[str]:
    """Build the ffprobe arguments that read a clip's first video timestamp.

    Only the first packet is read. In a stream-copied clip it is the keyframe
    before the hit, carrying a negative timestamp equal to the pre-roll.
    """
    return ["-v", "error", "-select_streams", "v:0", "-show_entries", "packet=pts_time",
            "-read_intervals", "%+#1", "-of", "csv=p=0", str(clip)]


def parse_preroll(output: str) -> float:
    return max(0.0, -float(output.strip().split(",")[0]))


def preroll(clip: Path) -> float:
    """Seconds of footage ahead of the hit at the start of a clip file."""
    result = subprocess.run([str(config.ffprobe()), *preroll_command(clip)],
                            capture_output=True, text=True, check=True)
    return parse_preroll(result.stdout)


def cut(hit: Hit, mode: str, directory: Path, encoder: str = LIBX264,
        recordings: dict[str, Path] | None = None) -> Clip:
    """Cut one hit into a clip in `directory`, reusing a clip already there.

    `recordings` maps media ids to files on disk (`recording_paths`); a hit
    whose recording is missing from it is read through WISE's media route.

    ffmpeg writes to a temporary name that is renamed once the clip is
    complete, so a clip interrupted mid-write is never mistaken for a finished
    one by a later search or by a player watching the folder.
    """
    destination = directory / clip_name(hit, mode)
    if not destination.exists():
        directory.mkdir(parents=True, exist_ok=True)
        partial = destination.with_name(destination.name + ".part")
        command = cut_command(source(hit, recordings or {}), hit.ts, hit.seconds,
                              partial, mode, encoder)
        subprocess.run([str(config.ffmpeg()), *command], check=True)
        os.replace(partial, destination)
    return Clip(destination, preroll(destination))


def cut_all(hits: Iterable[Hit], mode: str, directory: Path,
            encoder: str = LIBX264,
            recordings: dict[str, Path] | None = None) -> Iterator[tuple[int, Hit, Clip]]:
    """Cut hits in rank order, yielding each clip as soon as it is written.

    Yielding per clip rather than returning the batch lets the best result be
    announced while the rest are still being cut.
    """
    for rank, hit in enumerate(hits, start=1):
        yield rank, hit, cut(hit, mode, directory, encoder, recordings)
