# TODO once rehearsal data exists

Nice-to-have work that becomes possible only when enough rehearsal footage
has been recorded. Nothing here blocks the current system.

## Train Orest's own action recogniser

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
   (`orest-search body`) to surface its repetitions, then confirm each hit by
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
7. **Swap it in.** Export to ONNX the same way as the NTU model. Orest only
   sees a different class list and a different weights file.

**Data protection:** the training set is footage of identifiable people. It
needs the same consent basis as the recordings themselves
(`knowledge/components/01_capture.md`).
