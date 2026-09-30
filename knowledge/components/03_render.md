# Rendering 
Overview: pipeline.md

## Live SITREP 
How will the live SITREP be displayed? Let's create a new tab on localhost for each prototype UI. 

### Prototype 1
Video feed displayed on the top third of the page, with bounding boxes and names of the characters attached top left on the bounding box. 

> Changed 30.09.26 (Moe): the display is projected in landscape. The video is on the left, the two characters in view on the right, one above the other, with the alarm beneath them.

Below video feed: Szenen Werte and color coded categorisation word (currently it is often "Ruhig").

Below that, to the left and to the right, the two names of the two characters currently in view (names here match the names over the bounding boxes) and there respective SITREP values, updating continously. 

If an Einschreiten is recommended, place this warning large, in red and as the only element of the page in the center. Once the value changes, go back to the regular view. 

We do not see any of the other values, even if they are all still being recorded. 

Press "R" once and the Reportbericht is displayed center of the page, no other elements visible. Press "R" again and we go back to the regular view. 

---

> **⚠ Written by Claude — draft, not yet reviewed by Moe (2026-09-12).**
> Everything between this box and the closing box below is a proposal drafted by
> Claude. It is not authoritative until Moe has reviewed and edited it.

## Playback chain: Orest → TouchDesigner → QLab → projectors

```mermaid
graph LR;
    UI["Orest UI<br/>Smart Search"]:::orest -->|OSC: hit metadata| TD["TouchDesigner<br/>effects"]:::proc;
    CUT[("Clip folder<br/>cut hits")]:::store -->|files| TD;
    UI -->|cuts clips| CUT;
    TD <-->|TDAbleton / OSC| ABL["Ableton<br/>sound design"]:::proc;
    TD -->|NDI or capture card| QL["QLab (macOS)<br/>mapping · blending · cues"]:::proc;
    QL -->|OSC: cues| TD;
    QL -->|all outputs| PROJ["Projectors"]:::out;

    classDef orest fill:#f7e8ee,stroke:#a83f6e,stroke-width:2px,color:#3a1226;
    classDef proc fill:#e8eef7,stroke:#3f6ea8,color:#12263a;
    classDef store fill:#eef7ee,stroke:#4a8a4a,color:#12331a;
    classDef out fill:#fff,stroke:#666,color:#222;
```

### Open decisions

- **TD ↔ Ableton.** TDAbleton (Derivative's official bridge, via Max for Live),
  plain OSC/MIDI, or Ableton Link for tempo. No Orest involvement.

## Interface: Orest → TouchDesigner

OSC carries messages, not pixels. The interface therefore has two channels.

### Pixels: cut clips on disk

A WISE hit is a time range inside a source recording that may be several GB
(e.g. Othello 2022, 4.3 GB). Seeking inside long-GOP H.264 or 4K files is slow
and unreliable in playback, so Orest cuts each hit into a short clip in a
playback-friendly codec, writes it to a shared clip folder, and TD plays the
file. This is the `HITS → CUT` node of the RENDER graph in
`source_of_truth/pipeline.md`.

For live frames rather than stored footage, the equivalent channel is Spout
(same machine) or NDI (across machines).

Clip cutting is decode-bound and costs about four times as much for 4K sources
(`changelog.md`, 2026-09-11). Clips are cut in rank order and each hit is
announced once its clip exists, so rank 1 is playable first.

### Control: OSC

```
/orest/results/begin  <query_id> <count>
/orest/results/hit    <query_id> <rank> <clip_path> <ts> <te> <score> <source_file> <preroll>
/orest/results/end    <query_id>
```

TD collects the hits of one `query_id` into a Table DAT. The fields follow
`Hit` in `src/smartsearch/client.py`. A return channel from TD (e.g.
`/orest/query ...`) allows a QLab cue to trigger a search.

## How many results reach the stage

**Orest sends a fixed maximum; TD/QLab chooses how many to use, per cue.**

- The number of clips a scene uses is a playback parameter, like opacity or
  timing. Stored in a QLab cue (as OSC to TD), it is recalled identically every
  performance; a dial in the search UI must be reset by hand each scene.
- The result list is ranked, so the top 5 are the first 5 of the top 20.
  Changing the count mid-scene needs no new search.
- The UI holds only the maximum, which also bounds clip-cutting work.

Division of responsibility:

| Orest (Smart Search) | TouchDesigner / QLab |
|---|---|
| Which moments are good results: ranking, per-file caps, excluding the recent past (`progress_tracker.md`, Phase 3) | How many are used and how, per cue |
| Maximum number of results sent | Count, order, effects, timing |

### Score threshold as an alternative to a fixed count

On the full pose index (`changelog.md`, 2026-09-11), a distinctive movement
returns one clear winner with a margin of 0.25–0.33 over the next result, while
an ordinary stage posture returns six results within 0.011 of each other. A
fixed count yields near-identical clips in the second case; a rule such as
"keep results within X of the best score" adapts to both. Scores are not
comparable across indices (SigLIP text/image search ~88, pose ~0.97), so a
threshold is set per index.

> **⚠ End of Claude-written section.**
