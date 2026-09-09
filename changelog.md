# Changelog

Central development log for Orest. Newest entries first. See
`knowledge/KNOWLEDGE_BASE.md` for pointers into the Source of Truth files
referenced below.

---

## 2026-09-09 — Live SITREP MVP: continuous loop with console output (MININT-ITT28VU)

**Machine:** `MININT-ITT28VU` (user `ctech`).

Added `src/sitrep/main.py` as the entry point for the Realtime-SITREP. It runs
the capture and reporting loop continuously and prints each report to the
console as it arrives, in the Palantir-style block layout. The camera feed is
handled by a separate path in the production and is not displayed here.

    python src/sitrep/main.py
    python src/sitrep/main.py --window 30 --interval 10 --audio-api WASAPI

`report.run_live()` was extracted as the reusable loop — it yields one SITREP
document per capture window and appends each to
`data/sitrep/<session>.jsonl`, skipping windows whose reply is unusable. Both
`main.py` and `report.py`'s own CLI consume it, so there is one implementation
of the live path for other features to build on. Empty fields are omitted from
the console block rather than printed blank.

Started `claude_concerns.md` for open risks and questions that need Moe's
decision rather than a code change — currently report accuracy, the production
machine's GPU, coverage gaps between windows, and what is still untested at
rehearsal scale.

---

## 2026-09-09 — Live SITREP steps 5-6: SITREP JSON, Gemma integration, latency budget (MININT-ITT28VU)

**Machine:** `MININT-ITT28VU` (user `ctech`), RTX 4070 Laptop, 8GB VRAM.

Added `src/sitrep/report.py` (step 5, "Write SITREP report JSON format") and
`src/sitrep/benchmark.py` (step 6, the p95/p99 latency test). The German
report format is documented under "Example SITREP" in
`knowledge/components/02_processing.md`.

    python src/sitrep/report.py --window 30 --interval 10
    python src/sitrep/benchmark.py --runs 10

`report.py` is the live runner: it consumes capture windows, generates a
report per window and appends it to `data/sitrep/<session>.jsonl`. Ollama
receives the pydantic schema as a grammar constraint, so replies parse without
repair. `zeitfenster` and `quelle` are filled from the capture window rather
than generated — the model cannot verify them and every generated token costs
latency.

**Model: `gemma4:e4b`.** The 12b build needs 8.5GB against this machine's
8.1GB and runs 30%/70% CPU/GPU, giving p95 latency of 28-30s regardless of
window size — the VRAM ceiling, not the model, was the bottleneck. e4b is
9.6GB on disk but resident at 3.2GB, 100% GPU.

**Latency is effectively flat in window size** (10 runs per configuration,
0 unusable replies):

| window | interval | frames | p50 | p95 | headroom |
|---|---|---|---|---|---|
| 10s | 5s | 2 | 4.0s | 4.4s | +56% |
| 15s | 5s | 3 | 5.3s | 5.8s | +61% |
| 20s | 5s | 4 | 5.5s | 6.5s | +67% |
| 30s | 10s | 3 | 5.4s | 5.7s | +81% |
| 30s | 5s | 6 | 5.3s | 6.3s | +79% |
| 60s | 15s | 4 | 6.9s | 7.6s | +87% |

Every configuration keeps up. Because latency barely grows with input size,
longer windows are strictly better for coverage: generation blocks the next
window, so the gap between windows equals the latency and coverage is
W/(W+latency) — 65% at a 15s window, 83% at 30s. Choosing X is therefore a
question of desired report cadence, not of compute.

**Audio clips must not end on a 30-second boundary.** The encoder works in
30s chunks; a clip landing on one leaves a final chunk with no usable samples
and the request fails with `Failed to tokenize prompt`. Deterministic and
sharp: 29.99998s and 30.01s are accepted, 30.0s and 30.00002s are not; 30/60/90s
fail, 45/50/75s pass. The 30s default window was exactly the failing case.
`capture.clip_for_encoder()` trims clips clear of the boundary.

**e4b is fast but confabulates heavily.** On live footage it reported a
subject in "Anzug und Krawatte" and, seconds later, "ein schwarzes Hemd und
eine Jeans"; invented a formal speech for `gesagt` where the room held no
German speech; and on an earlier clip described a blond child and a play
titled "Der Schatten des Vergessens". The 12b did not do this on comparable
input. `repeat_penalty` 1.2 was needed to stop e4b running into the token cap
mid-JSON, and both the live runner and the benchmark now skip an unusable
reply rather than ending the session.

**Open:** report content is not yet trustworthy. Most of the invented material
is speech, which step 4 (dedicated transcription) should remove by taking the
transcript out of the model's hands. Whether e4b is the right model at all
depends on the production machine's VRAM — see the note above on the 12b.

---

## 2026-09-09 — Live SITREP step 3: capture loop (MININT-ITT28VU)

**Machine:** `MININT-ITT28VU` (user `ctech`).

Added `src/sitrep/capture.py`, implementing step 3 of the Realtime-SITREP
steps in `knowledge/components/02_processing.md` ("Capture one frame every x
seconds") on top of the device selection below. Covers the `CAM`/`MIC` →
`ORE["Orest — real-time mode"]` path of the CAPTURE graph in
`knowledge/source_of_truth/pipeline.md`.

    python src/sitrep/capture.py --interval 5 --window 30

`run()` is a generator yielding one `Window` per interval: the JPEG frames
sampled during it, a WAV of the audio recorded alongside (16-bit PCM), and the
covered time range — the input shape step 5 ("every 30 seconds, prompt a
SITREP report") will consume. Output goes to `data/sitrep/<session>/`, already
excluded by `.gitignore`, in line with the consent/EU AI Act questions raised
in `02_processing.md` and `01_capture.md`.

Design points:
- Frames are pulled continuously on a background thread rather than read on
  demand, so a sampled frame reflects the current view of the room rather than
  one queued in the camera's buffer — matching the SITREP's low-latency-over-
  accuracy priority.
- The capture loop waits for the first frame before sampling starts, so every
  window (including the first) gets a full set of frames.
- Microphone selection resolves to each host API's own default input device
  rather than its first-enumerated device, so `--audio-api` can't silently
  land on a virtual microphone instead of the real one.
- Live display is left to step 6 ("video output ... handled perhaps via
  TouchDesigner"); `capture.py` is headless, and `devices.py --check` is the
  tool for eyeballing a source.

**Verified end to end:** correct frame count per window, audio duration
matching window length (48kHz WAV), and real image content in the sampled
JPEGs.

**Open:** webcam frame rate under DirectShow varies roughly 10–30 fps across
runs for a reason not yet identified; not a problem at the sparse sampling
rate the SITREP uses, but worth knowing if this path is ever used for
recording.

---

## 2026-09-09 — Live SITREP step 2: video/audio source selection (MININT-ITT28VU)

**Machine:** `MININT-ITT28VU` (user `ctech`).

Added `src/sitrep/devices.py`, implementing step 2 of the Realtime-SITREP
steps in `knowledge/components/02_processing.md` ("select video and audio
source"). Covers the `CAM`/`MIC` sensor inputs feeding the `ORE["Orest —
real-time mode"]` node of the CAPTURE graph in
`knowledge/source_of_truth/pipeline.md`. Step 1 (Gemma via Ollama) already
existed as `src/sitrep/test.py`.

Enumerates cameras and microphones and resolves a device from an index or a
case-insensitive name fragment. `--check` opens both at once and reports
frames/audio level, with a preview window and level meter by default.

    python src/sitrep/devices.py --list
    python src/sitrep/devices.py --check --video "FHD WebCam" --audio "Mikrofonarray" --audio-api WASAPI

Design points:
- Devices are addressed by **name**, not index: DirectShow/PortAudio indices
  shift as hardware is attached or removed, and per
  `knowledge/components/01_capture.md` the test webcam and laptop mic will be
  replaced by dedicated rehearsal hardware.
- Video capture uses `cv2.CAP_DSHOW` on Windows, matching the DirectShow
  enumeration `pygrabber` reads device names from — DirectShow and Media
  Foundation enumerate different device lists, so indices from one cannot be
  mixed with names from the other.
- Each physical microphone is reported once per host API (MME, DirectSound,
  WASAPI, WDM-KS), so `--audio-api` is used to disambiguate. MME truncates
  device names at 31 characters, so WASAPI is preferred for name matching.
- Reading an audio stream tolerates a brief silent warm-up period right after
  opening, rather than treating it as a dead input.

Dependencies added to the uv project: `opencv-python`, `sounddevice`,
`numpy`, `pygrabber`. Confirmed cp314 wheels exist for `torch` and
`faster-whisper`, so the `orest` env's Python 3.14 will not block step 4
(transcription).

---

## 2026-09-09 — Switched to `uv` for Orest's own Python environment and package management (MININT-ITT28VU)

**Machine:** `MININT-ITT28VU` (user `ctech`), same machine as the 2026-09-08 entry.

Orest's own Python code (`src/`) is now managed with
[uv](https://docs.astral.sh/uv/), tracked via `pyproject.toml`/`uv.lock` in
the repo root. The environment lives at `orest/`, gitignored via uv's own
`.gitignore` written inside that directory. `external/wise` is unaffected and
keeps its own conda env (`wise`) per its `docs/Install.md`.

Setup on this machine:
- `uv venv orest` — the virtual environment
- `uv init --bare --no-workspace --name orest` — creates `pyproject.toml`
  only; `--no-workspace` keeps `external/wise`'s own (conda-managed)
  `pyproject.toml` out of this project
- `UV_PROJECT_ENVIRONMENT=orest`, set as a persistent user env var (`setx`),
  so `uv add`/`uv sync` target `orest/` instead of the default `./.venv`

Verified: `uv add ollama` installs into `orest/Lib/site-packages` and records
`ollama>=0.6.2` in `pyproject.toml`. `README.md` setup instructions updated to
match.

---

## 2026-09-08 — WISE feature extraction working end-to-end on theatre test footage (MININT-ITT28VU)

**Machine:** `MININT-ITT28VU` (user `ctech`), TongFang GM5IX7A laptop, Windows 11,
32GB RAM, RTX 4070 Laptop GPU (8GB). This is a **different machine** from the
`ctechadmin` workstation of the 2026-08-29 entry — the two should not be
conflated when reading either entry's findings.

First end-to-end attempt at the `IDX[("Search index<br/>e.g. WISE")]` node of
`knowledge/source_of_truth/pipeline.md`, run over three theatre recordings in
`Desktop/moritz/test_data_orest` (Othello 2022 — 3h37m, 4.3GB; Theaterprobe im
DT Berlin Kapitel 1 — 19m, 3840x2160; Rehearsal Techniques workshop — 12m;
~4h10m total). Project dir `external/wise/wise-projects/test_data_orest`.

**Symptom:** `wise create-index` logged `No index requested for any modality
type` and exited; `wise serve` then failed on missing frontend assets.

**1. `extract-features` registered media but extracted nothing.**
`metadata/internal.db` held 3 `media` rows with correct duration, resolution
and frame counts, but `vectors` and `shots` were empty and the feature store
`store/mlfoundations/open_clip/ViT-B-16-SigLIP2-512/webli/features/` was an
empty directory. The `create-index` message is the downstream symptom, not a
flag problem: it derives its modality list from `WiseProject.discover_assets()`,
which returns nothing when no features exist (`wise/_main/create_index.py`,
the `if not modality_types_wanted` branch). Two causes:

- Re-running `extract-features` against an existing project prompts
  `Do you want to update it? [y/N]:` and aborts on anything but `y`
  (`wise/_main/extract_features.py`, the `if not args.yes` branch). Pass `-y`
  for non-interactive runs.
- The env's torch was the CPU-only wheel (`2.8.0+cpu`, `cuda.is_available()`
  false) despite the machine having an RTX 4070 Laptop GPU (8GB). Replaced with
  the CUDA build (item 2), which is worth having regardless. But this was
  asserted to be the cause of the empty feature store on no evidence beyond
  "CPU would be slow", and that inference was never substantiated — see the
  closing note on what remains unexplained.

**2. Installed the CUDA torch build — and broke numpy doing it (failed
approach, recorded so it isn't repeated).**
`pip install --force-reinstall torch==2.8.0 torchvision==0.23.0
torchaudio==2.8.0 --index-url https://download.pytorch.org/whl/cu128`
got torch onto the GPU (`2.8.0+cu128`, CUDA available), but
`--force-reinstall` re-resolves the entire dependency tree rather than only
the named packages, so it pulled numpy 2.5.2 and violated `msclap 1.3.4`'s
`numpy<2.0.0` ceiling — MS CLAP being WISE's audio feature extractor.
`requirements.txt` leaves numpy unpinned, so that transitive ceiling is the
only thing holding it below 2.x. Repaired with `pip install "numpy<2"`
(→ 1.26.4); `pip check` clean, msclap/faiss/open_clip/wise all import. Use
plain `pip install <pkg>==<version> --index-url ...` for targeted swaps
inside this env; avoid `--force-reinstall`.

**3. `wise serve` requires the frontend to be built separately.**
Fails with `FileNotFoundError: Frontend assets not found at frontend\dist`.
`package.json` lives in `external/wise/frontend/`, not the repo root, so
`npm install` and `npm run build` must be run from that directory. Built
successfully (vite, ~14s). As with the two source patches noted in the
2026-08-29 entry, this is local-only state — `dist/*` is gitignored by WISE
and `external/` wholesale by Orest — so it must be rebuilt after any
re-clone of `external/wise`.

Also noted for this machine: Windows PowerShell 5.1 does not support `&&` as
a statement separator (PowerShell 7+ only); chain with `;`. The bash-style
`\` line continuations in `docs/UserGuide.md` don't work there either, and
its inline `# ...` annotations break the command in bash too, since the
backslash is then no longer the final character on the line.

**4. `--media-include` takes glob patterns, not regular expressions.**
A probe run restricted with `--media-include ".*Rehearsal.*"` matched zero
files and exited with `No valid media files found. Nothing to do.` The
option's values are passed straight to `pathlib.Path.rglob()`
(`wise/dataloader/utils.py`, `get_files_from_directory_with_extensions`), so
they are globs — the `--help` text calling it a "regular expression" is
wrong, and the default value `["*"]` is likewise a glob. Use `*Rehearsal*`,
not `.*Rehearsal.*`.

**5. A project created with zero matched media files is unusable and must be
recreated.** After the failed glob run above left an empty project, re-running
`extract-features` against it — with media now matching — still refused:
`No feature extractors matching the relevant modality of the media files
specified.` A project's feature extractors are discovered from the `store/`
directory tree (`get_feature_extractor_ids_from_project()` →
`WiseProject.discover_assets()`), and an empty project has none registered.
`add_media` mode deliberately discards the extractor ids passed on the command
line in favour of the project's existing ones (it warns: "A project can only be
updated with new media files using the existing feature extractors"), so there
is no way to populate them after the fact. Only the `create` path reads
extractor ids from arguments/defaults. Fix: delete the project directory and
recreate it, or use a fresh `--project-dir`.

**6. Do not invoke WISE as `python -m wise` from inside `external/wise` — the
repo's `triton/` directory shadows the real `triton` package.**
A `ModuleNotFoundError: No module named 'triton.language'` was observed during
model construction and initially misdiagnosed as "Triton has no Windows build,
so `torch.compile` cannot work here." That diagnosis was wrong, and the
`wise_config.yaml` written to disable compilation has been removed again.

The real mechanism: `external/wise/triton/` holds Triton Inference Server
configuration (`cache/`, `models/`, `wise-env/`). `python -m wise` and
`python -c` put the working directory on `sys.path`, so `import triton`
resolves to that directory as an implicit namespace package. Torch guards this
import correctly for the *absent* case
(`torch/_inductor/runtime/triton_compat.py`: `try: import triton / except
ImportError: triton = None`), but a directory that imports successfully while
having no `language` submodule slips past the guard, and the following
`import triton.language` raises. The installed `wise` console script does not
put the working directory on `sys.path`, so it is unaffected — which is why
feature extraction had already been running without trouble on macOS and on the
other PC. Use the `wise` entry point; reserve `python -m wise` for directories
that contain no `triton/`.

Verified directly: with no config file and `compile` left at its default
(enabled), `wise extract-features` run from `external/wise` completed cleanly,
logging `Compiling model with backend inductor` and zero triton errors.
Disabling compilation made no measurable difference (88s vs 87s for the same
input), so there is no reason to turn it off.

**Status: working end-to-end.** Probe run over the 12-minute rehearsal video
(`--media-include "*Rehearsal*"`, project `wise-projects/probe`) extracted
1640 vectors — 1458 video (SigLIP2-512 at 2fps) and 182 audio (MS CLAP) — in
**88 seconds** on the RTX 4070 at ~24 it/s. `create-index` built both
`IndexFlatIP` indices without complaint. Extrapolating, the full ~4h10m test
set should take roughly 30 minutes.

**7. `wise serve` failed on Windows: feature extractor ids were built with
backslashes.** With the frontend built, `serve` still died with
`ValueError: Feature extractor name must be formatted as USER_OR_ORGANIZATION /
REPOSITORY_NAME / MODEL_NAME / TRAINING_DATASET`. `WiseProject.discover_assets()`
derives each id from the `store/` directory tree via
`str(feature_dir.relative_to(self._store_dir).parent)`, and `str()` on a path
yields the platform separator — so on Windows the ids came back as
`microsoft\clap\2023\four-datasets`. `FeatureExtractorFactory` splits them on
`/`, got a single element, and rejected it. `extract-features` is unaffected
because it takes ids from arguments rather than from disk, and `create-index`
is unaffected because it only uses the id as a key.

Fixed with `.as_posix()` in `src/wise/wise_project.py`, saved as
`knowledge/source_of_truth/wise-patches/0003-posix-feature-extractor-ids.patch`
and listed in `knowledge/source_of_truth/versions.md` alongside the two existing
Windows patches. Reinstalled with `pip install --no-deps --force-reinstall .`
(`--no-deps` keeps the dependency tree untouched — see item 2). Verified:
`http://localhost:9670/probe/` returns 200. The bare root returns 404; the
project name is a required path segment. Added a one-line usage note to Orest's
`README.md`.

**Still unexplained:** why the original 20:15 run over `test_data_orest` left
3 registered media rows and no vectors. Its console output was not captured,
and none of the causes established above (items 4, 5 and 6) apply to it — it
used the `wise` entry point, no `--media-include`, and a fresh project
directory. Worth re-running with output captured before drawing any conclusion.
`wise-projects/test_data_orest` still holds no vectors and should be recreated
rather than updated, per item 5.

---

## 2026-08-29 — WISE local install fixed on Windows (ctechadmin PC, Film University Babelsberg)

**Machine:** `ctechadmin` Windows 11 workstation, Film University Babelsberg (MDM-enrolled, Sophos + AppLocker managed).

Got `external/wise` (pinned per `knowledge/source_of_truth/versions.md`,
commit `fcfa443` cloned 2026-08-29) installed and running locally — this is
the search-index component in the pipeline (`knowledge/source_of_truth/pipeline.md`,
the `IDX[("Search index<br/>e.g. WISE")]` node). Three unrelated problems
stacked on top of each other; noting all three since the surface symptoms
were misleading.

**1. Miniconda installed but `conda` not on PATH.**
Ran `conda init powershell` and `conda init bash`, then had to
`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` (was `Restricted`) so
PowerShell would load the profile script conda's init writes.

**2. `environment.yml`'s unbounded `python>=3.10` resolved to Python 3.14.**
`requirements.txt` pins `torch>=2.2.2,<2.9` (torchaudio 2.9 dropped
`streamreader`, which WISE depends on). No torch wheel exists for cp314
below 2.9, so `conda env create` failed with a `pip` resolver error that
named torch, not Python, as the problem. First attempt used a scratch copy
of the YAML with `python=3.12` pinned as a one-off workaround — but that's
not discoverable, so the next plain run of the documented command
(`conda env create --name wise --file environment.yml`) hit the exact same
failure again. Real fix: edited `external/wise/environment.yml` itself to
`python>=3.10,<3.13`, since conda's `env create -f file python=3.12` CLI
override is silently misparsed as a bogus remote-file URL and ignored — the
bound has to live in the YAML. Same class of bug as noted for macOS in
`knowledge/background/wise_learnings.md` §2c/2d — Python version bounds are
load-bearing, and conda ignores CLI package overrides on `env create`. The
documented three-line install from `docs/Install.md` now works verbatim.

**3. `wise --help` hung indefinitely at ~100% CPU, no error, no traceback.**
Initially misread as Windows Defender Application Control / AppLocker
blocking a DLL (`_bz2.pyd` briefly threw a genuine, unrelated,
self-resolving on-access-scan block from Sophos — confirmed Smart App
Control was already off, so that lead was a dead end). `faulthandler.dump_traceback_later`
pinpointed the real cause: `python-magic`'s Windows `libmagic` build hangs
natively inside `magic_open()`/`magic_load()`, imported at module load time
by `wise/dataloader/utils.py`. WISE's own `docs/Install.md` already flags
Windows as untested — this is that. Fix: patched
`external/wise/src/wise/dataloader/utils.py` to skip `python-magic` on
`win32` and fall back to the stdlib `mimetypes` module instead (only used
as a last-resort fallback behind `filetype`, the primary matcher — no
behaviour change on Linux/macOS). Reinstalled with
`pip install --no-deps --force-reinstall .`; `wise --help` now completes in
~6s.

**Net result:** `wise` conda env (Python 3.12) fully functional on this
machine, installed via the plain documented command with no manual
workarounds.

**On the two local patches surviving a re-clone:** `external/wise` is a
plain git clone, gitignored wholesale by this repo's `external/` rule — so
edits inside it are invisible to Orest's git and would be lost if
`external/wise` is ever deleted and re-cloned. Both patches are saved as
`.patch` files under `knowledge/source_of_truth/wise-patches/` (tracked by
this repo) and documented in `knowledge/source_of_truth/versions.md` for
reapplication:

```bash
git -C external/wise apply ../../knowledge/source_of_truth/wise-patches/0001-pin-python-upper-bound.patch
git -C external/wise apply ../../knowledge/source_of_truth/wise-patches/0002-skip-libmagic-on-windows.patch
```
