# Changelog

Central development log for Orest. Newest entries first. See
`knowledge/KNOWLEDGE_BASE.md` for pointers into the Source of Truth files
referenced below.

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
workarounds. Two local patches to vendored WISE — `environment.yml`
(Python bound) and `src/wise/dataloader/utils.py` (libmagic skip) — will
need reapplying if `external/wise` is re-pulled from upstream at a newer
commit.
