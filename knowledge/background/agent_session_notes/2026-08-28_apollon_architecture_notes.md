---
title: "Apollon — Architecture Notes: Time, Cameras, Hindsight-SITREP, WISE Integration"
date: 2026-08-28
status: session notes, not implementation
author: Claude
project: "Human in the Loop"
---

# Apollon — Architecture Notes

Dated 2026-08-28. Results of a working session on the time model, camera
setup, post-processing and search integration. Open items at the end.

---

## 1. Two SITREP passes instead of one

The most consequential decision of the session.

| | Live SITREP | Hindsight SITREP |
|---|---|---|
| Purpose | operation during rehearsal | metadata for the archive |
| Input | stream | recorded files |
| Realtime budget | yes | none |
| Windows | non-overlapping, drops permitted | overlapping, gapless |
| Frame rate | reduced | full |
| Model | whatever runs in realtime | arbitrarily larger |

Same code, different scheduler. Latency then stops being a constraint on
metadata quality. A judgment's timestamp refers to the window it
analysed, which is all the join needs.

---

## 2. Time model

**Session clock.** Capture wall time **once** at session start, then use
`time.monotonic_ns()` exclusively. Derive wall time when writing.

**Never subtract two wall-clock readings.** NTP can step backwards
mid-session. Configure chrony to slew rather than step. Log any step that
happens anyway.

**Arrival time ≠ capture time.** Sensor, encode, transport and decode add
tens of milliseconds over USB and can add several hundred over RTSP, and
the audio and video paths differ. Calibration: one clap in front of the
camera, measure the offset between the audio transient and the frame,
store as a session constant, subtract it. A session recorded without
calibration is itself worth logging.

**Drift.** Every camera writing to its own card is its own clock domain.
Nominal 25 fps is really 24.997 or similar — roughly ten seconds
accumulate over three hours. A synchronised start time alone does not
solve this.

**Alignment methods, in descending order of reliability:**

1. **Hardware timecode** — Tentacle Sync or similar generates LTC,
   jam-syncs to a common clock, and either feeds a camera's timecode
   input or records onto an audio channel. Around €200 per unit. Read by
   every NLE. Removes drift as a concern.
2. **Sync events** — clap or flash at the start **and end** of every
   recording. Two points give offset *and* rate, hence a linear drift
   correction. One point gives offset only.
3. **Audio cross-correlation** — if every camera picks up room sound, the
   offsets can be recovered from the audio tracks.
   `scipy.signal.correlate` on downsampled envelopes, or the `audalign`
   package. Free, robust, works as a fallback and as a check on the other
   two.

**Principle:** correct timestamps, don't resample media. Store
`(offset, rate)` per file and apply at read time.

---

## 3. Cameras

### 3.1 Record everything, cut later

Live switching between cameras during rehearsal was rejected. Reasons:

- The cut is destructive. Whatever is switched away from is gone — and
  which moment matters becomes clear weeks later.
- Holes in the pose index: a camera running only part of the time
  produces empty result sets with no way to distinguish "the movement
  didn't happen" from "nobody was pointed at it".
- Costs three hours of one person's attention.
- The only saving is disk.

A virtual switcher over synchronised files gives the same result
afterwards.

**Exception:** backstage is a different space, not another angle on the
same action — its own continuous camera. Note §201a StGB near dressing
rooms.

### 3.2 One stream into SITREP

Only the wide stage view goes into analysis. Multiple parallel streams
through a 12B multimodal model is neither necessary nor affordable.

### 3.3 Interface with the film people

The work splits cleanly:

- **Their side:** all cameras to SD card, slates or timecode boxes,
  synchronisation, conforming.
- **My side:** the one streamed camera plus audio, whose timestamps
  originate in my own process.

Two possible handovers:

- **Raw files plus a table** — `(offset, rate)` per file, converted at
  read time. Two lines of code, but the table has to be carried around
  permanently.
- **Conformed export** — common start point, common frame rate, drift
  already corrected. Timestamp zero of every file *is* session time zero.
  No table, no arithmetic.

The second is routine for film people and moves the work to where the
tools are. Cost: working from re-encodes rather than originals, which is
irrelevant for search purposes.

**Agree early:** a common session clock, and the real start time in the
filename on both sides.

### 3.4 Where to record

The real question is not SSD versus computer but whether capture and
inference share a machine. Under GPU memory pressure, frames drop exactly
during the busiest moments.

Clean shape: one capture process per source writes the archival file
*and* publishes frames to the analysis process. One time source, one
clock domain, no post-hoc alignment. Camera-internal recording remains
the fallback for sources that can't stream losslessly (drone) — those get
sync events.

---

## 4. Hindsight-SITREP

### 4.1 Record shape

Key: `(source_id, t_from, t_to, run_id, person_id)`.

- `observed_at` is an **interval**, not an instant: `observed_from`,
  `observed_to`, plus `judged_at`.
- Record which frames actually entered the window.
- **One row per person per window**, not one per window. See §5.4 —
  without `person_id` the time join is unresolvable as soon as more than
  one person is on stage.

### 4.2 Run versioning

There will be several passes — better model, changed prompt, different
window. Without a `run_id` the second pass either clobbers the first or
silently mixes with it.

Every record carries: `run_id`, model version and hash, prompt version,
window spec.

### 4.3 Pure function

`(media_hash, window_spec, model, prompt) → records`. Re-runs are then
cheap, diffable, and checkable after a dependency upgrade.

### 4.4 Decode once, fan out

Decoding is usually the bottleneck. One pass feeds SITREP, WhisperX, pose
extraction and frame sampling together — not four passes over the same
file.

---

## 5. WISE integration

### 5.1 Findings

WISE indexes metadata at **file level** (SQLite FTS). One rehearsal = one
metadata entry. That's the gap.

However: the vector→content mapping already contains filename **and
timestamp**. The visual stream is sampled at roughly 2 fps, audio in
windows (e.g. 4 s with 2 s overlap). Visual, audio, face and ASR search
therefore already return timestamps within a long file.

**Consequence:** chunking is needed *only* to attach the SITREP text, not
for the other search modalities.

Cost note: one hour of video processes in under 10 minutes on a GPU
machine. Re-chunking a season means full re-extraction — the decision is
expensive to reverse.

### 5.2 Three options

| | Effort | Advantage | Disadvantage |
|---|---|---|---|
| **Chunk files** | no code | works in stock UI | boundary problem, re-extraction on change, fragmented timeline, ~1000 files/camera/rehearsal |
| **Fork the WISE Store** | schema trivial, query path and React frontend unknown | integrated, one UI | fork maintenance, upstream pinning |
| **Sidecar DB** | own query layer | no fork, metadata entirely mine | composite queries don't run in WISE's UI |

**Recommendation: sidecar.** A custom query layer is being built anyway
for live pose lookup. The option doesn't foreclose the other two.

### 5.3 Schema

```sql
CREATE TABLE segment_metadata (
  id        INTEGER PRIMARY KEY,
  media_id  INTEGER,
  t_from    REAL,
  t_to      REAL,
  run_id    TEXT,
  person_id TEXT,
  text      TEXT
);
CREATE VIRTUAL TABLE segment_metadata_fts
  USING fts5(text, content='segment_metadata', content_rowid='id');
CREATE INDEX idx_seg_time ON segment_metadata(media_id, t_from, t_to);
```

The core point: an **interval join on the timestamp**, where WISE does an
equality join on `media_id`. Chunking is nothing but an attempt to turn
the interval join into an equality join by cutting files.

### 5.4 Composite queries — what goes wrong

**Post-hoc intersection is the error.** CLIP returns a top 50, FTS
returns 30 windows, the intersection is empty — and there's no way to
tell "nothing matches" from "the match was at CLIP rank 180".
Intersecting two recall-limited lists produces a set far smaller than
either.

**Instead: constrained search.**

1. Query SQLite: `text MATCH ? AND run_id = ?` → a set of
   `(media_id, t_from, t_to)`.
2. Map intervals to vector IDs (range query against WISE's vector map).
3. Run the CLIP search **restricted to those IDs**, take the top k of
   that.

Faiss supports this directly: `IDSelectorBatch` via
`SearchParametersIVF(sel=...)` on an IVF index.

Run it the other way when the visual side is narrower. Heuristic:
estimate both set sizes, constrain on the smaller.

**Further traps:**

- **No LLM sentence decomposition.** Two input fields — visual query,
  metadata query. An LLM decomposer makes the tool nondeterministic and
  undebuggable. WISE does it this way itself: metadata filter and visual
  query are separate inputs.
- **Point in interval ≠ match.** A CLIP hit is an instant (2 fps), a
  SITREP judgment covers 10–30 s. False positives scale with window
  length — a concrete argument for a shorter hop in the batch pass.
- **Same time ≠ same person.** With four people on stage, "standing tall"
  may be person A and the threat rating person B. Hence `person_id` in
  every record. Once face or re-ID supplies an identity on the visual
  side too, the join becomes `(time, person)` rather than time alone.

### 5.5 Ranking

Cosine similarity and BM25 are not on the same scale — don't add them.
Filter with one, rank by the other; constrained search gives exactly
that. If genuine blending is needed later: **Reciprocal Rank Fusion**,
`sum(1/(60 + rank))` across the lists. Ignores scores, uses positions
only.

**Display:** dedupe before output. Consecutive hits at 2 fps produce
eight rows for one moment. Collapse runs into segments, rank by the best
frame in the segment.

### 5.6 Don't fuse

SITREP output stays **separate structured metadata**, joined on the
timebase. Baking labels into the media before embedding means re-embedding
on every judgment change — and destroys the separate queryability of
"what does this moment look like" versus "what did the system say about
it".

**Principle: the authoritative metadata store is mine, not WISE's.** The
WISE index is a derived, regenerable projection.

---

## 6. Text search

Independent of everything above; works even in the worst case (one
camera, one microphone).

- **WhisperX rather than Whisper.** Forced alignment against wav2vec2
  gives **word-level timestamps**; plain Whisper gives only loose segment
  boundaries.
- **The primary artifact is the word table:**
  `(word, t_start, t_end, confidence, speaker)`. Any window can be
  reconstructed from it.
- **Two indices over it:**
  - *Lexical* — SQLite FTS5 or BM25 over sliding windows. This is what
    lands "to be or not to be" on the exact moment. Cheap, no GPU.
  - *Semantic* — sentence embeddings over overlapping ~15 s windows, for
    "the bit where he talks about doubt".
  - Merge results by timestamp.
- **Diarization:** WhisperX bundles pyannote → per-speaker filter for
  free.
- WISE already includes WhisperX — check what its transcript index
  provides before building a parallel one. The word table may be all
  that's needed, for precise seeking.

---

## 7. Degradation ladder

| Tier | Requires | Yields |
|---|---|---|
| Baseline | one camera, one mic, WhisperX | full text search (exact + semantic), frame-accurate seeking |
| + batch SITREP | offline analysis pass | judgments joined on `(source_id, t_from, t_to)` |
| + pose | RTMPose, Faiss | pose and movement-phrase query |
| + multicam | timecode or sync events | all of the above across angles; one query returns every view of a moment |

Additive; no tier blocks the one below it. **Build the baseline first** —
needs no synchronisation work and covers the core requirement.

---

## 8. Open items

- [ ] Test dependency conflicts: WISE stack (OpenCLIP, OWLv2, InsightFace,
      CLAP, WhisperX) alongside the Gemma runtime in one venv. Decides
      single- versus multi-distribution layout.
- [ ] Read WISE's query path and React frontend — gives a realistic
      assessment of the fork option. The "one or two days" estimate
      covered schema and join only.
- [ ] Check what WISE's WhisperX integration already provides as a
      transcript index.
- [ ] Fix window length and hop for Hindsight-SITREP. A shorter hop
      reduces false positives in the interval join.
- [ ] Settle the handover format with the film people: raw files plus
      table, or conformed export.
- [ ] Establish AV offset calibration as a session routine (clap at start
      and end).
- [ ] Acquire timecode boxes or stay with slates.
- [ ] Choose a person re-ID method — determines when the join can move to
      `(time, person)`.
- [ ] Build the baseline tier (WhisperX + FTS5 + semantic index).
