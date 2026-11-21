# Athene

Athene's visuals for the LED wall: an audioreactive, living coordinate system
(brief: `description.md`). The page in `page/` draws them in the browser; the
Python modules feed it the voice and the cluster clips.

- `live.py`: the live page for rehearsals, the play's scenes performed from
  the keyboard (below).
- `render.py`: renders a design to PNG frames or video at 3840 × 2160 and
  50 fps, or previews it in the browser.
- `analyse.py`: turns a voice clip into the values that move the page.
- `cut_clips.py`: cuts four-second clips from other footage for the clusters,
  spread evenly or where a picks file says (`deathscene_picks.json`,
  `endvideo_picks.json`).
- `page/`: the page core (`athene.js`) and the designs (`page/designs/`).
- `archive/`: the Seestone-branded prototypes (see `archive/README.md`).
- `out/`: analyses, frame sheets, renders and the live page's files (ignored
  by git).

## Starting the live page

From the repo root, with the `apollon` environment active and `ffmpeg` on the
PATH:

    .\apollon\Scripts\Activate.ps1
    python -m athene.live

This serves the rehearsal design (`page/designs/rehearsal.js`) and opens
its 16:9 view in the default browser. Put the browser in fullscreen (F11) on
the wall. Ctrl+C in the terminal stops the server.

### Two outputs: the 9:1 strip and the 16:9 wall

Athene lives in a 9:1 world as high as the 4K frame (19440 × 2160 px). The
9:1 strip shows all of it (3840 × 427), the 16:9 wall its middle section
(3840 × 2160, drawn at full resolution, not cut from the strip's pixels).
Each output is its own page:

| Page | Address | Size |
|------|---------|------|
| wall, conducts | `http://127.0.0.1:8766/?design=rehearsal&mode=live&view=wall` | 3840 × 2160 |
| strip, follows | `http://127.0.0.1:8766/?design=rehearsal&mode=live&view=strip&follow` | 3840 × 427 |

The wall's page conducts: it takes the keys, plays the voices and runs the
performance, and every frame sends its state to the strip's page in the same
browser, which draws its view of it. So both show the same moment, the
strip about one frame behind. Each page plays only the cluster clips in its
view; the strip draws them from frame sheets (128 × 72 px, 12.5 frames a second).

For the show, both go out through OBS as two NDI streams, conducted by a
third page that goes out nowhere:

    python -m athene.live --obs

opens no browser and prints three addresses:

| Source | Address | Size | NDI |
|--------|---------|------|-----|
| Athene Regie, conducts | `...&view=wall` | 1280 × 720 | none |
| Athene Wand, follows | `...&view=wall&follow` | 3840 × 2160 | Dedicated NDI Output |
| Athene Band, follows | `...&view=strip&follow` | 3840 × 427 | Dedicated NDI Output |

Regie is the operator's page: it shows the help line, takes the keys and
plays the voices. The wall and the strip follow it, hide the help line and
take no keys, so nothing of the operator's reaches either output. Regie
draws the wall's view at the size of its source (a ninth of the 4K wall's
pixels at 1280 × 720); `--res` applies to the wall and the strip only. In OBS:

1. Three Browser Sources at the sizes above, all at OBS's frame rate, each
   with "Shutdown source when not visible" off. Width and height set the
   resolution each page draws at, so the outputs need exactly 3840 × 2160
   and 3840 × 427. With "Control audio via OBS" off, Regie plays the voices
   on the PC's audio output.
2. On the wall and the strip a DistroAV "Dedicated NDI Output" filter,
   named e.g. "Athene Wand" and "Athene Band". QLab takes the two NDI
   sources. Regie has no filter.
3. Keys go to Regie: right-click it, "Interact", and click into the window.
   The window shows Regie's page, help line included. OBS's Interact window
   sends keys without their code; the page takes the key's character instead.
4. Start `athene.live` before OBS, or refresh all three sources after it starts.
5. Keep the three sources in one scene that OBS shows (in the program, the
   preview or a projector), as a source OBS does not show may stop drawing.

Not yet checked in OBS: that its Browser Sources reach each other (all run
in OBS's one browser), whether a source must be shown to keep drawing, and
the resolution of a dedicated output.
In a browser, the strip can be opened in a second window from the printed
address; a hidden window may stop drawing.

The first start takes a while: each voice clip is analysed, Whisper finds
where it says "von null auf eins", and the cluster clips are cut to small
looping videos, all kept in `out/live/`. Later starts reuse them; a voice
clip is analysed again only when its file is newer.

Options:

    python -m athene.live --voices FOLDER       # other voice clips (default: example_audio/athene_voice_2110)
    python -m athene.live --clips A B           # other cluster clip folders, one group each
    python -m athene.live --res 0.5             # draw at a fixed half of the view's size (default: fitted to the screen)
    python -m athene.live --port 8800           # another port
    python -m athene.live --obs                 # no browser; the addresses of the two OBS Browser Sources
    python -m athene.live --rehearsal           # Athene as before the strip: one 16:9 page, the clusters across it

### The cluster pulse to Max

Each cluster C places sends `/athene/cluster 1` over
OSC, then `0` 100 ms later, as Apollon's pulses do (`src/sitrep/pulse.py`):
a C pressed while the pulse is still high gives a fresh 0 → 1 edge, and
the closing 0 is sent twice against UDP loss. A C that places no cluster
(outside the death scene, or with all clips shown) sends nothing. The
target is Apollon's Max, `192.168.10.3:7400` (`APOLLON_PULSE_HOST`,
`APOLLON_PULSE_PORT`). In Max:

    [udpreceive 7400] -> [route /athene/cluster] -> [sel 1]

The clusters take their clips from `data/clips/athene_deathscene` (the
death scene rehearsals) and `data/clips/athene_endvideos` (the play's end
videos), mixed. The voice clips play in name order, one per P.

Both are four-second clips picked by hand, listed with what they show:
- `deathscene_picks.json`: 106 clips from the six recordings in
  `Desktop/HITL_Database` named "DeathScene": the pistol pointed, grabs,
  struggles, strangling, falls and the body. Each is cropped to the 960 ×
  540 px around the actors.
- `endvideo_picks.json`: 160 clips from the 21 videos in
  `Desktop/04_Endvideos`, three to twelve per video.

Each press of C shows the next 16 clips, about six of the rehearsals and
ten of the end videos (the two in proportion to their numbers, so both run
out together), which gives 17 clusters, the last of ten clips. Within each
group the clips are ordered so that a cluster mixes as many source videos
as possible. A clip is shown at most once per run of the death scene: once
all are shown C does nothing, and the help line says how many clusters are
left. Space, or entering the scene again, starts over with all clips.

The clips of a cluster appear at 2.5 times their settled size (700 px wide
on the 4K wall), spread out around the cluster but kept on the strip. After
12 s they shrink over 6 s and draw together into the cluster.

To change a pick, edit it in the picks file, delete its clip in
`data/clips/athene_deathscene` or `data/clips/athene_endvideos`, and cut
again (`athene/live.py` makes the small live copy on its next start):

    python -m athene.cut_clips $HOME\Desktop\HITL_Database --picks athene\deathscene_picks.json --destination data\clips\athene_deathscene
    python -m athene.cut_clips $HOME\Desktop\04_Endvideos --picks athene\endvideo_picks.json

### Keys

| Key   | Action                                                      |
|-------|-------------------------------------------------------------|
| N / B | next / previous scene                                       |
| Space | restart the scene                                           |
| P     | play the scene's next voice clip, or stop the one playing   |
| C     | death scene: a cluster of rehearsal and end video clips     |
| E     | growth scene: the ending at once (the last voice clip begins it by itself) |
| S     | growth scene: the strobe                                    |
| L     | growth scene: strikes manual (from the start) or automatic  |
| T     | manual strikes: hold to fire strikes for as long as held    |
| X     | growth scene, in the ending: cut to black                   |
| H     | show or hide the help line                                  |

### Scenes

In every scene the lines are chrome: satin bands along them and glints
where two slowly turning lights catch them.

1. **Two axes**: the two axes move and probe, on their own and on every
   syllable.
2. **Death scene**: the axes twirl until the first cluster key, then stop
   turning and only move along their length: they breathe, and every few
   seconds one reaches out a little (5–12 %) and draws back. Each C places a cluster somewhere along the whole 9:1 strip and grows an axis to it;
   no clip appears twice.
3. **Two axes**: the death scene's axes and clusters draw back.
4. **Growth**: the network grows faster and faster for three minutes (all
   axes in after about 3:10) and on until E ends it. Ever more straight axes join through the centre until
   they fill the wall and run past its edges. The lines are chrome-white
   metal out of a glowing core that grows with them, all in white. They
   glow with a strobe that stays rare for long and crowds in towards the
   end; some flashes light the plane two or three axes span, often as a
   cascade of quick strikes from one axis to one after another. S switches
   to the full strobe. E ends it: the network explodes for 6 s until its
   light fills the wall white, and then the whole view strobes, all white
   and all black in turn, 12.5 times a second (two frames white, two black
   at 50 fps), until X cuts it to black. Both views strobe in step.

   The last voice clip ends the scene by itself, so E is not needed once P
   has started it. The ending begins 6 s before the "Eins" of its closing
   "Von Null auf Eins" (the clip says the sentence once before, which does
   not count), so the strobe starts on "Eins". E pressed earlier begins the
   ending at once. X is always pressed by hand.
