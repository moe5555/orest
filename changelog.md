# Changelog

Central development log for Orest. Newest entries first. See
`knowledge/KNOWLEDGE_BASE.md` for pointers into the Source of Truth files
referenced below.

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
