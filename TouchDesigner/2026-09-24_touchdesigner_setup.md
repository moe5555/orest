# TouchDesigner setup: OSC receiver, body search, live SITREP

2026-09-24

This covers how `OrestTD.toe` receives search results and the live SITREP from
Orest. The scripts are in `TouchDesigner/code/` and get pasted into DATs. They
have been checked outside TouchDesigner against Orest's own message builders,
but not yet inside TouchDesigner.

## Structure

Orest sends everything to one address, `127.0.0.1:10000` (`src/osc/__init__.py`).
Only one OSC In DAT can hold that port, so a single receiver component listens
and routes each message to the feature component that owns its address prefix.
The two features don't reference each other.

```
/project1/osc_in       osc_in.tox       the OSC In DAT on port 10000, routing only
/project1/bodysearch   bodysearch.tox   /orest/results/…     search results, clips
/project1/sitrep       sitrep.tox       /orest/sitrep/…      the live report
                                        /orest/presence/…    who is in the room
```

Each feature component holds a module DAT with a `handle(address, args)`
function. The function returns `True` for addresses the module owns and
`False` for everything else. The receiver offers each message to every
module in turn.

| File | Goes into | Purpose |
|---|---|---|
| `code/osc_in_callbacks.py` | callbacks DAT of the OSC In DAT in `osc_in` | Routes messages to the feature modules |
| `code/bodysearch_osc.py` | Text DAT `bodysearch_osc` in `bodysearch` | Fills the `results` table |
| `code/sitrep_osc.py` | Text DAT `sitrep_osc` in `sitrep` | Fills the SITREP and presence tables |
| `code/body_search_dat.py` | Panel Execute DAT in `bodysearch` | Sends `/orest/body/start` and `/stop` to port 10001 (unchanged) |

`code/bs_osc_in_callbacks.py` is replaced by `bodysearch_osc.py`. Delete it once
body search works through the new receiver.

## 1. Receiver: `osc_in`

1. Create a Base COMP at `/project1/osc_in`.
2. Inside it, add an **OSC In DAT** with **Network Port** `10000`. If you
   already have one, move it in.
3. Paste `code/osc_in_callbacks.py` into its callbacks DAT.
4. If your feature components live at other paths, edit the `HANDLERS` list at
   the top of the callback. It's the only place the paths are named.
5. Save the component as `osc_in.tox`.

There must be exactly one OSC In DAT on port 10000 in the whole project.

## 2. Body search: `bodysearch`

1. In `/project1/bodysearch`, remove the old OSC In DAT. The receiver replaces
   it.
2. Add a Text DAT named `bodysearch_osc` and paste in `code/bodysearch_osc.py`.
3. Keep the **Table DAT `results`** in the same network. The module writes its
   header row.
4. Leave the OSC Out DAT (`oscout1`, port 10001) and the Panel Execute DAT as
   they are. Sending doesn't conflict with receiving.

Columns of `results`: `rank clip_path ts te score source preroll`. A hit is
added as soon as its clip has been cut, so rank 1 is playable first. Hits
from an earlier search are dropped.

## 3. Live SITREP: `sitrep`

Create a Base COMP at `/project1/sitrep`. It contains no OSC In DAT.

**Video**

1. Add an **NDI In TOP**.
2. Start `uv run orest-sitrep --send-ndi`.
3. In the TOP's **Source** menu, pick the entry ending in `(Orest SITREP)`.

The source name can be changed with `--ndi-name`.

**Text**

1. Add a Text DAT named `sitrep_osc` and paste in `code/sitrep_osc.py`.
2. Add these operators next to it, with exactly these names:

   | Operator | Name | Contents |
   |---|---|---|
   | Table DAT | `sitrep_meta` | One row: id, report number, window, frames, audio seconds, latency, counts, lage, prognose, empfehlung, vertrauen, what was said |
   | Table DAT | `sitrep_personen` | One row per person: `zeile kennung merkmale taetigkeit verantwortungsvoll menschlich gefahr kollaborativ` |
   | Table DAT | `sitrep_ereignisse` | One row per event: `zeile text` |
   | Text DAT | `sitrep_text` | The whole report as readable text |
   | Table DAT | `presence_meta` | One row: `tick zeit anwesend` |
   | Table DAT | `presence` | One row per person present: `zeile label name vermutet aehnlichkeit sichtungen seit dauer_s` |

**Layout: video with the report beneath it**

1. Add a **Text TOP** and set its Text parameter to the Python expression
   `op('sitrep_text').text`.
2. Use a monospace font (e.g. Consolas), left and top alignment, and word
   wrap.
3. Feed the NDI In TOP and the Text TOP into a **Layout TOP**, stacked
   vertically.

Save the component as `sitrep.tox`.

## 4. Test

```powershell
uv run orest-search serve --project test_data_orest       # WISE must be running to cut clips
uv run orest-search body-live --file <recording.mp4> --at 300 --send-td
uv run orest-sitrep --send-ndi --send-td
uv run orest-sitrep --send-ndi --send-td --cast data/cast  # adds the presence roster
```

- **Body search:** `results` fills row by row while clips are cut.
- **SITREP:** the tables and `sitrep_text` are replaced once per report
  window, about every 15 s.
- **Presence:** `presence` updates about twice a second, but only with
  `--cast`.

## How the SITREP tables behave

- **No half-filled reports.** A report's rows are held until
  `/orest/sitrep/end` arrives and are then written all at once. If
  TouchDesigner starts in the middle of a report, that report is skipped and
  the next one appears within a window.
- **The roster only moves forward.** A roster reading is shown only if its
  `tick` is higher than the one on screen, so a late UDP packet can't replace
  a newer reading. When `orest-sitrep` restarts, its ticks begin again at 1,
  and the table accepts that.
- **`presence` and `sitrep_personen` don't match up.** The presence `label`
  and the report `kennung` (P-01, P-02) come from two independent readings of
  the room, so neither table can be used to look up rows in the other.
- **`vermutet = 1` means a guess.** It marks a person the cast gallery didn't
  recognise; for them, `name` is empty.
- **Rating columns are fixed in `sitrep_osc.py`.** `PERSON_HEADER` follows
  `report.BEWERTUNGEN` in `src/sitrep/report.py`. If a rating is renamed
  there, update the header by hand.

## Troubleshooting

| Symptom | Cause |
|---|---|
| Nothing arrives at all | Another OSC In DAT, or another TouchDesigner instance, holds port 10000 |
| A SITREP table stays empty | Wrong operator name. The Textport shows `sitrep_osc: no Table DAT named …` |
| `results` stays empty, with an error in the Textport | The `results` Table DAT is missing, or `HANDLERS` points to the wrong path |
| One feature works and the other doesn't | That component's path in `HANDLERS` doesn't match. A missing component is skipped without an error |
| No NDI source in the menu | `orest-sitrep` was started without `--send-ndi`, or isn't running |
| `presence` stays empty | `--cast` wasn't passed, or `data/cast` has no enrolment photographs yet |

Host and port can be changed on the Orest side with `OREST_TD_HOST` and
`OREST_TD_PORT`. Both `orest-search` and `orest-sitrep` read them.
