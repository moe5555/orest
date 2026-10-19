/* Liquid: liquid metal folding and swirling, and detection lines flitting
   around it.

   After the ElevenLabs orbs of athene/description.md and the moodboard in
   athene/moodboard_starmirror (Herndon and Dryhurst's Starmirror, liquid
   chrome and gold, satin copper and steel converging): a soft, bright
   liquid metal, mostly silver, with steel blue and copper drifting through
   it. Its surface folds like satin, and the folds carry the reflections of
   a soft studio in long bands.

     flow       a height field of broad noise folded twice over by noise, on
                the sphere's surface, the whole turning about the vertical;
                its slopes tilt the surface.
     voice      the flow runs faster and turns further with the level, folds
                more and deeper; each syllable swells the folding; the metal
                brightens.
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
};

const LIQUID = {
  flowRest: 0.04,              // drift of the liquid per second in silence
  flowVoice: 0.35,             // added per second of full level
  turnRest: 2 * Math.PI / 90,  // radians per second the liquid turns about the vertical in silence
  turnVoice: 0.15,             // added per second of full level
  warp: [0.6, 1.1],            // folding at rest and at full level
  surge: 0.25,                 // folding added by a full-strength syllable …
  surgeRise: 0.3,              // … swelling over this many seconds …
  surgeLead: 0.1,              // … from this long before it …
  surgeFall: 0.6,              // … and ebbing over this many after
  bump: [0.3, 0.55],           // how deep the folds are, at rest and at full level
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
Object.assign(clip, { soft: [], softSum: [] });

// ---- Sphere (WebGL) --------------------------------------------------------

const VERTEX = `#version 300 es
void main() {
  vec2 p = vec2((gl_VertexID << 1) & 2, gl_VertexID & 2);
  gl_Position = vec4(p * 2.0 - 1.0, 0.0, 1.0);
}`;

const FRAGMENT = `#version 300 es
precision highp float;
uniform vec2 uSize;          // px of the drawing buffer
uniform float uRadius;       // px of the drawing buffer
uniform float uFlow;         // drift of the liquid
uniform float uTurn;         // radians the liquid has turned about the vertical
uniform float uWarp;         // how strongly it folds
uniform float uBump;         // how deep the folds are
uniform float uSheen;        // 0 to 1, the voice brightening the metal
out vec4 outColor;

// Silver, and the tints that drift through it: steel blue and copper.
const vec3 SILVER = vec3(0.86, 0.88, 0.92);
const vec3 STEEL_BLUE = vec3(0.62, 0.74, 0.95);
const vec3 COPPER = vec3(0.92, 0.62, 0.46);
const vec3 PEACH = vec3(0.933, 0.667, 0.525);
const vec3 ICE = vec3(0.62, 0.76, 1.0);
const vec3 BONE = vec3(0.949, 0.949, 0.957);
const float ROUGH = 0.02;     // tilt of the four normals a pixel averages

vec3 rotY(vec3 v, float a) { float c = cos(a), s = sin(a); return vec3(c * v.x + s * v.z, v.y, -s * v.x + c * v.z); }

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
vec3 noise3(vec3 q) {
  return vec3(noise(q), noise(q + vec3(5.2, 1.3, 2.8)), noise(q + vec3(2.1, 7.7, 4.4))) - 0.5;
}

// The liquid's height at surface point p: broad noise folded twice over by
// noise, without fine detail, so its folds are smooth like satin.
float height(vec3 p) {
  vec3 q = p * 1.1 + vec3(0.0, 0.0, uFlow);
  q += 1.6 * uWarp * noise3(q * 0.9);
  q += 0.9 * uWarp * noise3(q * 1.5 + vec3(uFlow * 0.6, 0.0, -uFlow * 0.4));
  return noise(q * 1.2);
}

// The soft, bright studio the metal reflects: light above, a dimmer floor
// below with a warm bounce, a soft band at the horizon, a large key light
// above, a warm light on the right and a cool one on the left.
vec3 studio(vec3 d) {
  vec3 col = vec3(mix(0.2, 0.75, smoothstep(-0.25, 0.9, d.y)));
  col += PEACH * 0.35 * pow(max(dot(d, normalize(vec3(0.0, -1.0, 0.3))), 0.0), 3.0);
  col += vec3(0.45) * exp(-pow((d.y - 0.05) / 0.12, 2.0));
  col += BONE * 1.1 * pow(max(dot(d, normalize(vec3(0.3, 0.8, 0.5))), 0.0), 18.0);
  col += PEACH * 0.9 * pow(max(dot(d, normalize(vec3(0.8, 0.1, -0.3))), 0.0), 6.0);
  col += ICE * 0.8 * pow(max(dot(d, normalize(vec3(-0.85, 0.2, -0.2))), 0.0), 6.0);
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
  vec3 n0 = vec3(p, sqrt(max(0.0, 1.0 - min(r * r, 1.0))));

  // The folds: the surface tilted by the slope of the liquid's height, read
  // in a frame that turns about the vertical.
  vec3 t1 = normalize(cross(n0, vec3(0.0, 1.0, 0.001)));
  vec3 t2 = cross(n0, t1);
  const float E = 0.01;
  float h0 = height(rotY(n0, uTurn));
  float h1 = height(rotY(normalize(n0 + E * t1), uTurn));
  float h2 = height(rotY(normalize(n0 + E * t2), uTurn));
  vec3 n = normalize(n0 - uBump * ((h1 - h0) * t1 + (h2 - h0) * t2) / E);

  // The tint: silver, with steel blue and copper drifting softly through it.
  float tf = mix(noise(rotY(n0, uTurn) * 0.9 + vec3(7.0, uFlow * 0.5, 3.0)), h0, 0.4);
  vec3 tint = mix(STEEL_BLUE, SILVER, smoothstep(0.3, 0.5, tf));
  tint = mix(tint, COPPER, smoothstep(0.55, 0.72, tf));

  // The studio in the metal, averaged over four slightly tilted normals for
  // a satin polish, tinted, whiter towards the grazing rim (Fresnel).
  vec3 u1 = normalize(cross(n, vec3(0.0, 1.0, 0.001)));
  vec3 u2 = cross(n, u1);
  vec3 env = vec3(0.0);
  for (int k = 0; k < 4; k++) {
    float a = 0.785 + 1.571 * float(k);
    env += studio(reflect(vec3(0.0, 0.0, -1.0), normalize(n + ROUGH * (cos(a) * u1 + sin(a) * u2))));
  }
  env *= 0.25;
  float fresnel = pow(1.0 - max(n.z, 0.0), 5.0);
  vec3 col = env * mix(tint, vec3(1.0), 0.5 * fresnel) * (1.0 + 0.25 * uSheen);
  col *= mix(0.75, 1.0, smoothstep(-0.95, 0.35, n0.y));

  // Gloss: soft highlights from two lights in front.
  vec3 v = vec3(0.0, 0.0, 1.0);
  float s1 = max(dot(n, normalize(normalize(vec3(-0.5, 0.55, 0.67)) + v)), 0.0);
  float s2 = max(dot(n, normalize(normalize(vec3(0.6, -0.25, 0.76)) + v)), 0.0);
  col += BONE * (0.9 * pow(s1, 300.0) + 0.12 * pow(s1, 30.0));
  col += PEACH * (0.5 * pow(s2, 250.0) + 0.06 * pow(s2, 25.0));
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
  ["uSize", "uRadius", "uFlow", "uTurn", "uWarp", "uBump", "uSheen"]
    .map((name) => [name, gl.getUniformLocation(program, name)]));

// The folding added by the syllables of the last moments.
function surge(t) {
  let sum = 0;
  for (const [start, strength] of clip.onsets) {
    if (start - LIQUID.surgeLead > t) break;
    const age = t - start + LIQUID.surgeLead;
    sum += strength * ease(age / LIQUID.surgeRise) * (1 - ease((age - LIQUID.surgeRise) / LIQUID.surgeFall));
  }
  return LIQUID.surge * Math.min(sum, 1.5);
}

function drawSphere(t, soft) {
  const s = sphereCanvas.width, k = SPHERE.supersample;
  const voiced = at(clip.softSum, t, 0);
  gl.viewport(0, 0, s, s);
  gl.clearColor(0, 0, 0, 0);
  gl.clear(gl.COLOR_BUFFER_BIT);
  gl.useProgram(program);
  gl.uniform2f(uniform.uSize, s, s);
  gl.uniform1f(uniform.uRadius, SPHERE.radius * k);
  gl.uniform1f(uniform.uFlow, LIQUID.flowRest * t + LIQUID.flowVoice * voiced);
  gl.uniform1f(uniform.uTurn, LIQUID.turnRest * t + LIQUID.turnVoice * voiced);
  gl.uniform1f(uniform.uWarp, LIQUID.warp[0] + (LIQUID.warp[1] - LIQUID.warp[0]) * soft + surge(t));
  gl.uniform1f(uniform.uBump, LIQUID.bump[0] + (LIQUID.bump[1] - LIQUID.bump[0]) * soft);
  gl.uniform1f(uniform.uSheen, soft);
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
    // Seconds of full smoothed level up to each frame, for motion that
    // gathers with the voice.
    c.softSum = new Float64Array(c.frames + 1);
    for (let i = 0; i < c.frames; i++) c.softSum[i + 1] = c.softSum[i] + c.soft[i] / c.fps;
    planDarts(c);
  },

  drawOrb(t) {
    const soft = at(clip.soft, t, 0);
    drawSphere(t, soft);
    drawBoxes(t, soft, at(clip.tone, t, 0.35));
  },
});
