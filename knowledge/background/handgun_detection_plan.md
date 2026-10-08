# Plan: handgun detection in the live SITREP

## Context

`knowledge/components/02_processing.md:25` (Realtime-SITREP) says: "The system
should recognize whether someone is holding a handgun. TBD how this effects the
scene." Moe wants reliable detection first. How a detection affects the scene
(Risiko, the alarm, the Empfehlung, OSC to TouchDesigner) is out of scope. A
detection is shown to the operator and logged, and nothing else.

Moe decided three things for this plan:
- The production uses **realistic prop pistols**, and they can be filmed on the
  Probebühne camera.
- The detector is **fine-tuned on our own footage**, starting from public data.
- **Permissive licences only** (Apache, MIT, CC-BY). That rules out Ultralytics
  YOLO (AGPL) and research-only datasets.

Nothing in Apollon detects this now:
- COCO detectors have no gun class.
- NTU120 class 110, "shoot at other person with a gun" (`src/action/sitrep_map.csv`),
  is a pose pattern, not an object. It fires on the gesture without a gun and
  misses a gun held lowered.

## Approach

### What "holding" means, technically

A handgun is about 0.1 of body height, so at the back of the stage it is
20–40 px in a 1080p frame. Searching the whole frame for an object that small
is the main source of misses and false alarms. Apollon already tracks up to
four bodies with wrists (RTMO body7, COCO-17: wrists 9/10, elbows 7/8;
`src/action/tracking.py` `Body`). So the detector looks only where a held gun
can be:

- **Hand crops.** For each wrist of each `recognizer.tallest(frame)` body:
  - centre: the wrist moved 0.25 × forearm along elbow→wrist, toward where a
    gripped pistol lies
  - side: about 0.4 × body height
  - taken from the full-resolution frame and resized to the detector input
  - skipped if the wrist score is below `tracking.VISIBLE`
- **Holding** means a handgun detected in a hand crop. The body's track id
  attributes it, so it works for an unnamed "Körper" too.
- Not covered: a gun whose hand pose has lost, and a gun lying on a table or in
  a holster. The evaluation measures the first of these (see below).

### Detector

**RF-DETR (Roboflow), the Apache-2.0 sizes**:
- one class, `handgun`
- fine-tuned with the `rfdetr` package, which exports ONNX
- runs through onnxruntime-gpu like every live model (`action/model.providers()`)
- No torch enters the project venv (Python 3.14). Training and export run in a
  throwaway uv environment, as `src/scripts/export_osnet.py` does.
- Training needs torch with CUDA 12.8 (≥ 2.7), since the RTX 5090 is sm_120.
- The licence of the chosen size is checked at download and recorded in
  `SOURCE.md`.
- The size (Nano, Small or Medium) is chosen by the evaluation: the smallest one
  that meets the targets.

**Training data:**
1. **v0, public only: Open Images V7 "Handgun".** Annotations are CC BY 4.0 and
   images CC BY 2.0. It gives a working model to build the pipeline and the
   evaluation on before our footage exists, and a baseline that shows what
   fine-tuning gains.
2. **v1, our footage plus Open Images.** The recording session is below.
   - Labelled as boxes on full frames, sampled at 2 fps.
   - Boxes rather than per-crop yes/no labels: with a few takes, a whole-crop
     label lets the model learn the take (jacket, light) instead of the gun.
   - Frames are turned into training crops by **the same `hand_crops()`** the
     live run uses, so training matches inference.
   - v0 pre-annotates, and a person corrects in Label Studio (Apache-2.0).
3. **Splits are by take, never by frame.** The test takes are recorded
   separately and never trained on.

### Recording session (Moe and cast, about 45 min, via OBS as now)

Protocol to be written to `knowledge/background/handgun_detection.md`:
- **Positives:** each prop, held by each cast member who may handle it.
  - Distances: front, middle and back of the stage.
  - Facing: toward the camera, side-on, away.
  - Grips: lowered at the side, aimed one-handed, two-handed, held by the
    barrel, handed to another person.
  - Two-person scenes with crossings.
  - The rehearsal room's light states, including coloured light.
- **Hard negatives** (no boxes needed):
  - phone, remote, black wallet, glasses case, stapler, cup or glass, script
  - finger-gun gesture, empty-hand aiming pose
  - the prop in a holster or pocket, or on a table (not held)
- **Gun-free footage for false alarms**, already on hand:
  - the 24 corpus scenes in `../test_data_orest`
  - earlier Probebühne recordings
- Footage and labels go in `data/handgun/` and are not committed.

### Temporal decision

- A `Handguns` thread reads the newest `(image, frame)` at **5 Hz**.
  - It is fed by an `appearance.Latest`-style `on_frame` slot, so the crops come
    from the exact image the bodies were tracked on.
  - It runs on its own thread, not on the recogniser's: one batched call for up
    to 8 crops would slow pose at 25 fps (`live_sitrep_latency.md`, "How real
    surveillance systems do it", point 1: small detectors run continuously,
    with an event within a second).
- **Raised** per body when `RAISE` of the last `WINDOW` passes score ≥
  `THRESHOLD` (e.g. 3 of 5, about 0.6 s).
- **Released** after `RELEASE` seconds without a detection.
- All constants are set from the evaluation, as appearance's `THRESHOLD` and
  `MARGIN` were (changelog 2026-10-06).

### Proposed acceptance targets (Moe to confirm)

| Metric | Measured on | Target |
|---|---|---|
| Event recall: held-gun intervals ≥ 1 s that are detected | test takes | ≥ 95 % |
| Latency: gun in hand → raised | test takes | p95 ≤ 1 s |
| False alarms after voting | corpus + Probebühne, gun-free | ≤ 1 per hour |
| False alarms on hard-negative takes | test takes | 0 |
| Right body | test takes | ≥ 95 % |
| GPU: one pass, 8 crops | RTX 5090 | ≤ 10 ms |

The evaluation also reports:
- per-crop precision and recall over thresholds
- how many held-gun frames had no usable wrist, which is the cost of hand crops
- a whole-frame baseline at the same model, so that cost is visible

## Files

**New:**
- `src/sitrep/handgun.py`, following `src/sitrep/appearance.py`:
  - `MODEL_DIR` (env `APOLLON_HANDGUN_MODEL_DIR`), `available()`, `session()`,
    `active_provider()`
  - `hand_crops(image, body)`, `detect(image, bodies) -> dict[int, Sighting]`
    (batched)
  - `class Handguns`:
    - `observe` (the on_frame slot), its own 5 Hz thread, voting
    - `holding() -> dict[int, Holding]`, plus `events` (raised and released,
      with time and track) in memory only
    - `error`, set when the detector fails so that only this cue stops, as in
      `ActionRatings._describe`
    - `clear()`, `close()`
  - `main()` for `python -m sitrep.handgun`, the evaluation, in the style of
    `python -m sitrep.appearance`: it walks footage with `recognizer.replay`
    and `ActionRecognizer().observe`, reads labels and prints the tables above.
- `src/scripts/handgun_dataset.py` (project venv): labelled frames → hand
  crops → COCO json. Also writes the v0 set from Open Images.
- `src/scripts/train_handgun.py` (throwaway uv env with torch and rfdetr):
  - trains, then exports `data/models/handgun/handgun.onnx`
  - checks ONNX against torch and writes `reference.npz`
  - copies the reference to `tests/fixtures/handgun_reference.npz`
- `data/models/handgun/SOURCE.md`: sources, the checkpoint SHA-256, terms.
- `tests/test_handgun.py`:
  - crop geometry on hand-built `tracking.Body` objects
  - voting and release on fake sightings
  - failure isolation with a monkeypatched `session`
  - ONNX parity, `skipif(not available())`

**Changed:**
- `src/sitrep/session.py:321-334`: build `Handguns` when `handgun.available()`
  (otherwise a warning naming the training script), pass its `observe` as a
  second `on_frame` observer, and close and clear it in `Session.close`.
  - `ActionRatings` (`src/sitrep/actions.py:280-289`) takes a sequence of
    `on_frame` observers.
  - `tests/test_session.py` fakes and the `readers` assertion are updated.
- `Session.overlay` / `src/sitrep/annotate.py`:
  - a body holding a gun gets a red box and a "WAFFE" tag on the operator video
  - the NDI feed stays clean
- `src/interface/live.py` `snapshot()`:
  - `in_view` entries gain `handgun: bool`
  - a `handgun` key carries the error and the recent events
  - the Übersicht's Im Bild panel shows a "Waffe" badge (`static/sitrep.js`)
  - Prototypes 1 and 2 are left alone until the effect is decided
- Console: one line when a gun is raised or released.
- `hardware_issues.md` H-5: a row for the model.
- `changelog.md`: entries for v0, the recording, v1 and the live check.
- `02_processing.md:25`: a note pointing to the implementation.

**Not touched:** `lage.py`, the alarm, `sitrep_map.csv`, the Empfehlung and OSC.

## Order of work

1. **Protocol and targets.** Moe confirms the targets, then the recording
   session is scheduled.
2. **v0, while waiting for the recording.**
   - Open Images set, training, export, `handgun.py`, the evaluation script,
     tests.
   - Run the evaluation on the corpus for a false-alarm baseline.
3. **Recording and labelling.** Moe and cast record; v0 pre-annotates; boxes
   are corrected.
4. **v1.**
   - Fine-tune and compare sizes on the test takes.
   - Set `THRESHOLD`, `RAISE`, `WINDOW` and `RELEASE`.
   - Log the measurements in the changelog.
5. **Live integration.** Session, overlay, snapshot, Im Bild badge.
6. **Live check in the room.** A short run with the props and hard negatives,
   with the GPU measured alongside Gemma (`python -m sitrep.replay ... --gpu`).

## Verification

- `uv run pytest`: the new tests, and the existing 564 still passing.
- `python -m sitrep.handgun --labels data/handgun/test/... <takes>`: the
  targets table on the test takes.
- `python -m sitrep.handgun ../test_data_orest/*.mp4`: false alarms per hour
  on gun-free footage.
- `python -m sitrep.replay <test take> --gpu`: the GPU load with the detector
  and Gemma together, and the 5 Hz pass keeping its rate.
- Live, `apollon-ui` on the Probebühne camera:
  - the WAFFE box appears within about 1 s of picking up the prop, on the
    right person
  - it clears after it is put down
  - no box during a hard-negative sequence
