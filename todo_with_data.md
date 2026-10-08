# TODO once rehearsal data exists

Work that needs footage: testing the live SITREP's measured values on the
sample corpus (`../test_data_orest`) now, and nice-to-have work that becomes
possible only when enough rehearsal footage has been recorded. Nothing here
blocks the current system.

## Tune the live SITREP on the production's footage

Since 2026-09-29 the live SITREP shows lines and live values within about a
second, keeps a Chronik in the background and makes a report on R
(`knowledge/background/live_distillation.md`). The constants were set on the
test corpus. `python -m sitrep.replay FILE --gpu` measures a recording.

**To do**
- **Decay.** How long should a threat keep someone's Risiko up?
  `lage.HALBWERTSZEIT` is 20 s.
- **Alarm and Empfehlung thresholds.** `lage.ALARM` is 3 and `report.SCHWELLE`
  is 6. On "Four Dogs", 4 of 7 Empfehlungen said "Einschreiten", all for
  verbal quarrels.
- **Utterance cuts.** `utterances.LONG_UTTERANCE` (3 s) and `PHRASE_PAUSE`
  (0.2 s) on the production's microphones, and whether lines come out whole.
- **Chronik length.** `--window` sets the Abschnitt; 30 s was measured.
- **Combined GPU load with the production's camera.** 25 GB of 32 on the
  replay of 1080p footage at 60 fps.

## Test the action ratings on sample data

Since 2026-09-28 the live SITREP measures `risiko` and `menschlichkeit` from
the action recogniser (`src/sitrep/actions.py`, `changelog.md`). A first replay
of 90 s of "Boom" named every body from its face and rated everyone. The values
are not calibrated yet.

**To do**
- **Feed sample footage into the live SITREP, sound included.** Done
  2026-09-28: OBS Virtual Camera for the picture, OBS's NDI output (DistroAV,
  "Main Output" on) for the sound via `--audio-ndi "VSH-ARLT-5090 (OBS PGM)"`,
  and `--language en`. NDI Webcam isn't needed.
- **Find the noise floor.** In an ordinary conversation everyone came out at
  risiko 1. Many risk classes each carry a little probability (e.g. "shoot at
  other person with a gun 0.10"), and the peak over ~100 readings per report
  rounds their sum up. Options:
  - Ignore classes below a minimum probability.
  - Subtract a neutral baseline measured on the corpus.
  - Require evidence in two consecutive readings.
- **Check strong readings against the footage.** "giving something to other
  person 0.93" gave menschlichkeit 4, unverified. Watch the moments behind
  every rating ≥ 3 and count hits and misses per class.
- **Record staged actions.** The corpus has no violence. Pushes, slaps,
  embraces and handovers, rehearsed on the production's stage, are needed to
  measure precision for the classes that matter.
- **Measure the combined GPU load.** Pose at 25 fps, face tracking, Whisper
  and `gemma4:26b` together. The only live run so far had an empty camera
  (3.3 s latency, 10 s window).
- **Review the mapping table** (`src/action/sitrep_map.csv`) against what the
  recogniser actually produces, e.g. salute as risiko +1.

- **Measure speaker attribution.** On a clip from the production's own
  camera, write down who spoke 30–50 Whisper segments and compare with
  `aeusserungen`. On the edited "Boom" footage 17 of 34 lines were attributed,
  but correctness is unknown, and the actors' faces were rarely recognised even
  when enrolled from the clip (dark, in profile, small in wide shots).
- **Send the attributed lines to TouchDesigner.** `aeusserungen` reach the
  console and the operator page; OSC still carries only `gesagt`.

- **Speech rating on real rehearsal lines.** The evaluation set
  (`src/sitrep/speech_eval.csv`, 31 of 34 within ±1) is invented. Add lines
  from the production's text and from rehearsals, with the scores they should
  get, and rerun `python -m sitrep.speech`.
- **Idioms read as literal.** "Ich lach mich tot" scores risiko +5. If such
  lines matter in the production, add them to `speech_examples.csv` with 0.

- **Check the loudness gain on the production's microphones.** On "Boom"
  the normal level was −30 dBFS ±5, and the loudest lines of the argument
  were amplified ×1.5 to ×1.7. Rehearsal sound with shouting, and with
  noise such as falling chairs, will show whether QUIET, GAIN and MAX_GAIN
  (`loudness.py`) fit.

**Open questions**
- **Who is the aggressor?** A pair reading counts for both people, so the
  one who is hit also gets risiko 5. A rule could tell them apart, e.g. whose
  wrist moves toward whose body.
- **Bodies that never show their face are not rated.** Actors with their back
  to the camera stay unnamed. Rate them under a body id, or keep a name on a
  body for longer?
- **A name can change mid-report.** Ratings are kept under the label a body
  had when it was read. If a guess becomes a recognition (`Vielleicht: Jakob`
  → `Anna`), the report's person finds no rating and shows `–`.
- **Spectators are rated** if they appear taller than a performer. Only the
  two tallest bodies are classified (`recognizer.MAX_PEOPLE`), matching the
  production's two performers. A performer further from the camera than a
  spectator, e.g. upstage, would be left out; a stage region would exclude the
  audience reliably.
- **Should a measured risiko raise the scene's gefahr?** The intervention
  rule reads the model's scene ratings only. A risiko 5 could set a minimum
  on the scene's gefahr, decaying over the following windows
  (`02_processing.md`, "Rule sets the floor").
- **Should the model be told what was recognised?** It would describe a slap
  it didn't see in its stills, but also the recogniser's false positives
  ("touch other person's pocket" during conversation).
- **Should ratings carry over between reports?** Each report is rated
  independently for now, so a blow counts only in the report it falls in.
- **Is Vorhersehbarkeit calibrated well on the real corpus?** It replaced
  Auffälligkeit on 2026-10-07 and is measured against the whole rehearsal
  corpus, not each person's own history. Check on footage that rehearsed
  movement sits near 0 and that the Probebühne camera's angle does not push
  everything negative.
- **What if lips can't be read?** A line stays `(unklar)` whenever only one
  mouth is visible or neither moves clearly more. Voice enrolment of the cast
  (a voice embedding per person, matched per segment) would attribute those
  too, and would check the lips where both are seen.
- **Is the first speech a fair calibration?** Each run learns its normal
  level from its first 120 s of speech (provisional after 30 s). "Four
  Dogs" opens almost whispered, which the longer span evens out. A warm-up
  at normal volume, or a level set by hand, would make it independent of
  how a scene begins.

## Train Apollon's own action recogniser

The pretrained NTU120 model (`changelog.md`, 2026-09-28) was trained in a lab,
on lab actions. A model trained on the production's own footage would know
its actors, its stage, its lighting and its choreographed fights, and could
use the production's own activity names instead of NTU's.

1. **Collect.** Record rehearsals with the production camera setup. Staged
   fights, embraces and falls are rehearsed many times, so a few weeks of
   rehearsal should hold dozens of repetitions of each.
2. **Define the labels.** Fix a small activity list with the dramaturgy
   (Schlag, Stoß, Umarmung, Sturz, Rennen, …), plus a "nothing special" class
   for everything else. That class needs the most examples.
3. **Find examples.** Body-search one good instance in the pose index
   (`apollon-search body`) to surface its repetitions, then confirm each hit by
   hand. Aim for about 50 clips per activity and a few hundred neutral clips.
4. **Extract skeletons.** Run RTMO over each 2–5 s clip and store the
   keypoints in the same two-person, 100-frame format the NTU model takes.
5. **Fine-tune, don't start from scratch.** Keep the NTU120 ST-GCN, replace
   its 120-class head with the production's activity list, and train on the
   labelled clips. The pretrained layers already know human movement, so a
   few hundred clips can be enough.
6. **Hold out whole rehearsals for testing,** not random clips. Clips from
   the same rehearsal are near-duplicates, and testing on them overstates
   accuracy. Report precision per activity, since a false "Schlag" triggers
   an intervention.
7. **Swap it in.** Export to ONNX the same way as the NTU model. Apollon only
   sees a different class list and a different weights file.

**Data protection:** the training set is footage of identifiable people. It
needs the same consent basis as the recordings themselves
(`knowledge/components/01_capture.md`).
