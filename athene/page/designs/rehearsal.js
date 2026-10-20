/* Rehearsal: Athene's scenes of the play, performed live from the keyboard.

   The network, webs, glow and clusters of the fourth axes design
   (designs/axes4.js), driven by the scenes of athene/description.md instead
   of a clip's timeline. Served by athene/live.py with the voice clips of the
   scenes and the clip groups of the clusters.

     1  two axes      the two axes of the coordinate system move and probe:
                      they reach out on their own and on every syllable.
     2  death scene   the axes move and probe until the first cluster key;
                      then they come to rest and only breathe along their
                      length. Each cluster key places a cluster of clips
                      somewhere on the wall, apart from the others, and grows
                      a new axis out of the centre to it: rehearsal footage
                      (R) or online footage (O). The clips play as looping
                      videos.
     3  two axes      the death scene's axes and clusters draw back, and the
                      two axes move and probe again.
     4  growth        the network grows ever more axes and branches, faster
                      and faster, to its full size and on until the ending,
                      with a pulse of light that quickens as it grows. More
                      and more arms shoot out like lightning instead of
                      creeping, at speeds of their own, and many of these
                      vanish again. E ends it: the network explodes in a
                      flickering strobe until it fills the wall, is sucked
                      into the centre like a star into a black hole, and a
                      glowing circle opens out of it. S makes the glow
                      flicker like lightning.
        straight      V switches the growth scene to its straight variant
                      and back: the branches draw back into their axes, and
                      ever more straight axes through the centre join, ever
                      faster, until they fill the wall and reach out beyond
                      it, out of a glowing core that grows with them. The
                      lines are metal, chrome turning to red as they grow,
                      and glow with a strobe of their own, rare for long
                      and crowding in at the end (S: the full strobe); some
                      flashes light the plane two or three axes span. E ends it in
                      a zero instead of the circle, and 0 makes the zero
                      blink four times and come back as a one.

   Keys: N next scene, B previous scene, Space restart the scene, P play the
   scene's next voice clip (or stop the one playing), H show or hide the
   help line. Changing scene stops the voice and animates the network into
   the new scene's state.

   The voice lights the network in every scene: each syllable sends a bolt
   of light from the hub out along one ray, and the glow rises with the
   level. The live page draws at the resolution the frame takes on the
   screen, one pixel per screen pixel; `LIVE.res` or ?res= set a fixed share
   of 3840 × 2160 instead.

   AXES holds the parameters of the network, SCENES and LIVE those of the
   performance. */

"use strict";

const AXES = {
  dims: 56,             // dimensions of the space: the axes of the growth scene
  radius: 1000,         // px, half-length of an axis at full size
  centre: [W / 2, H / 2],
  margin: 70,
  hub: [10, 22],        // px, radius of the hub with two axes and at full size

  // Growth (scene 4): `growthSpan` seconds to full size and the full
  // schedule of axes and forks; it keeps growing beyond, at `overgrowth` of
  // full size per span. The schedule runs on a clock that speeds up: after
  // a share x of the span it stands at x ^ `accelerate`, so the growth
  // quickens towards the end. Growth times below are in that clock's seconds.
  growthSpan: 300, accelerate: 1.8, overgrowth: 0.25,
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
  // Creeping edges grow out within `creepLife` seconds, their pace uneven.
  creepLife: [1.5, 12], creepSurge: 0.35,
  // Lightning: of the edges born at a point of the schedule, a share rising
  // from shootShare[0] at its start to [1] at its end shoots out within
  // `shootLife` seconds and forks again within `shootWait`, flashing while
  // it grows; `shootDie` of these vanish again after `shootStay` seconds,
  // within `shootFade`.
  shootShare: [0.1, 0.9], shootLife: [0.06, 1.2], shootWait: [0.025, 1.2],
  shootDie: 0.45, shootStay: [0.3, 4], shootFade: [0.2, 1.2], shootFlash: 0.9,

  branchFirst: 0.06, branchLast: 0.8,
  branchDepth: 6,
  forkChance: [0.95, 0.85, 0.75, 0.65, 0.5, 0.35],
  sideForkShare: 0.6, threeWay: 0.35,
  carryLength: [0.6, 0.95], sideLength: [0.45, 0.8],
  carryKink: 0.3, sideAngle: [0.55, 1.15],
  sway: 0.15, forkWait: [1, 12],
  dieShare: 0.25, dieAfter: [15, 50], dieLife: 6,

  // Tubes: width in px is minWidth + widthGain × √(edges fed), at most maxWidth.
  minWidth: 3, widthGain: 2.6, maxWidth: 12, taperTip: 0.6, faint: 0.45,
  webSpan: 1.9, webGain: 5, webLife: 35, webMax: 150, webShare: 0.4, webBow: 0.3,
  pulse: 0.22, pulsePeriod: 7, pulseLength: 1400,
  glow: [0.45, 1.0], glowBlur: 7, bloom: [0.1, 0.85], bloomBlur: 10,

  boltSpeed: 3500, boltFork: 0.5, boltRise: 0.03, boltFade: 0.22,
  boltGlow: 1.0, boltBlur: 3, levelGlow: 0.3,

  clipWidth: 280,       // px once settled; the height follows the clips' aspect ratio
  clipsPerCluster: 16,
  clipScatter: 480, clipTilt: 0.1, clipIn: 0.05, clipAlpha: 0.92,
  clipLarge: 1.6, clipLargeFor: 8, clipShrink: 1.5,
  clipGrey: false,
};

// The scenes: their voice clips (by the start of their file names, played
// in this order), whether the network moves, whether the axes probe, and
// whether it grows. The death scene moves and probes until its first
// cluster.
const SCENES = [
  { name: "ZWEI ACHSEN", voices: ["athene_1", "athene_2"], motion: 1, probing: true },
  { name: "TODESSZENE", voices: ["athene_3", "athene_4", "athene_5"], motion: 1, probing: true, death: true },
  { name: "WIEDER ZWEI ACHSEN", voices: ["athene_6"], motion: 1, probing: true },
  { name: "WACHSTUM", voices: ["athene_7", "athene_8"], motion: 1, growing: true },
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
  breathe: 0.08, breatheRate: 0.6,
  // Clusters: placed at the best of `placeTries` random points, the one
  // furthest from the other clusters, at least `placeHub` px from the hub.
  placeTries: 40, placeHub: 550,
  clusterLeave: 0.8,
  // Growth scene: bolts on their own per second, and a pulse of the glow in
  // Hz with its depth, from the start to the full schedule; the motion
  // speeds up to 1 + `hectic` times at full size.
  boltRate: [0.15, 8], pulseRate: [0.2, 3.5], pulseDepth: [0, 0.9], hectic: 1.5,
  // Ending: for `explode` seconds the network explodes, the strobe on and
  // `explodeBolts` bolts per second, its growth sped up to `explodeGrowth`
  // times and its size rising to `explodeSize` times. Then within `collapse`
  // seconds it is sucked into the centre, faster and faster, the parts near
  // the centre first and turning up to `swirl` radians. The circle (radius
  // and line width in px) opens within `ringGrow` seconds as it vanishes.
  // While it explodes, the flickering glow floods the wall through a wide
  // wash (`explodeWash` times, blurred `washBlur` px at a sixteenth of the
  // resolution), and the sharp lines fade out, leaving the glow. Over its
  // last `whiteRise` seconds the light rises to a white wall, which holds for
  // `whiteHold` seconds before the collapse and fades over its first
  // `whiteFade` seconds.
  explode: 6, explodeBolts: 14, explodeGrowth: 25, explodeSize: 2.2,
  explodeWash: 3, washBlur: 14,
  whiteRise: 1.5, whiteHold: 4, whiteFade: 0.8,
  collapse: 3.5, swirl: 4, ringRadius: 700, ringWidth: 16, ringGrow: 3,
  // Strobe: flashes of the glow at irregular gaps (s), of random strength,
  // each fading with a time constant (s); between flashes the glow sinks to
  // `strobeBase` of its strength.
  strobeGap: [0.03, 0.28], strobeStrength: [0.5, 2.5], strobeFade: [0.03, 0.12], strobeBase: 0.25,

  // Straight variant of the growth scene (V): the branches draw back within
  // `branchFade` seconds and `lines` further axes join through the centre.
  // They join between these shares of the schedule, the count rising as the
  // schedule's share to the power 1 / `lineCurve`, each within `lineLife`
  // seconds (the first to the last), flashing while it shoots out. An axis
  // is `lineLength` of AXES.radius long and drifts up to `lineDrift` radians;
  // every axis reaches out to 1 + `outward` × share² times its length, so by
  // full size most run beyond the wall. Their tubes are `lineWidth` of the
  // network's and lit at `lineAlpha`.
  branchFade: 1.5,
  lines: 300, lineFirst: 0.05, lineLast: 1.1, lineCurve: 0.5, lineLife: [4, 0.25],
  lineLength: [0.35, 1.1], lineDrift: 0.12, lineDriftRate: [0.03, 0.12],
  outward: 2.5, outwardCap: 1.6, lineWidth: 0.5, lineAlpha: [0.35, 1],
  // Glow by strobe: in the straight variant the glow rests at `strobeRest`
  // (from the start to full size, as the strobe takes over) and blazes with
  // each flash of a strobe that runs on its own,
  // `autoStrobe` flashes a second from the start to the full schedule, or
  // at the strobe's gaps with S. Its flashes and the bolts along the lines
  // follow the schedule's share to the power `strikeCurve`, so they stay
  // rare for long and crowd in towards the end; a flash fades within
  // `strobeFadeEarly` at the start and `strobeFade` at full size.
  autoStrobe: [0.1, 14], strikeCurve: 3, strobeFadeEarly: [0.08, 0.2], strobeRest: [1, 0.5],
  // With S, the straight variant's strobe follows the share to the power
  // `strobeGrowth` until the ending: gaps of `strobeGapEarly` seconds and
  // `strobeEarly` of the flashes' strength at the start, the full strobe
  // (strobeGap, strobeStrength) at full size.
  strobeGrowth: 1.5, strobeGapEarly: [0.4, 1.4], strobeEarly: 0.3,
  // Core: in the straight variant a glowing core takes the place of the
  // hub's disc, `coreRadius` px from the start to full size (following the
  // share to the power `coreCurve`) at `coreGlow` brightness, swelling with
  // the voice (`coreVoice`) and the strobe (`coreFlash`); its heart is the
  // colour whitened by `coreHeat`. Around it a halo of the colour lights
  // the wall out to `haloRadius` px at `haloAlpha` from the start to full
  // size, brightening by `haloFlash` with the strobe.
  coreRadius: [0, 900], coreCurve: 1.2, coreGlow: [0, 1], coreVoice: 0.12, coreFlash: 0.15, coreHeat: 0.8,
  haloRadius: [0, 2200], haloAlpha: [0, 0.45], haloFlash: 0.25,
  // Heart: within the radius where the lines' widths at the centre add up
  // to its circumference (their summed width / 2π, times `heartSpread`)
  // they merge into white light, falling off as a bell curve `heartWidth`
  // times that radius wide, out to `heartFade` times it. It grows with
  // every line that joins, from nothing.
  heartSpread: 1, heartWidth: 0.8, heartFade: 2.6,
  // The lines' glow in the straight variant, from the start to full size:
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
  // 1) from `metalDark` through `metalMid` of its colour to its colour
  // whitened by `metalSheen`, after the satin chrome of the liquid design.
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
  // Its ending opens a zero, `digitHeight` px high in `digitFont`, instead
  // of the circle. Key 0 makes it blink `blinks` times (`blinkOff` dark,
  // `blinkOn` lit, in seconds); it comes back from the last blink as a one.
  digitHeight: 1100, digitFont: "Michroma", blinks: 4, blinkOff: 0.2, blinkOn: 0.35,
  // Its colour lives in the glow; the lines themselves stay chrome. The glow
  // is white until `redStart` of the growth's time; then a front of red runs
  // out along every line from the centre to its tip by the end of the
  // schedule, `redSoft` of the line's length deep. Where red, the glow
  // shimmers: two waves of light, `shimmerLength` px and 0.37 of that
  // long, run out along it at `shimmerSpeed` radians a second, brightening
  // and darkening it by up to `shimmer`. A glow gradient has a stop every
  // quarter wave, at most `shimmerStops`. Each edge turns to a red of its
  // own between `red[0]` and `red[1]` (RGB), its front up to `redLag` of
  // the schedule behind the others, so the front is uneven. The core and
  // the hub take the middle of the range at the centre, the
  // planes at `redPlanes` of the way out.
  red: [[200, 0, 15], [230, 10, 20]], redLag: 0.15, redSoft: 0.25, redPlanes: 0.3,
  redStart: 0.35, shimmer: 0.6, shimmerLength: 500, shimmerSpeed: 3, shimmerStops: 10,
  colourFade: 1.5,      // seconds C takes to turn the colour off or on
  // Manual strikes (L switches from automatic): the strobe's own flashes and
  // plane strikes stop, and holding T fires strikes `strikeGap` seconds
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

function hash(a, b) {
  const x = Math.sin(a * 12.9898 + b * 78.233) * 43758.5453;
  return x - Math.floor(x);
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

// How red edge `id` (null for the middle of the range) has turned `u` of
// the way from the centre to its tip, when the red front has come `p` of
// the way, all 0 to 1.
function redAt(id, p, u = 0) {
  const lag = LIVE.redLag * (id === null ? 0.5 : hash(id, 3.7));
  const front = (p - lag) / (1 - LIVE.redLag) * (1 + LIVE.redSoft);
  return ease((front - u) / LIVE.redSoft);
}

// The straight variant's colour there, as [r, g, b].
function tint(id, p, u = 0) {
  const k = redAt(id, p, u);
  const s = id === null ? 0.5 : hash(id, 9.1);
  const [lo, hi] = LIVE.red;
  return lo.map((v, i) => 255 + (v + (hi[i] - v) * s - 255) * k);
}

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

// The cluster clips ({url, group}, played as videos) and the voice clips with
// their analyses.
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
  let ids = 0;
  // The edges of a fork at the end of an edge grown at `after`; `fast` when
  // that edge shot out.
  const forks = (depth, after, side, fast) => {
    const chance = AXES.forkChance[depth] * (side ? AXES.sideForkShare : 1);
    if (depth >= AXES.branchDepth || random() > chance) return [];
    const count = random() < AXES.threeWay ? 3 : 2;
    const birth = depth === 0
      ? Math.max(after, between(random, [AXES.branchFirst, AXES.branchLast]) * span)
      : after + between(random, fast ? AXES.shootWait : AXES.forkWait);
    const firstSide = random() < 0.5 ? 1 : -1;
    const edges = [];
    for (let k = 0; k < count; k++) {
      const carry = k === 0;
      const turn = carry
        ? AXES.carryKink * (2 * random() - 1)
        : (k === 1 ? firstSide : -firstSide) * between(random, AXES.sideAngle);
      const edgeBirth = birth + (fast ? 0.2 : 1.5) * k * random();
      const shooter = random() < between(() => Math.min(1, edgeBirth / span), AXES.shootShare);
      const creep = between(random, shooter ? AXES.shootLife : AXES.creepLife);
      const dies = shooter ? random() < AXES.shootDie : !carry && depth > 0 && random() < AXES.dieShare;
      edges.push({
        id: ids++,
        birth: edgeBirth,
        creep,
        shooter,
        death: dies ? edgeBirth + creep + between(random, shooter ? AXES.shootStay : AXES.dieAfter) : Infinity,
        fade: shooter ? between(random, AXES.shootFade) : AXES.dieLife,
        carry, turn,
        length: between(random, carry ? AXES.carryLength : AXES.sideLength),
        sway: wave(random, AXES.reachRate),
        stretch: wave(random, AXES.reachRate),
        surge: wave(random, 0.5),
        forks: forks(depth + 1, edgeBirth + creep, !carry, shooter),
      });
    }
    return edges;
  };
  space.roots = [];
  for (let h = 0; h < 2 * n; h++) {
    const join = space.joins[h >> 1] + between(random, AXES.halfDelay);
    const life = space.joinLives[h >> 1] / between(random, AXES.halfPace);
    space.roots.push({
      id: ids++,
      join, life,
      bias: between(random, AXES.halves),
      reach: wave(random, AXES.reachRate),
      breathe: wave(random, LIVE.breatheRate),
      forks: forks(0, join + life, false, false),
    });
  }
  // The straight variant's further axes, in the order they join.
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
  deathAxes: [],        // {id, angle, length, born, leaving, breathe}
  clusters: [],         // {x, y, appear, leaving, clips}
  still: false,         // the death scene has come to rest
  nextClip: new Map(),  // per clip group, the next clip to use
  regrow: tween(1),     // the network growing back out of the centre after the ending
  ring: tween(0),
  endAt: null,          // the clock when E was pressed
  strobe: false,
  flashes: [],          // the strobe's flashes: {start, strength, fade}
  nextFlash: 0,
  straight: false,      // the growth scene's straight variant
  manual: false,        // the straight variant's strikes fired by hand (T) instead of on their own
  striking: false,      // T is held
  nextStrike: 0,        // the clock of the next strike while T is held
  colour: true,         // the straight variant turns red (false: it stays white)
  colourMix: tween(1),  // 1 in colour, 0 in white, easing between them
  branching: tween(1),  // 1 with the branches grown, 0 in the straight variant
  planes: [],           // the planes lit: {start, strength, fade, rays}
  cascades: [],         // strikes in succession: {anchor, used, left, next}
  blinkAt: null,        // the clock when 0 was pressed
  queue: 0,             // the scene's next voice clip
  voice: null,          // {audio, analysis, last}
  rays: [],             // the rays of the last frame: {id, angle, length, root}
  hint: true,
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
  for (const d of live.deathAxes) if (d.leaving === null) d.leaving = live.clock;
  for (const c of live.clusters) if (c.leaving === null) c.leaving = live.clock;
  live.still = false;
  live.growthMode = scene.growing ? "restart" : "rewind";
  if (live.endAt !== null) {
    // The network was sucked into the centre: it grows back out of it.
    live.growth = 0;
    live.regrow = { from: 0, to: 1, start: live.clock, dur: 2 };
    tweenTo(live.ring, 0, 1, live.clock);
  }
  live.endAt = null;
  live.blinkAt = null;
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
  live.voice = { audio: voice.audio, analysis: voice.analysis, last: 0 };
  voice.audio.currentTime = 0;
  voice.audio.play();
  voice.audio.onended = () => {
    if (live.voice && live.voice.audio === voice.audio) live.voice = null;
    showHint();
  };
  showHint();
}

// A cluster of clips of `group` somewhere on the wall, apart from the
// others, and a new axis of the death scene from the centre to it. The
// first one brings the network to rest.
function deathCluster(group) {
  if (!sceneOf().death) return;
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
    const px = m + hw + Math.random() * (W - 2 * (m + hw));
    const py = m + hh + Math.random() * (H - 2 * (m + hh));
    if (Math.hypot(px - cx, py - cy) < LIVE.placeHub) continue;
    const apart = others.reduce((d, c) => Math.min(d, Math.hypot(px - c.x, py - c.y)), W);
    if (apart > best) { best = apart; x = px; y = py; }
  }
  const angle = Math.atan2(y - cy, x - cx);
  const id = 1e6 + live.deathAxes.length;
  live.deathAxes.push({
    id, angle, length: Math.hypot(x - cx, y - cy), born: live.clock, leaving: null,
    breathe: wave(Math.random, LIVE.breatheRate),
  });

  const pool = clipFiles.filter((f) => f.group === group);
  if (!pool.length) return;
  const first = live.nextClip.get(group) || 0;
  live.nextClip.set(group, first + AXES.clipsPerCluster);
  const clips = [];
  for (let k = 0; k < AXES.clipsPerCluster; k++) {
    const video = document.createElement("video");
    video.src = pool[(first + k) % pool.length].url;
    video.muted = true;
    video.loop = true;
    video.playsInline = true;
    clips.push({
      video,
      started: false,
      dx: AXES.clipScatter * (2 * Math.random() - 1),
      dy: AXES.clipScatter * 0.7 * (2 * Math.random() - 1),
      tilt: AXES.clipTilt * (2 * Math.random() - 1),
    });
  }
  live.clusters.push({ x, y, appear: live.clock + 0.8 * LIVE.deathGrow, leaving: null, clips });
}

// Stops a cluster's videos and lets their memory go.
function release(cluster) {
  for (const c of cluster.clips) {
    c.video.pause();
    c.video.removeAttribute("src");
    c.video.load();
  }
}

function endScene() {
  if (!sceneOf().growing || live.endAt !== null) return;
  live.endAt = live.clock;
  live.strobe = true;
  live.flashes = [];
  live.nextFlash = live.clock;
  tweenTo(live.ring, 1, LIVE.ringGrow, live.clock, LIVE.explode + LIVE.whiteHold + 0.85 * LIVE.collapse);
  showHint();
}

// Switches the growth scene between its branches and its straight variant.
function switchVariant() {
  if (!sceneOf().growing) return;
  live.straight = !live.straight;
  tweenTo(live.branching, live.straight ? 0 : 1, LIVE.branchFade, live.clock);
  live.planes = [];
  live.cascades = [];
  showHint();
}

// The straight variant's zero starts to blink, once it has opened.
function blinkDigit() {
  if (!sceneOf().growing || !live.straight || live.blinkAt !== null) return;
  if (tweenAt(live.ring, live.clock) < 0.5) return;
  live.blinkAt = live.clock;
  showHint();
}

// The digit the straight variant ends with at the live clock: "0", "1", or
// null while it is dark in a blink.
function digitAt(clock) {
  if (live.blinkAt === null) return "0";
  const x = clock - live.blinkAt, cycle = LIVE.blinkOff + LIVE.blinkOn;
  const k = Math.floor(x / cycle);
  if (k >= LIVE.blinks) return "1";
  if (x - k * cycle < LIVE.blinkOff) return null;
  return k === LIVE.blinks - 1 ? "1" : "0";
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
    KeyR: () => deathCluster(0),
    KeyO: () => deathCluster(1),
    KeyE: endScene,
    KeyV: switchVariant,
    KeyL: () => {
      if (!sceneOf().growing || !live.straight) return;
      live.manual = !live.manual;
      live.striking = false;
      live.cascades = [];
      showHint();
    },
    KeyT: () => {
      if (!sceneOf().growing || !live.straight || !live.manual || live.endAt !== null) return;
      live.striking = true;
      live.nextStrike = live.clock;
    },
    KeyC: () => {
      if (!sceneOf().growing || !live.straight) return;
      live.colour = !live.colour;
      tweenTo(live.colourMix, live.colour ? 1 : 0, LIVE.colourFade, live.clock);
      showHint();
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
  if (scene.death) parts.push("R: PROBEN-CLUSTER", "O: ONLINE-CLUSTER");
  if (scene.growing) {
    parts.push(`V: ${live.straight ? "GERADE ACHSEN" : "VERZWEIGT"}`, "E: ENDE", `S: STROBO ${live.strobe ? "AN" : "AUS"}`);
    if (live.straight) {
      parts.push(`L: BLITZE ${live.manual ? "MANUELL" : "AUTOMATISCH"}`);
      if (live.manual) parts.push("T: BLITZ (HALTEN)");
      parts.push(`C: FARBE ${live.colour ? "AN" : "AUS"}`);
    }
    if (live.straight && live.endAt !== null) parts.push("0: NULL ZU EINS");
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
  const share = Math.min(1, scheduled(live.growth) / AXES.growthSpan);
  if (live.endAt !== null && ending.collapse >= 1 && live.strobe) {
    live.strobe = false;
    showHint();
  }
  if (scene.growing && ending.collapse < 1) {
    // The pace of the strikes: in the straight variant rare for long, then
    // crowding in towards the end.
    const pace = live.straight ? share ** LIVE.strikeCurve : share;
    const rate = live.endAt !== null ? LIVE.explodeBolts : between(() => pace, LIVE.boltRate);
    if (Math.random() < rate * dt) {
      const ray = randomRay(false);
      if (ray !== null) live.bolts.push({ start: live.clock, strength: 0.6 + 0.4 * Math.random(), ray, seed: Math.random() * 1000 });
    }
    live.pulsePhase += 2 * Math.PI * between(() => share, LIVE.pulseRate) * dt;
    // The straight variant's own strobe, quickening as the network grows;
    // S adds its flashes to these. With manual strikes it is silent, and T
    // fires strikes while it is held.
    if (live.straight && live.manual && live.striking) {
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
    if (live.straight && !live.manual && Math.random() < between(() => pace, LIVE.autoStrobe) * dt) {
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
    // In the straight variant the strobe grows with the network until the
    // ending: sparse and faint at first, the full strobe at full size.
    const full = scene.growing && live.straight && live.endAt === null ? share ** LIVE.strobeGrowth : 1;
    const gap = LIVE.strobeGapEarly.map((v, i) => v + (LIVE.strobeGap[i] - v) * full);
    const strength = LIVE.strobeEarly + (1 - LIVE.strobeEarly) * full;
    while (live.nextFlash <= live.clock) {
      const flash = {
        start: live.nextFlash,
        strength: strength * between(Math.random, LIVE.strobeStrength),
        fade: between(Math.random, LIVE.strobeFade),
      };
      live.flashes.push(flash);
      if (scene.growing && live.straight) {
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

// How far an edge has grown out, 0 to 1: creeping edges at an uneven pace,
// shooters straight out; then the pull back of edges that die.
function crept(e, growth, now) {
  const x = (growth - e.birth) / e.creep;
  if (x <= 0) return 0;
  const surge = e.shooter ? 0 : AXES.creepSurge * Math.sin(Math.PI * Math.min(1, x)) * e.surge(now) / 2;
  return ease(x + surge) * (1 - ease((growth - e.death) / e.fade));
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

// The network at the live state: edges, forks with their arms, and rays.
function figure() {
  const { now, clock } = live;
  const growth = scheduled(live.growth);
  const share = growth / AXES.growthSpan;
  // At rest the rays breathe along their length; the breathing fades in as
  // the motion stops.
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
  // The straight variant: branches drawn back, every axis reaching outward.
  const branch = tweenAt(live.branching, clock);
  const straight = 1 - branch;
  const outward = 1 + straight * LIVE.outward * Math.min(share, LIVE.outwardCap) ** 2;
  const edges = [], forks = [], rays = [];

  const add = (x, y, angle, length, alpha, dist, g, lit, id) => {
    const dx = Math.cos(angle), dy = Math.sin(angle);
    const flash = lit.length ? flashOf(lit, clock, dist + length / 2) : 0;
    const e = { id, x, y, dx, dy, length, alpha, dist, feed: g, fedEnd: 0, flash };
    edges.push(e);
    return { e, tip: { x: x + dx * length, y: y + dy * length, dx, dy, angle, length, dist: dist + length } };
  };

  const grow = (fork, from, alpha, lit) => {
    let carried = 0, born = Infinity;
    const arms = [{ dx: -from.dx, dy: -from.dy, length: from.length }];
    for (const f of fork) {
      const out = crept(f, growth, now);
      const g = out * branch;
      if (g <= 0) continue;
      born = Math.min(born, f.birth);
      const angle = from.angle + f.turn + AXES.sway * f.sway(now);
      const nominal = from.nominal * f.length * (1 + AXES.reach * f.stretch(now));
      const on = f.carry ? lit : lit.filter((b) => hash(b.seed, f.id) < AXES.boltFork);
      const { e, tip } = add(from.x, from.y, angle, nominal * g, alpha * (0.55 + 0.45 * g), from.dist, g, on, f.id);
      // A shooter flashes while it shoots out and while it vanishes.
      if (f.shooter && out < 1) e.flash += AXES.shootFlash * (1 - out);
      tip.nominal = nominal * g;
      e.fedEnd = grow(f.forks, tip, alpha, on);
      e.feed += e.fedEnd;
      carried += e.feed;
      arms.push({ dx: e.dx, dy: e.dy, length: e.length });
    }
    if (carried > 0) forks.push({ x: from.x, y: from.y, fed: carried, age: growth - born, alpha, arms });
    return carried;
  };

  const hubArms = [];
  let hubFed = 0;
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
      const lit = live.bolts.filter((b) => b.ray === root.id);
      const { e, tip } = add(cx, cy, angle, length, alpha, 0, half, lit, root.id);
      tip.nominal = nominal;
      e.fedEnd = grow(root.forks, tip, alpha, lit);
      e.feed += e.fedEnd;
      hubFed += e.feed;
      hubArms.push({ dx: e.dx, dy: e.dy, length: e.length });
      rays.push({ id: root.id, angle, length, root: true });
    }
  }

  // The straight variant's further axes: straight lines through the centre,
  // shooting out as they join and reaching outward with the growth.
  if (straight > 0.001) {
    for (const line of space.lines) {
      const out = ease((growth - line.join) / line.life);
      if (out <= 0) continue;
      const g = out * straight;
      const angle = line.angle + LIVE.lineDrift * line.drift(now);
      const stretch = (1 + AXES.reach * line.reach(now)) * outward * size * g;
      for (const half of [0, 1]) {
        const id = line.id + half;
        const lit = live.bolts.filter((b) => b.ray === id);
        const a = angle + half * Math.PI;
        const { e } = add(cx, cy, a, AXES.radius * line.halves[half] * stretch, line.alpha * straight, 0, g, lit, id);
        e.widthScale = LIVE.lineWidth;
        if (out < 1) e.flash += AXES.shootFlash * (1 - out);
        hubFed += e.feed;
        hubArms.push({ dx: e.dx, dy: e.dy, length: e.length });
        rays.push({ id, angle: a, length: e.length, root: true });
      }
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
      const lit = live.bolts.filter((b) => b.ray === id);
      const { e } = add(cx, cy, angle, d.length * share * g * breath(d.breathe), 1, 0, g, lit, id);
      hubFed += e.feed;
      hubArms.push({ dx: e.dx, dy: e.dy, length: e.length });
      rays.push({ id, angle, length: e.length, root: false });
    }
  }
  forks.push({ x: cx, y: cy, fed: hubFed, age: growth, alpha: 1, arms: hubArms, hub: true });
  live.rays = rays;
  return { edges, forks, size: Math.min(1, size) };
}

// ---- Drawing -----------------------------------------------------------------------------

// The drawing resolution, as a share of 3840 × 2160. The live page draws
// at the size the frame takes on the screen (the window fitted to 16:9,
// times the device pixel ratio, at most 4K), one pixel per screen pixel, so
// the browser never rescales it and thin lines keep their pixels; ?res= or
// LIVE.res set a fixed share instead. Every other mode draws at full size.
function screenRes() {
  if (mode !== "live") return 1;
  const fixed = Number(params.get("res")) || LIVE.res;
  if (fixed) return fixed;
  const shown = Math.min(innerWidth, innerHeight * W / H) * (devicePixelRatio || 1);
  return Math.min(1, shown / W);
}

const layer = (scale) => {
  const c = offscreen(Math.round(W * scale), Math.round(H * scale));
  return { canvas: c, ctx: c.getContext("2d"), scale };
};
let RES, axesL, glowSourceL, glowL, bloomL, flashSourceL, flashL, washL, planesL;
const scratch = new Map();
const digitImages = new Map();   // the digits rendered at RES (digitImage)

// The layers drawn into, at `res`; the scratch layers follow on demand.
function buildLayers(res) {
  RES = res;
  axesL = layer(RES);
  glowSourceL = layer(RES / 4);
  glowL = layer(RES / 4);
  bloomL = layer(RES / 8);
  flashSourceL = layer(RES / 4);
  flashL = layer(RES / 4);
  washL = layer(RES / 16);
  planesL = layer(RES / 2);
  scratch.clear();
  digitImages.clear();
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

// How far a line from (x, y) along (dx, dy) runs before it leaves the frame
// widened by `pad` px.
function frameReach(x, y, dx, dy, pad = 50) {
  const along = (pos, d, lo, hi) => (d > 1e-9 ? (hi - pos) / d : d < -1e-9 ? (lo - pos) / d : Infinity);
  return Math.max(0, Math.min(along(x, dx, -pad, W + pad), along(y, dy, -pad, H + pad)));
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

function webs(c, f) {
  const reach = (f.widthScale || 1)
    * Math.min(AXES.webMax, AXES.webGain * tube(f.fed) * (1 - Math.exp(-f.age / AXES.webLife)));
  if (reach < 1 || f.arms.length < 2) return;
  const arms = f.arms.map((a) => ({ ...a, angle: Math.atan2(a.dy, a.dx) })).sort((a, b) => a.angle - b.angle);
  c.beginPath();
  for (let k = 0; k < arms.length; k++) {
    const a = arms[k], b = arms[(k + 1) % arms.length];
    let gap = b.angle - a.angle;
    if (gap <= 0) gap += 2 * Math.PI;
    // The hub's web spans every gap and keeps its reach along short rays, so
    // its body holds as the rays turn out of view.
    if (!f.hub && gap > AXES.webSpan) continue;
    const r = f.hub ? reach : Math.min(reach, AXES.webShare * a.length, AXES.webShare * b.length);
    if (r < 1) continue;
    const mid = a.angle + gap / 2;
    const bow = r * AXES.webBow / Math.max(0.35, Math.cos(gap / 2));
    c.moveTo(f.x, f.y);
    c.lineTo(f.x + a.dx * r, f.y + a.dy * r);
    c.quadraticCurveTo(f.x + Math.cos(mid) * bow, f.y + Math.sin(mid) * bow, f.x + b.dx * r, f.y + b.dy * r);
    c.closePath();
  }
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

// The edges and forks of the network moved to their places in the ending.
function sunk(edges, forks, fill, k) {
  if (fill === 1 && k <= 0) return;
  for (const e of edges) {
    const [x0, y0] = sink(e.x, e.y, fill, k);
    const [x1, y1, scale] = sink(e.x + e.dx * e.length, e.y + e.dy * e.length, fill, k);
    const length = Math.hypot(x1 - x0, y1 - y0);
    Object.assign(e, { x: x0, y: y0, dx: length > 1e-6 ? (x1 - x0) / length : e.dx, dy: length > 1e-6 ? (y1 - y0) / length : e.dy, length, widthScale: (e.widthScale || 1) * Math.max(0.15, Math.min(1, scale)) });
  }
  for (const f of forks) {
    const [x, y, scale] = sink(f.x, f.y, fill, k);
    f.arms = f.arms.map((a) => {
      const [ax, ay] = sink(f.x + a.dx * a.length, f.y + a.dy * a.length, fill, k);
      const length = Math.hypot(ax - x, ay - y);
      return length > 1e-6 ? { dx: (ax - x) / length, dy: (ay - y) / length, length } : a;
    });
    Object.assign(f, { x, y, widthScale: Math.max(0.15, Math.min(1, scale)) });
  }
}

// Clears a layer and sets it to draw in frame coordinates, pulled towards
// the centre by `pull` (1 for none).
function begin(l, pull) {
  const [cx, cy] = AXES.centre;
  l.ctx.setTransform(1, 0, 0, 1, 0, 0);
  l.ctx.clearRect(0, 0, l.canvas.width, l.canvas.height);
  l.ctx.setTransform(l.scale * pull, 0, 0, l.scale * pull, l.scale * cx * (1 - pull), l.scale * cy * (1 - pull));
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

// A digit in LIVE.digitFont, white, LIVE.digitHeight px high, rendered once
// at the drawing resolution: {canvas, w, h}, w and h in frame px, the ink
// centred. Text drawn at a changing scale is re-fitted to the pixel grid at
// every size and shakes; the image scales smoothly. The size is taken from
// the zero, so both digits stand equally high.
function digitImage(digit) {
  if (digitImages.has(digit)) return digitImages.get(digit);
  const probe = offscreen(1, 1).getContext("2d");
  probe.font = `400 100px ${LIVE.digitFont}, sans-serif`;
  const zero = probe.measureText("0");
  const size = 100 * LIVE.digitHeight / Math.max(1, zero.actualBoundingBoxAscent + zero.actualBoundingBoxDescent);
  probe.font = `400 ${size}px ${LIVE.digitFont}, sans-serif`;
  const m = probe.measureText(digit);
  const pad = 8;
  const w = m.actualBoundingBoxLeft + m.actualBoundingBoxRight + 2 * pad;
  const h = m.actualBoundingBoxAscent + m.actualBoundingBoxDescent + 2 * pad;
  const canvas = offscreen(Math.ceil(w * RES), Math.ceil(h * RES));
  const c = canvas.getContext("2d");
  c.scale(RES, RES);
  c.font = probe.font;
  c.fillStyle = "#ffffff";
  c.textAlign = "left";
  c.textBaseline = "alphabetic";
  c.fillText(digit, pad + m.actualBoundingBoxLeft, pad + m.actualBoundingBoxAscent);
  const image = { canvas, w, h };
  digitImages.set(digit, image);
  return image;
}

// A digit centred on (cx, cy) at `scale` of its size.
function drawDigit(c, digit, cx, cy, scale) {
  const { canvas: image, w, h } = digitImage(digit);
  c.imageSmoothingEnabled = true;
  c.imageSmoothingQuality = "high";
  c.drawImage(image, cx - w * scale / 2, cy - h * scale / 2, w * scale, h * scale);
}

function drawClusters() {
  const clock = live.clock;
  for (const cluster of live.clusters) {
    if (clock < cluster.appear) continue;
    const gone = cluster.leaving === null ? 0 : ease((clock - cluster.leaving) / LIVE.clusterLeave);
    cluster.clips.forEach((c, k) => {
      const start = cluster.appear + k * AXES.clipIn;
      if (clock < start) return;
      if (!c.started) {
        c.started = true;
        c.video.play().catch(() => {});
      }
      const video = c.video;
      if (video.readyState < 2 || !video.videoWidth) return;
      const shrunk = ease((clock - start - AXES.clipLargeFor) / AXES.clipShrink);
      const scale = (AXES.clipLarge + (1 - AXES.clipLarge) * shrunk) * (1 - gone);
      if (scale <= 0.01) return;
      const w = AXES.clipWidth * scale, h = w * video.videoHeight / video.videoWidth;
      ctx.save();
      ctx.translate(cluster.x + c.dx * scale, cluster.y + c.dy * scale);
      ctx.rotate(c.tilt);
      ctx.globalAlpha = AXES.clipAlpha;
      if (AXES.clipGrey) ctx.filter = "grayscale(1)";
      ctx.drawImage(video, -w / 2, -h / 2, w, h);
      ctx.filter = "none";
      ctx.restore();
    });
  }
}

function drawLive({ level, share }) {
  const { edges, forks, size } = figure();
  const [cx, cy] = AXES.centre;
  const clock = live.clock;
  const phase = 2 * Math.PI * live.now / AXES.pulsePeriod;
  const pull = tweenAt(live.regrow, clock);
  const ring = tweenAt(live.ring, clock);
  const ending = endingOf(clock);
  const fill = 1 + (LIVE.explodeSize - 1) * ease(ending.explode);
  sunk(edges, forks, fill, ending.collapse);
  const hub = AXES.hub[0] + (AXES.hub[1] - AXES.hub[0]) * Math.max(0, (size - AXES.twoAxisSize) / (1 - AXES.twoAxisSize));

  // How far the explosion floods the wall: all the way while it explodes,
  // easing off as the collapse begins. The sharp lines fade out with it.
  const flood = ease(ending.explode) * (1 - ease(2 * ending.collapse));
  const sharp = 1 - flood > 0.02;
  // The straight variant: how far it has come in (metal) and how far its
  // red front has run, from `redStart` of the growth's time to its end.
  const metal = 1 - tweenAt(live.branching, clock);
  const red = metal * tweenAt(live.colourMix, clock)
    * Math.min(1, Math.max(0, (live.growth / AXES.growthSpan - LIVE.redStart) / (1 - LIVE.redStart)));
  // The strobe's flashes as they stand: they blaze in the metal's glints.
  let blaze = 0;
  for (const f of live.flashes) {
    const x = clock - f.start;
    if (x >= 0) blaze += f.strength * Math.exp(-x / f.fade);
  }
  const baseRGB = tint(null, red);
  // The straight variant's glow, rising with the growth.
  const grownNow = Math.min(1, share);
  const glowWide = 1 + (between(() => grownNow, LIVE.glowWidth) - 1) * metal;
  const glowBoost = 1 + (between(() => grownNow, LIVE.lineGlow) - 1) * metal;
  const base = metal > 0 ? css(metalRGB(baseRGB, 0.75, metal)) : "#ffffff";
  const planeColour = metal > 0 ? css(metalRGB(tint(null, red, LIVE.redPlanes), 0.75, metal)) : "#ffffff";
  const c = axesL.ctx, g = glowSourceL.ctx, fl = flashSourceL.ctx, pl = planesL.ctx;
  for (const l of [axesL, glowSourceL, flashSourceL, planesL]) begin(l, Math.max(pull, 1e-3));
  let hubWidth = 0;     // the summed width of the lines where they leave the centre
  // The narrowest sharp line in frame px: LIVE.minLinePx drawn pixels. A
  // line thinner than a pixel or so switches the pixels it crosses on and
  // off as it moves; drawn at this width and dimmed in proportion it gives
  // the same light and moves smoothly.
  const minLine = LIVE.minLinePx / RES;
  if (pull > 0.002 && ending.collapse < 1) {
    for (const e of edges) {
      const ws = e.widthScale || 1;
      const w0 = tube(e.feed) * ws, w1 = (e.fedEnd > 0 ? tube(e.fedEnd) : tube(e.feed) * AXES.taperTip) * ws;
      const mid = e.dist + e.length / 2;
      if (LIVE.chrome > 0) {
        // Gradients along the visible part of the edge: the line in chrome,
        // shaded at each stop; the glow carrying the red front out along it,
        // shaded as the middle of the line.
        const angle = Math.atan2(e.dy, e.dx);
        const seen = Math.min(e.length, frameReach(e.x, e.y, e.dx, e.dy));
        const tip = e.dist + e.length;
        if (seen >= 0.5) {
          // colourAt(r, u): r px from the centre, u of the way to the tip.
          const along = (l, stops, colourAt) => {
            const grad = l.createLinearGradient(e.x, e.y, e.x + e.dx * seen, e.y + e.dy * seen);
            for (let k = 0; k < stops; k++) {
              const t = k / (stops - 1);
              const r = e.dist + t * seen;
              grad.addColorStop(t, css(colourAt(r, r / tip)));
            }
            return grad;
          };
          if (sharp) {
            const stops = Math.min(LIVE.metalStops, Math.max(2, Math.ceil(4 * seen / LIVE.bandLength) + 1));
            c.fillStyle = along(c, stops, (r) => metalRGB([255, 255, 255], sheen(angle, r, live.now, clock, blaze), LIVE.chrome));
          }
          // The glow keeps the edge's own colour, brightened or darkened by
          // its shade but never whitened, so the wall stays in its colour;
          // where it has turned red, light shimmers out along it.
          const shade = Math.min(1.2, sheen(angle, mid, live.now, clock, blaze));
          const phase = 2 * Math.PI * hash(e.id, 5.3);
          const wave = 2 * Math.PI / LIVE.shimmerLength, run = LIVE.shimmerSpeed * clock;
          const glowStops = Math.min(LIVE.shimmerStops, Math.max(2, Math.ceil(4 * seen / LIVE.shimmerLength) + 1));
          g.fillStyle = fl.fillStyle = along(g, glowStops, (r, u) => {
            const rgb = tint(e.id, red, u);
            const shimmer = 1 + LIVE.shimmer * redAt(e.id, red, u)
              * (0.6 * Math.sin(wave * r - run + phase) + 0.4 * Math.sin(wave * r / 0.37 - 1.7 * run + 2 * phase));
            // Outside the straight variant the glow keeps its full light.
            const lit = 1 + (shade * shimmer - 1) * metal;
            return mixRGB(rgb, rgb.map((v) => Math.min(255, v * lit)), LIVE.chrome);
          });
        }
      }
      if (e.dist === 0) hubWidth += w0;
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
    c.fillStyle = g.fillStyle = base;
    // In the straight variant the core takes the place of the hub's web
    // and disc.
    for (const f of forks) {
      const shown = f.hub ? 1 - metal : 1;
      if (shown <= 0.001) continue;
      c.globalAlpha = shown;
      if (sharp) webs(c, f);
      g.globalAlpha = f.alpha * shown;
      webs(g, f);
    }
    // The planes the flashes light, spanned by their axes as they stand now
    // and moved with the network in the ending.
    const raysById = new Map(live.rays.map((r) => [r.id, r]));
    pl.fillStyle = g.fillStyle = planeColour;
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
    for (const l of [c, g]) {
      if (metal >= 1) break;
      l.globalAlpha = 1 - metal;
      l.beginPath();
      l.arc(cx, cy, hub * fill * (1 - ending.collapse), 0, 2 * Math.PI);
      l.fill();
    }
  }
  // The new shape opening out of the centre: a circle, or in the straight
  // variant a zero that blinks into a one.
  const digit = live.straight ? digitAt(clock) : null;
  if (ring > 0.001 && (!live.straight || digit)) {
    for (const l of [axesL, glowSourceL]) {
      l.ctx.setTransform(l.scale, 0, 0, l.scale, 0, 0);
      l.ctx.globalAlpha = Math.min(1, ring * 1.5);
      l.ctx.fillStyle = l.ctx.strokeStyle = base;
      if (live.straight) {
        // The digits stay white whatever colour the network has turned, and
        // steady: they open with the ring and do not follow the voice.
        drawDigit(l.ctx, digit, cx, cy, ring);
        continue;
      }
      l.ctx.lineWidth = LIVE.ringWidth;
      l.ctx.beginPath();
      l.ctx.arc(cx, cy, LIVE.ringRadius * ring * (1 + 0.03 * level), 0, 2 * Math.PI);
      l.ctx.stroke();
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
  // The strobe flickers the glow; in the straight variant the glow rests
  // low and lives on its flashes.
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
    ctx.drawImage(source, 0, 0, W, H);
  };

  ctx.setTransform(RES, 0, 0, RES, 0, 0);
  ctx.globalAlpha = 1;
  ctx.fillStyle = "#000000";
  ctx.fillRect(0, 0, W, H);
  ctx.globalCompositeOperation = "lighter";
  addLayer(bloomL, lerp(AXES.bloom) * lift * glowBoost);
  addLayer(glowL, flickering ? lerp(AXES.glow) * lift * glowBoost : Math.min(1, lerp(AXES.glow) * lift));
  if (live.planes.length) addLayer(planesL, 1);
  addLayer(flashL, AXES.boltGlow * (flickering ? flicker : 1));
  if (flood > 0) addLayer(washL, LIVE.explodeWash * flood * flicker);
  ctx.globalCompositeOperation = "source-over";
  if (sharp) {
    ctx.globalAlpha = 1 - flood;
    ctx.drawImage(axesL.canvas, 0, 0, W, H);
    ctx.globalAlpha = 1;
  }
  // The straight variant's core: light at the centre the axes grow out of,
  // fading into the colour without an edge, larger and brighter as the
  // network grows, with a wide halo of the colour lighting the wall, and
  // the white heart where the lines merge. It sinks into the centre with
  // the collapse.
  const core = metal * (1 - ending.collapse) * pull;
  if (core > 0.002) {
    const swell = 1 + LIVE.coreVoice * level + LIVE.coreFlash * Math.min(2, blaze);
    const r = between(() => grownNow ** LIVE.coreCurve, LIVE.coreRadius) * fill * swell;
    const halo = between(() => grownNow, LIVE.haloRadius) * fill * swell;
    const heart = mixRGB(baseRGB, [255, 255, 255], LIVE.coreHeat);
    const rgba = (rgb, a) => `rgba(${rgb.map(Math.round).join(",")},${a})`;
    const glowAt = (radius, stops, alpha) => {
      const grad = ctx.createRadialGradient(cx, cy, 0, cx, cy, radius);
      for (const [t, rgb, a] of stops) grad.addColorStop(t, rgba(rgb, a));
      ctx.globalAlpha = Math.min(1, alpha);
      ctx.fillStyle = grad;
      ctx.fillRect(cx - radius, cy - radius, 2 * radius, 2 * radius);
    };
    ctx.globalCompositeOperation = "lighter";
    glowAt(halo, [[0, baseRGB, 1], [0.25, baseRGB, 0.55], [0.6, baseRGB, 0.15], [1, baseRGB, 0]],
      between(() => grownNow, LIVE.haloAlpha) * (1 + LIVE.haloFlash * Math.min(2, blaze)) * core);
    glowAt(r, [[0, heart, 0.8], [0.25, baseRGB, 0.55], [0.6, baseRGB, 0.18], [1, baseRGB, 0]],
      between(() => grownNow, LIVE.coreGlow) * core);
    // The heart: out to the radius where the lines' widths fill the
    // circumference they cross, they overlap into one light.
    // Its light falls off as a bell curve with no rim, white at the middle
    // and taking on the colour as it fades.
    const merged = LIVE.heartSpread * hubWidth / (2 * Math.PI) * fill * (1 + 0.5 * (swell - 1));
    if (merged > 1) {
      const reach = merged * LIVE.heartFade;
      const stops = [];
      for (let k = 0; k <= 12; k++) {
        const t = k / 12;
        const x = t * reach / (LIVE.heartWidth * merged);
        stops.push([t, mixRGB([255, 255, 255], heart, Math.min(1, t * 1.5)), k === 12 ? 0 : Math.exp(-x * x)]);
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
    ctx.fillRect(0, 0, W, H);
    ctx.globalCompositeOperation = "source-over";
    ctx.globalAlpha = 1;
  }
  drawClusters();
}

// ---- Loading and modes ---------------------------------------------------------------------

async function loadLive() {
  try {
    document.fonts.add(await new FontFace(LIVE.digitFont, `url(/fonts/${LIVE.digitFont}-Regular.ttf)`).load());
  } catch {
    // Without the font the digits fall back to the browser's sans-serif.
  }
  const clips = await fetch("/clips.json");
  if (clips.ok) {
    for (const c of await clips.json()) {
      const res = await fetch(c.src);
      if (res.ok) clipFiles.push({ url: URL.createObjectURL(await res.blob()), group: c.group });
    }
  }
  const list = await fetch("/voices.json");
  if (list.ok) {
    for (const v of await list.json()) {
      const analysis = await (await fetch(v.analysis)).json();
      const audio = new Audio(v.audio);
      audio.preload = "auto";
      voices.push({ name: v.name, audio, analysis });
    }
  }
}

// The live page: the frame follows the performance, drawn as fast as the
// machine allows.
function runLive() {
  // The frame follows the window, so going fullscreen or moving to another
  // screen redraws it at that screen's resolution.
  const fit = () => {
    const res = screenRes();
    if (res !== RES) buildLayers(res);
    canvas.width = Math.round(W * RES);
    canvas.height = Math.round(H * RES);
  };
  fit();
  addEventListener("resize", fit);
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
    drawLive(update(dt));
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
