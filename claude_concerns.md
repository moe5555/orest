# Claude's Concerns

Open questions and risks I have flagged while building Orest, with the evidence
behind them. Written for Moe to decide on — I have not acted on any of these
beyond what is already in the code. Newest first.

Related: `changelog.md` for what was built, `knowledge/components/02_processing.md`
for the specification.

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
