/* Axes 2: Athene grows from a coordinate system into a branching star.

   The style and the space of the first axes design (designs/axes.js),
   grown into the figure of Moe's sketch (athene/athene_axes_sketch.jpg):
   rays of unequal length from a hub, whose ends fork into twos and threes
   that fork again, and clusters of replaying body-search clips hanging at
   the ends of branches.

     space     the axes are the unit vectors of a space of AXES.dims
               dimensions, seen through a turning two-dimensional window, as
               in the first design. Every axis is a straight line through the
               centre; the hub is drawn as a dot where they meet.
     joining   two short orthogonal axes at first; the figure grows slowly
               to its full size, and the other axes grow out of the
               centre one after another. As they join, the two halves of
               each axis take on lengths of their own, so the hub turns from a
               cross into rays, some long, some stubs.
     branches  from the ends of the rays edges fork off, two or three at a
               time: one carries the ray on with a kink, the others open to
               the sides. Their ends fork again, the continuing edges more
               often than the side ones, up to AXES.branchDepth generations.
               Every edge stays straight and sways at its joint.
     clusters  a few body-search clips (athene/render.py cuts them into
               frame sheets) appear one after another at the tip of a far
               branch, overlapping, replay their four seconds over and over,
               and leave again in reverse order. When and how many is set in
               AXES.clusters. While a cluster is shown the network holds
               still: Athene's life stops and her reach, breath and tone are
               held, so the clips play in their colours on a frozen figure.
               Once they have left, the network moves and grows on from
               where it stopped.

   The voice drives Athene's life as in the first design: slow in silence,
   fast while she speaks. Level widens the figure and brightens its glow,
   each syllable makes one ray reach out, tone opens the forks.

   AXES holds the parameters of the design. */

"use strict";

const AXES = {
  dims: 6,              // dimensions of the space: twelve rays at the end of a clip
  radius: 560,          // px, half-length of an axis at rest
  centre: [W / 2, H / 2],
  margin: 70,           // px kept free at the frame's edges
  hub: 15,              // px, radius of the dot where the axes meet

  // Life: seconds of full-level speech plus `restRate` per second of time,
  // not counting the time the network is frozen.
  restRate: 0.2,

  // Size: the figure starts at `startSize` of its full size and reaches it
  // at `sizeFull` of the clip's life.
  startSize: 0.3, sizeFull: 0.8,

  // Turning of the window, in radians.
  tilt: 0.9, tiltHidden: 0.3, tiltRate: [0.12, 0.35], planesPerDim: 3,
  spin: 0.04, normalise: 0.8,

  // Joining, as shares of the clip's life.
  joinFirst: 0.1, joinLast: 0.5, joinCurve: 0.6, joinLife: 1.6,

  // Halves: the lasting length of each half-axis, as a share of the axis,
  // taken on between these shares of the clip's life.
  halves: [0.3, 1.3], halvesFirst: 0.08, halvesLast: 0.45,

  // Reaching, flicks and breath, as in the first design.
  reach: 0.25, reachRate: 0.5,
  flick: 0.4, flickRise: 0.12, flickFall: 0.5,
  breath: 0.12, breathSmooth: 0.25,

  // Branches. The first forks are born between these shares of the clip's
  // life; each later fork waits until its parent edge has grown.
  branchFirst: 0.2, branchLast: 0.8,
  branchDepth: 4,                        // generations of forks
  forkChance: [0.85, 0.6, 0.4, 0.25],    // chance that an end forks, per generation
  sideForkShare: 0.5,                    // side edges fork this much less often
  threeWay: 0.35,                        // share of forks with three edges instead of two
  carryLength: [0.55, 0.9],              // continuing edge, share of its parent's length
  sideLength: [0.3, 0.6],                // side edges
  carryKink: 0.3,                        // radians the continuing edge may bend
  sideAngle: [0.5, 1.0],                 // radians side edges open, before tone
  toneOpen: 0.25,                        // radians a bright voice opens them further
  sway: 0.18,                            // radians an edge sways at its joint
  branchLife: 2.0,                       // units of life an edge takes to grow
  forkWait: [0.3, 3.0],                  // units of life between an edge grown and its fork

  // Clusters of clips. Times are shares of the clip's duration; each
  // cluster takes the next `clips` frame sheets the renderer serves.
  clusters: [
    { appear: 0.33, vanish: 0.45, clips: 6 },
    { appear: 0.62, vanish: 0.74, clips: 6 },
  ],
  freeze: true,         // the network holds still while a cluster is shown
  freezeEase: 0.5,      // seconds the network takes to come to rest, and to move again
  clipSize: 280,        // px, side of a clip
  clipScatter: 140,     // px, largest offset of a clip from the cluster's centre
  clipTilt: 0.1,        // radians, largest tilt of a clip
  clipStagger: 0.4,     // seconds between clips appearing and leaving
  clipFade: 0.35,       // seconds a clip takes to appear or leave
  clipAlpha: 0.88,
  clipOutline: 3,       // px, white outline around each clip
  clipGrey: false,      // true shows the clips in greyscale, like the lines

  // Lines.
  width: [12, 6],       // px at the centre and at the end of a ray
  taper: 0.65,          // an edge ends at this share of its starting width
  minWidth: 3,
  faint: 0.45,          // brightness of a fully foreshortened axis
  glow: [0.35, 0.8], glowBlur: 7,
};

// ---- Preparation -------------------------------------------------------------

// Per-frame series are held while the network is frozen: life stands still,
// and breath, tone and each half-axis's flicks keep the value they had.
const space = {
  planes: [],
  joins: [],
  roots: [],      // per half-axis (2i for +, 2i+1 for −): {id, bias, reach, forks}
  life: new Float64Array(0),
  lifeEnd: 1,
  breath: new Float64Array(0),
  tone: new Float64Array(0),
  flick: [],      // per half-axis
  clusters: [],   // {appear, vanish, tip, clips: [{sheet, dx, dy, tilt}]}
};

// Frame sheets of the cluster clips: {image, frames, fps, width, height, columns, group}.
const sheets = [];

function lifeAt(t) {
  return space.life.length ? at(space.life, t, 0) : AXES.restRate * t;
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
// cluster's appearance until its last clip has left, eased at both ends.
function motionSeries(times) {
  const motion = new Float64Array(clip.frames).fill(1);
  if (!AXES.freeze) return motion;
  for (const { appear, vanish } of times) {
    const release = vanish + AXES.clipFade;
    for (let i = 0; i < clip.frames; i++) {
      const t = i / clip.fps;
      const still = ease((t - appear) / AXES.freezeEase) * ease((release - t) / AXES.freezeEase);
      motion[i] = Math.min(motion[i], 1 - still);
    }
  }
  return motion;
}

// The series followed while the network moves and held while it is frozen.
function held(series, motion) {
  const out = new Float64Array(series.length);
  let y = series.length ? series[0] : 0;
  for (let i = 0; i < series.length; i++) out[i] = y = motion[i] * series[i] + (1 - motion[i]) * y;
  return out;
}

// One half-axis reaching out after a syllable: a rise beginning 0.06 s
// before it, then an exponential fall.
function flickShape(dt) {
  const rise = ease((dt + 0.06) / AXES.flickRise);
  return rise * Math.exp(-Math.max(0, dt - AXES.flickRise + 0.06) / AXES.flickFall);
}

function buildSpace() {
  const random = makeRandom(11);
  const n = AXES.dims;
  const times = clusterTimes();
  const motion = motionSeries(times);
  space.life = new Float64Array(clip.frames ? clip.frames + 1 : 0);
  for (let i = 0; i < clip.frames; i++) {
    space.life[i + 1] = space.life[i] + motion[i] * (AXES.restRate + clip.level[i]) / clip.fps;
  }
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
    // Side edges open to alternate sides; with three, one to each side.
    const firstSide = random() < 0.5 ? 1 : -1;
    const edges = [];
    for (let k = 0; k < count; k++) {
      const carry = k === 0;
      const turn = carry
        ? AXES.carryKink * (2 * random() - 1)
        : (k === 1 ? firstSide : -firstSide) * between(random, AXES.sideAngle);
      const edgeBirth = birth + 0.4 * k * random();
      edges.push({
        id: ids++,
        birth: edgeBirth,
        carry,
        turn,
        length: between(random, carry ? AXES.carryLength : AXES.sideLength),
        sway: wave(random, AXES.reachRate),
        stretch: wave(random, AXES.reachRate),
        forks: forks(depth + 1, edgeBirth + AXES.branchLife, !carry),
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

  // Each syllable goes to one of the half-axes visible at its time.
  const raw = Array.from({ length: 2 * n }, () => new Float64Array(clip.frames));
  for (const [start, strength] of clip.onsets) {
    const life = lifeAt(start);
    const shown = space.joins.filter((join) => life > join + AXES.joinLife / 2).length;
    const target = raw[Math.floor(random() * 2 * shown)];
    const first = Math.max(0, Math.floor((start - 0.06) * clip.fps));
    const last = Math.min(clip.frames, Math.ceil((start + 5 * AXES.flickFall) * clip.fps));
    for (let i = first; i < last; i++) target[i] += strength * flickShape(i / clip.fps - start);
  }
  space.flick = raw.map((series) => held(series, motion));
  space.breath = held(clip.frames ? smoothBoth(clip.level, AXES.breathSmooth, clip.fps) : [], motion);
  space.tone = held(clip.tone.slice(0, clip.frames), motion);
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
      const score = Math.hypot(tip.x - cx, tip.y - cy) - (cramped ? W : 0);
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

// The figure at time t: its edges as {x, y, dx, dy, length, w0, w1, alpha},
// and the tip of every edge by id as {x, y, dx, dy}.
function figure(t) {
  const life = lifeAt(t);
  const tone = at(space.tone, t, 0.35);
  const n = AXES.dims;
  const grown = space.joins.map((join) => ease((life - join) / AXES.joinLife));
  const { p, q } = windowAt(life, grown);

  let sum = 0, weight = 0;
  for (let i = 0; i < n; i++) {
    sum += grown[i] * (p[i] * p[i] + q[i] * q[i]);
    weight += grown[i];
  }
  const mean = Math.sqrt(sum / weight);
  const breath = 1 + AXES.breath * at(space.breath, t, 0);
  const size = AXES.startSize + (1 - AXES.startSize) * ease(life / space.lifeEnd / AXES.sizeFull);
  const scale = AXES.radius * size * breath / Math.max(mean, 0.05) ** AXES.normalise;
  const halves = ease((life / space.lifeEnd - AXES.halvesFirst) / (AXES.halvesLast - AXES.halvesFirst));
  const open = AXES.toneOpen * tone;
  const [cx, cy] = AXES.centre;
  const edges = [], tips = new Map();

  const add = (id, x, y, angle, length, w0, alpha, w1 = Math.max(AXES.minWidth, w0 * AXES.taper)) => {
    const dx = Math.cos(angle), dy = Math.sin(angle);
    const len = fit(length, room(x, y, dx, dy));
    edges.push({ x, y, dx, dy, length: len, w0, w1, alpha });
    const tip = { x: x + dx * len, y: y + dy * len, dx, dy, angle, length: len, width: w1 };
    if (len > 1) tips.set(id, tip);
    return tip;
  };

  const grow = (forks, from, alpha) => {
    for (const e of forks) {
      if (life <= e.birth) continue;
      const g = ease((life - e.birth) / AXES.branchLife);
      const turn = e.carry ? e.turn : e.turn + Math.sign(e.turn) * open;
      const angle = from.angle + turn + AXES.sway * e.sway(life);
      const length = from.length * e.length * (1 + 0.25 * e.stretch(life)) * g;
      const tip = add(e.id, from.x, from.y, angle, length, from.width, alpha * (0.6 + 0.4 * g));
      grow(e.forks, tip, alpha);
    }
  };

  for (let i = 0; i < n; i++) {
    if (grown[i] <= 0) continue;
    const projected = Math.hypot(p[i], q[i]);
    if (projected < 1e-6) continue;
    const alpha = AXES.faint + (1 - AXES.faint) * Math.min(1, projected / mean);
    for (const sign of [1, -1]) {
      const half = 2 * i + (sign > 0 ? 0 : 1);
      const root = space.roots[half];
      const angle = Math.atan2(sign * q[i], sign * p[i]);
      const reach = (1 + (root.bias - 1) * halves) * (1 + AXES.reach * root.reach(life))
        + AXES.flick * at(space.flick[half] || [], t, 0);
      const tip = add(root.id, cx, cy, angle, scale * projected * reach * grown[i], AXES.width[0], alpha, AXES.width[1]);
      grow(root.forks, tip, alpha);
    }
  }
  return { edges, tips };
}

// ---- Drawing --------------------------------------------------------------------

const axesLayer = offscreen(W, H);
const axesCtx = axesLayer.getContext("2d");
const glowLayer = offscreen(W / 4, H / 4);
const glowCtx = glowLayer.getContext("2d");

// A straight edge tapering from w0 to w1, with a round end.
function edge(c, { x, y, dx, dy, length, w0, w1 }) {
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
  for (const cluster of space.clusters) {
    const n = cluster.clips.length, gap = AXES.clipStagger;
    if (t < cluster.appear || t > cluster.vanish + AXES.clipFade) continue;
    const tip = tips.get(cluster.tip);
    if (!tip) continue;
    // The cluster sits beyond the tip, so the branch ends at its edge.
    const ox = Math.min(W - m - half, Math.max(m + half, tip.x + tip.dx * half * 0.8));
    const oy = Math.min(H - m - half, Math.max(m + half, tip.y + tip.dy * half * 0.8));
    // Clips appear in order and leave in reverse order.
    cluster.clips.forEach((c, k) => {
      const start = cluster.appear + k * gap, end = cluster.vanish - (n - 1 - k) * gap;
      const shown = ease((t - start) / AXES.clipFade) * ease((end + AXES.clipFade - t) / AXES.clipFade);
      if (shown <= 0) return;
      const sheet = c.sheet;
      const frame = Math.floor(Math.max(0, t - start) * sheet.fps) % sheet.frames;
      const sx = (frame % sheet.columns) * sheet.width, sy = Math.floor(frame / sheet.columns) * sheet.height;
      const size = s * (0.85 + 0.15 * shown);
      ctx.save();
      ctx.translate(ox + c.dx, oy + c.dy);
      ctx.rotate(c.tilt);
      ctx.globalAlpha = AXES.clipAlpha * shown;
      if (AXES.clipGrey) ctx.filter = "grayscale(1)";
      ctx.drawImage(sheet.image, sx, sy, sheet.width, sheet.height, -size / 2, -size / 2, size, size);
      ctx.filter = "none";
      ctx.globalAlpha = shown;
      ctx.strokeStyle = "#ffffff";
      ctx.lineWidth = AXES.clipOutline;
      ctx.strokeRect(-size / 2, -size / 2, size, size);
      ctx.restore();
    });
  }
}

function drawAxes(t) {
  const { edges, tips } = figure(t);
  const level = at(clip.level, t, 0);
  const [cx, cy] = AXES.centre;

  const c = axesCtx;
  c.clearRect(0, 0, W, H);
  c.fillStyle = "#ffffff";
  for (const e of edges) {
    c.globalAlpha = e.alpha;
    edge(c, e);
  }
  c.globalAlpha = 1;
  c.beginPath();
  c.arc(cx, cy, AXES.hub, 0, 2 * Math.PI);
  c.fill();

  glowCtx.clearRect(0, 0, W / 4, H / 4);
  glowCtx.filter = `blur(${AXES.glowBlur}px)`;
  glowCtx.drawImage(axesLayer, 0, 0, W / 4, H / 4);
  glowCtx.filter = "none";
  ctx.globalAlpha = AXES.glow[0] + (AXES.glow[1] - AXES.glow[0]) * level;
  ctx.drawImage(glowLayer, 0, 0, W, H);
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
