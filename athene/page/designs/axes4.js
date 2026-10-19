/* Axes 4: the slime mould grows clusters of clips, and the voice runs
   through it as light.

   The slime-mould network of the third axes design (designs/axes3.js), with
   webbed forks, clusters of clips that stay, and the voice back as light:

     space     the axes are the unit vectors of a space of AXES.dims
               dimensions, seen through a slowly turning two-dimensional
               window. Every axis is a straight line through the centre.
     growing   two short orthogonal axes at first; the others grow out of
               the centre one after another and fork, the forks fork again,
               and the network spreads beyond the edges of the frame by the
               end of the clip. Edges creep out at an uneven pace, sway and
               reach on slow waves, thicken with the network they feed, and
               some side edges pull back and vanish. Growth is spread over
               the clip, whatever its length; the waves keep their pace.
     webs      where edges spring from a fork, a web spans the angle between
               neighbouring edges, like the skin between fingers: its concave
               rim stretches as the edges move, and it reaches further out
               along them the longer the fork has existed. The hub, the
               oldest fork, is webbed between its rays.
     clusters  clips pop up one after another at the tip of a branch, in
               their own aspect ratio, large at first, and shrink after a
               few seconds. They stay where they appeared and keep replaying
               while the network grows on. Six clusters by the end: three
               from the rehearsals, then three from other footage (the clip
               groups the renderer serves, in that order).
     voice     the voice moves nothing; it lights the network. Each syllable
               sends a bolt of light from the hub out along one ray, forking
               through part of its branches like lightning, and the glow
               rises a little with the level.
     glow      the lines are solid white; their glow and a wide bloom
               strengthen as the figure grows, dimmer where an axis is
               foreshortened, with a slow pulse running outward.

   AXES holds the parameters of the design. */

"use strict";

const AXES = {
  dims: 10,             // dimensions of the space: twenty rays at the end of a clip
  radius: 800,          // px, half-length of an axis at full size
  centre: [W / 2, H / 2],
  margin: 70,           // px kept free at the frame's edges, for the clusters
  hub: [8, 22],         // px, radius of the dot where the axes meet, small and full size

  // Growth runs on its own clock, `growthSpan` seconds of it over the whole
  // clip. Every growth time below is in seconds of that clock; the waves of
  // motion are in seconds of the clip.
  growthSpan: 108,

  // Size: the figure starts at `startSize` of its full size and grows to it
  // over the clip, a little faster at first.
  startSize: 0.12, sizeCurve: 0.85,

  // Turning of the window: radians, and radians of wave phase per second.
  tilt: 0.9, tiltHidden: 0.3, tiltRate: [0.02, 0.06], planesPerDim: 3,
  spin: 0.008, normalise: 0.8,
  // How much a ray shortens as its axis tilts out of view: its length goes
  // with (projected / mean) to this power. The forks on it keep their size.
  foreshorten: 0.5,

  // Joining, as shares of the growth; `joinLife` in seconds of growth.
  joinFirst: 0.06, joinLast: 0.6, joinCurve: 0.7, joinLife: 6,

  // Halves: the lasting length of each half-axis, as a share of the axis,
  // taken on between these shares of the growth.
  halves: [0.35, 1.3], halvesFirst: 0.05, halvesLast: 0.45,

  // Tentacles: the share of its length an edge reaches out or draws back,
  // and the wave phase of that per second.
  reach: 0.3, reachRate: 0.12,

  // Creeping: seconds an edge takes to grow out, and how uneven its pace is.
  creepLife: 7, creepSurge: 0.35,

  // Forks. The first are born between these shares of the growth; each
  // later fork waits `forkWait` seconds after its parent has grown.
  branchFirst: 0.1, branchLast: 0.75,
  branchDepth: 6,
  forkChance: [0.95, 0.85, 0.75, 0.65, 0.5, 0.35],
  sideForkShare: 0.6,
  threeWay: 0.35,
  carryLength: [0.6, 0.95],
  sideLength: [0.45, 0.8],
  carryKink: 0.3,
  sideAngle: [0.55, 1.15],
  sway: 0.15,           // radians an edge sways at its joint
  forkWait: [0.5, 6],

  // Die-back: the share of side edges that pull back, and the seconds it takes.
  dieShare: 0.25, dieAfter: [8, 25], dieLife: 6,

  // Tubes: width in px is minWidth + widthGain × √(edges fed, as grown).
  minWidth: 3, widthGain: 2.6, taperTip: 0.6,
  faint: 0.45,          // glow of a fully foreshortened axis

  // Webs: between neighbouring edges less than `webSpan` radians apart. A
  // web reaches `webGain` times the width of the tube ending in the fork
  // along each edge, approached with the time constant `webLife` in seconds
  // of growth, at most `webMax` px and `webShare` of the shorter edge. Its
  // rim bows in to `webBow` of its reach.
  webSpan: 1.9, webGain: 5, webLife: 25, webMax: 150, webShare: 0.4, webBow: 0.3,

  // Streaming: a pulse of glow running outward.
  pulse: 0.22, pulsePeriod: 7, pulseLength: 1400,   // depth, seconds, px between pulses

  // Glow and bloom, from the start to full size.
  glow: [0.45, 1.0], glowBlur: 7,       // blur in px at a quarter of the resolution
  bloom: [0.1, 0.85], bloomBlur: 10,    // blur in px at an eighth of the resolution

  // Voice. A bolt runs out from the hub at `boltSpeed` px per second,
  // carrying on through every edge and into `boltFork` of the side edges.
  // Where it passes, an edge flashes within `boltRise` seconds and fades
  // over `boltFade`. The glow rises by `levelGlow` at full level.
  boltSpeed: 3500, boltFork: 0.5, boltRise: 0.03, boltFade: 0.22,
  boltGlow: 1.0, boltBlur: 3, levelGlow: 0.3, levelSmooth: 0.3,

  // Clusters: times are shares of the clip's duration, `group` the clip
  // group the renderer serves. Clips pop up `clipIn` seconds apart and
  // replay until the end. Each starts `clipLarge` times its size, stays so
  // for `clipLargeFor` seconds and then shrinks within `clipShrink`.
  clusters: [
    { appear: 0.2, group: 0, clips: 16 },
    { appear: 0.3, group: 0, clips: 16 },
    { appear: 0.4, group: 0, clips: 16 },
    { appear: 0.52, group: 1, clips: 16 },
    { appear: 0.62, group: 1, clips: 16 },
    { appear: 0.72, group: 1, clips: 16 },
  ],
  clipWidth: 112,       // px; the height follows the clips' aspect ratio
  clipScatter: 110, clipTilt: 0.1,
  clipIn: 0.05, clipAlpha: 0.92,
  clipLarge: 3, clipLargeFor: 8, clipShrink: 1.5,
  clipGrey: false,
};

// ---- Preparation -------------------------------------------------------------

const space = {
  planes: [],
  joins: [],
  roots: [],      // per half-axis: {id, bias, reach, forks}
  bolts: [],      // {start, strength, root, seed}
  level: new Float64Array(0),
  clusters: [],   // {appear, x, y, clips: [{sheet, height, dx, dy, tilt}]}
};

// Frame sheets of the cluster clips: {image, frames, fps, width, height, columns, group}.
const sheets = [];

function duration() {
  return clip.frames ? clip.frames / clip.fps : 60;
}

// Seconds of growth at time t.
function growthAt(t) {
  return t * AXES.growthSpan / duration();
}

// Smooth noise in [-1, 1]: three sines of nearby frequencies.
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

// A number in [0, 1) fixed by two integers, for choices made frame by frame.
function hash(a, b) {
  const x = Math.sin(a * 12.9898 + b * 78.233) * 43758.5453;
  return x - Math.floor(x);
}

function buildSpace() {
  const random = makeRandom(23);
  const n = AXES.dims;
  const span = AXES.growthSpan;

  space.joins = [-Infinity, -Infinity];
  for (let j = 2; j < n; j++) {
    const x = n > 3 ? (j - 2) / (n - 3) : 0;
    const share = AXES.joinFirst + (AXES.joinLast - AXES.joinFirst) * x ** AXES.joinCurve;
    space.joins.push(share * span);
  }

  space.planes = [];
  for (let j = 1; j < n; j++) {
    const partners = new Set();
    while (partners.size < Math.min(j, AXES.planesPerDim)) partners.add(Math.floor(random() * j));
    for (const i of partners) space.planes.push({ i, j, wave: wave(random, between(random, AXES.tiltRate)) });
  }

  // A fork: the edges growing from the end of an edge, the first carrying it on.
  let ids = 0;
  const forks = (depth, after, side) => {
    const chance = AXES.forkChance[depth] * (side ? AXES.sideForkShare : 1);
    if (depth >= AXES.branchDepth || random() > chance) return [];
    const count = random() < AXES.threeWay ? 3 : 2;
    const birth = depth === 0
      ? Math.max(after, between(random, [AXES.branchFirst, AXES.branchLast]) * span)
      : after + between(random, AXES.forkWait);
    const firstSide = random() < 0.5 ? 1 : -1;
    const edges = [];
    for (let k = 0; k < count; k++) {
      const carry = k === 0;
      const turn = carry
        ? AXES.carryKink * (2 * random() - 1)
        : (k === 1 ? firstSide : -firstSide) * between(random, AXES.sideAngle);
      const edgeBirth = birth + 1.5 * k * random();
      const dies = !carry && depth > 0 && random() < AXES.dieShare;
      edges.push({
        id: ids++,
        birth: edgeBirth,
        death: dies ? edgeBirth + AXES.creepLife + between(random, AXES.dieAfter) : Infinity,
        carry,
        turn,
        length: between(random, carry ? AXES.carryLength : AXES.sideLength),
        sway: wave(random, AXES.reachRate),
        stretch: wave(random, AXES.reachRate),
        surge: wave(random, 0.5),
        forks: forks(depth + 1, edgeBirth + AXES.creepLife, !carry),
      });
    }
    return edges;
  };

  space.roots = [];
  for (let h = 0; h < 2 * n; h++) {
    const joined = space.joins[h >> 1] + AXES.joinLife;
    space.roots.push({
      id: ids++,
      bias: between(random, AXES.halves),
      reach: wave(random, AXES.reachRate),
      forks: forks(0, joined, false),
    });
  }

  // Each syllable sends a bolt along one of the rays shown at its time.
  space.bolts = clip.onsets.map(([start, strength], k) => {
    const growth = growthAt(start);
    const shown = space.joins.filter((join) => growth > join + AXES.joinLife / 2).length;
    return { start, strength, root: Math.floor(random() * 2 * shown), seed: k + 1 };
  });
  space.level = clip.frames ? smoothBoth(clip.level, AXES.levelSmooth, clip.fps) : new Float64Array(0);
  buildClusters(random);
}

// Each cluster appears at the tip furthest from the centre and from the other
// clusters that has room for it in the frame, and stays there. Its centre
// lies beyond the tip, so the branch ends at its edge, and is kept far
// enough inside the frame for all of its clips at their largest.
function buildClusters(random) {
  space.clusters = [];
  const next = new Map();
  const placed = [];
  const [cx, cy] = AXES.centre;
  const m = AXES.margin;
  const large = AXES.clipLarge;
  const sx = large * (AXES.clipWidth / 2 + AXES.clipScatter), sy = large * (AXES.clipWidth / 2 + 0.7 * AXES.clipScatter);
  for (const spec of AXES.clusters) {
    const pool = sheets.filter((s) => s.group === spec.group);
    const first = next.get(spec.group) || 0;
    const count = Math.min(spec.clips, pool.length - first);
    if (count <= 0) continue;
    next.set(spec.group, first + count);
    const appear = spec.appear * duration();
    let best = null, bestScore = -Infinity;
    for (const tip of figure(appear).tips.values()) {
      const inside = tip.x > m && tip.x < W - m && tip.y > m && tip.y < H - m;
      const apart = placed.reduce((d, c) => Math.min(d, Math.hypot(tip.x - c.x, tip.y - c.y)), W);
      const score = Math.hypot(tip.x - cx, tip.y - cy) + apart - (inside ? 0 : 4 * W);
      if (score > bestScore) { best = tip; bestScore = score; }
    }
    if (best === null) continue;
    const reach = AXES.clipWidth / 2 * 0.8;
    const x = Math.min(W - m - sx, Math.max(m + sx, best.x + best.dx * reach));
    const y = Math.min(H - m - sy, Math.max(m + sy, best.y + best.dy * reach));
    placed.push({ x: best.x, y: best.y });
    const clips = [];
    for (let k = 0; k < count; k++) {
      const sheet = pool[first + k];
      clips.push({
        sheet,
        height: AXES.clipWidth * sheet.height / sheet.width,
        dx: AXES.clipScatter * (2 * random() - 1),
        dy: AXES.clipScatter * 0.7 * (2 * random() - 1),
        tilt: AXES.clipTilt * (2 * random() - 1),
      });
    }
    space.clusters.push({ appear, x, y, clips });
  }
}

// ---- The figure ---------------------------------------------------------------

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
    const share = AXES.tiltHidden + (1 - AXES.tiltHidden) * grown[j];
    turn(i, j, AXES.tilt * share * wave(now));
  }
  turn(0, 1, AXES.spin * now);
  return { p, q };
}

// Distance from (x, y) along the unit direction (dx, dy) to the margin of
// the frame; 0 outside it.
function room(x, y, dx, dy) {
  const m = AXES.margin;
  const along = (pos, d, lo, hi) => (d > 1e-9 ? (hi - pos) / d : d < -1e-9 ? (lo - pos) / d : Infinity);
  return Math.max(0, Math.min(along(x, dx, m, W - m), along(y, dy, m, H - m)));
}

// How far an edge has crept out, 0 to 1: an ease whose pace surges and
// slackens, then a pull back for edges that die.
function crept(e, growth, now) {
  const x = (growth - e.birth) / AXES.creepLife;
  if (x <= 0) return 0;
  const out = ease(x + AXES.creepSurge * Math.sin(Math.PI * Math.min(1, x)) * e.surge(now) / 2);
  return out * (1 - ease((growth - e.death) / AXES.dieLife));
}

// The light of the bolts on an edge whose middle lies `dist` px from the hub.
function flashOf(bolts, t, dist) {
  let sum = 0;
  for (const b of bolts) {
    const x = t - b.start - dist / AXES.boltSpeed;
    if (x <= 0) continue;
    sum += b.strength * ease(x / AXES.boltRise) * Math.exp(-Math.max(0, x - AXES.boltRise) / AXES.boltFade);
  }
  return sum;
}

// The figure at time t: its edges as {x, y, dx, dy, length, feed, fedEnd,
// alpha, dist, flash}, its forks as {x, y, fed, age, alpha, arms: [{dx, dy,
// length}]}, and the tip of every edge by id as {x, y, dx, dy}. `feed`
// counts the edges an edge carries, itself included, weighted by how far
// they have grown; `dist` is the distance from the hub along the network; a
// fork's `age` is the growth since its first edge was born, and its arms are
// the edges meeting there, the one it grows from included.
function figure(t) {
  const growth = growthAt(t);
  const share = Math.min(1, growth / AXES.growthSpan);
  const n = AXES.dims;
  const grown = space.joins.map((join) => ease((growth - join) / AXES.joinLife));
  const { p, q } = windowAt(t, grown);

  let sum = 0, weight = 0;
  for (let i = 0; i < n; i++) {
    sum += grown[i] * (p[i] * p[i] + q[i] * q[i]);
    weight += grown[i];
  }
  const mean = Math.sqrt(sum / weight);
  const size = AXES.startSize + (1 - AXES.startSize) * share ** AXES.sizeCurve;
  const scale = AXES.radius * size / Math.max(mean, 0.05) ** AXES.normalise;
  const halves = ease((share - AXES.halvesFirst) / (AXES.halvesLast - AXES.halvesFirst));
  const [cx, cy] = AXES.centre;
  const edges = [], forks = [], tips = new Map();
  // Bolts of the last seconds: three seconds carry one beyond the frame.
  const bolts = space.bolts.filter((b) => t >= b.start && t < b.start + 3 + 5 * AXES.boltFade);

  const add = (id, x, y, angle, length, alpha, dist, g, lit) => {
    const dx = Math.cos(angle), dy = Math.sin(angle);
    const flash = lit.length ? flashOf(lit, t, dist + length / 2) : 0;
    const e = { x, y, dx, dy, length, alpha, dist, feed: g, fedEnd: 0, flash };
    edges.push(e);
    const tip = { x: x + dx * length, y: y + dy * length, dx, dy, angle, length, dist: dist + length };
    if (length > 1) tips.set(id, tip);
    return { e, tip };
  };

  // Grows the edges of a fork from `from` and returns the edges they carry,
  // as grown. `lit` are the bolts running along the edge it grows from.
  const grow = (fork, from, alpha, lit) => {
    let carried = 0, born = Infinity;
    const arms = [{ dx: -from.dx, dy: -from.dy, length: from.length }];
    for (const f of fork) {
      const g = crept(f, growth, t);
      if (g <= 0) continue;
      born = Math.min(born, f.birth);
      const angle = from.angle + f.turn + AXES.sway * f.sway(t);
      const nominal = from.nominal * f.length * (1 + AXES.reach * f.stretch(t));
      const on = f.carry ? lit : lit.filter((b) => hash(b.seed, f.id) < AXES.boltFork);
      const { e, tip } = add(f.id, from.x, from.y, angle, nominal * g, alpha * (0.55 + 0.45 * g), from.dist, g, on);
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
      const half = 2 * i + (sign > 0 ? 0 : 1);
      const root = space.roots[half];
      const angle = Math.atan2(sign * q[i], sign * p[i]);
      const stretch = (1 + (root.bias - 1) * halves) * (1 + AXES.reach * root.reach(t));
      const nominal = scale * mean * stretch * grown[i];
      const length = nominal * (projected / mean) ** AXES.foreshorten;
      const lit = bolts.filter((b) => b.root === half);
      const { e, tip } = add(root.id, cx, cy, angle, length, alpha, 0, grown[i], lit);
      tip.nominal = nominal;
      e.fedEnd = grow(root.forks, tip, alpha, lit);
      e.feed += e.fedEnd;
      hubFed += e.feed;
      hubArms.push({ dx: e.dx, dy: e.dy, length: e.length });
    }
  }
  forks.push({ x: cx, y: cy, fed: hubFed, age: growth, alpha: 1, arms: hubArms });
  return { edges, forks, tips, share, size };
}

// ---- Drawing --------------------------------------------------------------------

const axesLayer = offscreen(W, H);
const axesCtx = axesLayer.getContext("2d");
const glowSource = offscreen(W / 4, H / 4);
const glowSourceCtx = glowSource.getContext("2d");
const glowLayer = offscreen(W / 4, H / 4);
const glowCtx = glowLayer.getContext("2d");
const bloomLayer = offscreen(W / 8, H / 8);
const bloomCtx = bloomLayer.getContext("2d");
const flashSource = offscreen(W / 4, H / 4);
const flashSourceCtx = flashSource.getContext("2d");
const flashLayer = offscreen(W / 4, H / 4);
const flashCtx = flashLayer.getContext("2d");

function tube(feed) {
  return AXES.minWidth + AXES.widthGain * Math.sqrt(feed);
}

// A straight edge tapering from w0 to w1, with a round end around its tip.
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

// The webs of a fork: between each pair of neighbouring arms, a patch from
// the fork out along both arms, closed by a rim bowing in towards the fork.
function webs(c, f) {
  const reach = Math.min(AXES.webMax, AXES.webGain * tube(f.fed) * (1 - Math.exp(-f.age / AXES.webLife)));
  if (reach < 1 || f.arms.length < 2) return;
  const arms = f.arms.map((a) => ({ ...a, angle: Math.atan2(a.dy, a.dx) })).sort((a, b) => a.angle - b.angle);
  c.beginPath();
  for (let k = 0; k < arms.length; k++) {
    const a = arms[k], b = arms[(k + 1) % arms.length];
    let gap = b.angle - a.angle;
    if (gap <= 0) gap += 2 * Math.PI;
    if (gap > AXES.webSpan) continue;
    const r = Math.min(reach, AXES.webShare * a.length, AXES.webShare * b.length);
    if (r < 1) continue;
    const mid = a.angle + gap / 2;
    const bow = r * AXES.webBow / Math.cos(gap / 2);
    c.moveTo(f.x, f.y);
    c.lineTo(f.x + a.dx * r, f.y + a.dy * r);
    c.quadraticCurveTo(f.x + Math.cos(mid) * bow, f.y + Math.sin(mid) * bow, f.x + b.dx * r, f.y + b.dy * r);
    c.closePath();
  }
  c.fill();
}

function drawClusters(t) {
  for (const cluster of space.clusters) {
    if (t < cluster.appear) continue;
    // Clips pop up in order and replay until the end; each is large for a
    // while, then shrinks towards the cluster's centre.
    cluster.clips.forEach((c, k) => {
      const start = cluster.appear + k * AXES.clipIn;
      if (t < start) return;
      const shrunk = ease((t - start - AXES.clipLargeFor) / AXES.clipShrink);
      const scale = AXES.clipLarge + (1 - AXES.clipLarge) * shrunk;
      const sheet = c.sheet;
      const frame = Math.floor((t - start) * sheet.fps) % sheet.frames;
      const fx = (frame % sheet.columns) * sheet.width, fy = Math.floor(frame / sheet.columns) * sheet.height;
      const w = AXES.clipWidth * scale, h = c.height * scale;
      ctx.save();
      ctx.translate(cluster.x + c.dx * scale, cluster.y + c.dy * scale);
      ctx.rotate(c.tilt);
      ctx.globalAlpha = AXES.clipAlpha;
      if (AXES.clipGrey) ctx.filter = "grayscale(1)";
      ctx.drawImage(sheet.image, fx, fy, sheet.width, sheet.height, -w / 2, -h / 2, w, h);
      ctx.filter = "none";
      ctx.restore();
    });
  }
}

function drawAxes(t) {
  const { edges, forks, share, size } = figure(t);
  const [cx, cy] = AXES.centre;
  const phase = 2 * Math.PI * t / AXES.pulsePeriod;
  const hub = AXES.hub[0] + (AXES.hub[1] - AXES.hub[0]) * (size - AXES.startSize) / (1 - AXES.startSize);

  // The lines in solid white; at a quarter of the resolution the source of
  // their glow, weighted by foreshortening and the outward pulse, and the
  // light of the bolts.
  const c = axesCtx, g = glowSourceCtx, fl = flashSourceCtx;
  c.clearRect(0, 0, W, H);
  c.fillStyle = "#ffffff";
  for (const layer of [g, fl]) {
    layer.setTransform(1, 0, 0, 1, 0, 0);
    layer.clearRect(0, 0, W / 4, H / 4);
    layer.setTransform(0.25, 0, 0, 0.25, 0, 0);
    layer.fillStyle = "#ffffff";
  }
  for (const e of edges) {
    const w0 = tube(e.feed), w1 = e.fedEnd > 0 ? tube(e.fedEnd) : w0 * AXES.taperTip;
    edge(c, e.x, e.y, e.dx, e.dy, e.length, w0, w1);
    // The pulse runs outward: its phase falls with the distance from the hub.
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
    webs(c, f);
    g.globalAlpha = f.alpha;
    webs(g, f);
  }
  for (const layer of [c, g]) {
    layer.globalAlpha = 1;
    layer.beginPath();
    layer.arc(cx, cy, hub, 0, 2 * Math.PI);
    layer.fill();
  }

  // Glow at a quarter of the resolution, bloom from it at an eighth, and the
  // bolts' light, all added under the sharp lines. Glow and bloom strengthen
  // as the figure grows and rise a little with the voice.
  glowCtx.clearRect(0, 0, W / 4, H / 4);
  glowCtx.filter = `blur(${AXES.glowBlur}px)`;
  glowCtx.drawImage(glowSource, 0, 0);
  glowCtx.filter = "none";
  bloomCtx.clearRect(0, 0, W / 8, H / 8);
  bloomCtx.filter = `blur(${AXES.bloomBlur}px)`;
  bloomCtx.drawImage(glowLayer, 0, 0, W / 8, H / 8);
  bloomCtx.filter = "none";
  flashCtx.clearRect(0, 0, W / 4, H / 4);
  flashCtx.filter = `blur(${AXES.boltBlur}px)`;
  flashCtx.drawImage(flashSource, 0, 0);
  flashCtx.filter = "none";
  const lift = 1 + AXES.levelGlow * at(space.level, t, 0);
  const lerp = ([a, b]) => a + (b - a) * share;
  ctx.globalCompositeOperation = "lighter";
  ctx.globalAlpha = Math.min(1, lerp(AXES.bloom) * lift);
  ctx.drawImage(bloomLayer, 0, 0, W, H);
  ctx.globalAlpha = Math.min(1, lerp(AXES.glow) * lift);
  ctx.drawImage(glowLayer, 0, 0, W, H);
  ctx.globalAlpha = AXES.boltGlow;
  ctx.drawImage(flashLayer, 0, 0, W, H);
  ctx.globalCompositeOperation = "source-over";
  ctx.globalAlpha = 1;
  ctx.drawImage(axesLayer, 0, 0);
  drawClusters(t);
}

// The frame sheets listed by the renderer in /clips.json; none if it lists none.
async function loadSheets() {
  const res = await fetch("/clips.json");
  if (!res.ok) return;
  for (const s of await res.json()) {
    sheets.push({ ...s, image: await loadImage(s.src) });
  }
}

buildSpace();

registerDesign({
  load: loadSheets,
  prepare: buildSpace,
  draw: drawAxes,
});
