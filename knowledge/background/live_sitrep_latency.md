# Live SITREP latency: the problem and proposed fixes

Written 2026-09-28, after the continuous recording of the same day
(`changelog.md`). All measurements are from the production machine
(`VSH-ARLT-5090`, RTX 5090) with `gemma4:26b`, on the test corpus.

**Status 2026-09-29:** fixes 1–4 are built, with reports made only on request
instead of every window or spike, and fix 5 is measured. See
`live_distillation.md`.

## The problem

Nothing the live SITREP measures reaches the operator until a window has
closed *and* the model has written its report. With 15 s windows:

- A line said at the **end** of a window shows about **6 s** later: the
  report's own processing time.
- A line said at the **start** of a window shows about **21 s** later: the
  rest of the window, plus processing.
- On average that is **13–14 s**, for every value on the page. That includes
  values that need no language model at all, such as loudness or a
  recognised push.

For an operator who is meant to intervene, that is too slow. A shout or a
threat should appear within one or two seconds.

## Where the time goes

Measured per report (`changelog.md`, 2026-09-28, "Recording never pauses"):

| Step | Time | Notes |
|---|---|---|
| Waiting for the window to close | 0–15 s | the largest share, and the one that grows with the window |
| Whisper, 15 s of audio | ~0.1 s | ~2.8 s on the first call, loading |
| Line rating (`speech.py`) | ~1 s | runs in parallel with the report |
| Gemma report (`report.analyse`) | 2.3–5 s | mostly *generating* text: description, people, three forecasts |
| Report, end to end | mean 5.7 s, max 7.4 s | replay of "Four Dogs", 0–405 s |

**Shorter windows don't help.** A report costs 3–7 s however short its window.
With `--window 5`, reports are either merged (as now) or, as before the
continuous recording, half the scene was never heard (58 % captured, 20 of
67 lines). The fixed cost belongs to *the report*, not to the footage.

## How real surveillance systems do it

They separate **raising an alarm** from **describing what happened**:

1. **Small, specialised detectors run continuously**, on every frame and every
   short stretch of audio: people, weapons, falls, shots, aggressive voices.
   Each gives a result within a second, and an event goes out as soon as one
   fires. None waits for a window.
2. **Speech is transcribed as it arrives.** Voice-activity detection finds the
   end of each utterance and it is transcribed then, or even word by word.
   Text follows speech by one to two seconds.
3. **Heavy analysis is triggered by events and runs afterwards**: a
   vision-language model describing the clip around an event, or a human
   operator checking it. It may take seconds, but the alarm is already out.
4. **The operator gets events and changing values, not reports.** The
   narrative summary trails behind.

## What this means for Apollon

Most of a fast lane already exists. It is held back only by being routed
through the per-window report:

| Signal | Now | In a fast lane |
|---|---|---|
| Actions (`actions.py`) | classified every second, shown per report | shown within 1–4 s (the classifier looks at the last 4 s) |
| Loudness (`loudness.py`) | measured per window | measured continuously, shown at once |
| Speech (`transcribe.py`, `speakers.py`, `speech.py`) | transcribed per window | per utterance: Whisper ~0.1–0.3 s + rating ~1 s once the utterance ends |
| Risiko and Menschlichkeit per person | per report | updated whenever one of the above changes |
| Gemma report: description, scene, forecast | every window, on the critical path | a summary every window, plus one at once when something spikes |

## Proposed fixes, in order

### 1. Speech per utterance (largest effect)

- Run voice-activity detection on the live audio as it arrives. Silero VAD,
  already used inside faster-whisper, can run on 30 ms chunks.
- When an utterance ends (silence of ~0.5 s), or has run for 10 s, transcribe
  just that utterance.
- Attribute it with the mouth measurements of its span, as now.
- Rate it (`speech.rate`). Batch utterances that end within the same second
  into one request.
- Push the line and the updated person values to the page and over OSC
  straight away.
- Expected: **a line is on screen 1.5–2.5 s after it ends.**
- The window report then reads the utterances already transcribed instead
  of transcribing again.

### 2. A live values stream

- Keep each person's Risiko and Menschlichkeit current, from actions every
  second and speech per utterance, with loudness as now.
- **Let values decay** with a half-life of perhaps 20–30 s. A value that only
  ever rises until the next report would otherwise stay up after the moment
  has passed. The spec already describes this ("rule sets the floor,
  decaying").
- Send changes as they happen: server-sent events to the operator page (it
  already receives one per second for the live action panel), and a new OSC
  address such as `/apollon/live/person` for TouchDesigner.

### 3. Reports triggered by a spike

- Keep the regular report every window as the narrative summary.
- When the fast lane crosses a threshold (a line rated Risiko ≥ 3, a line
  marked `geschrien`, an action with Risiko ≥ 3), start a report right away
  on the last 10–15 s instead of waiting for the window to end.
- One report at a time. A trigger during a running report brings the next
  one forward rather than queueing a second.
- Expected: **scene Eskalation and Gefahr 5–7 s after the trigger** instead of
  up to 21 s.

### 4. A cheaper Gemma report

- **Write less.** Shorter person descriptions, one short sentence per
  forecast, and possibly two forecasts instead of three. Generated tokens are
  most of the 2.3–5 s.
- **Stream the output** to the page as it is generated, so the description
  appears before the forecasts are finished.
- **Keep the prompt's fixed part first.** Instructions, then roster, then
  context, then transcript. Ollama reuses its cache for an identical prefix,
  which shortens prompt processing.
- Fewer frames per report where they add little.
- Measure p50 and p95 with `sitrep.benchmark` (step 6 in
  `02_processing.md`) before and after each change.

### 5. GPU contention

Pose at 25 fps, face tracking, the mouth landmarks, Whisper and Gemma all
share one GPU. Their combined load has never been measured in a live run.
Measure it first. If needed, run pose at 12.5 fps (the action classifier then
reads 50 frames per 4 s, resampled to its 100) and leave Gemma the headroom.

## Risks and open questions

- **Overlapping speech and shouting** make the end of an utterance harder to
  detect. A long shouting match may come through as 10 s pieces rather than
  lines.
- **More model requests.** Rating per utterance means more, smaller requests
  to Ollama. Batching per second keeps the number bounded; it needs measuring
  alongside the report.
- **Decay needs a dramaturgical decision.** How long should a threat keep
  someone's Risiko up?
- **Data retention does not change.** Utterances live in memory until
  reported, as windows do now, and are deleted when a run stops.

## How to measure it

Define latency per kind of output and measure it on the same replay of
"Four Dogs" used on 2026-09-28:

| Output | Measured from | Target |
|---|---|---|
| Line on screen | end of the utterance | p95 ≤ 2.5 s |
| Person value updated | the moment of the action or line | p95 ≤ 3 s |
| Report after a spike | the triggering event | p95 ≤ 8 s |
| Regular report | end of its window | p95 ≤ 7 s (currently max 7.4 s) |
