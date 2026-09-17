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
| 3 | Embodied search: live capture becomes the query | **done** |
| 4 | Speech as query — transcript import and live line matching | not started |
| 5 | Localhost UI, hybrid search, TouchDesigner over OSC | **OSC bridge done**; UI not started |
| 6 | Hindsight-SITREP | spec is a TODO |
| — | Segment-level visual index (Qwen3-VL) | **deferred, hardware** |

**Reordered 2026-09-17.** The TouchDesigner bridge — clip cutting and OSC —
was pulled forward from phase 5 ahead of phase 3. Every search mode ends in it,
and it is what lets the video department work with real results.

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
- **Common postures barely discriminate.** On the full corpus, distinctive
  movement retrieves itself with a margin of 0.25–0.33, but a query of two
  actors in ordinary stage posture returns six results within 0.011 of each
  other, its own segment at rank 2. Candidates: index every body rather than
  the largest, weight motion over static posture, or down-weight the most
  common postures by frequency. The full corpus is indexed (7,439 vectors,
  108.5 min), so any of these can be evaluated against it directly.
- **Hits merge into long spans** because indexed segments overlap by half. A
  precise mode would read the unmerged windows.
- **A still cannot query the pose index**, since the vector spans 16 frames.
  Fine as specified, where the query is a captured sequence, but it forecloses
  querying from a photograph.

### Phase 3 — embodied search — done

`orest-search body-live`: Enter or OSC `/orest/body/start` and
`/orest/body/stop` on port 10001 bracket a capture, which is searched in
index-shaped windows and delivered to TouchDesigner like any other search.
Verified on known footage played in real time with `--file`; details in
`changelog.md`.

Open:

- **The camera path is untested live.** `--file` exercised everything but
  `sitrep.capture.VideoStream`, which the SITREP already uses.
- **Excluding the recent past** is not implemented. The index is built offline,
  so it holds nothing from the session being captured; it becomes necessary
  once the rehearsal recording feeds the index while rehearsal continues.
- **Merged spans are long**, up to 122 s in a webcam test — the phase 2
  overlap merge, carried into clip length. `--segments` sidesteps it with
  four-second windows. **A maximum clip length for merged results is
  deliberately left open** until the system has been used in rehearsal, where
  the right length will be apparent.
- **Scores rise with capture length.** Results carry the best score over all
  windows of the capture, so a 45 s capture scored 0.988 on moments a 2 s
  capture scored 0.5. A score threshold in TouchDesigner must allow for this.

### Phase 4 — speech

Transcripts imported as segment metadata and indexed for full-text search, which
is also the join Hindsight-SITREP will use. Reuses `sitrep.transcribe`. Tone of
voice stays out of reach: neither CLAP nor a transcript carries prosody.

### Phase 5 — UI

The localhost interface of `02_processing.md`: text, still and live-camera
search, hybrid search against Hindsight metadata, results to TouchDesigner over
OSC. FastAPI plus plain HTML.

**OSC bridge done:** `smartsearch.clips` cuts results in fast (stream copy) or
precise (H.264 re-encode) mode, `smartsearch.td` announces each clip, both
behind `--cut` / `--send-td` on `query` and `body`. The UI calls the same
`main.deliver()`. Open:

- **Pre-roll trimming in TouchDesigner.** TouchDesigner ignores the edit list
  hiding a fast clip's pre-roll, so the hit message carries it; trimming it on
  the Movie File In TOP is set up but not yet verified on the test clip.
- **TouchDesigner hangs while editing** a network with several players, on the
  laptop's Non-Commercial licence; playback of two players is stable. Not
  investigated until the production workstation.
- **HAP** is not in the `wise` environment's ffmpeg build.
- **Simultaneous H.264 streams** in TouchDesigner are unmeasured.
- Clips are cut one at a time; precise mode could cut several in parallel.

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
