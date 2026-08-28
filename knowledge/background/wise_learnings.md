# WISE: Practical Learnings (macOS arm64)

Notes from getting WISE running on an Apple-silicon Mac and indexing a first
collection. Written for carrying into a follow-on project.

Environment of record: macOS 15 (Darwin 25.5), arm64, miniconda at
`/opt/miniconda3`, conda env `wise`, Python 3.12, torch 2.8.0 (MPS).

---

## 1. The headline problem: duplicate OpenMP runtimes

This cost the most time and was the hardest to see, because **it produces no
Python traceback**.

A pip-installed ML stack on macOS ends up with several copies of the OpenMP
runtime, because multiple wheels each vendor their own:

```
lib/libiomp5.dylib                            (conda, via mkl/blas)
lib/libomp.dylib                              (conda)
site-packages/torch/lib/libomp.dylib          (pytorch wheel)
site-packages/faiss/.dylibs/libomp.dylib      (faiss wheel)
site-packages/sklearn/.dylibs/libomp.dylib    (scikit-learn wheel)
```

Three of them load into the same process and collide. Two different failures:

| Command | Exit code | What you see |
|---|---|---|
| `extract-features` | 139 = SIGSEGV | Nothing. Process vanishes during model init |
| `create-index` | 134 = SIGABRT | `OMP: Error #15: Initializing libomp.dylib, but found libomp.dylib already initialized` |

The segfault is the dangerous one. It left a project that looked half-plausible:
12 media rows registered with correct durations, and **zero vectors**. Nothing in
the logs said "failed".

**Fix — both variables, they solve different halves:**

```bash
export OMP_NUM_THREADS=1         # prevents the SIGSEGV in __kmp_fork_barrier
export KMP_DUPLICATE_LIB_OK=TRUE # lets faiss proceed past its duplicate check
```

`KMP_DUPLICATE_LIB_OK` is officially "unsafe, unsupported, undocumented" and may
"silently produce incorrect results" — so **verify output, don't trust exit 0**.
We checked top-k results against known content (a query for "white text on a
black background" returned t=1.0/4.0/4.5s — the opening title cards) before
accepting the index.

Cleaner long-term fixes, in preference order:
1. Get all OpenMP-using packages from one source (all conda-forge, or all pip),
   so a single runtime is linked.
2. Symlink the vendored copies to one file (works, but fragile across upgrades).
3. The env vars above (what we did — fast, reversible).

### Generalisable lesson
When a Python ML process dies with no traceback, **check the exit code**:

```bash
cmd; echo "EXIT=$?"     # 139 = SIGSEGV, 134 = SIGABRT, 137 = SIGKILL/OOM
ls -t ~/Library/Logs/DiagnosticReports/ | head   # macOS logs a full .ips report
```

The `.ips` crash report is JSON after the first line, and names the faulting
thread and every loaded dylib. That is what identified libomp here:

```python
d = json.loads(open(report).read().split("\n", 1)[1])
th = d["threads"][d["faultingThread"]]
```

---

## 2. Dependency resolution on macOS

Three separate install failures, each with a different shape.

### 2a. `onnxruntime-gpu` has no macOS wheels
An undeclared dependency of `insightface`. Only Linux/Windows builds exist.
Environment markers handle it without breaking other platforms:

```
onnxruntime-gpu; platform_system != "Darwin"
onnxruntime; platform_system == "Darwin"
```

### 2b. `tritonclient[all]` drags in Linux-only packages
The `all` extra = `http` + `grpc` + `cuda` + `perf-analyzer`. The latter two
(`cuda-python`, `perf-analyzer`) have no macOS wheels.

The failure was **wildly misleading**: pip backtracked through every tritonclient
release hunting for one whose deps resolve, reached 2.22.x which pins
`grpcio==1.41.0` (sdist only), tried to build it from source, and died on
`ModuleNotFoundError: No module named 'pkg_resources'`. The error named grpcio
and setuptools — neither was the problem.

```
tritonclient[all]; platform_system != "Darwin"
tritonclient[http,grpc]; platform_system == "Darwin"
```

**Lesson:** when pip reports a build error for an *old* version of a package you
never pinned, you are looking at backtracking. Read *upward* in the log to find
the first `INFO: pip is looking at multiple versions of X` — X is the real
culprit.

### 2c. Python version bounds are load-bearing
`python>=3.10` let conda pick 3.14, which broke things twice over:

- **3.14:** `torch<2.9` has no cp314 wheels. Loud, obvious failure.
- **3.13:** `ml-dtypes>=0.5` requires `numpy>=2.1`, but `msclap` pins
  `numpy<2.0.0`. pip silently resolved back to ml-dtypes 0.4.1 — too old for
  onnx 1.19. **Install succeeded**; `import insightface` then failed with
  `module 'ml_dtypes' has no attribute 'float4_e2m1fn'`.

The 3.13 case is the instructive one: a green install is not a working install.
Correct bound was `python>=3.10,<3.13`.

**Lesson:** always pin an upper Python bound derived from your heaviest pinned
dependency. And check transitive markers — `ml-dtypes` declares a *different*
numpy floor per Python version.

### 2d. `conda env create` silently ignores package specs
```bash
conda env create --name wise --file environment.yml python=3.12   # python= IGNORED
```
It parses `python=3.12` as `remote_definition` (a URL for a remote env file) and
discards it, warning only via a `FutureWarning` that is easy to miss. The Python
version **must** come from the YAML file.

---

## 3. Namespace-package shadowing

The repo has a `triton/` directory (a Triton Inference Server model repo — not
Python). With no `__init__.py`, Python treats it as a **namespace package**, so
`import triton` *succeeds* and returns an empty module.

torch then fails with `ModuleNotFoundError: No module named 'triton.language'`
instead of the clean `No module named 'triton'` it knows how to handle on
GPU-less machines.

Triggered by anything that puts CWD on `sys.path`:

| Invocation | CWD on sys.path? |
|---|---|
| `python -m pytest` | **yes** — 7 spurious test failures |
| `python - <<EOF` heredoc | **yes** |
| `pytest` | no |
| console script (`wise`) | no — uses the script's own dir |

With `pytest src/ -q` the suite was 43/43 green; with `python -m pytest`, 36/7.
**Same code, same env, different invocation.**

**Lesson:** a non-Python directory at your repo root whose name collides with a
PyPI package is a latent trap. `python -m X` is not a synonym for `X`.

---

## 4. Editable installs and IDE interpreters

Two related traps:

- `conda env remove` can leave pip-installed files behind in the prefix. A stale,
  **non-editable** copy of the project survived an env rebuild and was silently
  shadowing the working tree — edits to `src/` had no effect on the `wise`
  command. Check with `pip show <pkg>` and look at `Location` /
  `dist-info/direct_url.json`.
- `ModuleNotFoundError: No module named 'wise'` when hitting the IDE Run button
  means the IDE is using a different interpreter (system or conda `base`), not
  the env. In VS Code: `Cmd+Shift+P` → "Python: Select Interpreter".

Always `pip install -e . --no-deps` for a repo you are editing, and never run
`src/pkg/__main__.py` as a file — Python puts `src/pkg/` on the path, not `src/`.

---

## 5. WISE architecture, in brief

The core idea: media and text are embedded into a **shared vector space**, so
search is nearest-neighbour lookup. SigLIP2 handles image/video↔text; CLAP
handles audio↔text. Media is **chunked** before embedding, which is why a hit
points into a video at a timestamp.

```
your folders ──▶ extract-features ──▶ create-index ──▶ serve
                 decode, chunk,        build FAISS      FastAPI + web UI
                 embed, store          from vectors
```

### The project folder is self-contained — except your media

```
wise-projects/NAME/
├── metadata/internal.db      # source_collections → media → vectors → …
├── thumbs.db                 # thumbnails (separate DB)
└── store/<org>/<repo>/<model>/<dataset>/
    ├── features/video-000000.faiss
    └── index/video-IndexFlatIP.faiss
```

It stores **paths, not copies**. Moving or renaming source media breaks playback.

### Feature extractor IDs are namespaces
`ORG/REPO/MODEL/DATASET` — dispatches the factory *and* becomes the on-disk
directory path. Prefix with `triton://host:port/` to route inference to a Triton
server with no other change.

### Three modes, inferred from arguments
| You pass | Mode | Effect |
|---|---|---|
| folders + empty project dir | `create` | fresh project |
| folders + existing project | `add_media` | adds media, reuses extractors |
| **no** folders + existing project | `add_feature_extractor` | re-embeds existing media with a new model |

The third is genuinely useful: add face or object search later without
re-scanning the source drive. Re-run `create-index` after any extraction.

### Gotcha: the extractor default is all-or-nothing
Defaults (SigLIP2 for image+video, CLAP for audio) apply **only if you name no
extractors at all**. Pass `--image-feature-id X` alone and audio silently
defaults to empty — no audio search, no error.

---

## 6. Operational numbers

12 MP4 trailers, 1,496s (~25 min) total, 436 MB, on MPS:

- **31.5 min** extraction wall time, ~1.8 chunks/s
- **2,993** video vectors — exactly `duration × 2fps`, the default sample rate
- **369** audio vectors — one per ~4s segment
- **2,993** thumbnails
- Index build: **under 1 second** (`IndexFlatIP` is exact/brute-force)

Rough planning figure: **~1.25 min of processing per 1 min of video** on M-series
CPU/MPS. `FaissStore` buffers in memory and only writes a shard at
`--shard-maxcount` (2^19) or at the end, so **`store/` staying at 0 B mid-run is
normal**, not a failure.

### Health check for a project
```bash
curl -s localhost:9670/PROJECT/info
```
`num_vectors: 0` and `search_targets: {}` mean extraction never produced
anything — and an empty `search_targets` is what makes the web UI spin forever
and blank out on hover. **The UI has no error state for an empty index**; it just
breaks. Check `/info` first, always.

---

## 7. Checklist for the next project

```bash
# 1. Pin Python from the YAML, not the CLI
#    python>=3.10,<3.13   (derived from the heaviest pinned dep)

# 2. Platform-mark the Linux-only deps
#    onnxruntime-gpu / tritonclient[all] → Darwin alternatives

# 3. Set the OpenMP vars before ANY wise command
export OMP_NUM_THREADS=1 KMP_DUPLICATE_LIB_OK=TRUE

# 4. Editable install of the project itself
pip install -e . --no-deps

# 5. Prove the env works before touching real data
pytest src/ -q                              # NOT python -m pytest
bash tests/test-wikimedia-commons-25.sh /tmp/wise-test/

# 6. Build the frontend before `serve`, and run it from the repo root
cd frontend && npm install && npm run build && cd ..

# 7. After every extraction: check /info before opening the browser
```

**The meta-lesson:** at three separate points in this process, a command exited
0 (or installed cleanly) while having accomplished nothing or something wrong —
the ml-dtypes downgrade, the segfaulting extraction, the `python=3.12` that was
discarded. Verify the *artifact*, not the *exit status*: count the vectors,
import the module, check the resolved version.
