"""Locations and defaults for the WISE installation Orest drives.

WISE is never imported. It runs in its own conda environment, pinned against
numpy<2 by its audio feature extractor (knowledge/source_of_truth/versions.md),
while Orest's own code runs under uv on Python 3.12+. The two processes meet at
WISE's command line and at its HTTP API, so everything here addresses WISE by
filesystem path and by URL.

Every location can be overridden by environment variable. The machine that runs
this in the Probebuehne is not the machine it was written on, and its conda
prefix, media locations and port are all expected to differ
(claude_concerns.md, "Which GPU will actually run this?").
"""

import os
import shutil
import sys
from pathlib import Path

# Repository root, two levels above this file (src/smartsearch/config.py).
REPO_ROOT = Path(__file__).resolve().parents[2]

# Name of the conda environment holding the WISE installation.
ENV_NAME = os.environ.get("OREST_WISE_ENV", "wise")

# Clone of ox-vgg/wise. Needed for the built frontend assets, which `wise serve`
# reads from disk rather than from the installed package.
WISE_REPO = Path(os.environ.get("OREST_WISE_REPO", REPO_ROOT / "external" / "wise"))

# WISE projects live under data/ rather than inside the clone. Everything below
# external/ is lost when external/wise is re-cloned to reapply the Windows
# patches (knowledge/source_of_truth/versions.md), and an index over a full
# rehearsal season is expensive to rebuild.
PROJECTS_ROOT = Path(os.environ.get("OREST_WISE_PROJECTS", REPO_ROOT / "data" / "wise-projects"))

# Captured output of each batch command, one file per run.
LOGS_ROOT = Path(os.environ.get("OREST_WISE_LOGS", REPO_ROOT / "data" / "logs"))

# Rehearsal footage to index. Test recordings until the Probebuehne naming
# convention is settled (knowledge/components/01_capture.md, "Saving").
MEDIA_DIR = Path(os.environ.get("OREST_MEDIA_DIR", REPO_ROOT.parent / "test_data_orest"))

DEFAULT_PROJECT = os.environ.get("OREST_WISE_PROJECT", "test_data_orest")

# WISE binds 0.0.0.0 by default. Orest binds the loopback interface instead: the
# corpus is unreleased footage of identifiable people, and the consent questions
# in knowledge/components/01_capture.md are open. Override to serve a UI machine
# elsewhere on the theatre network.
HOST = os.environ.get("OREST_WISE_HOST", "127.0.0.1")
PORT = int(os.environ.get("OREST_WISE_PORT", "9670"))

# Clips cut from search results, one folder per project. Under data/, which git
# ignores: clips are footage of identifiable people, like the corpus itself.
CLIPS_ROOT = Path(os.environ.get("OREST_CLIPS_DIR", REPO_ROOT / "data" / "clips"))

# Where TouchDesigner is reached, and where Orest is reached from it. Defined
# in the `osc` package and re-exported here, because the live SITREP addresses
# the same OSC In DAT and two definitions of one receiver would drift apart.
from osc import CONTROL_HOST, CONTROL_PORT, TD_HOST, TD_PORT  # noqa: E402,F401

# Defaults WISE applies when no feature extractor is named.
OPEN_CLIP_ID = "mlfoundations/open_clip/ViT-B-16-SigLIP2-512/webli"
CLAP_ID = "microsoft/clap/2023/four-datasets"

# Segment-level visual extractor: one vector per 8s segment rather than one per
# frame. The 2B build is the largest that fits alongside its activations on an
# 8GB card (claude_concerns.md, "Which GPU will actually run this?").
QWEN_ID = "hf/Qwen/Qwen3-VL-Embedding/2B"

_SCRIPT = "Scripts/wise.exe" if sys.platform == "win32" else "bin/wise"

# ffmpeg as conda installs it into an environment: WISE's decoding stack brings
# one along.
_FFMPEG = "Library/bin/ffmpeg.exe" if sys.platform == "win32" else "bin/ffmpeg"


def _conda_roots() -> list[Path]:
    """Standard conda installation prefixes, most likely first."""
    roots = [Path.home() / name for name in ("miniconda3", "anaconda3", "miniforge3")]
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        roots.append(Path(local_app_data) / "miniconda3")
    roots.append(Path("/opt/miniconda3"))
    return roots


def executable() -> Path:
    """Locate the `wise` console script inside its conda environment.

    The console script is used rather than `python -m wise`: the latter puts the
    working directory on sys.path, where external/wise/triton/ shadows the real
    triton package and breaks model construction (changelog.md, 2026-09-08).

    Invoking the script directly, without activating the environment, is enough
    on this machine — torch resolves its CUDA libraries from the environment's
    own site-packages.
    """
    override = os.environ.get("OREST_WISE_EXE")
    if override:
        return Path(override)

    on_path = shutil.which("wise")
    if on_path:
        return Path(on_path)

    for root in _conda_roots():
        candidate = root / "envs" / ENV_NAME / _SCRIPT
        if candidate.exists():
            return candidate

    raise RuntimeError(
        f"No 'wise' executable found for conda environment {ENV_NAME!r}. "
        f"Install WISE per external/wise/docs/Install.md, or set OREST_WISE_EXE "
        f"to the full path of the console script."
    )


def ffmpeg() -> Path:
    """Locate an ffmpeg executable for cutting clips.

    Found by override, then on PATH, then in the WISE conda environment, which
    carries a GPL build with libx264 and NVENC.
    """
    override = os.environ.get("OREST_FFMPEG_EXE")
    if override:
        return Path(override)

    on_path = shutil.which("ffmpeg")
    if on_path:
        return Path(on_path)

    for root in _conda_roots():
        candidate = root / "envs" / ENV_NAME / _FFMPEG
        if candidate.exists():
            return candidate

    raise RuntimeError(
        f"No ffmpeg found on PATH or in conda environment {ENV_NAME!r}. "
        f"Set OREST_FFMPEG_EXE to the full path of an ffmpeg executable."
    )


def ffprobe() -> Path:
    """The ffprobe executable installed alongside ffmpeg."""
    executable = ffmpeg()
    return executable.with_name(executable.name.replace("ffmpeg", "ffprobe"))


def project_dir(name: str | None = None) -> Path:
    """Directory of a WISE project, which also names it in every URL path."""
    return PROJECTS_ROOT / (name or DEFAULT_PROJECT)


def clips_dir(name: str | None = None) -> Path:
    """Folder holding the clips cut from a project's search results."""
    return CLIPS_ROOT / (name or DEFAULT_PROJECT)


def frontend_dist() -> Path:
    """Built frontend assets, which `wise serve` requires on disk.

    Built once per clone with `npm install && npm run build` in
    external/wise/frontend/ (knowledge/source_of_truth/versions.md).
    """
    return WISE_REPO / "frontend" / "dist"


def base_url() -> str:
    """Root URL of the WISE server, without a project path segment."""
    return os.environ.get("OREST_WISE_URL", f"http://{HOST}:{PORT}").rstrip("/")
