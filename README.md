# orest

"Orest" is the surveillance system that will be used in the production of Human in the Loop/Human on a Leash at Schauspiel Stuttgart December 2026.

## Setup 

### Python Environment (orest)

Orest's own Python code (under `src/`) is managed with
[uv](https://docs.astral.sh/uv/), tracked via `pyproject.toml`/`uv.lock` in
the repo root. The virtual environment itself lives at `orest/` and is
gitignored (uv writes its own `.gitignore` inside the venv folder).

**Set up from a fresh clone** (already done on this machine):

    uv venv orest          # create the virtual environment
    uv init --bare --no-workspace --name orest   # create pyproject.toml (skip if already present)
    setx UV_PROJECT_ENVIRONMENT "orest"          # Windows: point uv at ./orest instead of the default ./.venv
    # bash/zsh equivalent: add `export UV_PROJECT_ENVIRONMENT=orest` to your shell profile

`--no-workspace` matters here: `external/wise` has its own `pyproject.toml`,
and without this flag `uv init` would try to fold it into the same
workspace. `UV_PROJECT_ENVIRONMENT` must be set (not just an activated venv)
or `uv add`/`uv sync` will silently create a second, separate `.venv/`
instead of using `orest/`.

**Activate it:**

    # PowerShell
    .\orest\Scripts\Activate.ps1

    # cmd.exe
    orest\Scripts\activate.bat

    # bash
    source orest/Scripts/activate

**Deactivate it:**

    deactivate

**Install/manage packages** — use `uv`, not plain `pip`, so dependencies
stay tracked:

    uv add <package>            # install a package and record it in pyproject.toml
    uv add <package>==<version> # pin a version
    uv remove <package>         # uninstall and untrack a package
    uv sync                     # reinstall exactly what pyproject.toml/uv.lock specify

`uv add`/`uv remove` update `pyproject.toml` and `uv.lock` automatically —
commit both so the environment is reproducible on other machines.

This is separate from `external/wise`'s own conda environment (`wise`)
below, which is unaffected by this and still follows WISE's own install
docs.

### Running the live SITREP

`src/sitrep/` is installed into the `orest` environment as the `sitrep`
package, so `uv sync` puts the entry point on the path:

    uv run orest-sitrep
    uv run orest-sitrep --window 30 --interval 10 --audio-api WASAPI
    uv run orest-sitrep --json     # raw report JSON instead of the console block

Ollama must be running with the model given by `--model` (default
`gemma4:e4b`) pulled. The live SITREP records nothing: reports are streamed to
the console and not retained, and no frame or audio clip is written to disk.

Each module also runs on its own, for diagnostics:

    uv run python -m sitrep.devices --list
    uv run python -m sitrep.devices --check --video "FHD WebCam"
    uv run python -m sitrep.capture --interval 5 --window 30
    uv run python -m sitrep.benchmark --speech <speech.wav>

The console block is drawn with box-drawing characters, so redirecting it to
a file needs UTF-8:

    PYTHONIOENCODING=utf-8 uv run orest-sitrep > session.txt

### Running smart search

`src/smartsearch/` drives WISE from the `orest` environment: batch work through
WISE's command line, retrieval through its HTTP API. WISE itself stays in its
own conda environment (below) and is never imported.

Build an index over a folder of rehearsal footage:

    uv run orest-search extract --project rehearsals --media <folder>
    uv run orest-search index --project rehearsals

Then serve it and search. `serve` runs in the foreground, so use a second
terminal for the queries:

    uv run orest-search serve --project rehearsals
    uv run orest-search info --project rehearsals
    uv run orest-search query "zwei Personen streiten" --project rehearsals
    uv run orest-search query "applause" --project rehearsals --target av

`--target video` searches the picture, `--target av` the sound. `-n` is the
number of moments wanted, not the number of vectors retrieved. Add a second
model to an existing project without re-scanning the footage:

    uv run orest-search add-extractor --project rehearsals --video-id <id>
    uv run orest-search index --project rehearsals

Projects are written to `data/wise-projects/<name>/` and each batch run is
logged to `data/logs/`. Both are outside `external/`, which is deleted whenever
WISE is re-cloned. A project stores paths to the footage rather than copies, so
moving or renaming source files breaks playback.

Locations are overridable for another machine: `OREST_WISE_EXE`,
`OREST_WISE_ENV`, `OREST_WISE_REPO`, `OREST_WISE_PROJECTS`, `OREST_MEDIA_DIR`,
`OREST_WISE_HOST`, `OREST_WISE_PORT`.

### Searching by body

A second index describes what bodies do rather than what a scene looks like, so
a movement can be the query. Build it over a project that already has media:

    uv run orest-search add-extractor --project rehearsals --video-id orest/pose/rtmo-s/body7
    uv run orest-search index --project rehearsals

Then search with a few seconds of movement taken from any video file:

    uv run orest-search body <clip.mp4> --at 90 --project rehearsals

`--at` is where the movement starts in that file. The query covers four seconds,
matching the indexed segment length.

The encoder lives in `wise_ext/` as the `orest_pose` package and is installed
into **both** environments, because indexing runs inside WISE and the query is
encoded here. It must be the same code on both sides or a query lands in a
different space from the index and retrieves nothing useful.

### Sending results to TouchDesigner

`query` and `body` cut each result into a clip and can announce it over OSC.
In TouchDesigner, an **OSC In DAT** on port 10000 receives:

    /orest/results/begin  <query_id> <count>
    /orest/results/hit    <query_id> <rank> <clip_path> <ts> <te> <score> <source_file> <preroll>
    /orest/results/end    <query_id>

    uv run orest-search query "zwei Personen streiten" --send-td
    uv run orest-search query "zwei Personen streiten" --cut precise --send-td
    uv run orest-search body <clip.mp4> --at 90 --send-td
    uv run orest-search query "zwei Personen streiten" --cut fast

`--cut fast` (the default with `--send-td`) copies the stream: about 0.1s per
clip, in the recording's own codec. A fast clip file begins at the keyframe
before the hit; `preroll` is the seconds to skip, which TouchDesigner must trim
since it ignores the MP4 edit list that hides them from other players. `--cut precise` re-encodes to H.264: about
1s per 8 seconds of 1080p and 3.5s per 8 seconds of 4K; `--encoder h264_nvenc`
is faster where the GPU is free. Clips cover exactly the range WISE returned,
are written to `data/clips/<project>/`, and are reused when a later search finds
the same moment. Each clip is announced as soon as it is written, best result
first. The WISE server must be running, since clips are read through it.

ffmpeg is taken from PATH or the `wise` conda environment. Overrides:
`OREST_FFMPEG_EXE`, `OREST_CLIPS_DIR`, `OREST_TD_HOST`, `OREST_TD_PORT`.

    uv pip install --no-deps rtmlib --python orest/Scripts/python.exe
    uv add --editable ./wise_ext

    conda activate wise
    pip install --no-deps rtmlib
    pip install --no-deps -e ./wise_ext

`--no-deps` is required in both. `rtmlib` depends on `opencv-contrib-python`,
which would install a second, conflicting `cv2` here and would drag numpy above
the `numpy<2` ceiling that WISE's audio extractor holds. Everything rtmlib
actually uses is present already. `pip check` reports the missing
`opencv-contrib-python` as a result; that is expected.

Pose detection uses the GPU in the `wise` environment and the CPU in Orest's,
which has no CUDA runtime. That only affects live queries, where a single clip
costs well under a second either way.

The GPU path depends on `onnxruntime-gpu` matching the CUDA line that torch
brings — currently 1.22.0 against CUDA 12 — and **fails quietly to CPU if they
diverge**, logging a warning rather than raising. After upgrading either, check:

    python -c "from orest_pose import model; model.load(); print(model.active_provider())"

`CUDAExecutionProvider` is the answer you want. `hardware_issues.md` H-10 has
the detail, and `OREST_POSE_DEVICE` forces the choice.

**Tests** (no camera, microphone or GPU required):

    uv run pytest

### External Code: WISE  

WISE is not vendored in this repo. Clone it into folder `external/`:

    mkdir -p external
    git clone https://github.com/ox-vgg/wise.git external/wise
    cd external/wise && git checkout fcfa443fbb46eb361bb19151339338616838a5b5

Pinned version: fcfa443fbb46eb361bb19151339338616838a5b5 2026-08-06 (cloned 2026-08-29)
Install per external/wise/docs/Install.md, or `docker compose up`.
WISE serves on http://localhost:9670.
Run the UI from `external/wise` with `wise serve --project-dir wise-projects/<name>`, then open `http://localhost:9670/<name>/` — the project name is part of the URL.

Follow Install.md from WISE, install via conda as described. Then: conda activate wise followed by wise --help to make sure it is up and running.
