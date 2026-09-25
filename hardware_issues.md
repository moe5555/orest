# Hardware Issues

Everything in Orest that is currently limited, blocked or undecided **because of
the machine it runs on**. Written to be worked through in one pass once the
production hardware is settled.

Each issue states what was measured, on what, what it blocks, and what to do
when the final machine exists. Non-hardware risks stay in `claude_concerns.md`;
what was built is in `changelog.md`.

**Nothing here is a code defect.** Every item is a machine constraint, and
several of the design decisions taken so far exist only to work around one.

---

## Reference machines

| Name | Spec | Role so far |
|---|---|---|
| `MININT-ITT28VU` | TongFang GM5IX7A laptop, Win 11, 32 GB RAM, **RTX 4070 Laptop, 8 GB VRAM** | every measurement below unless stated |
| `ctechadmin` | Win 11 workstation, Film University Babelsberg, MDM-enrolled (Sophos + AppLocker) | WISE install only, 2026-08-29 |
| `VSH-ARLT-5090` | Win 11 workstation, i9-14900KF (24 cores / 32 threads), 128 GB RAM, **RTX 5090, 32 GB VRAM**, 514 GB free on C: | **production machine**, from 2026-09-25 |

Confirmed by Moe on 2026-09-11: this machine runs **either** Smart Search **or**
the live SITREP, never both. That removes what would otherwise be the tightest
constraint, and it should be confirmed again for the production machine.

---

## What actually decides this

Three independent properties, in order of how much they change:

1. **VRAM** — H-1, H-2, H-8. At 8 GB, two models have already been rejected for
   it (`gemma4:12b-it-qat`, Qwen3-VL-2B) and a third is in use because it fits,
   not because it is good. This is the number that changes the most.
2. **CPU cores and disk** — H-3, H-4. Stock feature extraction is decode-bound
   rather than GPU-bound, so cores matter more than the card, and the index
   costs ~127 MB per hour of footage.
3. **Network access** — H-5. Decides whether ~15 GB of model weights can be
   fetched on site or must travel with the machine.

The rest (H-6, H-7, H-9) are things that can only be measured in the real room
on the real machine. **H-10 is resolved** but listed because it fails silently
and must be re-confirmed on any new machine or dependency upgrade.

---

## Issues

### H-1 · The SITREP model was chosen for VRAM, not for quality

**Measured:** `gemma4:12b-it-qat` needs 8.5 GB against 8.1 GB available. It runs
30% CPU / 70% GPU, giving p95 latency of 28–30 s at every window size — the VRAM
ceiling, not the model, being the bottleneck. `gemma4:e4b` is resident at 3.2 GB,
100% GPU, p95 4.4–7.6 s.

**Consequence:** e4b is in production use and confabulates heavily — inventing
clothing, speeches and a play title (`claude_concerns.md`, concern 1). On
comparable input the 12b described the scene correctly and correctly left the
speech field empty.

**Blocks:** the accuracy of every SITREP judgement, including the
`gefahr` rating attached to named people.

**At ≥12 GB VRAM:** re-run the 12b fully on GPU and re-measure p95. Much of
concern 1 may simply disappear, which would make prompt-tuning e4b wasted work.
**Do this before investing in any other SITREP accuracy mitigation.**

**On `VSH-ARLT-5090`, 2026-09-25:** `gemma4:26b` (Mixture-of-Experts, 25.2B
parameters, 3.8B active, 18 GB) is pulled and was run on three frames of stage
footage with five people in shot: **3.7 s and 4.2 s warm**, 14.3 s including
the model load, with a description that matched the frame. That is three
generations, not a p95. Still to do: `benchmark.py --model gemma4:26b` for p95
against the window, the same against `gemma4:12b`, and VRAM with Whisper
resident (H-8).

---

### H-2 · Qwen3-VL segment embedding is unusable at 8 GB

**Measured 2026-09-11**, `hf/Qwen/Qwen3-VL-Embedding/2B` on the 12-minute probe:

| | |
|---|---|
| Rate | **55 s per 8-second segment**, still rising at 17 segments |
| VRAM | 7,862 MiB of 8,188 — at the ceiling |
| Speed vs realtime | **13.6× slower** |
| 12-minute probe would take | ~2.7 hours |
| 4h08m corpus would take | **~56 hours** |

For scale, SigLIP2 indexed the same probe in **87 seconds**.

The run was killed at 17 segments. Weights (4.0 GB) stay cached, so a re-test on
better hardware costs nothing but time.

**Consequence:** the Smart Search roadmap was reordered on 2026-09-11. The
segment-level visual index is deferred and the custom pose extractor becomes the
body-search route instead.

**Blocks:** searching by *event* ("someone collapsing") as opposed to by scene
semantics or by limb configuration.

**When hardware is final:** re-run `orest-search add-extractor --project probe
--video-id hf/Qwen/Qwen3-VL-Embedding/2B` and read the iteration rate off the
first 20 segments. Anything near or below realtime makes the index practical;
the 8B build needs a further step up again. Note the model loads in float16
already, so `--enable-autocast` will not help.

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

**Measured:** the full corpus extracted at **6.6× realtime** (4h08m of footage
in 37.6 min). The process held about two cores busy while the GPU idled between
batches. The 12-minute probe, whose file is smaller, ran at 8.4×; the corpus
includes a 4K file.

**Consequence:** a faster GPU alone will not speed up stock extraction much.
Cores, and the decoder, are what matter.

**The same holds for pose.** Per four-second segment, decode costs 498 ms
against 247 ms for pose inference on the GPU. Over the corpus the pose index
took 108.5 minutes, and throughput fell from ~1.3 to ~0.35 segments/s on
reaching the 4K file, with the GPU idle and the CPU at 7–12% — a single
decoder thread working through a stream four times the size. Resolution of the
rehearsal cameras therefore sets indexing time more directly than the GPU does.

**At scale:** `bloom-wise-architecture.md` estimates 1,400 hours for the season.
At 6.6× that is **~9 days of continuous extraction**, which is why that document
recommends running incrementally each night rather than in one pass.

**When hardware is final:** re-measure, and test `--num-workers` above 0 — every
run so far used 0. Downscaling source video to 512px height before extraction is
the documented remedy (`external/wise/docs/Processing-Large-Datasets.md`).

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
alternative is broken (`claude_concerns.md`, item 2).

**Blocks:** nothing yet. It is a purchasing decision.

**When hardware is final:** decide the disk, then decide the visual sampling
rate. 2 fps is the default; 0.5 fps would quarter both thumbnails and vectors
and is described as ample for a static room. **Changing it later means
re-extracting everything**, so it is cheap now and expensive after the first
rehearsal week.

---

### H-5 · Roughly 15 GB of model weights must reach the machine

| Model | Size | Source | Used by |
|---|---|---|---|
| `gemma4:e4b` | 9.6 GB | Ollama registry | live SITREP |
| Whisper `large-v3-turbo` | ~1.6 GB | Hugging Face | transcription |
| Qwen3-VL-Embedding-2B | 4.0 GB | Hugging Face | deferred, see H-2 |
| SigLIP2-512 + MS CLAP | small | Hugging Face | already cached |

The Ollama registry download **failed repeatedly over IPv6 on this machine**
(`WSAECONNABORTED`, all 16 parallel parts). Hugging Face downloads warned that
`hf_xet` is missing and fell back to plain HTTP at 5–9 MB/s.

**When hardware is final:** confirm internet access. If the Probebühne is
offline or on a restricted network, fetch everything in advance and carry the
Hugging Face cache (`~/.cache/huggingface`) and the Ollama model store with the
machine — then run one live session on it before relying on it.

---

### H-6 · Untested at rehearsal scale

Every measurement so far is one person, a laptop webcam and a built-in
microphone array in a domestic room. Unknown on real hardware in a real room:

- **Long sessions.** The longest continuous run is a few minutes. Memory growth,
  Ollama context handling and **thermal throttling over a three-hour rehearsal**
  are all unmeasured, and a laptop chassis is the worst case for the last one.
- **Room acoustics.** Distant speakers on a Probebühne are a far harder audio
  case than a laptop mic at desk distance.
- **Stage lighting.** Auto-exposure behaviour under theatre lighting is untested.
- **Several people at once.** Person re-identification is not implemented.

**When hardware is final:** run one full-length session end to end on the real
machine, in the real room, before relying on any of it.

---

### H-7 · Webcam frame rate varies 10–30 fps under DirectShow

**Observed** on this laptop's webcam, cause not identified. Harmless at the
sparse sampling rate the SITREP uses, and irrelevant once dedicated cameras
replace the webcam.

**When hardware is final:** re-check with the actual rehearsal cameras. Only
matters if this path is ever used for recording rather than sampling.

---

### H-8 · Whisper and Gemma resident together use 5.8 of 8.2 GB

**Measured** during live SITREP operation. It works, with 2.4 GB spare — but
that headroom is what a larger SITREP model (H-1) or speaker diarisation would
have to come out of.

**When hardware is final:** re-measure with whichever model H-1 settles on, and
confirm there is room for diarisation, which is still unimplemented.

---

### H-10 · ONNX Runtime on GPU — RESOLVED 2026-09-11, but version-fragile

**Was:** pose detection ran on CPU at 43 ms/frame because no CUDA provider was
available. **Now:** 9 ms/frame on the GPU, a **4.8x** speedup, and InsightFace
face search gains the same GPU path.

Three separate causes, each of which had to be fixed:

1. **Both `onnxruntime` and `onnxruntime-gpu` were installed.** They share the
   `onnxruntime` module name and install over each other; the CPU build's core
   binding won, so no CUDA provider was offered at all.
2. **`onnxruntime-gpu` 1.29 requires CUDA 13.** This machine has CUDA 12.8, from
   torch. Installing 1.29 alone made the provider *appear* in the list and then
   fail at session creation — `cublasLt64_13.dll` missing — falling back to CPU
   silently. **A listed provider is not a working one**, which is why
   `orest_pose.model.active_provider()` reports what the session actually got.
3. **The CUDA 12 libraries were not on `PATH`.** ONNX Runtime loads its CUDA
   provider as a separate DLL whose own dependencies the Windows loader resolves
   against `PATH`; `os.add_dll_directory()` does not cover that second hop. The
   same defeat as CTranslate2 in `sitrep/transcribe.py`.

**What is installed now:** `onnxruntime-gpu==1.22.0` only, the newest CUDA 12
line, plus `coloredlogs`. `orest_pose.model` prepends torch's `lib` directory to
`PATH` at load, which is where a complete CUDA 12 runtime already sits —
nothing extra was downloaded.

**This is fragile in a specific way.** An upgrade of `onnxruntime-gpu`, or of
torch to a different CUDA line, silently returns pose detection to CPU. It will
not error; it will log a warning and run ~5x slower. Check
`orest_pose.model.active_provider()` after any change to either.

**Orest's own environment is still CPU** for pose, since it has no torch and so
no CUDA runtime. That only affects live queries, where a single clip is 16
frames — about 0.7 s, acceptable — not indexing.

**When hardware is final:** confirm `active_provider()` still reports
`CUDAExecutionProvider`, and match the `onnxruntime-gpu` major line to whatever
CUDA the installed torch brings. `OREST_POSE_DEVICE` forces the device.

---

### H-9 · Which machine, and can it be reached remotely?

`knowledge/components/02_processing.md` specifies only "PC to run local
inference on". `knowledge/background/thoughts.md` asks whether the machine can
be controlled remotely to run batch processing — relevant given H-3, since
overnight extraction runs want to be startable without being in the room.

**Open:** the spec of the machine, whether it is a laptop or a workstation, its
disk, and whether it is reachable over the network.

---

## Working through this list

Suggested order once the machine exists, since the early items change the value
of the later ones:

1. **H-1** — settle the SITREP model. Decides how much SITREP accuracy work is needed at all.
2. **H-10** — confirm pose still runs on the GPU; it is version-fragile and fails quietly.
3. **H-2** — re-test Qwen. Decides whether the roadmap reorder of 2026-09-11 stands.
4. **H-4** — settle disk and sampling rate. Expensive to reverse after the first rehearsal week.
5. **H-3** — re-measure extraction, test `--num-workers`, decide on downscaling.
6. **H-5** — get the weights onto the machine and prove one cold run.
7. **H-8**, **H-7** — re-measure in passing.
8. **H-6** — one full-length session in the real room. Do this last, and do it before the first real rehearsal.
