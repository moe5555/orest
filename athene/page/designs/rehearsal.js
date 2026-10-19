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

   Keys: N next scene, B previous scene, Space restart the scene, P play the
   scene's next voice clip (or stop the one playing), H show or hide the
   help line. Changing scene stops the voice and animates the network into
   the new scene's state.

   The voice lights the network in every scene: each syllable sends a bolt
   of light from the hub out along one ray, and the glow rises with the
   level. `LIVE.res` sets the drawing resolution of the live page as a share
   of 3840 × 2160 (?res= overrides it).

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
  res: 1,               // drawing resolution of the live page, as a share of 3840 × 2160
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
  // resolution), and the sharp lines fade out, leaving the glow.
  explode: 6, explodeBolts: 14, explodeGrowth: 25, explodeSize: 2.2,
  explodeWash: 3, washBlur: 14,
  collapse: 3.5, swirl: 4, ringRadius: 700, ringWidth: 16, ringGrow: 3,
  // Strobe: flashes of the glow at irregular gaps (s), of random strength,
  // each fading with a time constant (s); between flashes the glow sinks to
  // `strobeBase` of its strength.
  strobeGap: [0.03, 0.28], strobeStrength: [0.5, 2.5], strobeFade: [0.03, 0.12], strobeBase: 0.25,
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

// A thrust that rises within `rise` seconds and falls back to nothing in `fall`.
function thrust(x, rise, fall) {
  if (x <= 0 || x >= rise + fall) return 0;
  return ease(x / rise) * (1 - ease((x - rise) / fall));
}

// ---- The space -------------------------------------------------------------------

const space = { planes: [], joins: [], joinLives: [], roots: [] };

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
  live.strobe = false;
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
  tweenTo(live.ring, 1, LIVE.ringGrow, live.clock, LIVE.explode + 0.85 * LIVE.collapse);
  showHint();
}

// The ending at the live clock: how far the explosion and the collapse have
// come, each 0 to 1.
function endingOf(clock) {
  if (live.endAt === null) return { explode: 0, collapse: 0 };
  const x = clock - live.endAt;
  return {
    explode: Math.min(1, x / LIVE.explode),
    collapse: Math.min(1, Math.max(0, (x - LIVE.explode) / LIVE.collapse)),
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
  if (scene.growing) parts.push("E: ENDE", `S: STROBO ${live.strobe ? "AN" : "AUS"}`);
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
    const rate = live.endAt !== null ? LIVE.explodeBolts : between(() => share, LIVE.boltRate);
    if (Math.random() < rate * dt) {
      const ray = randomRay(false);
      if (ray !== null) live.bolts.push({ start: live.clock, strength: 0.6 + 0.4 * Math.random(), ray, seed: Math.random() * 1000 });
    }
    live.pulsePhase += 2 * Math.PI * between(() => share, LIVE.pulseRate) * dt;
  }
  if (live.strobe) {
    while (live.nextFlash <= live.clock) {
      live.flashes.push({
        start: live.nextFlash,
        strength: between(Math.random, LIVE.strobeStrength),
        fade: between(Math.random, LIVE.strobeFade),
      });
      live.nextFlash += between(Math.random, LIVE.strobeGap);
    }
  }
  live.flashes = live.flashes.filter((f) => live.clock - f.start < 6 * f.fade);
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
  const edges = [], forks = [], rays = [];

  const add = (x, y, angle, length, alpha, dist, g, lit) => {
    const dx = Math.cos(angle), dy = Math.sin(angle);
    const flash = lit.length ? flashOf(lit, clock, dist + length / 2) : 0;
    const e = { x, y, dx, dy, length, alpha, dist, feed: g, fedEnd: 0, flash };
    edges.push(e);
    return { e, tip: { x: x + dx * length, y: y + dy * length, dx, dy, angle, length, dist: dist + length } };
  };

  const grow = (fork, from, alpha, lit) => {
    let carried = 0, born = Infinity;
    const arms = [{ dx: -from.dx, dy: -from.dy, length: from.length }];
    for (const f of fork) {
      const g = crept(f, growth, now);
      if (g <= 0) continue;
      born = Math.min(born, f.birth);
      const angle = from.angle + f.turn + AXES.sway * f.sway(now);
      const nominal = from.nominal * f.length * (1 + AXES.reach * f.stretch(now));
      const on = f.carry ? lit : lit.filter((b) => hash(b.seed, f.id) < AXES.boltFork);
      const { e, tip } = add(from.x, from.y, angle, nominal * g, alpha * (0.55 + 0.45 * g), from.dist, g, on);
      // A shooter flashes while it shoots out and while it vanishes.
      if (f.shooter && g < 1) e.flash += AXES.shootFlash * (1 - g);
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
      const length = nominal * ((projected / mean) ** AXES.foreshorten + pokedAt(root.id, clock)) * breath(root.breathe);
      const lit = live.bolts.filter((b) => b.ray === root.id);
      const { e, tip } = add(cx, cy, angle, length, alpha, 0, half, lit);
      tip.nominal = nominal;
      e.fedEnd = grow(root.forks, tip, alpha, lit);
      e.feed += e.fedEnd;
      hubFed += e.feed;
      hubArms.push({ dx: e.dx, dy: e.dy, length: e.length });
      rays.push({ id: root.id, angle, length, root: true });
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
      const { e } = add(cx, cy, angle, d.length * share * g * breath(d.breathe), 1, 0, g, lit);
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

// The live page draws at LIVE.res (or ?res=), every other mode at full size.
const RES = mode === "live" ? Number(params.get("res")) || LIVE.res : 1;
const layer = (scale) => {
  const c = offscreen(Math.round(W * scale), Math.round(H * scale));
  return { canvas: c, ctx: c.getContext("2d"), scale };
};
const axesL = layer(RES), glowSourceL = layer(RES / 4), glowL = layer(RES / 4), bloomL = layer(RES / 8);
const flashSourceL = layer(RES / 4), flashL = layer(RES / 4), washL = layer(RES / 16);

// A scratch layer of the same size as `l`, for brightening it.
const scratch = new Map();
function boosted(l) {
  if (!scratch.has(l)) scratch.set(l, layer(l.scale));
  return scratch.get(l);
}

function tube(feed) {
  return Math.min(AXES.maxWidth, AXES.minWidth + AXES.widthGain * Math.sqrt(feed));
}

function edge(c, x, y, dx, dy, length, w0, w1) {
  if (length < 0.5) return;
  const ex = x + dx * length, ey = y + dy * length;
  const nx = -dy, ny = dx;
  c.beginPath();
  c.moveTo(x + nx * w0 / 2, y + ny * w0 / 2);
  c.lineTo(ex + nx * w1 / 2, ey + ny * w1 / 2);
  c.arc(ex, ey, w1 / 2, Math.atan2(ny, nx), Math.atan2(ny, nx) - Math.PI, true);
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
    Object.assign(e, { x: x0, y: y0, dx: length > 1e-6 ? (x1 - x0) / length : e.dx, dy: length > 1e-6 ? (y1 - y0) / length : e.dy, length, widthScale: Math.max(0.15, Math.min(1, scale)) });
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
  const c = axesL.ctx, g = glowSourceL.ctx, fl = flashSourceL.ctx;
  for (const l of [axesL, glowSourceL, flashSourceL]) begin(l, Math.max(pull, 1e-3));
  if (pull > 0.002 && ending.collapse < 1) {
    for (const e of edges) {
      const ws = e.widthScale || 1;
      const w0 = tube(e.feed) * ws, w1 = (e.fedEnd > 0 ? tube(e.fedEnd) : tube(e.feed) * AXES.taperTip) * ws;
      if (sharp) edge(c, e.x, e.y, e.dx, e.dy, e.length, w0, w1);
      const mid = e.dist + e.length / 2;
      const pulse = 1 - AXES.pulse * (0.5 + 0.5 * Math.sin(phase - 2 * Math.PI * mid / AXES.pulseLength));
      g.globalAlpha = Math.min(1, e.alpha * pulse + e.flash);
      edge(g, e.x, e.y, e.dx, e.dy, e.length, w0, w1);
      if (e.flash > 0.01) {
        fl.globalAlpha = Math.min(1, e.flash);
        edge(fl, e.x, e.y, e.dx, e.dy, e.length, 1.5 * w0, 1.5 * w1);
      }
    }
    for (const f of forks) {
      if (sharp) webs(c, f);
      g.globalAlpha = f.alpha;
      webs(g, f);
    }
    for (const l of [c, g]) {
      l.globalAlpha = 1;
      l.beginPath();
      l.arc(cx, cy, hub * fill * (1 - ending.collapse), 0, 2 * Math.PI);
      l.fill();
    }
  }
  // The new shape: a circle opening out of the centre.
  if (ring > 0.001) {
    for (const l of [axesL, glowSourceL]) {
      l.ctx.setTransform(l.scale, 0, 0, l.scale, 0, 0);
      l.ctx.globalAlpha = Math.min(1, ring * 1.5);
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
  let flicker = 1;
  if (live.strobe) {
    flicker = LIVE.strobeBase;
    for (const f of live.flashes) {
      const x = clock - f.start;
      if (x >= 0) flicker += f.strength * Math.exp(-x / f.fade);
    }
  }
  const lift = (1 + AXES.levelGlow * level) * (1 + pulseDepth * (0.5 + 0.5 * Math.sin(live.pulsePhase))) * (1 + surge) * flicker;
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
  addLayer(bloomL, lerp(AXES.bloom) * lift);
  addLayer(glowL, live.strobe ? lerp(AXES.glow) * lift : Math.min(1, lerp(AXES.glow) * lift));
  addLayer(flashL, AXES.boltGlow * (live.strobe ? flicker : 1));
  if (flood > 0) addLayer(washL, LIVE.explodeWash * flood * flicker);
  ctx.globalCompositeOperation = "source-over";
  if (sharp) {
    ctx.globalAlpha = 1 - flood;
    ctx.drawImage(axesL.canvas, 0, 0, W, H);
    ctx.globalAlpha = 1;
  }
  drawClusters();
}

// ---- Loading and modes ---------------------------------------------------------------------

async function loadLive() {
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
  canvas.width = Math.round(W * RES);
  canvas.height = Math.round(H * RES);
  addEventListener("keydown", onKey);
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
