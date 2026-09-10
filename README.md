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
