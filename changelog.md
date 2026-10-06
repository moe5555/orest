# Changelog

Central development log for Apollon. Newest entries first. See
`knowledge/KNOWLEDGE_BASE.md` for pointers into the Source of Truth files
referenced below.

---

## 2026-10-06 — Camera and sound chosen on the operator page (VSH-ARLT-5090)

Requested by Moe: the operator page has two dropdowns, **Kamera** and **Ton**,
so the sources no longer have to be given on the command line. This is step 2
of the Realtime-SITREP in `knowledge/components/02_processing.md` ("select
video and audio source"), moved into the localhost interface.

- **What is offered.** Every DirectShow camera; every microphone, grouped by
  host API, since one microphone appears under each; and the NDI sources on
  the network. NDI sources come from a separate request,
  `GET /api/sources/ndi`, because the search takes two seconds
  (`ndi_audio.sources`). Cameras and microphones appear at once.
- **The server keeps the selection** (`interface/sources.py`, `Selection`),
  not the page. A run started from any tab, or restarted from the SITREP page, opens
  the same sources. `POST /api/sources` checks that the camera and microphone
  exist and refuses the choice otherwise; the page shows why and returns to
  the previous choice. An NDI source is checked when the run starts.
- **Saved** to `data/interface/sources.json` (`APOLLON_UI_SOURCES`), so the
  choice survives a restart of `apollon-ui`. `--video`, `--audio`,
  `--audio-api` and `--audio-ndi` still work and replace the saved choice.
  The sound is replaced as a whole: a microphone given on the command line
  ends a saved NDI source.
- **Devices are kept by full name**, as before (`devices.py`). `_select` now
  takes a full name as that device even where it is part of a longer one:
  "vMix Video External 3" was refused as ambiguous beside "vMix Video
  External 3 YV12". A fragment that matches several devices is still refused.
- A choice made during a run applies from the next start, and the page says
  so.
- **Code in English, interface text in German** (set by Moe). The new module,
  routes, JSON fields, element ids and CSS classes are English; what the page
  shows ("Kamera", "Ton", its notices) is German. Code written before this
  still carries German names (e.g. `/api/sitrep/bericht`, the snapshot's
  `quelle`).

**Verified** on this machine with `apollon-ui` on a spare port, without
starting a run: the page listed 18 cameras and 35 microphones under four host
APIs and marked the selection given by `--video`. A choice was saved and
reloaded, and an unknown camera was refused with the device list. Headless
Edge rendered the page. No NDI source was on the network (OBS's NDI output
was off), so a saved NDI source showed as "nicht gefunden". 9 new tests; 503
pass.

**Not yet checked:** a run started from the page with a choice made there,
and the NDI list with OBS's NDI output on.

---

## 2026-10-06 — Recording in OBS while the live SITREP watches the same camera (VSH-ARLT-5090)

**Moe's observation:** with OBS recording `SandbergCapture`, the live SITREP
reported "Could not open video device [5] 'SandbergCapture'." and the camera
stream in OBS froze.

- **Cause.** DirectShow opens a capture device for one application at a
  time. OBS held it, and the SITREP's attempt to open it failed and
  interrupted OBS's stream. No change in Apollon lets both open the device.
- **Setup.** OBS holds the device and records. Its virtual camera passes the
  picture on, and the SITREP reads `--video "OBS Virtual Camera"`. The steps
  are in the README ("Recording in OBS while the SITREP watches"). OBS is
  then the Recorder of `pipeline.md` (CAPTURE, `REC`) and the SITREP one
  reader of its stream.
- **`devices.open_video`**: the error now says that the device may be held by
  another application and names the virtual camera as the way through.

**Checked** on this machine with OBS running: `OBS Virtual Camera` [17] opens
alongside OBS and delivers frames (77 in 3 s). The virtual camera wasn't
started, so it sent OBS's placeholder logo at 640×480. A run started in that
state analyses the logo. 55 tests in the capture, session and NDI audio
modules pass.

**Still to do:** start the virtual camera with the Sandberg source and raise
OBS's output resolution, then run the SITREP once while OBS records.

---

## 2026-10-06 — System renamed from Orest to Apollon

Set by Moe. The name changes everywhere in the repository, including earlier
entries in this changelog. Identifiers in older entries now carry the new
names:

| Before | After |
|---|---|
| package `orest`, `orest-pose` (`wise_ext/src/orest_pose`) | `apollon`, `apollon-pose` (`wise_ext/src/apollon_pose`) |
| `orest-search`, `orest-sitrep`, `orest-ui` | `apollon-search`, `apollon-sitrep`, `apollon-ui` |
| environment variables `OREST_*` | `APOLLON_*` |
| OSC addresses `/orest/…` | `/apollon/…` |
| WISE extractor id `orest/pose/rtmo-s/body7` | `apollon/pose/rtmo-s/body7` |
| `0006-register-orest-pose-extractor.patch` | `0006-register-apollon-pose-extractor.patch` |
| `TouchDesigner/Orest_TD_New.toe`, `old/OrestTD*.toe` | `Apollon_TD_New.toe`, `old/ApollonTD*.toe` |

Unchanged: the play's characters and titles (Orestes, Oresteia), the corpus
folder and WISE project `test_data_orest`, and the repository folder.

The `apollon` and `apollon-pose` packages are installed in the project venv,
and `apollon-pose` is installed in the `wise` conda env. The patched
`external/wise` checkout registers the `apollon/pose/` prefix. No WISE project
held pose features under the old id. 493 tests pass.

**Still to do:** the code pasted into the TouchDesigner DATs still listens on
`/orest/…`. Paste in the updated files from `TouchDesigner/code/` (or replace
`/orest/` with `/apollon/` in the OSC In DATs). The venv folder is still
`orest/` with `UV_PROJECT_ENVIRONMENT=orest`. The README now says `apollon/`,
so the venv needs to be recreated under that name.

---

## 2026-10-01 — Prototype 1: Override for a recommendation to intervene

Requested by Moe (`knowledge/components/03_render.md`, Prototype 1,
Einschreiten): the Einschreiten screen has an **Override** button. Clicking it
or pressing **X** sets the recommendation aside and the page returns to its
regular view. Before this, the screen stayed up until the next recommendation.

`POST /api/sitrep/override?nummer=N` (`LiveSitrep.uebergehen`) clears the
recommendation on the server, so the Übersicht shows "Keine Empfehlung" as
well. The page sends the number of the recommendation on screen, so a newer
one that arrived in the meantime stays visible. The run itself is not told:
the next automatic or requested recommendation appears as usual, and
TouchDesigner gets no OSC message for an override.

**Verified** by tests for the endpoint (clear, stale number, nothing to clear)
and for the markup and key binding. 493 tests pass. Not yet checked in a
browser.

---

## 2026-09-30 — Prototype 1 laid out for a landscape projection (VSH-ARLT-5090)

Set by Moe, since the display is projected in landscape
(`knowledge/components/03_render.md`, Prototype 1): the picture on the left,
two thirds of the width at 16:9; on the right the two people in view, one
above the other, the left-most on top, with the alarm directly beneath them.
The whole is centred vertically. Errors and a silent sound source span both
columns above. Einschreiten and the report on R are unchanged.

The people and the alarm share one column container (`.p1-seite`), so the
alarm follows the people rather than a grid row stretched to the picture's
height. The rating bars narrow on smaller screens so the labels stay whole.

**Verified** in headless Edge at 1920×1080 and 1280×720 against a stand-in run
with fixed data, with and without the alarm. Headless Edge does not draw the
MJPEG feed, so the picture itself was not checked. 490 tests pass.

---

## 2026-09-30 — Ghost bodies removed: duplicates and shadows (VSH-ARLT-5090)

The pose model reported people who were not there, and the body tracker
followed, named and classified them as someone beside the real person. On the
Probebühne camera with Lena alone, 78% of frames held a second or third body:
**her shadow on the projection screen** behind her, read as an upper body
overlapping hers. On the test footage, **the same person boxed twice**. Both
took names from the real person, produced pair readings ("pat on back",
"touch other person's pocket") with her, and pushed real people out of the
two tallest bodies that are rated and shown.

`action.tracking.without_ghosts` drops them before linking. A detection is
measured against every more confident one in the same frame:

- **Duplicate:** its joints lie on the other's, on average under 6% of body
  height away (`DUPLICATE_APART`). Measured: duplicates ≤ 0.05, a second person
  overlapping another ≥ 0.36.
- **Shadow:** at least 15% of its box inside the other's, joints averaging
  under 0.80, and its pose the other's own, shifted and scaled, to within 10%
  of body height (`SHADOW_*`), sides as labelled or exchanged. Measured: Lena's
  shadow scored 0.61–0.82 and fitted within 0.02–0.14 (p95 0.07).

**Confidence alone does not separate them.** In "Fool for Love" an actress
kneeling beside a standing actor overlaps his box at 0.63–0.79, as unsure as a
shadow; her own pose fits his no better than 0.13. The copy fit keeps her.

**Measured:**

| | before | after |
|---|---|---|
| Lena alone, frames with more than one body (615 frames) | 78% | 2% |
| "Fool for Love" 0–120 s, real overlapping people kept | 16 of 16 | 16 of 16 |
| "Four Dogs" 120–300 s, body label changes (`sitrep.namecheck`) | 11 | 2 |

Of the two remaining changes one is the camera cut described in the entry
below. 5 new tests; 490 pass.

---

## 2026-09-30 — Names hold: body names are voted, face tracks also link by place (VSH-ARLT-5090)

"Who is in the scene" (`knowledge/components/02_processing.md`, Realtime-SITREP)
lost correct names within seconds: Moe saw a person alone on stage, rightly
named, shown as someone else a few frames later. Two causes, both measured:

- **A face track split whenever the embedding dipped.** A turned head, a hand
  or a change of light scored below the link threshold against the person's own
  track and below the naming threshold against the cast, so a new track began
  with a guessed name in the very place the named one had just been.
- **A body took whichever name the latest face gave it.** One split face track
  was enough to rename the body on the operator's video, guess over cast name.

**Face tracks link by place as a third cue** (`presence.PLACE_LINK`,
`PLACE_AGE`). A face no embedding cue claims continues the track sighted within
the last two passes whose box it overlaps by IoU ≥ 0.3, unless the cast gallery
names the face as someone other than that track.

**Body names are weighed on their sightings** (`actions.ActionRatings.name`).
Each face sighting of a cast name is a vote on the body; votes halve every 3 s
(`VOTE_HALF_LIFE`); another cast name replaces the one a body carries only once
it leads by two votes (`SWITCH`), about five sightings in a row. The same
margin decides which body in view keeps a name two of them claim. A guess names
a body only while no cast name does, set by Moe: a person the cast has
recognised should keep that name.

**Replay check: `python -m sitrep.namecheck`.** Walks a recording through the
face tracker and body naming on the footage's own clock, as a live run wires
them, and prints every name made, lost or changed, then a summary: how close
faces score to the naming threshold, how many face tracks split off a live one,
and body label changes by kind.

**Measured** on "Four Dogs a Bone", 120–300 s, two actors enrolled from the
scene's first 90 s (not in the repository):

| | before | after |
|---|---|---|
| face tracks started | 23 | 13 |
| of them split off a live track | 13 | 3 |
| body label changes | 27 (9.0/min) | 11 (3.7/min) |
| of them cast name → guess | 5 | 0 |
| body-seconds under a cast name | 89% | 93% |

The one cast → cast change is a camera cut the body tracker carried from one
actor to the other; it is now corrected after 4 s instead of 1 s, which is the
price of names that hold. The remaining changes are a cast name passing between
**two bodies pose detection places on one person**, overlapping boxes around the
same actor (seen at 226 s). The duplicate also pushes the other actor out of
the two tallest bodies. Suppressing overlapping bodies in `action.tracking` is
the next step. Enrolment from the same footage flatters recognition; the
cast's phone photographs (`data/cast`) against the rehearsal camera are
unmeasured.

9 new tests, one rewritten for the new rule; 485 pass.

**Live check**, AVMATRIX camera, Lena enrolled from phone photographs, the
operator page's state read twice a second for 90 s:

- **Lena alone (16–90 s): named in 99% of samples, never under another name**,
  including while crouched with her face to the floor.
- **A second body beside her in 17% of samples**, shown as `Körper <id>`
  over her upper body: her shadow on the projection screen. Removed in the
  entry above.
- **Alessa passing behind Lena, back to the camera (0–16 s)**, was guessed at
  as three different names in turn and recognised as Alessa for about 1.5 s.
  Moe keeps the guesses as they are: a guess that stuck to the body would keep
  a wrong name as well as a right one. For 1 s two bodies both showed "Lena":
  the one-body-per-name rule runs only at the next naming step, and a body
  missing from that step's frame keeps its name.

---

## 2026-09-29 — Live SITREP display, Prototype 1, as a tab of the operator page (VSH-ARLT-5090)

The first display prototype of `knowledge/components/03_render.md` ("Live
SITREP", Prototype 1) is a second view of `/sitrep`, beside the existing one.
Faint tabs at the top switch between "Übersicht" and "Prototyp 1"; the choice
is kept in the address (`/sitrep#p1`). Both views read the same snapshot, so
the run, its readers and the existing view are unchanged.

- **Picture on the top third**, boxes and names as the overlay already draws
  them: each name on a tag at the box's top-left corner.
- **Beneath it, the two people in view**, left and right as they stand, with
  their live Risiko and Menschlichkeit. A person in view without evidence reads 0.
- **Beneath them, the live alarm** while it is raised, set by Moe: who, their
  Risiko and the cause, as the overview's alarm panel words it. Nothing while
  it is not. Nothing else of the run is shown; an error or a silent sound
  source still is.
- **Einschreiten** fills the page in red while the latest Empfehlung
  recommends it, until the next Empfehlung says otherwise, set by Moe. E still
  asks for a new one. Beneath the word, set by Moe: why (the Empfehlung's
  `lage`, the model's sentence on what is happening) and what to do (its
  `empfehlung`).
- **R** shows the Lagebericht alone, centred, and asks for a new one; R again
  returns. The report takes precedence over Einschreiten, since it was asked for.
- **Szene values left out**, set by Moe: no source produces them continuously
  (Chronik, Empfehlung and Lagebericht each have their own rhythm).

**One addition to the snapshot:** `im_bild`, the names on the video's boxes
ordered left to right (`interface.live.im_bild`), read from the same
`ActionRatings.visible()` the overlay draws. The live values alone cannot
serve: they hold everyone with evidence in the last ~80 s, including people who
have left the frame.

Each prototype is its own script (`static/prototyp1.js`) that registers with
`ANSICHTEN` in `sitrep.js`: a render function, the keys it takes over, and what
to reset when its tab is left.

**Verified** in headless Edge against a stand-in run with fixed data: the
normal view with two people placed by position, the full-page Einschreiten, and
the report on R. 3 new tests; 476 pass.

**Open:** on the test footage the two tallest bodies are shown, audience
included, as `Körper <id>` until a face names them. Moe intends to show only
people in the cast; that needs the cast enrolment in `data/cast`
(`progress_tracker.md`, cast recognition).

---

## 2026-09-29 — Decision: QLab owns the final output and projection

**Decided by Moe.** QLab owns the outputs (mapping, blending, cue timeline);
TouchDesigner's output is taken into QLab, at the cost of one extra video hop
and its latency. The alternative, TouchDesigner driving the projectors with
QLab as cue master only, is dropped from the open decisions in
`knowledge/components/03_render.md`. This settles the output end of the RENDER
graph in `knowledge/source_of_truth/pipeline.md` ("Playback on stage"). The
playback chain diagram in 03_render.md shows QLab driving all outputs and
cueing TouchDesigner.

**Consequence for Apollon:** QLab runs on a Mac, and Apollon's control listener
binds `127.0.0.1` by default (`APOLLON_CONTROL_HOST`), so a QLab cue cannot
start a body capture until the listener is bound to the show network. Nothing
in the code changed.

---

## 2026-09-29 — NDI sound received in a child process (VSH-ARLT-5090)

**Moe's observation:** with `--audio-ndi "VSH-ARLT-5090 (OBS PGM)"` the page
reported no sound from the source for 25 s, though OBS was sending.

- **Cause.** cyndilib holds Python's interpreter lock while `receive()`
  waits for a frame (200 ms). With NDI sound received on a thread of the run,
  every other thread woke about 207 times in 5 s instead of about 3,200. The
  utterance cutter fell behind: 237 chunks were waiting after 15 s, the
  meter saw nothing, and no line was made. The window recorder before today
  barely needed to run, which is likely why this went unnoticed on
  2026-09-28.
- **Fix.** `ndi_audio.Receiving` runs the receiver in a child process that
  sends mono float32 chunks over a pipe. A thread in the run reads them;
  waiting on the pipe releases the lock.
  - Other threads now wake as often as without NDI (5,115 in 8 s).
  - A missing source still fails at start, naming the sources seen.
- **Tried and dropped:**
  - Short receive waits (0–20 ms) freed the lock but received less sound.
  - NDI's frame sync (`capture_available_audio`, `capture_audio`) returned
    only zeros in this cyndilib version.
- **Not addressed:** OBS/DistroAV itself sends only about 80 % of its audio
  frames under the present load. NDI reported 0 dropped frames, and the gaps
  in the sender's timestamps are whole frames. OBS is the test tool, so this
  is left.

All 473 tests pass. `Receiving` has no automated test; it needs a live NDI
source.

---

## 2026-09-29 — A silent sound source is reported (VSH-ARLT-5090)

**Moe's observation:** no lines at all, and the Chronik wrote "Kein Beginn
der Szene dokumentiert. Statische Situation ohne erkennbare Interaktion."

- **Cause.** `apollon-ui` ran without `--audio-ndi`, so it listened to the
  default device, "Webcam 4 (NDI Webcam Audio)". That device delivers
  digital silence (−96.7 dBFS), as noted on 2026-09-28. With no speech the
  Chronik only had its stills to summarise. OBS's NDI output
  (`--audio-ndi "VSH-ARLT-5090 (OBS PGM)"`) carries the sound at −40 dBFS.
  The corpus also needs `--language en`.
- **Fix.** The run now says when its source is silent.
  - `loudness.Meter` records when sound was last above `STILL` (−70 dBFS).
  - After 10 s below it (`session.STUMM`), or with no sound arriving at all,
    the session emits `Ton(stumm=True)`, and `Ton(stumm=False)` when sound
    returns.
  - The console prints a red "KEIN TON" line naming the source and the flags
    to check. The page shows the level in its header and a red panel.
- **Checked** on this machine: the NDI Webcam device is reported silent
  after 12 s; OBS's NDI output reads −43 dBFS and is not.

5 new tests; 473 pass.

---

## 2026-09-29 — A run checks its model at start (VSH-ARLT-5090)

**Moe's observation:** R gave "Lagebericht fehlgeschlagen: model 'gemma4:e4b'
not found (status code: 404)".

- **Cause.** The run was started without `--model`, and the default
  (`report.MODEL`, `gemma4:e4b`) isn't installed on this machine; only
  `gemma4:26b` is. Every request failed. Line ratings, Chronik summaries and
  Empfehlungen failed silently, since they only print to stderr.
- **Fix.** `llm.pruefen` asks Ollama for its models when a Session is
  constructed, before the camera opens.
  - A missing model names the installed ones and `--model`.
  - Ollama not running is reported as such.
  - `apollon-sitrep` prints the message and exits; `apollon-ui` shows it on the
    page.
- **Default model is now `gemma4:26b`** (`report.MODEL`), set by Moe: the
  model on the production machine and the one every measurement used.
- **The check is model-agnostic.** It compares the name given with Ollama's
  list, reading a name without a tag as `:latest`. Its tests use invented
  model names.

5 new tests; 469 pass.

---

## 2026-09-29 — Live SITREP in three speeds: fast lane, Chronik, report on R (VSH-ARLT-5090)

Built fixes 1–4 of `knowledge/background/live_sitrep_latency.md` and measured
fix 5, with Moe's change: **a report is made only when the operator presses
R**. A summary of the scene is written in the background, so a report covers
the last minutes. The Empfehlung builds on the same infrastructure. This
replaces step 6 of the Realtime-SITREP in `02_processing.md` ("Every x
seconds, prompt a SITREP report"); a note there says so. Architecture:
`knowledge/background/live_distillation.md`.

**Fast lane** (fixes 1 and 2):
- **`utterances.py`.** Silero VAD runs on the live sound chunk by chunk,
  carrying its state; the streamed probabilities equal one pass exactly.
  - An utterance ends after 0.5 s of silence, or at a 0.2 s pause once it has
    run 3 s, or at 10 s.
  - Whisper, lip attribution and loudness per utterance. The line is handed
    out at once; the rating follows on its own thread.
  - Lines arriving during a rating are rated together next, with the four
    before them as context (`speech.rate(..., vorher)`).
- **`lage.py`.** Live Risiko and Menschlichkeit per person, from action
  readings and rated lines, computed every 0.5 s and never stored.
  - Evidence counts half after 20 s (`HALBWERTSZEIT`).
  - The **alarm** is a rule: a person's live Risiko, or a line of unknown
    speaker, at 3 or more.
- **Supporting changes.**
  - `loudness.Meter` measures the live sound's level as it arrives.
  - `ActionRatings.take` became `between` and `since`: readings are read,
    not consumed, and kept 10 min.
  - `capture.FrameRing` keeps named stills; `capture.listen` opens the sound.

**Chronik** (`chronik.py`):
- **Abschnitte.** Every `--window` seconds the stretch just passed becomes
  an Abschnitt: its lines, action ratings, roster and two stills. The model
  summarises it in 1–2 sentences, with Eskalation, Gefahr and a Tendenz.
- **Rückblick.** Abschnitte older than 5 min are folded, 4 at a time, into
  one chronological Rückblick, and their words deleted.
- **Kurve.** Eskalation and Gefahr per Abschnitt are kept as numbers for the
  whole run.

**On request** (fix 3, changed):
- **Lagebericht (R).** Reads the Chronik, the live values, the lines since
  the last summarised Abschnitt word for word, and two stills from the last
  15 s. It gains a **Verlauf**: turning points with their times.
- **Empfehlung.** Made on the alarm's rising edge, on an Abschnitt above the
  threshold, or on E; `--no-auto-empfehlung` leaves it to E.
  - The rule `SCHWELLE` still decides whether to intervene.
  - Automatic ones are at least 15 s apart.
- **Model gate (`llm.py`).** Ollama here serves one request at a time; a 60
  token request behind a 400 token one took 1.2 s instead of 0.23 s. The
  gate orders Apollon's requests: line ratings, Empfehlung, Lagebericht,
  Chronik.
- **Leaner prompts** (fix 4, partly). One fixed opening shared by report and
  Empfehlung (`report.QUELLEN`), then roster, Chronik, live values,
  transcript. Person descriptions and forecasts are one sentence each.
  Streaming the report's text was not built.
- **Removed:** `report.sitreps`, the per-window report and held-back lines,
  and `Sitrep.quelle.ton_s`. Replaced by `quelle.abschnitte` and
  `woertlich_s`.

**Outputs:**
- **Console.** Lines as said, live values when they change, Abschnitte,
  Empfehlungen; R and E typed in the console.
- **Page.** The video beside the alarm, the Empfehlung (dimmed after 60 s)
  and the live values. Below it, the lines, the Chronik with its curve, and
  the Lagebericht on R.
  - Checked in headless Edge on a replayed run.
  - Endpoints: `POST /api/sitrep/bericht` and `/empfehlung`.
- **OSC.** `/apollon/live/{begin,person,end,zeile,empfehlung}` and
  `/apollon/chronik/abschnitt`. The report's `begin` carries `abschnitte`
  instead of `ton_s`, and adds `/apollon/sitrep/verlauf`.
  - `TouchDesigner/code/sitrep_osc.py` writes optional `live_*` and
    `chronik` tables.
  - **`sitrep_meta` gains `verlauf` and `abschnitte`.** The TouchDesigner
    module must be pasted in anew.
- **`python -m sitrep.replay FILE`** plays a recording into a run in real
  time, without OBS, and prints the latencies against the doc's targets. It
  works with `--send-td`.

**What didn't work first:**
- **Lines waited for their rating.** Rating in the same thread as
  transcription let a line wait for the previous rating: p95 4.8 s. Showing
  it unrated first gave p50 0.6 s, but p95 was still 3.5 s.
- **Quarrels never paused for 0.5 s.** Utterances ran to 10 s and were cut
  at a pause seconds in the past. The 0.2 s phrase-pause rule gave p95 0.8 s.
- **Reports ran into the token cap.** Without stills, a report listed
  "Unbekannt" until the reply was cut off. The list of people is now capped
  at one per name.

**Measured**, "Four Dogs" 0–405 s, `--window 30 --interval 5`, `gemma4:26b`:

| Output | Measured | Target |
|---|---|---|
| Line on screen after it ends | p50 0.4 s, p95 0.9 s (60 utterances) | p95 ≤ 2.5 s |
| Line rated | p50 1.2 s, p95 2.1 s | – |
| Person value after a line | p50 2.0 s, p95 5.8 s | p95 ≤ 3 s, **missed** |
| Lagebericht after R | 3.3–4.4 s (3 reports) | – |
| Empfehlung after its trigger | p95 1.8 s (7 made, 5 alarms) | – |
| Abschnitt summary | p50 2.0 s (14) | – |
| GPU (fix 5) | mean 23 %, p95 85 %, max 25.0 GB of 32 | – |

- **Person values miss their target.** They are measured from the end of the
  line's Whisper segment, and a segment early in a long utterance waits for
  it to end.
- **The Kurve** read 1, 2, 5, 6, 6, 8, 5, 4, 7, 6, 5, 6, 5, 6, the
  trajectory found on 2026-09-28.
- **The report at 400 s** spanned 402 s over 13 Abschnitte, but its Verlauf
  was generic ("Tendenz zur Eskalation"). Asked again on the same Chronik
  with the current instruction (turning points with times), the Verlauf
  named 12:16:18, 12:17:18, 12:18:48 and 12:20:18, twice out of two.
- **Empfehlungen.** 4 of 7 said "Einschreiten", all for verbal quarrels.
  The thresholds are in `todo_with_data.md`.

69 new tests; 464 pass.

---

## 2026-09-28 — Recording never pauses; cut lines held back; loudness marked; previous lines as context (VSH-ARLT-5090)

**Moe's observation** on "Four Dogs a Bone" (test corpus), run with
`--window 5 --interval 5`:
- Eskalation and Gefahr rose with the conflict, but crucial lines were
  missing from the dashboard.
- Loud shouting didn't raise Risiko or Eskalation.

**Diagnosed** by replaying the clip through the live loop's own steps, with
a Whisper transcript of the whole clip as ground truth:
- **The loop stopped recording while it made a report.** At 5 s windows a
  report took ~4–5 s, so 58 % of the conflict (150–360 s) was captured and 20
  of 67 lines were heard whole. 4 of the 10 loudest lines fell into the gaps.
  At 15 s windows: 73 %, 40 of 65 lines. This is concern 3 of
  `claude_concerns.md`.
- **Short windows cost as much per report.** Whisper ~0.1 s, the line rating
  ~1 s (in parallel), the Gemma report 2.3–5 s, mostly generated text. The
  cost is per report, not per second of footage.
- **The model rated each window blind to the previous one,** and couldn't
  know a line was shouted.
- **Risiko per person needs attributed lines;** on this footage most stay
  `(unklar)`.

**1. `capture.Recorder`** replaces the generator that recorded only while it
was waited on.
- It records on its own thread, windows back to back.
- `AudioBuffer` hands over all sound since the last cut. `AudioRing`, which
  kept only the last window's worth, is gone.
- A report takes every window that finished meanwhile, merged (`merge`): all
  the sound, and the usual number of frames spread over them. More than 60 s
  behind (`MAX_BACKLOG`), the oldest sound is dropped with a message.
- The session holds the recorder, so stopping drops waiting windows at once,
  even while a report is still being generated.
- `Session.close()` now also deletes face tracks (`PresenceTracker.clear`),
  poses, names and unreported readings (`ActionRatings.clear`), mouth
  measurements (`Speakers.clear`) and the loudness calibration. Tests check
  that nothing is held after a stop. Kept, as agreed: the last report on the
  page, and Ollama's cached prompt.

**2. Cut lines held back** (`report._held_back`). A last segment ending within
0.5 s of the window's sound (`CUT`), and at most 10 s long (`MAX_CARRY`), is
left out and its sound put in front of the next window (`capture.prepend`),
where it is transcribed and reported whole.

**3. Loudness marked for the model.** Lines 1.5 or 2.5 standard deviations
above normal carry `lautstaerke` "laut" or "geschrien". The transcript reads
`Name (geschrien): …`, and the prompt says what the marks mean.
- **Calibration** became provisional after 30 s of speech and fixed after
  120 s (`PROVISIONAL`, `CALIBRATION`).
- Calibrated on 30 s alone, the whispered opening of "Four Dogs" (−38.8 dBFS
  against a median of −26) marked 63 % of all lines. Now 44 lines of the
  conflict are "laut" and 3 "geschrien", the three loudest of the clip.
- The page and console show "lernt n/120 s" until it's fixed.

**4. Previous lines as context.** The report's model sees the previous
report's last 8 lines as "Zuvor gesagt", and is told to rate this window
while noting whether the situation is sharpening or easing.

**Result**, replaying 0–405 s of "Four Dogs" at `--window 15 --interval 5`
through the new pipeline:
- **Lines:** 119 of 128 ground-truth lines appear in a report; the rest
  differ in Whisper's wording.
- **Eskalation:** 0 through the calm opening, 6–8 through the conflict (peak
  8 at "That's fucking racist, you stupid bitch!"), easing to 2–4 around
  300 s and back to 7 at 345–375 s. Gefahr up to 4. Before: mostly 0–3.
- **Delay:** reports 5.7 s after their window on average, at most 7.4 s. No
  merging was needed at 15 s.

**On window length:** a report costs 3–7 s whatever the window, so 10–15 s
windows keep up. At 5 s, windows are merged, and the reports are both later
and coarser than at 15 s.

17 new tests; 395 pass.

---

## 2026-09-28 — Loudness amplifies Risiko, calibrated per session (VSH-ARLT-5090)

The Audio route under "Calculating Values" in `02_processing.md`: higher
loudness increases negative-coded values. As Moe asked, each session
calibrates itself at the beginning and loudness amplifies what pose and speech
measure.
- **Risiko only**, following the spec's "negative-coded". Menschlichkeit is
  left as it is.
- **Amplifies, never lowers**, and adds no evidence of its own, so a loud
  laugh is not a danger.

**`src/sitrep/loudness.py`:**
- **Level:** the window's audio in 100 ms steps as dBFS. A stretch's level is
  the 90th percentile of its steps, so pauses between words don't pull a line
  down.
- **Calibration:** `Calibration` learns the mean and spread (at least 3 dB)
  of the first 30 s of detected speech, weighting each Whisper segment by its
  length. Silence isn't counted, since it would make every line loud. Until
  then every gain is 1. There is one calibration per `Session`.
- **Gain:** the first standard deviation above normal counts as ordinary
  speech (`QUIET`). Beyond it, `1 + 0.5` per standard deviation, capped at
  2×. It multiplies positive Risiko evidence before rounding and clipping to
  0–5.

**Where it applies:**
- **Actions:** each reading gets the gain of its own 4 s, before the peak is
  taken (`actions.rate(..., gain)`). The Handlung records it as
  `verstaerkung`, and the cause says `laut ×1.5`. Readings from before the
  window's audio, such as those made while the previous report was generated,
  get 1.
- **Speech:** each line carries `pegel_db` and `verstaerkung`.
  `Sitrep.bewertung` uses the amplified Risiko.
- **Report order:** `report.sitrep` now transcribes first, learns from the
  window's speech, and then takes the action readings with the gain.
- **Display:** the report carries `pegel` (calibrated, seconds heard, normal
  level, spread). The console footer and the page header show it, and
  amplified lines show their gain.

**Measured on 5 min of "Boom"** in 15 s windows:
- Calibrated after the third window (31 s of speech): normal −29.8 dBFS
  ±5.0.
- With a plain `1 + 0.25·σ`, nearly every later line was amplified, by 1.1 to
  1.3, because the scene opens quietly and grows louder.
- With the one-σ dead zone and a 0.5 slope: 37 lines amplified, 13 above
  ×1.3. The loudest are the argument about being locked in (375–392 s, ×1.5
  to ×1.7): "Why did you lock the door?", "The obsession with the fish is
  too much."

11 new tests; 383 pass.

**Open:** a session that opens quietly and escalates sets a low normal level.
This is in `todo_with_data.md`, with checking the constants on the
production's microphones.

---

## 2026-09-28 — Speech rated per line; combined with actions by maximum (VSH-ARLT-5090)

The Sentiment Analysis route under "Calculating Values" in `02_processing.md`.
Decided with Moe:
- Lines are taken at their word: as seriously meant, whether acted or not.
- Risiko and Menschlichkeit combine with the action values by maximum.
- The prompt's example lines stand in for the trigger-word table for now.

**`src/sitrep/speech.py`:**
- One text-only request per report to the report's model, run alongside the
  report's own request, with the same context size so Ollama keeps one
  loaded model.
- Each line (`Name: text`) gets a one-sentence reason and evidence from −5 to
  +5 for risiko and menschlichkeit, the scale of the action table.
- The reason comes first in the schema, so the model states what a line
  means before it scores it.
- The grammar holds the reply to one reading per line. Temperature is 0.
- A failed request leaves the lines unrated and keeps the report.
- The anchors are `src/sitrep/speech_examples.csv`, an editable table like
  `action/sitrep_map.csv`.

**Combination.**
- `Aeusserung` carries each line's `begruendung`, `risiko` and
  `menschlichkeit`.
- `Sitrep.bewertung(name, rating)` returns the higher of the person's action
  rating and the peak of their attributed lines, clipped to 0–5, together
  with its cause: an NTU class, or the line and its reason.
- Unattributed lines count for no one.
- Console, operator page and OSC show the combined values. The console and
  page also show each line's evidence, with the reason on hover.

**Evaluation: `python -m sitrep.speech`** rates `src/sitrep/speech_eval.csv`,
34 invented German and English lines, none of them among the examples, in
groups of 6.
- First prompt: 26 of 34 within ±1. Friendly lines got risiko −2, and idioms
  were read word for word ("Ich lach mich tot" → risiko +5).
- After stating that negative risiko means actively calming, that friendliness
  alone is 0, and that idioms keep their ordinary meaning: **31 of 34**.
- Asking the reason field for "what the speaker means" instead of "what the
  line says literally" gave 29 and was reverted.
- Remaining misses: two idioms, and "Ich schlag dir gleich eine rein" at +5
  where +4 was expected.
- Every threat, hate line and insult lands: "I hate everything about you" →
  risiko +3, "Man muss sie alle loswerden" → +5.
- 1.2–1.5 s per request with `gemma4:26b`.

13 new tests; 373 pass.

---

## 2026-09-28 — Speaker attribution by lip movement; the tracked people named on the operator's video (VSH-ARLT-5090)

Moe asked for the two most visible people on stage to be tracked, for what
they say to be attributed to them, and for their names and boxes to appear on
the webcam feed, using the models that already track people and their
identity. This is the speaker diarisation that the sentiment analysis in
`02_processing.md` ("Calculating Values") needs.

**The people** are the action recogniser's: the two tallest bodies from pose
tracking (`recognizer.MAX_PEOPLE`), named through the face tracker
(`actions.py`). `recognizer.tallest()` picks them per frame.

**Mouths: `src/sitrep/speakers.py`.**
- The recogniser now hands each tracked frame to an `on_frame` listener.
- For each of the two tallest bodies, a face box comes from the pose's head
  joints: the ear distance, or the eye distance, sets its size.
- `2d106det.onnx`, the 106-point landmark model of the `buffalo_l` bundle
  whose detector and recogniser Apollon already uses (`face/model.py` unpacks
  it from the cached zip), finds the lips.
- The opening is the gap between the inner lip centres (points 62/60) divided
  by the mouth's width (52/61). Found by drawing the points on a corpus face.
- 1.3 ms per face on the GPU, so about 65 ms of GPU time per second for two
  people at 25 fps.

**Attribution.** Whisper now returns timed segments (`transcribe.segments`).
A segment goes to the person whose mouth opening varied at least `RATIO` 1.5
times as much as the other's over it, each needing at least 5 measurements.
- With fewer than two mouths seen, or no clear difference, the line stays
  unattributed.
- A speaker whose body carries no name is `Unbekannt`.
- The report gains the measured field `aeusserungen` (name or None, text,
  beginning, end). `gesagt` stays verbatim.
- The model reads the transcript as `Name: line`, with `(unklar)` where the
  speaker isn't known.
- The console and the operator page list the lines with speakers.

**Names now survive a body leaving the frame.** A name moves off another body
only if that body is in the same frame. Before, every camera cut stripped a
name from the earlier body's readings. On a replay, lines attributed to
`Unbekannt` fell from 12 to 5.

**Overlay.** The operator page's MJPEG feed draws the two tallest bodies with
their names, or `Körper <id>` while unnamed. It uses `annotate.draw_names`,
off the event loop. The NDI feed stays unmarked.

**Measured on "Boom"** (edited multi-camera footage):
- Feasibility, 5 min: 107 segments with both mouths visible, of which 69 had
  a clear mover (≥1.5×). Clear cases can be decisive, e.g. 15× on "Yeah, I
  don't have a good job".
- Full pipeline, 60 s from 200 s: 17 of 34 lines attributed.
- The two actors appear under many guessed names, because face tracks restart
  at cuts, and even with the two enrolled from the clip, their dark, profile
  and wide-shot faces were rarely recognised. Where "Person A" was recognised,
  the lines fit the character.
- Accuracy is unmeasured; `todo_with_data.md` describes how to measure it on
  the production's own footage.

The overlay was checked on a replayed frame: both performers boxed, audience
heads in the foreground excluded. 16 new tests; 361 pass.

---

## 2026-09-28 — People and their ratings on the first screen, with numbers (VSH-ARLT-5090)

**The values were on the page but easy to miss.** A full-page capture showed:
- The per-person ratings were the third panel under the video, below the
  first screen at 1600×900.
- They were drawn as five pips with no number, so a 0 looked like an empty
  field. Most ratings on the corpus are 0.

Changes to the operator page:
- **Personen and Gemessen** now come directly after the recommendation,
  before the description and the scene.
- **The video** takes at most 48 % of the window height, down from 62 %.
- **Each rating shows its number** next to the pips, or `–` if not measured.

At 1600×900 the first screen now holds the video, the report header, the
recommendation and the people with their ratings.

**A stale cache was also real.** Moe's regular Edge profile went on showing
no values while a private tab worked. The page files had been served without
cache headers since 2026-09-25. Edge could therefore reuse a copy that was
days old for hours without asking the server, and a newer script ran against
older markup. The `no-cache` header added earlier today applies only once a
file has been fetched fresh, so an existing profile needs its cache cleared
once.

---

## 2026-09-28 — Sound from an NDI source: `--audio-ndi` (VSH-ARLT-5090)

Live test runs had no speech: OBS Virtual Camera carries video only, and the
NDI Webcam audio device Apollon recorded had no source. Once OBS's DistroAV NDI
output was on (`VSH-ARLT-5090 (OBS PGM)`), NDI Webcam still couldn't be set
to it, since its window didn't respond. Apollon now receives the NDI source's
audio itself.

- **`src/sitrep/ndi_audio.py`**: `NdiAudio(source)` names the source.
  `Receiving` finds it (up to 10 s, and the error lists the sources seen),
  receives audio only on a thread, mixes it to mono and resamples to 48 kHz if
  needed. It fills the same `capture.AudioRing` a microphone does. It uses
  cyndilib, already a dependency for the NDI video output (`feed.py`).
- **`capture.windows`** opens either a microphone (sounddevice) or the NDI
  receiver, both as context managers.
- **`--audio-ndi SOURCE`** in `apollon-sitrep` and `apollon-ui`.
  `session.resolve_sources(args)` picks the camera and the sound source for
  both entry points. `devices.describe` names an NDI source in the startup
  lines.
- 5 new tests; 347 pass.

**Verified** against OBS playing the corpus: 15 s received through
`Receiving` gave 13.5 s of audio (about 1.5 s to connect) at −40 dBFS RMS.
Whisper `en` transcribed it cleanly ("Who's gonna stay in this apartment and
who's not? … You are deeply cruel.").

---

## 2026-09-28 — Report back on the first screen; readings named when a report takes them (VSH-ARLT-5090)

**The report was below the visible area.** In a new Edge window Moe again saw
only the video. Checked from this machine:
- The server made a report every ~17 s with 1.9–2.1 s latency.
- All 22 event-stream messages in 20 s were valid JSON.
- A headless Edge rendered the report without error.
- A screenshot at 1600×900 showed the cause: the live action panel, added
  between the video and the report, pushed the report's top to 803 px, below
  the 808 px viewport. The page is laid out so that the video takes a fixed
  share of the window and the report starts on the first screen (`style.css`,
  `.feed`).

The panel now comes after the report. The stale-page explanation of the entry
below also held: Moe's regular Edge profile kept showing nothing while a
private tab worked (see the entry above).

**Readings are named when a report takes them.** The live panel showed both
performers as `Körper 37` and `Körper 41` at one moment, and named a few
seconds later. Readings were named when they were recorded, so everything a
body did before its face was matched was lost: 2–10 readings per person in a
15 s report, of about 45 possible. `ActionRatings` now keeps readings under
the body's track id (`Evidence.members`) and resolves names in `take()`. A
body named at any point before the report counts with all its readings. Name
changes are serialised with the same lock as the records. 1 new test; 342
pass. A replay of 60 s of "Boom" with the real models still names and rates
both performers.

**No NDI source exists on this machine.** An NDI finder (cyndilib) listed
none. OBS's DistroAV output is off, so NDI Webcam has nothing to select, and
live runs still record silence.

---

## 2026-09-28 — Transcription language selectable: `--language` (VSH-ARLT-5090)

Whisper's language was fixed to German (`transcribe.LANGUAGE`, for the
Stuttgart production). A fixed language is also the language Whisper writes
in, so the English test corpus came out as rough German. On 20 s of "Boom":
"thank you for noticing the tank is nice" became "danke für die Aufmerksamkeit,
die Tank ist nett", and "They are dying" was lost. With `en` the same audio
transcribes cleanly.

`--language` in `apollon-sitrep` and `apollon-ui` sets it per run (default `de`).
It passes through `session.Options.language` and `report.sitreps` to
`transcribe.transcribe`, and appears in the startup lines. It prepares the
sentiment analysis in `02_processing.md` ("Calculating Values"), which reads
the transcript. 341 tests pass.

Also found: **live test runs have had no speech.** OBS Virtual Camera carries
only video, and the NDI Webcam Audio device Apollon records had no source
(report #42: `gesagt` empty). OBS's DistroAV NDI output can feed it; steps are
in `todo_with_data.md`.

---

## 2026-09-28 — Operator page no longer mixes cached and new files (VSH-ARLT-5090)

**Symptom.** After the action panels were added, a run in `apollon-ui` showed a
smooth video and "Live", but never a report.

**Cause.** The server was producing reports: #7 after 2 min, with 2.1–2.2 s
latency, so `gemma4:26b` was back on the GPU. The browser tab had kept the
old `sitrep.html` alongside the new `sitrep.js`. The script looked for the new
live-action panel, found no element, and threw before reaching the report.

Verified in a fresh headless Edge driven over DevTools: the same page showed
report #14, 3 person cards, 4 measured people and 3 live action rows, with no
script error.

**Fix.** Page and static responses now carry `Cache-Control: no-cache`, so the
browser checks every file on each load; an unchanged file costs a 304. The
video and event streams keep `no-store`. 340 tests pass.

---

## 2026-09-28 — Action recognition limited to the two tallest people (VSH-ARLT-5090)

Set by Moe: the production's footage shows two performers, and they are the
tallest bodies in frame. `recognizer.MAX_PEOPLE` is now 2, down from 6 in the
entry below. Each window then classifies at most three groups: each performer
alone, and the pair while they stand close. 339 tests pass.

---

## 2026-09-28 — Action classification no longer takes over the GPU (VSH-ARLT-5090)

**Symptom.** In `apollon-ui` with `gemma4:26b` on sample footage showing about 17
people, reports hardly arrived and the video stuttered.

**Cause, measured.**
- Apollon's process held **27.4 GB of the 5090's 32 GB**. Ollama kept 3.8 GB on
  the GPU, and Windows moved the rest of the model (~21 GB) into system RAM,
  so generation ran largely from system memory.
- The action recogniser sent every person and every close pair to the network
  in one batch. With 17 people that can be over 150 groups a second, each as
  10 clips.
- GPU memory grew by about 250 MB per group, and ONNX Runtime keeps its arena
  and grew it by doubling.
- The three people of the earlier Boom test needed only a few hundred MB.

**Fix:**
- **`model.CHUNK = 4`**: the network gets at most 4 sequences (40 clips) per
  run. Results are unchanged; a test checks that chunks stay aligned.
- **`arena_extend_strategy: kSameAsRequested`**: the CUDA arena grows by what a
  run needs instead of doubling.
- Measured: 1 to 40 groups now stay at **~2 GB** for the process, including the
  CUDA context. Before, 8 groups already took 2.6 GB, still growing.
- **`recognizer.MAX_PEOPLE = 6`**: only the six tallest bodies in a window are
  classified, alone and in pairs, so at most 21 groups. Even with bounded
  memory, 150 groups can't be classified within the one-second step.
  Performers usually stand nearer the camera than an audience at the edges.
  This partly answers "The audience dominates" (2026-09-28, step 4).

339 tests pass. Clean timings with Gemma on the GPU are still to be measured:
the machine was occupied by the run being diagnosed.

---

## 2026-09-28 — Operator page shows the action recogniser live and per report (VSH-ARLT-5090)

The operator page (`apollon-ui`) now shows what the action recogniser measures,
so it can be watched while testing on sample footage:

- **Aktionserkennung · live**, under the camera. The latest classification,
  refreshed every second. Each row shows a person or pair, the most probable
  class with its probability, and the signed evidence for risiko and
  menschlichkeit. The strongest evidence comes first, and at most 12 rows are
  shown, since spectators are classified too. Unnamed bodies appear as
  `Körper <id>`, which shows at once whether naming works. A recogniser that
  stopped shows its error here.
- **Gemessen**, in each report. One card per rated person, with both ratings,
  the class behind each and the number of readings. It includes people the
  model left out of its list.
- The header says whether action recognition is on.

`ActionRatings` keeps its last classification (`latest`, `evaluations`) for
this view. The snapshot carries it as `aktionen`. The event stream now sends
whenever the snapshot changes, not only when the version rises, because live
readings change every second without changing the run's state.

4 new tests; 337 pass. The page script passes `node --check`. It has not been
looked at in a browser.

---

## 2026-09-28 — Risiko and Menschlichkeit measured by the action recogniser in the live SITREP (VSH-ARLT-5090)

The live SITREP now takes `risiko` and `menschlichkeit` per person from the
NTU120 action recogniser, not from the model. This is the Pose route under
"Calculating Values" in `knowledge/components/02_processing.md`, and step 7 of
action recognition. The model rates only `auffaelligkeit`.

**`src/sitrep/actions.py`** runs the recogniser as another reader of the
session's camera (`Session.actions`). It turns readings into ratings in three
steps:

- **Naming.** Every second, when the recogniser classifies, each body whose
  head joints (nose, eyes, ears) lie in a face box takes that face's name. The
  box must come from the presence tracker's last 1 s, and may be up to half
  its size away. Pairing is one-to-one, nearest centre first, and a name seen
  on a new body leaves the old one. `PresenceTracker.faces()` hands out the
  recent boxes without running a pass.
- **Evidence.** A reading's evidence is `Σ P(class) · table value`, the
  expected value under the model's own uncertainty, using
  `action/sitrep_map.csv`. A pair reading counts for both people.
- **Rating.** Over a report, each rating is the peak evidence, rounded and
  clipped to 0–5. A single blow is enough, however calm the rest of the window
  was. A report takes every reading since the previous one, including those
  made while that report was being generated, when capture is paused.

**Measured and generated are kept apart**, as for `anwesend`:
- The measured values are a new field, `Sitrep.handlungen`. Each `Handlung`
  holds a name, the two ratings, the class behind each (`anlass_risiko`,
  `anlass_menschlichkeit`) and the number of readings.
- `Person` in the model's schema holds only `auffaelligkeit`, and the prompt
  defines only that.
- `Sitrep.bewertungen(person)` joins the two sources in `BEWERTUNGEN` order.
- A person the recogniser read nothing of gets `None`, which is not a 0. It
  travels as **-1 over OSC** and shows as `–` in the console and "nicht
  gemessen" on the operator page. The console and the page also show the
  class behind each rating above 0.

**Other changes:**
- On by default. `--no-actions` turns it off in `apollon-sitrep` and `apollon-ui`.
- The action model loads when the run starts, so a missing model fails the
  run immediately.
- The session stops the recogniser before the face tracker it reads.
- An error on the recogniser's thread is now kept (`ActionRecognizer.error`)
  and printed, and recognition stops. Before, the thread ended silently.
- 22 new tests, none needing a model or GPU; 333 pass.

**Replay on sample data.** A scratch script ran 90 s of "Boom" (from 120 s)
through the real pose, face and action models, driven frame by frame, with a
report every 30 s:

- All three people on stage were named from their faces and rated, with
  54–104 readings each per report. It took 38 s of wall time for 90 s of
  footage.
- **Everyone came out at risiko 1** in an ordinary conversation. Small
  probabilities on many risk classes add up, and the peak over ~100 readings
  rounds them up.
- One person got menschlichkeit 4 from "giving something to other person
  0.93". Not checked against the footage.

A live window on this machine started cleanly ("action: NTU120 ST-GCN on
CUDAExecutionProvider"), with 3.3 s latency. The NDI Webcam was empty, so it
measured no one.

Calibration steps, open questions and a way to feed sample footage into the
live SITREP are in `todo_with_data.md`.

---

## 2026-09-28 — Per-person ratings narrowed to Risiko, Menschlichkeit, Auffälligkeit; suggested Action-to-SITREP table (VSH-ARLT-5090)

Moe set the categories per person under Realtime-SITREP in
`knowledge/components/02_processing.md`, where they are now defined. They
replace `kollaborativ relevanz verantwortungsvoll menschlich gefahr`, still
0–5:

| Rating | Meaning |
|---|---|
| `risiko` | how dangerous the person is: hitting, threatening or dark speech, aggressive or radical behaviour |
| `menschlichkeit` | pro-social behaviour: giving, helping, saying something positive |
| `auffaelligkeit` | deviation from the person's past behaviour, e.g. a Mahalanobis distance |

**Each rating is defined in the prompt.** In the 2026-09-25 test run the
undefined `menschlich` came back 0 for everyone. Nothing measures
`auffaelligkeit` yet, so the model rates it against the others in the window,
the only reference it has. The scene ratings (`relevanz eskalation gefahr`,
0–10) and the intervention rule are unchanged.

Renamed throughout, with no other change: the OSC person row
(`<risiko> <menschlichkeit> <auffaelligkeit>`), `PERSON_HEADER` in
`TouchDesigner/code/sitrep_osc.py`, the setup note, the README and the operator
page. The console and the page colour `risiko` as they coloured `gefahr`.
**TouchDesigner's `sitrep_personen` table changes from nine columns to seven.**

**Suggested Action-to-SITREP table: `src/action/sitrep_map.csv`.** This is the
first half of action recognition step 7. It has one row per NTU120 class, with
evidence from -5 to +5 for `risiko` and `menschlichkeit`, a `paar` flag for
NTU's 26 mutual classes, and a note. It follows the "label activities, not
values" note in `02_processing.md`: the recogniser names actions, and the
table says what they mean.

- Strong risk: hitting, kicking, knocking over, knife, gun (+5, and -3 to
  menschlichkeit). Pushing and shaking a fist are +3.
- Strong humanity: hugging, giving, supporting (+4). Handshake, pat on the
  back, high-five and carrying together are +3.
- Classes the recogniser produced for ordinary conversation in the test
  corpus (point finger, touch pocket) have at most ±1.
- Warm-up exercises (side kick, arm swings) and signals that belong to the
  scene rather than a person (falling, staggering, hands up, "stop") are 0,
  with notes.

`action/sitrep_map.py` loads and checks it: every class once, in order, and
within ±5. A test compares the names with the model's label map when that map
is present. 310 tests pass.

**Open:**
- **Pair classes have no direction.** NTU does not record which of two people
  hits, so both would receive +5 risiko. The victim needs a rule, e.g. whose
  wrist moves toward whose body.
- **The table is not applied yet.** Turning probabilities into ratings is the
  SITREP formula, which is still undecided.
- **The longer prompt costs latency.** The three definitions add tokens,
  though there are now fewer rating fields to generate. Not measured.

---

## 2026-09-25 — Review of the name-tagging change; a failed naming pass no longer ends the session

Review of the entry below. Python, the OSC wire format, `sitrep_osc.py`, the
README and the TouchDesigner setup note agree. The grammar schema leaves out
the computed `einschreiten`. `uv.lock` matches `pyproject.toml`.

**One change.** The naming pass now runs inside the SITREP sampling loop
(`capture.windows` → `Session._name_faces`), so an error in the face models,
e.g. a CUDA out-of-memory error with Ollama holding the GPU, would have ended
the session. `Session._name_faces` now sends that frame unmarked and prints the
error to stderr. This follows `report.sitreps`, which skips a bad window
rather than ending the run. The Realtime-SITREP puts low latency ahead of
accuracy (`knowledge/components/02_processing.md`). 272 tests pass.

**Open, for Moe. Not changed, since each one changes how the tracker behaves:**
- **A tag can show a name the grammar doesn't allow.** Frames are tagged when
  they are sampled, but the name list comes from the roster when the window
  ends. If a track is recognised partway through the window (`Vielleicht:
  Jakob` becomes `Anna`), or `_adopt` gives it a stronger name, earlier frames
  show a label that isn't in the enum.
- **Two faces in one frame can both be tagged with one cast name.**
  `gallery.match` isn't one-to-one. If two faces both pass the threshold for
  Anna, both tracks take the name, `_merge_by_name` merges them into one
  track, and the model sees "Anna" on two people.
- **An error in the tracker's own thread stops it with no message.** This was
  already true. It matters more now that the tracker runs on every session:
  the roster sent to TouchDesigner would stop updating, and nothing would say
  why.

---

## 2026-09-28 — Pretrained action recognition, step 4: continuous pose, tracking, pairs (VSH-ARLT-5090)

`src/action/` feeds the NTU120 ST-GCN what it was trained on, from a live
source or a recording:

    python -m action --recording <file> --start 120 --duration 60

- **`preprocess.py`** reproduces the model's MMAction2 test pipeline in
  numpy: normalisation, joint features, frame sampling, decoding and person
  slots. It is **bit-identical** to MMAction2's output on the reference
  sequence. Its frame indices also match MMAction2's for 100-, 150- and
  250-frame sequences, the sampling branches the 75-frame reference doesn't
  reach. The export script now records those indices too. Three details
  decide the match:
  - The keypoints pass through float16.
  - The 10 test clips are sampled with a generator seeded at 255. A local
    `RandomState(255)` draws the same numbers without touching NumPy's
    global state.
  - An absent person is zeros before normalisation, so -1 after it, as in
    training.
- **`tracking.py`** gives each body a stable id by greedy box overlap between
  consecutive frames. A body may go undetected for up to 1 s and keep its id.
  Detections with fewer than 5 visible joints aren't followed.
- **`recognizer.py`** runs pose at **25 fps** and classifies the last **4 s**
  every second. 25 × 4 = 100 frames is exactly one clip. NTU clips mostly
  span a whole action in 100 or more frames, and a shorter window would be
  looped to fill the clip, showing the action faster and repeated. Each person
  present in at least half the window is classified alone, and each pair
  whose centres stay within 1.5 mean body heights is classified together.
  NTU recorded mutual actions with two people and single actions with one,
  so the model knows each only in that form. Everything in a window goes to
  the model as one batch.
- **`model.py`** runs the ONNX file on CUDA with TF32 off, and averages the
  softmax over the 10 clips as MMAction2 does.

**Measured** over 30 s of "Boom" from the test corpus: pose 8.2 ms per frame,
the action model 47 ms per window for all groups together, both on CUDA. 20
new tests, none needing the model or a GPU; 304 pass.

**Not measured: whether it recognises anything that matters.** The corpus is
improvised comedy with no violence. The readings are what NTU makes of people
talking:
- A woman holding a glass: "reading".
- Seated spectators: "playing with phone/tablet".
- Pairs in conversation: "point finger at the other person", "touch other
  person's pocket".

A test needs footage of the actions the SITREP cares about, such as staged
pushes, slaps or embraces, ideally from the production's own rehearsals.

**Open:**
- **The audience dominates.** Track ids reach 17 in 30 s as spectators at the
  frame's edges come and go, and each is classified. A stage region, or a
  minimum body size, would restrict recognition to the performers.
- **Readings aren't filtered or mapped yet.** Every reading carries all 120
  classes. Step 5 selects the classes of interest, and step 7 connects them
  to the SITREP's values.
- **Combined GPU load is unmeasured.** Pose at 25 fps takes about 200 ms of
  GPU time per second. That comes on top of the presence tracker's face
  passes, Whisper and Gemma, and all of them together have not been run.

---

## 2026-09-28 — GPU ONNX Runtime in Apollon's environment (VSH-ARLT-5090)

Pose detection, face recognition and the new action model now run on the GPU
in the `apollon` environment. Until now they ran on the CPU there, on every
machine (`hardware_issues.md` H-10). The step 3 entry below wrongly called this
a regression on the new machine: the laptop's `apollon` environment was CPU-only
too, and the GPU build H-10 describes lived in WISE's environment.

- **`onnxruntime-gpu[cuda,cudnn]==1.26.0`** is declared in `pyproject.toml`.
  It is the last CUDA 12 line, matching CTranslate2's, so the environment
  carries one CUDA runtime. It is also the first version with Python 3.14
  wheels on the CUDA 12 line; 1.27 onwards needs CUDA 13.
- **A uv override drops the CPU `onnxruntime`** that `rtmlib` and
  `faster-whisper` depend on. Both packages install the same `onnxruntime`
  module, and whichever lands last wins.
- **`apollon_pose.model` and `face.model`** put
  `site-packages/nvidia/*/bin` on PATH when torch isn't installed. The first
  attempt used `onnxruntime.preload_dlls()` alone, and cuDNN then failed on
  the first convolution: it loads `cudnn_engines_tensor_ir64_9.dll` by name
  and couldn't find it (`CUDNN_STATUS_SUBLIBRARY_LOADING_FAILED`).

**Verified:** all three models report `CUDAExecutionProvider`, and Whisper
still transcribes. 284 tests pass.

| Model | Before, on the CPU | Now, on the RTX 5090 |
|---|---|---|
| RTMO pose | 43 ms per frame | 8.1 ms per frame |
| Face detection and embedding | ~226 ms per pass | 10.1 ms per pass |
| NTU120 action model, 10 clips | 122 ms | 3.9 ms |

**TF32 changes results slightly.** ONNX Runtime's CUDA provider uses TF32 by
default, which moved the action model's probabilities by up to 8 × 10⁻⁴
against MMAction2 (2.7 ms). With `use_tf32=0` the difference is 3.6 × 10⁻⁷
(3.9 ms). The action model will run without TF32, which keeps its tests
exact.

---

## 2026-09-28 — Pretrained action recognition, step 3: exported to ONNX (VSH-ARLT-5090)

The NTU120 ST-GCN now exists as `data/models/ntu120_stgcn/stgcn_ntu120_2d.onnx`.
Apollon can run it with `onnxruntime` alone; MMAction2 and PyTorch are needed
only to produce the file. `src/scripts/export_ntu_stgcn.py` does the export
and checks it. Its docstring gives the environment setup, so the export can
be repeated.

**A separate conda environment, `mmaction`** (Python 3.10, torch 2.3.1 CPU,
mmengine 0.10.7, mmcv-lite 2.1.0, MMAction2 1.2.0). It follows the same
pattern as `wise`: a PyTorch stack that can't live in Apollon's Python 3.14
environment is kept apart. Three things needed working around:

- **MMAction2 1.2.0 can't be imported as packaged, from PyPI or from git.**
  `mmaction/models/localizers/drn` has no `__init__.py`, so the package build
  skips it, and `import mmaction.models` fails. The fix was an editable
  install from a clone at tag v1.2.0 in `external/mmaction2`, which is
  gitignored.
- **Pinned to torch 2.3.** From torch 2.6, `torch.load` defaults to
  `weights_only`, which checkpoints of this generation don't load under.
- **mmcv-lite rather than full mmcv.** ST-GCN needs none of mmcv's compiled
  operators, and full mmcv has no wheels for this setup.

**What was exported:** the network only, `cls_head(backbone(x))`. It takes
`(batch, 2 people, 100 frames, 17 joints, x/y/score)` and returns 120
logits, with a dynamic batch axis, at opset 17. MMAction2's preprocessing, and
its softmax averaged over 10 test clips, stay outside the file for Apollon to
reproduce in step 4.

**Verified:**

| Check | Max difference |
|---|---|
| Network: PyTorch vs ONNX Runtime, random input, logits | 1.9 × 10⁻⁶ |
| Recogniser: MMAction2 `inference_skeleton` vs ONNX fed MMAction2's preprocessing, 120 probabilities | 6.6 × 10⁻⁷ |
| The same, in Apollon's environment (onnxruntime 1.29.0) | 3.0 × 10⁻⁷ |

- **Speed in Apollon, on the CPU:** 10.6 ms per clip, about 130 ms for the
  full 10-clip average.
- **Reference fixture (`reference.npz`):** a synthetic two-person sequence
  of 75 frames at 1080p, with MMAction2's preprocessed tensor for it and its
  final prediction. Step 4's preprocessing is to be tested against it. It's
  synthetic, so it holds no footage of anyone.
- **The synthetic sequence's result:** its arm sweep was classified as
  "point finger at the other person" (0.67) and "pat on back" (0.24). Both
  are two-person classes, but that says nothing about accuracy on real
  footage.

**Found on the way: ONNX Runtime in the `apollon` environment is CPU-only on
this machine.** It is version 1.29.0 with no CUDA provider, which is the
silent regression `hardware_issues.md` H-10 warns about. The laptop's
`onnxruntime-gpu` was a manual install that was never declared, so it didn't
reach this machine, and RTMO pose detection runs on the CPU here too. The
recogniser itself is fast enough on the CPU. Fixing it means declaring the
GPU build in `pyproject.toml`; see H-10.

---

## 2026-09-28 — Pretrained action recognition, step 1: model chosen and downloaded (VSH-ARLT-5090)

This is the first step toward the *Pose* route under "Calculating Values" in
`knowledge/components/02_processing.md`: recognising activities such as
hitting or hugging, and mapping them to SITREP values. The plan starts from a
recogniser someone else trained. Training one on Apollon's own footage would
need a labelled archive first.

**Model: ST-GCN, joint modality, NTU RGB+D 120 cross-subject, 2D keypoints**,
from the MMAction2 model zoo. The choice rests on three points:

- **The keypoints match.** MMAction2's 2D NTU skeletons were produced with
  HRNet-w32 in COCO-17 layout, the same 17 joints in the same order that RTMO
  (`apollon_pose`) outputs.
- **NTU120, not NTU60.** NTU120 has all 26 two-person classes. Only it has
  "hit other person with something", "wield knife towards other person" and
  "knock over other person". The NTU60 models score higher (ST-GCN++ 89.3%)
  but lack these classes.
- **Joint modality, plain ST-GCN.** It takes raw keypoints, with no bone or
  motion features to derive, at 83.19% top-1 against 83.36% for the bone
  variant. It is also the simplest architecture on offer, which matters for
  the ONNX export in step 3.

Files are in `data/models/ntu120_stgcn/`, which is gitignored. `SOURCE.md`
there gives URLs and the checksum. MMAction2 publishes only an NTU60 class
list, so `label_map_ntu120.txt` was assembled from it and the official NTU
README; the first 60 classes agree exactly.

**Verified** in the `wise` environment, which has torch:
- The SHA-256 begins `612416c6`, matching the filename.
- 3.1 M parameters and a 120-class head.
- The input batch norm expects 51 values: 17 joints × (x, y, confidence).

**What step 4 has to reproduce**, per the config:
- `PreNormalize2D` normalises keypoints to the image size.
- `FormatGCNInput` always takes two people, padding the second with zeros.
- `UniformSampleFrames` resamples every clip to 100 frames, whatever its
  length; testing averages 10 such clips. NTU clips run about 2–5 s, so a live
  window should be about that long, resampled the same way.

**Licence:** NTU RGB+D is "for academic research only … for non-commercial
purposes" and prohibits "derivation … and commercial usage … in any way or
form" without permission from ROSE Lab. Moe confirmed that the theatre
project is part of a research project, which these terms cover.

Training Apollon's own recogniser on rehearsal footage is listed as a
nice-to-have in `todo_with_data.md`.

---

## 2026-09-25 — Operator page: the live SITREP in the browser (VSH-ARLT-5090)

The live SITREP is displayed in a browser instead of TouchDesigner. Laid out
with a Text TOP, the report was unreadable as a display. Moe decided that
TouchDesigner keeps receiving the report as OSC data, but no longer lays it
out. This completes step 7 of the Realtime-SITREP in
`knowledge/components/02_processing.md` ("video output ... and SITREP text
beneath it"). It also starts the localhost interface of the same file, as
planned in `progress_tracker.md` (Smart Search, phase 5: "FastAPI plus plain
HTML").

    uv run apollon-ui --video "OBS Virtual Camera" --model gemma4:26b

- **Operator page (`/`)**: a single button, **Start live SITREP**, which opens
  `/sitrep` in a new tab.
- **SITREP page (`/sitrep`)**: starts the run on opening and shows the camera
  feed with the report beneath it. The report shows the Empfehlung as a banner
  that turns red above the threshold, the Beschreibung and transcript, the
  three scene ratings as bars with the threshold marked, a card per person
  (guessed names marked) and the three forecasts with probability bars. The
  last report stays on screen after a stop. Model text is set with
  `textContent` only, so a reply cannot inject markup.
- **Transport**: the camera goes to the browser as MJPEG, which an `<img>`
  plays with no script. Reports arrive as server-sent events, which reconnect
  on their own.
- **`interface.live.LiveSitrep`** holds the single run on its own thread. It
  opens the session on request, so device errors show on the page rather than
  in the terminal.
- **Binding**: `apollon-ui` binds 127.0.0.1:9680, for the same reason as the
  WISE server: the page shows footage of identifiable people.
- **New dependencies**: `fastapi` 0.141.1 and `uvicorn` 0.54.0.

**A COM fix was needed.** Resolving the camera from the run's thread failed
with `CoInitialize has not been called`. `pygrabber` enumerates cameras through
DirectShow, a COM API, and `comtypes` initialises COM only on the main thread.
`devices.list_video_devices()` now initialises and releases COM around the
enumeration, which works on any thread.

**Verified end to end** with OBS Virtual Camera playing a test recording and
`gemma4:26b`:
- A run started through the API and reached `running`. The tracker named two
  people, and the report arrived with every field.
- The video endpoint delivered 44 JPEG parts in 3 s (about 15 fps).
- Headless Edge rendered both pages. It doesn't paint MJPEG streams, so the
  video area was black in its screenshot only.
- 284 tests pass. The feed generator is tested directly, because Starlette's
  test client buffers whole responses and never returns from an open-ended
  stream.

**Open:**
- **Closing the tab doesn't stop the run.** A second viewer, or a later
  TouchDesigner Web Render TOP, would otherwise stop it for everyone. The
  camera stays held until Stoppen or until the server exits.
- **Stopping takes up to one window.** The camera is released at once, but
  the run's thread finishes the generation it is in before another run can
  start.
- **OBS's virtual camera delivers 640×480** unless its output resolution is
  raised. At that size the faces in a stage wide shot are small for
  recognition.
- **The alarm state is untested with the real model.** No test scene has
  crossed the threshold.

---

## 2026-09-25 — Names drawn onto the model's frames; scene ratings decide intervention (VSH-ARLT-5090)

Two changes asked for by Moe, following the entry below.

**The model reads who is who.** The previous entry left the model with a
list of names and no positions, so with several people in frame a name, and
that person's `gefahr`, could land on the wrong person. Each frame sampled for
the model now carries a tag with the tracker's name above every face:

- `PresenceTracker.name_faces(frame)` runs a pass over that exact frame and
  returns each face's box with its track's label. Running the pass on the
  sampled frame, rather than reusing the tracker's last boxes, keeps every
  tag on its face even when people have moved. Tracks now keep the box of
  their latest sighting.
- Passes are serialised by a lock. The tracker's own thread and the sampling
  loop both run them, and two interleaved passes could each start a track for
  the same new face, putting one person on the roster twice.
- `src/sitrep/annotate.py` draws a yellow box and a white-on-black name tag,
  using Pillow (12.3.0, new dependency). OpenCV's fonts cover ASCII only, and
  a cast name with an umlaut has to appear on the frame exactly as in the
  name list the grammar enforces. Only the model's copy is marked; the NDI
  feed stays clean.
- `capture.windows()` takes an `annotate` hook, applied to each frame before
  encoding. The session passes the tracker's names through it.

Verified on three frames of stage footage with the real tracker and
`gemma4:26b`. Three faces were tagged (`Vielleicht: Sophie`,
`Vielleicht: Matthias`, `Vielleicht: Hedda`), and the report put each name on
the right person: Sophie standing with the glass, Matthias seated and
gesturing, Hedda in the background. A naming pass costs ~150 ms per sampled
frame; the first costs ~10 s, loading the face models. Generation took 5.2 s.

**Scene ratings decide intervention.** The report has a new `szene` with
`relevanz`, `eskalation` and `gefahr`, 0–10 from low to high. It is separate
from the 0–5 ratings per person. The Empfehlung is written only when
`eskalation` or `gefahr` is above 6 (`report.SCHWELLE`):

- `einschreiten` is a computed field of `Lagebericht`, derived from the scene
  ratings. It is absent from the schema the model is given, so the model has
  no field in which to decide it.
- The model is told to write a measure only above the threshold. Any measure
  it writes below the threshold is discarded.
- `empfehlung` is now the measure as a string. The `Empfehlung` model is gone.

OSC: a new `/apollon/sitrep/szene <id> <relevanz> <eskalation> <gefahr>`.
`/apollon/sitrep/empfehlung` keeps its shape, with `einschreiten` now derived.
`sitrep_meta` in TouchDesigner gains the three scene columns. 271 tests pass.

**Open:**
- **The threshold path is untested live.** The test scene rated eskalation 1
  and gefahr 0. Whether the model writes a usable measure when a scene does
  cross 6 has only been checked in unit tests, which don't run the model.
- **An empty measure above the threshold is possible.** The grammar can't make
  a field required only above 6. If the model leaves it empty, the report
  shows EINSCHREITEN with no action.
- **`menschlich` came back 0 for all three people** in the test run. It may
  be misread as "is not human-like". The category may need a description in
  the prompt, as `relevanz` has.

---

## 2026-09-25 — SITREP fields redefined; the roster names the people in the report (VSH-ARLT-5090)

**Machine:** `VSH-ARLT-5090`, the production workstation: RTX 5090 (32 GB),
i9-14900KF, 128 GB RAM (`hardware_issues.md`, reference machines).

The report's fields were set by Moe. They refine "write SITREP report" in
`knowledge/components/02_processing.md` (Realtime-SITREP) and replace the
`Lagebericht` of 2026-09-09:

| Field | Content |
|---|---|
| `beschreibung` | what happened, who did what, briefly |
| `personen` | `name`, `beschreibung` (how the person comes across), and 0–5 ratings `kollaborativ relevanz verantwortungsvoll menschlich gefahr` |
| `prognose` | exactly three developments, each with a probability in percent, most likely first |
| `empfehlung` | `einschreiten` (bool) and `massnahme`; intervening is instructed to be the exception |

`lage`, `ereignisse`, `vertrauen`, `kennung`, `merkmale` and `taetigkeit` are
gone. `relevanz` is new. `vertrauen` never tracked accuracy
(`claude_concerns.md`, smaller items).

**Names come from the presence roster.** This is the first open increment under
"Cast recognition" in `progress_tracker.md`. `Sitrep` carries the tracker's
roster for its window as a measured field, `anwesend`. The prompt lists it,
and the schema sent to Ollama holds `Person.name` to that list plus
`Unbekannt`. The model therefore picks names it was given and cannot invent
one. So that every person carries a name, **the presence tracker now runs on
every session**, not only with `--cast`: without a cast, every name is a
guess (`Vielleicht: Jakob`).

**The grammar enforces both constraints.** Checked against `gemma4:26b`: asked
to name two people "Anna and Bert", it used only the enumerated names; asked
for one forecast, it returned exactly three. The three forecasts are sorted by
probability in `report.py`, so renderers can take the first one as the most
likely without relying on the model's order. A declined intervention clears
`massnahme`, since models phrase "no action" as an action.

**OSC wire format changed** (`src/sitrep/td.py`): `/apollon/sitrep/lage` and
`/ereignis` are replaced by `/beschreibung`, `/prognose <rang>
<wahrscheinlichkeit> <verlauf>` and `/empfehlung <einschreiten> <massnahme>`.
The person row is `<zeile> <name> <vermutet> <beschreibung>` plus the five
ratings. `TouchDesigner/code/sitrep_osc.py` and
`TouchDesigner/2026-09-25_touchdesigner_setup.md` follow: `sitrep_prognose`
replaces `sitrep_ereignisse`. The note of 2026-09-24 that the report and roster
tables must not be joined no longer applies: a report name is a roster label.

**First generation on the production machine.** `gemma4:26b` on three frames
of stage footage with five people in shot, with the new schema: 3.7 s and
4.2 s warm (14.3 s including the model load). The description matched the
frame, including clothing, a glass held and a bearded man with glasses
gesturing. That is the kind of detail e4b invented on the laptop. Three runs,
not a benchmark (`hardware_issues.md`, H-1).

`NUM_PREDICT` rose from 700 to 1000 for the three forecasts. 251 tests pass,
none needing a camera, a model or TouchDesigner.

**Open:**
- **Names are assigned by the model, not measured.** It receives the roster
  without positions, so with several people in frame a name, and that
  person's `gefahr`, can land on the wrong person. In the test run it placed
  the one recognised name on the right man, but it had no way to know.
  *Resolved in the entry above: names are drawn onto the frames.*
- **The intervention threshold is a placeholder.** The prompt says to
  intervene only "wenn die Lage ohne Eingriff eskaliert". What counts as a
  reason to intervene is a dramaturgical decision for Moe. *Resolved in the
  entry above: scene ratings above 6.*
- **Audience members are reported as people.** Background spectators appear
  in `personen` with ratings. Whether they belong in the report is undecided.
- **Probabilities are not required to sum to 100.** The prompt asks for at
  most 100 in total, and nothing checks it.
- The camera on this machine delivered a completely black frame
  (`NDI Webcam Video 1`, no NDI source feeding it), which produced empty
  reports at 0/5 confidence. It is not a fault in Apollon, but it is
  indistinguishable from an empty stage in the report.

---

## 2026-09-24 — The live SITREP reaches TouchDesigner: NDI and OSC (MININT-ITT28VU)

**Machine:** `MININT-ITT28VU` (user `ctech`), RTX 4070 Laptop, TouchDesigner
2025.31760 Non-Commercial on the same machine.

The live camera and the generated report now leave Apollon for TouchDesigner,
which is step 7 of the Realtime-SITREP in
`knowledge/components/02_processing.md` ("Output: video output ... and SITREP
text beneath it"). The two channels are the ones
`knowledge/components/03_render.md` describes: "OSC carries messages, not
pixels."

    apollon-sitrep --send-ndi                      # the camera as an NDI source
    apollon-sitrep --send-td                       # report and roster over OSC
    apollon-sitrep --send-ndi --send-td --cast data/cast

**Pixels travel as NDI.** `src/sitrep/feed.py` publishes the camera as an NDI
source that TouchDesigner receives with its native NDI In TOP. Spout would have
been the obvious same-machine choice and is what 03_render.md names, but
`SpoutGL` publishes no wheel for CPython 3.14, which this environment runs;
TouchDesigner's Shared Mem In TOP requires a licence above Non-Commercial; and
Video Stream In TOP takes RTSP, HLS/DASH, SRT and WebRTC but not HTTP MJPEG.
`cyndilib` was the one NDI binding with a 3.14 Windows wheel. The NDI runtime
needed no separate install: TouchDesigner ships `Processing.NDI.Lib.x64.dll`.

The transport is one class. `feed.Sink` is opened through `feed.open_sink`, so
TouchDesigner's shared memory, or an ffmpeg process serving SRT, would
substitute without anything above that line changing. **A TouchDesigner licence
upgrade would not change this design**: neither operator used is licence-gated,
and Spout stays blocked by the Python version rather than by the licence.

**Cost: 0.94 ms p50 per frame** at 640x360 on CPU, sending at 30 fps — far
below the 226 ms the presence pass costs. Publishing does not show up in the
report path either: four consecutive windows with NDI running came in at 4.6,
6.5, 5.1 and 6.9 s against a 15 s window, none skipped. Both figures are at the
webcam's default 640x480; a 1080p stage camera is untested.

**Messages travel as OSC**, in the begin/row/end shape `smartsearch/td.py`
established, so one OSC In DAT receives search results and the live SITREP and
routes on the address prefix:

    /apollon/sitrep/begin  /sitrep/lage  /sitrep/gesagt
    /apollon/sitrep/person /sitrep/ereignis  /sitrep/end
    /apollon/presence/begin  /presence/person  /presence/end

`begin` carries the row counts so TouchDesigner can size a table before its
rows arrive. Ratings are read off `report.BEWERTUNGEN` rather than named, so
renaming a category fails a test instead of silently shifting a column in
TouchDesigner. The transcript is sent even when the room was silent, so the
table keeps its shape.

The roster is a second, faster stream rather than a field of the report: a
report arrives once a window while the tracker reads the room twice a second,
and carrying the roster on the report would make "who is on stage now" lag by
up to a whole window. Its `tick` counts upward so a receiver can discard a
reading that arrived out of order.

**One camera, three readers.** `capture.run()` opened and closed its own
`VideoStream`, which is what prevented sharing — and DirectShow refuses a
second process the device, so TouchDesigner cannot open the camera itself.
`capture.windows()` is now the sampling loop over a stream it does not own, and
`run()` is the standalone form that opens one. `src/sitrep/session.py` holds the
camera, the microphone, the presence tracker, the publisher and the OSC sender;
readers are closed before the camera, and a reader that fails to start unwinds
the session rather than stranding the device with no handle to it.
`report.run_live()` is replaced by `report.sitreps(windows)`, which takes the
windows rather than the devices that produce them and is testable without a
camera.

`Session` is also the shape the localhost interface of `02_processing.md` will
need: one object to start, one to stop. Its options are a pydantic model so
that interface receives them as a request body.

**`src/osc/` is a new shared package.** `Sender`, `Message` and the TouchDesigner
host and port moved there from `smartsearch`. There is one TouchDesigner and
one OSC In DAT; two definitions of its address would drift, and the live path
should not have to import the retrieval path to reach it.

**`uv sync` used to remove `rtmlib`**, which `apollon_pose` imports to load the
RTMO model, because it was installed by hand with `--no-deps` and was therefore
absent from the lock. It is now declared in the root project, with a uv override
dropping its request for `opencv-contrib-python` — that package ships its own
`cv2` and collides with the pinned `opencv-python`, which is why the manual
install skipped its dependencies. Body search survives a sync now.

**Verified end to end:** two reports with both channels open, on the real
camera and microphone. Latency 8.7 s and 4.7 s against a 15 s window, so the
run keeps pace with the video feed running. TouchDesigner held port 10000
throughout and received the messages directly. 228 tests pass, none of them
needing a camera, a model, NDI or TouchDesigner.

**Open:**
- **The roster path is untested end to end**, because `data/cast` holds no
  enrolment photographs yet. The messages and the stream are unit-tested; what
  has not run is a rehearsal with names in it.
- **Two unjoined views of the same room.** The roster's `label` does not
  correspond to the `Person.kennung` the model assigns in the report; the model
  is still not told who is present. Joining them is the first open increment
  under "Cast recognition" in `progress_tracker.md`. Nothing in TouchDesigner
  should try to join those two tables.
- **NDI cost at 1080p** is untested. The webcam delivers 640x480 by default,
  which is a quarter of the pixels a stage camera will; `--ndi-fps` and
  `--width/--height` are the levers if it bites.
- `03_render.md` names Spout or NDI for live frames without deciding; the
  decision taken here, and why Spout was not available, is recorded in this
  entry for Moe to reconcile into that file.

---

## 2026-09-24 — Presence tracker: `sitrep/presence.py` (MININT-ITT28VU)

**Machine:** `MININT-ITT28VU` (user `ctech`), RTX 4070 Laptop, 8GB VRAM, 32 cores.

`src/sitrep/presence.py` follows every face the camera shows, names the ones
the enrolled cast matches and guesses at the rest. It turns the per-frame recognition of the entry
below into a roster of who was in the room over a stretch of time, which is
what the Realtime-SITREP of `knowledge/components/02_processing.md` needs for
"who is in the scene". The report does not consume the roster yet.

    python -m sitrep.presence --cast data/cast
    python -m sitrep.presence --cast data/cast --recording rehearsal.mp4 --start 4200

**Runs at its own rate, not the window's.** Two passes a second against a
SITREP window that reaches the model every five or ten seconds. A window is far
too sparse to follow a person across, and the tracker also keeps observing
during generation, when capture is otherwise blind (`claude_concerns.md`,
"Coverage gaps between windows"). The source is anything presenting a
`latest()`, which is how `capture.VideoStream` already presents the camera, so
the two share one camera rather than opening it twice.

**Face detection alone, no body detection.** The tracker was designed around
RTMO supplying bodies and face recognition naming them. Measured first: across
the Othello stage footage and the DT Berlin rehearsal, face detection finds
94-100% of the people RTMO's body detection finds. The second model was
dropped, which keeps one model in the live path. This holds for camera-facing
performance and documentary footage, which is all the corpus has; a Probebühne
wide shot with actors turned upstage is untested and is where a body layer
would earn its place.

**Two association cues, and the second one is what makes it work.** A face
close enough to a track's own stored faces joins it, greedily, strongest pair
first. A face the gallery *names* then joins whichever live track already
carries that name. The first cue alone fragmented badly: in a 120-second
replay one actor appeared as three simultaneous `person_02` tracks, because a
person's own frontal and profile views can sit below the link threshold — the
same person across a long stretch drops to 0.39 at the fifth percentile — while
the enrolment holds several angles and recognises both. Live tracks that end up
sharing a name are folded into the earliest of them, which keeps its identifier
and its first sighting.

**Everyone in the room is accounted for, and unknown people are guessed at.**
A face the cast gallery does not match is given an invented German first name
marked as a guess — `Vielleicht: Jakob` — rather than a number, and every
detection reaches the roster on its first sighting. The guess lasts as long as
the track: a person seen again after an absence is guessed at afresh, so the
same face can be Bastian and later Theo. Once the gallery does recognise
someone, the guess gives way to their real name.

An earlier version required three sightings before a track counted as present,
to keep single-frame detections off the roster. Dropped on Moe's instruction:
every person entering has to be recognised by the system.

**Measured on Othello.** Enrolment photographs were cut from the first 20
minutes for 10 of the 12 identities, and the tracker replayed 120 seconds
starting at 70 minutes — footage the enrolment never saw. Two identities were
deliberately left unenrolled, both of them absent from the first 20 minutes.

- No name was ever held by two live tracks at once.
- No track ever changed name.
- Named tracks held for 44-114 seconds and 25-151 sightings.
- 15% of detected faces were guessed at rather than recognised, across 20
  short tracks.
- Every recognised track was checked by eye against its enrolment photographs
  and was the right person. The largest guessed track, 25 sightings of one of
  the two unenrolled actors, held one invented name throughout.

**`face.detect.SCORE_THRESHOLD` is 0.60**, raised from 0.50. Everything the
detector returns becomes a person on the roster, and at 0.50 that included
panels of patterned stage cloth. Over 150 frames the change drops 14 of 341
detections: four panels of scenery, several backs of heads, one actor's face
repeatedly covered by a hand, and one clear profile.

It does not reduce the number of guessed people — twelve at both thresholds —
because removing a weak sighting also splits a track, so single-sighting
guesses rose from six to eight. Recognition is untouched: the same five people
are recognised, with one sighting fewer out of 294. The threshold is the right
lever for scenery, not for phantoms; the lever for those is `FORGET`, which
holds a lone detection on the roster for thirty seconds.

**Cost: 226 ms p50, 320 ms p95 per pass** on a 1080p frame, CPU, at four
inference threads — about a tenth of the machine at two passes a second. What
this costs while Ollama is generating is still untested.

**Replay time is counted from `REPLAY_EPOCH`**, an arbitrary reference far
enough from `datetime.min` that subtracting the forget window cannot underflow.
Counting from `datetime.min` crashed any replay started at the first frame.

`data/cast/` holds the enrolment: one folder per person, named after them,
carrying five to ten photographs. The convention is in `README.md` and in that
folder's own README; `data/` stays untracked, since the photographs are of
identifiable people.

**Next:** wiring the roster into the SITREP. `Window` gains the people seen
during it, `Sitrep` carries them as a measured field beside `quelle` and
`gesagt`, and `Person.kennung` becomes a value the model selects from a fixed
roster rather than one it assigns.

---

## 2026-09-23 — Face recognition: `src/face/`, measured on the corpus (MININT-ITT28VU)

**Machine:** `MININT-ITT28VU` (user `ctech`), RTX 4070 Laptop, 8GB VRAM, 32 cores.

`src/face/` detects faces, embeds them and matches them against an enrolled
cast. This is the identity half of "who is in the scene" in the Realtime-SITREP
of `knowledge/components/02_processing.md`, and the mechanism behind that
file's "provide the system with images of each team member". The SITREP does
not use it yet; this step establishes what it does on footage like the corpus.

    python -m face.gallery data/cast

**Two ONNX models from InsightFace's `buffalo_l`**, run directly rather than
through the `insightface` package: SCRFD-10GF for detection, which returns a
box and the five landmarks alignment needs, and ArcFace R50 for a
512-dimension embedding. `insightface` builds from source on this
environment's Python 3.14 and carries a second numpy stack; the models need
only onnxruntime, numpy and cv2. `buffalo_l` is chosen over the smaller
bundles because WISE's own face extractor uses it
(`knowledge/background/wise_clip_as_query.md`), so a future Hindsight-SITREP
face index would share one embedding space with the live path rather than
two.

The package sits in `src/` beside `sitrep` and `smartsearch`, not in
`wise_ext/`. `apollon_pose` lives there because it registers a feature extractor
inside WISE's conda environment; face recognition runs on the live camera
stream and has no such constraint.

**Identity is measured, not generated.** The design follows the separation
already in `src/sitrep/report.py`, where the transcript is Whisper's and the
model may not invent speech. A name will reach the report as a measured field
beside `zeitfenster` and `quelle`, not as something `gemma4:e4b` is asked to
read off a photograph. A person is kept as the set of their enrolled vectors
rather than one average, and a match below threshold is reported as unknown
rather than as the nearest name.

### Measured on the corpus

Two videos, sampled as stills: the characterisation workshop (12 min, 720p,
1582 faces from 365 stills) and Othello (first 2 hours, 1080p, 2173 faces from
900 stills). Ground truth was built by clustering the embeddings and then
confirming every cluster and every merge by eye against contact sheets: 6
identities in the workshop, 12 in Othello.

Recall at 100% precision, enrolling the three largest faces per person:

| | thr 0.30 | thr 0.35 | thr 0.40 | thr 0.45 |
|---|---|---|---|---|
| workshop, 6 people | 0.955 | 0.905 | 0.796 | 0.606 |
| Othello, 12 people | 0.992 | 0.979 | 0.937 | 0.883 |
| Othello, enrolled on close shots, probed on faces under 50px | 0.980 | 0.955 | 0.864 | 0.763 |
| Othello, enrolled in the first 20 min, probed after the first hour | 0.992 | 0.983 | 0.965 | 0.902 |

**No wrong name was produced anywhere in any sweep.** In the last row 149 of
the 811 probes are actors who appear only later and were never enrolled; all
were correctly left unnamed. Stage lighting does not break the match: the same
face under a deep blue wash and under a red wash scores 0.6-0.8.

**Strangers stay unnamed.** Leave-one-person-out, each identity in turn removed
from the gallery: 0 of 2028 Othello probes and 0 of 1212 workshop probes were
given a name at threshold 0.35 or above. Across 60,600 different-person pairs
the highest similarity observed was 0.35, against a same-person median of 0.48
(workshop) and 0.60 (Othello).

**Face size is the limit, not lighting.** Recall at threshold 0.40 by size in
frame: 0.49 under 30px, 0.79-0.82 at 30-40px, 0.90 at 40-60px, 0.98 above
120px. Enrolment count matters about as much: one photograph gives 0.62,
three 0.76, ten 0.86 on the same probes.

Threshold 0.40 is the default in `gallery.THRESHOLD`: it sits above every
different-person pair observed and still names four probes in five. Lowering
it buys recall the measurements say is still free of wrong names, but the
sample is 18 people.

**Caveat on recall.** Ground-truth clusters were formed by this same model, so
faces it embeds oddly are over-represented among those excluded from the
labelled set. The precision figures do not have this problem; they come from
held-out identities.

### ONNX Runtime thread default costs 3.6x on CPU

A detect-and-embed pass over a 1080p frame with 3.6 faces takes **802 ms p50**
at ONNX Runtime's default thread count and **222 ms p50 / 493 ms p95** at four
threads. The default is one thread per core, which on 32 cores costs more in
synchronisation than it wins, and costs more again when two sessions are called
alternately. `face.model.THREADS` caps it at four, overridable with
`APOLLON_FACE_THREADS`.

Both models run on `CPUExecutionProvider`: ONNX Runtime resolves no CUDA
provider in this environment, the same condition pose detection runs under
(`hardware_issues.md` H-10). `apollon_pose` does not pay this penalty: measured
again alongside the face models it runs at 42 ms per frame on CPU at the
default thread count, matching its original figure. The cost appears when two
sessions are called alternately, which pose alone never does.

**Next:** the presence tracker that turns per-frame recognition into a per-
window roster, then wiring that roster into the SITREP prompt and schema.
At 222 ms a pass, a tracker reading the camera at 2 fps fits alongside Whisper
and Ollama; the blocking question is what it costs during generation, which is
untested.

---

## 2026-09-17 — Segment results: `--segments` (MININT-ITT28VU)

**Machine:** `MININT-ITT28VU` (user `ctech`).

`query`, `body` and `body-live` take `--segments`, which returns the indexed
four-second windows in place of merged spans.

    apollon-search query "zwei Personen streiten" --segments --send-td
    apollon-search body-live --segments --send-td

**Why.** A merged span grows with every neighbouring window that matches, so
where a long stretch of a recording resembles the query — one person, barely
moving, in the webcam test — a single result ran to 122 s, and its bounds
shifted from search to search as different windows matched, so the same moment
was cut to a new clip file each time: 70 of 209 clips overlapped another by
more than 80%, about 1.2 GB. Segment results are always four seconds and always
on the index grid, so a moment found again reuses its clip.

**What WISE sends.** Every result block carries both forms, `merged_windows`
and `unmerged_windows`, with identical fields; `client.py` names them and
picks one. The client's earlier fallback looked for a `vectors` key WISE does
not send. In segment mode one vector is one result, so exactly `limit` vectors
are retrieved rather than ten per wanted moment.

**Live captures do not merge in segment mode.** Windows of one movement
retrieve the same segments, so a segment found by several windows is kept once
with its best score, and neighbouring segments are left separate; joining them
would rebuild the long spans.

**Granularity differs by index.** The text index holds one vector per frame at
2 fps, and its windows sit half a second apart, so a strongly matching moment
yields several near-identical results (567.0–571.0 and 567.5–571.5). The pose
index is segment-level and steps by two seconds.

**Verified** against the served corpus: `"a person kneeling on the floor"`
returns the same top moments in both modes with identical scores, as
four-second windows in segment mode; cutting the top three twice produced three
clip files, not six. 137 tests pass.

**Left open, on Moe's decision:** a maximum clip length for merged results.
Whether merged spans need capping, and at what length, is to be judged once the
system is used in rehearsal. Scores also rise with the length of a live
capture, since the best score over all its windows is kept; a threshold in
TouchDesigner must allow for this.

---

## 2026-09-17 — Smart Search phase 3: search by a movement performed live (MININT-ITT28VU)

**Machine:** `MININT-ITT28VU` (user `ctech`), RTX 4070 Laptop, 8GB VRAM.

A movement performed in front of a camera is the query. A start press and a
stop press bracket the capture, and the results reach TouchDesigner like any
other search. This is embodied search, "body", in
`knowledge/components/02_processing.md` ("press a button, then press a button
again after a few seconds to capture that live sequence") and the
`QB["BODY SEARCH"] → ENC["Live encoder"]` path of the RENDER graph in
`knowledge/source_of_truth/pipeline.md`.

    apollon-search body-live --send-td
    apollon-search body-live --video "FHD WebCam" --per-file 2 --send-td
    apollon-search body-live --file <recording.mp4> --at 300

**Presses** come from the terminal (Enter toggles) and over OSC,
`/apollon/body/start` and `/apollon/body/stop` on `127.0.0.1:10001` — the return
channel from TouchDesigner or QLab drafted in `knowledge/components/03_render.md`.
A start while capturing or a stop while idle is ignored, so a doubled button
press neither cuts a capture short nor searches with nothing.

**Bodies are detected while the movement happens.** `smartsearch.live` samples
the camera at the index's rate, four frames a second, detects poses immediately
and keeps only keypoints. Detection runs on the CPU in Apollon's environment at
42–45 ms per frame whatever the resolution, since RTMO letterboxes to 640 px:
under a fifth of the sampling interval. A capture of any length costs next to no
memory, and its query is ready when the stop press arrives. If detection ever
falls behind the sampling interval it is reported, since the movement would
then be spread over fewer frames than the index expects.

**A capture is searched in the shape of the index.** Indexed segments are 16
frames over four seconds, stepped by two, and a query of a different length
describes a differently paced movement. A capture is therefore cut into
four-second windows stepped by two seconds, the last aligned to the end of the
capture, and each window is searched on its own. A capture shorter than four
seconds is extended backwards from the stop press to a full segment, which is
how the index saw a short movement. Windows with no body are skipped. Results
from the windows are merged: overlapping hits in one recording become one hit
spanning both, with the better score.

**`--per-file N`** keeps at most N results from any one recording, retrieving
five times as many candidates so the list still fills. This is the result cap
`progress_tracker.md` placed in this phase; excluding the recent past is not
implemented, as the offline index holds nothing from the session being
captured.

**`--file`** plays a recording in real time in place of the camera, so the
workflow can be rehearsed and tested on footage whose content is known.

**Verified** against the served corpus, with presses sent over OSC and the
workshop and 4K Theaterprobe recordings played through `--file`:

| Capture | Rank 1 | Score | Next |
|---|---|---|---|
| 4.2 s, workshop 133.7–137.9 s, 2 windows | its own span, 132–165.75 s | 0.931 | 0.570 |
| 10.0 s, workshop 139.8–149.9 s, 5 windows | its own span, 134–165.75 s | 0.982 | 0.612 |
| 6.1 s, Theaterprobe crawl 300.6–306.7 s, 3 windows | its own span, 284–335.75 s | 0.929 | 0.674 |

From the stop press to the result table took 0.23 s, and to the first clip
announced 0.64 s. `--per-file 2` held the Theaterprobe capture to two results
per recording. 4K VP9 playback kept real time and detection never fell behind.
130 tests pass, 22 of them new, needing no camera, model, server or
TouchDesigner.

**Open:** the camera itself is untested in this path — `--file` exercised
everything but `sitrep.capture.VideoStream`, which the SITREP already uses.
Merged spans are long (51 s for a 6 s capture), carried over from phase 2's
overlap merge into clip length.

---

## 2026-09-17 — Search results reach TouchDesigner: clip cutting and OSC (MININT-ITT28VU)

**Machine:** `MININT-ITT28VU` (user `ctech`), RTX 4070 Laptop, 8GB VRAM;
TouchDesigner Non-Commercial on the same machine.

A search result becomes a clip file and an OSC message, so TouchDesigner can
play what Apollon finds. This is the `HITS → CUT` node of the RENDER graph in
`knowledge/source_of_truth/pipeline.md` and "Results are piped into
TouchDesigner" in `knowledge/components/02_processing.md`, following the
interface drafted in `knowledge/components/03_render.md`.

    apollon-search query "zwei Personen streiten" --send-td
    apollon-search query "zwei Personen streiten" --cut precise --send-td
    apollon-search body <clip.mp4> --at 90 --send-td

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

    /apollon/results/begin  <query_id> <count>
    /apollon/results/hit    <query_id> <rank> <clip_path> <ts> <te> <score> <source_file> <preroll>
    /apollon/results/end    <query_id>

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
Apollon sends every result; how many are used is decided in TouchDesigner
(`03_render.md`, "How many results reach the stage"). OSC goes to
`127.0.0.1:10000` by default.

ffmpeg 6.1.2 (GPL) is taken from the `wise` conda environment, found the same
way as `wise.exe`. `python-osc` 1.10.2 was added to the `apollon` project.

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
`apollon/pose/rtmo-s/body7` holds **7,439 vectors**, one per four-second segment,
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

`apollon_pose.model` now prepends torch's `lib` directory to `PATH`, where a
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

    apollon-search add-extractor --project P --video-id apollon/pose/rtmo-s/body7
    apollon-search index --project P
    apollon-search body <clip.mp4> --at 134 --project P

**One encoder, installed in both environments.** `wise_ext/` holds the
`apollon_pose` package: RTMO keypoint detection and the embedding, in pure numpy
with no declared dependencies. WISE's environment imports it to build the index,
Apollon's imports it to encode a live query. A query encoded even slightly
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
`0006-register-apollon-pose-extractor.patch`. Only the two registration lines are
patched; the extractor itself stays in this repository.

**No WISE patch is needed to query it.** WISE decodes every visual query as a
still image and cannot embed a clip, but `/search_with_feature` accepts a
finished vector, so Apollon runs the same encoder on the query clip and posts the
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

## 2026-09-11 — Smart Search phase 1: WISE driven from Apollon, sample corpus indexed (MININT-ITT28VU)

**Machine:** `MININT-ITT28VU` (user `ctech`), RTX 4070 Laptop, 8GB VRAM.

`src/smartsearch/` is an installed package that builds, serves and queries a
WISE search index from the `apollon` environment. It implements the "Process
rehearsal footage from folder on computer" and "Feature embedding that WISE
offers out of the box" points of the Smart Search affordance in
`knowledge/components/02_processing.md`, and fills the
`IDX[("Search index")]` node of `knowledge/source_of_truth/pipeline.md`. The
4h08m test corpus is indexed and searchable by text over both picture and sound.

The roadmap for the rest of Smart Search — clip-as-query, embodied search, the
pose extractor, speech, the localhost UI — is in `progress_tracker.md`.

    apollon-search extract --project rehearsals --media <folder>
    apollon-search index --project rehearsals
    apollon-search serve --project rehearsals
    apollon-search query "zwei Personen streiten" --project rehearsals
    apollon-search query "applause" --project rehearsals --target av

**Two processes, one HTTP boundary.** WISE keeps its own conda environment,
whose torch stack is pinned under `numpy<2` by MS CLAP, and is never imported.
Batch operations go through its command line as a subprocess; retrieval goes
through its REST API. `wise_cli.py` builds each command line as a pure function
and runs it separately, so argument lists are testable without a subprocess, and
every batch run is written to `data/logs/` as well as the terminal.

**WISE is invoked as the console script in its environment, without activating
it.** `<conda>/envs/wise/Scripts/wise.exe` resolves torch and CUDA from its own
site-packages; `conda run` is not needed and starts 2.4x slower (6.9s against
2.9s). `config.executable()` finds it by `APOLLON_WISE_EXE`, then `PATH`, then the
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
computed in Apollon and submitted to `/search_with_feature`, so no WISE patch is
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

**Package.** `src/sitrep/` installs into the `apollon` environment
(`[build-system]` and `[project.scripts]` in `pyproject.toml`), and its
modules import each other relatively. The entry point is `apollon-sitrep`, or
`python -m sitrep.<module>` for the per-module diagnostics; **`python
src/sitrep/main.py` no longer works** and the READMEs and docstrings name the
new commands. `pydantic` is now a declared dependency, pytest sits in a `dev`
group, and `requires-python` is `>=3.12` — at that bound the lock resolves to
identical versions of all 42 packages.

**One entry point.** `main.py` is the only runner; `report.py`'s duplicate CLI
is replaced by `apollon-sitrep --json`. Source, timing and resolution arguments
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
`ORE["Apollon — real-time mode"]` path of the CAPTURE graph in
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
source"). Covers the `CAM`/`MIC` sensor inputs feeding the `ORE["Apollon —
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
`faster-whisper`, so the `apollon` env's Python 3.14 will not block step 4
(transcription).

---

## 2026-09-09 — Switched to `uv` for Apollon's own Python environment and package management (MININT-ITT28VU)

**Machine:** `MININT-ITT28VU` (user `ctech`), same machine as the 2026-09-08 entry.

Apollon's own Python code (`src/`) is now managed with
[uv](https://docs.astral.sh/uv/), tracked via `pyproject.toml`/`uv.lock` in
the repo root. The environment lives at `apollon/`, gitignored via uv's own
`.gitignore` written inside that directory. `external/wise` is unaffected and
keeps its own conda env (`wise`) per its `docs/Install.md`.

Setup on this machine:
- `uv venv apollon` — the virtual environment
- `uv init --bare --no-workspace --name apollon` — creates `pyproject.toml`
  only; `--no-workspace` keeps `external/wise`'s own (conda-managed)
  `pyproject.toml` out of this project
- `UV_PROJECT_ENVIRONMENT=apollon`, set as a persistent user env var (`setx`),
  so `uv add`/`uv sync` target `apollon/` instead of the default `./.venv`

Verified: `uv add ollama` installs into `apollon/Lib/site-packages` and records
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
and `external/` wholesale by Apollon — so it must be rebuilt after any
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
project name is a required path segment. Added a one-line usage note to Apollon's
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
edits inside it are invisible to Apollon's git and would be lost if
`external/wise` is ever deleted and re-cloned. Both patches are saved as
`.patch` files under `knowledge/source_of_truth/wise-patches/` (tracked by
this repo) and documented in `knowledge/source_of_truth/versions.md` for
reapplication:

```bash
git -C external/wise apply ../../knowledge/source_of_truth/wise-patches/0001-pin-python-upper-bound.patch
git -C external/wise apply ../../knowledge/source_of_truth/wise-patches/0002-skip-libmagic-on-windows.patch
```
