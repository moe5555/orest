WISE pinned at fcfa443fbb46eb361bb19151339338616838a5b5 2026-08-06, cloned 2026-08-29, from github.com/ox-vgg/wise

`external/wise` is a plain clone (not a submodule) and is gitignored by
`external/` in `.gitignore`, so local edits inside it are invisible to this
repo's git and are lost on re-clone. Three Windows fixes are needed on
top of the pinned commit above — see `knowledge/source_of_truth/wise-patches/`
and reapply with `git -C external/wise apply <patch>` after a fresh clone:

- `0001-pin-python-upper-bound.patch` — `environment.yml`, bounds Python to
  `<3.13` so `conda env create` doesn't pick a version newer than torch supports.
- `0002-skip-libmagic-on-windows.patch` — `src/wise/dataloader/utils.py`,
  skips `python-magic` on `win32` (its libmagic build hangs natively there).
- `0003-posix-feature-extractor-ids.patch` — `src/wise/wise_project.py`, builds
  feature extractor ids with `as_posix()` so they stay slash-separated on
  Windows; without it `wise serve` fails to construct any feature extractor.

Patches 0002 and 0003 change installed code, so re-run
`pip install --no-deps --force-reinstall .` in `external/wise` after applying
them. `wise serve` additionally needs the frontend built once:
`npm install && npm run build` in `external/wise/frontend/`.

See `changelog.md` (2026-08-29 and 2026-09-08 entries) for the full story.