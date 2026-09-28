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
`gemma4:e4b`) pulled.

Recording never pauses for a report. Windows are cut back to back on a thread
of their own (`capture.Recorder`), and a report takes every window that
finished while the previous one was being made, merged into one. A line still
being spoken when a window ends is held back and reported whole with the next
window. Each report's model also sees the previous report's last lines. A
report takes 3–7 s to make with `gemma4:26b`, so windows of 10–15 s keep up;
shorter windows are merged in pairs or more, which delays the reports.
Stopping a run deletes at once everything it holds: waiting windows, sound
not yet cut, face tracks, poses, mouth measurements and unreported readings. Speech is transcribed as German unless `--language` names
another Whisper language code; the English test corpus needs `--language en`,
or it comes out as rough German. `--audio-ndi SOURCE` takes the sound from an
NDI source instead of a microphone, e.g. OBS's programme output with DistroAV:

    uv run orest-ui --video "OBS Virtual Camera" --audio-ndi "VSH-ARLT-5090 (OBS PGM)" --language en The live SITREP records nothing: reports are streamed to
the console and not retained, and no frame or audio clip is written to disk.

Each report carries a **Beschreibung** (what happened, who did what), the
**Personen** in the window, each with a short description and three 0–5
ratings (risiko, menschlichkeit, auffaelligkeit), the
**Szene** rated 0–10 for relevanz, eskalation and gefahr, a **Prognose** of the
three most likely developments with a percentage each, most likely first, and
an **Empfehlung**. The Empfehlung is written only when the scene's eskalation
or gefahr is above 6 (`report.SCHWELLE`). Orest applies that rule itself, not
the model.

Faces are tracked on every run, and person names come from that tracking. With
`--cast data/cast`, enrolled people are recognised by name; everyone else gets
a guessed name such as `Vielleicht: Jakob`. Each name is drawn above its face
in the frames the model sees, and the model may only use those names, or
`Unbekannt`. The NDI picture sent to TouchDesigner stays unmarked.

**risiko** and **menschlichkeit** are measured, not generated. The NTU120
action recogniser (`src/action/`) runs on the camera at 25 fps beside the
report. Each body takes the name of the face its head is in, and the
recognised actions are weighed with `src/action/sitrep_map.csv`
(`src/sitrep/actions.py`). A person whose body the recogniser didn't read
shows these two ratings as `–`. The model rates only **auffaelligkeit**.

**What was said** is rated per line by a second, text-only request to the same
model (`src/sitrep/speech.py`). Each line is taken at its word, as if seriously
meant, and scored from −5 to +5 for risiko and menschlichkeit, reason first.
The example lines in `src/sitrep/speech_examples.csv` anchor the scale; add a
row there to fix how a line is scored. A person's risiko and menschlichkeit are
the higher of their action and speech ratings. `python -m sitrep.speech
--model gemma4:26b` rates the lines in `src/sitrep/speech_eval.csv` and counts
the misses.

**Loudness** amplifies Risiko (`src/sitrep/loudness.py`). Each run learns its
normal speaking level from its first speech: provisionally after 30 s of
detected speech, fixed after 120 s. Until the first 30 s nothing is
amplified. Lines that stand out are marked `(laut)` or `(geschrien)` in the
transcript the model reads. Afterwards, a line or an action louder than one standard
deviation above normal has its positive Risiko evidence multiplied by up to 2.
Menschlichkeit is left as it is. The report header shows the calibration
(`Pegel normal −30 dBFS ±5`), and each amplified line its gain (`×1.5`).

**Who said what** is measured by lip movement (`src/sitrep/speakers.py`). The
two tallest bodies are the people the system follows. Each Whisper segment
goes to the one whose lips moved at least 1.5 times as much as the other's,
measured with the 106-point landmark model of the face models' `buffalo_l`
bundle. Otherwise it stays `(unklar)`. The report carries the lines as
`aeusserungen`, and the model reads the transcript as `Name: line`. The
operator page's video shows both people boxed with their names. The NDI feed
and the model's frames are marked as before.
`--no-actions` turns the recogniser off. It needs the exported model in
`data/models/ntu120_stgcn/`.

### The operator page

`src/interface/` serves the operator page on the loopback interface:

    uv run orest-ui
    uv run orest-ui --video "OBS Virtual Camera" --model gemma4:26b --window 15 --interval 5

Open http://127.0.0.1:9680/. **Start live SITREP** opens a new tab, starts the
run and shows the camera with the current report beneath it. The tab's
**Stoppen** button releases the camera. Closing the tab does not stop the run.
Reopening the page rejoins it.

Below the camera, **Aktionserkennung · live** shows the action recogniser's
latest classification every second: each person or pair, their most probable
action and its evidence for risiko and menschlichkeit. Bodies without a
recognised face appear as `Körper <id>` and don't count toward the report. In
each report, **Gemessen** lists everyone the recogniser rated, with the action
behind each rating.

`orest-ui` takes the same camera, microphone, window, `--cast`, `--send-td`
and `--send-ndi` options as `orest-sitrep`, and applies them to every run
started from the page. Devices are resolved when a run starts, so a device
error appears on the page. Only one run can hold the camera at a time.
Overrides: `OREST_UI_HOST`, `OREST_UI_PORT`.

Without a physical camera, OBS's virtual camera works as a source: a Media
Source playing a recording, then **Start Virtual Camera**, then
`--video "OBS Virtual Camera"`. OBS sends no audio this way, so `gesagt` stays
empty.

### Sending the live SITREP to TouchDesigner

Two channels, turned on separately — pixels and messages travel differently
(`knowledge/components/03_render.md`):

    uv run orest-sitrep --send-ndi                  # the camera, as an NDI source
    uv run orest-sitrep --send-td                   # report and roster, over OSC
    uv run orest-sitrep --send-ndi --send-td --cast data/cast

In TouchDesigner, an **NDI In TOP** receives the picture — the source is named
`Orest SITREP` by default, changed with `--ndi-name`. An **OSC In DAT on port
10000** receives the text, on the same port search results already use; the
addresses are namespaced so one DAT can route both:

    /orest/sitrep/begin         <id> <nummer> <beginn> <ende> <dauer_s> <bilder>
                                <ton_s> <latenz_s> <personen> <prognosen>
    /orest/sitrep/beschreibung  <id> <beschreibung>
    /orest/sitrep/gesagt        <id> <gesagt>
    /orest/sitrep/person        <id> <zeile> <name> <vermutet> <beschreibung>
                                <risiko> <menschlichkeit> <auffaelligkeit>
    /orest/sitrep/szene         <id> <relevanz> <eskalation> <gefahr>
    /orest/sitrep/prognose      <id> <rang> <wahrscheinlichkeit> <verlauf>
    /orest/sitrep/empfehlung    <id> <einschreiten> <massnahme>
    /orest/sitrep/end           <id>

A second and faster stream reports who is in the room, about twice a second,
framed by a rising `tick`:

    /orest/presence/begin  <tick> <zeit> <anwesend>
    /orest/presence/person <tick> <zeile> <label> <name> <vermutet>
                           <aehnlichkeit> <sichtungen> <seit> <dauer_s>
    /orest/presence/end    <tick>

In the roster, `name` is empty and `vermutet` is 1 when the cast gallery did
not recognise the person, so a guess can be set apart from a recognition. In a
report, `vermutet` is 1 for a guessed name and for `Unbekannt`. A report `name`
is always a roster `label` from the report's window, or `Unbekannt`.
Forecasts arrive most likely first. `einschreiten` is 1 when the scene's
`eskalation` or `gefahr` is above 6; `massnahme` is empty otherwise.
`risiko` and `menschlichkeit` are -1 when the action recogniser read nothing
of the person.

The TouchDesigner side is described in
`TouchDesigner/2026-09-25_touchdesigner_setup.md`.

Host and port come from `OREST_TD_HOST` and `OREST_TD_PORT`, shared with
`orest-search`. Only one process can hold port 10000, so a second TouchDesigner
instance will not receive anything.

Each module also runs on its own, for diagnostics:

    uv run python -m sitrep.devices --list
    uv run python -m sitrep.devices --check --video "FHD WebCam"
    uv run python -m sitrep.capture --interval 5 --window 30
    uv run python -m sitrep.presence --cast data/cast
    uv run python -m sitrep.benchmark --speech <speech.wav>

The console block is drawn with box-drawing characters, so redirecting it to
a file needs UTF-8:

    PYTHONIOENCODING=utf-8 uv run orest-sitrep > session.txt

### Recognising the cast

`src/face/` detects and identifies faces, and `sitrep.presence` follows them
across a rehearsal. Put a few photographs of each person in a folder named
after them:

    data/cast/
      klara/01.jpg  02.jpg  03.jpg
      moritz/01.jpg 02.jpg  03.jpg

Five to ten images each, varied in angle, profiles included. Measured on the
corpus, one image identifies 62% of later sightings, three 76%, ten 86%.

Check the enrolment before a rehearsal — every value off the diagonal should be
well below the naming threshold:

    uv run python -m face.gallery data/cast

Then watch who the system sees, live or over a recording:

    uv run python -m sitrep.presence --cast data/cast
    uv run python -m sitrep.presence --cast data/cast --recording rehearsal.mp4 --start 300

A face the enrolment does not match is given an invented name marked as a
guess, such as `Vielleicht: Jakob`, which holds until that person leaves.

The models download on first use (288 MB) to `~/.cache/orest/`. Nothing in
`data/` is tracked by git: the photographs are of identifiable people and the
consent questions in `knowledge/components/01_capture.md` are open.

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

### Searching by a live movement

`body-live` watches a camera and searches with whatever movement is captured
between a start and a stop press:

    uv run orest-search body-live --send-td
    uv run orest-search body-live --video "FHD WebCam" --per-file 2 --send-td
    uv run orest-search body-live --file <recording.mp4> --at 300

Enter in the terminal toggles a capture. From TouchDesigner or QLab, send OSC
to `127.0.0.1:10001`:

    /orest/body/start
    /orest/body/stop

A capture of any length is searched in four-second windows stepped by two
seconds, the shape of the indexed segments, and a capture shorter than four
seconds is extended backwards from the stop press. Results from the windows are
merged. `--per-file N` keeps at most N results from any one recording. `--file`
plays a recording in real time in place of the camera, for rehearsing the
workflow on known footage. Overrides: `OREST_CONTROL_HOST`,
`OREST_CONTROL_PORT`.

### Sending results to TouchDesigner

`query`, `body` and `body-live` cut each result into a clip and can announce it
over OSC.
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
since it ignores the MP4 edit list that hides them from other players.
`--cut precise` re-encodes to H.264: about
1s per 8 seconds of 1080p and 3.5s per 8 seconds of 4K; `--encoder h264_nvenc`
is faster where the GPU is free. Clips cover exactly the range WISE returned,
are written to `data/clips/<project>/`, and are reused when a later search finds
the same moment. Each clip is announced as soon as it is written, best result
first. The WISE server must be running, since clips are read through it.

ffmpeg is taken from PATH or the `wise` conda environment. Overrides:
`OREST_FFMPEG_EXE`, `OREST_CLIPS_DIR`, `OREST_TD_HOST`, `OREST_TD_PORT`.

**Merged spans or segments.** By default a result is a span of neighbouring
matches merged into one moment, which can run to a minute or more where a long
stretch matches, and whose bounds shift from search to search. `--segments`
returns the indexed four-second windows instead: every clip is four seconds,
and the same moment always maps to the same clip file. On the text index the
windows sit half a second apart, so several results may cover one moment; on
the body index they step by two seconds. Available on `query`, `body` and
`body-live`.

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
