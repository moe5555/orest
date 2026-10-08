# Body search in `Apollon_TD_New.toe`

2026-10-08

Performing a movement in front of a camera, capturing it with a button in
TouchDesigner and getting the rehearsal moments where the same movement
happened, as playable clips. The search runs over the WISE project
`hitl_database`.

`Apollon_TD_New.toe` already contains everything needed. Four things in it are
out of date or wrong and need fixing before the first search. They are listed in
step 1. `2026-09-25_touchdesigner_setup.md` describes how the component was
built from scratch.

## How it fits together

```
camera ──► apollon-search body-live ──► WISE (serve) ──► clips in data/clips/hitl_database/
                ▲                                              │
   /apollon/body/start, /stop                     /apollon/results/… (begin, hit, end)
   OSC to 127.0.0.1:10001                         OSC to 127.0.0.1:10000
                │                                              ▼
           button1 ─ panelexec1 ─ oscout1      osc_in ─► bodysearch_osc ─► results ─► moviefilein1–3
```

Pressing the button starts a capture, releasing it stops the capture and runs
the search. Each result is cut into a clip and announced as soon as it exists,
best result first, so `moviefilein1` can play before the rest are cut.

What is in `/project1/bodysearch`:

| Operator | Role |
|---|---|
| `button1` | Toggle button: on starts a capture, off stops it and searches |
| `panelexec1` | Sends start and stop when `button1` changes |
| `oscout1` | OSC Out DAT to `127.0.0.1:10001`, where `body-live` listens |
| `bodysearch_osc` | Writes incoming results into `results` |
| `results` | One row per result: `rank clip_path ts te score source preroll` |
| `rank` | Constant CHOP, which result each player shows: `chan1` 1, `chan2` 2, `chan3` 3 |
| `moviefilein1`–`3` | Play the results picked by `rank`, trimmed by `preroll` |
| `out1`–`3` | Out TOPs of the three players |

The receiver `/project1/osc_in` (OSC In DAT on port 10000) forwards everything
under `/apollon/results/` to `bodysearch_osc`.

## 1. Fix the project

Open `TouchDesigner/Apollon_TD_New.toe`.

**1a. `bodysearch_osc` still listens to the old name.** It accepts only
`/orest/results/…`, so every result Apollon sends is ignored. The file on disk is
current, but this DAT doesn't sync with it.

1. Select `/project1/bodysearch/bodysearch_osc`.
2. On its **DAT** parameter page, check that **File** is `code/bodysearch_osc.py`.
3. Pulse **Load File Now**, then turn on **Sync to File**.
4. Open the DAT: line 26 must read `if not address.startswith('/apollon/results/'):`.

**1b. `oscin1_callbacks` the same way.** Only its comments are out of date, so
it works as it is. Syncing it keeps it current with `code/`. In
`/project1/osc_in/oscin1_callbacks`, pulse **Load File Now** and turn on
**Sync to File**.

**1c. `panelexec1` is switched off and watches a button that doesn't exist.**
Select `/project1/bodysearch/panelexec1`:

1. **Active**: on.
2. **Panels**: `button1`. It currently says `button`.
3. **Off to On** and **On to Off**: both on.
4. Open the DAT and check it sends `/apollon/body/start` and `/apollon/body/stop`.
   It syncs from `code/body_search_dat.py` and should already be current.
   If it still says `/orest/`, pulse **Load File Now**.

**1d. `moviefilein2` and `moviefilein3` trim by the wrong clip's preroll.** Both
take their **Trim Start** from result 1 instead of their own, so they skip the
wrong amount. Their guards also check the wrong row. `moviefilein1` is correct.
Replace both expressions on each TOP.

`moviefilein2`, **File**:

```python
op('results')[int(op('rank')['chan2']), 'clip_path'].val if op('results').numRows > int(op('rank')['chan2']) else ''
```

`moviefilein2`, **Trim Start** (unit: seconds):

```python
float(op('results')[int(op('rank')['chan2']), 'preroll'].val) if op('results').numRows > int(op('rank')['chan2']) else 0
```

`moviefilein3`, **File**:

```python
op('results')[int(op('rank')['chan3']), 'clip_path'].val if op('results').numRows > int(op('rank')['chan3']) else ''
```

`moviefilein3`, **Trim Start** (unit: seconds):

```python
float(op('results')[int(op('rank')['chan3']), 'preroll'].val) if op('results').numRows > int(op('rank')['chan3']) else 0
```

**Trim** must stay on for all three. To show other results, change the values in
`rank`: setting `chan1` to 4 makes `moviefilein1` play the fourth result.

Save the project (Ctrl+S).

`results` still holds rows from a search on the old laptop, with paths under
`C:/Users/ctech/…`. The players show a file error until the first search
replaces them. That is expected.

## 2. Start Apollon

Two PowerShell terminals, both in `C:\Users\video\Desktop\orest`.

**Terminal 1, the search server.** Keep it running, since every search goes
through it:

```powershell
uv run apollon-search serve --project hitl_database
```

**Terminal 2, the capture.** First rehearse with a recording instead of the
camera. `--file` plays a file in real time as if it were the camera:

```powershell
uv run apollon-search body-live --project hitl_database --file "C:\Users\video\Desktop\HITL_Database\2026-10-07 11-12-31_DeathScene.mp4" --at 120 --send-td
```

Wait for `ready - Enter or /apollon/body/start …`.

## 3. First search

1. In TouchDesigner, turn `button1` on. Terminal 2 prints `capturing …`.
2. After about four seconds, turn it off. Terminal 2 prints
   `captured …`, the result table, and one line per clip as it is cut.
3. `results` fills row by row and `moviefilein1` plays result 1.

**Check:** the recording is part of the index, so result 1 should be that same
recording near the playback position at the moment of capture. The clip should
open on the movement you saw in the playback.

Clips are re-encoded, so each starts exactly on its result and `preroll` is 0.
The Trim Start expressions then have nothing to skip, and only matter for clips
cut with `--cut fast`.

## 4. Search with the camera

Stop terminal 2 (Ctrl+C) and start it with the camera:

```powershell
uv run python -m sitrep.devices --list
uv run apollon-search body-live --project hitl_database --video "<part of the camera name>" --send-td
```

Without `--video`, the system's default camera is used. Useful options:

- Results from one recording are at least 30 s apart by default, so they
  aren't neighbouring moments of one passage. `--min-gap 60` spreads them
  further, `--min-gap 0` turns it off.
- `--per-file 2` keeps at most two results from one recording, so the results
  aren't all from the same long rehearsal.
- `--segments` returns the indexed four-second windows instead of merged spans.
  Every clip is four seconds long. Merged spans can run to a minute or more.
- `-n 5` returns five results instead of ten.
- `--cut fast` copies the stream instead of re-encoding: about 0.15 s per clip
  instead of 0.6–1.2 s, but each clip starts up to 10 s early and relies on
  the preroll trim, which makes players show black or freeze. Only worth it for
  recordings with a keyframe every 1–2 s.

A capture shorter than four seconds is extended backwards from the stop. A
longer one is searched in four-second windows and the results are merged. Only
the largest body in the picture counts, both in the capture and in the index.

## Troubleshooting

| Symptom | Cause |
|---|---|
| The button does nothing in terminal 2 | `panelexec1` not active, **Panels** not `button1`, or **Off to On** / **On to Off** off (step 1c). Or `body-live` isn't running |
| Terminal 2 searches, but `results` stays unchanged | `bodysearch_osc` still checks for `/orest/results/` (step 1a) |
| `No body found in the capture.` | Nobody visible during the capture, or too dark for pose detection |
| `No WISE server at …` in terminal 2 | Terminal 1 isn't running, or serves a different project |
| `results` fills, players show a file error | The clip path doesn't exist. Check the path in `results` against `data/clips/hitl_database/` |
| A player shows black or a frozen frame | The clips were cut with `--cut fast`. Drop the option |
| A clip opens a few seconds before the movement | A fast clip whose preroll isn't trimmed. Check **Trim** is on and **Trim Start** is in seconds, or drop `--cut fast` |
| Players 2 and 3 are black for about a second after each search | Expected: their clips are still being cut. They stay black if the search returned fewer results |
| Players 2 and 3 skip into their clip | The old expressions are still in place (step 1d) |
| A new clip starts somewhere in the middle | The TOP's **Play Mode** follows the timeline. Set it to *Sequential* |
| Nothing arrives at all | Another OSC In DAT or a second TouchDesigner instance holds port 10000 |
