# BLOOM × WISE: search architecture and live pose querying

Working notes. Two parts: (1) how to index the rehearsal archive, (2) how to make the performer's body a live query against it.

---

# Part 1 — Indexing the archive

## The distinction that shapes everything

Two different kinds of thing get called "features," and WISE already treats them differently:

**Embeddings** — OpenCLIP scene vectors, OWLv2 regions, InsightFace identities, CLAP audio. Dense vectors, searched by approximate nearest neighbour, open-vocabulary, fuzzy. Stored in Faiss indices (768-dim, IndexIVFFlat; IVFPQ where an extractor generates many candidate regions).

**Structured annotations** — BLOOM's six scores, pose keypoints, speaker labels, `judged_at` timestamps. Numbers and categories. Never ANN search; you want `WHERE gefahr >= 7 AND person_id = 3`. WISE already keeps a SQLite table mapping each vector to filename, timestamp and region coordinates, with FTS over media-level metadata.

**Consequence:** "moments the system thought Alessa was angry" is almost entirely the second kind. It's a join between the face index and BLOOM's own recorded judgments — not a new embedding space. A custom "angry" extractor would build a *second* opinion when what you want is to retrieve the *first* one verbatim.

## Two-layer architecture

```
                    ┌─────────────────────────────┐
                    │  Capture                    │
                    │  cameras, mics, ONE clock   │
                    └──────────┬───────┬──────────┘
                               │       │
            ┌──────────────────┘       └──────────────────┐
            ▼                                             ▼
┌───────────────────────────┐              ┌───────────────────────────┐
│  BLOOM live               │              │  WISE indexing            │
│  Gemma scores, SITREP     │              │  nightly batch, offline   │
└─────────────┬─────────────┘              └─────────────┬─────────────┘
              ▼                                          ▼
┌───────────────────────────┐              ┌───────────────────────────┐
│  Judgment log             │              │  Feature indices          │
│  six scores, judged_at    │              │  Faiss vectors + SQLite   │
└─────────────┬─────────────┘              └─────────────┬─────────────┘
              └──────────────────┐   ┌──────────────────┘
                                 ▼   ▼
                    ┌─────────────────────────────┐
                    │  Query surface              │
                    │  joined on camera + time    │
                    └─────────────────────────────┘
```

- **Layer 1 (existing):** ring buffer → Gemma → scores + SITREP, written to an event log with `observed_at`, `judged_at`, `camera_id`, `person_ref`, six scores, raw text.
- **Layer 2 (new):** nightly WISE batch over the day's recordings.
- Everything joins on `(camera_id, timestamp)`.

**The join key is the whole design.** One monotonic clock across all cameras and mics — NTP at minimum, plus a physical sync marker at the top of each session (clap, beep, slate). Cheap insurance, and a nice object.

## Custom extractors worth writing, ranked

**1. Pose → vector index + discrete labels.** The one genuinely worth an extractor.
- RTMPose or MediaPipe → root-center and scale-normalise keypoints → flatten → Faiss IVFFlat.
- Enables query *by posture*: "every moment anyone stood like this," via query image or drawn skeleton.
- Pose vectors are not in CLIP space, so no text query. Bridge cheaply with rule-based discrete labels from joint angles — `sitting`, `standing`, `arms_raised`, `facing_away` — written to the metadata table. Text-searchable, legible, and far safer legally than an affect classifier.

**2. BLOOM's own prose, embedded.** Run each SITREP through a sentence encoder and index it. Search the archive by *the character of the system's language*: "the system was uncertain," "the system was describing an empty room." Roughly four hours of work. The recursive move.

**3. Person re-ID (OSNet / TorchReID) as a second identity space** that deliberately disagrees with InsightFace. The ID switches — person 3 → person 7 → person 3 — are entity resolution failing in public. Gotham's core mechanism breaking, on your own ensemble.

**4. Scalars into metadata, not vectors:** motion energy per window, speech rate, interruption counts, silence duration. These are `WHERE` clauses.

**Don't rebuild:** CLAP already handles laughter, footsteps and clapping out of the box.

## The identity join

WISE's face index returns regions matched by facial identity; BLOOM's scores are per-person per-window. Both need a stable person ID.

Make InsightFace embeddings the canonical resolver: run once over the archive, cluster, assign IDs, then resolve BLOOM's live person labels against that index **post-hoc** rather than keeping them in sync live.

This is **entity resolution** — the same operation Gotham performs to merge disparate records into one person object, and the thing the BVerfG criticised Hesse for doing without distinguishing suspects from incidental contacts. **Log every merge and every split. The error log is a script.**

## On "angry"

The framing "moments the system *thought* they were angry" is exactly right — it's retrieval of a recorded judgment, not fresh classification. But it only works if BLOOM produced that judgment, which puts you back inside AI Act Art. 5(1)(f).

**The design that keeps everything and loses nothing: don't infer affect at all — infer proxies, and let the system's prose do the naming.**

- Measure: elbow angle, movement velocity, vocal amplitude, speech rate, interruption frequency.
- The SITREP generator, given those numbers, writes "subject displays elevated agitation."
- You index the prose, so `angry` still retrieves it.

Not a workaround. It is more accurate to how these systems actually behave — measure proxies, speak in affective language — and it stages the laundering step that the euphemism critique (Sharif, estimative probability) is entirely about. The inference is legally defensible; the confabulation on top of it is the subject matter.

## Practical numbers

- ~10 min GPU time per hour of video; sub-second retrieval on 6,000+ hour collections.
- 6 cameras × 6 h × 5 days × 8 weeks ≈ **1,400 hours** ≈ **230 GPU-hours** at full rate.
- Run **incrementally each night**, not in one pass. The archive visibly growing overnight is also the right image.
- Two knobs if it's too much: drop visual sampling below the default 2 fps (0.5 fps is plenty for a static room); reserve OWLv2 object regions for selected cameras only (region extractors generate enormous candidate counts — hence IVFPQ there).
- Storage: ~3 TB video at 1080p, plus tens of GB of vectors. Single machine with a large disk.

## Open question to verify

Could not read `docs/FeatureExtractor.md` (GitLab renders client-side). **Check whether the Extractor interface expects one fixed-dimension vector per frame, or supports variable region sets.** That determines whether pose goes in as a scene-level extractor (one vector per frame, assumes one person) or region-level (one vector per detected person — what you want).

---

# Part 2 — The body as live query

The actor holds a pose → it becomes the query → matching clips from the archive return and display. This requires faking nothing: the score you want already exists as a real number.

## Distance to nearest neighbour *is* the unpredictability score

Faiss returns top-k matches **and their distances**. If the current pose is far from everything indexed, that distance is large. That quantity is a novelty score — how outlier detection actually works — and the honest version of "the system doesn't recognise this."

Three reasons this matters:

1. **Not emotion inference.** It says nothing about interior state. It's a claim about the *archive*: how much of this have we seen before. Clean under Art. 5(1)(f), and a more interesting claim than "angry."
2. **It solves the never-abstains problem in the right direction.** Top-k always returns k results, however wrong — the system will always show "the same pose" even for a posture it has never seen. But the *distance* knows. So: retrieval that is confidently wrong, with a confidence metric that is quietly correct. You then choose whether the operator display shows the distance or hides it. **Hiding it is the more accurate portrait of commercial systems.**
3. **It's calibratable.** Raw L2 distances mean nothing to an audience. Offline: sample held-out poses from the archive, compute kNN distances, build the distribution, map live distance to a percentile. Now "Vorhersagbarkeit 3/10" is a real percentile rank.

## Query with a window, not a frame

A single frame's pose is noisy and semantically thin. Concatenate 8–16 normalised frames over ~0.5–1 s into one vector → you're querying a **movement phrase**, not a posture. Retrieval quality rises sharply. Conceptually better too: the body's sentence as query, not its letter.

**Latency:** RTMPose is single-digit ms on GPU; Faiss ANN over ~10M vectors is <10 ms. The bottleneck is decoding and displaying returned clips, not search. Budget 200–300 ms end to end; pre-warm a decoder pool.

**Two clocks on stage:** instant retrieval of the past, judgment arriving 4–25× late. Use the contrast deliberately.

## The fork: does the index keep growing during the show?

This decision determines what the piece means.

| | Mechanic | Meaning |
|---|---|---|
| **Frozen archive** | Novelty can only rise | The performer, pushed to invent, becomes progressively illegible to the system. A narrative of escape. |
| **Live-updating index** | Every gesture is added within seconds | The attempt to be unrecognisable *trains the system*. Do something strange twice and it's normal. Escape is impossible by inventing — only by never repeating. And rehearsal is repetition. |

**The second is far stronger.** It is pattern-of-life doctrine exactly: the model doesn't need to know who you are, it needs your behaviour to have a baseline, and it builds that baseline from whatever you do. Chamayou becomes a live mechanic rather than a citation.

## The Elektra connection — and the constraint mechanism

This is the answer to "build at least one mechanism by which scores actually constrain what performers are permitted to do," and it's better than anything imposed from outside:

> **The performer must keep the unpredictability score low.** Which means they may only move in ways the archive already contains. Which means they are compelled to repeat their own past — the recorded weeks of their own rehearsal — and every gesture summons projected footage of themselves having already made it.

A body that cannot do a new thing, haunted by earlier versions of itself performing the same act, in a house where the only permitted action is the one already performed. That argues itself to a dramaturg.

**Inverse ending, also available:** at the close the performer does something genuinely unprecedented, the score spikes, and the system names them as a target — correctly identifying novelty and calling it threat.

## Degrading it honestly

Faiss trades accuracy for compression: IVFFlat (near-exact) at one end, aggressive product quantisation at the other. The paper notes IVFPQ reduces compute and storage with minor accuracy impact — **so run it backwards.** Progressively swap in coarser PQ codebooks across the evening. Retrieval returns increasingly wrong matches. The displayed confidence number never changes, because nothing in the system knows the index got worse.

Rising confidence, falling accuracy, implemented as a parameter you turn. No simulation, no cheating. The technical mechanism *is* the dramaturgy.

## Retrieval hygiene — three things that will bite you

1. **Exclude the recent past.** With a live-updating index the top match is always the performer four seconds ago. Set a temporal exclusion window of several minutes, or it's a mirror rather than an archive.
2. **Enforce temporal diversity.** Cap results at one per session or per hour, or all eight clips come from the same Tuesday afternoon.
3. **Expect the archive to be dominated by sitting.** Most of 1,400 hours is people in chairs, so naive kNN returns sitting for almost everything. Correct with inverse-frequency weighting — *or* let it happen, because a system that answers every gesture with footage of the ensemble sitting in a circle in week two is funnier and more accurate than a well-tuned one.

## The risk

This can very easily become a toy. "My body searches a database, and look, it works" is a media-art installation demo, and audiences have seen many. The interactive delight is real and it is **not** the same thing as stakes.

What keeps it from being a toy: **the constraint** (the score doing something to the performer) and **the wrongness** of the retrieval.

> If the matches are impressive, you've built a tech demo. If the matches are plausible-but-wrong, and the performer is nonetheless obliged to obey them, you've built the piece.

---

## Immediate next steps

- [ ] Verify the Extractor interface signature (scene-level vs region-level)
- [ ] Settle the clock and sync-marker protocol before any recording starts
- [ ] Betriebsrat/Personalrat consent + DSFA (from the earlier briefing) — gate on this
- [ ] Prototype pose index on the Konzeptionswoche footage you already have
- [ ] Calibrate the novelty-distance distribution on held-out poses
- [ ] Decide the fork: frozen vs live-updating index
