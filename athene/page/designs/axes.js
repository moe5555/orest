/* Axes: Athene as a living high-dimensional coordinate system.

   Athene stands apart from Seestone: no mark, no name, no CI colours. White
   straight lines on black (athene/description.md).

     space     the axes are the unit vectors of a space of AXES.dims
               dimensions, seen through a two-dimensional window (an
               orthonormal pair of vectors p, q). Axis i appears as the line
               through the centre with direction (p[i], q[i]): every axis is
               straight and all of them meet in the middle. The window turns
               through the planes of the space, so the axes swing, change
               their angles and foreshorten as they tilt out of view.
     joining   at first only two axes are drawn, orthogonal, the coordinate
               system everyone knows. The others are already there and bend
               the two before they show; one after another they grow out of
               the centre until the space has all its dimensions. Their
               arrivals are spread over the clip, the first ones far apart,
               the last ones close together.
     reaching  each half of an axis reaches out and draws back on its own,
               like a tentacle, and each syllable makes one of them reach
               out further.
     branches  later in the clip the ends of the axes spawn edges of their
               own, which in turn spawn edges: the coordinate system becomes
               a star.

   The voice drives Athene's life: time passes slowly in silence and quickly
   while she speaks, so the space moves and grows with her speech. Level
   widens the whole figure and brightens its glow; tone opens the branches.

   AXES holds the parameters of the design. */

"use strict";

const AXES = {
  dims: 12,             // dimensions of the space: the axes at the end of a clip
  radius: 620,          // px, half-length of an axis at rest
  centre: [W / 2, H / 2],
  margin: 70,           // px kept free at the frame's edges

  // Life: the clock of the motion, in seconds of full-level speech plus
  // `restRate` per second of time, so silence moves her slowly.
  restRate: 0.2,

  // Turning of the window, in radians.
  tilt: 0.9,            // largest tilt in a plane of the space
  tiltHidden: 0.3,      // share of the tilt into dimensions not yet shown
  tiltRate: [0.12, 0.35], // radians of wave phase per unit of life, slowest and fastest plane
  planesPerDim: 3,      // planes each dimension turns in, with earlier ones
  spin: 0.04,           // radians per unit of life the window turns in its own plane
  normalise: 0.8,       // 0 lets the figure shrink as axes foreshorten, 1 holds its mean size

  // Joining, as shares of the clip's life.
  joinFirst: 0.07, joinLast: 0.7,
  joinCurve: 0.6,       // below 1, the first arrivals are far apart and the last close together
  joinLife: 1.6,        // units of life an axis takes to grow out

  // Reaching.
  reach: 0.3,           // share of its length a half-axis reaches out or draws back
  reachRate: 0.5,       // radians of wave phase per unit of life
  flick: 0.4,           // share a full-strength syllable makes one half-axis reach out
  flickRise: 0.12, flickFall: 0.5,   // seconds; the rise starts 0.06 s before the syllable

  // Breath: the whole figure widens with the voice.
  breath: 0.12, breathSmooth: 0.25,  // share at full level, smoothing in seconds

  // Branches, as shares of the clip's life.
  branchFirst: 0.35, branchLast: 0.92,
  branchShare: 0.7,     // share of the ends that branch
  branchDepth: 2,       // generations of branches
  branchCount: 2,       // edges each end spawns
  branchLength: 0.34,   // share of the parent's length
  branchSpread: [0.45, 0.8],  // radians either side of the parent, dark and bright voice
  branchLife: 2.5,      // units of life a branch takes to grow out
  branchDelay: 0.08,    // share of the clip's life between generations

  // Lines.
  width: [12, 4],       // px at the centre and at the end of an axis
  branchWidth: 0.75,    // width of a branch as a share of its parent's end
  faint: 0.45,          // brightness of a fully foreshortened axis
  glow: [0.35, 0.8],    // glow strength at rest and at full level
  glowBlur: 7,          // px of blur at a quarter of the resolution
};

// ---- Preparation -------------------------------------------------------------

const space = {
  planes: [],     // {i, j, amp, rate, phase, rate2, phase2}, in the order applied
  joins: [],      // life at which axis i begins to grow out
  reaches: [],    // per half-axis (2i for +, 2i+1 for −): wave parameters
  branches: [],   // per half-axis: a tree of {birth, wobble} nodes, null where it does not branch
  flicks: [],     // [time, strength, half-axis]
  breath: new Float64Array(0),
  lifeEnd: 1,
};

function lifeAt(t) {
  return AXES.restRate * t + spokenAt(t);
}

// Smooth noise in [-1, 1]: three sines of nearby frequencies.
function wave(random, rate) {
  const parts = [1, 0.55, 0.3].map((amp) => ({
    amp, rate: rate * (0.6 + 0.9 * random()), phase: 2 * Math.PI * random(),
  }));
  const total = parts.reduce((sum, p) => sum + p.amp, 0);
  return (x) => parts.reduce((sum, p) => sum + p.amp * Math.sin(p.rate * x + p.phase), 0) / total;
}

function buildSpace() {
  const random = makeRandom(7);
  const n = AXES.dims;
  const duration = clip.frames ? clip.frames / clip.fps : 60;
  space.lifeEnd = Math.max(1, lifeAt(duration));

  // The first two axes are there from the start; the others join in order.
  space.joins = [-Infinity, -Infinity];
  for (let j = 2; j < n; j++) {
    const x = n > 3 ? (j - 2) / (n - 3) : 0;
    const share = AXES.joinFirst + (AXES.joinLast - AXES.joinFirst) * x ** AXES.joinCurve;
    space.joins.push(share * space.lifeEnd);
  }

  // Each dimension turns in planes with a few earlier ones, so the window
  // passes through all of the space.
  space.planes = [];
  for (let j = 1; j < n; j++) {
    const partners = new Set();
    while (partners.size < Math.min(j, AXES.planesPerDim)) partners.add(Math.floor(random() * j));
    for (const i of partners) {
      const [lo, hi] = AXES.tiltRate;
      space.planes.push({ i, j, wave: wave(random, lo + (hi - lo) * random()) });
    }
  }

  space.reaches = [];
  for (let h = 0; h < 2 * n; h++) space.reaches.push(wave(random, AXES.reachRate));

  // Branch trees: a node is born after its parent, its children after it.
  const node = (depth, after) => {
    if (random() > AXES.branchShare) return null;
    const share = AXES.branchFirst + (AXES.branchLast - AXES.branchFirst) * random();
    const birth = Math.max(after, (share + depth * AXES.branchDelay) * space.lifeEnd);
    const children = [];
    if (depth + 1 < AXES.branchDepth) {
      for (let k = 0; k < AXES.branchCount; k++) children.push(node(depth + 1, birth + AXES.branchLife));
    }
    return { birth, angle: wave(random, AXES.reachRate), length: wave(random, AXES.reachRate), children };
  };
  space.branches = [];
  for (let h = 0; h < 2 * n; h++) {
    const joined = space.joins[h >> 1] + AXES.joinLife;
    const ends = [];
    for (let k = 0; k < AXES.branchCount; k++) ends.push(node(0, joined));
    space.branches.push(ends);
  }

  // Each syllable goes to one of the half-axes visible at its time.
  space.flicks = clip.onsets.map(([start, strength]) => {
    const life = lifeAt(start);
    const shown = space.joins.filter((join) => life > join + AXES.joinLife / 2).length;
    return [start, strength, Math.floor(random() * 2 * shown)];
  });

  space.breath = clip.frames ? smoothBoth(clip.level, AXES.breathSmooth, clip.fps) : new Float64Array(0);
}

// ---- The window ---------------------------------------------------------------

// The pair (p, q) at a given life: the starting window (e0, e1) turned
// through every plane of the space in a fixed order.
function windowAt(life, grown) {
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
    turn(i, j, AXES.tilt * share * wave(life));
  }
  turn(0, 1, AXES.spin * life);
  return { p, q };
}

// ---- Drawing --------------------------------------------------------------------

const axesLayer = offscreen(W, H);
const axesCtx = axesLayer.getContext("2d");
const glowLayer = offscreen(W / 4, H / 4);
const glowCtx = glowLayer.getContext("2d");

// Distance from (x, y) along the unit direction (dx, dy) to the margin of the frame.
function room(x, y, dx, dy) {
  const m = AXES.margin;
  const along = (pos, d, lo, hi) => (d > 1e-9 ? (hi - pos) / d : d < -1e-9 ? (lo - pos) / d : Infinity);
  return Math.max(0, Math.min(along(x, dx, m, W - m), along(y, dy, m, H - m)));
}

// Lengths up to 60 % of the room pass unchanged; longer ones approach the
// margin without reaching it.
function fit(length, limit) {
  const knee = 0.6 * limit;
  if (length <= knee) return length;
  return knee + (limit - knee) * Math.tanh((length - knee) / (limit - knee));
}

// A straight edge from (x, y) along (dx, dy), tapering from w0 to w1, with a
// round end.
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

function flickAt(t, half) {
  let sum = 0;
  for (const [start, strength, target] of space.flicks) {
    if (start > t + 0.1) break;
    if (target !== half || t - start > 5 * AXES.flickFall) continue;
    const dt = t - start;
    const rise = ease((dt + 0.06) / AXES.flickRise);
    sum += strength * rise * Math.exp(-Math.max(0, dt - AXES.flickRise + 0.06) / AXES.flickFall);
  }
  return sum;
}

function drawBranches(c, nodes, x, y, angle, length, width, alpha, life, spread, depth) {
  nodes.forEach((n, k) => {
    if (n === null || life <= n.birth) return;
    const grown = ease((life - n.birth) / AXES.branchLife);
    const side = nodes.length > 1 ? (2 * k / (nodes.length - 1) - 1) : 0;
    const a = angle + side * spread + 0.25 * n.angle(life);
    const dx = Math.cos(a), dy = Math.sin(a);
    const want = length * AXES.branchLength * (1 + 0.3 * n.length(life)) * grown;
    const len = fit(want, room(x, y, dx, dy));
    const w0 = width * AXES.branchWidth, w1 = Math.max(1.5, w0 * 0.45);
    c.globalAlpha = alpha * (0.6 + 0.4 * grown);
    edge(c, x, y, dx, dy, len, w0, w1);
    drawBranches(c, n.children, x + dx * len, y + dy * len, a, len, w1, alpha, life, spread, depth + 1);
  });
}

function drawAxes(t) {
  const life = lifeAt(t);
  const level = at(clip.level, t, 0);
  const tone = at(clip.tone, t, 0.35);
  const n = AXES.dims;
  const grown = space.joins.map((join) => ease((life - join) / AXES.joinLife));
  const { p, q } = windowAt(life, grown);

  // Mean projected length of the axes shown, for the normalisation.
  let sum = 0, weight = 0;
  for (let i = 0; i < n; i++) {
    sum += grown[i] * (p[i] * p[i] + q[i] * q[i]);
    weight += grown[i];
  }
  const mean = Math.sqrt(sum / weight);
  const breath = 1 + AXES.breath * at(space.breath, t, 0);
  const scale = AXES.radius * breath / Math.max(mean, 0.05) ** AXES.normalise;
  const spread = AXES.branchSpread[0] + (AXES.branchSpread[1] - AXES.branchSpread[0]) * tone;
  const [cx, cy] = AXES.centre;

  const c = axesCtx;
  c.clearRect(0, 0, W, H);
  c.fillStyle = "#ffffff";
  for (let i = 0; i < n; i++) {
    if (grown[i] <= 0) continue;
    const projected = Math.hypot(p[i], q[i]);
    if (projected < 1e-6) continue;
    const alpha = AXES.faint + (1 - AXES.faint) * Math.min(1, projected / mean);
    for (const sign of [1, -1]) {
      const half = 2 * i + (sign > 0 ? 0 : 1);
      const dx = sign * p[i] / projected, dy = sign * q[i] / projected;
      const reach = 1 + AXES.reach * space.reaches[half](life) + AXES.flick * flickAt(t, half);
      const len = fit(scale * projected * reach * grown[i], room(cx, cy, dx, dy));
      const [w0, w1] = AXES.width;
      c.globalAlpha = alpha;
      edge(c, cx, cy, dx, dy, len, w0, w1);
      drawBranches(c, space.branches[half], cx + dx * len, cy + dy * len, Math.atan2(dy, dx),
        len, w1, alpha, life, spread, 0);
    }
  }
  c.globalAlpha = 1;

  // Glow: the lines blurred at a quarter of the resolution, under the sharp lines.
  glowCtx.clearRect(0, 0, W / 4, H / 4);
  glowCtx.filter = `blur(${AXES.glowBlur}px)`;
  glowCtx.drawImage(axesLayer, 0, 0, W / 4, H / 4);
  glowCtx.filter = "none";
  ctx.globalAlpha = AXES.glow[0] + (AXES.glow[1] - AXES.glow[0]) * level;
  ctx.drawImage(glowLayer, 0, 0, W, H);
  ctx.globalAlpha = 1;
  ctx.drawImage(axesLayer, 0, 0);
}

buildSpace();

registerDesign({
  prepare: buildSpace,
  draw: drawAxes,
});
