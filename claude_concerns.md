# Claude's Concerns

Open questions and risks I have flagged while building Apollon, with the evidence
behind them. Written for Moe to decide on — I have not acted on any of these
beyond what is already in the code. Newest first.

**Anything that depends on which machine Apollon runs on lives in
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
from individual frames, less well. `progress_tracker.md` ("Deferred") has what
building it would involve.
