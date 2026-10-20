# Athene

Athene's visuals for the LED wall: an audioreactive, living coordinate system
(brief: `description.md`). The page in `page/` draws them in the browser; the
Python modules feed it the voice and the cluster clips.

- `live.py`: the live page for rehearsals, the play's scenes performed from
  the keyboard (below).
- `render.py`: renders a design to PNG frames or video at 3840 × 2160 and
  50 fps, or previews it in the browser.
- `analyse.py`: turns a voice clip into the values that move the page.
- `cut_clips.py`: cuts four-second clips from other footage for the clusters.
- `page/`: the page core (`athene.js`) and the designs (`page/designs/`).
- `archive/`: the Seestone-branded prototypes (see `archive/README.md`).
- `out/`: analyses, frame sheets, renders and the live page's files (ignored
  by git).

## Starting the live page

From the repo root, with the `apollon` environment active and `ffmpeg` on the
PATH:

    .\apollon\Scripts\Activate.ps1
    python -m athene.live

This serves the rehearsal design (`page/designs/rehearsal.js`) at
`http://127.0.0.1:8766/?design=rehearsal&mode=live` and opens it in the
default browser. Put the browser in fullscreen (F11) on the wall. Ctrl+C in
the terminal stops the server.

The first start takes a while: each voice clip is analysed and the cluster
clips are cut to small looping videos, all kept in `out/live/`. Later starts
reuse them; a voice clip is analysed again only when its file is newer.

Options:

    python -m athene.live --voices FOLDER       # other voice clips (default: example_audio/athene_voice_placeholder)
    python -m athene.live --clips A B           # other cluster clip folders, one group each
    python -m athene.live --res 0.5             # draw at a fixed half of 3840 × 2160 (default: fitted to the screen)
    python -m athene.live --port 8800           # another port

The clusters take their clips from `data/clips/hitl_database` (rehearsal
footage, key R) and `data/clips/athene_online` (online footage, key O, cut by
`cut_clips.py`). The voice clips play in name order, one per P.

### Keys

| Key   | Action                                                      |
|-------|-------------------------------------------------------------|
| N / B | next / previous scene                                       |
| Space | restart the scene                                           |
| P     | play the scene's next voice clip, or stop the one playing   |
| R / O | death scene: a cluster of rehearsal / online clips          |
| E     | growth scene: the ending (explosion, black hole, glow)      |
| S     | growth scene: the strobe                                    |
| V     | growth scene: switch between branching and straight axes   |
| L     | straight variant: strikes automatic or manual               |
| T     | manual strikes: hold to fire strikes for as long as held    |
| C     | straight variant: colour on or off (white)                  |
| 0     | straight variant, after the ending: the zero blinks into a one |
| H     | show or hide the help line                                  |

### Scenes

In every scene the lines are chrome: satin bands along them and glints
where two slowly turning lights catch them.

1. **Two axes**: the two axes move and probe, on their own and on every
   syllable.
2. **Death scene**: the axes twirl until the first cluster key, then rest and
   breathe. Each R or O places a cluster on the wall and grows an axis to it.
3. **Two axes**: the death scene's axes and clusters draw back.
4. **Growth**: the network grows faster and faster for five minutes and on
   until E ends it. It comes in two variants, switched with V at any moment:
   - **Branching**: the axes fork into branches that shoot out like
     lightning. S makes the glow flicker, and E ends in a glowing circle.
   - **Straight**: no branches. Ever more straight axes join through the
     centre until they fill the wall and run past its edges. The lines are
     chrome-white metal out of a glowing core that grows with them. Later
     in the growth their glow turns red from the centre out to the tips,
     shimmering. They glow with a strobe
     that stays rare for long and crowds in towards the end; some flashes
     light the plane two or three axes span, often as a cascade of quick
     strikes from one axis to one after another. S switches to the full strobe,
     and E ends in a white zero, which 0 turns into a one after four blinks.
