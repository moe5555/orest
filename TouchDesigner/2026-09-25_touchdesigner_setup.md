# TouchDesigner setup: OSC receiver, body search, live SITREP

2026-09-25

These instructions build Orest's TouchDesigner project from an empty file. It
receives search results and the live SITREP from Orest, and it starts and
stops live body captures. The scripts are in `TouchDesigner/code/` and get
pasted into DATs. They have been checked outside TouchDesigner against Orest's
own message builders, but not yet inside TouchDesigner.

## Structure

Orest sends everything to one address, `127.0.0.1:10000` (`src/osc/__init__.py`).
Only one OSC In DAT can hold that port, so a single receiver component listens
and routes each message to the feature component that owns its address prefix.
The two features don't reference each other.

```
/project1/osc_in       OSC In DAT on port 10000, routing only
/project1/bodysearch   /orest/results/…      search results, clip playback,
                                             start/stop of live captures
/project1/sitrep       /orest/sitrep/…       the live report
                       /orest/presence/…     who is in the room
```

Each feature component holds a module DAT with a `handle(address, args)`
function. The function returns `True` for addresses the module owns and
`False` for everything else. The receiver offers each message to every
module in turn.

| File | Goes into |
|---|---|
| `code/osc_in_callbacks.py` | callbacks DAT of the OSC In DAT in `osc_in` |
| `code/bodysearch_osc.py` | Text DAT `bodysearch_osc` in `bodysearch` |
| `code/body_search_dat.py` | Panel Execute DAT in `bodysearch` |
| `code/sitrep_osc.py` | Text DAT `sitrep_osc` in `sitrep` |

Operator names matter: the scripts find their tables and operators by name.
Rename each operator as you create it.

Start with a new project (File → New) and work inside `/project1`.

## 1. Receiver: `osc_in`

1. Create a **Base COMP** named `osc_in` and go inside it.
2. Add an **OSC In DAT** and set **Network Port** to `10000`.
3. The OSC In DAT's **Callbacks DAT** parameter names a docked Text DAT
   (`oscin1_callbacks`). Replace that DAT's contents with
   `code/osc_in_callbacks.py`.
4. Right-click the COMP → **Save Component .tox** → `TouchDesigner/osc_in.tox`.

There must be exactly one OSC In DAT on port 10000 in the whole project.

The `HANDLERS` list at the top of the callback names the two feature modules
by path: `/project1/bodysearch/bodysearch_osc` and
`/project1/sitrep/sitrep_osc`. If you name the components differently, edit
the list. A component that doesn't exist yet is skipped, so you can test the
receiver before both features are built.

## 2. Body search: `bodysearch`

Create a **Base COMP** named `bodysearch` and go inside it.

**Receiving results**

1. Add a **Text DAT** named `bodysearch_osc` and paste in
   `code/bodysearch_osc.py`.
2. Add a **Table DAT** named `results`. Leave it empty; the module writes the
   header row.

Columns of `results`: `rank clip_path ts te score source preroll`. A hit is
added as soon as its clip has been cut, so rank 1 is playable first. Hits
from an earlier search are dropped.

**Starting and stopping a live capture**

`orest-search body-live` listens for `/orest/body/start` and `/orest/body/stop`
on port 10001.

1. Add an **OSC Out DAT** named `oscout1`, with **Network Address**
   `127.0.0.1` and **Network Port** `10001`.
2. Add a **Button COMP** and set **Button Type** to *Toggle Down*. On sends
   start and off sends stop.
3. Add a **Panel Execute DAT**:
   - Set **Panels** to the button.
   - Turn on **Off to On** and **On to Off**.
   - Replace its contents with `code/body_search_dat.py`.

**Playing a result**

1. Add a **Movie File In TOP**.
2. Set its **File** parameter to the Python expression
   `op('results')[1, 'clip_path']` for the best result. Use row 2 for the
   second-best result, and so on.

Fast clips begin at the keyframe before the hit. `preroll` is the number of
seconds to skip, and TouchDesigner has to trim them itself, because it ignores
the edit list that hides them in other players. Trimming on the Movie File In
TOP is not verified yet (`changelog.md`, 2026-09-17). Clips cut with
`--cut precise` have a preroll of 0.

Save as `TouchDesigner/bodysearch.tox`.

## 3. Live SITREP: `sitrep`

Create a **Base COMP** named `sitrep` and go inside it. It contains no OSC In
DAT.

**Video**

1. Add an **NDI In TOP**.
2. Start `uv run orest-sitrep --send-ndi`.
3. In the TOP's **Source** menu, pick the entry ending in `(Orest SITREP)`.

The source name can be changed with `--ndi-name`.

**Text**

1. Add a **Text DAT** named `sitrep_osc` and paste in `code/sitrep_osc.py`.
2. Add these operators next to it and rename each one to exactly the name
   given. Don't enter anything into them. The module finds each table by its
   name, clears it and writes the header row and the data whenever a report
   arrives. The Contents column describes what it will write.

   | Operator | Name | Contents |
   |---|---|---|
   | Table DAT | `sitrep_meta` | One row: `id nummer beginn ende dauer_s bilder ton_s latenz_s personen prognosen beschreibung gesagt relevanz eskalation gefahr einschreiten massnahme` |
   | Table DAT | `sitrep_personen` | One row per person: `zeile name vermutet beschreibung kollaborativ relevanz verantwortungsvoll menschlich gefahr` |
   | Table DAT | `sitrep_prognose` | The three forecasts, most likely first: `rang wahrscheinlichkeit verlauf` |
   | Text DAT | `sitrep_text` | The whole report as readable text |
   | Table DAT | `presence_meta` | One row: `tick zeit anwesend` |
   | Table DAT | `presence` | One row per person present: `zeile label name vermutet aehnlichkeit sichtungen seit dauer_s` |

**Check the wiring without Orest**

Feed the module one made-up report. Open the Textport (Alt+T) and paste the
lines below. Python rejects leading spaces here, so copy the lines exactly as
they are, without indentation.

```python
m = op('/project1/sitrep/sitrep_osc').module
m.handle('/orest/sitrep/begin', ['t1', 1, '2026-09-25T12:00:00', '2026-09-25T12:00:15', 15.0, 3, 15.0, 4.2, 1, 3])
m.handle('/orest/sitrep/beschreibung', ['t1', 'Testbericht.'])
m.handle('/orest/sitrep/gesagt', ['t1', ''])
m.handle('/orest/sitrep/person', ['t1', 1, 'Vielleicht: Jakob', 1, 'Steht mittig.', 3, 4, 2, 3, 0])
m.handle('/orest/sitrep/szene', ['t1', 5, 7, 2])
m.handle('/orest/sitrep/prognose', ['t1', 1, 60, 'Fortsetzung.'])
m.handle('/orest/sitrep/prognose', ['t1', 2, 30, 'Abgang.'])
m.handle('/orest/sitrep/prognose', ['t1', 3, 10, 'Streit.'])
m.handle('/orest/sitrep/empfehlung', ['t1', 1, 'Probe unterbrechen.'])
m.handle('/orest/sitrep/end', ['t1'])
```

`sitrep_meta`, `sitrep_personen`, `sitrep_prognose` and `sitrep_text` fill in
after the last line. If one stays empty, the Textport names the table it
couldn't find. If the first line fails, the COMP isn't at `/project1/sitrep`;
adjust the path.

**Where the report is displayed**

The SITREP isn't laid out in TouchDesigner. The operator page shows the camera
with the report beneath it (`orest-ui`, see the README). TouchDesigner receives
the report as data, for driving effects or cues from values such as
`eskalation`, `gefahr` or `einschreiten` in `sitrep_meta`. `sitrep_text` stays
available as a quick way to read a report inside TouchDesigner.

Save as `TouchDesigner/sitrep.tox`.

## 4. Test

Save the project and test each part on its own.

```powershell
# Body search: WISE must be running, since clips are cut through it
uv run orest-search serve --project test_data_orest
uv run orest-search body-live --file <recording.mp4> --at 300 --send-td

# SITREP
uv run orest-sitrep --send-ndi --send-td --model gemma4:26b
uv run orest-sitrep --send-ndi --send-td --model gemma4:26b --cast data/cast  # recognises the cast
```

- **Body search:** toggling the button on and then off runs a search.
  `results` fills row by row while clips are cut, and the Movie File In TOP
  plays rank 1.
- **SITREP:** the tables and `sitrep_text` are replaced once per report
  window, about every 15 s.
- **Presence:** `presence` updates about twice a second. Without `--cast`,
  every name in it is a guess.

## How the SITREP tables behave

- **No half-filled reports.** A report's rows are held until
  `/orest/sitrep/end` arrives and are then written all at once. If
  TouchDesigner starts in the middle of a report, that report is skipped and
  the next one appears within a window.
- **The roster only moves forward.** A roster reading is shown only if its
  `tick` is higher than the one on screen, so a late UDP packet can't replace
  a newer reading. When `orest-sitrep` restarts, its ticks begin again at 1,
  and the table accepts that.
- **Report names come from the roster.** Each `name` in `sitrep_personen` is
  either a `label` from `presence` during that report's window or
  `Unbekannt`, for someone in frame whose face wasn't tracked. Orest draws
  each name above its face in the frames the model sees, so the model reads
  who is who. The NDI picture in TouchDesigner stays unmarked.
- **`vermutet = 1` means not recognised.** In `sitrep_personen` it marks a
  guessed name (`Vielleicht: Jakob`) or `Unbekannt`. In `presence` it marks a
  guessed name, and `name` is then empty.
- **Forecasts are ranked.** `sitrep_prognose` always has three rows, `rang` 1
  being the most likely. Orest sorts them, so the order doesn't depend on how
  the model listed them.
- **Scene ratings run 0–10.** `relevanz`, `eskalation` and `gefahr` in
  `sitrep_meta` rate the scene as a whole, from low to high. They're separate
  from the 0–5 ratings per person.
- **`einschreiten` follows from the scene ratings.** It's 1 when `eskalation`
  or `gefahr` is above 6, and only then does `massnahme` hold a recommended
  action. The model doesn't decide it.
- **Rating columns are fixed in `sitrep_osc.py`.** `PERSON_HEADER` follows
  `report.BEWERTUNGEN` in `src/sitrep/report.py`. If a rating is renamed
  there, update the header by hand.

## Troubleshooting

| Symptom | Cause |
|---|---|
| Nothing arrives at all | Another OSC In DAT, or another TouchDesigner instance, holds port 10000 |
| A SITREP table stays empty | Wrong operator name. The Textport shows `sitrep_osc: no Table DAT named …` |
| `results` stays empty, with an error in the Textport | The `results` Table DAT is missing or named differently |
| One feature works and the other doesn't | That component's path in `HANDLERS` doesn't match. A missing component is skipped without an error |
| The button doesn't start a capture | `body-live` isn't running, the OSC Out DAT isn't named `oscout1`, or it isn't set to port 10001 |
| No NDI source in the menu | `orest-sitrep` was started without `--send-ndi`, or isn't running |
| `presence` stays empty | `--send-td` wasn't passed, or no face is visible to the camera |
| Everyone is `Unbekannt` | No face was tracked during the window: the camera shows nobody facing it, or the picture is black |

Host and port can be changed on the Orest side:

- `OREST_TD_HOST` and `OREST_TD_PORT` set where Orest sends to TouchDesigner.
  Both `orest-search` and `orest-sitrep` read them.
- `OREST_CONTROL_HOST` and `OREST_CONTROL_PORT` set where `body-live` listens.
