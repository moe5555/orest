/* Futurist: Athene as a flat Futurist eye.

   The devices come from the moodboard (athene/moodboard): the halo of
   concentric flat bands around a tower, and the transparent faceted planes
   that change the tone of what they cross; Depero's target discs and
   sun-wheels on black (New York, 1930); the motion broken into rectangular
   dabs of Simon Denny's plotted paintings. At the centre sits the lens of
   the Seestone mark.

     halo     flat bands in Steel tints, stepping to Bone at the eye. The
              voice widens them from the inside out, each band a little
              later than the one within.
     force    wedges radiating from the eye, the lines of force. Where they
              cross the halo its bands turn to Signal; beyond it they flare
              as rays as the voice grows. Each syllable turns them by a jolt,
              and their positions of the last moments stay behind as stepped
              echoes, so a jolt shows as a sequence of planes. Signal, the
              CI's accent, thus marks the voice.
     dabs     horizontal fragments of the orb, torn out and shifted sideways
              as the voice grows and thrown further by each syllable. Each
              carries the colour of the place it was torn from.

   Flat colours, no gradients, after the CI. */

"use strict";

// Bands from the rim inwards, as fractions of the radius, then the eye: a
// black pupil holding a dot.
const HALO = {
  bands: [1.0, 0.82, 0.65, 0.5, 0.37],
  pupil: 0.24, dot: 0.07,
  widen: 0.09,       // share of its radius a band widens at full level
  lag: 0.04,         // seconds each band follows the one within
  palette: [COLOR.steel15, COLOR.steel35, COLOR.steelFaint, COLOR.steel, COLOR.bone],
  dotColor: COLOR.bone,
};

const FORCE = {
  wedges: 7,
  width: [0.05, 0.2],        // radians, narrowest and widest wedge
  // Bright voices (tone 1) narrow the wedges to lines, dark ones open them to planes.
  dark: 1.3, bright: 0.55,
  ray: [1.04, 1.32],         // reach beyond the halo at rest and at full level, fractions of the radius
  spinRest: 2 * Math.PI / 90,   // radians per second in silence
  spinVoice: 0.25,           // radians per second of full-level speech
  jolt: 0.16,                // radians a full-strength syllable turns the wedges
  joltTime: 0.12,            // seconds the jolt takes
  echoes: 3, echoGap: 0.05,  // positions kept behind, and their spacing in seconds
  echoMin: 0.01,             // radians; echoes closer to the wedges are left out
  palette: [COLOR.signal12, COLOR.signal30, COLOR.signal55, COLOR.signal, COLOR.bone],
  rayColor: COLOR.signal30,
  echoPalette: [COLOR.steel15, COLOR.signal12, COLOR.signal30, COLOR.signal55, COLOR.steel],
  echoRay: COLOR.signal12,
};

const DABS = {
  count: 240,
  reach: 1.05,               // torn from within this fraction of the radius
  width: [50, 240], height: [10, 28],   // px; bright voices make them thinner
  shift: [40, 360],          // px sideways when fully torn out
  fray: 0.3,                 // level above a dab's threshold at which it is fully torn out
  throw: 0.8,                // growth added by a full-strength syllable at full level
  throwTime: 0.3,            // seconds for the throw to settle
  sway: 30, swayRate: 1.5,   // px, and cycles per second of full-level speech
};

const random = makeRandom(7);
const between = ([a, b]) => a + (b - a) * random();

const WEDGES = Array.from({ length: FORCE.wedges }, (_, i) => ({
  angle: 2 * Math.PI * (i + 0.6 * random()) / FORCE.wedges,
  width: between(FORCE.width),
}));

// Sources spread evenly over the disc, in fractions of the radius; each dab
// moves left or right.
const DAB_SHAPES = Array.from({ length: DABS.count }, () => {
  const a = 2 * Math.PI * random(), r = DABS.reach * Math.sqrt(random());
  return {
    x: r * Math.cos(a), y: r * Math.sin(a),
    width: between(DABS.width),
    height: between(DABS.height),
    shift: between(DABS.shift) * (random() < 0.5 ? -1 : 1),
    threshold: 0.05 + 0.9 * random(),
    phase: 2 * Math.PI * random(),
  };
});

// The force layers are drawn whole on this canvas and laid onto the frame
// through their wedges in one step, so no layer beneath shows at the wedges'
// anti-aliased edges.
const layer = offscreen(W, H);
const lctx = layer.getContext("2d");

// Outward throw of the dabs from the syllables of the last moments, 0 to 1.5.
function thrown(t) {
  let sum = 0;
  for (const [start, strength] of clip.onsets) {
    if (start > t) break;
    sum += strength * Math.exp(-(t - start) / DABS.throwTime);
  }
  return Math.min(sum, 1.5);
}

// The wedges' steady turn: slow in silence, faster with the voice.
function steady(t) {
  return FORCE.spinRest * t + FORCE.spinVoice * spokenAt(t);
}

// Radii of the halo's bands at time t, outermost first, the inner ones
// widening first.
function bandRadii(t) {
  const last = HALO.bands.length - 1;
  return HALO.bands.map((fraction, k) => {
    const level = at(clip.level, t - (last - k) * HALO.lag, 0);
    return LAYOUT.radius * fraction * (1 + HALO.widen * level);
  });
}

function drawHalo(c, radii, palette) {
  radii.forEach((r, k) => disc(c, r, palette[k]));
  disc(c, LAYOUT.radius * HALO.pupil, COLOR.ground);
  disc(c, LAYOUT.radius * HALO.dot, HALO.dotColor);
}

// The halo in another palette, seen through the wedges at an angle.
function drawForce(angle, scale, reach, radii, palette, rayColor) {
  lctx.clearRect(0, 0, W, H);
  disc(lctx, reach, rayColor);
  drawHalo(lctx, radii, palette);
  ctx.save();
  ctx.clip(sectors(WEDGES, angle, scale, LAYOUT.radius * HALO.pupil, reach));
  ctx.drawImage(layer, 0, 0);
  ctx.restore();
}

// Whether the angle a lies inside one of the wedges turned by angle.
function inWedge(a, angle, scale) {
  for (const w of WEDGES) {
    const d = (a - w.angle - angle) % (2 * Math.PI);
    const off = Math.abs(((d + 3 * Math.PI) % (2 * Math.PI)) - Math.PI);
    if (off < w.width * scale / 2) return true;
  }
  return false;
}

// The colour the orb shows at an offset (x, y) from its centre, or null
// where the ground shows.
function colorAt(x, y, scene) {
  const r = Math.hypot(x, y);
  if (r < LAYOUT.radius * HALO.dot) return HALO.dotColor;
  if (r < LAYOUT.radius * HALO.pupil) return null;
  let palette = HALO.palette, color = null;
  if (r < scene.reach && inWedge(Math.atan2(y, x), scene.angle, scene.scale)) {
    palette = FORCE.palette;
    color = FORCE.rayColor;
  }
  scene.radii.forEach((radius, k) => { if (r <= radius) color = palette[k]; });
  return color;
}

function drawDabs(t, level, tone, scene) {
  const throwOut = DABS.throw * thrown(t) * level;
  const sway = DABS.sway * Math.sin(2 * Math.PI * DABS.swayRate * spokenAt(t));
  const thin = 1 - 0.5 * tone;
  const R = LAYOUT.radius;
  for (const d of DAB_SHAPES) {
    const grown = Math.min(1, Math.max(0, (level - d.threshold) / DABS.fray)) + throwOut;
    if (grown <= 0) continue;
    const color = colorAt(d.x * R, d.y * R, scene);
    if (color === null) continue;
    const w = d.width * Math.min(grown, 1), h = d.height * thin;
    const x = LAYOUT.orbX + d.x * R + d.shift * grown + sway * Math.sin(d.phase);
    const y = LAYOUT.orbY + d.y * R;
    ctx.fillStyle = color;
    ctx.fillRect(Math.round(x - w / 2), Math.round(y - h / 2), Math.round(w), Math.round(h));
  }
}

registerDesign({
  drawOrb(t) {
    const level = at(clip.level, t, 0);
    const tone = at(clip.tone, t, 0.35);
    const scale = FORCE.dark + (FORCE.bright - FORCE.dark) * tone;
    const reach = LAYOUT.radius * (FORCE.ray[0] + (FORCE.ray[1] - FORCE.ray[0]) * level);
    const radii = bandRadii(t);
    const base = steady(t);
    const angle = base + jolted(t, FORCE.jolt, FORCE.joltTime);

    drawHalo(ctx, radii, HALO.palette);
    for (let k = FORCE.echoes; k >= 1; k--) {
      const echo = base + jolted(t - k * FORCE.echoGap, FORCE.jolt, FORCE.joltTime);
      if (Math.abs(angle - echo) < FORCE.echoMin) continue;
      drawForce(echo, scale, reach, radii, FORCE.echoPalette, FORCE.echoRay);
    }
    drawForce(angle, scale, reach, radii, FORCE.palette, FORCE.rayColor);
    drawDabs(t, level, tone, { radii, reach, angle, scale });
  },
});
