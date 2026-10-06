# Hardware Issues

Everything in Apollon that is limited, blocked or undecided **because of the
machine it runs on**. The production machine, `VSH-ARLT-5090`, has existed since
2026-09-25; each item says what was measured on the laptop, what has since been
measured on the workstation, and what is still to do there.

Non-hardware risks stay in `claude_concerns.md`; what was built is in
`changelog.md`.

**Nothing here is a code defect.** Every item is a machine constraint, and
several of the design decisions taken so far exist only to work around one.

---

## Reference machines

| Name | Spec | Role so far |
|---|---|---|
| `MININT-ITT28VU` | TongFang GM5IX7A laptop, Win 11, 32 GB RAM, **RTX 4070 Laptop, 8 GB VRAM** | development until 2026-09-24; Smart Search measurements |
| `ctechadmin` | Win 11 workstation, Film University Babelsberg, MDM-enrolled (Sophos + AppLocker) | WISE install only, 2026-08-29 |
| `VSH-ARLT-5090` | Win 11 workstation, i9-14900KF (24 cores / 32 threads), 128 GB RAM, **RTX 5090, 32 GB VRAM**, 514 GB free on C: | **production machine**, from 2026-09-25; live SITREP |

Confirmed by Moe on 2026-09-11: the machine runs **either** Smart Search **or**
the live SITREP, never both. To be confirmed again for `VSH-ARLT-5090`.

---

## Issues

### H-1 · The SITREP model — settled on `gemma4:26b`, p95 not yet benchmarked

**On the laptop:** `gemma4:12b-it-qat` needed 8.5 GB against 8.1 GB available
and ran at p95 28–30 s, so `gemma4:e4b` (3.2 GB) was used for fitting in VRAM.
It confabulated heavily (`changelog.md`, 2026-09-09).

**On `VSH-ARLT-5090`:** `gemma4:26b` (Mixture-of-Experts, 3.8B active, 18 GB)
is the default since 2026-09-29 (`report.MODEL`). Its descriptions have matched
the frame (`changelog.md`, 2026-09-25). Measured in the live SITREP on "Four
Dogs" (`changelog.md`, 2026-09-29): line rating p95 2.1 s, Lagebericht
3.3–4.4 s.

**Still to do:** `benchmark.py --model gemma4:26b` for a p95 against the
window.

---

### H-2 · Qwen3-VL segment embedding is unusable at 8 GB

**Measured 2026-09-11** on the laptop, `hf/Qwen/Qwen3-VL-Embedding/2B` on the
12-minute probe:

| | |
|---|---|
| Rate | **55 s per 8-second segment**, still rising at 17 segments |
| VRAM | 7,862 MiB of 8,188 — at the ceiling |
| Speed vs realtime | **13.6× slower** |
| 12-minute probe would take | ~2.7 hours |
| 4h08m corpus would take | **~56 hours** |

For scale, SigLIP2 indexed the same probe in **87 seconds**.

**Consequence:** the Smart Search roadmap was reordered on 2026-09-11. The
segment-level visual index is deferred and the custom pose extractor is the
body-search route.

**Blocks:** searching by *event* ("someone collapsing") as opposed to by scene
semantics or by limb configuration.

**Not yet re-tested on `VSH-ARLT-5090`.** Re-run `apollon-search add-extractor
--project probe --video-id hf/Qwen/Qwen3-VL-Embedding/2B` and read the
iteration rate off the first 20 segments. Anything near or below realtime makes
the index practical; the 8B build needs a further step up again. The model
loads in float16 already, so `--enable-autocast` will not help. The weights
(4.0 GB) must be downloaded there first (H-5).

**If the re-test is abandoned part-way, clean up after it.** A killed run leaves
an empty `store/hf/Qwen/...` directory and orphan rows in the `vectors` table.
WISE discovers extractors from the store directory tree and instantiates every
one of them at `serve` startup, so the orphan would load 4 GB of weights on
every server start for an index that does not exist:

    rm -rf <project>/store/hf
    sqlite3 <project>/metadata/internal.db \
      "delete from vectors where feature_extractor_id like 'hf/Qwen/%';"

---

### H-3 · Feature extraction is decode-bound, not GPU-bound

**Measured** on the laptop: the full corpus extracted at **6.6× realtime**
(4h08m of footage in 37.6 min). The process held about two cores busy while the
GPU idled between batches. The 12-minute probe, whose file is smaller, ran at
8.4×; the corpus includes a 4K file.

**Consequence:** a faster GPU alone will not speed up stock extraction much.
Cores, and the decoder, are what matter.

**The same holds for pose.** Per four-second segment, decode costs 498 ms
against 247 ms for pose inference on the GPU. Over the corpus the pose index
took 108.5 minutes, and throughput fell from ~1.3 to ~0.35 segments/s on
reaching the 4K file, with the GPU idle and the CPU at 7–12% — a single
decoder thread working through a stream four times the size. Resolution of the
rehearsal cameras therefore sets indexing time more directly than the GPU does.

**At scale:** `knowledge/background/agent_session_notes/bloom-wise-architecture.md`
estimates 1,400 hours for the season. At 6.6× that is **~9 days of continuous
extraction**, which is why that document recommends running incrementally each
night rather than in one pass.

**Not yet re-measured on `VSH-ARLT-5090`.** Re-measure there, and test
`--num-workers` above 0 — every run so far used 0. Downscaling source video to
512px height before extraction is the documented remedy
(`external/wise/docs/Processing-Large-Datasets.md`).

---

### H-4 · Search index storage: ~127 MB per hour of footage

**Measured** on the 4h08m corpus with the two stock extractors:

| Component | Total | Per hour |
|---|---|---|
| Thumbnails | 315 MB | 75 MB |
| Vectors | 204 MB | 49 MB |
| Metadata | 6 MB | 1 MB |
| **Total** | **525 MB** | **~127 MB** |

At 1,400 hours that is **~178 GB of index**, on top of roughly 3 TB of video.
Thumbnails are 59% of it and cannot simply be dropped: WISE's on-demand
alternative is broken (`claude_concerns.md`, item 2). `VSH-ARLT-5090` has
514 GB free on C:, which holds the index but not the video.

**Blocks:** nothing yet. It is a purchasing decision.

**To decide:** the disk for the recordings, then the visual sampling rate. 2 fps
is the default; 0.5 fps would quarter both thumbnails and vectors and is
described as ample for a static room. **Changing it later means re-extracting
everything**, so it is cheap now and expensive after the first rehearsal week.

---

### H-5 · Model weights must reach the machine

| Model | Size | Source | Used by | On `VSH-ARLT-5090` |
|---|---|---|---|---|
| `gemma4:26b` | 18 GB | Ollama registry | live SITREP | yes |
| Whisper `large-v3-turbo` | ~1.6 GB | Hugging Face | transcription | yes |
| ST-GCN NTU120 2D (`data/models/ntu120_stgcn/`) | 12.5 MB | OpenMMLab | action recognition | yes |
| Qwen3-VL-Embedding-2B | 4.0 GB | Hugging Face | deferred, see H-2 | no |
| SigLIP2-512 + MS CLAP | small | Hugging Face | Smart Search | not checked |

On the laptop, the Ollama registry download **failed repeatedly over IPv6**
(`WSAECONNABORTED`, all 16 parallel parts), and Hugging Face downloads warned
that `hf_xet` is missing and fell back to plain HTTP at 5–9 MB/s.

**Open:** whether `VSH-ARLT-5090` has internet access where it will stand. If
the Probebühne is offline or on a restricted network, fetch everything in
advance — the Hugging Face cache (`~/.cache/huggingface`) and the Ollama model
store — and run one live session there before relying on it.

---

### H-6 · Untested at rehearsal scale

Every live run so far has been test footage played through OBS or a webcam,
not a rehearsal. Unknown in the real room:

- **Long sessions.** The longest measured run is under seven minutes
  ("Four Dogs", 405 s). Memory growth, Ollama context handling and thermal
  behaviour over a three-hour rehearsal are unmeasured.
- **Room acoustics.** Distant speakers on a Probebühne are a far harder audio
  case than footage with a mixed soundtrack.
- **Cameras and stage lighting.** The rehearsal cameras are not yet chosen;
  their resolution also sets indexing time (H-3), and auto-exposure under
  theatre lighting is untested.
- **The cast roster.** `data/cast` holds no enrolment photographs, so naming
  people has not run end to end (`progress_tracker.md`, cast recognition).

**To do:** one full-length session end to end on `VSH-ARLT-5090`, in the real
room, before relying on any of it.

---

### H-8 · GPU memory during the live SITREP — resolved on `VSH-ARLT-5090`

**On the laptop:** Whisper and `gemma4:e4b` together used 5.8 of 8.2 GB.

**On `VSH-ARLT-5090`:** a live SITREP run with `gemma4:26b` peaked at
**25.0 GB of 32** ("Four Dogs",
`changelog.md`, 2026-09-29). This depends on the action recogniser's bounded
memory (`changelog.md`, 2026-09-28): before it, Apollon's process took 27.4 GB
on a 17-person scene and pushed most of Gemma into system RAM.

**Re-measure** if the SITREP model changes or a voice-based diarisation model
is added.

---

### H-10 · ONNX Runtime on GPU — resolved, but version-fragile

ONNX Runtime runs on CUDA in both environments: pose in WISE's, and pose, face
and action recognition in Apollon's. How each was made to work is in `changelog.md` (2026-09-11 for
WISE's environment, 2026-09-28 for Apollon's).

**What is installed:**
- **WISE's environment:** `onnxruntime-gpu==1.22.0`, the newest CUDA 12 line.
  `apollon_pose.model` prepends torch's `lib` directory to `PATH`, where a
  complete CUDA 12 runtime already sits.
- **Apollon's environment:** `onnxruntime-gpu[cuda,cudnn]==1.26.0`, declared in
  `pyproject.toml`, which brings the CUDA runtime and cuDNN as
  `nvidia-*-cu12` packages. A uv override drops the CPU `onnxruntime` that
  `rtmlib` and `faster-whisper` ask for. Without torch, `apollon_pose.model` and
  `face.model` put `site-packages/nvidia/*/bin` on `PATH`.

Measured on the RTX 5090:

| Model | On the CPU | On CUDA |
|---|---|---|
| RTMO pose | 43 ms per frame | 8.1 ms per frame |
| Face detection and embedding | ~226 ms per pass | 10.1 ms per pass |
| NTU120 action model, 10 clips | 122 ms | 3.9 ms |

**This is fragile in a specific way.** Both `onnxruntime` packages installed
at once, an `onnxruntime-gpu` line built for a different CUDA major version, or
the CUDA libraries missing from `PATH` each return inference to the CPU
silently — a CUDA provider can be listed and still fail at session creation.
After any change to `onnxruntime-gpu` or torch, check that
`apollon_pose.model.active_provider()` reports `CUDAExecutionProvider`.
`APOLLON_POSE_DEVICE` forces the device.

**Still to do:** the same check for WISE's environment on `VSH-ARLT-5090`,
once Smart Search is installed there.

---

### H-9 · Can the machine be reached remotely?

`knowledge/background/archive/thoughts.md` asks whether the machine can be
controlled remotely to run batch processing — relevant given H-3, since
overnight extraction runs want to be startable without being in the room.

**Open:** whether `VSH-ARLT-5090` is reachable over the network, and where it
will stand.

---

## Working through this list

Suggested order on `VSH-ARLT-5090`:

1. **H-1** — benchmark `gemma4:26b` for p95.
2. **H-4** — settle disk and sampling rate. Expensive to reverse after the first rehearsal week.
3. **H-5**, **H-9** — confirm network access and remote reach where the machine will stand.
4. **H-2**, **H-3**, **H-10** — once Smart Search is installed there: re-test Qwen, re-measure extraction, confirm pose on the GPU.
5. **H-6** — one full-length session in the real room. Do this last, and do it before the first real rehearsal.
