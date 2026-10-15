/* Planetary: a blue planet read by the lines of a machine that watches it.

   The planet stands for the world, the points and lines that move around and
   across it for the planetary computation that analyses everything going on
   there: Athene, goddess of war and strategy. After the moodboard in
   athene/moodboard_planetary: the Northern Circle star maps (polar
   projection, dotted rings, crosshair, fine network lines), the circular
   maps of Frédérique Aït-Touati's Terra Forma, a radar interface, and a dark
   orb under a triangulated mesh.

     planet   drawn per pixel by WebGL: continents with contour lines and a
              lit coast, clouds, a graticule, day and night, an atmosphere in
              Signal. It turns once in 90 s; the voice brightens its contour
              lines and graticule, the planet being read.
     tracks   points on the surface, in clusters, turning with it; links to
              their neighbours run across it as great-circle arcs.
     boxes    detections in the style of Apollon's display (annotate.DISPLAY):
              corner brackets in Bone, the class in IBM Plex Mono capitals,
              the confidence in Michroma. The louder the voice, the more
              tracks are boxed; a box closes in on its track as it opens.
     locks    each syllable locks one track in Signal, beams it from the
              nearest satellite and sends packets along its links.
     sweep    a radar sweep around the planet, faster with the voice; tracks
              it passes flash.
     ring     a degree ring with ticks and a crosshair, after the star maps;
              satellites on their orbits around the planet.

   Every motion follows the level smoothed both ways and eases in and out. */

"use strict";

const PLANET = {
  radius: 560,
  tiltToward: 0.32,            // radians the north pole leans towards the audience
  tiltSide: 0.41,              // radians the axis leans sideways (the Earth's 23.4°)
  turn: 2 * Math.PI / 90,      // radians per second
  clouds: 2 * Math.PI / 240,   // radians per second the clouds drift over the ground
  light: [-0.55, 0.45, 0.7],   // towards the sun, in view space
  size: 1520,                  // px, side of the square drawn around the planet
};

const TRACKS = {
  clusters: 14,
  perCluster: [3, 9],
  spread: 0.12,                // radians around a cluster's centre
  links: 3,                    // nearest neighbours a track links to …
  linkMax: 0.55,               // … within this many radians
  threshold: [0.35, 1.2],      // smoothed level at which a track's box begins to open (some never)
  opening: 0.2,                // level over which it opens fully
  box: [44, 96],               // px
  labelled: 0.3,               // share of boxes that carry a label
  classes: ["PERSON", "MENGE", "FAHRZEUG", "KONVOI", "SCHIFF", "FLUGZEUG", "GEBÄUDE", "FUNK"],
};

const LOCK = {
  inner: 0.35,                 // a syllable locks a track at least this far onto the visible face
  rise: 0.25, hold: 0.6, fall: 1.0,   // seconds
  packet: 0.8,                 // seconds a packet takes along a link
  beam: 1.1,                   // seconds a satellite's beam lasts
};

const ORBITS = {
  count: 6,
  radius: [1.12, 1.3],         // fractions of the planet's radius
  period: [40, 110],           // seconds per orbit
};

const SWEEP = {
  rest: 2 * Math.PI / 14,      // radians per second in silence
  voice: 2 * Math.PI / 6,      // radians added per second of full level
  trail: 0.7,                  // radians of the fading wake
  ping: 0.6,                   // radians behind the sweep over which a passed track fades
};

const RING = { radius: 1.38, dots: 1.07 };   // fractions of the planet's radius
const LINE = { fine: 1.5, box: 2.5 };        // px
const TEXT = { label: 22, ring: 20 };        // px
const SMOOTH = 0.3;                          // seconds; the level smoothed both ways

const prng = makeRandom(23);
const pick = ([a, b]) => a + (b - a) * prng();

// Series derived from the level in prepare; empty without a clip.
Object.assign(clip, { soft: [], softSum: [] });

// ---- Vectors ---------------------------------------------------------------

// The same rotations as the shader's, so tracks sit on its ground.
const rotX = ([x, y, z], a) => [x, Math.cos(a) * y - Math.sin(a) * z, Math.sin(a) * y + Math.cos(a) * z];
const rotY = ([x, y, z], a) => [Math.cos(a) * x + Math.sin(a) * z, y, -Math.sin(a) * x + Math.cos(a) * z];
const rotZ = ([x, y, z], a) => [Math.cos(a) * x - Math.sin(a) * y, Math.sin(a) * x + Math.cos(a) * y, z];
const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
const normalize = (v) => { const l = Math.hypot(...v); return v.map((c) => c / l); };

function unitRandom(rand) {
  const z = 2 * rand() - 1, a = 2 * Math.PI * rand(), s = Math.sqrt(1 - z * z);
  return [s * Math.cos(a), z, s * Math.sin(a)];
}

// A point on the planet (its own frame) seen from the audience at a turn.
function toView(q, turn) {
  return rotX(rotZ(rotY(q, -turn), PLANET.tiltSide), PLANET.tiltToward);
}

// View space in planet radii to frame pixels.
function toScreen(v) {
  return [LAYOUT.orbX + PLANET.radius * v[0], LAYOUT.orbY - PLANET.radius * v[1]];
}

// The great circle from a to b at s in [0, 1].
function slerp(a, b, s) {
  const w = Math.acos(Math.min(1, Math.max(-1, dot(a, b))));
  if (w < 1e-6) return a;
  const k0 = Math.sin((1 - s) * w) / Math.sin(w), k1 = Math.sin(s * w) / Math.sin(w);
  return [k0 * a[0] + k1 * b[0], k0 * a[1] + k1 * b[1], k0 * a[2] + k1 * b[2]];
}

// ---- Fixed shapes ----------------------------------------------------------

// Tracks in clusters, as settlements, harbours and roads gather them.
const TRACK_SET = [];
for (let c = 0; c < TRACKS.clusters; c++) {
  const centre = unitRandom(prng);
  const count = Math.round(pick(TRACKS.perCluster));
  for (let k = 0; k < count; k++) {
    const offset = [0, 1, 2].map(() => TRACKS.spread * (2 * prng() - 1));
    TRACK_SET.push({
      p: normalize(centre.map((v, i) => v + offset[i])),
      threshold: pick(TRACKS.threshold),
      box: pick(TRACKS.box),
      labelled: prng() < TRACKS.labelled,
      label: `${TRACKS.classes[Math.floor(prng() * TRACKS.classes.length)]} ${String(Math.floor(prng() * 9000) + 1000)}`,
      confidence: 0.55 + 0.4 * prng(),
      neighbours: [],
    });
  }
}

// Each track linked to its nearest neighbours.
const LINKS = [];
{
  const seen = new Set();
  TRACK_SET.forEach((a, i) => {
    TRACK_SET
      .map((b, j) => [j, Math.acos(Math.min(1, dot(a.p, b.p)))])
      .filter(([j, w]) => j !== i && w < TRACKS.linkMax)
      .sort((x, y) => x[1] - y[1])
      .slice(0, TRACKS.links)
      .forEach(([j]) => {
        const key = i < j ? `${i}/${j}` : `${j}/${i}`;
        if (seen.has(key)) return;
        seen.add(key);
        LINKS.push([i, j]);
        a.neighbours.push(j);
        TRACK_SET[j].neighbours.push(i);
      });
  });
}

const ORBIT_SET = Array.from({ length: ORBITS.count }, () => {
  const normal = unitRandom(prng);
  const e1 = normalize(cross(normal, Math.abs(normal[1]) < 0.9 ? [0, 1, 0] : [1, 0, 0]));
  return {
    e1, e2: cross(normal, e1),
    radius: pick(ORBITS.radius),
    period: pick(ORBITS.period),
    phase: 2 * Math.PI * prng(),
  };
});

// View-space position of a satellite at time t, in planet radii.
function satellite(o, t) {
  const u = o.phase + 2 * Math.PI * t / o.period;
  return [0, 1, 2].map((k) => o.radius * (Math.cos(u) * o.e1[k] + Math.sin(u) * o.e2[k]));
}

const behindPlanet = (v) => v[2] < 0 && v[0] * v[0] + v[1] * v[1] < 1;

// ---- Planet (WebGL) --------------------------------------------------------

const VERTEX = `#version 300 es
void main() {
  vec2 p = vec2((gl_VertexID << 1) & 2, gl_VertexID & 2);
  gl_Position = vec4(p * 2.0 - 1.0, 0.0, 1.0);
}`;

const FRAGMENT = `#version 300 es
precision highp float;
uniform vec2 uSize;
uniform float uRadius;
uniform float uTurn;
uniform float uClouds;
uniform vec2 uTilt;        // towards the audience, sideways
uniform vec3 uLight;
uniform float uRead;       // 0 to 1: how strongly the planet is being read
out vec4 outColor;

const vec3 DEEP = vec3(0.016, 0.043, 0.102);
const vec3 OCEAN = vec3(0.043, 0.129, 0.278);
const vec3 LOW = vec3(0.106, 0.247, 0.478);
const vec3 HIGH = vec3(0.227, 0.435, 0.769);
const vec3 PEAK = vec3(0.612, 0.753, 0.969);
const vec3 COAST = vec3(0.498, 0.690, 1.0);
const vec3 CONTOUR = vec3(0.561, 0.714, 0.949);
const vec3 CLOUD = vec3(0.902, 0.933, 0.988);
const vec3 SIGNAL = vec3(0.357, 0.608, 1.0);
const float SEA = 0.5;

vec3 rotX(vec3 v, float a) { float c = cos(a), s = sin(a); return vec3(v.x, c * v.y - s * v.z, s * v.y + c * v.z); }
vec3 rotY(vec3 v, float a) { float c = cos(a), s = sin(a); return vec3(c * v.x + s * v.z, v.y, -s * v.x + c * v.z); }
vec3 rotZ(vec3 v, float a) { float c = cos(a), s = sin(a); return vec3(c * v.x - s * v.y, s * v.x + c * v.y, v.z); }

// Value noise and its sum over octaves, 0 to 1.
float hash(vec3 p) {
  p = fract(p * 0.3183099 + 0.1);
  p *= 17.0;
  return fract(p.x * p.y * p.z * (p.x + p.y + p.z));
}
float noise(vec3 x) {
  vec3 i = floor(x), f = fract(x);
  f = f * f * (3.0 - 2.0 * f);
  return mix(mix(mix(hash(i), hash(i + vec3(1, 0, 0)), f.x),
                 mix(hash(i + vec3(0, 1, 0)), hash(i + vec3(1, 1, 0)), f.x), f.y),
             mix(mix(hash(i + vec3(0, 0, 1)), hash(i + vec3(1, 0, 1)), f.x),
                 mix(hash(i + vec3(0, 1, 1)), hash(i + vec3(1, 1, 1)), f.x), f.y), f.z);
}
float fbm(vec3 p) {
  float v = 0.0, a = 0.5;
  for (int i = 0; i < 6; i++) {
    v += a * noise(p);
    p = p * 2.03 + vec3(1.7, 9.2, 5.3);
    a *= 0.5;
  }
  return v / 0.984;
}

// 1 on lines every step of x, anti-aliased to about a pixel.
float lines(float x, float step) {
  float d = abs(fract(x / step + 0.5) - 0.5) * step;
  return 1.0 - smoothstep(0.0, fwidth(x) * 1.2, d);
}

void main() {
  vec2 p = (gl_FragCoord.xy - 0.5 * uSize) / uRadius;
  float r = length(p);
  float aa = 1.5 / uRadius;
  float halo = 0.28 * exp(-max(r - 1.0, 0.0) * 14.0);
  if (r > 1.0 + aa) {
    outColor = vec4(SIGNAL * halo, halo);
    return;
  }

  vec3 n = vec3(p, sqrt(max(0.0, 1.0 - min(r * r, 1.0))));
  vec3 q = rotY(rotZ(rotX(n, -uTilt.x), -uTilt.y), uTurn);

  float e = fbm(q * 1.7 + vec3(3.1, 1.3, 7.7));
  float land = smoothstep(SEA - fwidth(e), SEA + fwidth(e), e);
  vec3 ocean = mix(DEEP, OCEAN, smoothstep(0.3, SEA, e));
  vec3 ground = mix(LOW, HIGH, smoothstep(SEA, SEA + 0.15, e));
  ground = mix(ground, PEAK, smoothstep(SEA + 0.15, SEA + 0.28, e));
  vec3 col = mix(ocean, ground, land);
  col = mix(col, CONTOUR, lines((e - SEA) / 0.025, 1.0) * land * (0.2 + 0.4 * uRead));
  col = mix(col, COAST, (1.0 - smoothstep(0.0, fwidth(e) * 1.5, abs(e - SEA))) * 0.8);

  float c = fbm(rotY(q, uClouds) * 2.6 + vec3(11.0, 4.0, 2.0));
  col = mix(col, CLOUD, smoothstep(0.56, 0.78, c) * 0.5);

  float day = smoothstep(-0.2, 0.55, dot(n, uLight));
  col *= 0.16 + 0.84 * day;

  float lat = degrees(asin(clamp(q.y, -1.0, 1.0)));
  float lon = degrees(atan(q.z, q.x));
  float grid = max(lines(lat, 15.0), lines(lon, 15.0) * smoothstep(80.0, 70.0, abs(lat)));
  col = mix(col, SIGNAL, grid * (0.1 + 0.3 * uRead));

  col += SIGNAL * pow(1.0 - n.z, 3.0) * 0.45 * (0.3 + 0.7 * day);

  float cover = 1.0 - smoothstep(1.0 - aa, 1.0, r);
  outColor = vec4(col * cover + SIGNAL * halo * (1.0 - cover), cover + halo * (1.0 - cover));
}`;

const planetCanvas = offscreen(PLANET.size, PLANET.size);
const gl = planetCanvas.getContext("webgl2", { premultipliedAlpha: true, preserveDrawingBuffer: true, antialias: false });
if (!gl) throw new Error("WebGL2 is not available");

function compile(type, source) {
  const shader = gl.createShader(type);
  gl.shaderSource(shader, source);
  gl.compileShader(shader);
  if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(shader));
  return shader;
}

const program = gl.createProgram();
gl.attachShader(program, compile(gl.VERTEX_SHADER, VERTEX));
gl.attachShader(program, compile(gl.FRAGMENT_SHADER, FRAGMENT));
gl.linkProgram(program);
if (!gl.getProgramParameter(program, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(program));
const uniform = Object.fromEntries(
  ["uSize", "uRadius", "uTurn", "uClouds", "uTilt", "uLight", "uRead"]
    .map((name) => [name, gl.getUniformLocation(program, name)]));

function drawPlanet(t, read) {
  const s = PLANET.size;
  gl.viewport(0, 0, s, s);
  gl.clearColor(0, 0, 0, 0);
  gl.clear(gl.COLOR_BUFFER_BIT);
  gl.useProgram(program);
  gl.uniform2f(uniform.uSize, s, s);
  gl.uniform1f(uniform.uRadius, PLANET.radius);
  gl.uniform1f(uniform.uTurn, PLANET.turn * t);
  gl.uniform1f(uniform.uClouds, PLANET.clouds * t);
  gl.uniform2f(uniform.uTilt, PLANET.tiltToward, PLANET.tiltSide);
  gl.uniform3fv(uniform.uLight, normalize(PLANET.light));
  gl.uniform1f(uniform.uRead, read);
  gl.drawArrays(gl.TRIANGLES, 0, 3);
  ctx.drawImage(planetCanvas, LAYOUT.orbX - s / 2, LAYOUT.orbY - s / 2);
}

// ---- Locks -----------------------------------------------------------------

// The track and satellite each syllable locks, chosen once per syllable from
// the tracks well onto the visible face at its time.
const locks = new Map();

function lockOf(j) {
  if (!locks.has(j)) {
    const start = clip.onsets[j][0];
    const rand = makeRandom(7000 + j);
    const turn = PLANET.turn * start;
    const visible = TRACK_SET.map((tr, i) => [i, toView(tr.p, turn)[2]]).filter(([, z]) => z > LOCK.inner);
    const track = visible.length ? visible[Math.floor(rand() * visible.length)][0] : 0;
    const [tx, ty] = toScreen(toView(TRACK_SET[track].p, turn));
    let sat = 0, best = Infinity;
    ORBIT_SET.forEach((o, k) => {
      const v = satellite(o, start);
      if (behindPlanet(v)) return;
      const [sx, sy] = toScreen(v);
      const d = Math.hypot(sx - tx, sy - ty);
      if (d < best) { best = d; sat = k; }
    });
    locks.set(j, { track, sat });
  }
  return locks.get(j);
}

// Locks under way at t: their syllable, lock and age.
function activeLocks(t) {
  const span = LOCK.rise + LOCK.hold + LOCK.fall;
  const out = [];
  clip.onsets.forEach(([start], j) => {
    const age = t - start;
    if (age >= 0 && age < span) out.push({ j, age, ...lockOf(j) });
  });
  return out;
}

function lockEnvelope(age) {
  return ease(age / LOCK.rise) * (1 - ease((age - LOCK.rise - LOCK.hold) / LOCK.fall));
}

// ---- Overlay ---------------------------------------------------------------

function ringRadius() {
  return PLANET.radius * RING.radius;
}

function drawRing() {
  const { orbX, orbY } = LAYOUT;
  const r = ringRadius();
  ctx.strokeStyle = COLOR.steel;
  ctx.lineWidth = LINE.fine;
  ctx.globalAlpha = 0.45;
  ctx.beginPath();
  ctx.arc(orbX, orbY, r, 0, 2 * Math.PI);
  for (let deg = 0; deg < 360; deg += 2) {
    const a = -Math.PI / 2 + deg * Math.PI / 180, len = deg % 10 === 0 ? 22 : 10;
    ctx.moveTo(orbX + r * Math.cos(a), orbY + r * Math.sin(a));
    ctx.lineTo(orbX + (r + len) * Math.cos(a), orbY + (r + len) * Math.sin(a));
  }
  ctx.stroke();

  ctx.font = `600 ${TEXT.ring}px "IBM Plex Mono"`;
  ctx.letterSpacing = "0.12em";
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillStyle = COLOR.steel;
  for (let deg = 0; deg < 360; deg += 30) {
    const a = -Math.PI / 2 + deg * Math.PI / 180;
    ctx.fillText(String(deg).padStart(3, "0"), orbX + (r - 34) * Math.cos(a), orbY + (r - 34) * Math.sin(a));
  }

  // The dotted circle close around the planet.
  const d = PLANET.radius * RING.dots;
  ctx.globalAlpha = 0.5;
  ctx.beginPath();
  for (let deg = 0; deg < 360; deg += 1.5) {
    const a = deg * Math.PI / 180;
    ctx.moveTo(orbX + d * Math.cos(a) + 2, orbY + d * Math.sin(a));
    ctx.arc(orbX + d * Math.cos(a), orbY + d * Math.sin(a), 2, 0, 2 * Math.PI);
  }
  ctx.fill();
  ctx.globalAlpha = 1;
}

function drawCrosshair() {
  const { orbX, orbY } = LAYOUT;
  const r = ringRadius();
  ctx.strokeStyle = COLOR.steel;
  ctx.lineWidth = LINE.fine;
  ctx.globalAlpha = 0.22;
  ctx.setLineDash([4, 12]);
  ctx.beginPath();
  ctx.moveTo(orbX - r, orbY);
  ctx.lineTo(orbX + r, orbY);
  ctx.moveTo(orbX, orbY - r);
  ctx.lineTo(orbX, orbY + r);
  ctx.stroke();
  ctx.setLineDash([]);
  ctx.globalAlpha = 1;
}

// Orbits behind the planet before it is drawn, those in front after.
function drawOrbits(t, front) {
  ctx.lineWidth = LINE.fine;
  ctx.strokeStyle = COLOR.steel;
  ctx.globalAlpha = front ? 0.4 : 0.18;
  ctx.setLineDash(front ? [] : [6, 10]);
  ctx.beginPath();
  for (const o of ORBIT_SET) {
    let prev = null;
    for (let k = 0; k <= 180; k++) {
      const u = 2 * Math.PI * k / 180;
      const v = [0, 1, 2].map((i) => o.radius * (Math.cos(u) * o.e1[i] + Math.sin(u) * o.e2[i]));
      const [x, y] = toScreen(v);
      const inFront = v[2] >= 0;
      if (prev && prev.inFront === front && inFront === front) ctx.lineTo(x, y);
      else ctx.moveTo(x, y);
      prev = { inFront };
    }
  }
  ctx.stroke();
  ctx.setLineDash([]);

  ctx.globalAlpha = front ? 1 : 0.4;
  ctx.strokeStyle = COLOR.bone;
  ctx.fillStyle = COLOR.bone;
  for (const o of ORBIT_SET) {
    const v = satellite(o, t);
    if ((v[2] >= 0) !== front) continue;
    const [x, y] = toScreen(v);
    ctx.strokeRect(x - 7, y - 7, 14, 14);
    ctx.fillRect(x - 2, y - 2, 4, 4);
  }
  ctx.globalAlpha = 1;
}

// The radar sweep and its fading wake.
function drawSweep(angle) {
  const { orbX, orbY } = LAYOUT;
  const r = ringRadius();
  const wake = ctx.createConicGradient(angle - SWEEP.trail, orbX, orbY);
  wake.addColorStop(0, "rgba(91, 155, 255, 0)");
  wake.addColorStop(SWEEP.trail / (2 * Math.PI), "rgba(91, 155, 255, 0.16)");
  wake.addColorStop(SWEEP.trail / (2 * Math.PI) + 0.0001, "rgba(91, 155, 255, 0)");
  ctx.fillStyle = wake;
  ctx.beginPath();
  ctx.moveTo(orbX, orbY);
  ctx.arc(orbX, orbY, r, angle - SWEEP.trail, angle);
  ctx.closePath();
  ctx.fill();
  ctx.strokeStyle = COLOR.signal;
  ctx.lineWidth = LINE.fine;
  ctx.globalAlpha = 0.7;
  ctx.beginPath();
  ctx.moveTo(orbX, orbY);
  ctx.lineTo(orbX + r * Math.cos(angle), orbY + r * Math.sin(angle));
  ctx.stroke();
  ctx.globalAlpha = 1;
}

function drawLinks(turn, opened, locked) {
  ctx.strokeStyle = COLOR.signal;
  ctx.lineWidth = LINE.fine;
  for (const [a, b] of LINKS) {
    const pa = TRACK_SET[a].p, pb = TRACK_SET[b].p;
    const strength = Math.min(0.9, 0.12 + 0.45 * Math.max(opened[a], opened[b]) + 0.45 * Math.max(locked[a], locked[b]));
    const mid = toView(slerp(pa, pb, 0.5), turn);
    if (mid[2] <= 0) continue;
    ctx.globalAlpha = strength * ease(mid[2] / 0.25);
    ctx.beginPath();
    let drawing = false;
    for (let k = 0; k <= 12; k++) {
      const v = toView(slerp(pa, pb, k / 12), turn);
      const [x, y] = toScreen(v);
      if (v[2] > 0 && drawing) ctx.lineTo(x, y);
      else ctx.moveTo(x, y);
      drawing = v[2] > 0;
    }
    ctx.stroke();
  }
  ctx.globalAlpha = 1;
}

function brackets(cx, cy, size) {
  const h = size / 2, arm = size * 0.28;
  ctx.beginPath();
  for (const sx of [-1, 1]) {
    for (const sy of [-1, 1]) {
      ctx.moveTo(cx + sx * h, cy + sy * (h - arm));
      ctx.lineTo(cx + sx * h, cy + sy * h);
      ctx.lineTo(cx + sx * (h - arm), cy + sy * h);
    }
  }
  ctx.stroke();
}

function labelFont(part) {
  ctx.font = part === "text" ? `600 ${TEXT.label}px "IBM Plex Mono"` : `400 ${TEXT.label}px Michroma`;
  ctx.letterSpacing = part === "text" ? "0.12em" : "0px";
}

// The tag a label occupies: [x, y, width, height].
function labelRect(l) {
  labelFont("text");
  l.w = ctx.measureText(l.text).width;
  labelFont("value");
  const v = ctx.measureText(l.value).width;
  return [l.x - 4, l.y - TEXT.label - 4, l.w + v + 22, TEXT.label + 10];
}

// Labels in order of priority; one that would overlap a label already set
// is left out.
function drawLabels(candidates) {
  const placed = [];
  const overlaps = (a, b) => a[0] < b[0] + b[2] + 6 && b[0] < a[0] + a[2] + 6 && a[1] < b[1] + b[3] + 6 && b[1] < a[1] + a[3] + 6;
  candidates.sort((a, b) => b.priority - a.priority);
  for (const l of candidates) {
    const rect = labelRect(l);
    if (placed.some((p) => overlaps(p, rect))) continue;
    placed.push(rect);
    label(l, rect);
  }
  ctx.globalAlpha = 1;
}

// A label above a box: the class on a black tag, the confidence after it.
function label({ x, y, text, value, valueColor, alpha, w }, rect) {
  ctx.textAlign = "left";
  ctx.textBaseline = "alphabetic";
  ctx.fillStyle = COLOR.ground;
  ctx.globalAlpha = alpha * 0.7;
  ctx.fillRect(...rect);
  ctx.globalAlpha = alpha;
  ctx.fillStyle = COLOR.bone;
  labelFont("text");
  ctx.fillText(text, x, y);
  ctx.fillStyle = valueColor;
  labelFont("value");
  ctx.fillText(value, x + w + 12, y);
}

function drawTracks(turn, sweep, opened, locked) {
  const labels = [];
  TRACK_SET.forEach((tr, i) => {
    const v = toView(tr.p, turn);
    if (v[2] <= 0) return;
    const limb = ease(v[2] / 0.25);
    const [x, y] = toScreen(v);
    const screenAngle = Math.atan2(y - LAYOUT.orbY, x - LAYOUT.orbX);
    const lag = (((sweep - screenAngle) % (2 * Math.PI)) + 2 * Math.PI) % (2 * Math.PI);
    const ping = Math.exp(-lag / SWEEP.ping);
    const open = opened[i], lock = locked[i];

    ctx.fillStyle = COLOR.bone;
    ctx.globalAlpha = limb * (0.35 + 0.65 * Math.max(ping, open, lock));
    ctx.fillRect(x - 3, y - 3, 6, 6);

    if (ping > 0.05) {
      ctx.strokeStyle = COLOR.signal;
      ctx.lineWidth = LINE.fine;
      ctx.globalAlpha = 0.7 * ping * limb;
      ctx.beginPath();
      ctx.arc(x, y, 8 + 22 * (1 - ping), 0, 2 * Math.PI);
      ctx.stroke();
    }

    ctx.lineWidth = LINE.box;
    if (open * (1 - lock) > 0.01) {
      ctx.strokeStyle = COLOR.bone;
      ctx.globalAlpha = open * (1 - lock) * limb;
      brackets(x, y, tr.box * (1 + 0.8 * (1 - open)));
    }
    if (lock > 0.01) {
      ctx.strokeStyle = COLOR.signal;
      ctx.globalAlpha = lock * limb;
      brackets(x, y, tr.box * (1 + 0.8 * (1 - lock)));
    }

    const shown = Math.max(tr.labelled ? ease((open - 0.6) / 0.3) : 0, lock);
    if (shown > 0.01) {
      const size = tr.box * (1 + 0.8 * (1 - Math.max(open, lock)));
      const confidence = tr.confidence + (0.99 - tr.confidence) * lock;
      labels.push({
        x: x - size / 2, y: y - size / 2 - 12, text: tr.label, value: confidence.toFixed(2),
        valueColor: lock > 0.5 ? COLOR.signal : COLOR.bone, alpha: shown * limb,
        priority: lock > 0 ? 2 + lock : open,
      });
    }
  });
  drawLabels(labels);
}

// Packets along a locked track's links, and the satellite's beam onto it.
function drawLockLines(t, turn, under) {
  for (const { age, track, sat } of under) {
    const tr = TRACK_SET[track];
    const target = toView(tr.p, turn);
    if (target[2] <= 0) continue;
    const limb = ease(target[2] / 0.25);
    const [tx, ty] = toScreen(target);

    if (age < LOCK.packet) {
      ctx.fillStyle = COLOR.bone;
      for (const k of tr.neighbours) {
        for (const [back, alpha] of [[0, 1], [0.06, 0.5], [0.12, 0.25]]) {
          const s = ease(age / LOCK.packet) - back;
          if (s <= 0) continue;
          const v = toView(slerp(tr.p, TRACK_SET[k].p, s), turn);
          if (v[2] <= 0) continue;
          const [x, y] = toScreen(v);
          ctx.globalAlpha = alpha * limb * (1 - 0.5 * s);
          ctx.fillRect(x - 4, y - 4, 8, 8);
        }
      }
    }

    if (age < LOCK.beam) {
      const v = satellite(ORBIT_SET[sat], t);
      if (behindPlanet(v)) continue;
      const [sx, sy] = toScreen(v);
      ctx.strokeStyle = COLOR.signal;
      ctx.lineWidth = LINE.box;
      ctx.globalAlpha = 0.8 * limb * ease(age / 0.15) * (1 - ease((age - 0.15) / (LOCK.beam - 0.15)));
      ctx.beginPath();
      ctx.moveTo(sx, sy);
      ctx.lineTo(tx, ty);
      ctx.stroke();
    }
  }
  ctx.globalAlpha = 1;
}

registerDesign({
  prepare(c) {
    c.soft = smoothBoth(c.level, SMOOTH, c.fps);
    // Seconds of full smoothed level up to each frame, for the sweep's turn.
    c.softSum = new Float64Array(c.frames + 1);
    for (let i = 0; i < c.frames; i++) c.softSum[i + 1] = c.softSum[i] + c.soft[i] / c.fps;
  },

  drawOrb(t) {
    const soft = at(clip.soft, t, 0);
    const turn = PLANET.turn * t;
    const sweep = -Math.PI / 2 + SWEEP.rest * t + SWEEP.voice * at(clip.softSum, t, 0);

    const opened = TRACK_SET.map((tr) => ease((soft - tr.threshold) / TRACKS.opening));
    const locked = TRACK_SET.map(() => 0);
    const under = activeLocks(t);
    for (const { age, track } of under) locked[track] = Math.max(locked[track], lockEnvelope(age));

    drawRing();
    drawOrbits(t, false);
    drawPlanet(t, soft);
    drawCrosshair();
    drawSweep(sweep);
    drawLinks(turn, opened, locked);
    drawLockLines(t, turn, under);
    drawTracks(turn, sweep, opened, locked);
    drawOrbits(t, true);
  },
});
