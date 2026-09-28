# Changelog

Central development log for Orest. Newest entries first. See
`knowledge/KNOWLEDGE_BASE.md` for pointers into the Source of Truth files
referenced below.

---

## 2026-09-25 — Review of the name-tagging change; a failed naming pass no longer ends the session

Review of the entry below. Python, the OSC wire format, `sitrep_osc.py`, the
README and the TouchDesigner setup note agree. The grammar schema leaves out
the computed `einschreiten`. `uv.lock` matches `pyproject.toml`.

**One change.** The naming pass now runs inside the SITREP sampling loop
(`capture.windows` → `Session._name_faces`), so an error in the face models,
e.g. a CUDA out-of-memory error with Ollama holding the GPU, would have ended
the session. `Session._name_faces` now sends that frame unmarked and prints the
error to stderr. This follows `report.sitreps`, which skips a bad window
rather than ending the run. The Realtime-SITREP puts low latency ahead of
accuracy (`knowledge/components/02_processing.md`). 272 tests pass.

**Open, for Moe. Not changed, since each one changes how the tracker behaves:**
- **A tag can show a name the grammar doesn't allow.** Frames are tagged when
  they are sampled, but the name list comes from the roster when the window
  ends. If a track is recognised partway through the window (`Vielleicht:
  Jakob` becomes `Anna`), or `_adopt` gives it a stronger name, earlier frames
  show a label that isn't in the enum.
- **Two faces in one frame can both be tagged with one cast name.**
  `gallery.match` isn't one-to-one. If two faces both pass the threshold for
  Anna, both tracks take the name, `_merge_by_name` merges them into one
  track, and the model sees "Anna" on two people.
- **An error in the tracker's own thread stops it with no message.** This was
  already true. It matters more now that the tracker runs on every session:
  the roster sent to TouchDesigner would stop updating, and nothing would say
  why.

---

## 2026-09-28 — Pretrained action recognition, step 4: continuous pose, tracking, pairs (VSH-ARLT-5090)

`src/action/` feeds the NTU120 ST-GCN what it was trained on, from a live
source or a recording:

    python -m action --recording <file> --start 120 --duration 60

- **`preprocess.py`** reproduces the model's MMAction2 test pipeline in
  numpy: normalisation, joint features, frame sampling, decoding and person
  slots. It is **bit-identical** to MMAction2's output on the reference
  sequence. Its frame indices also match MMAction2's for 100-, 150- and
  250-frame sequences, the sampling branches the 75-frame reference doesn't
  reach. The export script now records those indices too. Three details
  decide the match:
  - The keypoints pass through float16.
  - The 10 test clips are sampled with a generator seeded at 255. A local
    `RandomState(255)` draws the same numbers without touching NumPy's
    global state.
  - An absent person is zeros before normalisation, so -1 after it, as in
    training.
- **`tracking.py`** gives each body a stable id by greedy box overlap between
  consecutive frames. A body may go undetected for up to 1 s and keep its id.
  Detections with fewer than 5 visible joints aren't followed.
- **`recognizer.py`** runs pose at **25 fps** and classifies the last **4 s**
  every second. 25 × 4 = 100 frames is exactly one clip. NTU clips mostly
  span a whole action in 100 or more frames, and a shorter window would be
  looped to fill the clip, showing the action faster and repeated. Each person
  present in at least half the window is classified alone, and each pair
  whose centres stay within 1.5 mean body heights is classified together.
  NTU recorded mutual actions with two people and single actions with one,
  so the model knows each only in that form. Everything in a window goes to
  the model as one batch.
- **`model.py`** runs the ONNX file on CUDA with TF32 off, and averages the
  softmax over the 10 clips as MMAction2 does.

**Measured** over 30 s of "Boom" from the test corpus: pose 8.2 ms per frame,
the action model 47 ms per window for all groups together, both on CUDA. 20
new tests, none needing the model or a GPU; 304 pass.

**Not measured: whether it recognises anything that matters.** The corpus is
improvised comedy with no violence. The readings are what NTU makes of people
talking:
- A woman holding a glass: "reading".
- Seated spectators: "playing with phone/tablet".
- Pairs in conversation: "point finger at the other person", "touch other
  person's pocket".

A test needs footage of the actions the SITREP cares about, such as staged
pushes, slaps or embraces, ideally from the production's own rehearsals.

**Open:**
- **The audience dominates.** Track ids reach 17 in 30 s as spectators at the
  frame's edges come and go, and each is classified. A stage region, or a
  minimum body size, would restrict recognition to the performers.
- **Readings aren't filtered or mapped yet.** Every reading carries all 120
  classes. Step 5 selects the classes of interest, and step 7 connects them
  to the SITREP's values.
- **Combined GPU load is unmeasured.** Pose at 25 fps takes about 200 ms of
  GPU time per second. That comes on top of the presence tracker's face
  passes, Whisper and Gemma, and all of them together have not been run.

---

## 2026-09-28 — GPU ONNX Runtime in Orest's environment (VSH-ARLT-5090)

Pose detection, face recognition and the new action model now run on the GPU
in the `orest` environment. Until now they ran on the CPU there, on every
machine (`hardware_issues.md` H-10). The step 3 entry below wrongly called this
a regression on the new machine: the laptop's `orest` environment was CPU-only
too, and the GPU build H-10 describes lived in WISE's environment.

- **`onnxruntime-gpu[cuda,cudnn]==1.26.0`** is declared in `pyproject.toml`.
  It is the last CUDA 12 line, matching CTranslate2's, so the environment
  carries one CUDA runtime. It is also the first version with Python 3.14
  wheels on the CUDA 12 line; 1.27 onwards needs CUDA 13.
- **A uv override drops the CPU `onnxruntime`** that `rtmlib` and
  `faster-whisper` depend on. Both packages install the same `onnxruntime`
  module, and whichever lands last wins.
- **`orest_pose.model` and `face.model`** put
  `site-packages/nvidia/*/bin` on PATH when torch isn't installed. The first
  attempt used `onnxruntime.preload_dlls()` alone, and cuDNN then failed on
  the first convolution: it loads `cudnn_engines_tensor_ir64_9.dll` by name
  and couldn't find it (`CUDNN_STATUS_SUBLIBRARY_LOADING_FAILED`).

**Verified:** all three models report `CUDAExecutionProvider`, and Whisper
still transcribes. 284 tests pass.

| Model | Before, on the CPU | Now, on the RTX 5090 |
|---|---|---|
| RTMO pose | 43 ms per frame | 8.1 ms per frame |
| Face detection and embedding | ~226 ms per pass | 10.1 ms per pass |
| NTU120 action model, 10 clips | 122 ms | 3.9 ms |

**TF32 changes results slightly.** ONNX Runtime's CUDA provider uses TF32 by
default, which moved the action model's probabilities by up to 8 × 10⁻⁴
against MMAction2 (2.7 ms). With `use_tf32=0` the difference is 3.6 × 10⁻⁷
(3.9 ms). The action model will run without TF32, which keeps its tests
exact.

---

## 2026-09-28 — Pretrained action recognition, step 3: exported to ONNX (VSH-ARLT-5090)

The NTU120 ST-GCN now exists as `data/models/ntu120_stgcn/stgcn_ntu120_2d.onnx`.
Orest can run it with `onnxruntime` alone; MMAction2 and PyTorch are needed
only to produce the file. `src/scripts/export_ntu_stgcn.py` does the export
and checks it. Its docstring gives the environment setup, so the export can
be repeated.

**A separate conda environment, `mmaction`** (Python 3.10, torch 2.3.1 CPU,
mmengine 0.10.7, mmcv-lite 2.1.0, MMAction2 1.2.0). It follows the same
pattern as `wise`: a PyTorch stack that can't live in Orest's Python 3.14
environment is kept apart. Three things needed working around:

- **MMAction2 1.2.0 can't be imported as packaged, from PyPI or from git.**
  `mmaction/models/localizers/drn` has no `__init__.py`, so the package build
  skips it, and `import mmaction.models` fails. The fix was an editable
  install from a clone at tag v1.2.0 in `external/mmaction2`, which is
  gitignored.
- **Pinned to torch 2.3.** From torch 2.6, `torch.load` defaults to
  `weights_only`, which checkpoints of this generation don't load under.
- **mmcv-lite rather than full mmcv.** ST-GCN needs none of mmcv's compiled
  operators, and full mmcv has no wheels for this setup.

**What was exported:** the network only, `cls_head(backbone(x))`. It takes
`(batch, 2 people, 100 frames, 17 joints, x/y/score)` and returns 120
logits, with a dynamic batch axis, at opset 17. MMAction2's preprocessing, and
its softmax averaged over 10 test clips, stay outside the file for Orest to
reproduce in step 4.

**Verified:**

| Check | Max difference |
|---|---|
| Network: PyTorch vs ONNX Runtime, random input, logits | 1.9 × 10⁻⁶ |
| Recogniser: MMAction2 `inference_skeleton` vs ONNX fed MMAction2's preprocessing, 120 probabilities | 6.6 × 10⁻⁷ |
| The same, in Orest's environment (onnxruntime 1.29.0) | 3.0 × 10⁻⁷ |

- **Speed in Orest, on the CPU:** 10.6 ms per clip, about 130 ms for the
  full 10-clip average.
- **Reference fixture (`reference.npz`):** a synthetic two-person sequence
  of 75 frames at 1080p, with MMAction2's preprocessed tensor for it and its
  final prediction. Step 4's preprocessing is to be tested against it. It's
  synthetic, so it holds no footage of anyone.
- **The synthetic sequence's result:** its arm sweep was classified as
  "point finger at the other person" (0.67) and "pat on back" (0.24). Both
  are two-person classes, but that says nothing about accuracy on real
  footage.

**Found on the way: ONNX Runtime in the `orest` environment is CPU-only on
this machine.** It is version 1.29.0 with no CUDA provider, which is the
silent regression `hardware_issues.md` H-10 warns about. The laptop's
`onnxruntime-gpu` was a manual install that was never declared, so it didn't
reach this machine, and RTMO pose detection runs on the CPU here too. The
recogniser itself is fast enough on the CPU. Fixing it means declaring the
GPU build in `pyproject.toml`; see H-10.

---

## 2026-09-28 — Pretrained action recognition, step 1: model chosen and downloaded (VSH-ARLT-5090)

This is the first step toward the *Pose* route under "Calculating Values" in
`knowledge/components/02_processing.md`: recognising activities such as
hitting or hugging, and mapping them to SITREP values. The plan starts from a
recogniser someone else trained. Training one on Orest's own footage would
need a labelled archive first.

**Model: ST-GCN, joint modality, NTU RGB+D 120 cross-subject, 2D keypoints**,
from the MMAction2 model zoo. The choice rests on three points:

- **The keypoints match.** MMAction2's 2D NTU skeletons were produced with
  HRNet-w32 in COCO-17 layout, the same 17 joints in the same order that RTMO
  (`orest_pose`) outputs.
- **NTU120, not NTU60.** NTU120 has all 26 two-person classes. Only it has
  "hit other person with something", "wield knife towards other person" and
  "knock over other person". The NTU60 models score higher (ST-GCN++ 89.3%)
  but lack these classes.
- **Joint modality, plain ST-GCN.** It takes raw keypoints, with no bone or
  motion features to derive, at 83.19% top-1 against 83.36% for the bone
  variant. It is also the simplest architecture on offer, which matters for
  the ONNX export in step 3.

Files are in `data/models/ntu120_stgcn/`, which is gitignored. `SOURCE.md`
there gives URLs and the checksum. MMAction2 publishes only an NTU60 class
list, so `label_map_ntu120.txt` was assembled from it and the official NTU
README; the first 60 classes agree exactly.

**Verified** in the `wise` environment, which has torch:
- The SHA-256 begins `612416c6`, matching the filename.
- 3.1 M parameters and a 120-class head.
- The input batch norm expects 51 values: 17 joints × (x, y, confidence).

**What step 4 has to reproduce**, per the config:
- `PreNormalize2D` normalises keypoints to the image size.
- `FormatGCNInput` always takes two people, padding the second with zeros.
- `UniformSampleFrames` resamples every clip to 100 frames, whatever its
  length; testing averages 10 such clips. NTU clips run about 2–5 s, so a live
  window should be about that long, resampled the same way.

**Licence:** NTU RGB+D is "for academic research only … for non-commercial
purposes" and prohibits "derivation … and commercial usage … in any way or
form" without permission from ROSE Lab. Moe confirmed that the theatre
project is part of a research project, which these terms cover.

Training Orest's own recogniser on rehearsal footage is listed as a
nice-to-have in `todo_with_data.md`.

---

## 2026-09-25 — Operator page: the live SITREP in the browser (VSH-ARLT-5090)

The live SITREP is displayed in a browser instead of TouchDesigner. Laid out
with a Text TOP, the report was unreadable as a display. Moe decided that
TouchDesigner keeps receiving the report as OSC data, but no longer lays it
out. This completes step 7 of the Realtime-SITREP in
`knowledge/components/02_processing.md` ("video output ... and SITREP text
beneath it"). It also starts the localhost interface of the same file, as
planned in `progress_tracker.md` (Smart Search, phase 5: "FastAPI plus plain
HTML").

    uv run orest-ui --video "OBS Virtual Camera" --model gemma4:26b

- **Operator page (`/`)**: a single button, **Start live SITREP**, which opens
  `/sitrep` in a new tab.
- **SITREP page (`/sitrep`)**: starts the run on opening and shows the camera
  feed with the report beneath it. The report shows the Empfehlung as a banner
  that turns red above the threshold, the Beschreibung and transcript, the
  three scene ratings as bars with the threshold marked, a card per person
  (guessed names marked) and the three forecasts with probability bars. The
  last report stays on screen after a stop. Model text is set with
  `textContent` only, so a reply cannot inject markup.
- **Transport**: the camera goes to the browser as MJPEG, which an `<img>`
  plays with no script. Reports arrive as server-sent events, which reconnect
  on their own.
- **`interface.live.LiveSitrep`** holds the single run on its own thread. It
  opens the session on request, so device errors show on the page rather than
  in the terminal.
- **Binding**: `orest-ui` binds 127.0.0.1:9680, for the same reason as the
  WISE server: the page shows footage of identifiable people.
- **New dependencies**: `fastapi` 0.141.1 and `uvicorn` 0.54.0.

**A COM fix was needed.** Resolving the camera from the run's thread failed
with `CoInitialize has not been called`. `pygrabber` enumerates cameras through
DirectShow, a COM API, and `comtypes` initialises COM only on the main thread.
`devices.list_video_devices()` now initialises and releases COM around the
enumeration, which works on any thread.

**Verified end to end** with OBS Virtual Camera playing a test recording and
`gemma4:26b`:
- A run started through the API and reached `running`. The tracker named two
  people, and the report arrived with every field.
- The video endpoint delivered 44 JPEG parts in 3 s (about 15 fps).
- Headless Edge rendered both pages. It doesn't paint MJPEG streams, so the
  video area was black in its screenshot only.
- 284 tests pass. The feed generator is tested directly, because Starlette's
  test client buffers whole responses and never returns from an open-ended
  stream.

**Open:**
- **Closing the tab doesn't stop the run.** A second viewer, or a later
  TouchDesigner Web Render TOP, would otherwise stop it for everyone. The
  camera stays held until Stoppen or until the server exits.
- **Stopping takes up to one window.** The camera is released at once, but
  the run's thread finishes the generation it is in before another run can
  start.
- **OBS's virtual camera delivers 640×480** unless its output resolution is
  raised. At that size the faces in a stage wide shot are small for
  recognition.
- **The alarm state is untested with the real model.** No test scene has
  crossed the threshold.

---

## 2026-09-25 — Names drawn onto the model's frames; scene ratings decide intervention (VSH-ARLT-5090)

Two changes asked for by Moe, following the entry below.

**The model reads who is who.** The previous entry left the model with a
list of names and no positions, so with several people in frame a name, and
that person's `gefahr`, could land on the wrong person. Each frame sampled for
the model now carries a tag with the tracker's name above every face:

- `PresenceTracker.name_faces(frame)` runs a pass over that exact frame and
  returns each face's box with its track's label. Running the pass on the
  sampled frame, rather than reusing the tracker's last boxes, keeps every
  tag on its face even when people have moved. Tracks now keep the box of
  their latest sighting.
- Passes are serialised by a lock. The tracker's own thread and the sampling
  loop both run them, and two interleaved passes could each start a track for
  the same new face, putting one person on the roster twice.
- `src/sitrep/annotate.py` draws a yellow box and a white-on-black name tag,
  using Pillow (12.3.0, new dependency). OpenCV's fonts cover ASCII only, and
  a cast name with an umlaut has to appear on the frame exactly as in the
  name list the grammar enforces. Only the model's copy is marked; the NDI
  feed stays clean.
- `capture.windows()` takes an `annotate` hook, applied to each frame before
  encoding. The session passes the tracker's names through it.

Verified on three frames of stage footage with the real tracker and
`gemma4:26b`. Three faces were tagged (`Vielleicht: Sophie`,
`Vielleicht: Matthias`, `Vielleicht: Hedda`), and the report put each name on
the right person: Sophie standing with the glass, Matthias seated and
gesturing, Hedda in the background. A naming pass costs ~150 ms per sampled
frame; the first costs ~10 s, loading the face models. Generation took 5.2 s.

**Scene ratings decide intervention.** The report has a new `szene` with
`relevanz`, `eskalation` and `gefahr`, 0–10 from low to high. It is separate
from the 0–5 ratings per person. The Empfehlung is written only when
`eskalation` or `gefahr` is above 6 (`report.SCHWELLE`):

- `einschreiten` is a computed field of `Lagebericht`, derived from the scene
  ratings. It is absent from the schema the model is given, so the model has
  no field in which to decide it.
- The model is told to write a measure only above the threshold. Any measure
  it writes below the threshold is discarded.
- `empfehlung` is now the measure as a string. The `Empfehlung` model is gone.

OSC: a new `/orest/sitrep/szene <id> <relevanz> <eskalation> <gefahr>`.
`/orest/sitrep/empfehlung` keeps its shape, with `einschreiten` now derived.
`sitrep_meta` in TouchDesigner gains the three scene columns. 271 tests pass.

**Open:**
- **The threshold path is untested live.** The test scene rated eskalation 1
  and gefahr 0. Whether the model writes a usable measure when a scene does
  cross 6 has only been checked in unit tests, which don't run the model.
- **An empty measure above the threshold is possible.** The grammar can't make
  a field required only above 6. If the model leaves it empty, the report
  shows EINSCHREITEN with no action.
- **`menschlich` came back 0 for all three people** in the test run. It may
  be misread as "is not human-like". The category may need a description in
  the prompt, as `relevanz` has.

---

## 2026-09-25 — SITREP fields redefined; the roster names the people in the report (VSH-ARLT-5090)

**Machine:** `VSH-ARLT-5090`, the production workstation: RTX 5090 (32 GB),
i9-14900KF, 128 GB RAM (`hardware_issues.md`, reference machines).

The report's fields were set by Moe. They refine "write SITREP report" in
`knowledge/components/02_processing.md` (Realtime-SITREP) and replace the
`Lagebericht` of 2026-09-09:

| Field | Content |
|---|---|
| `beschreibung` | what happened, who did what, briefly |
| `personen` | `name`, `beschreibung` (how the person comes across), and 0–5 ratings `kollaborativ relevanz verantwortungsvoll menschlich gefahr` |
| `prognose` | exactly three developments, each with a probability in percent, most likely first |
| `empfehlung` | `einschreiten` (bool) and `massnahme`; intervening is instructed to be the exception |

`lage`, `ereignisse`, `vertrauen`, `kennung`, `merkmale` and `taetigkeit` are
gone. `relevanz` is new. `vertrauen` never tracked accuracy
(`claude_concerns.md`, smaller items).

**Names come from the presence roster.** This is the first open increment under
"Cast recognition" in `progress_tracker.md`. `Sitrep` carries the tracker's
roster for its window as a measured field, `anwesend`. The prompt lists it,
and the schema sent to Ollama holds `Person.name` to that list plus
`Unbekannt`. The model therefore picks names it was given and cannot invent
one. So that every person carries a name, **the presence tracker now runs on
every session**, not only with `--cast`: without a cast, every name is a
guess (`Vielleicht: Jakob`).

**The grammar enforces both constraints.** Checked against `gemma4:26b`: asked
to name two people "Anna and Bert", it used only the enumerated names; asked
for one forecast, it returned exactly three. The three forecasts are sorted by
probability in `report.py`, so renderers can take the first one as the most
likely without relying on the model's order. A declined intervention clears
`massnahme`, since models phrase "no action" as an action.

**OSC wire format changed** (`src/sitrep/td.py`): `/orest/sitrep/lage` and
`/ereignis` are replaced by `/beschreibung`, `/prognose <rang>
<wahrscheinlichkeit> <verlauf>` and `/empfehlung <einschreiten> <massnahme>`.
The person row is `<zeile> <name> <vermutet> <beschreibung>` plus the five
ratings. `TouchDesigner/code/sitrep_osc.py` and
`TouchDesigner/2026-09-25_touchdesigner_setup.md` follow: `sitrep_prognose`
replaces `sitrep_ereignisse`. The note of 2026-09-24 that the report and roster
tables must not be joined no longer applies: a report name is a roster label.

**First generation on the production machine.** `gemma4:26b` on three frames
of stage footage with five people in shot, with the new schema: 3.7 s and
4.2 s warm (14.3 s including the model load). The description matched the
frame, including clothing, a glass held and a bearded man with glasses
gesturing. That is the kind of detail e4b invented on the laptop. Three runs,
not a benchmark (`hardware_issues.md`, H-1).

`NUM_PREDICT` rose from 700 to 1000 for the three forecasts. 251 tests pass,
none needing a camera, a model or TouchDesigner.

**Open:**
- **Names are assigned by the model, not measured.** It receives the roster
  without positions, so with several people in frame a name, and that
  person's `gefahr`, can land on the wrong person. In the test run it placed
  the one recognised name on the right man, but it had no way to know.
  *Resolved in the entry above: names are drawn onto the frames.*
- **The intervention threshold is a placeholder.** The prompt says to
  intervene only "wenn die Lage ohne Eingriff eskaliert". What counts as a
  reason to intervene is a dramaturgical decision for Moe. *Resolved in the
  entry above: scene ratings above 6.*
- **Audience members are reported as people.** Background spectators appear
  in `personen` with ratings. Whether they belong in the report is undecided.
- **Probabilities are not required to sum to 100.** The prompt asks for at
  most 100 in total, and nothing checks it.
- The camera on this machine delivered a completely black frame
  (`NDI Webcam Video 1`, no NDI source feeding it), which produced empty
  reports at 0/5 confidence. It is not a fault in Orest, but it is
  indistinguishable from an empty stage in the report.

---

## 2026-09-24 — The live SITREP reaches TouchDesigner: NDI and OSC (MININT-ITT28VU)

**Machine:** `MININT-ITT28VU` (user `ctech`), RTX 4070 Laptop, TouchDesigner
2025.31760 Non-Commercial on the same machine.

The live camera and the generated report now leave Orest for TouchDesigner,
which is step 7 of the Realtime-SITREP in
`knowledge/components/02_processing.md` ("Output: video output ... and SITREP
text beneath it"). The two channels are the ones
`knowledge/components/03_render.md` describes: "OSC carries messages, not
pixels."

    orest-sitrep --send-ndi                      # the camera as an NDI source
    orest-sitrep --send-td                       # report and roster over OSC
    orest-sitrep --send-ndi --send-td --cast data/cast

**Pixels travel as NDI.** `src/sitrep/feed.py` publishes the camera as an NDI
source that TouchDesigner receives with its native NDI In TOP. Spout would have
been the obvious same-machine choice and is what 03_render.md names, but
`SpoutGL` publishes no wheel for CPython 3.14, which this environment runs;
TouchDesigner's Shared Mem In TOP requires a licence above Non-Commercial; and
Video Stream In TOP takes RTSP, HLS/DASH, SRT and WebRTC but not HTTP MJPEG.
`cyndilib` was the one NDI binding with a 3.14 Windows wheel. The NDI runtime
needed no separate install: TouchDesigner ships `Processing.NDI.Lib.x64.dll`.

The transport is one class. `feed.Sink` is opened through `feed.open_sink`, so
TouchDesigner's shared memory, or an ffmpeg process serving SRT, would
substitute without anything above that line changing. **A TouchDesigner licence
upgrade would not change this design**: neither operator used is licence-gated,
and Spout stays blocked by the Python version rather than by the licence.

**Cost: 0.94 ms p50 per frame** at 640x360 on CPU, sending at 30 fps — far
below the 226 ms the presence pass costs. Publishing does not show up in the
report path either: four consecutive windows with NDI running came in at 4.6,
6.5, 5.1 and 6.9 s against a 15 s window, none skipped. Both figures are at the
webcam's default 640x480; a 1080p stage camera is untested.

**Messages travel as OSC**, in the begin/row/end shape `smartsearch/td.py`
established, so one OSC In DAT receives search results and the live SITREP and
routes on the address prefix:

    /orest/sitrep/begin  /sitrep/lage  /sitrep/gesagt
    /orest/sitrep/person /sitrep/ereignis  /sitrep/end
    /orest/presence/begin  /presence/person  /presence/end

`begin` carries the row counts so TouchDesigner can size a table before its
rows arrive. Ratings are read off `report.BEWERTUNGEN` rather than named, so
renaming a category fails a test instead of silently shifting a column in
TouchDesigner. The transcript is sent even when the room was silent, so the
table keeps its shape.

The roster is a second, faster stream rather than a field of the report: a
report arrives once a window while the tracker reads the room twice a second,
and carrying the roster on the report would make "who is on stage now" lag by
up to a whole window. Its `tick` counts upward so a receiver can discard a
reading that arrived out of order.

**One camera, three readers.** `capture.run()` opened and closed its own
`VideoStream`, which is what prevented sharing — and DirectShow refuses a
second process the device, so TouchDesigner cannot open the camera itself.
`capture.windows()` is now the sampling loop over a stream it does not own, and
`run()` is the standalone form that opens one. `src/sitrep/session.py` holds the
camera, the microphone, the presence tracker, the publisher and the OSC sender;
readers are closed before the camera, and a reader that fails to start unwinds
the session rather than stranding the device with no handle to it.
`report.run_live()` is replaced by `report.sitreps(windows)`, which takes the
windows rather than the devices that produce them and is testable without a
camera.

`Session` is also the shape the localhost interface of `02_processing.md` will
need: one object to start, one to stop. Its options are a pydantic model so
that interface receives them as a request body.

**`src/osc/` is a new shared package.** `Sender`, `Message` and the TouchDesigner
host and port moved there from `smartsearch`. There is one TouchDesigner and
one OSC In DAT; two definitions of its address would drift, and the live path
should not have to import the retrieval path to reach it.

**`uv sync` used to remove `rtmlib`**, which `orest_pose` imports to load the
RTMO model, because it was installed by hand with `--no-deps` and was therefore
absent from the lock. It is now declared in the root project, with a uv override
dropping its request for `opencv-contrib-python` — that package ships its own
`cv2` and collides with the pinned `opencv-python`, which is why the manual
install skipped its dependencies. Body search survives a sync now.

**Verified end to end:** two reports with both channels open, on the real
camera and microphone. Latency 8.7 s and 4.7 s against a 15 s window, so the
run keeps pace with the video feed running. TouchDesigner held port 10000
throughout and received the messages directly. 228 tests pass, none of them
needing a camera, a model, NDI or TouchDesigner.

**Open:**
- **The roster path is untested end to end**, because `data/cast` holds no
  enrolment photographs yet. The messages and the stream are unit-tested; what
  has not run is a rehearsal with names in it.
- **Two unjoined views of the same room.** The roster's `label` does not
  correspond to the `Person.kennung` the model assigns in the report; the model
  is still not told who is present. Joining them is the first open increment
  under "Cast recognition" in `progress_tracker.md`. Nothing in TouchDesigner
  should try to join those two tables.
- **NDI cost at 1080p** is untested. The webcam delivers 640x480 by default,
  which is a quarter of the pixels a stage camera will; `--ndi-fps` and
  `--width/--height` are the levers if it bites.
- `03_render.md` names Spout or NDI for live frames without deciding; the
  decision taken here, and why Spout was not available, is recorded in this
  entry for Moe to reconcile into that file.

---

## 2026-09-24 — Presence tracker: `sitrep/presence.py` (MININT-ITT28VU)

**Machine:** `MININT-ITT28VU` (user `ctech`), RTX 4070 Laptop, 8GB VRAM, 32 cores.

`src/sitrep/presence.py` follows every face the camera shows, names the ones
the enrolled cast matches and guesses at the rest. It turns the per-frame recognition of the entry
below into a roster of who was in the room over a stretch of time, which is
what the Realtime-SITREP of `knowledge/components/02_processing.md` needs for
"who is in the scene". The report does not consume the roster yet.

    python -m sitrep.presence --cast data/cast
    python -m sitrep.presence --cast data/cast --recording rehearsal.mp4 --start 4200

**Runs at its own rate, not the window's.** Two passes a second against a
SITREP window that reaches the model every five or ten seconds. A window is far
too sparse to follow a person across, and the tracker also keeps observing
during generation, when capture is otherwise blind (`claude_concerns.md`,
"Coverage gaps between windows"). The source is anything presenting a
`latest()`, which is how `capture.VideoStream` already presents the camera, so
the two share one camera rather than opening it twice.

**Face detection alone, no body detection.** The tracker was designed around
RTMO supplying bodies and face recognition naming them. Measured first: across
the Othello stage footage and the DT Berlin rehearsal, face detection finds
94-100% of the people RTMO's body detection finds. The second model was
dropped, which keeps one model in the live path. This holds for camera-facing
performance and documentary footage, which is all the corpus has; a Probebühne
wide shot with actors turned upstage is untested and is where a body layer
would earn its place.

**Two association cues, and the second one is what makes it work.** A face
close enough to a track's own stored faces joins it, greedily, strongest pair
first. A face the gallery *names* then joins whichever live track already
carries that name. The first cue alone fragmented badly: in a 120-second
replay one actor appeared as three simultaneous `person_02` tracks, because a
person's own frontal and profile views can sit below the link threshold — the
same person across a long stretch drops to 0.39 at the fifth percentile — while
the enrolment holds several angles and recognises both. Live tracks that end up
sharing a name are folded into the earliest of them, which keeps its identifier
and its first sighting.

**Everyone in the room is accounted for, and unknown people are guessed at.**
A face the cast gallery does not match is given an invented German first name
marked as a guess — `Vielleicht: Jakob` — rather than a number, and every
detection reaches the roster on its first sighting. The guess lasts as long as
the track: a person seen again after an absence is guessed at afresh, so the
same face can be Bastian and later Theo. Once the gallery does recognise
someone, the guess gives way to their real name.

An earlier version required three sightings before a track counted as present,
to keep single-frame detections off the roster. Dropped on Moe's instruction:
every person entering has to be recognised by the system.

**Measured on Othello.** Enrolment photographs were cut from the first 20
minutes for 10 of the 12 identities, and the tracker replayed 120 seconds
starting at 70 minutes — footage the enrolment never saw. Two identities were
deliberately left unenrolled, both of them absent from the first 20 minutes.

- No name was ever held by two live tracks at once.
- No track ever changed name.
- Named tracks held for 44-114 seconds and 25-151 sightings.
- 15% of detected faces were guessed at rather than recognised, across 20
  short tracks.
- Every recognised track was checked by eye against its enrolment photographs
  and was the right person. The largest guessed track, 25 sightings of one of
  the two unenrolled actors, held one invented name throughout.

**`face.detect.SCORE_THRESHOLD` is 0.60**, raised from 0.50. Everything the
detector returns becomes a person on the roster, and at 0.50 that included
panels of patterned stage cloth. Over 150 frames the change drops 14 of 341
detections: four panels of scenery, several backs of heads, one actor's face
repeatedly covered by a hand, and one clear profile.

It does not reduce the number of guessed people — twelve at both thresholds —
because removing a weak sighting also splits a track, so single-sighting
guesses rose from six to eight. Recognition is untouched: the same five people
are recognised, with one sighting fewer out of 294. The threshold is the right
lever for scenery, not for phantoms; the lever for those is `FORGET`, which
holds a lone detection on the roster for thirty seconds.

**Cost: 226 ms p50, 320 ms p95 per pass** on a 1080p frame, CPU, at four
inference threads — about a tenth of the machine at two passes a second. What
this costs while Ollama is generating is still untested.

**Replay time is counted from `REPLAY_EPOCH`**, an arbitrary reference far
enough from `datetime.min` that subtracting the forget window cannot underflow.
Counting from `datetime.min` crashed any replay started at the first frame.

`data/cast/` holds the enrolment: one folder per person, named after them,
carrying five to ten photographs. The convention is in `README.md` and in that
folder's own README; `data/` stays untracked, since the photographs are of
identifiable people.

**Next:** wiring the roster into the SITREP. `Window` gains the people seen
during it, `Sitrep` carries them as a measured field beside `quelle` and
`gesagt`, and `Person.kennung` becomes a value the model selects from a fixed
roster rather than one it assigns.

---

## 2026-09-23 — Face recognition: `src/face/`, measured on the corpus (MININT-ITT28VU)

**Machine:** `MININT-ITT28VU` (user `ctech`), RTX 4070 Laptop, 8GB VRAM, 32 cores.

`src/face/` detects faces, embeds them and matches them against an enrolled
cast. This is the identity half of "who is in the scene" in the Realtime-SITREP
of `knowledge/components/02_processing.md`, and the mechanism behind that
file's "provide the system with images of each team member". The SITREP does
not use it yet; this step establishes what it does on footage like the corpus.

    python -m face.gallery data/cast

**Two ONNX models from InsightFace's `buffalo_l`**, run directly rather than
through the `insightface` package: SCRFD-10GF for detection, which returns a
box and the five landmarks alignment needs, and ArcFace R50 for a
512-dimension embedding. `insightface` builds from source on this
environment's Python 3.14 and carries a second numpy stack; the models need
only onnxruntime, numpy and cv2. `buffalo_l` is chosen over the smaller
bundles because WISE's own face extractor uses it
(`knowledge/background/wise_clip_as_query.md`), so a future Hindsight-SITREP
face index would share one embedding space with the live path rather than
two.

The package sits in `src/` beside `sitrep` and `smartsearch`, not in
`wise_ext/`. `orest_pose` lives there because it registers a feature extractor
inside WISE's conda environment; face recognition runs on the live camera
stream and has no such constraint.

**Identity is measured, not generated.** The design follows the separation
already in `src/sitrep/report.py`, where the transcript is Whisper's and the
model may not invent speech. A name will reach the report as a measured field
beside `zeitfenster` and `quelle`, not as something `gemma4:e4b` is asked to
read off a photograph. A person is kept as the set of their enrolled vectors
rather than one average, and a match below threshold is reported as unknown
rather than as the nearest name.

### Measured on the corpus

Two videos, sampled as stills: the characterisation workshop (12 min, 720p,
1582 faces from 365 stills) and Othello (first 2 hours, 1080p, 2173 faces from
900 stills). Ground truth was built by clustering the embeddings and then
confirming every cluster and every merge by eye against contact sheets: 6
identities in the workshop, 12 in Othello.

Recall at 100% precision, enrolling the three largest faces per person:

| | thr 0.30 | thr 0.35 | thr 0.40 | thr 0.45 |
|---|---|---|---|---|
| workshop, 6 people | 0.955 | 0.905 | 0.796 | 0.606 |
| Othello, 12 people | 0.992 | 0.979 | 0.937 | 0.883 |
| Othello, enrolled on close shots, probed on faces under 50px | 0.980 | 0.955 | 0.864 | 0.763 |
| Othello, enrolled in the first 20 min, probed after the first hour | 0.992 | 0.983 | 0.965 | 0.902 |

**No wrong name was produced anywhere in any sweep.** In the last row 149 of
the 811 probes are actors who appear only later and were never enrolled; all
were correctly left unnamed. Stage lighting does not break the match: the same
face under a deep blue wash and under a red wash scores 0.6-0.8.

**Strangers stay unnamed.** Leave-one-person-out, each identity in turn removed
from the gallery: 0 of 2028 Othello probes and 0 of 1212 workshop probes were
given a name at threshold 0.35 or above. Across 60,600 different-person pairs
the highest similarity observed was 0.35, against a same-person median of 0.48
(workshop) and 0.60 (Othello).

**Face size is the limit, not lighting.** Recall at threshold 0.40 by size in
frame: 0.49 under 30px, 0.79-0.82 at 30-40px, 0.90 at 40-60px, 0.98 above
120px. Enrolment count matters about as much: one photograph gives 0.62,
three 0.76, ten 0.86 on the same probes.

Threshold 0.40 is the default in `gallery.THRESHOLD`: it sits above every
different-person pair observed and still names four probes in five. Lowering
it buys recall the measurements say is still free of wrong names, but the
sample is 18 people.

**Caveat on recall.** Ground-truth clusters were formed by this same model, so
faces it embeds oddly are over-represented among those excluded from the
labelled set. The precision figures do not have this problem; they come from
held-out identities.

### ONNX Runtime thread default costs 3.6x on CPU

A detect-and-embed pass over a 1080p frame with 3.6 faces takes **802 ms p50**
at ONNX Runtime's default thread count and **222 ms p50 / 493 ms p95** at four
threads. The default is one thread per core, which on 32 cores costs more in
synchronisation than it wins, and costs more again when two sessions are called
alternately. `face.model.THREADS` caps it at four, overridable with
`OREST_FACE_THREADS`.

Both models run on `CPUExecutionProvider`: ONNX Runtime resolves no CUDA
provider in this environment, the same condition pose detection runs under
(`hardware_issues.md` H-10). `orest_pose` does not pay this penalty: measured
again alongside the face models it runs at 42 ms per frame on CPU at the
default thread count, matching its original figure. The cost appears when two
sessions are called alternately, which pose alone never does.

**Next:** the presence tracker that turns per-frame recognition into a per-
window roster, then wiring that roster into the SITREP prompt and schema.
At 222 ms a pass, a tracker reading the camera at 2 fps fits alongside Whisper
and Ollama; the blocking question is what it costs during generation, which is
untested.

---

## 2026-09-17 — Segment results: `--segments` (MININT-ITT28VU)

**Machine:** `MININT-ITT28VU` (user `ctech`).

`query`, `body` and `body-live` take `--segments`, which returns the indexed
four-second windows in place of merged spans.

    orest-search query "zwei Personen streiten" --segments --send-td
    orest-search body-live --segments --send-td

**Why.** A merged span grows with every neighbouring window that matches, so
where a long stretch of a recording resembles the query — one person, barely
moving, in the webcam test — a single result ran to 122 s, and its bounds
shifted from search to search as different windows matched, so the same moment
was cut to a new clip file each time: 70 of 209 clips overlapped another by
more than 80%, about 1.2 GB. Segment results are always four seconds and always
on the index grid, so a moment found again reuses its clip.

**What WISE sends.** Every result block carries both forms, `merged_windows`
and `unmerged_windows`, with identical fields; `client.py` names them and
picks one. The client's earlier fallback looked for a `vectors` key WISE does
not send. In segment mode one vector is one result, so exactly `limit` vectors
are retrieved rather than ten per wanted moment.

**Live captures do not merge in segment mode.** Windows of one movement
retrieve the same segments, so a segment found by several windows is kept once
with its best score, and neighbouring segments are left separate; joining them
would rebuild the long spans.

**Granularity differs by index.** The text index holds one vector per frame at
2 fps, and its windows sit half a second apart, so a strongly matching moment
yields several near-identical results (567.0–571.0 and 567.5–571.5). The pose
index is segment-level and steps by two seconds.

**Verified** against the served corpus: `"a person kneeling on the floor"`
returns the same top moments in both modes with identical scores, as
four-second windows in segment mode; cutting the top three twice produced three
clip files, not six. 137 tests pass.

**Left open, on Moe's decision:** a maximum clip length for merged results.
Whether merged spans need capping, and at what length, is to be judged once the
system is used in rehearsal. Scores also rise with the length of a live
capture, since the best score over all its windows is kept; a threshold in
TouchDesigner must allow for this.

---

## 2026-09-17 — Smart Search phase 3: search by a movement performed live (MININT-ITT28VU)

**Machine:** `MININT-ITT28VU` (user `ctech`), RTX 4070 Laptop, 8GB VRAM.

A movement performed in front of a camera is the query. A start press and a
stop press bracket the capture, and the results reach TouchDesigner like any
other search. This is embodied search, "body", in
`knowledge/components/02_processing.md` ("press a button, then press a button
again after a few seconds to capture that live sequence") and the
`QB["BODY SEARCH"] → ENC["Live encoder"]` path of the RENDER graph in
`knowledge/source_of_truth/pipeline.md`.

    orest-search body-live --send-td
    orest-search body-live --video "FHD WebCam" --per-file 2 --send-td
    orest-search body-live --file <recording.mp4> --at 300

**Presses** come from the terminal (Enter toggles) and over OSC,
`/orest/body/start` and `/orest/body/stop` on `127.0.0.1:10001` — the return
channel from TouchDesigner or QLab drafted in `knowledge/components/03_render.md`.
A start while capturing or a stop while idle is ignored, so a doubled button
press neither cuts a capture short nor searches with nothing.

**Bodies are detected while the movement happens.** `smartsearch.live` samples
the camera at the index's rate, four frames a second, detects poses immediately
and keeps only keypoints. Detection runs on the CPU in Orest's environment at
42–45 ms per frame whatever the resolution, since RTMO letterboxes to 640 px:
under a fifth of the sampling interval. A capture of any length costs next to no
memory, and its query is ready when the stop press arrives. If detection ever
falls behind the sampling interval it is reported, since the movement would
then be spread over fewer frames than the index expects.

**A capture is searched in the shape of the index.** Indexed segments are 16
frames over four seconds, stepped by two, and a query of a different length
describes a differently paced movement. A capture is therefore cut into
four-second windows stepped by two seconds, the last aligned to the end of the
capture, and each window is searched on its own. A capture shorter than four
seconds is extended backwards from the stop press to a full segment, which is
how the index saw a short movement. Windows with no body are skipped. Results
from the windows are merged: overlapping hits in one recording become one hit
spanning both, with the better score.

**`--per-file N`** keeps at most N results from any one recording, retrieving
five times as many candidates so the list still fills. This is the result cap
`progress_tracker.md` placed in this phase; excluding the recent past is not
implemented, as the offline index holds nothing from the session being
captured.

**`--file`** plays a recording in real time in place of the camera, so the
workflow can be rehearsed and tested on footage whose content is known.

**Verified** against the served corpus, with presses sent over OSC and the
workshop and 4K Theaterprobe recordings played through `--file`:

| Capture | Rank 1 | Score | Next |
|---|---|---|---|
| 4.2 s, workshop 133.7–137.9 s, 2 windows | its own span, 132–165.75 s | 0.931 | 0.570 |
| 10.0 s, workshop 139.8–149.9 s, 5 windows | its own span, 134–165.75 s | 0.982 | 0.612 |
| 6.1 s, Theaterprobe crawl 300.6–306.7 s, 3 windows | its own span, 284–335.75 s | 0.929 | 0.674 |

From the stop press to the result table took 0.23 s, and to the first clip
announced 0.64 s. `--per-file 2` held the Theaterprobe capture to two results
per recording. 4K VP9 playback kept real time and detection never fell behind.
130 tests pass, 22 of them new, needing no camera, model, server or
TouchDesigner.

**Open:** the camera itself is untested in this path — `--file` exercised
everything but `sitrep.capture.VideoStream`, which the SITREP already uses.
Merged spans are long (51 s for a 6 s capture), carried over from phase 2's
overlap merge into clip length.

---

## 2026-09-17 — Search results reach TouchDesigner: clip cutting and OSC (MININT-ITT28VU)

**Machine:** `MININT-ITT28VU` (user `ctech`), RTX 4070 Laptop, 8GB VRAM;
TouchDesigner Non-Commercial on the same machine.

A search result becomes a clip file and an OSC message, so TouchDesigner can
play what Orest finds. This is the `HITS → CUT` node of the RENDER graph in
`knowledge/source_of_truth/pipeline.md` and "Results are piped into
TouchDesigner" in `knowledge/components/02_processing.md`, following the
interface drafted in `knowledge/components/03_render.md`.

    orest-search query "zwei Personen streiten" --send-td
    orest-search query "zwei Personen streiten" --cut precise --send-td
    orest-search body <clip.mp4> --at 90 --send-td

**Two cutting modes** in `smartsearch.clips`, both cutting exactly the range
WISE returned:

| | fast (default with `--send-td`) | precise |
|---|---|---|
| Method | stream copy | re-encode to H.264, `libx264 veryfast` |
| 8 s, Othello 1080p H.264 | 0.12 s, 2.7 MB | 1.15 s, 3.0 MB |
| 8 s, Theaterprobe 4K VP9 | 0.09 s, 9.3 MB | 3.53 s, 10.8 MB |
| Picture | recording's own codec and resolution | H.264, yuv420p |

`h264_nvenc` cuts precise clips in about 70% of the time (`--encoder`);
libx264 is the default because during a performance the GPU holds live pose
encoding and Whisper. Intermediate codecs cost far more space for no gain here:
DNxHD at 1080p was 117 MB for the same 8 s.

**Fast clips carry pre-roll, reported in every hit message.** Stream copy can
only begin at a keyframe, and Othello's keyframes are 0.5–10 s apart. ffmpeg
keeps the frames from that keyframe with negative timestamps and writes an MP4
edit list hiding them: through ffmpeg, a clip cut at 2100 s shows a first frame
pixel-identical to the source at 2100 s. **TouchDesigner ignores the edit
list** and starts at the keyframe: `data/td_test/copy_cut_at_13s.mp4`, a fast
cut at 13 s from a timecode source with keyframes every 5 s, shows 00:00:10 as
its first frame. Each clip's pre-roll is therefore read back from its first
video packet with ffprobe (about 0.07 s) and sent as `preroll`, for
TouchDesigner to trim. It matched the source's keyframe gaps exactly (3.000 s on
the test clip, 0.458 s and 0.958 s on Othello) and is 0 for precise clips.

    /orest/results/begin  <query_id> <count>
    /orest/results/hit    <query_id> <rank> <clip_path> <ts> <te> <score> <source_file> <preroll>
    /orest/results/end    <query_id>

**Clips are read through WISE's media route**, not from disk. WISE's API does
not expose source paths, but it serves byte ranges, which ffmpeg seeks with.
Against local disk this costs under 0.1 s per clip and gives byte-identical
output, and nothing about where recordings live has to be configured on the
theatre machine. The WISE server must therefore be running to cut clips.

**Delivery.** Clips go to `data/clips/<project>/`, named from media id,
recording, range and mode, so a moment found again reuses its clip. ffmpeg
writes to a `.part` name that is renamed on completion, so an interrupted cut
is never taken for a finished clip. Clips are cut in rank order and each is
announced by `smartsearch.td` as soon as it is written, between a begin and an
end message carrying a per-search id. Paths are absolute with forward slashes.
Orest sends every result; how many are used is decided in TouchDesigner
(`03_render.md`, "How many results reach the stage"). OSC goes to
`127.0.0.1:10000` by default.

ffmpeg 6.1.2 (GPL) is taken from the `wise` conda environment, found the same
way as `wise.exe`. `python-osc` 1.10.2 was added to the `orest` project.

**Verified end to end** against the served corpus with a stand-in OSC receiver
on port 10000. `"two people arguing on a stage"`, five results: fast clips cut
and announced in 1.1 s including search and process start; precise in 8.0 s,
the five hit messages arriving 1.1–2.5 s apart in rank order; a repeated
search reused all five clips in 0.5 s. Clip durations match the hit ranges
(precise exact, fast within 0.12 s). First frames were compared with the source
at the hit start: fast clips pixel-identical, precise clips within
re-encoding loss and closer to the source frame at the hit start than to either
neighbour. Pre-roll arrived on every hit, 0.46–2.0 s on fast clips and 0 on
precise ones. In TouchDesigner, an OSC In DAT callback filling a results table
and a Movie File In TOP reading from it play fast VP9, fast H.264 and precise
H.264 clips, and two simultaneous players are stable. 108 tests pass, 24 of
them new, needing neither ffmpeg, the WISE server nor TouchDesigner.

**Open:**
- Trimming `preroll` on the Movie File In TOP is not yet verified; on the test
  clip the first frame should then read 00:00:13.
- TouchDesigner stops responding while the network is edited with several
  players loaded, on the laptop's Non-Commercial licence. Not investigated
  before the production workstation.
- HAP is not in the `wise` environment's ffmpeg build.
- Simultaneous H.264 playback capacity in TouchDesigner is unmeasured, and the
  Non-Commercial licence caps resolution, so the laptop is a lower bound.

---

## 2026-09-11 — Pose index built over the full corpus (MININT-ITT28VU)

**Machine:** `MININT-ITT28VU` (user `ctech`), RTX 4070 Laptop, 8GB VRAM.

The 4h08m test corpus is searchable by body movement.
`orest/pose/rtmo-s/body7` holds **7,439 vectors**, one per four-second segment,
and each file is covered end to end:

| File | Vectors | Covers |
|---|---|---|
| Othello 2022 (1080p) | 6,503 | 0 – 13,007 s of 13,007 s |
| Rehearsal Techniques workshop | 364 | 0 – 729 s of 729 s |
| Theaterprobe DT Berlin (4K) | 572 | 0 – 1,145 s of 1,146 s |

Extraction took **6,513 s (108.5 min)**. The pose store is 31 MB, about 7.5 MB
per hour of footage — small beside the 75 MB/h of thumbnails. The index built
in under a second. No thumbnail was duplicated.

**The 4K file sets the pace.** Throughput held at about 1.3 segments/s through
the two 1080p-and-smaller files and fell to about 0.35 segments/s on the 4K
recording, with the GPU idle and CPU at 7–12%. Pose extraction is decode-bound
like the stock extractors (`hardware_issues.md` H-3), and a 4K stream costs
roughly four times as much to decode per segment.

**Verified across files**, with a clip from the corpus as the query:

| Query | Rank 1 | Score | Next |
|---|---|---|---|
| Dancer on the floor, arm raised (Theaterprobe 1008 s) | its own segment, 1008 s | 0.796 | 0.545 |
| Crawling toward the camera (Theaterprobe 300 s) | its own span, 286–314 s | 0.973 | 0.648 |
| Two actors, one seated (Othello 2093 s) | another moment, 4330 s | 0.970 | 0.966, its own segment |

Distinctive movement discriminates clearly, with margins of 0.25 to 0.33 over
the next result. **Ordinary stage posture barely discriminates at all:** the
Othello query's top six all fall between 0.959 and 0.970, with the source at
rank 2. The likely reason is the one
`knowledge/background/agent_session_notes/bloom-wise-architecture.md` predicts
for any pose archive — a body standing or sitting on stage is the most common
thing in it, and one standing body looks much like another. Indexing only the
largest body in frame adds to it, since in a two-hander that is usually whoever
is standing nearest.

**The first full attempt died silently and the cause is not known.** It stopped
after 2,169 segments and 26 minutes, with no traceback, no Windows crash record
and no sleep transition; the "exit code 0" it reported belonged to the `grep` at
the end of the pipeline. Ruled out: memory growth in pose inference (flat over
400 frames) and in the decoder (flat over 900 segments), a decode failure at
that point in the file, and a truncating break condition in WISE's segment
loop. The second attempt, run with the true exit code captured, completed
cleanly. Until a failure reproduces, long runs should be started without a
pipeline so the exit status is WISE's own.

---

## 2026-09-11 — Pose detection on the GPU, and a thumbnail bug of ours (MININT-ITT28VU)

**Machine:** `MININT-ITT28VU` (user `ctech`), RTX 4070 Laptop, 8GB VRAM.

Pose detection runs on the GPU at **9 ms/frame** against 43 ms on CPU. Indexing
the corpus went from an estimated four hours to a measured **108.5 minutes**, of
which the GPU is only part: the larger single win was stopping `add-extractor`
from regenerating thumbnails.

**Three stacked causes kept ONNX Runtime on CPU**, each hiding the next.

1. `onnxruntime` and `onnxruntime-gpu` were both installed. They share a module
   name and overwrite each other; the CPU build's binding won, so no CUDA
   provider was offered.
2. With only `onnxruntime-gpu` 1.29 installed, the provider appeared in the list
   and then failed at session creation: it requires **CUDA 13**, and this
   machine has CUDA 12.8 from torch. **A listed provider is not a working one** —
   it degrades to CPU silently. Fixed by `onnxruntime-gpu==1.22.0`, the newest
   CUDA 12 line.
3. The CUDA 12 libraries were not on `PATH`. ONNX Runtime loads its CUDA
   provider as a separate DLL whose own dependencies the Windows loader resolves
   against `PATH` only; `os.add_dll_directory()` does not cover that hop. The
   same defeat CTranslate2 shows in `sitrep/transcribe.py`.

`orest_pose.model` now prepends torch's `lib` directory to `PATH`, where a
complete CUDA 12 runtime already sits, so nothing extra was downloaded. It also
reports the provider the session actually got and warns when CUDA was asked for
and not granted, because the failure is otherwise invisible.
`coloredlogs` was added, a declared dependency of `onnxruntime-gpu`.

**`add-extractor` was regenerating thumbnails.** Thumbnails are keyed by media
and timestamp rather than by extractor, so adding a second model to an existing
project decoded them all again and appended a duplicate set — 1,838 duplicate
rows in the probe, more than doubling `thumbs.db` to 33 MB. It now passes
`--no-thumbnails`, and the duplicates in both projects were deleted.

**Where the time actually goes**, measured over 20 segments of the corpus:

| | Per 4-second segment |
|---|---|
| Decode | 498 ms |
| Pose inference on GPU | 247 ms |
| Tensor conversion | under 1 ms |

Extraction is decode-bound even for pose, so the 4.8x gain on inference becomes
about 1.6x on the pipeline. The indexed segments overlap by half, so every frame
is decoded twice; removing the overlap would halve the work and is the next
lever if this needs to be faster, at the cost of splitting movements that
straddle a boundary.

**This arrangement is fragile in a specific way.** Upgrading `onnxruntime-gpu`,
or moving torch to a different CUDA line, silently returns pose to CPU with only
a warning. `hardware_issues.md` H-10 records what to re-check.

---

## 2026-09-11 — Smart Search phase 2: search by body movement (MININT-ITT28VU)

**Machine:** `MININT-ITT28VU` (user `ctech`), RTX 4070 Laptop, 8GB VRAM.

A second index describes what bodies do rather than what a scene looks like, so
a few seconds of movement can be the query. This is the "body" half of embodied
search in `knowledge/components/02_processing.md` and the `QB["BODY SEARCH"]`
node of `knowledge/source_of_truth/pipeline.md`.

    orest-search add-extractor --project P --video-id orest/pose/rtmo-s/body7
    orest-search index --project P
    orest-search body <clip.mp4> --at 134 --project P

**One encoder, installed in both environments.** `wise_ext/` holds the
`orest_pose` package: RTMO keypoint detection and the embedding, in pure numpy
with no declared dependencies. WISE's environment imports it to build the index,
Orest's imports it to encode a live query. A query encoded even slightly
differently from the index lands in a different space and retrieves nothing, so
there is one implementation rather than two. It installs with `--no-deps` in
both: `rtmlib` pulls `opencv-contrib-python`, which would add a second
conflicting `cv2` and lift numpy over the `numpy<2` ceiling that MS CLAP holds
in the `wise` environment.

**The embedding is a movement, not a posture.** Sixteen frames spanning four
seconds, each skeleton centred on the hip midpoint and scaled by torso length,
concatenated and L2-normalised into 544 dimensions. Centring and scaling are
what make the same action match whether it happens upstage or down, near the
camera or far from it. Torso length rather than bounding box: a raised arm
enlarges the box but not the body, and would otherwise rescale the whole
skeleton. Four seconds at 4 fps separates a fall from a slow descent, which the
2 fps the Qwen entries use blurs together.

**Only the largest body in each frame is indexed.** WISE stores one vector per
segment, so one skeleton has to stand for the frame. Everyone else in shot is
dropped. This is the main known limitation and the natural next increment.

**Registered through WISE's documented extension point**, a hardcoded prefix
chain in the feature extractor factory, as
`0006-register-orest-pose-extractor.patch`. Only the two registration lines are
patched; the extractor itself stays in this repository.

**No WISE patch is needed to query it.** WISE decodes every visual query as a
still image and cannot embed a clip, but `/search_with_feature` accepts a
finished vector, so Orest runs the same encoder on the query clip and posts the
result. This is why clip-as-query left the critical path.

**Measured** on the 12-minute probe:

| | |
|---|---|
| Pose detection, RTMO-s on CPU | 43 ms/frame |
| Indexing | 364 segments in 7.2 min, 1.2 s/segment |
| Embedding | 544 dimensions, unit length |

Those are CPU figures. Pose moved to the GPU later the same day and the
thumbnail waste described in the entry above was removed; see that entry for
the numbers that now apply.

**Verified.** Self-retrieval: a clip taken from the corpus at 134s returns the
span containing 134s at rank 1, scoring 0.942 against 0.504 for the next
result; the same at 400s returns its own span at 0.928. On held-out clips the
embedding separates movements — two samples of one crawl score 0.77 against each
other and 0.01 to 0.11 against a different action. Detection was checked by eye
on rendered skeletons: correct on a floor posture under a single spotlight, two
bodies resolved on a wide outdoor stage shot, and limb confusion on an extreme
foreshortened crawl toward the camera. 84 tests pass, 11 of them new, needing
neither model nor video.

**Known behaviour:** because indexed segments overlap by half, a run of matching
segments merges into a long span — a four-second query can return a
thirty-second result. The merge is correct for browsing; a precise mode would
read the unmerged windows instead.

---

## 2026-09-11 — Video playback in WISE is 66x faster (MININT-ITT28VU)

Found by Moe browsing the indexed corpus: clicking between segments of a long
video took a long time to load.

`send_bytes_range_requests()` streamed media in **10 KB** chunks. Each chunk is
one message through the ASGI send path, which costs roughly 830 microseconds
against a read that costs nothing, so throughput was governed by the chunk size
and not by the disk. Raised to 1 MB in
`knowledge/source_of_truth/wise-patches/0005-media-streaming-chunk-size.patch`.

Measured on `Othello 2022.mp4` (4.29 GB), serving a range from the two-billionth
byte:

| | Before | After |
|---|---|---|
| Bounded 8 MB range | 12 MB/s | 811 MB/s |
| Open-ended range to end of file (2.29 GB) | ~190s | 1.4s |
| Raw disk read of the same region, for reference | 2,617 MB/s | |

The open-ended case is the one that was felt. Browsers request video as
`Range: bytes=N-`, so every seek made the server stream from the seek point to
the end of the file; the client aborts once buffered, which is the
`ConnectionResetError [WinError 10054]` that accompanied it. At 12 MB/s that was
over three minutes of streaming per seek on the Othello recording, and it
compounded as seeks stacked up. The error itself is normal for range requests
and is unchanged.

**Not fixed, and left deliberately:** the high-resolution still view raises
`AttributeError: 'list' object has no attribute 'keys'` on every modal open.
`WiseProject.thumbnail()` passes `AVDataset` a list of paths where it now
expects a map of media id to path, and the line after reads `chunks["video"]`
with a string key on an enum-keyed dictionary — the same defect class as patch
0004. The path has not worked since that refactor. The frontend's `onerror`
handler falls back to the stored thumbnail, so the cost is a soft preview image
rather than a crisp one. See `claude_concerns.md`.

---

## 2026-09-11 — Smart Search phase 1: WISE driven from Orest, sample corpus indexed (MININT-ITT28VU)

**Machine:** `MININT-ITT28VU` (user `ctech`), RTX 4070 Laptop, 8GB VRAM.

`src/smartsearch/` is an installed package that builds, serves and queries a
WISE search index from the `orest` environment. It implements the "Process
rehearsal footage from folder on computer" and "Feature embedding that WISE
offers out of the box" points of the Smart Search affordance in
`knowledge/components/02_processing.md`, and fills the
`IDX[("Search index")]` node of `knowledge/source_of_truth/pipeline.md`. The
4h08m test corpus is indexed and searchable by text over both picture and sound.

The roadmap for the rest of Smart Search — clip-as-query, embodied search, the
pose extractor, speech, the localhost UI — is in `progress_tracker.md`.

    orest-search extract --project rehearsals --media <folder>
    orest-search index --project rehearsals
    orest-search serve --project rehearsals
    orest-search query "zwei Personen streiten" --project rehearsals
    orest-search query "applause" --project rehearsals --target av

**Two processes, one HTTP boundary.** WISE keeps its own conda environment,
whose torch stack is pinned under `numpy<2` by MS CLAP, and is never imported.
Batch operations go through its command line as a subprocess; retrieval goes
through its REST API. `wise_cli.py` builds each command line as a pure function
and runs it separately, so argument lists are testable without a subprocess, and
every batch run is written to `data/logs/` as well as the terminal.

**WISE is invoked as the console script in its environment, without activating
it.** `<conda>/envs/wise/Scripts/wise.exe` resolves torch and CUDA from its own
site-packages; `conda run` is not needed and starts 2.4x slower (6.9s against
2.9s). `config.executable()` finds it by `OREST_WISE_EXE`, then `PATH`, then the
standard conda prefixes. Every other location is overridable the same way, since
the Probebuehne machine is not this one.

**Projects live in `data/wise-projects/`, not under `external/`.** Everything
below `external/` is lost whenever `external/wise` is re-cloned to reapply the
Windows patches, and an index over a season is expensive to rebuild.

**Thumbnails were never written by WISE, and now are.** The extraction loop
looks the thumbnail chunk up under the string `"thumbnails"` in a dictionary
keyed by the `MediaChunkType` enum, so the branch could not fire and
`--thumbnails` had no effect. Saved as
`knowledge/source_of_truth/wise-patches/0004-thumbnails-enum-key.patch` and
listed in `versions.md`. A second thumbnail defect is left alone: the on-demand
high-resolution route raises `AttributeError: 'list' object has no attribute
'keys'`. Both are upstream at `fcfa443` and neither is Windows-specific — see
`claude_concerns.md` for why the first had to be fixed before indexing.

**A search returns moments, not frames.** WISE ranks one vector per sampled
frame and merges neighbouring hits into playable segments afterwards, so
requesting five results returned one: the top five frames were all the same
moment. `client.py` treats `limit` as the number of moments wanted and retrieves
ten vectors per moment to fill it, measured at roughly seven vectors per moment
on this footage. A search response is flattened into one ranked list of `Hit`
regardless of which modality block it arrived in, which is the type the planned
UI, OSC bridge and hybrid ranking all consume.

**Corpus indexed** (`Desktop/moritz/test_data_orest`, 3 files, 4h08m01s, 5.0GB):

| | Count | Rate |
|---|---|---|
| Video vectors (SigLIP2-512, 2 fps) | 29,763 | exactly duration x 2 |
| Audio vectors (MS CLAP) | 3,719 | one per 4.0s |
| Thumbnails | 29,763 | one per indexed frame |
| Extraction wall time | 2,254s (37.6 min) | 6.6x realtime |
| Index build (`IndexFlatIP`, both) | under 1s | |
| Project on disk | 525 MB | ~127 MB per hour of footage |

Extraction is decode-bound rather than GPU-bound: the process held about two
cores busy while the GPU idled between batches, and the 12-minute probe ran at
8.4x realtime against 6.6x for the corpus, whose largest file is 4K.

**The segment-level visual index is deferred and the roadmap is reordered.**
`hf/Qwen/Qwen3-VL-Embedding/2B` runs at **55 s per 8-second segment** on this
GPU with VRAM at 7,862 MiB of 8,188 — 13.6x slower than realtime, which is 2.7
hours for the 12-minute probe and ~56 hours for the corpus. SigLIP2 indexed the
same probe in 87 s. The run was stopped after 17 segments, with the rate still
rising; the 4.0 GB of weights stay cached for a re-test on better hardware.

The custom pose extractor therefore moves ahead of it as the body-search route,
and the clip-as-query patch leaves the critical path: a pose embedding can be
computed in Orest and submitted to `/search_with_feature`, so no WISE patch is
needed for live body queries. `progress_tracker.md` carries the new order.

This is the second model rejected for VRAM on this machine after
`gemma4:12b-it-qat`. Hardware-dependent limits are now collected in
`hardware_issues.md`, to be worked through in one pass once the production
machine is decided.

**Verified end to end.** `"a person kneeling on the floor"` returns five
moments, all from the rehearsal recording rather than the staged Othello;
`"two people arguing on a stage"` returns Othello and clusters around 34-36
minutes; `"applause"` on the audio index puts 2:52:08 of Othello first, near the
end of the performance. Querying with a frame taken from 36:20 returns 36:20 as
its own top hit at 88.6, and a vector pulled back out of the index through
`/vectors` and resubmitted to `/search_with_feature` retrieves its own segment —
the escape hatch that later phases need for embeddings computed outside WISE.
Thumbnails serve as 342x192 JPEGs. 73 tests pass, 23 of them new, none needing a
GPU, camera or server.

---

## 2026-09-10 — Live SITREP records nothing (MININT-ITT28VU)

**Machine:** `MININT-ITT28VU` (user `ctech`).

The Realtime-SITREP streams in and streams out. `report.run_live()` yields
each report to whatever consumes it and keeps no copy; `main.py` prints it and
drops it. The `--log` option and `report.new_log_path()` are gone, and nothing
in the real-time path opens a file. Capture already held frames and audio in
memory only, so the whole live path is now non-recording.

`data/sitrep/` is deleted — nine `.jsonl` report logs, plus six session
folders holding 37 JPEG frames and 12 WAV clips written by a capture version
predating the in-memory design. 6.7 MB, none of it tracked by git.

**This diverges from the specification.**
`knowledge/components/02_processing.md` line 18 (Realtime-SITREP,
implementation steps) still asks to "write log file, but not necessary to
time-sync with footage. Choice moments can be extracted if desired." Recording
was removed on Moe's instruction; the Source of Truth is left untouched for
him to reconcile.

Note this concerns the real-time path only. The recorder feeding the rehearsal
database is a separate node in `knowledge/source_of_truth/pipeline.md` (REC →
local storage) and is unaffected, as is the Hindsight-SITREP, which works from
recorded footage by definition.

**Verified:** two live windows end to end; the repository and `data/` are
byte-identical afterwards, and `data/sitrep/` is not recreated.
`tests/test_report.py` asserts that a `run_live()` session leaves an empty
directory behind. 50 tests pass.

---

## 2026-09-10 — SITREP refactor: package layout, typed report, test suite (MININT-ITT28VU)

**Machine:** `MININT-ITT28VU` (user `ctech`), RTX 4070 Laptop, 8GB VRAM.

`src/sitrep/` is an installed package with one console entry point, a typed
report document and a test suite. What the SITREP observes and reports is
unchanged. The package layout is what the OSC and Hindsight-SITREP work in
`knowledge/components/02_processing.md` needs, since both import this code
rather than run it as a script.

**Package.** `src/sitrep/` installs into the `orest` environment
(`[build-system]` and `[project.scripts]` in `pyproject.toml`), and its
modules import each other relatively. The entry point is `orest-sitrep`, or
`python -m sitrep.<module>` for the per-module diagnostics; **`python
src/sitrep/main.py` no longer works** and the READMEs and docstrings name the
new commands. `pydantic` is now a declared dependency, pytest sits in a `dev`
group, and `requires-python` is `>=3.12` — at that bound the lock resolves to
identical versions of all 42 packages.

**One entry point.** `main.py` is the only runner; `report.py`'s duplicate CLI
is replaced by `orest-sitrep --json`. Source, timing and resolution arguments
are defined once in the new `cli.py` and attached as parser parents. The
default sampling interval is 10s everywhere — `capture.py`'s standalone CLI
used 5s.

**Typed SITREP.** `report.Sitrep` carries the model's `Lagebericht` as a
nested field beside the measured `zeitfenster`, `quelle`, `gesagt` and
`latenz_s`, rather than flattening it into a dict where a generated field
could displace a measured one. **The log line changes shape: `bericht` is now
a nested object.** `main.py` renders from attributes, and the rating
categories come from `Person`'s fields instead of being restated.

**Device selection.** A host API publishing no default input device
(PortAudio answers -1) is reported with the candidate list, rather than
falling through to whichever device enumerates first — on this machine a
virtual cable sits ahead of the microphone array. Entry points resolve and
print their sources; `capture.run()` and `report.run_live()` take resolved
devices and print nothing.

**Benchmark.** Reports coverage — W/(W+p95), the share of rehearsal actually
observed — per configuration, and recommends the configuration with the best
coverage. It previously recommended the smallest sustainable window, which is
the worst coverage among those that keep up and contradicts the 2026-09-09
entry and `claude_concerns.md` §3. Frame counts come from
`capture.frames_per_window()`, shared with the capture loop.

**Smaller changes.** The sampling loop sleeps until the next sample instead of
polling every 10ms; `main._wrap()` is `textwrap.wrap()`; window times are
formatted from datetimes rather than sliced out of ISO strings;
`transcribe.py` applies its cuBLAS `PATH` fix on first model use rather than
at import; `report.Analyse` is gone, its latency field having never been read.
The five committed `.pyc` files under `src/sitrep/__pycache__/` are untracked.

**Tests.** `tests/` covers device resolution, the audio ring, WAV encoding,
the sampling loop against a fake camera, the report schema and the console
block — 50 tests, no camera, microphone or GPU required: `uv run pytest`.

**Verified:** live end to end — one 10s window, 2 frames, Whisper on GPU,
`gemma4:e4b`, 8.3s latency, console block rendered and the JSONL line
re-validating as a `Sitrep`. `uv pip check` clean across 42 packages.

**Note for `claude_concerns.md` §1:** in that run Whisper returned "Vielen
Dank." from an empty, silent room despite `vad_filter=True` — the phantom-text
failure `transcribe.py` documents, which the filter was meant to prevent — and
the model built an event from it, "P-01 spricht: Vielen Dank."

---

## 2026-09-10 — Live SITREP step 4: Whisper transcription replaces audio input (MININT-ITT28VU)

**Machine:** `MININT-ITT28VU` (user `ctech`), RTX 4070 Laptop, 8GB VRAM.

Added `src/sitrep/transcribe.py`, implementing step 4 of the Realtime-SITREP
steps in `knowledge/components/02_processing.md` ("Transcribe everything that
is said"). Speaker diarisation is not implemented.

Gemma no longer receives audio. Each window's audio is transcribed with
faster-whisper; `report.py` gives the model the transcript as text and writes
it into the report verbatim as `gesagt`, which was removed from the model's
schema. Given audio directly, e4b had invented speeches, a play title and
ambient sounds; a transcript it merely reads cannot be embellished that way.

Design points:
- `large-v3-turbo`, German fixed, greedy decoding: 02_processing.md asks the
  Realtime-SITREP to prioritise latency over accuracy, and turbo covers German
  where the distil models do not.
- The voice-activity filter is required. On room tone, turbo with German fixed
  transcribed "Vielen Dank." without it, and nothing with it.
- GPU inference needs cuBLAS, added as the `nvidia-cublas-cu12` wheel.
  CTranslate2 finds it only via `PATH` — `os.add_dll_directory()` still fails
  with `cublas64_12.dll is not found` — so `transcribe.py` prepends the wheel's
  `bin` directory to `PATH` on import.
- `capture.clip_for_encoder()` was removed: the 30-second boundary bug lived in
  Gemma's audio encoder, which no longer receives audio.
- `benchmark.py` times transcription and generation separately and takes the
  speech recording as a required `--speech` argument, since the bundled sample
  in `src/data/` was deleted and room tone would understate transcription cost.

**Verified:** the encoder runs on CUDA (0.20s warm); Whisper and Gemma resident
together use 5.8 of 8.2GB; live end to end, a 15s window reports in 5.8s (the
first window 14.3s, including model loads). Real German speech was transcribed
and written verbatim, with some names misheard ("Dona Haraway").

**Open:** the model now attributes transcript content to whoever is on camera —
see `claude_concerns.md`, concern 1. Latency across window sizes has not been
re-measured with transcription in the loop, pending a speech recording for
`--speech`.

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
report format is the `Lagebericht` schema in `report.py`.

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
