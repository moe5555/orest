# Claude's Concerns

Open questions and risks I have flagged while building Orest, with the evidence
behind them. Written for Moe to decide on — I have not acted on any of these
beyond what is already in the code. Newest first.

**Anything that depends on which machine Orest runs on lives in
`hardware_issues.md`**, to be worked through in one pass once the production
hardware is settled. Concerns here that have a hardware dimension cross-
reference it rather than repeating the measurements.

Related: `changelog.md` for what was built, `knowledge/components/02_processing.md`
for the specification.

---

## 2026-09-11 — Smart Search, phase 1

### 1. What the search index costs per hour of rehearsal

Moved to `hardware_issues.md` **H-4** — it is a disk-purchasing decision, and it
is coupled to the visual sampling rate, which is expensive to change after the
first rehearsal week. Short version: ~127 MB of index per hour of footage,
~178 GB across the estimated season, of which thumbnails are 59%.

The reason thumbnails cannot simply be dropped is item 2 below.

### 2. Two upstream thumbnail bugs, one patched

Neither is Windows-specific; both are in WISE at `fcfa443`.

- **Stored thumbnails were never written**, whatever `--thumbnails` said. The
  code looks the thumbnail chunk up under the string `"thumbnails"` in a
  dictionary keyed by a `MediaChunkType` enum, so the branch never ran. Patched
  as `0004-thumbnails-enum-key.patch`; 29,763 thumbnails now written for the
  test corpus, exactly one per indexed frame.
- **On-demand high-resolution stills crash, and this fires constantly.**
  `GET /thumbnail?high_res=true` returns 500. The frontend requests it on every
  modal open (`StillImageView.tsx` upgrades a stored thumbnail to a full-
  resolution still), so browsing the corpus fills the server log with
  tracebacks. Two stacked defects: `WiseProject.thumbnail()` hands `AVDataset` a
  list of paths where it now expects a map of media id to path, and the line
  after reads `chunks["video"]` with a string key on an enum-keyed dictionary —
  the same defect class as the one patched above. The path has not worked since
  that refactor.

  **Left unpatched deliberately.** The frontend's `onerror` handler falls back
  to the stored thumbnail, so the only cost is a soft preview image instead of a
  crisp one. Fixing it means correcting two calls in upstream code we do not
  otherwise need, carried on every re-clone. It is, however, the reason item 1
  has no cheap escape: without stored thumbnails there would be no picture at
  all.

A third upstream defect, 10 KB video streaming chunks, **was** patched — see
`changelog.md`, 2026-09-11. All three are worth reporting upstream rather than
carrying locally forever.

### 3. Shot detection has not been run

`shots: 0`. Retrieval hits are therefore merged by proximity — consecutive
matches within 4 seconds become one result — rather than snapped to shot
boundaries. The returned ranges are usable, and for continuous single-camera
rehearsal footage there may be no shots to find; TransNetV2 is built for edited
video. For the Othello recording, which is edited, shot detection would give
cleaner segment boundaries.

It is a separate GitLab project with its own TensorFlow environment
(`external/wise/docs/Shot-Detection.md`). **Worth the setup, or not?** My
inclination is not yet: it matters for presentation, not for whether the right
moment is found.

### 4. The segment-level visual index is deferred, not abandoned

Qwen3-VL-Embedding-2B ran at 13.6x slower than realtime on this GPU, which would
be ~56 hours for the test corpus. Measurements and the re-test procedure are in
`hardware_issues.md` **H-2**; its 4.0 GB download is folded into **H-5**.

What this costs, until hardware allows it: searching by *event* — "someone
collapsing", "two people embracing" — at the granularity of a short segment
rather than a single frame. The stock CLIP index still answers those queries
from individual frames, less well.

The roadmap was reordered on 2026-09-11 in response: the custom pose extractor
becomes the body-search route, and the clip-as-query patch is no longer needed
for it, because a pose embedding can be computed in Orest and submitted to
WISE's `/search_with_feature` endpoint, which is verified working.
`progress_tracker.md` has the current order.

---

## 2026-09-09 — Realtime-SITREP MVP

### 1. The SITREP content is not trustworthy yet

**This is the biggest open risk.** `gemma4:e4b` produces well-formed, confident,
German reports whose content is substantially invented.

Observed on live webcam footage of a single person sitting in a room:

| Run | What it reported | Reality |
|---|---|---|
| 1 | "Anzug und Krawatte" | patterned shirt |
| 2, 15s later | "schwarzes Hemd und eine Jeans" | same person, unchanged |
| 3 | "Junges Mädchen mit dunklem Haar" | adult man |
| 4, 20s later | "Junger Mann mit dunklem Haar" | same person, unchanged |
| — | "Bühnenbild mit Vorhängen und Möbeln" | a domestic room, no set |
| — | `gesagt`: a full formal address, *"Sehr geehrte Damen und Herren, wir sind heute hier zusammengekommen, um über die Zukunft unseres Theaters zu sprechen…"* | no German speech in the room at all |
| — | "Der Schatten des Vergessens" (a play title) | invented outright |
| — | "Wind in den Blättern, Vogelzwitschern, Plätschern von Wasser" | room tone from a laptop microphone |

The prompt already forbids speculation explicitly and instructs the model to
leave fields empty when nothing is discernible. It complies sometimes — `gesagt`
does come back empty on silence — but not reliably. `vertrauen` sat at 3–4/5
while the model was describing clothes that do not exist, so the model's own
confidence score does not identify these failures.

Note this is a **quality** problem, not a stability one: the mechanism is
reliable (0 unusable replies in 60 benchmark generations), it is the content
that is wrong.

**Why it matters beyond accuracy.** The categories per person are
`verantwortungsvoll / menschlich / gefahr / kollaborativ` — these are judgements
about named people, logged to disk. A `gefahr` score attached to a person the
system has also described as wearing clothes they are not wearing is a
different kind of artefact than a wrong caption, both dramaturgically and under
the EU AI Act point already raised in `02_processing.md`.

**Questions:**
- How accurate does this actually need to be for the production? If the piece is
  *about* an AI confidently misreading a room, the confabulation may be material
  rather than a defect — but that should be a deliberate decision, not something
  we discover on stage.
- Should I try the mitigations below, or is this good enough for now?

**Mitigations available, roughly in order of expected effect:**
1. **Step 4 (dedicated transcription) — done 2026-09-10.** `gesagt` is now
   Whisper's transcript, written into the report verbatim, so the model can no
   longer invent speech — and in the first live run with real German speech,
   it didn't. It surfaced a new failure mode, below.
2. **A larger model** — see hardware below.
3. Prompt/schema tightening: force `merkmale` to be omitted rather than guessed,
   drop `prognose`/`empfehlung` (both are invitations to speculate), lower
   temperature to 0. Related: e4b fills unknown fields with placeholders
   ("Keine Angaben vorhanden.", "N/A") instead of leaving them empty as
   instructed, and the console prints those as if they were content.
4. Feed the model the previous window's report so descriptions stay consistent
   between windows. Costs latency and can entrench an early error.

**New since transcription: the transcript is read as a description of whoever
is on camera.** In the first live run the speech mentioned "ein junger Student
aus Berlin". The model recorded P-01, the only person in frame, as "Junger
Student aus Berlin (laut Transkript). Geschlecht: männlich", assumed P-01 was
the speaker, inferred an audience from "ihr alle", and referred to a P-02 it
never listed. Nothing links a voice to a face: the system cannot tell who is
speaking, or whether the speech comes from someone off camera or from a device.
That is the diarisation step 4 defers ("speaker diarisation eventually"), and it
matters more now than before — the transcript is an authoritative-looking input
the model builds on.

**Question:** was the speech in that run you, or audio playing from a device?
The "Student aus Berlin" attribution is wrong either way, but it decides
whether "P-01 spricht" was.

**The transcript itself is not always real speech.** In a run on 2026-09-10 in
an empty, silent room, Whisper returned "Vielen Dank." with `vad_filter=True`
— the phantom-text failure the filter was chosen to prevent, and the same
phrase that motivated choosing it (`transcribe.py`). `gemma4:e4b` then
recorded it as an event: "P-01 spricht: Vielen Dank." So the two failure modes
compound: the transcript can be a hallucination, and the model treats it as
the one authoritative input it is not allowed to doubt. Worth measuring how
often the filter lets phantom text through on real room tone before the
Probebühne — a rehearsal has long silences, and every one of them is an
opportunity for this.

### 2. Which GPU will actually run this?

All code and every measurement so far is from the **RTX 4070 Laptop, 8GB**.
That constraint has already made one significant decision for us:

- `gemma4:12b-it-qat` needs 8.5GB and runs **30% CPU / 70% GPU**, giving p95
  latency of 28–30s regardless of window size — unusable.
- `gemma4:e4b` is resident at 3.2GB, **100% GPU**, p95 4.4–7.6s.

So e4b was chosen for VRAM, not for quality — and on comparable input the 12b
described the scene correctly and correctly left `gesagt` empty where e4b
invented a speech.

**Question: what is the spec of the machine that runs this in the Probebühne
and in the production?** `02_processing.md` says only "PC to run local inference
on". If it has ≥12GB VRAM, the 12b likely runs fully on GPU and is both fast
*and* accurate, and most of concern 1 may simply evaporate. That would make
tuning e4b wasted effort. I would like to know this before investing in
mitigations 3 and 4 above.

### 3. Coverage gaps between windows

Generation blocks the next capture window, so the gap between windows equals the
generation latency. Coverage is W/(W+latency): **65% at a 15s window, 83% at
30s**. The system is blind for ~7s after every report.

Latency is nearly flat in window size (4.4s at a 10s window, 7.6s at 60s), so
longer windows are strictly better for coverage. But if continuous coverage
matters, the fix is to run generation on a worker thread while capture
continues, dropping windows when generation falls behind — which is what step 6
describes ("only processes as many seconds as it can keep up with"). I have not
built this because sequential is simpler and currently sufficient.

**Question:** does the SITREP need to observe continuously, or are gaps
acceptable?

### 4. Untested at rehearsal scale

Everything so far is one person, a laptop webcam and a built-in microphone array
in a domestic room. Untested and expected to matter:

- **Several people at once.** Person re-identification across windows is not
  implemented at all — `P-01` in one report has no relationship to `P-01` in the
  next, and the model already contradicts itself about a single subject.
  `02_processing.md` raises "provide the system with images of each team member,
  perhaps their bio?" — that is unbuilt and is the natural answer here.
- **Room acoustics.** A Probebühne with distant speakers is a much harder audio
  case than a laptop mic at desk distance.
- **Long sessions.** The longest continuous run so far is a few minutes. Memory
  growth, Ollama context handling and thermal throttling over a 3-hour rehearsal
  are all unknown.
- **Stage lighting.** Auto-exposure behaviour under theatre lighting is
  untested, and I have an unexplained DirectShow frame-rate variance
  (~10–30 fps) already logged in `changelog.md`.

---

## Smaller items

- **`gemma4:12b-it-qat` appears to have been removed** from the local Ollama
  models. If that was to free disk space, note that re-pulling is ~7.2GB and the
  registry download failed repeatedly over IPv6 on this machine
  (`WSAECONNABORTED`, all 16 parallel parts).
- **Audio encoder boundary — no longer applies, but will return.** Gemma's audio
  encoder rejects clips whose length lands within a hair of a 30-second
  multiple (`Failed to tokenize prompt`). Since 2026-09-10 Gemma receives a
  Whisper transcript instead of audio, so the bug cannot occur and
  `capture.clip_for_encoder()` was removed. If audio is ever passed to Gemma
  again — e.g. transcript *and* audio, to recover non-verbal information — the
  trim has to come back: the 30s default window hit the boundary exactly.
- **`vertrauen` is self-reported** by the model and did not correlate with
  actual accuracy in anything I observed. I would not display it to an operator
  as if it meant something.
- **`src/data/` has been deleted** — the speech sample `test01_20s.wav` and
  `test_frame.jpg`. The `data/` rule in `.gitignore` matches a directory of that
  name at any depth, so both were never committed and cannot be restored from
  git. As a result `src/sitrep/test.py` no longer runs, and `benchmark.py` now
  takes the speech recording as a required `--speech` argument. **Was the
  deletion intentional?** If test assets belong in the repo, they need a
  directory name the rule does not match, or the rule narrowed to `/data/`.
- **`__pycache__/` was committed** in `03de01f` (five `.pyc` files under
  `src/sitrep/`). Worth adding `__pycache__/` to `.gitignore` and untracking
  them with `git rm --cached`. I have not done either, since it changes the
  repository.
- **Both models download on first use, which needs internet.** Whisper
  large-v3-turbo (~1.6GB) took about 4 minutes from Hugging Face on its first
  run here, including load; `gemma4:e4b` is ~9.6GB from the Ollama registry,
  whose download failed repeatedly over IPv6 on this machine. If the Probebühne
  or production machine is offline or on a restricted network, both have to be
  fetched in advance and a first run tested on that machine. **Will it have
  internet access?**
