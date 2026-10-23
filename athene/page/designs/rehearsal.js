/* Rehearsal: Athene's scenes of the play, performed live from the keyboard.

   The network, glow and clusters of the fourth axes design
   (designs/axes4.js), driven by the scenes of athene/description.md instead
   of a clip's timeline. Served by athene/live.py with the voice clips of the
   scenes and the clip groups of the clusters.

     1  two axes      the two axes of the coordinate system move and probe:
                      they reach out on their own and on every syllable.
     2  death scene   the axes move and probe until the first cluster key;
                      then they stop turning and only move along their
                      length: they breathe, and now and then one reaches
                      out a little. Each C places a cluster of clips somewhere on
                      the wall, apart from the others, and grows a new axis
                      out of the centre to it. A cluster mixes the death
                      scene rehearsals and the play's end videos. Its clips
                      play as looping videos, each at most once per run of
                      the scene; they appear large and spread out, and
                      after a while shrink slowly into the cluster.
     3  two axes      the death scene's axes and clusters draw back, and the
                      two axes move and probe again.
     4  growth        ever more straight axes join through the centre, ever
                      faster, until they fill the wall and reach out beyond
                      it, out of a glowing core that grows with them, with a
                      pulse of light that quickens as it grows. The lines
                      are white metal and glow with a strobe of their own,
                      rare for long and crowding in at the end (S: the full
                      strobe); some flashes light the plane two or three
                      axes span. E ends it: the network explodes in a
                      flickering strobe until it fills the wall, is sucked
                      into the centre like a star into a black hole, and a
                      zero opens out of it; 0 makes the zero blink four
                      times and come back as a one.

   Keys: N next scene, B previous scene, Space restart the scene, P play the
   scene's next voice clip (or stop the one playing), H show or hide the
   help line. Changing scene stops the voice and animates the network into
   the new scene's state.

   The voice lights the network in every scene: each syllable sends a bolt
   of light from the hub out along one ray, and the glow rises with the
   level. The live page draws at the resolution its view takes on the
   screen, one pixel per screen pixel; `LIVE.res` or ?res= set a fixed share
   of the view's full size instead.

   Athene lives in a 9:1 world as high as the 4K frame. A live page draws
   one view of it (?view=): "strip", the whole world for the 9:1 output
   (3840 × 427 at full size), or "wall", its middle section for the 16:9
   output (3840 × 2160, the default). One page conducts the performance: it
   takes the keys, plays the voices and sends its state, every frame, to
   the pages following it in the same browser. A page opened with ?follow
   draws its view of that state and takes no keys and plays no sound, so
   two views stay in step frame by frame. ?hint=0 hides the help line from
   the start. ?rehearsal makes the world the 16:9 frame, as it was before
   the strip, for rehearsing on one screen.

   AXES holds the parameters of the network, SCENES and LIVE those of the
   performance. */

"use strict";

// The world, in px: nine times as wide as the frame is high, or with
// ?rehearsal the 16:9 frame itself, as Athene was drawn before the strip
// (the wall view then shows all of it).
const WORLD_W = params.has("rehearsal") ? W : 9 * H;
// The views of the world: the part shown (x, y, w, h, in world px) and the
// size it is drawn at in full (out, in px).
const VIEWS = {
  strip: { x: 0, y: 0, w: WORLD_W, h: H, out: [W, Math.round(H * W / WORLD_W)] },
  wall: { x: (WORLD_W - W) / 2, y: 0, w: W, h: H, out: [W, H] },
};
const VIEW = VIEWS[params.get("view")] || VIEWS.wall;
// Drawn px per world px, at full size.
const ZOOM = VIEW.out[0] / VIEW.w;
const FOLLOW = params.has("follow");
const CHANNEL = "BroadcastChannel" in window ? new BroadcastChannel("athene-live") : null;

const AXES = {
  dims: 56,             // dimensions of the space: the axes of the growth scene
  radius: 1000,         // px, half-length of an axis at full size
  centre: [WORLD_W / 2, H / 2],
  margin: 70,
  hub: [10, 22],        // px, radius of the hub with two axes and at full size

  // Growth (scene 4): `growthSpan` seconds to full size and the full
  // schedule of axes; it keeps growing beyond, at `overgrowth` of
  // full size per span. The schedule runs on a clock that speeds up: after
  // a share x of the span it stands at x ^ `accelerate`, so the growth
  // quickens towards the end. Growth times below are in that clock's seconds.
  growthSpan: 180, accelerate: 1.8, overgrowth: 0.25,
  // Size of the figure with two axes, as a share of full size.
  twoAxisSize: 0.5, sizeCurve: 1,

  tilt: 0.9, tiltHidden: 0.3, tiltRate: [0.02, 0.06], planesPerDim: 3,
  spin: 0.008, normalise: 0.8, foreshorten: 0.5,

  // New axes join within `joinLife` seconds, the last ones within
  // `joinLifeLast`. Each half of an axis joins `halfDelay` seconds late, at
  // `halfPace` times that speed, and takes on a lasting length of its own
  // (`halves`, as a share of the axis) between these shares of the growth.
  joinFirst: 0.01, joinLast: 0.75, joinCurve: 0.85, joinLife: 7, joinLifeLast: 0.6,
  halfDelay: [0, 6], halfPace: [0.5, 2],
  halves: [0.2, 1.6], halvesFirst: 0, halvesLast: 0.3,

  reach: 0.3, reachRate: 0.12,
  shootFlash: 0.9,      // the flash of an axis as it shoots out, fading as it reaches its length

  // Tubes: width in px is minWidth + widthGain × √(share grown), at most maxWidth.
  minWidth: 3, widthGain: 2.6, maxWidth: 12, taperTip: 0.6, faint: 0.45,
  pulse: 0.22, pulsePeriod: 7, pulseLength: 1400,
  glow: [0.45, 1.0], glowBlur: 7, bloom: [0.1, 0.85], bloomBlur: 10,

  boltSpeed: 3500, boltRise: 0.03, boltFade: 0.22,
  boltGlow: 1.0, boltBlur: 3, levelGlow: 0.3,

  clipWidth: 280,       // px once settled; the height follows the clips' aspect ratio
  clipsPerCluster: 16,
  clipScatter: 480, clipTilt: 0.1, clipIn: 0.05, clipAlpha: 0.92,
  // A clip appears `clipLarge` times its settled size, stays so for
  // `clipLargeFor` seconds and shrinks over `clipShrink` seconds, drawing
  // into its cluster as it does.
  clipLarge: 2.5, clipLargeFor: 12, clipShrink: 6,
  clipGrey: false,
};

// The scenes: their voice clips (by the start of their file names, played
// in this order), whether the network moves, whether the axes probe, and
// whether it grows. The death scene moves and probes until its first
// cluster.
const SCENES = [
  { name: "ZWEI ACHSEN", voices: ["athene_1", "athene_2"], motion: 1, probing: true },
  { name: "TODESSZENE", voices: ["athene_3"], motion: 1, probing: true, death: true },
  { name: "WIEDER ZWEI ACHSEN", voices: ["athene_4_new"], motion: 1, probing: true },
  { name: "WACHSTUM", voices: ["athene_5_new", "athene_6_new"], motion: 1, growing: true },
];

const LIVE = {
  res: 0,               // drawing resolution of the live page, as a share of 3840 × 2160; 0 fits it to the screen
  minLinePx: 1.5,       // drawn pixels: thinner lines are drawn this wide and dimmed in proportion
  motionEase: 1.5,      // seconds the network takes to stop or start moving
  rewind: 1.2,          // time constant in seconds of the growth drawing back
  // Probes: a ray thrusts forward by a share of its length in `rise`
  // seconds and draws back in `fall`; on its own every `probeGap` seconds,
  // and on every syllable of the voice.
  probeGap: [2, 5], probe: [0.2, 0.45], probeRise: 0.5, probeFall: 1.4,
  flick: 0.4, flickRise: 0.12, flickFall: 0.6,
  // Death scene: seconds an axis takes to grow out and to draw back, the
  // length of its other half as a share of it, and how far a ray breathes
  // along its length at rest (a share, radians of wave phase per second).
  deathGrow: 2, deathRetract: 2.5, deathBack: 0.4,
  breathe: 0.12, breatheRate: 0.9,
  // At rest a ray reaches out along its length every `restProbeGap`
  // seconds, by a share of it, rising and falling over these seconds.
  restProbeGap: [1.5, 4], restProbe: [0.05, 0.12], restProbeRise: 0.9, restProbeFall: 2.2,
  // Clusters: placed at the best of `placeTries` random points, the one
  // furthest from the other clusters, at least `placeHub` px from the hub.
  placeTries: 40, placeHub: 550,
  clusterLeave: 0.8,
  // Seconds a starting clip may be from where the performance's clock puts
  // it before it is moved there (playFrom).
  clipJoin: 0.3,
  // Growth scene: bolts on their own per second, and a pulse of the glow in
  // Hz with its depth, from the start to the full schedule; the motion
  // speeds up to 1 + `hectic` times at full size.
  boltRate: [0.15, 8], pulseRate: [0.2, 3.5], pulseDepth: [0, 0.9], hectic: 1.5,
  // Ending: for `explode` seconds the network explodes, the strobe on and
  // `explodeBolts` bolts per second, its growth sped up to `explodeGrowth`
  // times and its size rising to `explodeSize` times. Then within `collapse`
  // seconds it is sucked into the centre, faster and faster, the parts near
  // the centre first and turning up to `swirl` radians. The zero opens
  // within `ringGrow` seconds as it vanishes.
  // While it explodes, the flickering glow floods the wall through a wide
  // wash (`explodeWash` times, blurred `washBlur` px at a sixteenth of the
  // resolution), and the sharp lines fade out, leaving the glow. Over its
  // last `whiteRise` seconds the light rises to a white wall, which holds for
  // `whiteHold` seconds before the collapse and fades over its first
  // `whiteFade` seconds.
  explode: 6, explodeBolts: 14, explodeGrowth: 25, explodeSize: 2.2,
  explodeWash: 3, washBlur: 14,
  whiteRise: 1.5, whiteHold: 4, whiteFade: 0.8,
  collapse: 3.5, swirl: 4, ringGrow: 3,
  // Strobe: flashes of the glow at irregular gaps (s), of random strength,
  // each fading with a time constant (s); between flashes the glow sinks to
  // `strobeBase` of its strength.
  strobeGap: [0.03, 0.28], strobeStrength: [0.5, 2.5], strobeFade: [0.03, 0.12], strobeBase: 0.25,

  // Growth scene: its look (the glow shaded as metal, the core in place of
  // the hub's disc, the strobe resting low) comes in within `lookFade`
  // seconds as the scene is entered and goes as it is left. `lines` further
  // axes join through the centre, between these shares of the schedule, the count rising as the
  // schedule's share to the power 1 / `lineCurve`, each within `lineLife`
  // seconds (the first to the last), flashing while it shoots out. An axis
  // is `lineLength` of AXES.radius long and drifts up to `lineDrift` radians;
  // every axis reaches out to 1 + `outward` × share² times its length, so by
  // full size most run beyond the wall. Their tubes are `lineWidth` of the
  // network's and lit at `lineAlpha`.
  lookFade: 1.5,
  lines: 300, lineFirst: 0.05, lineLast: 1.1, lineCurve: 0.5, lineLife: [4, 0.25],
  lineLength: [0.35, 1.1], lineDrift: 0.12, lineDriftRate: [0.03, 0.12],
  outward: 2.5, outwardCap: 1.6, lineWidth: 0.5, lineAlpha: [0.35, 1],
  // Glow by strobe: in the growth scene the glow rests at `strobeRest`
  // (from the start to full size, as the strobe takes over) and blazes with
  // each flash of a strobe that runs on its own,
  // `autoStrobe` flashes a second from the start to the full schedule, or
  // at the strobe's gaps with S. Its flashes and the bolts along the lines
  // follow the schedule's share to the power `strikeCurve`, so they stay
  // rare for long and crowd in towards the end; a flash fades within
  // `strobeFadeEarly` at the start and `strobeFade` at full size.
  autoStrobe: [0.1, 14], strikeCurve: 3, strobeFadeEarly: [0.08, 0.2], strobeRest: [1, 0.5],
  // With S, the growth scene's strobe follows the share to the power
  // `strobeGrowth` until the ending: gaps of `strobeGapEarly` seconds and
  // `strobeEarly` of the flashes' strength at the start, the full strobe
  // (strobeGap, strobeStrength) at full size.
  strobeGrowth: 1.5, strobeGapEarly: [0.4, 1.4], strobeEarly: 0.3,
  // Core: in the growth scene a glowing core takes the place of the hub's
  // disc, `coreRadius` px from the start to full size (following the share
  // to the power `coreCurve`) at `coreGlow` brightness, swelling with the
  // voice (`coreVoice`) and the strobe (`coreFlash`). Around it a halo
  // lights the wall out to `haloRadius` px at `haloAlpha` from the start to
  // full size, brightening by `haloFlash` with the strobe.
  coreRadius: [0, 900], coreCurve: 1.2, coreGlow: [0, 1], coreVoice: 0.12, coreFlash: 0.15,
  haloRadius: [0, 2200], haloAlpha: [0, 0.45], haloFlash: 0.25,
  // Heart: within the radius where the lines' widths at the centre add up
  // to its circumference (their summed width / 2π, times `heartSpread`)
  // they merge into white light, falling off as a bell curve `heartWidth`
  // times that radius wide, out to `heartFade` times it. It grows with
  // every line that joins, from nothing.
  heartSpread: 1, heartWidth: 0.8, heartFade: 2.6,
  // The lines' glow in the growth scene, from the start to full size:
  // drawn `glowWidth` times as wide as the lines and brightened
  // `lineGlow` times.
  glowWidth: [1, 2.5], lineGlow: [1.2, 3],
  // Planes: a flash lights the plane two axes span from the centre (the
  // parallelogram), or three (`planeTriple` of the time, a hexagon), filled
  // at `planeAlpha` of its strength and glowing at `planeGlow` of that. The
  // axes of a plane are at least `planeApart` (the sine of their angle)
  // apart. `autoPlane` of the strobe's own flashes light one plane; with
  // S, each flash lights `planesPerFlash`.
  planeTriple: 0.25, planeAlpha: 0.16, planeGlow: 0.25, planeApart: 0.25,
  autoPlane: 0.5, planesPerFlash: [1, 3],
  // Cascades: `cascadeShare` of the strikes become a cascade of quick
  // strikes, `cascadeGap` seconds apart, each lighting the plane between one
  // axis that stays and a different axis each time. A cascade has from
  // `cascadeMin` strikes up to as many as its axis has planes with the
  // axes present, drawn as a share of that range to the power
  // `cascadeSkew` (1 even, higher favouring short ones). Each strike fades
  // within `cascadeFade` and flashes the glow at `cascadeGlow` of its
  // strength. At most `cascadeMax` run at once.
  cascadeShare: 0.5, cascadeMin: 2, cascadeSkew: 1, cascadeGap: [0.03, 0.1], cascadeFade: [0.03, 0.1],
  cascadeGlow: 0.5, cascadeMax: 2,
  // Metal: every edge, in every scene, is shaded (`chrome` of the way, 0 to
  // 1) from `metalDark` through `metalMid` of white to white, after the
  // satin chrome of the liquid design.
  // Satin bands
  // `bandLength` px apart run along it, warped by its angle (`bandWarp`
  // radians) and flowing at `bandFlow` radians a second; two lights, turning
  // at `lightTurn` radians a second and `glintAngle` apart, make the edges
  // facing them glint (sharper the higher `glintPower`). Each flash of the
  // strobe makes the glints blaze by `flashGlint` of its strength. The
  // gradient along an edge has a stop every quarter band, at most
  // `metalStops`.
  chrome: 1, metalDark: 0.12, metalMid: 0.7, metalSheen: 0.6,
  bandLength: 520, bandWarp: 2.5, bandFlow: 0.15, bandDepth: 0.5,
  lightTurn: 0.04, glintAngle: 1.9, glintPower: [40, 80], glintSecond: 0.5, glintBase: 0.45,
  flashGlint: 0.8, metalStops: 12,
  // The growth scene's ending opens a zero, drawn as a line like the
  // network's, in the proportions of a sans-serif typeface: `digitHeight` px
  // high, measured to the line's middle, and the line `digitWidth` px wide.
  // The zero is a superellipse (exponent `digitRound`, between an ellipse
  // and a rectangle) `digitAspect` of the height wide. The one is a stem as
  // high whose flag reaches `digitFlag` of the height to the left and down.
  // The digits stay crisp: they light the
  // glow at only `digitGlow` of their strength. Key 0 makes the zero blink
  // `blinks` times (`blinkOff` dark, `blinkOn` lit, in seconds); it comes
  // back from the last blink as a one. A voice clip saying "von null auf
  // eins" (found by athene/live.py) ends the scene by itself: the ending
  // begins so that the zero has stood fully open for `zeroHold` seconds when
  // the sentence comes, and the zero blinks on its four words: dark
  // `blinkOff` before each word, at most `blinkGap` of the time since the
  // word before, and lit again on the word, as a one on "eins".
  digitHeight: 620, digitWidth: 46, digitAspect: 0.68, digitRound: 2.4, digitFlag: [0.3, 0.22], digitGlow: 0.1,
  blinks: 4, blinkOff: 0.2, blinkOn: 0.35, blinkGap: 0.5, zeroHold: 2,
  // Manual strikes (from the start; L switches to automatic and back): the
  // strobe's own flashes and plane strikes stop, and holding T fires strikes `strikeGap` seconds
  // apart, each flashing the glow and lighting a plane (or beginning a
  // cascade), for as long as T is held.
  strikeGap: [0.04, 0.18],
};

// ---- Helpers -------------------------------------------------------------------

function wave(random, rate) {
  const parts = [1, 0.55, 0.3].map((amp) => ({
    amp, rate: rate * (0.6 + 0.9 * random()), phase: 2 * Math.PI * random(),
  }));
  const total = parts.reduce((sum, p) => sum + p.amp, 0);
  return (x) => parts.reduce((sum, p) => sum + p.amp * Math.sin(p.rate * x + p.phase), 0) / total;
}

function between(random, [lo, hi]) {
  return lo + (hi - lo) * random();
}

// A value easing from one level to another over a stretch of the live clock.
function tween(value) {
  return { from: value, to: value, start: 0, dur: 1 };
}

function tweenAt(tw, clock) {
  return tw.from + (tw.to - tw.from) * ease((clock - tw.start) / tw.dur);
}

function tweenTo(tw, to, dur, clock, delay = 0) {
  tw.from = tweenAt(tw, clock);
  tw.to = to;
  tw.start = clock + delay;
  tw.dur = dur;
}

const WHITE = [255, 255, 255];

// A colour as CSS. The strings are kept, since tens of thousands of
// gradient stops a frame repeat far fewer colours.
const cssKept = new Map();
function css([r, g, b]) {
  const byte = (v) => Math.max(0, Math.min(255, Math.round(v)));
  const key = (byte(r) << 16) | (byte(g) << 8) | byte(b);
  let s = cssKept.get(key);
  if (s === undefined) {
    s = `rgb(${key >> 16},${(key >> 8) & 255},${key & 255})`;
    if (cssKept.size < 100000) cssKept.set(key, s);
  }
  return s;
}

function mixRGB(a, b, k) {
  return a.map((v, i) => v + (b[i] - v) * k);
}

// Colour `rgb` as metal at `shade`, 0 (dark) to 1 (highlight), with
// `metal` (0 to 1) of the metal look.
function metalRGB(rgb, shade, metal) {
  const s = Math.min(1, Math.max(0, shade));
  const mid = rgb.map((v) => v * LIVE.metalMid);
  const lit = s < 0.5
    ? mixRGB(rgb.map((v) => v * LIVE.metalDark), mid, 2 * s)
    : mixRGB(mid, mixRGB(rgb, [255, 255, 255], LIVE.metalSheen), 2 * s - 1);
  return mixRGB(rgb, lit, metal);
}

// The shade of metal at angle `a` and `r` px from the centre: satin bands
// along the edges and the glints of two lights, blazing with the strobe.
function sheen(a, r, now, clock, blaze) {
  const light = LIVE.lightTurn * clock;
  const glint = Math.abs(Math.cos(a - light)) ** LIVE.glintPower[0]
    + LIVE.glintSecond * Math.abs(Math.cos(a - light - LIVE.glintAngle)) ** LIVE.glintPower[1];
  const band = 0.5 + 0.5 * Math.sin(2 * Math.PI * r / LIVE.bandLength
    + LIVE.bandWarp * Math.sin(2 * a + LIVE.bandFlow * now) - LIVE.bandFlow * now);
  return 0.2 + LIVE.bandDepth * band + glint * (LIVE.glintBase + LIVE.flashGlint * blaze);
}

// A thrust that rises within `rise` seconds and falls back to nothing in `fall`.
function thrust(x, rise, fall) {
  if (x <= 0 || x >= rise + fall) return 0;
  return ease(x / rise) * (1 - ease((x - rise) / fall));
}

// ---- The space -------------------------------------------------------------------

const space = { planes: [], joins: [], joinLives: [], roots: [], lines: [] };

// The cluster clips ({url, group} played as videos, or {sheet, group} drawn
// from a frame sheet: {image, frames, fps, cell, columns}) in the order the
// clusters take them (mixedOrder), and the voice clips with their analyses.
const clipFiles = [];
const voices = [];

// Seconds of the growth schedule after `growth` seconds of the scene.
function scheduled(growth) {
  return AXES.growthSpan * (growth / AXES.growthSpan) ** AXES.accelerate;
}

function buildSpace() {
  const random = makeRandom(31);
  const n = AXES.dims;
  const span = AXES.growthSpan;
  space.joins = [-Infinity, -Infinity];
  space.joinLives = [AXES.joinLife, AXES.joinLife];
  for (let j = 2; j < n; j++) {
    const x = n > 3 ? (j - 2) / (n - 3) : 0;
    space.joins.push((AXES.joinFirst + (AXES.joinLast - AXES.joinFirst) * x ** AXES.joinCurve) * span);
    space.joinLives.push(AXES.joinLife + (AXES.joinLifeLast - AXES.joinLife) * x);
  }
  space.planes = [];
  for (let j = 1; j < n; j++) {
    const partners = new Set();
    while (partners.size < Math.min(j, AXES.planesPerDim)) partners.add(Math.floor(random() * j));
    for (const i of partners) space.planes.push({ i, j, wave: wave(random, between(random, AXES.tiltRate)) });
  }
  // The halves of the axes, two per dimension.
  space.roots = [];
  for (let h = 0; h < 2 * n; h++) {
    space.roots.push({
      id: h,
      join: space.joins[h >> 1] + between(random, AXES.halfDelay),
      life: space.joinLives[h >> 1] / between(random, AXES.halfPace),
      bias: between(random, AXES.halves),
      reach: wave(random, AXES.reachRate),
      breathe: wave(random, LIVE.breatheRate),
    });
  }
  // The growth scene's further axes, in the order they join.
  space.lines = [];
  for (let j = 0; j < LIVE.lines; j++) {
    const x = LIVE.lines > 1 ? j / (LIVE.lines - 1) : 0;
    space.lines.push({
      id: 2e6 + 2 * j,
      join: (LIVE.lineFirst + (LIVE.lineLast - LIVE.lineFirst) * x ** LIVE.lineCurve) * span,
      life: LIVE.lineLife[0] + (LIVE.lineLife[1] - LIVE.lineLife[0]) * x,
      angle: 2 * Math.PI * random(),
      halves: [between(random, LIVE.lineLength), between(random, LIVE.lineLength)],
      alpha: between(random, LIVE.lineAlpha),
      drift: wave(random, between(random, LIVE.lineDriftRate)),
      reach: wave(random, AXES.reachRate),
    });
  }
}

// The plane two or three axes span from the centre, as the polygon of all
// sums of shares of them: a parallelogram for two, a hexagon for three.
// Corners relative to the centre, in order around it.
function spanned(vectors) {
  const sides = vectors.flatMap(([x, y]) => [[x, y], [-x, -y]])
    .map((v) => ({ v, angle: (Math.atan2(v[1], v[0]) + 2 * Math.PI) % (2 * Math.PI) }))
    .sort((a, b) => a.angle - b.angle);
  // Start at the corner lowest in y: the sum of the axes pointing that way.
  let x = 0, y = 0;
  for (const [vx, vy] of vectors) if (Math.atan2(vy, vx) < 0) { x += vx; y += vy; }
  const corners = [];
  for (const { v } of sides) {
    corners.push([x, y]);
    x += v[0];
    y += v[1];
  }
  return corners;
}

// ---- The performance ----------------------------------------------------------------

const live = {
  clock: 0,             // seconds since the page started
  scene: 0,
  now: 0,               // the clock of the network's motion, standing still while frozen
  motion: tween(1),
  growth: 0,
  growthMode: "rewind", // "rewind" towards nothing, "restart" (rewind, then run) or "run"
  pokes: [],            // {start, strength, ray, rise, fall}
  nextProbe: 0,
  bolts: [],            // {start, strength, ray, seed}
  pulsePhase: 0,
  deathAxes: [],        // {id, angle, length, born, leaving, breathe (the seed of its breathing)}
  clusters: [],         // {id, x, y, appear, leaving, clips: [{video (null where drawn from a sheet), file (index in clipFiles), dx, dy, tilt}]}
  still: false,         // the death scene has come to rest
  nextClip: 0,          // the next clip to use in this run of the death scene
  regrow: tween(1),     // the network growing back out of the centre after the ending
  ring: tween(0),
  endAt: null,          // the clock when E was pressed
  strobe: false,
  flashes: [],          // the strobe's flashes: {start, strength, fade}
  nextFlash: 0,
  look: tween(0),       // the growth scene's look: 1 in that scene, 0 in the others, easing between them
  manual: true,         // the growth scene's strikes fired by hand (T) instead of on their own
  striking: false,      // T is held
  nextStrike: 0,        // the clock of the next strike while T is held
  planes: [],           // the planes lit: {start, strength, fade, rays}
  cascades: [],         // strikes in succession: {anchor, used, left, next}
  blinks: null,         // the zero's blinks on the clock: [{dark, on}], the last lit again as a one
  queue: 0,             // the scene's next voice clip
  voice: null,          // {audio, analysis, last, zeroToOne}
  rays: [],             // the rays of the last frame: {id, angle, length, root}
  hint: params.get("hint") !== "0",
};

function sceneOf() {
  return SCENES[live.scene];
}

function stopVoice() {
  if (!live.voice) return;
  live.voice.audio.pause();
  live.voice.audio.currentTime = 0;
  live.voice = null;
}

// Enters scene k from whatever state the network is in.
function enter(k) {
  live.scene = k;
  const scene = sceneOf();
  stopVoice();
  live.queue = 0;
  tweenTo(live.motion, scene.motion, LIVE.motionEase, live.clock);
  tweenTo(live.look, scene.growing ? 1 : 0, LIVE.lookFade, live.clock);
  for (const d of live.deathAxes) if (d.leaving === null) d.leaving = live.clock;
  for (const c of live.clusters) if (c.leaving === null) c.leaving = live.clock;
  // Each run of the death scene draws on all clips again.
  live.nextClip = 0;
  live.still = false;
  live.growthMode = scene.growing ? "restart" : "rewind";
  if (live.endAt !== null) {
    // The network was sucked into the centre: it grows back out of it.
    live.growth = 0;
    live.regrow = { from: 0, to: 1, start: live.clock, dur: 2 };
    tweenTo(live.ring, 0, 1, live.clock);
  }
  live.endAt = null;
  live.blinks = null;
  live.strobe = false;
  live.planes = [];
  live.cascades = [];
  showHint();
}

function playVoice() {
  if (live.voice) {
    stopVoice();
    showHint();
    return;
  }
  const names = sceneOf().voices;
  if (live.queue >= names.length) return;
  const voice = voices.find((v) => v.name.startsWith(names[live.queue]));
  live.queue += 1;
  if (!voice) return;
  live.voice = { audio: voice.audio, analysis: voice.analysis, last: 0, zeroToOne: voice.zeroToOne };
  voice.audio.currentTime = 0;
  voice.audio.play();
  voice.audio.onended = () => {
    if (live.voice && live.voice.audio === voice.audio) live.voice = null;
    showHint();
  };
  showHint();
}

// The clips in the order the clusters take them: the clip groups merged in
// proportion to their sizes, each in the order athene/live.py lists it, so
// that every cluster mixes the groups and all of them run out together.
function mixedOrder(files) {
  const groups = new Map();
  for (const f of files) {
    if (!groups.has(f.group)) groups.set(f.group, []);
    groups.get(f.group).push(f);
  }
  const lists = [...groups.values()];
  const taken = lists.map(() => 0);
  const share = (k) => (taken[k] + 0.5) / lists[k].length;
  const order = [];
  while (order.length < files.length) {
    // The group furthest behind its share.
    let g = -1;
    lists.forEach((list, k) => {
      if (taken[k] < list.length && (g < 0 || share(k) < share(g))) g = k;
    });
    order.push(lists[g][taken[g]++]);
  }
  return order;
}

// Clusters left in this run of the death scene.
function clustersLeft() {
  return Math.ceil(Math.max(0, clipFiles.length - live.nextClip) / AXES.clipsPerCluster);
}

// Starts a clip's video `at` seconds into the clip, where the performance's
// clock puts it, once its length is known: a follower that starts it late,
// or a page whose clip comes back into view, joins it where the other pages
// show it. From there it plays freely.
function playFrom(video, at) {
  if (!video.paused || !video.duration) return;
  const t = at % video.duration;
  if (Math.abs(video.currentTime - t) > LIVE.clipJoin) video.currentTime = t;
  video.play().catch(() => {});
}

// A looping, silent video of a clip.
function clipVideo(url) {
  const video = document.createElement("video");
  video.src = url;
  video.muted = true;
  video.loop = true;
  video.playsInline = true;
  return video;
}

// The breathing of a death scene axis, made from its seed, so that every
// page following the performance breathes it alike.
const breathings = new Map();
function breathing(seed) {
  if (!breathings.has(seed)) breathings.set(seed, wave(makeRandom(seed), LIVE.breatheRate));
  return breathings.get(seed);
}

// A cluster of clips somewhere in the world, the whole 9:1 strip, apart
// from the others, and a new axis of the death scene from the centre to it.
// The first one brings the network to rest. Clusters take the next clips of
// clipFiles, and no clip is shown twice in a run of the scene: once all are
// shown, the key does nothing.
function deathCluster() {
  if (!sceneOf().death || !clustersLeft()) return;
  if (!live.still) {
    live.still = true;
    tweenTo(live.motion, 0, LIVE.motionEase, live.clock);
  }
  const [cx, cy] = AXES.centre;
  const m = AXES.margin;
  const hw = AXES.clipWidth / 2 + 0.5 * AXES.clipScatter, hh = AXES.clipWidth * 0.3 + 0.35 * AXES.clipScatter;
  const others = live.clusters.filter((c) => c.leaving === null);
  let x = cx, y = cy, best = -Infinity;
  for (let k = 0; k < LIVE.placeTries; k++) {
    const px = m + hw + Math.random() * (WORLD_W - 2 * (m + hw));
    const py = m + hh + Math.random() * (H - 2 * (m + hh));
    if (Math.hypot(px - cx, py - cy) < LIVE.placeHub) continue;
    const apart = others.reduce((d, c) => Math.min(d, Math.hypot(px - c.x, py - c.y)), WORLD_W);
    if (apart > best) { best = apart; x = px; y = py; }
  }
  const angle = Math.atan2(y - cy, x - cx);
  const id = 1e6 + live.deathAxes.length;
  live.deathAxes.push({
    id, angle, length: Math.hypot(x - cx, y - cy), born: live.clock, leaving: null,
    breathe: Math.floor(Math.random() * 2 ** 31),
  });

  const first = live.nextClip;
  const picked = clipFiles.slice(first, first + AXES.clipsPerCluster);
  live.nextClip += picked.length;
  const clips = picked.map((f, k) => ({
    video: f.url ? clipVideo(f.url) : null,
    file: first + k,
    dx: AXES.clipScatter * (2 * Math.random() - 1),
    dy: AXES.clipScatter * 0.7 * (2 * Math.random() - 1),
    tilt: AXES.clipTilt * (2 * Math.random() - 1),
  }));
  live.clusters.push({ id: clustersMade++, x, y, appear: live.clock + 0.8 * LIVE.deathGrow, leaving: null, clips });
  showHint();
}
let clustersMade = 0;

// Stops a cluster's videos and lets their memory go.
function release(cluster) {
  for (const c of cluster.clips) if (c.video) stopVideo(c.video);
}

function stopVideo(video) {
  video.pause();
  video.removeAttribute("src");
  video.load();
}

// Seconds from the start of the ending until the zero begins to open.
function ringDelay() {
  return LIVE.explode + LIVE.whiteHold + 0.85 * LIVE.collapse;
}

function endScene() {
  if (!sceneOf().growing || live.endAt !== null) return;
  live.endAt = live.clock;
  live.strobe = true;
  live.flashes = [];
  live.nextFlash = live.clock;
  tweenTo(live.ring, 1, LIVE.ringGrow, live.clock, ringDelay());
  showHint();
}

// The growth scene's zero starts to blink in its own rhythm, once it has
// opened.
function blinkDigit() {
  if (!sceneOf().growing || live.blinks) return;
  if (tweenAt(live.ring, live.clock) < 0.5) return;
  const cycle = LIVE.blinkOff + LIVE.blinkOn;
  live.blinks = Array.from({ length: LIVE.blinks }, (_, k) => ({
    dark: live.clock + k * cycle,
    on: live.clock + k * cycle + LIVE.blinkOff,
  }));
  showHint();
}

// The zero blinks on the words of "von null auf eins", their starts on the
// live clock.
function blinkOnWords(words) {
  live.blinks = words.map((on, k) => ({
    dark: on - (k ? Math.min(LIVE.blinkOff, LIVE.blinkGap * (on - words[k - 1])) : LIVE.blinkOff),
    on,
  }));
}

// The digit the growth scene ends with at the live clock: "0", "1", or
// null while it is dark in a blink.
function digitAt(clock) {
  if (!live.blinks) return "0";
  const next = live.blinks.find((b) => clock < b.on);
  if (!next) return "1";
  return clock >= next.dark ? null : "0";
}

// The rays a plane can be spanned by.
function planeRays() {
  return live.rays.filter((r) => r.root && r.length > 20);
}

// A strike: the plane two or three axes span lights up, the axes picked at
// random among those well apart in angle; or, `cascadeShare` of the time,
// a cascade of strikes from one axis begins.
function planeFlash(strength, fade) {
  const rays = planeRays();
  if (rays.length < 2) return;
  if (live.cascades.length < LIVE.cascadeMax && Math.random() < LIVE.cascadeShare) {
    const anchor = rays[Math.floor(Math.random() * rays.length)];
    // The planes this axis can span with the axes present: its most strikes.
    const planes = rays.filter((r) => Math.abs(Math.sin(r.angle - anchor.angle)) > LIVE.planeApart).length;
    const least = Math.min(LIVE.cascadeMin, planes);
    live.cascades.push({
      anchor: anchor.id,
      used: new Set([anchor.id]),
      left: least + Math.floor(Math.random() ** LIVE.cascadeSkew * (planes - least + 1)),
      next: live.clock,
    });
    return;
  }
  const count = rays.length > 2 && Math.random() < LIVE.planeTriple ? 3 : 2;
  const chosen = [];
  for (let tries = 0; tries < 20 && chosen.length < count; tries++) {
    const r = rays[Math.floor(Math.random() * rays.length)];
    if (chosen.every((c) => Math.abs(Math.sin(r.angle - c.angle)) > LIVE.planeApart)) chosen.push(r);
  }
  if (chosen.length < 2) return;
  live.planes.push({ start: live.clock, strength, fade, rays: chosen.map((r) => r.id) });
}

// The cascades' strikes that are due: each lights the plane between the
// cascade's axis and one it has not struck yet, and flashes the glow. A
// cascade ends when its strikes are spent or no axis is left to strike.
function strikeCascades() {
  const rays = planeRays();
  for (const c of live.cascades) {
    while (c.left > 0 && c.next <= live.clock) {
      const anchor = rays.find((r) => r.id === c.anchor);
      const free = anchor ? rays.filter((r) => !c.used.has(r.id)
        && Math.abs(Math.sin(r.angle - anchor.angle)) > LIVE.planeApart) : [];
      if (!free.length) {
        c.left = 0;
        break;
      }
      const partner = free[Math.floor(Math.random() * free.length)];
      c.used.add(partner.id);
      const strength = between(Math.random, LIVE.strobeStrength);
      const fade = between(Math.random, LIVE.cascadeFade);
      live.planes.push({ start: c.next, strength, fade, rays: [anchor.id, partner.id] });
      live.flashes.push({ start: c.next, strength: strength * LIVE.cascadeGlow, fade });
      c.left -= 1;
      c.next += between(Math.random, LIVE.cascadeGap);
    }
  }
  live.cascades = live.cascades.filter((c) => c.left > 0);
}

// The ending at the live clock: how far the explosion and the collapse have
// come, each 0 to 1, and how white the wall is between them, 0 to 1.
function endingOf(clock) {
  if (live.endAt === null) return { explode: 0, white: 0, collapse: 0 };
  const x = clock - live.endAt;
  const collapseAt = LIVE.explode + LIVE.whiteHold;
  const white = x < collapseAt
    ? ease((x - (LIVE.explode - LIVE.whiteRise)) / LIVE.whiteRise)
    : 1 - ease((x - collapseAt) / LIVE.whiteFade);
  return {
    explode: Math.min(1, x / LIVE.explode),
    white,
    collapse: Math.min(1, Math.max(0, (x - collapseAt) / LIVE.collapse)),
  };
}

function onKey(e) {
  if (e.repeat) return;
  const keys = {
    KeyN: () => { if (live.scene + 1 < SCENES.length) enter(live.scene + 1); },
    KeyB: () => { if (live.scene > 0) enter(live.scene - 1); },
    Space: () => enter(live.scene),
    KeyP: playVoice,
    KeyC: deathCluster,
    KeyE: endScene,
    KeyL: () => {
      if (!sceneOf().growing) return;
      live.manual = !live.manual;
      live.striking = false;
      live.cascades = [];
      showHint();
    },
    KeyT: () => {
      if (!sceneOf().growing || !live.manual || live.endAt !== null) return;
      live.striking = true;
      live.nextStrike = live.clock;
    },
    Digit0: blinkDigit,
    Numpad0: blinkDigit,
    KeyS: () => {
      if (!sceneOf().growing) return;
      live.strobe = !live.strobe;
      live.flashes = [];
      live.nextFlash = live.clock;
      showHint();
    },
    KeyH: () => { live.hint = !live.hint; showHint(); },
  };
  if (keys[e.code]) {
    e.preventDefault();
    keys[e.code]();
  }
}

function showHint() {
  const hint = document.querySelector(".hint");
  if (!hint) return;
  hint.style.display = live.hint ? "" : "none";
  const scene = sceneOf();
  const voice = live.voice ? "STIMME LÄUFT" : `P: STIMME ${Math.min(live.queue + 1, scene.voices.length)}/${scene.voices.length}`;
  const parts = [`SZENE ${live.scene + 1}/${SCENES.length} · ${scene.name}`, voice];
  if (scene.death) {
    parts.push(`C: CLUSTER (${clustersLeft() ? `NOCH ${clustersLeft()}` : "KEINE MEHR"})`);
  }
  if (scene.growing) {
    const voiceEnds = live.voice && live.voice.zeroToOne && live.endAt === null;
    parts.push(voiceEnds ? "ENDE MIT DER STIMME (E: SOFORT)" : "E: ENDE", `S: STROBO ${live.strobe ? "AN" : "AUS"}`,
      `L: BLITZE ${live.manual ? "MANUELL" : "AUTOMATISCH"}`);
    if (live.manual) parts.push("T: BLITZ (HALTEN)");
    if (live.endAt !== null) parts.push(live.voice && live.voice.zeroToOne ? "NULL ZU EINS MIT DER STIMME" : "0: NULL ZU EINS");
  }
  parts.push("N: WEITER", "B: ZURÜCK", "LEERTASTE: NEUSTART", "H: HILFE");
  hint.textContent = parts.join(" \\ ");
}

// The level of the voice playing and the syllables passed since the last frame.
function listen() {
  if (!live.voice) return { level: 0, syllables: [] };
  const { audio, analysis } = live.voice;
  const t = audio.currentTime;
  const i = Math.min(analysis.level.length - 1, Math.max(0, Math.floor(t * analysis.fps)));
  const syllables = analysis.onsets.filter(([start]) => start > live.voice.last && start <= t);
  live.voice.last = t;
  return { level: analysis.level[i] || 0, syllables };
}

function randomRay(rootsOnly) {
  const rays = live.rays.filter((r) => r.length > 20 && (!rootsOnly || r.root));
  return rays.length ? rays[Math.floor(Math.random() * rays.length)].id : null;
}

function update(dt) {
  live.clock += dt;
  const scene = sceneOf();
  const probing = scene.probing && !live.still;
  const motion = tweenAt(live.motion, live.clock);
  const grownSoFar = Math.min(1, scheduled(live.growth) / AXES.growthSpan);
  live.now += motion * dt * (scene.growing ? 1 + LIVE.hectic * grownSoFar ** 2 : 1);

  const ending = endingOf(live.clock);
  if (live.growthMode === "run") live.growth += dt * (1 + (LIVE.explodeGrowth - 1) * ease(ending.explode));
  else {
    live.growth *= Math.exp(-dt / LIVE.rewind);
    if (live.growth < 0.05) {
      live.growth = 0;
      if (live.growthMode === "restart") live.growthMode = "run";
    }
  }

  const heard = listen();
  // A voice clip saying "von null auf eins" ends the scene: the ending
  // begins in time for the zero to stand open `zeroHold` seconds before the
  // first blink, and the zero blinks into a one on the words. E pressed
  // earlier begins the ending then.
  const words = live.voice && live.voice.zeroToOne;
  if (words && scene.growing) {
    const t = live.voice.audio.currentTime;
    const first = words[0] - LIVE.blinkOff, last = words[words.length - 1];
    if (live.endAt === null && t >= first - LIVE.zeroHold - ringDelay() - LIVE.ringGrow && t <= last) endScene();
    if (live.endAt !== null && !live.blinks && t >= first && t <= last) {
      blinkOnWords(words.map((w) => live.clock + w - t));
    }
  }
  for (const [, strength] of heard.syllables) {
    const ray = randomRay(false);
    if (ray !== null) live.bolts.push({ start: live.clock, strength, ray, seed: Math.random() * 1000 });
    if (probing && motion > 0.5) {
      const root = randomRay(true);
      if (root !== null) {
        live.pokes.push({ start: live.clock, strength: LIVE.flick * strength, ray: root, rise: LIVE.flickRise, fall: LIVE.flickFall });
      }
    }
  }
  if (probing && motion > 0.5 && live.clock >= live.nextProbe) {
    const root = randomRay(true);
    if (root !== null) {
      live.pokes.push({ start: live.clock, strength: between(Math.random, LIVE.probe), ray: root, rise: LIVE.probeRise, fall: LIVE.probeFall });
    }
    live.nextProbe = live.clock + between(Math.random, LIVE.probeGap);
  }
  if (scene.death && live.still && live.clock >= live.nextProbe) {
    const ray = randomRay(false);
    if (ray !== null) {
      live.pokes.push({
        start: live.clock, strength: between(Math.random, LIVE.restProbe), ray,
        rise: LIVE.restProbeRise, fall: LIVE.restProbeFall,
      });
    }
    live.nextProbe = live.clock + between(Math.random, LIVE.restProbeGap);
  }
  const share = Math.min(1, scheduled(live.growth) / AXES.growthSpan);
  if (live.endAt !== null && ending.collapse >= 1 && live.strobe) {
    live.strobe = false;
    showHint();
  }
  if (scene.growing && ending.collapse < 1) {
    // The pace of the strikes: rare for long, then crowding in towards the end.
    const pace = share ** LIVE.strikeCurve;
    const rate = live.endAt !== null ? LIVE.explodeBolts : between(() => pace, LIVE.boltRate);
    if (Math.random() < rate * dt) {
      const ray = randomRay(false);
      if (ray !== null) live.bolts.push({ start: live.clock, strength: 0.6 + 0.4 * Math.random(), ray, seed: Math.random() * 1000 });
    }
    live.pulsePhase += 2 * Math.PI * between(() => share, LIVE.pulseRate) * dt;
    // The growth scene's own strobe, quickening as the network grows; S adds
    // its flashes to these. With manual strikes it is silent, and T fires
    // strikes while it is held.
    if (live.manual && live.striking) {
      while (live.nextStrike <= live.clock) {
        const flash = {
          start: live.nextStrike,
          strength: between(Math.random, LIVE.strobeStrength),
          fade: between(Math.random, LIVE.strobeFade),
        };
        live.flashes.push(flash);
        planeFlash(flash.strength, flash.fade);
        live.nextStrike += between(Math.random, LIVE.strikeGap);
      }
    }
    if (!live.manual && Math.random() < between(() => pace, LIVE.autoStrobe) * dt) {
      const fade = LIVE.strobeFadeEarly.map((v, i) => v + (LIVE.strobeFade[i] - v) * pace);
      const flash = {
        start: live.clock,
        strength: between(Math.random, LIVE.strobeStrength),
        fade: between(Math.random, fade),
      };
      live.flashes.push(flash);
      if (Math.random() < LIVE.autoPlane) planeFlash(flash.strength, flash.fade);
    }
  }
  if (live.strobe) {
    // In the growth scene the strobe grows with the network until the
    // ending: sparse and faint at first, the full strobe at full size.
    const full = scene.growing && live.endAt === null ? share ** LIVE.strobeGrowth : 1;
    const gap = LIVE.strobeGapEarly.map((v, i) => v + (LIVE.strobeGap[i] - v) * full);
    const strength = LIVE.strobeEarly + (1 - LIVE.strobeEarly) * full;
    while (live.nextFlash <= live.clock) {
      const flash = {
        start: live.nextFlash,
        strength: strength * between(Math.random, LIVE.strobeStrength),
        fade: between(Math.random, LIVE.strobeFade),
      };
      live.flashes.push(flash);
      if (scene.growing) {
        const planes = Math.round(between(Math.random, LIVE.planesPerFlash) * full);
        for (let k = 0; k < planes; k++) planeFlash(flash.strength, flash.fade);
      }
      live.nextFlash += between(Math.random, gap);
    }
  }
  live.flashes = live.flashes.filter((f) => live.clock - f.start < 6 * f.fade);
  // Once the network has collapsed, no strike outlasts it.
  if (live.endAt !== null && ending.collapse >= 1) {
    live.cascades = [];
    live.striking = false;
  }
  strikeCascades();
  // A plane has faded to 2 % after four of its fade times; its large fill is
  // dropped then.
  live.planes = live.planes.filter((f) => live.clock - f.start < 4 * f.fade);
  live.pokes = live.pokes.filter((p) => live.clock - p.start < p.rise + p.fall);
  live.bolts = live.bolts.filter((b) => live.clock - b.start < 3 + 5 * AXES.boltFade);
  live.deathAxes = live.deathAxes.filter((d) => d.leaving === null || live.clock - d.leaving < LIVE.deathRetract);
  live.clusters = live.clusters.filter((c) => {
    const kept = c.leaving === null || live.clock - c.leaving < LIVE.clusterLeave;
    if (!kept) release(c);
    return kept;
  });
  return { level: heard.level, share, motion };
}

// ---- The figure ----------------------------------------------------------------------

function windowAt(now, grown) {
  const n = AXES.dims;
  const p = new Float64Array(n), q = new Float64Array(n);
  p[0] = 1;
  q[1] = 1;
  const turn = (i, j, angle) => {
    const c = Math.cos(angle), s = Math.sin(angle);
    for (const v of [p, q]) {
      const a = v[i], b = v[j];
      v[i] = c * a - s * b;
      v[j] = s * a + c * b;
    }
  };
  for (const { i, j, wave } of space.planes) {
    turn(i, j, AXES.tilt * (AXES.tiltHidden + (1 - AXES.tiltHidden) * grown[j]) * wave(now));
  }
  turn(0, 1, AXES.spin * now);
  return { p, q };
}

function room(x, y, dx, dy) {
  const m = AXES.margin;
  const along = (pos, d, lo, hi) => (d > 1e-9 ? (hi - pos) / d : d < -1e-9 ? (lo - pos) / d : Infinity);
  return Math.max(0, Math.min(along(x, dx, m, W - m), along(y, dy, m, H - m)));
}

function flashOf(bolts, clock, dist) {
  let sum = 0;
  for (const b of bolts) {
    const x = clock - b.start - dist / AXES.boltSpeed;
    if (x <= 0) continue;
    sum += b.strength * ease(x / AXES.boltRise) * Math.exp(-Math.max(0, x - AXES.boltRise) / AXES.boltFade);
  }
  return sum;
}

function pokedAt(ray, clock) {
  let sum = 0;
  for (const p of live.pokes) if (p.ray === ray) sum += p.strength * thrust(clock - p.start, p.rise, p.fall);
  return sum;
}

// The network at the live state: its edges, each a ray out of the centre.
function figure() {
  const { now, clock } = live;
  const growth = scheduled(live.growth);
  const share = growth / AXES.growthSpan;
  // At rest the rays breathe along their length without turning; the
  // breathing fades in as the motion stops.
  const rest = 1 - tweenAt(live.motion, clock);
  const breath = (w) => 1 + LIVE.breathe * rest * w(clock);
  const n = AXES.dims;
  const grown = space.joins.map((join, j) => ease((growth - join) / space.joinLives[j]));
  const { p, q } = windowAt(now, grown);
  let sum = 0, weight = 0;
  for (let i = 0; i < n; i++) {
    sum += grown[i] * (p[i] * p[i] + q[i] * q[i]);
    weight += grown[i];
  }
  const mean = Math.sqrt(sum / weight);
  const size = AXES.twoAxisSize + (1 - AXES.twoAxisSize) * Math.min(1, share) ** AXES.sizeCurve
    + AXES.overgrowth * Math.max(0, share - 1);
  const scale = AXES.radius * size / Math.max(mean, 0.05) ** AXES.normalise;
  const halves = ease((Math.min(1, share) - AXES.halvesFirst) / (AXES.halvesLast - AXES.halvesFirst));
  const [cx, cy] = AXES.centre;
  // Every axis reaches outward with the growth.
  const outward = 1 + LIVE.outward * Math.min(share, LIVE.outwardCap) ** 2;
  const edges = [], rays = [];

  // An edge out of the centre, grown `g` of the way and lit by the bolts
  // running along it.
  const add = (angle, length, alpha, g, id) => {
    const dx = Math.cos(angle), dy = Math.sin(angle);
    const lit = live.bolts.filter((b) => b.ray === id);
    const flash = lit.length ? flashOf(lit, clock, length / 2) : 0;
    const e = { id, x: cx, y: cy, dx, dy, length, alpha, feed: g, flash };
    edges.push(e);
    return e;
  };

  for (let i = 0; i < n; i++) {
    if (grown[i] <= 0) continue;
    const projected = Math.hypot(p[i], q[i]);
    if (projected < 1e-6) continue;
    const alpha = AXES.faint + (1 - AXES.faint) * Math.min(1, projected / mean);
    for (const sign of [1, -1]) {
      const root = space.roots[2 * i + (sign > 0 ? 0 : 1)];
      const half = i < 2 ? 1 : ease((growth - root.join) / root.life);
      if (half <= 0) continue;
      const angle = Math.atan2(sign * q[i], sign * p[i]);
      const stretch = (1 + (root.bias - 1) * halves) * (1 + AXES.reach * root.reach(now));
      const nominal = scale * mean * stretch * half;
      const length = nominal * ((projected / mean) ** AXES.foreshorten + pokedAt(root.id, clock)) * breath(root.breathe) * outward;
      add(angle, length, alpha, half, root.id);
      rays.push({ id: root.id, angle, length, root: true });
    }
  }

  // The growth scene's further axes: straight lines through the centre,
  // shooting out as they join and reaching outward with the growth.
  for (const line of space.lines) {
    const g = ease((growth - line.join) / line.life);
    if (g <= 0) continue;
    const angle = line.angle + LIVE.lineDrift * line.drift(now);
    const stretch = (1 + AXES.reach * line.reach(now)) * outward * size * g;
    for (const half of [0, 1]) {
      const id = line.id + half;
      const a = angle + half * Math.PI;
      const e = add(a, AXES.radius * line.halves[half] * stretch, line.alpha, g, id);
      e.widthScale = LIVE.lineWidth;
      if (g < 1) e.flash += AXES.shootFlash * (1 - g);
      rays.push({ id, angle: a, length: e.length, root: true });
    }
  }

  // The death scene's axes: straight lines through the centre, the longer
  // half reaching to its cluster.
  for (const d of live.deathAxes) {
    const g = ease((clock - d.born) / LIVE.deathGrow)
      * (d.leaving === null ? 1 : 1 - ease((clock - d.leaving) / LIVE.deathRetract));
    if (g <= 0) continue;
    for (const [half, angle, share] of [[0, d.angle, 1], [1, d.angle + Math.PI, LIVE.deathBack]]) {
      const id = d.id + half / 2;
      const e = add(angle, d.length * share * g * breath(breathing(d.breathe)) * (1 + pokedAt(id, clock)), 1, g, id);
      rays.push({ id, angle, length: e.length, root: false });
    }
  }
  live.rays = rays;
  return { edges, size: Math.min(1, size) };
}

// ---- Drawing -----------------------------------------------------------------------------

// The drawing resolution, as a share of the view's full size. The live page
// draws at the size the view takes on the screen (the window fitted to its
// aspect ratio, times the device pixel ratio, at most full size), one pixel
// per screen pixel, so the browser never rescales it and thin lines keep
// their pixels; ?res= or LIVE.res set a fixed share instead. Every other
// mode draws at full size.
function screenRes() {
  if (mode !== "live") return 1;
  const fixed = Number(params.get("res")) || LIVE.res;
  if (fixed) return fixed;
  const [w, h] = VIEW.out;
  const shown = Math.min(innerWidth, innerHeight * w / h) * (devicePixelRatio || 1);
  return Math.min(1, shown / w);
}

// A layer of the view, `scale` of its px to a world px.
const layer = (scale) => {
  const c = offscreen(Math.round(VIEW.w * scale), Math.round(VIEW.h * scale));
  return { canvas: c, ctx: c.getContext("2d"), scale };
};
// SHARE: the share of the view's full size it is drawn at; RES: drawn px
// per world px.
let SHARE, RES, axesL, glowSourceL, glowL, bloomL, flashSourceL, flashL, washL, planesL;
const scratch = new Map();

// The layers drawn into, at `share` of the view's full size; the scratch
// layers follow on demand.
function buildLayers(share) {
  SHARE = share;
  RES = share * ZOOM;
  axesL = layer(RES);
  glowSourceL = layer(RES / 4);
  glowL = layer(RES / 4);
  bloomL = layer(RES / 8);
  flashSourceL = layer(RES / 4);
  flashL = layer(RES / 4);
  washL = layer(RES / 16);
  planesL = layer(RES / 2);
  scratch.clear();
}
buildLayers(screenRes());

// A scratch layer of the same size as `l`, for brightening it.
function boosted(l) {
  if (!scratch.has(l)) scratch.set(l, layer(l.scale));
  return scratch.get(l);
}

function tube(feed) {
  return Math.min(AXES.maxWidth, AXES.minWidth + AXES.widthGain * Math.sqrt(feed));
}

// How far a line from (x, y) along (dx, dy) runs before it leaves the view
// widened by `pad` px.
function frameReach(x, y, dx, dy, pad = 50) {
  const along = (pos, d, lo, hi) => (d > 1e-9 ? (hi - pos) / d : d < -1e-9 ? (lo - pos) / d : Infinity);
  return Math.max(0, Math.min(along(x, dx, VIEW.x - pad, VIEW.x + VIEW.w + pad),
    along(y, dy, VIEW.y - pad, VIEW.y + VIEW.h + pad)));
}

// An edge as a tapering tube with a round tip, cut off where it leaves the
// frame. The tip is a polygon of TIP_STEPS sides, not an arc, so the tube
// stays a polygon the canvas fills directly: with an arc, long edges are
// drawn through a mask the size of their bounds, which slows the frame
// several times over once many of them cross the wall.
const TIP_STEPS = 6;
function edge(c, x, y, dx, dy, length, w0, w1) {
  length = Math.min(length, frameReach(x, y, dx, dy));
  if (length < 0.5) return;
  const ex = x + dx * length, ey = y + dy * length;
  const nx = -dy, ny = dx;
  const side = Math.atan2(ny, nx);
  c.beginPath();
  c.moveTo(x + nx * w0 / 2, y + ny * w0 / 2);
  for (let k = 0; k <= TIP_STEPS; k++) {
    const a = side - Math.PI * k / TIP_STEPS;
    c.lineTo(ex + Math.cos(a) * w1 / 2, ey + Math.sin(a) * w1 / 2);
  }
  c.lineTo(x - nx * w0 / 2, y - ny * w0 / 2);
  c.closePath();
  c.fill();
}

// A point of the network at its place in the ending: widened `fill` times
// about the centre, then drawn into it as the collapse comes on (k, 0 to 1).
// Near the centre the collapse comes sooner and turns faster, like matter
// falling into a black hole. Returns the point and its local scale.
function sink(x, y, fill, k) {
  const [cx, cy] = AXES.centre;
  const dx = (x - cx) * fill, dy = (y - cy) * fill;
  if (k <= 0) return [cx + dx, cy + dy, fill];
  const inner = 900 / (Math.hypot(dx, dy) + 900);
  const p = Math.min(1, k * (1 + 0.8 * inner));
  const shrink = 1 - p * p;
  const turn = LIVE.swirl * p * p * (0.4 + inner);
  const c = Math.cos(turn), s = Math.sin(turn);
  return [cx + (dx * c - dy * s) * shrink, cy + (dx * s + dy * c) * shrink, fill * shrink];
}

// The edges of the network moved to their places in the ending.
function sunk(edges, fill, k) {
  if (fill === 1 && k <= 0) return;
  for (const e of edges) {
    const [x0, y0] = sink(e.x, e.y, fill, k);
    const [x1, y1, scale] = sink(e.x + e.dx * e.length, e.y + e.dy * e.length, fill, k);
    const length = Math.hypot(x1 - x0, y1 - y0);
    Object.assign(e, { x: x0, y: y0, dx: length > 1e-6 ? (x1 - x0) / length : e.dx, dy: length > 1e-6 ? (y1 - y0) / length : e.dy, length, widthScale: (e.widthScale || 1) * Math.max(0.15, Math.min(1, scale)) });
  }
}

// Sets a layer's context to draw in world coordinates.
function inWorld(l) {
  l.ctx.setTransform(l.scale, 0, 0, l.scale, -l.scale * VIEW.x, -l.scale * VIEW.y);
}

// Clears a layer and sets it to draw in world coordinates, pulled towards
// the centre by `pull` (1 for none).
function begin(l, pull) {
  const [cx, cy] = AXES.centre;
  l.ctx.setTransform(1, 0, 0, 1, 0, 0);
  l.ctx.clearRect(0, 0, l.canvas.width, l.canvas.height);
  l.ctx.setTransform(l.scale * pull, 0, 0, l.scale * pull,
    l.scale * (cx * (1 - pull) - VIEW.x), l.scale * (cy * (1 - pull) - VIEW.y));
  l.ctx.fillStyle = "#ffffff";
  l.ctx.strokeStyle = "#ffffff";
  l.ctx.globalAlpha = 1;
}

function blurInto(target, source, px) {
  target.ctx.setTransform(1, 0, 0, 1, 0, 0);
  target.ctx.clearRect(0, 0, target.canvas.width, target.canvas.height);
  target.ctx.filter = `blur(${px}px)`;
  target.ctx.drawImage(source.canvas, 0, 0, target.canvas.width, target.canvas.height);
  target.ctx.filter = "none";
}

// A digit centred on (cx, cy) at `scale` of its size, stroked in the
// context's stroke style: the zero a superellipse, the one a stem with a
// flag, centred on its width. Both stand LIVE.digitHeight px high, measured
// to the line's middle.
function drawDigit(c, digit, cx, cy, scale) {
  const h = LIVE.digitHeight * scale / 2;
  c.save();
  c.lineWidth = LIVE.digitWidth * scale;
  c.lineCap = "round";
  c.lineJoin = "round";
  c.beginPath();
  if (digit === "0") {
    const a = h * LIVE.digitAspect, power = 2 / LIVE.digitRound, steps = 180;
    for (let k = 0; k < steps; k++) {
      const t = 2 * Math.PI * k / steps, cos = Math.cos(t), sin = Math.sin(t);
      const x = cx + a * Math.sign(cos) * Math.abs(cos) ** power;
      const y = cy + h * Math.sign(sin) * Math.abs(sin) ** power;
      if (k) c.lineTo(x, y);
      else c.moveTo(x, y);
    }
    c.closePath();
  } else {
    const fx = 2 * h * LIVE.digitFlag[0], fy = 2 * h * LIVE.digitFlag[1];
    const stem = cx + fx / 2;
    c.moveTo(stem - fx, cy - h + fy);
    c.lineTo(stem, cy - h);
    c.lineTo(stem, cy + h);
  }
  c.stroke();
  c.restore();
}

function drawClusters() {
  const clock = live.clock;
  for (const cluster of live.clusters) {
    if (clock < cluster.appear) continue;
    const gone = cluster.leaving === null ? 0 : ease((clock - cluster.leaving) / LIVE.clusterLeave);
    cluster.clips.forEach((c, k) => {
      // A clip plays as a video, or where the view draws clips small, from
      // its frame sheet.
      const { video } = c;
      const { sheet } = clipFiles[c.file];
      const start = cluster.appear + k * AXES.clipIn;
      const shrunk = ease((clock - start - AXES.clipLargeFor) / AXES.clipShrink);
      const scale = (AXES.clipLarge + (1 - AXES.clipLarge) * shrunk) * (1 - gone);
      const w = AXES.clipWidth * scale;
      const h = w * (sheet ? sheet.cell[1] / sheet.cell[0] : video.videoWidth ? video.videoHeight / video.videoWidth : 9 / 16);
      // Spread around the cluster in proportion to its size, and kept in the world.
      const x = Math.min(Math.max(cluster.x + c.dx * scale, w / 2), WORLD_W - w / 2);
      const y = Math.min(Math.max(cluster.y + c.dy * scale, h / 2), H - h / 2);
      // Only the clips in this page's view play; the others rest.
      const seen = clock >= start && scale > 0.01
        && x + w > VIEW.x && x - w < VIEW.x + VIEW.w && y + h > VIEW.y && y - h < VIEW.y + VIEW.h;
      if (!seen) {
        if (video && !video.paused) video.pause();
        return;
      }
      // The picture to draw and its part: the sheet's frame at the clip's time, or the video.
      let image, part;
      if (sheet) {
        const [cw, ch] = sheet.cell;
        const n = Math.floor((clock - start) * sheet.fps) % sheet.frames;
        image = sheet.image;
        part = [(n % sheet.columns) * cw, Math.floor(n / sheet.columns) * ch, cw, ch];
      } else {
        playFrom(video, clock - start);
        if (video.readyState < 2 || !video.videoWidth) return;
        image = video;
        part = [0, 0, video.videoWidth, video.videoHeight];
      }
      ctx.save();
      ctx.translate(x, y);
      ctx.rotate(c.tilt);
      ctx.globalAlpha = AXES.clipAlpha;
      if (AXES.clipGrey) ctx.filter = "grayscale(1)";
      ctx.drawImage(image, ...part, -w / 2, -h / 2, w, h);
      ctx.filter = "none";
      ctx.restore();
    });
  }
}

function drawLive({ level, share }) {
  const { edges, size } = figure();
  const [cx, cy] = AXES.centre;
  const clock = live.clock;
  const phase = 2 * Math.PI * live.now / AXES.pulsePeriod;
  const pull = tweenAt(live.regrow, clock);
  const ring = tweenAt(live.ring, clock);
  const ending = endingOf(clock);
  const fill = 1 + (LIVE.explodeSize - 1) * ease(ending.explode);
  sunk(edges, fill, ending.collapse);
  const hub = AXES.hub[0] + (AXES.hub[1] - AXES.hub[0]) * Math.max(0, (size - AXES.twoAxisSize) / (1 - AXES.twoAxisSize));

  // How far the explosion floods the wall: all the way while it explodes,
  // easing off as the collapse begins. The sharp lines fade out with it.
  const flood = ease(ending.explode) * (1 - ease(2 * ending.collapse));
  const sharp = 1 - flood > 0.02;
  // How far the growth scene's look has come in: the glow shaded as metal,
  // the core in place of the hub's disc.
  const metal = tweenAt(live.look, clock);
  // The strobe's flashes as they stand: they blaze in the metal's glints.
  let blaze = 0;
  for (const f of live.flashes) {
    const x = clock - f.start;
    if (x >= 0) blaze += f.strength * Math.exp(-x / f.fade);
  }
  // The growth scene's glow, rising with the growth.
  const grownNow = Math.min(1, share);
  const glowWide = 1 + (between(() => grownNow, LIVE.glowWidth) - 1) * metal;
  const glowBoost = 1 + (between(() => grownNow, LIVE.lineGlow) - 1) * metal;
  const base = css(metalRGB(WHITE, 0.75, metal));
  const c = axesL.ctx, g = glowSourceL.ctx, fl = flashSourceL.ctx, pl = planesL.ctx;
  for (const l of [axesL, glowSourceL, flashSourceL, planesL]) begin(l, Math.max(pull, 1e-3));
  let hubWidth = 0;     // the summed width of the lines where they leave the centre
  // The narrowest sharp line in world px: LIVE.minLinePx drawn pixels. A
  // line thinner than a pixel or so switches the pixels it crosses on and
  // off as it moves; drawn at this width and dimmed in proportion it gives
  // the same light and moves smoothly.
  const minLine = LIVE.minLinePx / RES;
  if (pull > 0.002 && ending.collapse < 1) {
    for (const e of edges) {
      const ws = e.widthScale || 1;
      const w0 = tube(e.feed) * ws, w1 = w0 * AXES.taperTip;
      const mid = e.length / 2;
      if (LIVE.chrome > 0) {
        // The line in chrome: a gradient along its visible part, shaded at
        // each stop. The glow takes the shade of the line's middle, darkened
        // by it but never brighter than white; outside the growth scene it
        // keeps its full light.
        const angle = Math.atan2(e.dy, e.dx);
        const seen = Math.min(e.length, frameReach(e.x, e.y, e.dx, e.dy));
        if (seen >= 0.5) {
          if (sharp) {
            const stops = Math.min(LIVE.metalStops, Math.max(2, Math.ceil(4 * seen / LIVE.bandLength) + 1));
            const grad = c.createLinearGradient(e.x, e.y, e.x + e.dx * seen, e.y + e.dy * seen);
            for (let k = 0; k < stops; k++) {
              const t = k / (stops - 1);
              grad.addColorStop(t, css(metalRGB(WHITE, sheen(angle, t * seen, live.now, clock, blaze), LIVE.chrome)));
            }
            c.fillStyle = grad;
          }
          const lit = 1 + (Math.min(1.2, sheen(angle, mid, live.now, clock, blaze)) - 1) * metal;
          g.fillStyle = fl.fillStyle = css(WHITE.map((v) => v * (1 - (1 - Math.min(1, lit)) * LIVE.chrome)));
        }
      }
      hubWidth += w0;
      if (sharp) {
        const thin = Math.min(1, (w0 + w1) / 2 / minLine);
        c.globalAlpha = thin;
        edge(c, e.x, e.y, e.dx, e.dy, e.length, w0 / thin, w1 / thin);
      }
      const pulse = 1 - AXES.pulse * (0.5 + 0.5 * Math.sin(phase - 2 * Math.PI * mid / AXES.pulseLength));
      g.globalAlpha = Math.min(1, e.alpha * pulse + e.flash);
      edge(g, e.x, e.y, e.dx, e.dy, e.length, w0 * glowWide, w1 * glowWide);
      if (e.flash > 0.01) {
        fl.globalAlpha = Math.min(1, e.flash);
        edge(fl, e.x, e.y, e.dx, e.dy, e.length, 1.5 * w0, 1.5 * w1);
      }
    }
    c.globalAlpha = 1;
    // The planes the flashes light, spanned by their axes as they stand now
    // and moved with the network in the ending.
    const raysById = new Map(live.rays.map((r) => [r.id, r]));
    c.fillStyle = g.fillStyle = pl.fillStyle = base;
    for (const f of live.planes) {
      const alpha = Math.min(1, LIVE.planeAlpha * f.strength * Math.exp(-(clock - f.start) / f.fade));
      const rays = f.rays.map((id) => raysById.get(id)).filter(Boolean);
      if (alpha < 0.004 || rays.length < 2) continue;
      const corners = spanned(rays.map((r) => [r.length * Math.cos(r.angle), r.length * Math.sin(r.angle)]))
        .map(([x, y]) => sink(cx + x, cy + y, fill, ending.collapse));
      for (const [l, a] of [[pl, alpha], [g, alpha * LIVE.planeGlow]]) {
        l.globalAlpha = a;
        l.beginPath();
        corners.forEach(([x, y], k) => (k ? l.lineTo(x, y) : l.moveTo(x, y)));
        l.closePath();
        l.fill();
      }
    }
    // The hub's disc, giving way to the core in the growth scene.
    for (const l of [c, g]) {
      if (metal >= 1) break;
      l.globalAlpha = 1 - metal;
      l.beginPath();
      l.arc(cx, cy, hub * fill * (1 - ending.collapse), 0, 2 * Math.PI);
      l.fill();
    }
  }
  // The zero opening out of the centre, which blinks into a one. The digits
  // stay steady: they open with the ring and do not follow the voice.
  const digit = digitAt(clock);
  if (ring > 0.001 && digit) {
    for (const l of [axesL, glowSourceL]) {
      inWorld(l);
      l.ctx.globalAlpha = Math.min(1, ring * 1.5) * (l === glowSourceL ? LIVE.digitGlow : 1);
      l.ctx.strokeStyle = base;
      drawDigit(l.ctx, digit, cx, cy, ring);
    }
  }

  blurInto(glowL, glowSourceL, AXES.glowBlur * RES);
  blurInto(bloomL, glowL, AXES.bloomBlur * RES);
  blurInto(flashL, flashSourceL, AXES.boltBlur * RES);
  if (flood > 0) blurInto(washL, bloomL, LIVE.washBlur * RES);

  // The glow strengthens as the network grows, rises with the voice, pulses
  // ever faster in the growth scene and surges as the network explodes and
  // is sucked into the centre.
  const grownShare = Math.min(1, share);
  const pulseDepth = sceneOf().growing ? between(() => grownShare, LIVE.pulseDepth) : 0;
  const surge = 0.8 * ease(ending.explode) * (1 - ending.collapse) + 1.5 * Math.sin(Math.PI * ending.collapse);
  // The strobe flickers the glow; in the growth scene the glow rests low
  // and lives on its flashes.
  let flicker = live.strobe ? LIVE.strobeBase + blaze : 1;
  if (metal > 0) flicker += (between(() => grownNow, LIVE.strobeRest) + blaze - flicker) * metal;
  const flickering = live.strobe || metal > 0;
  // Over the collapse the glow settles: it stops following the voice, the
  // pulse and the strobe, so the light around the new shape is still.
  const settle = ease(ending.collapse);
  flicker += (1 - flicker) * settle;
  const lift = (1 + AXES.levelGlow * level * (1 - settle))
    * (1 + pulseDepth * (0.5 + 0.5 * Math.sin(live.pulsePhase)) * (1 - settle)) * (1 + surge) * flicker;
  const strength = Math.max(grownShare, ring);
  const lerp = ([a, b]) => a + (b - a) * strength;
  // A layer added `amount` times over, so the glow can rise beyond one
  // pass: brightened at its own size, then drawn onto the frame once.
  const addLayer = (l, amount) => {
    if (amount <= 0.001) return;
    let source = l.canvas;
    if (amount > 1) {
      const b = boosted(l);
      b.ctx.globalCompositeOperation = "copy";
      b.ctx.globalAlpha = 1;
      b.ctx.drawImage(l.canvas, 0, 0);
      b.ctx.globalCompositeOperation = "lighter";
      for (let left = Math.min(amount, 4) - 1; left > 0.001; left -= 1) {
        b.ctx.globalAlpha = Math.min(1, left);
        b.ctx.drawImage(l.canvas, 0, 0);
      }
      source = b.canvas;
    }
    ctx.globalAlpha = Math.min(1, amount);
    ctx.drawImage(source, VIEW.x, VIEW.y, VIEW.w, VIEW.h);
  };

  ctx.setTransform(RES, 0, 0, RES, -RES * VIEW.x, -RES * VIEW.y);
  ctx.globalAlpha = 1;
  ctx.fillStyle = "#000000";
  ctx.fillRect(VIEW.x, VIEW.y, VIEW.w, VIEW.h);
  ctx.globalCompositeOperation = "lighter";
  addLayer(bloomL, lerp(AXES.bloom) * lift * glowBoost);
  addLayer(glowL, flickering ? lerp(AXES.glow) * lift * glowBoost : Math.min(1, lerp(AXES.glow) * lift));
  if (live.planes.length) addLayer(planesL, 1);
  addLayer(flashL, AXES.boltGlow * (flickering ? flicker : 1));
  if (flood > 0) addLayer(washL, LIVE.explodeWash * flood * flicker);
  ctx.globalCompositeOperation = "source-over";
  if (sharp) {
    ctx.globalAlpha = 1 - flood;
    ctx.drawImage(axesL.canvas, VIEW.x, VIEW.y, VIEW.w, VIEW.h);
    ctx.globalAlpha = 1;
  }
  // The growth scene's core: white light at the centre the axes grow out
  // of, fading without an edge, larger and brighter as the network grows,
  // with a wide halo lighting the wall, and the heart where the lines
  // merge. It sinks into the centre with the collapse.
  const core = metal * (1 - ending.collapse) * pull;
  if (core > 0.002) {
    const swell = 1 + LIVE.coreVoice * level + LIVE.coreFlash * Math.min(2, blaze);
    const r = between(() => grownNow ** LIVE.coreCurve, LIVE.coreRadius) * fill * swell;
    const halo = between(() => grownNow, LIVE.haloRadius) * fill * swell;
    // A radial glow in white, its stops [t, alpha].
    const glowAt = (radius, stops, alpha) => {
      const grad = ctx.createRadialGradient(cx, cy, 0, cx, cy, radius);
      for (const [t, a] of stops) grad.addColorStop(t, `rgba(255,255,255,${a})`);
      ctx.globalAlpha = Math.min(1, alpha);
      ctx.fillStyle = grad;
      ctx.fillRect(cx - radius, cy - radius, 2 * radius, 2 * radius);
    };
    ctx.globalCompositeOperation = "lighter";
    glowAt(halo, [[0, 1], [0.25, 0.55], [0.6, 0.15], [1, 0]],
      between(() => grownNow, LIVE.haloAlpha) * (1 + LIVE.haloFlash * Math.min(2, blaze)) * core);
    glowAt(r, [[0, 0.8], [0.25, 0.55], [0.6, 0.18], [1, 0]],
      between(() => grownNow, LIVE.coreGlow) * core);
    // The heart: out to the radius where the lines' widths fill the
    // circumference they cross, they overlap into one light. Its light
    // falls off as a bell curve with no rim.
    const merged = LIVE.heartSpread * hubWidth / (2 * Math.PI) * fill * (1 + 0.5 * (swell - 1));
    if (merged > 1) {
      const reach = merged * LIVE.heartFade;
      const stops = [];
      for (let k = 0; k <= 12; k++) {
        const t = k / 12;
        const x = t * reach / (LIVE.heartWidth * merged);
        stops.push([t, k === 12 ? 0 : Math.exp(-x * x)]);
      }
      glowAt(reach, stops, core);
    }
    ctx.globalCompositeOperation = "source-over";
    ctx.globalAlpha = 1;
  }
  // The white wall between the explosion and the collapse.
  if (ending.white > 0.001) {
    ctx.globalCompositeOperation = "lighter";
    ctx.globalAlpha = Math.min(1, ending.white);
    ctx.fillStyle = "#ffffff";
    ctx.fillRect(VIEW.x, VIEW.y, VIEW.w, VIEW.h);
    ctx.globalCompositeOperation = "source-over";
    ctx.globalAlpha = 1;
  }
  drawClusters();
}

// ---- Loading and modes ---------------------------------------------------------------------

async function loadLive() {
  const clips = await fetch("/clips.json");
  if (clips.ok) {
    for (const c of await clips.json()) {
      // A view that draws the clips at less than half their size (the
      // strip) draws them from their frame sheets, the others play them.
      if (ZOOM < 0.5 && c.sheet) {
        const res = await fetch(c.sheet.src);
        if (res.ok) clipFiles.push({ sheet: { ...c.sheet, image: await createImageBitmap(await res.blob()) }, group: c.group });
      } else {
        const res = await fetch(c.src);
        if (res.ok) clipFiles.push({ url: URL.createObjectURL(await res.blob()), group: c.group });
      }
    }
    clipFiles.splice(0, clipFiles.length, ...mixedOrder(clipFiles));
  }
  // A follower plays no sound: the voices' level reaches it with the state.
  const list = FOLLOW ? null : await fetch("/voices.json");
  if (list && list.ok) {
    for (const v of await list.json()) {
      const analysis = await (await fetch(v.analysis)).json();
      const audio = new Audio(v.audio);
      audio.preload = "auto";
      voices.push({ name: v.name, audio, analysis, zeroToOne: v.zeroToOne || null });
    }
  }
}

// The state a conducting page sends its followers each frame: the
// performance without its sound and videos, and the voice's level and the
// growth handed to drawLive.
function snapshot(heard) {
  const { voice, rays, cascades, clusters, ...rest } = live;
  return {
    ...rest,
    heard,
    clusters: clusters.map(({ clips, ...cluster }) => ({
      ...cluster,
      clips: clips.map(({ video, ...clip }) => clip),
    })),
  };
}

// The follower's own videos of the clusters' clips, by cluster and clip.
const followedVideos = new Map();

// Takes on a conductor's state: the performance as it stands, with the
// follower's own videos for the clusters' clips (drawClusters plays them in
// step). Returns what drawLive is handed.
function adopt(state) {
  const { heard, clusters, ...rest } = state;
  Object.assign(live, rest);
  const shown = new Set();
  live.clusters = clusters.map((cluster) => ({
    ...cluster,
    clips: cluster.clips.map((clip, k) => {
      const file = clipFiles[clip.file];
      if (!file.url) return { ...clip, video: null };
      const key = `${cluster.id}:${k}`;
      shown.add(key);
      if (!followedVideos.has(key)) followedVideos.set(key, clipVideo(file.url));
      return { ...clip, video: followedVideos.get(key) };
    }),
  }));
  for (const [key, video] of followedVideos) {
    if (shown.has(key)) continue;
    stopVideo(video);
    followedVideos.delete(key);
  }
  return heard;
}

// A follower: draws its view of the latest state the conductor has sent.
function follow() {
  const hint = document.querySelector(".hint");
  if (hint) hint.style.display = "none";
  let latest = null, heard = { level: 0, share: 0 };
  if (CHANNEL) CHANNEL.onmessage = (e) => { latest = e.data; };
  const tick = () => {
    if (latest) {
      heard = adopt(latest);
      latest = null;
    }
    drawLive(heard);
    requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
}

// The live page: the view follows the performance, drawn as fast as the
// machine allows. It conducts, or with ?follow follows a page conducting.
function runLive() {
  // The view follows the window, so going fullscreen or moving to another
  // screen redraws it at that screen's resolution.
  const fit = () => {
    const share = screenRes();
    if (share !== SHARE) buildLayers(share);
    canvas.width = Math.round(VIEW.out[0] * SHARE);
    canvas.height = Math.round(VIEW.out[1] * SHARE);
  };
  fit();
  addEventListener("resize", fit);
  if (FOLLOW) {
    follow();
    return;
  }
  addEventListener("keydown", onKey);
  // Letting go of T ends the strikes, the cascade with them.
  addEventListener("keyup", (e) => {
    if (e.code !== "KeyT" || !live.striking) return;
    live.striking = false;
    live.cascades = [];
  });
  enter(0);
  let last = performance.now();
  const tick = (ms) => {
    const dt = Math.min(0.1, Math.max(0, (ms - last) / 1000));
    last = ms;
    const heard = update(dt);
    drawLive(heard);
    if (CHANNEL) CHANNEL.postMessage(snapshot(heard));
    requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
}

buildSpace();

registerDesign({
  load: loadLive,
  live: runLive,
  // Outside the live page the frame shows the first scene at rest.
  draw: () => {
    ctx.save();
    drawLive({ level: 0, share: 0 });
    ctx.restore();
  },
});
