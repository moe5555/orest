# Performance

Draft, 2026-10-22. Cues from `knowledge/HITLText_2210.pdf` (Moe's parts in
green). Page numbers as printed in the script. PowerShell, from
`C:\Users\video\Desktop\orest`.

`(?)` my reading of the script, to confirm. `TBD` not built yet.

## Before the show

1. Ollama running (`gemma4:26b`).
2. OBS: **Start Virtual Camera**.
3. Terminals:

   ```powershell
   # T1  Live SITREP
   uv run apollon-ui --video "OBS Virtual Camera" --width 1920 --height 1080

   # T2  Smart Search server
   uv run apollon-search serve --project hitl_database

   # T3  Body search (wait for "ready")
   uv run apollon-search body-live --project hitl_database --video "OBS Virtual Camera" --segments -n 30 --send-td

   # T4  Athene
   .\apollon\Scripts\Activate.ps1
   python -m athene.live --obs
   ```

4. http://127.0.0.1:9680/ → Kamera `OBS Virtual Camera`, Ton, Besetzung
   `data/cast` (Alex, Lena) → **Start live SITREP** → new tab: **Prototyp 4**, F11.
   A second tab on http://127.0.0.1:9680/sitrep stays on **Übersicht**, off the
   wall, for naming people by hand (Im Bild).
5. TouchDesigner: open `TouchDesigner/Apollon_TD_New.toe`.
6. OBS: Athene wall and strip Browser Sources on the addresses T4 prints,
   hidden until Szene 6 (?).

**Szene → X**: choose X in the Szene dropdown on the operator page, then click
back into the SITREP tab. Keys only reach the window in focus.

## Einlass (p. 1)

| Cue | Do |
|---|---|
| Audience comes in | SITREP running, Szene → **Szene 1 - Waechter** (30 people tracked) |
| "wenn alle sitzen, Zoom In" | Camera zoom in. SITREP **P** (30 → 3 people) (?) |

## Szenario 1: Wächter (p. 1–4)

| Cue | Do |
|---|---|
| "Iuh, iuh." → "Das ist mein Zeichen" (p. 3) | SITREP **T** (fire strobe) |
| "denn Troja ist gefallen –" (p. 3) | SITREP **T** (close) (?) |

## Szenario 1.2: Übergang (p. 4)

| Cue | Do |
|---|---|
| Start | Szene → **Szene 1.2**. TBD: no thermal video in `src/sitrep/scenes.toml`, shows the live camera |

## Szenario 2A: Grab (p. 4–9)

| Cue | Do |
|---|---|
| Start | SITREP off the wall (?). Don't press Stoppen: it forgets the learned names |

## Szenario 2B: Racheschwur (p. 9–11)

| Cue | Do |
|---|---|
| Lena puts the blindfold on Orest (p. 9) | SITREP back on the wall. Szene → **Szene 2.3 - Aggression** |
| Each "Ich bin derjenige der es entscheidet" (p. 10–11) | SITREP **W** (Orestes's Aggression +1, **S** −1) (?) |
| "Ich sagte lauter du drecksau" (p. 11) | SITREP **M** ("Maximales Aggressionspotenzial erreicht.") (?) |
| "now get on your fucking knees" / SEX TRACK IN (p. 11) | SITREP **X** (close). SITREP off the wall |

## Szenario 3: Pylades / Klytaimnestra (p. 13–14)

| Cue | Do |
|---|---|
| Start (p. 13) | SITREP back on the wall. Szene → **Szene 3 - Pylades** (Lena is Elektra) |
| Lena becomes Klytaimnestra (?) | Übersicht tab → Im Bild: Lena's row → **Klytaimnestra**. Elektra is then no longer offered |
| "…mischen sich hier meinetwillen ein." (p. 14) | SITREP **C** (live → rehearsal clip). TBD: clip from the last rehearsal in December, `video` in `scenes.toml` |

## Human in the Loop: Loop des Mordes (p. 15)

| Cue | Do |
|---|---|
| Before the fight | TD **F1** (wall), **4** |
| "L. zieht O. ran" → "L. stirbt" | TD hold **Space** through the fight, release on "L. stirbt" (?) |

## Szenario 4: Werbeblock (p. 15–19)

—

## Szenario 5: Hundetierheim (p. 19–20)

| Cue | Do |
|---|---|
| Start, "Body Search ein" | TD wall open (**F1**), **4**. Hold **Space** while Alex moves, release (?) |
| "…die meinen Sinn befällt." (p. 20) | TD **9** (4 → 9 tiles) |
| Verfolgungsvideo "Im Überwachungssystem" (p. 20) | TBD: no SITREP scene plays it yet |

## Szene 6: Athene (p. 22–29)

| Cue | Do |
|---|---|
| Orestes back in the room (p. 22) | SITREP **Stoppen**. TD **Esc**. Ctrl+C in T3, T2 |
| "Orestes ruft Athene an" (p. 23) | OBS: Athene sources visible (?). Focus: wall source → Interact (?) |
| Athene (1) "Ich habe deine Rufe erhört." | **P** |
| Athene (2) "Du sagst Apollon befahl dir zu töten?" | **P** |
| Athene (3) "Alleine kann ich kein Urteil fällen." | **N** (death scene), **P** |
| Chor "Sucht, sucht…" (p. 24) | **C** |
| "…Die unseren Alltag verunmöglichen." (p. 24) | **C**, **C** |
| The vote (p. 25–27) | **C** as wanted (17 clusters in all) |
| Athene (4) (p. 27) | **N** (back to two axes), **P** (?) |
| Orestes: "Aber jemand muss doch Recht sprechen?" (p. 28) | **N** (growth, full network after 3 min) |
| Athene (5) "Die Tat ist unstrittig." (p. 29) | **P** |
| Athene (6) "Absofort wird diese neue Ordnung gelten." (p. 29) | **P**. Ends by itself: explosion, white, strobe from "Eins". No E |
| When the strobe should stop | **X** (cut to black) |
| During the growth | Hold **T** for strikes. **S** full strobe (?) |

## End (p. 30–31)

Athene stays black. After the show: Ctrl+C in T4, T1.

## Keys

- **SITREP tab:** R Lagebericht · E Empfehlung · X close screen ·
  Szene 1: T strobe, L Podest line, P 30 ↔ 3 people ·
  Szene 2.3: W / S Aggression Orestes ±1, M screen ·
  Szene 3: C live ↔ clip
- **TD wall** (after F1): Space held = capture, release = search ·
  digit = tiles (1, 4, 9) · Esc close
- **Athene:** N / B scene · Space restart scene · P voice · C cluster ·
  T held strikes · L strikes manual ↔ auto · S strobe · E ending now ·
  X cut to black · H help line
