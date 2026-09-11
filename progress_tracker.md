# Progress Tracker

Where each affordance of `knowledge/components/02_processing.md` stands. What
was built and why is in `changelog.md`; open questions are in
`claude_concerns.md`, and those that depend on the production machine are in
`hardware_issues.md`.

---

## Realtime-SITREP

| Step | Status |
|---|---|
| 1 · Gemma via Ollama | done |
| 2 · Select video and audio source | done — `sitrep.devices` |
| 3 · Capture loop | done — `sitrep.capture` |
| 4 · Transcription | done — `sitrep.transcribe`; speaker diarisation not implemented |
| 5 · SITREP JSON | done — `sitrep.report` |
| 6 · Latency budget | done — `sitrep.benchmark` |
| 7 · Output | console only; TouchDesigner handover open |

Report content is not yet trustworthy (`claude_concerns.md`, concern 1).

---

## Smart Search

Six phases. Each ends with something testable, and later phases reuse the
earlier code.

| Phase | What | Status |
|---|---|---|
| 1 | Drive WISE from Orest; index the sample corpus | **done** |
| 2 | Custom pose feature extractor — the body index | **done** |
| 3 | Embodied search: live capture becomes the query | next |
| 4 | Speech as query — transcript import and live line matching | not started |
| 5 | Localhost UI, hybrid search, TouchDesigner over OSC | not started |
| 6 | Hindsight-SITREP | spec is a TODO |
| — | Segment-level visual index (Qwen3-VL) | **deferred, hardware** |

**Reordered 2026-09-11.** Pose was phase 4 and the body index was to be
Qwen3-VL's. Qwen runs 13.6x slower than realtime on the 8 GB GPU
(`hardware_issues.md` H-2), so pose moves up and becomes the body-search route.
The clip-as-query patch that phase 2 used to be is no longer on the critical
path — see "Deferred" below.

### Phase 1 — done

`src/smartsearch/` drives WISE from the `orest` environment: `orest-search
extract | add-extractor | index | serve | info | query`. The sample corpus is
indexed and searchable by text over both picture and sound.

### Phase 2 — done

`wise_ext/` holds `orest_pose`, installed into both environments: RTMO keypoints
normalised and concatenated into a 544-dimension movement vector. Registered
with WISE through its factory, indexed, and searchable with a clip as the query
via `orest-search body`. Verified by self-retrieval on the probe. Details and
measurements in `changelog.md`.

Open increments, in rough order of value:

- **Only the largest body per frame is indexed.** WISE stores one vector per
  segment, so everyone else in shot is dropped. Supporting several people means
  patching WISE's segment loop, which currently creates exactly one vector row
  per segment.
- **The full corpus is not indexed yet** — ~2.3 hours on CPU, pending H-10.
- **Hits merge into long spans** because indexed segments overlap by half. A
  precise mode would read the unmerged windows.
- **A still cannot query the pose index**, since the vector spans 16 frames.
  Fine as specified, where the query is a captured sequence, but it forecloses
  querying from a photograph.

### Phase 3 — embodied search

Press a key to start, press again to stop, and the captured seconds become the
query — the "body" half of embodied search in `02_processing.md`. Builds on
`sitrep.capture`, which already streams frames and audio, and on
`smartsearch.pose`, which already encodes a clip and searches with it; what is
missing is only the live capture in place of a file.

**No WISE patch needed**, confirmed in phase 2: Orest encodes the query and
posts the vector to `/search_with_feature`.

Retrieval hygiene belongs here: exclude the recent past, cap results per file so
one afternoon does not fill the list.

### Phase 4 — speech

Transcripts imported as segment metadata and indexed for full-text search, which
is also the join Hindsight-SITREP will use. Reuses `sitrep.transcribe`. Tone of
voice stays out of reach: neither CLAP nor a transcript carries prosody.

### Phase 5 — UI

The localhost interface of `02_processing.md`: text, still and live-camera
search, hybrid search against Hindsight metadata, results to TouchDesigner over
OSC. FastAPI plus plain HTML.

Hybrid search needs no new retrieval machinery — WISE's `metadata_filter`
already constrains a vector search to the rows an FTS query matched.

### Phase 6 — Hindsight-SITREP

Blocked on the specification. The offline pass can reuse the live report code
with a different scheduler.

### Deferred — segment-level visual index, and clip-as-query

Qwen3-VL-Embedding-2B is not viable on this GPU (`hardware_issues.md` H-2).
Revisit when the production machine exists; H-2 gives the re-test.

If it becomes viable, it also needs the clip-as-query patch, which was the
original phase 2: WISE declares a video segment as a query term but never
implements it, sending every visual query to `PIL.Image.open` instead. The
segment extractor's `extract_video_segment_features()` already exists and is
unreachable from any search path, so wiring it up is one branch in the embedding
service. Only worth building once there is a segment index to query.
