/* Painterly: Athene as a plotter painting that paints itself while she speaks.

   After Simon Denny's plotted paintings (athene/moodboard/Denny-Defense-*):
   Futurist compositions painted by machines in layers, a soft inkjet ground,
   translucent planes with hard edges and rectangular brush strokes, in rust
   and peach against blue.

     ground   concentric bands, navy at the rim through rust to peach and
              cream at the eye, blurred to a luminous underpainting that
              widens with the voice.
     strokes  brush strokes over it in the colours of the ground beneath
              them, some in blue against it. At rest they lie as the plotter
              laid them, near horizontal; as the voice grows they turn into a
              vortex around the eye, lengthen, and circle it, the inner ones
              faster: the spiral of Crali's cockpit views, and the Palantir's
              swirl.
     planes   translucent wedges from the eye, alternately light and dark,
              gliding on by each syllable and trailed by fading echoes.
     fresh    each syllable has the plotter lay new strokes along the planes,
              cream for bright sounds and Signal for dark ones, drying back
              into the painting within two seconds.
     canvas   a woven grain multiplied over the paint; black stays black.

   Every motion follows the level smoothed both ways, and each syllable's
   glide begins shortly before it, so the painting moves without jolts. The
   eye's dot, the lens of the Seestone mark, stays crisp. */

"use strict";

// Rust and peach after the moodboard's paintings, outside the Seestone CI,
// which keeps the name, the mark and the lens.
const WARM = {
  rustDeep: "#3b1710",
  rust: "#8c3b24",
  peach: "#eeaa86",
  cream: "#f7d8c3",
};

const PAINT = {
  bands: [1.0, 0.8, 0.62, 0.46, 0.34],   // from the rim inwards, fractions of the radius
  pupil: 0.22, dot: 0.06,
  palette: [COLOR.signal12, WARM.rustDeep, WARM.rust, WARM.peach, WARM.cream],
  // Blue counterparts for the strokes laid against the ground.
  cool: [COLOR.signal30, COLOR.signal30, COLOR.signal55, COLOR.signal, COLOR.bone],
  widen: 0.08,       // share of its radius a band widens at full level
  lag: 0.04,         // seconds each band follows the one within
  scale: 8,          // the ground is painted at 1/8 size …
  blur: 8,           // … and blurred by this many of its pixels (64 px at full size)
};

const STROKES = {
  count: 1500,
  reach: 1.15,                 // laid within this fraction of the radius
  length: [60, 210], height: [22, 58],
  alpha: [0.55, 0.95],
  mix: 0.3,                    // share taking a neighbouring band's colour
  cool: 0.18,                  // share laid in blue against the ground
  tilt: 0.14,                  // radians from horizontal at rest, at most
  pitch: 0.4,                  // radians the vortex turns inwards from the circle
  turn: 0.55,                  // radians per second of full vortex, near the eye
  stretch: 0.6,                // share of its length a stroke gains in the vortex
  swirlTime: 0.35,             // seconds the vortex takes to follow the level
};

const PLANES = {
  wedges: 6,
  width: [0.06, 0.24],         // radians
  dark: 1.3, bright: 0.6,      // width scale for tone 0 and tone 1
  ray: [1.06, 1.4],            // reach at rest and at full level, fractions of the radius
  spinRest: 2 * Math.PI / 120, spinVoice: 0.2,
  glide: 0.12,                 // radians a full-strength syllable carries the planes on
  glideTime: 0.45,             // seconds the glide takes …
  glideLead: 0.15,             // … beginning this long before the syllable
  echoes: 2, echoGap: 0.08, echoMin: 0.01, echoFade: 0.45,
  lightAlpha: 0.12, shadeAlpha: 0.4,
  light: WARM.cream,
};

const FRESH = {
  count: [4, 14],              // strokes for a syllable of strength 0 and of strength 1
  life: 2.0,                   // seconds to dry back into the painting
  laying: 0.3,                 // seconds the plotter takes to lay a stroke
  length: [100, 240], height: [22, 48],
  radius: [0.3, 1.0],          // where a stroke starts, fractions of the radius
  alpha: 0.85,
};

// Smoothing of the level for the ground and the planes' reach, in seconds.
const SOFT_TIME = 0.12;

const GRAIN = { size: 256, depth: 0.14 };

const prng = makeRandom(11);
const pick = ([a, b]) => a + (b - a) * prng();

// Series derived from the level in prepare; empty without a clip.
Object.assign(clip, { soft: [], swirl: [], swirled: [] });

// ---- Materials -------------------------------------------------------------

// A brush stamp: white bristles on transparent, ragged at both ends, with a
// few thinly painted gaps.
const STAMP_W = 256, STAMP_H = 64;

function makeStamp(rand) {
  const bristles = 20;
  const c = offscreen(STAMP_W, STAMP_H);
  const g = c.getContext("2d");
  g.fillStyle = "rgba(255,255,255,0.5)";
  g.fillRect(STAMP_W * 0.05, STAMP_H * 0.1, STAMP_W * 0.88, STAMP_H * 0.8);
  for (let b = 0; b < bristles; b++) {
    const y = (b + 0.5) * STAMP_H / bristles, th = STAMP_H / bristles * (0.8 + 0.8 * rand());
    const start = STAMP_W * 0.08 * rand(), end = STAMP_W * (0.84 + 0.16 * rand());
    const a = 0.4 + 0.6 * rand();
    const fade = g.createLinearGradient(start, 0, end, 0);
    fade.addColorStop(0, "rgba(255,255,255,0)");
    fade.addColorStop(0.08, `rgba(255,255,255,${a})`);
    fade.addColorStop(0.75, `rgba(255,255,255,${a * (0.5 + 0.5 * rand())})`);
    fade.addColorStop(1, "rgba(255,255,255,0)");
    g.fillStyle = fade;
    g.fillRect(start, y - th / 2, end - start, th);
  }
  g.globalCompositeOperation = "destination-out";
  for (let k = 0; k < 4; k++) {
    g.fillStyle = `rgba(0,0,0,${0.2 + 0.25 * rand()})`;
    g.fillRect(STAMP_W * (0.25 + 0.6 * rand()), STAMP_H * rand(), STAMP_W * 0.12 * rand(), STAMP_H / bristles);
  }
  return c;
}

const STAMPS = Array.from({ length: 6 }, () => makeStamp(prng));
const tinted = new Map();

// Stamp k in a colour, made on first use.
function stampOf(color, k) {
  const key = `${color}/${k}`;
  if (!tinted.has(key)) {
    const c = offscreen(STAMP_W, STAMP_H);
    const g = c.getContext("2d");
    g.drawImage(STAMPS[k], 0, 0);
    g.globalCompositeOperation = "source-in";
    g.fillStyle = color;
    g.fillRect(0, 0, STAMP_W, STAMP_H);
    tinted.set(key, c);
  }
  return tinted.get(key);
}

// A woven canvas: threads two pixels wide in both directions, and pixel noise.
function makeGrain(rand) {
  const s = GRAIN.size;
  const c = offscreen(s, s);
  const g = c.getContext("2d");
  const img = g.createImageData(s, s);
  const rows = Array.from({ length: s / 2 }, () => rand());
  const cols = Array.from({ length: s / 2 }, () => rand());
  for (let y = 0; y < s; y++) {
    for (let x = 0; x < s; x++) {
      const v = 255 * (1 - GRAIN.depth * (0.4 * rows[y >> 1] + 0.35 * cols[x >> 1] + 0.25 * rand()));
      const i = 4 * (y * s + x);
      img.data[i] = img.data[i + 1] = img.data[i + 2] = v;
      img.data[i + 3] = 255;
    }
  }
  g.putImageData(img, 0, 0);
  return ctx.createPattern(c, "repeat");
}

const grain = makeGrain(prng);

// ---- Fixed shapes ----------------------------------------------------------

// The colour of a stroke at a fraction f of the radius: the ground's, now
// and then a neighbouring band's as mixed paint, or its blue counterpart.
function strokeColor(f, rand) {
  if (f < PAINT.dot) return COLOR.bone;
  if (f < PAINT.pupil) return COLOR.ground;
  let k = 0;
  PAINT.bands.forEach((band, i) => { if (f <= band) k = i; });
  if (rand() < STROKES.mix) {
    k = Math.min(PAINT.palette.length - 1, Math.max(0, k + (rand() < 0.5 ? -1 : 1)));
  }
  return rand() < STROKES.cool ? PAINT.cool[k] : PAINT.palette[k];
}

// Spread evenly over the disc; f is the distance from the eye in radii.
const STROKE_SET = Array.from({ length: STROKES.count }, () => {
  const f = STROKES.reach * Math.sqrt(prng());
  return {
    f,
    angle: 2 * Math.PI * prng(),
    tilt: STROKES.tilt * (2 * prng() - 1),
    length: pick(STROKES.length),
    height: pick(STROKES.height),
    alpha: pick(STROKES.alpha),
    color: strokeColor(f, prng),
    stamp: Math.floor(prng() * STAMPS.length),
  };
});

const PLANE_SET = Array.from({ length: PLANES.wedges }, (_, i) => ({
  angle: 2 * Math.PI * (i + 0.6 * prng()) / PLANES.wedges,
  width: pick(PLANES.width),
  light: i % 2 === 0,
}));

const groundSmall = offscreen(W / PAINT.scale, H / PAINT.scale);
const groundSoft = offscreen(W / PAINT.scale, H / PAINT.scale);

// ---- Motion ----------------------------------------------------------------

function prepareMotion(c) {
  c.soft = smoothBoth(c.level, SOFT_TIME, c.fps);
  c.swirl = smoothBoth(c.level, STROKES.swirlTime, c.fps);
  // Seconds of full vortex up to each frame, for the strokes' circling.
  c.swirled = new Float64Array(c.frames + 1);
  for (let i = 0; i < c.frames; i++) c.swirled[i + 1] = c.swirled[i] + c.swirl[i] / c.fps;
}

// The planes' angle: a slow turn, a turn with the voice, and a glide per
// syllable that eases in and out around it.
function planeAngle(t) {
  let angle = PLANES.spinRest * t + PLANES.spinVoice * spokenAt(t);
  for (const [start, strength] of clip.onsets) {
    if (start - PLANES.glideLead > t) break;
    angle += PLANES.glide * strength * ease((t - start + PLANES.glideLead) / PLANES.glideTime);
  }
  return angle;
}

// ---- Layers ----------------------------------------------------------------

function drawGround(t) {
  const k = PAINT.scale;
  const g = groundSmall.getContext("2d");
  g.clearRect(0, 0, groundSmall.width, groundSmall.height);
  const last = PAINT.bands.length - 1;
  const fill = (r, color) => {
    g.beginPath();
    g.arc(LAYOUT.orbX / k, LAYOUT.orbY / k, r / k, 0, 2 * Math.PI);
    g.fillStyle = color;
    g.fill();
  };
  PAINT.bands.forEach((fraction, i) => {
    const level = at(clip.soft, t - (last - i) * PAINT.lag, 0);
    fill(LAYOUT.radius * fraction * (1 + PAINT.widen * level), PAINT.palette[i]);
  });
  fill(LAYOUT.radius * PAINT.pupil, COLOR.ground);
  const s = groundSoft.getContext("2d");
  s.clearRect(0, 0, groundSoft.width, groundSoft.height);
  s.filter = `blur(${PAINT.blur}px)`;
  s.drawImage(groundSmall, 0, 0);
  s.filter = "none";
  ctx.imageSmoothingEnabled = true;
  ctx.imageSmoothingQuality = "high";
  ctx.drawImage(groundSoft, 0, 0, W, H);
}

function drawStrokes(t) {
  const swirl = at(clip.swirl, t, 0);
  const swirled = at(clip.swirled, t, 0);
  const R = LAYOUT.radius;
  for (const s of STROKE_SET) {
    // Inner strokes circle faster, as in a vortex.
    const phi = s.angle + STROKES.turn * swirled * 0.4 / (s.f + 0.15);
    const x = LAYOUT.orbX + s.f * R * Math.cos(phi);
    const y = LAYOUT.orbY + s.f * R * Math.sin(phi);
    // Between the laid tilt and the vortex, blended as axes (a stroke reads
    // the same both ways round): the doubled angles are averaged, which
    // turns the stroke continuously. Where the two cross at right angles the
    // blend is short, and the stroke shortens with it.
    const flow = phi + Math.PI / 2 + STROKES.pitch;
    const rel = 2 * (s.tilt - flow);
    const vx = swirl + (1 - swirl) * Math.cos(rel), vy = (1 - swirl) * Math.sin(rel);
    const a = flow + Math.atan2(vy, vx) / 2;
    const len = s.length * (1 + STROKES.stretch * swirl) * (0.5 + 0.5 * Math.hypot(vx, vy));
    ctx.setTransform(Math.cos(a), Math.sin(a), -Math.sin(a), Math.cos(a), x, y);
    ctx.globalAlpha = s.alpha;
    ctx.drawImage(stampOf(s.color, s.stamp), -len / 2, -s.height / 2, len, s.height);
  }
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.globalAlpha = 1;
}

function drawPlanes(angle, scale, reach, fade) {
  const inner = LAYOUT.radius * PAINT.pupil;
  for (const light of [true, false]) {
    const set = PLANE_SET.filter((p) => p.light === light);
    ctx.globalAlpha = (light ? PLANES.lightAlpha : PLANES.shadeAlpha) * fade;
    ctx.fillStyle = light ? PLANES.light : COLOR.ground;
    ctx.fill(sectors(set, angle, scale, inner, reach));
  }
  ctx.globalAlpha = 1;
}

// Strokes laid by the syllables of the last two seconds, each growing from
// its inner end while the plotter lays it, then drying away.
function drawFresh(t) {
  const R = LAYOUT.radius;
  for (let j = 0; j < clip.onsets.length; j++) {
    const [start, strength] = clip.onsets[j];
    if (start > t) break;
    const age = t - start;
    if (age <= 0 || age >= FRESH.life) continue;
    const laid = ease(age / FRESH.laying);
    if (laid <= 0) continue;
    const rand = makeRandom(1000 + j);
    const n = Math.round(FRESH.count[0] + (FRESH.count[1] - FRESH.count[0]) * strength);
    const settled = planeAngle(start + PLANES.glideTime);
    const bright = 0.3 + 0.6 * at(clip.tone, start, 0.35);
    ctx.globalAlpha = FRESH.alpha * laid * (1 - ease(age / FRESH.life));
    for (let m = 0; m < n; m++) {
      const plane = PLANE_SET[Math.floor(rand() * PLANE_SET.length)];
      const a = settled + plane.angle + (rand() - 0.5) * plane.width;
      const r = R * (FRESH.radius[0] + (FRESH.radius[1] - FRESH.radius[0]) * rand());
      const len = FRESH.length[0] + (FRESH.length[1] - FRESH.length[0]) * rand();
      const h = FRESH.height[0] + (FRESH.height[1] - FRESH.height[0]) * rand();
      const color = rand() < bright ? WARM.cream : (rand() < 0.6 ? COLOR.signal : COLOR.signal55);
      const stamp = Math.floor(rand() * STAMPS.length);
      const dir = a + (rand() - 0.5) * 0.2;
      ctx.setTransform(Math.cos(dir), Math.sin(dir), -Math.sin(dir), Math.cos(dir),
                       LAYOUT.orbX + r * Math.cos(a), LAYOUT.orbY + r * Math.sin(a));
      ctx.drawImage(stampOf(color, stamp), 0, 0, STAMP_W * laid, STAMP_H, 0, -h / 2, len * laid, h);
    }
  }
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.globalAlpha = 1;
}

registerDesign({
  prepare: prepareMotion,

  drawOrb(t) {
    const soft = at(clip.soft, t, 0);
    const tone = at(clip.tone, t, 0.35);
    const scale = PLANES.dark + (PLANES.bright - PLANES.dark) * tone;
    const reach = LAYOUT.radius * (PLANES.ray[0] + (PLANES.ray[1] - PLANES.ray[0]) * soft);

    drawGround(t);
    drawStrokes(t);
    const angle = planeAngle(t);
    for (let k = PLANES.echoes; k >= 1; k--) {
      const echo = planeAngle(t - k * PLANES.echoGap);
      if (Math.abs(angle - echo) < PLANES.echoMin) continue;
      drawPlanes(echo, scale, reach, PLANES.echoFade ** k);
    }
    drawPlanes(angle, scale, reach, 1);
    drawFresh(t);
    disc(ctx, LAYOUT.radius * PAINT.dot, COLOR.bone);

    // The canvas, multiplied over the paint; the black ground stays black.
    ctx.globalCompositeOperation = "multiply";
    ctx.fillStyle = grain;
    ctx.fillRect(0, 0, W, H);
    ctx.globalCompositeOperation = "source-over";
  },
});
