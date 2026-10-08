# Body search video wall

2026-10-08

A full-screen wall of 1 to 99 tiles showing body search results in a loop.
Hold space to capture a movement; release it to search. Each tile keeps looping
its clip until the next search replaces it.

| Key | Effect |
|---|---|
| Space, held | Captures while held; releasing stops the capture and searches |
| A digit | Number of tiles, set on release: 1 full screen, 2 side by side, 4 as 2×2, 9 as 3×3 |
| Two digits | Hold the first, press the second, release both: hold 1, press 6 → 16 tiles (4×4) |
| F1 | Opens the wall full screen |
| Esc | Closes it |

The keys only work while the wall is open (F1), so space in the network editor
still pans and can't start a capture.

It builds on the body search component of `Apollon_TD_New.toe`; see
`2026-10-08_body_search_setup.md` for that, including the fixes in its step 1.

## 1. Build the wall

The wall is built by a script, so no player has to be placed by hand. Open
`Apollon_TD_New.toe`, open the Textport (Alt+T) and paste this line exactly:

```python
exec(open(project.folder + '/code/build_wall.py').read())
```

It ends with `build_wall: 4 tiles, F1 opens the wall, Esc closes it`. In
`/project1/bodysearch` it creates:

| Operator | Role |
|---|---|
| `Tiles` | New parameter on `bodysearch` (page *Wall*): how many tiles, 1–99 |
| `tile` | The master player. Edit this one; every tile is a copy |
| `tiles` | Replicator COMP, makes one copy of `tile` per tile, inside itself |
| `tiles_callbacks` | Its callbacks (from `code/tiles_callbacks.py`): write the tiles into `wall` in rank order whenever tiles are added or removed |
| `wall` | Layout TOP, arranges the copies in a grid at 1920×1080 |
| `wall_window` | Window COMP showing `wall`, set as the Perform Window |
| `keys`, `wall_keys` | Keyboard In DAT and its callbacks (from `code/wall_keys.py`) |

Tile n plays row n of `results`, which is the search result of rank n. Changing
`Tiles` adds or removes copies.

`moviefilein1`–`3` and `out1`–`3` from before are no longer needed. Delete them,
since each one decodes a clip whether it's shown or not.

Save the project (Ctrl+S). Running the script again is safe; it updates what
exists.

**On the projector:** select `wall_window` and set **Display** to the
projector's monitor index (0 is the primary display). If the projector isn't
1920×1080, change `RESOLUTION` at the top of `code/build_wall.py` and run it
again.

**If the script stops with a `ValueError`,** a menu entry is named differently
in this TouchDesigner build. The error lists the available names; send it to
Claude.

## 2. Start Apollon

```powershell
uv run apollon-search serve --project hitl_database
uv run apollon-search body-live --project hitl_database --video "<part of the camera name>" --segments --send-td
```

`--segments` makes every result the matched four-second window, so each tile
loops one short movement. Clips are re-encoded and start exactly on the
movement.

**Variety:** results from one recording are at least 30 s apart, so tiles
don't show neighbouring seconds of one passage. To also spread them across
rehearsals, add `--per-file 3` (at most three per recording). `--min-gap 60`
spreads them further in time; `--min-gap 0` turns the spacing off.

**Results per search:** `body-live` sends 10 by default. For more tiles, add
`-n` with the largest tile count you'll use, e.g. `-n 16`; tiles beyond the
number of results stay black. Each clip takes about 0.6 s to cut, so 16 tiles
take about 10 s to fill, best result first. Every tile decodes a full 1080p
clip, so very large walls are limited by decoding in TouchDesigner.

To rehearse without a camera, replace `--video …` with
`--file "C:\Users\video\Desktop\HITL_Database\2026-10-07 11-12-31_DeathScene.mp4" --at 120`.

## 3. Use

1. Press F1. The wall opens full screen.
2. Hold space while the movement is performed. Terminal 2 prints `capturing …`.
3. Release. Terminal 2 prints the results, and the tiles switch to the new clips
   one by one, about a second apart, best result in the top-left tile.
4. The clips loop until the next capture. Until its new clip is ready, each
   tile keeps looping its old one, so there are no black gaps.

A capture shorter than four seconds is extended backwards from the release.
A tile stays black only if the search returned fewer results than there are
tiles.

## First-time checks

Two details of TouchDesigner's behaviour could not be checked outside it:

- **Order:** the top-left tile should show result 1 (compare with the first line
  terminal 2 prints).
- **Restart:** a tile that gets a new clip should start it from the beginning.

If either is off, note what you see and send it to Claude.

## Troubleshooting

| Symptom | Cause |
|---|---|
| Space or the number keys do nothing | The wall isn't open (F1). The keys only work there |
| Space opens a capture but releasing does nothing | `wall_keys` isn't the **Callbacks DAT** of `keys`, or `body-live` isn't running |
| Tiles stay black after a search | `results` stays empty: see `2026-10-08_body_search_setup.md`, step 1a |
| F1 opens something else | Pulse **Set as Perform Window** on `wall_window` |
| The wall opens on the wrong screen | **Display** on `wall_window` |
| Tiles show a few seconds before the movement | Clips cut with `--cut fast`. The wall doesn't trim preroll; drop the option |
