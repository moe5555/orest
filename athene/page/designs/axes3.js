/* Axes 3: Athene grows like a slime mould, independent of the voice.

   The figure of the second axes design (designs/axes2.js), a coordinate
   system that grows into a branching star, moved by time alone: no level,
   syllable or tone reaches it, so it creeps instead of answering the voice.
   Its growth follows the mechanics of a slime mould (Physarum):

     space     the axes are the unit vectors of a space of AXES.dims
               dimensions, seen through a slowly turning two-dimensional
               window. Every axis is a straight line through the centre.
     joining   two short orthogonal axes at first; the others grow out of
               the centre one after another, and the two halves of each axis
               take on lengths of their own.
     creeping  every edge creeps out over many seconds, its pace uneven, and
               reaches out and draws back on its own like a tentacle. In sum
               the figure only grows: it starts small and spreads beyond the
               edges of the frame by the end of the clip. The forks take
               their size from the nominal length of the edge they grow
               from, not from its length on the wall, so an axis turning out
               of view moves its forks but does not shrink them.
     forking   the ends fork into twos and threes, one edge carrying on with
               a kink, for up to AXES.branchDepth generations.
     tubes     an edge thickens with the network it feeds, as the tubes of a
               slime mould thicken with the flow through them: the trunks
               near the hub grow heavy, the exploring ends stay fine.
     nodes     where edges spring from the end of an edge, a node swells the
               longer the fork has existed.
     die-back  some side edges stop, pull back and vanish with everything
               that grew from them, as a slime mould gives up dead ends.
     streaming a slow pulse of light runs outward through the glow of the
               network, after the shuttle streaming in a slime mould's tubes.
     glow      the lines are solid white; their glow and a wide bloom
               strengthen as the figure grows, dimmer where an axis is
               foreshortened.
     clusters  body-search clips pop up at a far tip in their colours, in
               quick succession, while the network freezes, and pop out
               again just as quickly.

   Athene's life is the time the network moves, in seconds: it stands still
   while a cluster is shown.

   AXES holds the parameters of the design. */

"use strict";

const AXES = {
  dims: 10,             // dimensions of the space: twenty rays at the end of a clip
  radius: 800,          // px, half-length of an axis at full size
  centre: [W / 2, H / 2],
  margin: 70,           // px kept free at the frame's edges, for the clusters
  hub: [8, 22],         // px, radius of the dot where the axes meet, small and full size

  // Size: the figure starts at `startSize` of its full size and grows to it
  // over the clip's life, a little faster at first.
  startSize: 0.12, sizeCurve: 0.85,

  // Turning of the window: radians, and radians of wave phase per second.
  tilt: 0.9, tiltHidden: 0.3, tiltRate: [0.02, 0.06], planesPerDim: 3,
  spin: 0.008, normalise: 0.8,
  // How much a ray shortens as its axis tilts out of view: its length goes
  // with (projected / mean) to this power. The forks on it keep their size.
  foreshorten: 0.5,

  // Joining, as shares of the clip's life; `joinLife` in seconds.
  joinFirst: 0.06, joinLast: 0.6, joinCurve: 0.7, joinLife: 6,

  // Halves: the lasting length of each half-axis, as a share of the axis,
  // taken on between these shares of the clip's life.
  halves: [0.35, 1.3], halvesFirst: 0.05, halvesLast: 0.45,

  // Tentacles: the share of its length an edge reaches out or draws back,
  // and the wave phase of that per second.
  reach: 0.3, reachRate: 0.12,

  // Creeping: seconds an edge takes to grow out, and how uneven its pace is.
  creepLife: 7, creepSurge: 0.35,

  // Forks. The first are born between these shares of the clip's life;
  // each later fork waits `forkWait` seconds after its parent has grown.
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

  // Nodes: a fork's node starts as wide as the tube ending in it and its
  // radius grows by up to `nodeGrowth` px, approaching it with the time
  // constant `nodeLife` in seconds of Athene's life.
  nodeGrowth: 10, nodeLife: 30,
  faint: 0.45,          // glow of a fully foreshortened axis

  // Streaming: a pulse of glow running outward.
  pulse: 0.22, pulsePeriod: 7, pulseLength: 1400,   // depth, seconds, px between pulses

  // Glow and bloom, from the start to full size.
  glow: [0.45, 1.0], glowBlur: 7,       // blur in px at a quarter of the resolution
  bloom: [0.1, 0.85], bloomBlur: 10,    // blur in px at an eighth of the resolution

  // Clusters of clips, as in the second design. Times are shares of the
  // clip's duration. Clips pop up `clipIn` seconds apart and pop out
  // `clipOut` seconds apart, the last one leaving at `vanish`.
  clusters: [
    { appear: 0.33, vanish: 0.45, clips: 14 },
    { appear: 0.62, vanish: 0.74, clips: 14 },
  ],
  freeze: true, freezeEase: 0.8,
  clipSize: 260, clipScatter: 210, clipTilt: 0.1,
  clipIn: 0.08, clipOut: 0.05, clipAlpha: 0.92, clipOutline: 3,
  clipGrey: false,
};

// ---- Preparation -------------------------------------------------------------

const space = {
  planes: [],
  joins: [],
  roots: [],      // per half-axis: {id, bias, reach, forks}
  life: new Float64Array(0),
  lifeEnd: 1,
  clusters: [],   // {appear, vanish, tip, clips: [{sheet, dx, dy, tilt}]}
};

// Frame sheets of the cluster clips: {image, frames, fps, width, height, columns, group}.
const sheets = [];

function lifeAt(t) {
  return space.life.length ? at(space.life, t, 0) : t;
}

function duration() {
  return clip.frames ? clip.frames / clip.fps : 60;
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

// The clusters that have clips to show, with their times in seconds.
function clusterTimes() {
  const times = [];
  let next = 0;
  for (const spec of AXES.clusters) {
    const count = Math.min(spec.clips, sheets.length - next);
    if (count <= 0) break;
    times.push({ appear: spec.appear * duration(), vanish: spec.vanish * duration(), first: next, count });
    next += count;
  }
  return times;
}

// Per frame, 1 while the network moves and 0 while it is frozen: from a
// cluster's appearance until its last clip has left at `vanish`, eased at
// both ends.
function motionSeries(times) {
  const motion = new Float64Array(clip.frames).fill(1);
  if (!AXES.freeze) return motion;
  for (const { appear, vanish } of times) {
    for (let i = 0; i < clip.frames; i++) {
      const t = i / clip.fps;
      const still = ease((t - appear) / AXES.freezeEase) * ease((vanish - t) / AXES.freezeEase);
      motion[i] = Math.min(motion[i], 1 - still);
    }
  }
  return motion;
}

function buildSpace() {
  const random = makeRandom(23);
  const n = AXES.dims;
  const times = clusterTimes();
  const motion = motionSeries(times);
  space.life = new Float64Array(clip.frames ? clip.frames + 1 : 0);
  for (let i = 0; i < clip.frames; i++) space.life[i + 1] = space.life[i] + motion[i] / clip.fps;
  space.lifeEnd = Math.max(1, lifeAt(duration()));

  space.joins = [-Infinity, -Infinity];
  for (let j = 2; j < n; j++) {
    const x = n > 3 ? (j - 2) / (n - 3) : 0;
    const share = AXES.joinFirst + (AXES.joinLast - AXES.joinFirst) * x ** AXES.joinCurve;
    space.joins.push(share * space.lifeEnd);
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
      ? Math.max(after, between(random, [AXES.branchFirst, AXES.branchLast]) * space.lifeEnd)
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
  buildClusters(random, times);
}

// Each cluster hangs at the tip furthest from the centre in the figure it
// freezes, preferring tips with room for it, and carries no other cluster.
function buildClusters(random, times) {
  space.clusters = [];
  const taken = new Set();
  const [cx, cy] = AXES.centre;
  for (const { appear, vanish, first, count } of times) {
    let best = null, bestScore = -Infinity;
    for (const [id, tip] of figure(appear + AXES.freezeEase).tips) {
      if (taken.has(id)) continue;
      const cramped = room(tip.x, tip.y, tip.dx, tip.dy) < AXES.clipSize;
      const score = Math.hypot(tip.x - cx, tip.y - cy) - (cramped ? 2 * W : 0);
      if (score > bestScore) { best = id; bestScore = score; }
    }
    if (best === null) continue;
    taken.add(best);
    const clips = [];
    for (let k = 0; k < count; k++) {
      clips.push({
        sheet: sheets[first + k],
        dx: AXES.clipScatter * (2 * random() - 1),
        dy: AXES.clipScatter * (2 * random() - 1),
        tilt: AXES.clipTilt * (2 * random() - 1),
      });
    }
    space.clusters.push({ appear, vanish, tip: best, clips });
  }
}

// ---- The figure ---------------------------------------------------------------

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

// Distance from (x, y) along the unit direction (dx, dy) to the margin of
// the frame; 0 outside it.
function room(x, y, dx, dy) {
  const m = AXES.margin;
  const along = (pos, d, lo, hi) => (d > 1e-9 ? (hi - pos) / d : d < -1e-9 ? (lo - pos) / d : Infinity);
  return Math.max(0, Math.min(along(x, dx, m, W - m), along(y, dy, m, H - m)));
}

// How far an edge has crept out, 0 to 1: an ease whose pace surges and
// slackens, then a pull back for edges that die.
function crept(e, life) {
  const x = (life - e.birth) / AXES.creepLife;
  if (x <= 0) return 0;
  const out = ease(x + AXES.creepSurge * Math.sin(Math.PI * Math.min(1, x)) * e.surge(life) / 2);
  return out * (1 - ease((life - e.death) / AXES.dieLife));
}

// The share of the clip's life, 0 to 1.
function lifeShare(life) {
  return Math.min(1, life / space.lifeEnd);
}

// The figure at time t: its edges as {x, y, dx, dy, length, feed, fedEnd,
// alpha, dist}, its forks as {x, y, fed, age, alpha}, and the tip of every
// edge by id as {x, y, dx, dy}. `feed` counts the edges an edge carries,
// itself included, weighted by how far they have grown; `dist` is the
// distance from the hub along the network; a fork's `age` is the time since
// its first edge was born.
function figure(t) {
  const life = lifeAt(t);
  const share = lifeShare(life);
  const n = AXES.dims;
  const grown = space.joins.map((join) => ease((life - join) / AXES.joinLife));
  const { p, q } = windowAt(life, grown);

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

  const add = (id, x, y, angle, length, alpha, dist, g) => {
    const dx = Math.cos(angle), dy = Math.sin(angle);
    const e = { x, y, dx, dy, length, alpha, dist, feed: g, fedEnd: 0 };
    edges.push(e);
    const tip = { x: x + dx * length, y: y + dy * length, dx, dy, angle, dist: dist + length };
    if (length > 1) tips.set(id, tip);
    return { e, tip };
  };

  // Grows the edges of a fork from `from` and returns the edges they carry,
  // as grown.
  const grow = (fork, from, alpha) => {
    let carried = 0, born = Infinity;
    for (const f of fork) {
      const g = crept(f, life);
      if (g <= 0) continue;
      born = Math.min(born, f.birth);
      const angle = from.angle + f.turn + AXES.sway * f.sway(life);
      const nominal = from.nominal * f.length * (1 + AXES.reach * f.stretch(life));
      const { e, tip } = add(f.id, from.x, from.y, angle, nominal * g, alpha * (0.55 + 0.45 * g), from.dist, g);
      tip.nominal = nominal * g;
      e.fedEnd = grow(f.forks, tip, alpha);
      e.feed += e.fedEnd;
      carried += e.feed;
    }
    if (carried > 0) forks.push({ x: from.x, y: from.y, fed: carried, age: life - born, alpha });
    return carried;
  };

  for (let i = 0; i < n; i++) {
    if (grown[i] <= 0) continue;
    const projected = Math.hypot(p[i], q[i]);
    if (projected < 1e-6) continue;
    const alpha = AXES.faint + (1 - AXES.faint) * Math.min(1, projected / mean);
    for (const sign of [1, -1]) {
      const root = space.roots[2 * i + (sign > 0 ? 0 : 1)];
      const angle = Math.atan2(sign * q[i], sign * p[i]);
      const reach = (1 + (root.bias - 1) * halves) * (1 + AXES.reach * root.reach(life));
      const nominal = scale * mean * reach * grown[i];
      const length = nominal * (projected / mean) ** AXES.foreshorten;
      const { e, tip } = add(root.id, cx, cy, angle, length, alpha, 0, grown[i]);
      tip.nominal = nominal;
      e.fedEnd = grow(root.forks, tip, alpha);
      e.feed += e.fedEnd;
    }
  }
  return { edges, forks, tips, life, share, size };
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

function tube(feed) {
  return AXES.minWidth + AXES.widthGain * Math.sqrt(feed);
}

function nodeRadius(fork) {
  return tube(fork.fed) / 2 + AXES.nodeGrowth * (1 - Math.exp(-fork.age / AXES.nodeLife));
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

function drawClusters(t, tips) {
  const s = AXES.clipSize, half = s / 2, m = AXES.margin;
  // Room the scattered clips take around the cluster's centre.
  const spread = half + AXES.clipScatter;
  for (const cluster of space.clusters) {
    const n = cluster.clips.length;
    if (t < cluster.appear || t >= cluster.vanish) continue;
    const tip = tips.get(cluster.tip);
    if (!tip) continue;
    // The cluster sits beyond the tip, so the branch ends at its edge, and
    // keeps all of its clips within the frame.
    const ox = Math.min(W - m - spread, Math.max(m + spread, tip.x + tip.dx * half * 0.8));
    const oy = Math.min(H - m - spread, Math.max(m + spread, tip.y + tip.dy * half * 0.8));
    // Clips pop up in order and pop out in reverse order.
    cluster.clips.forEach((c, k) => {
      const start = cluster.appear + k * AXES.clipIn;
      const end = cluster.vanish - (n - 1 - k) * AXES.clipOut;
      if (t < start || t >= end) return;
      const sheet = c.sheet;
      const frame = Math.floor((t - start) * sheet.fps) % sheet.frames;
      const sx = (frame % sheet.columns) * sheet.width, sy = Math.floor(frame / sheet.columns) * sheet.height;
      ctx.save();
      ctx.translate(ox + c.dx, oy + c.dy);
      ctx.rotate(c.tilt);
      ctx.globalAlpha = AXES.clipAlpha;
      if (AXES.clipGrey) ctx.filter = "grayscale(1)";
      ctx.drawImage(sheet.image, sx, sy, sheet.width, sheet.height, -half, -half, s, s);
      ctx.filter = "none";
      ctx.globalAlpha = 1;
      ctx.strokeStyle = "#ffffff";
      ctx.lineWidth = AXES.clipOutline;
      ctx.strokeRect(-half, -half, s, s);
      ctx.restore();
    });
  }
}

function drawAxes(t) {
  const { edges, forks, tips, life, share, size } = figure(t);
  const [cx, cy] = AXES.centre;
  const phase = 2 * Math.PI * life / AXES.pulsePeriod;

  const hub = AXES.hub[0] + (AXES.hub[1] - AXES.hub[0]) * (size - AXES.startSize) / (1 - AXES.startSize);

  // The lines in solid white, and at a quarter of the resolution the source
  // of their glow, weighted by foreshortening and the outward pulse.
  const c = axesCtx, g = glowSourceCtx;
  c.clearRect(0, 0, W, H);
  c.fillStyle = "#ffffff";
  g.setTransform(1, 0, 0, 1, 0, 0);
  g.clearRect(0, 0, W / 4, H / 4);
  g.setTransform(0.25, 0, 0, 0.25, 0, 0);
  g.fillStyle = "#ffffff";
  for (const e of edges) {
    const w0 = tube(e.feed), w1 = e.fedEnd > 0 ? tube(e.fedEnd) : w0 * AXES.taperTip;
    edge(c, e.x, e.y, e.dx, e.dy, e.length, w0, w1);
    // The pulse runs outward: its phase falls with the distance from the hub.
    const mid = e.dist + e.length / 2;
    const pulse = 1 - AXES.pulse * (0.5 + 0.5 * Math.sin(phase - 2 * Math.PI * mid / AXES.pulseLength));
    g.globalAlpha = e.alpha * pulse;
    edge(g, e.x, e.y, e.dx, e.dy, e.length, w0, w1);
  }
  for (const f of forks) {
    const r = nodeRadius(f);
    c.beginPath();
    c.arc(f.x, f.y, r, 0, 2 * Math.PI);
    c.fill();
    g.globalAlpha = f.alpha;
    g.beginPath();
    g.arc(f.x, f.y, r, 0, 2 * Math.PI);
    g.fill();
  }
  for (const layer of [c, g]) {
    layer.globalAlpha = 1;
    layer.beginPath();
    layer.arc(cx, cy, hub, 0, 2 * Math.PI);
    layer.fill();
  }

  // Glow at a quarter of the resolution, bloom from it at an eighth, both
  // added under the sharp lines and stronger as the figure grows.
  glowCtx.clearRect(0, 0, W / 4, H / 4);
  glowCtx.filter = `blur(${AXES.glowBlur}px)`;
  glowCtx.drawImage(glowSource, 0, 0);
  glowCtx.filter = "none";
  bloomCtx.clearRect(0, 0, W / 8, H / 8);
  bloomCtx.filter = `blur(${AXES.bloomBlur}px)`;
  bloomCtx.drawImage(glowLayer, 0, 0, W / 8, H / 8);
  bloomCtx.filter = "none";
  const lerp = ([a, b]) => a + (b - a) * share;
  ctx.globalCompositeOperation = "lighter";
  ctx.globalAlpha = lerp(AXES.bloom);
  ctx.drawImage(bloomLayer, 0, 0, W, H);
  ctx.globalAlpha = lerp(AXES.glow);
  ctx.drawImage(glowLayer, 0, 0, W, H);
  ctx.globalCompositeOperation = "source-over";
  ctx.globalAlpha = 1;
  ctx.drawImage(axesLayer, 0, 0);
  drawClusters(t, tips);
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
