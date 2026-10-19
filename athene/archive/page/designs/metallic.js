/* Metallic: a chrome sphere, and detection lines flitting around it.

   The sphere reflects an abstract Futurist field in the colours of the
   painterly design (painterly.js), cut clean: flat colours with hard,
   jagged edges, rust, peach and cream against blue, with no centre. The
   field is one function of direction in the shader (environment), which an
   image can replace.

     surround   a studio backdrop, steel blue above and dark below; jagged
                shards and long blades scattered all round, after the
                shards and facets of the moodboard (athene/moodboard_itfuturism);
                rectangular strokes among them, laid at jagged angles; two
                tall lights behind the sphere that make bright crescents
                along its rim, and two lights for the highlights.
     voice      the strokes stream sideways past the shards, and with
                the level align with the stream and stretch into speed lines;
                each syllable jolts a few shards, which turn and shift, then
                settle; the surface ripples like liquid metal, finer for
                bright sounds. The whole field sways slowly.
     boxes      small detection boxes, corner brackets in Bone, hovering over
                and around the sphere. The louder the voice, the more of
                them; each closes in on its spot as it appears.
     darts      each syllable sends a few boxes darting to new spots, a thin
                line marking the way for a moment, and locks one in Signal.

   Every motion follows the level smoothed both ways and eases in and out;
   darts ease out. */

"use strict";

const SPHERE = {
  radius: 620,                 // px
  supersample: 2,              // drawn at twice the size and scaled down
  sway: [[0.22, 47], [0.12, 29]],   // radians and seconds of the field's slow sway
  ripple: [0.03, 0.25],        // surface ripple at rest and at full level
  flowRest: 0.05,              // ripple drift per second in silence
  flowVoice: 0.5,              // added per second of full level
};

const FIELD = {
  stream: 0.5,                 // radians the strokes stream per second of full level
  swirlTime: 0.35,             // seconds the strokes take to align with the level
};

// Shard jolts; SHARDS must match the shader's.
const SHARDS = 70;
const JOLT = {
  perSyllable: [2, 6],         // shards jolted by a syllable of strength 0 and of strength 1
  turn: [0.12, 0.45],          // radians a jolted shard turns, for good
  shift: [0.03, 0.1],          // how far it shifts and settles back, in tangent units
  glideTime: 0.45,             // seconds a turn takes …
  glideLead: 0.12,             // … beginning this long before the syllable
  rise: 0.12, fall: 0.8,       // seconds of a shift out and back
};

const FLIT = {
  count: 36,
  idle: 3,                     // boxes shown in silence
  reach: 1.12,                 // spots lie within this fraction of the radius
  threshold: [0.12, 1.05],     // smoothed level at which a box begins to appear
  opening: 0.2,                // level over which it appears fully
  size: [36, 120],             // px
  hop: [80, 360],              // px a dart covers
  perSyllable: [2, 6],         // boxes darting at a syllable of strength 0 and of strength 1
  dart: 0.22,                  // seconds a dart takes
  trail: 0.45,                 // seconds its line lingers
  wobble: 10,                  // px of hovering, at full level
  lock: { rise: 0.12, hold: 0.3, fall: 0.5 },   // seconds
};

const LINE = { box: 2.5, trail: 1.5 };   // px
const SMOOTH = 0.3;                      // seconds; the level smoothed both ways

const prng = makeRandom(31);
const pick = ([a, b]) => a + (b - a) * prng();
const easeOut = (x) => 1 - (1 - Math.min(1, Math.max(0, x))) ** 3;

// Series derived from the level in prepare; empty without a clip.
Object.assign(clip, { soft: [], softSum: [], toneSoft: [], swirl: [] });

// ---- Sphere (WebGL) --------------------------------------------------------

const VERTEX = `#version 300 es
void main() {
  vec2 p = vec2((gl_VertexID << 1) & 2, gl_VertexID & 2);
  gl_Position = vec4(p * 2.0 - 1.0, 0.0, 1.0);
}`;

const FRAGMENT = `#version 300 es
precision highp float;
const int SHARDS = ${SHARDS};
uniform vec2 uSize;          // px of the drawing buffer
uniform float uRadius;       // px of the drawing buffer
uniform float uSway;         // radians the field has swayed about the vertical
uniform float uStream;       // radians the strokes have streamed about the vertical
uniform float uSwirl;        // 0 strokes lie as laid, 1 they follow the stream
uniform vec3 uShard[SHARDS]; // per shard: turn, and shift in its tangent plane
uniform float uFlow;         // drift of the ripples
uniform float uRipple;       // their strength
uniform float uTone;         // 0 broad ripples, 1 fine ones
out vec4 outColor;

const vec3 NAVY = vec3(0.055, 0.086, 0.153);
const vec3 BLUE = vec3(0.196, 0.333, 0.549);
const vec3 BLUE_DEEP = vec3(0.114, 0.192, 0.329);
const vec3 SIGNAL = vec3(0.357, 0.608, 1.0);
const vec3 BONE = vec3(0.949, 0.949, 0.957);
const vec3 CREAM = vec3(0.969, 0.847, 0.765);
const vec3 PEACH = vec3(0.933, 0.667, 0.525);
const vec3 EMBER = vec3(0.769, 0.380, 0.184);
const vec3 RUST = vec3(0.549, 0.231, 0.141);
const vec3 RUST_DEEP = vec3(0.231, 0.090, 0.063);
const float TAU = 6.2831853;

const int BLADES = 12;       // the first shards are long, thin blades
const int STROKES = 220;
const float ROUGH = 0.006;    // tilt of the four normals a pixel averages

vec3 rotY(vec3 v, float a) { float c = cos(a), s = sin(a); return vec3(c * v.x + s * v.z, v.y, -s * v.x + c * v.z); }
vec2 rot2(vec2 v, float a) { float c = cos(a), s = sin(a); return vec2(c * v.x - s * v.y, s * v.x + c * v.y); }

float hash1(float x) {
  return fract(sin(x * 12.9898) * 43758.5453);
}
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

// A direction spread evenly over the sphere from two numbers in [0, 1].
vec3 direction(float u, float v) {
  float z = 2.0 * u - 1.0, a = TAU * v, s = sqrt(1.0 - z * z);
  return vec3(s * cos(a), z, s * sin(a));
}

// The plane touching the sphere of directions at c: right and top.
mat2x3 frame(vec3 c) {
  vec3 right = normalize(cross(abs(c.y) < 0.99 ? vec3(0.0, 1.0, 0.0) : vec3(1.0, 0.0, 0.0), c));
  return mat2x3(right, cross(c, right));
}

// d seen in the plane touching at c (gnomonic): a straight edge there is a
// great circle on the sphere of directions.
vec2 onPlane(vec3 d, vec3 c, mat2x3 f) {
  return vec2(dot(d, f[0]), dot(d, f[1])) / dot(d, c);
}

// Signed distance of q from the edge a to b, positive on its left.
float edge(vec2 q, vec2 a, vec2 b) {
  vec2 ab = b - a;
  return (ab.x * (q.y - a.y) - ab.y * (q.x - a.x)) / length(ab);
}

// 1 inside the triangle abc, anti-aliased over aa.
float triangle(vec2 q, vec2 a, vec2 b, vec2 c, float aa) {
  float s = sign((b.x - a.x) * (c.y - a.y) - (b.y - a.y) * (c.x - a.x));
  float e = min(s * edge(q, a, b), min(s * edge(q, b, c), s * edge(q, c, a)));
  return smoothstep(-aa, aa, e);
}

// 1 inside the rectangle of half-sizes e about the origin, its long side
// along direction u.
float rectangle(vec2 q, vec2 u, vec2 e, float aa) {
  vec2 r = vec2(dot(q, vec2(u.y, -u.x)), dot(q, u));
  return smoothstep(-aa, aa, e.x - abs(r.x)) * smoothstep(-aa, aa, e.y - abs(r.y));
}

// The palette, picked by h in [0, 1]: rust and peach the most, then blue.
vec3 paint(float h) {
  if (h < 0.16) return RUST_DEEP;
  if (h < 0.32) return RUST;
  if (h < 0.44) return EMBER;
  if (h < 0.56) return PEACH;
  if (h < 0.63) return CREAM;
  if (h < 0.77) return NAVY;
  if (h < 0.9) return BLUE;
  return SIGNAL;
}

// The field by direction (y up, z towards the audience). aa is the pixel's
// footprint in directions, taken outside the loops.
vec3 environment(vec3 d, float aa) {
  vec3 col = mix(BLUE, NAVY * 0.6, smoothstep(-0.3, 0.7, -d.y));

  // Shards: irregular triangles about their centres; the first ones blades.
  for (int i = 0; i < SHARDS; i++) {
    float f = float(i);
    vec3 c = direction(hash1(f * 1.37 + 0.11), hash1(f * 2.71 + 0.53));
    bool blade = i < BLADES;
    float size = blade ? 0.45 + 0.45 * hash1(f * 3.9) : 0.1 + 0.3 * hash1(f * 3.9 + 0.7);
    float w = dot(d, c);
    if (w < cos(atan(size * 1.5)) - 0.02) continue;
    vec2 q = onPlane(d, c, frame(c));
    q = rot2(q - uShard[i].yz, -uShard[i].x);
    float base = TAU * hash1(f * 5.3 + 0.2);
    vec2 a, b, e;
    if (blade) {
      vec2 u = vec2(cos(base), sin(base)), n = vec2(-u.y, u.x);
      a = -size * u;
      b = size * u + 0.05 * size * n;
      e = size * u - 0.05 * size * n;
    } else {
      a = size * (0.6 + 0.4 * hash1(f * 6.1)) * vec2(cos(base), sin(base));
      b = size * (0.6 + 0.4 * hash1(f * 6.7)) * vec2(cos(base + 2.1 + 0.5 * hash1(f * 7.3)), sin(base + 2.1 + 0.5 * hash1(f * 7.3)));
      e = size * (0.6 + 0.4 * hash1(f * 8.3)) * vec2(cos(base + 4.2 + 0.5 * hash1(f * 9.7)), sin(base + 4.2 + 0.5 * hash1(f * 9.7)));
    }
    float inside = triangle(q, a, b, e, aa / max(w, 0.2));
    vec3 colour = blade ? (hash1(f * 4.4) < 0.5 ? CREAM : (hash1(f * 4.9) < 0.5 ? SIGNAL : PEACH)) : paint(hash1(f * 8.8 + 1.3));
    col = mix(col, colour, inside * (blade ? 0.85 : 0.95));
  }

  // Strokes, looked up in a field streamed about the vertical, so they
  // slide past the shards. Laid at jagged angles, they align with the stream and
  // stretch as the level grows; a rectangle reads the same both ways round,
  // so the stream's direction is taken on the side of the laid one.
  vec3 ds = rotY(d, -uStream);
  for (int i = 0; i < STROKES; i++) {
    float f = float(i);
    vec3 c = direction(hash1(f * 3.17 + 0.5), hash1(f * 7.31 + 1.7));
    float w = dot(ds, c);
    if (w < 0.92) continue;
    vec2 q = onPlane(ds, c, frame(c));
    float tilt = (hash1(f * 4.7 + 2.2) - 0.5) * 1.2;
    vec2 laid = vec2(cos(tilt), sin(tilt)), stream = vec2(1.0, 0.0);
    if (dot(laid, stream) < 0.0) stream = -stream;
    vec2 along = normalize(mix(laid, stream, uSwirl));
    vec2 e = vec2(0.012 + 0.02 * hash1(f * 5.77 + 2.9),
                  (0.04 + 0.1 * hash1(f * 1.93 + 4.1)) * (1.0 + uSwirl));
    float inside = rectangle(q, along, e, aa / max(w, 0.2));
    col = mix(col, paint(hash1(f * 8.9 + 3.3)), inside * 0.92);
  }

  // Two tall lights behind the sphere, cool on the left and warm on the
  // right, which it gathers into bright crescents along its rim; a key light
  // high on the right and a strip low on the right for the highlights.
  vec3 l = normalize(vec3(-0.72, 0.15, -0.68));
  col = mix(col, BONE * 0.9, rectangle(onPlane(d, l, frame(l)), vec2(0.0, 1.0), vec2(0.5, 1.2), aa) * step(0.05, dot(d, l)));
  l = normalize(vec3(0.75, -0.1, -0.65));
  col = mix(col, PEACH, rectangle(onPlane(d, l, frame(l)), vec2(0.0, 1.0), vec2(0.45, 1.2), aa) * step(0.05, dot(d, l)));
  l = normalize(vec3(0.5, 0.62, 0.6));
  col += BONE * 1.4 * rectangle(onPlane(d, l, frame(l)), vec2(0.0, 1.0), vec2(0.18, 0.11), aa) * step(0.05, dot(d, l));
  l = normalize(vec3(0.8, -0.1, 0.59));
  col += CREAM * 1.2 * rectangle(onPlane(d, l, frame(l)), vec2(0.0, 1.0), vec2(0.025, 0.35), aa) * step(0.05, dot(d, l));
  return col;
}

void main() {
  vec2 p = (gl_FragCoord.xy - 0.5 * uSize) / uRadius;
  float r = length(p);
  float edgeAa = 2.0 / uRadius;
  if (r > 1.0 + edgeAa) {
    outColor = vec4(0.0);
    return;
  }
  vec3 n = vec3(p, sqrt(max(0.0, 1.0 - min(r * r, 1.0))));

  // Ripples: the normal pushed along the surface by three noise channels,
  // broad and fine mixed by the tone.
  vec3 qa = n * 2.2 + vec3(0.0, 0.0, uFlow), qb = n * 5.0 + vec3(0.0, uFlow, 0.0);
  vec3 push = mix(vec3(noise(qa), noise(qa + 19.1), noise(qa + 37.7)),
                  vec3(noise(qb), noise(qb + 19.1), noise(qb + 37.7)), uTone) - 0.5;
  push -= n * dot(push, n);
  n = normalize(n + uRipple * push);

  // A slightly rough mirror: the field averaged over four normals tilted a
  // little about the true one, which softens its edges like polish does.
  float aa = length(fwidth(rotY(reflect(vec3(0.0, 0.0, -1.0), n), uSway))) * 0.75 + 1e-4;
  vec3 t1 = normalize(cross(n, vec3(0.0, 1.0, 0.001)));
  vec3 t2 = cross(n, t1);
  vec3 col = vec3(0.0);
  for (int k = 0; k < 4; k++) {
    float a = 0.785 + 1.571 * float(k);
    vec3 nk = normalize(n + ROUGH * (cos(a) * t1 + sin(a) * t2));
    col += environment(rotY(reflect(vec3(0.0, 0.0, -1.0), nk), uSway), aa + ROUGH);
  }
  col *= 0.25;

  // Metal: the reflection a little desaturated, steel-tinted and deeper in
  // its mid-tones; darker face-on than at the grazing rim (Fresnel, F0 0.72);
  // shaded darker towards the bottom for volume.
  float grey = dot(col, vec3(0.299, 0.587, 0.114));
  col = mix(vec3(grey), col, 0.82) * vec3(0.92, 0.95, 1.0);
  col = pow(col, vec3(1.1));
  col *= 0.72 + 0.28 * pow(1.0 - max(n.z, 0.0), 5.0);
  col *= mix(0.7, 1.0, smoothstep(-0.95, 0.35, n.y));

  // Gloss: sharp highlights from two lights in front, each with a soft glow.
  vec3 v = vec3(0.0, 0.0, 1.0);
  vec3 h1 = normalize(normalize(vec3(-0.5, 0.55, 0.67)) + v);
  vec3 h2 = normalize(normalize(vec3(0.6, -0.25, 0.76)) + v);
  float s1 = max(dot(n, h1), 0.0), s2 = max(dot(n, h2), 0.0);
  col += BONE * (1.4 * pow(s1, 700.0) + 0.16 * pow(s1, 40.0));
  col += PEACH * (0.7 * pow(s2, 500.0) + 0.08 * pow(s2, 30.0));
  col = min(col, vec3(1.0));

  float cover = 1.0 - smoothstep(1.0 - edgeAa, 1.0, r);
  outColor = vec4(col * cover, cover);
}`;

const SPHERE_SIZE = Math.ceil(SPHERE.radius * 2.1);
const sphereCanvas = offscreen(SPHERE_SIZE * SPHERE.supersample, SPHERE_SIZE * SPHERE.supersample);
const gl = sphereCanvas.getContext("webgl2", { premultipliedAlpha: true, preserveDrawingBuffer: true, antialias: false });
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
  ["uSize", "uRadius", "uSway", "uStream", "uSwirl", "uShard", "uFlow", "uRipple", "uTone"]
    .map((name) => [name, gl.getUniformLocation(program, name)]));

// ---- Shard jolts -----------------------------------------------------------

// Each shard's jolts ({time, turn, sx, sy}), chosen once from the analysis.
const shardJolts = Array.from({ length: SHARDS }, () => []);

function planJolts(c) {
  c.onsets.forEach(([start, strength], j) => {
    const rand = makeRandom(12000 + j);
    const count = Math.round(JOLT.perSyllable[0] + (JOLT.perSyllable[1] - JOLT.perSyllable[0]) * strength);
    for (let k = 0; k < count; k++) {
      const i = Math.floor(rand() * SHARDS);
      const turn = (rand() < 0.5 ? -1 : 1) * (JOLT.turn[0] + (JOLT.turn[1] - JOLT.turn[0]) * rand());
      const a = 2 * Math.PI * rand(), shift = JOLT.shift[0] + (JOLT.shift[1] - JOLT.shift[0]) * rand();
      shardJolts[i].push({ time: start, turn: turn * strength, sx: shift * Math.cos(a), sy: shift * Math.sin(a) });
    }
  });
}

// Every shard's turn and shift at time t, for the shader.
const shardMotion = new Float32Array(SHARDS * 3);

function shardsAt(t) {
  shardJolts.forEach((jolts, i) => {
    let turn = 0, sx = 0, sy = 0;
    for (const jolt of jolts) {
      if (jolt.time - JOLT.glideLead > t) break;
      turn += jolt.turn * ease((t - jolt.time + JOLT.glideLead) / JOLT.glideTime);
      const age = t - jolt.time;
      const out = ease(age / JOLT.rise) * (1 - ease((age - JOLT.rise) / JOLT.fall));
      sx += jolt.sx * out;
      sy += jolt.sy * out;
    }
    shardMotion.set([turn, sx, sy], 3 * i);
  });
  return shardMotion;
}

function drawSphere(t, soft, tone) {
  const s = sphereCanvas.width, k = SPHERE.supersample;
  const voiced = at(clip.softSum, t, 0);
  gl.viewport(0, 0, s, s);
  gl.clearColor(0, 0, 0, 0);
  gl.clear(gl.COLOR_BUFFER_BIT);
  gl.useProgram(program);
  gl.uniform2f(uniform.uSize, s, s);
  gl.uniform1f(uniform.uRadius, SPHERE.radius * k);
  gl.uniform1f(uniform.uSway, SPHERE.sway.reduce((sum, [a, period]) => sum + a * Math.sin(2 * Math.PI * t / period), 0));
  gl.uniform1f(uniform.uStream, FIELD.stream * voiced);
  gl.uniform1f(uniform.uSwirl, at(clip.swirl, t, 0));
  gl.uniform3fv(uniform.uShard, shardsAt(t));
  gl.uniform1f(uniform.uFlow, SPHERE.flowRest * t + SPHERE.flowVoice * voiced);
  gl.uniform1f(uniform.uRipple, SPHERE.ripple[0] + (SPHERE.ripple[1] - SPHERE.ripple[0]) * soft);
  gl.uniform1f(uniform.uTone, tone);
  gl.drawArrays(gl.TRIANGLES, 0, 3);
  ctx.imageSmoothingEnabled = true;
  ctx.imageSmoothingQuality = "high";
  ctx.drawImage(sphereCanvas, LAYOUT.orbX - SPHERE_SIZE / 2, LAYOUT.orbY - SPHERE_SIZE / 2, SPHERE_SIZE, SPHERE_SIZE);
}

// ---- Boxes -----------------------------------------------------------------

// A spot within reach of the sphere, in px from its centre, spread evenly.
function spot(rand) {
  const a = 2 * Math.PI * rand(), r = FLIT.reach * SPHERE.radius * Math.sqrt(rand());
  return [r * Math.cos(a), r * Math.sin(a)];
}

// Each box starts at a spot; the syllables add the spots it darts to
// ({time, x, y, lock}), in order of time.
const FLITTERS = Array.from({ length: FLIT.count }, (_, i) => {
  const [x, y] = spot(prng);
  return {
    threshold: i < FLIT.idle ? -1 : pick(FLIT.threshold),
    size: pick(FLIT.size),
    phase: [2 * Math.PI * prng(), 2 * Math.PI * prng()],
    rate: 0.2 + 0.3 * prng(),
    darts: [{ time: -Infinity, x, y, lock: -1 }],
  };
});

// The darts of every syllable, chosen once from the analysis: the boxes
// showing at its time (or any, if none shows), a hop from where each was.
function planDarts(c) {
  c.onsets.forEach(([start, strength], j) => {
    const rand = makeRandom(9000 + j);
    const level = at(c.soft, start, 0);
    let pool = FLITTERS.filter((f) => f.threshold < level);
    if (pool.length === 0) pool = FLITTERS;
    const count = Math.min(pool.length, Math.round(FLIT.perSyllable[0] + (FLIT.perSyllable[1] - FLIT.perSyllable[0]) * strength));
    const chosen = new Set();
    while (chosen.size < count) chosen.add(pool[Math.floor(rand() * pool.length)]);
    let first = true;
    for (const f of chosen) {
      // A hop that would leave the reach goes the other way, or, if that
      // leaves it too, to a fresh spot, so boxes do not gather at the edge.
      const last = f.darts[f.darts.length - 1];
      const a = 2 * Math.PI * rand(), hop = FLIT.hop[0] + (FLIT.hop[1] - FLIT.hop[0]) * rand();
      const dx = hop * Math.cos(a), dy = hop * Math.sin(a), max = FLIT.reach * SPHERE.radius;
      const fresh = spot(rand);
      let [x, y] = [last.x + dx, last.y + dy];
      if (Math.hypot(x, y) > max) [x, y] = [last.x - dx, last.y - dy];
      if (Math.hypot(x, y) > max) [x, y] = fresh;
      f.darts.push({ time: start, x, y, lock: first ? j : -1 });
      first = false;
    }
  });
}

// A box at time t: where it is, and its latest dart and the one before.
function flitterAt(f, t, soft) {
  let k = f.darts.length - 1;
  while (k > 0 && f.darts[k].time > t) k--;
  const cur = f.darts[k], prev = f.darts[Math.max(0, k - 1)];
  const s = k === 0 ? 1 : easeOut((t - cur.time) / FLIT.dart);
  const hover = FLIT.wobble * (0.3 + 0.7 * soft);
  return {
    x: prev.x + (cur.x - prev.x) * s + hover * Math.sin(2 * Math.PI * f.rate * t + f.phase[0]),
    y: prev.y + (cur.y - prev.y) * s + hover * Math.sin(2 * Math.PI * f.rate * 1.3 * t + f.phase[1]),
    cur, prev, k,
  };
}

function lockEnvelope(age) {
  const { rise, hold, fall } = FLIT.lock;
  return ease(age / rise) * (1 - ease((age - rise - hold) / fall));
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

function drawBoxes(t, soft, tone) {
  const { orbX, orbY } = LAYOUT;
  for (const f of FLITTERS) {
    const shown = f.threshold < 0 ? 0.45 : ease((soft - f.threshold) / FLIT.opening);
    const at_ = flitterAt(f, t, soft);
    const age = t - at_.cur.time;
    const lock = at_.cur.lock >= 0 ? lockEnvelope(age) : 0;
    const alpha = Math.max(shown, lock);
    if (alpha < 0.01) continue;
    const x = orbX + at_.x, y = orbY + at_.y;

    // The dart's way, fading.
    if (at_.k > 0 && age < FLIT.trail) {
      ctx.strokeStyle = COLOR.bone;
      ctx.lineWidth = LINE.trail;
      ctx.globalAlpha = alpha * 0.6 * (1 - age / FLIT.trail) ** 2;
      ctx.beginPath();
      ctx.moveTo(orbX + at_.prev.x, orbY + at_.prev.y);
      ctx.lineTo(x, y);
      ctx.stroke();
    }

    // Smaller towards the rim, as if lying on the sphere; smaller for bright
    // sounds; wider while appearing, closing in as it settles.
    const rim = Math.min(1, Math.hypot(at_.x, at_.y) / SPHERE.radius);
    const size = f.size * (1 - 0.35 * rim * rim) * (1 - 0.3 * tone) * (1 + 0.6 * (1 - shown)) * (1 - 0.25 * lock);
    ctx.lineWidth = LINE.box;
    if (shown * (1 - lock) > 0.01) {
      ctx.strokeStyle = COLOR.bone;
      ctx.globalAlpha = shown * (1 - lock);
      brackets(x, y, size);
    }
    if (lock > 0.01) {
      ctx.strokeStyle = COLOR.signal;
      ctx.globalAlpha = lock;
      brackets(x, y, size);
      ctx.beginPath();
      ctx.moveTo(x - 8, y);
      ctx.lineTo(x + 8, y);
      ctx.moveTo(x, y - 8);
      ctx.lineTo(x, y + 8);
      ctx.stroke();
    }
    ctx.fillStyle = lock > 0.5 ? COLOR.signal : COLOR.bone;
    ctx.globalAlpha = alpha;
    ctx.fillRect(x - 2, y - 2, 4, 4);
  }
  ctx.globalAlpha = 1;
}

registerDesign({
  prepare(c) {
    c.soft = smoothBoth(c.level, SMOOTH, c.fps);
    c.toneSoft = smoothBoth(c.tone, SMOOTH, c.fps);
    c.swirl = smoothBoth(c.level, FIELD.swirlTime, c.fps);
    // Seconds of full smoothed level up to each frame, for motion that
    // gathers with the voice.
    c.softSum = new Float64Array(c.frames + 1);
    for (let i = 0; i < c.frames; i++) c.softSum[i + 1] = c.softSum[i] + c.soft[i] / c.fps;
    planJolts(c);
    planDarts(c);
  },

  drawOrb(t) {
    const soft = at(clip.soft, t, 0);
    const tone = at(clip.toneSoft, t, 0.35);
    drawSphere(t, soft, tone);
    drawBoxes(t, soft, tone);
  },
});
