/* Athene: an orb that answers a recorded voice, for the LED wall.

   A frame depends on its time and the clip's analysis (athene/analyse.py)
   alone, so the preview with sound and the frame-by-frame render
   (athene/render.py) draw the same pictures, in any order.

   This page holds what every design shares: the frame and its layout after
   Apollon (the Seestone mark small at the top, the name in Michroma above
   the orb), the clip, and the preview and render modes. The orb is drawn by
   a design in designs/, chosen with ?design=NAME:
     futurist    flat halo, lines of force and torn fragments
     painterly   a plotter painting that paints itself while she speaks
     planetary   a sphere of blue light read by the lines of a machine that watches it

   Colours are the Seestone CI's (src/interface/static/style.css) and their
   tints on black. The ground is pure black rather than Void, as every lit
   value lights the LED wall up to its edges. */

"use strict";

const W = 3840, H = 2160;

const COLOR = {
  ground: "#000000",
  bone: "#f2f2f4",
  steel: "#8c909c",
  steelFaint: "#5c5f69",   // Steel at 65 % (style.css)
  steel35: "#313237",      // Steel at 35 % on black
  steel15: "#151617",      // Steel at 15 % on black
  signal: "#5b9bff",
  signal55: "#32558c",     // Signal at 55 % on black
  signal30: "#1d3154",     // Signal at 30 % (style.css)
  signal12: "#0e1627",     // Signal at 12 % (style.css)
};

// Positions and sizes in pixels of the 3840 × 2160 frame.
const LAYOUT = {
  markTop: 56, markSize: 84,
  nameY: 330, nameSize: 104, nameTrack: 0.04,   // tracking of the Apollon wordmark (.wordmark)
  orbX: W / 2, orbY: 1230,
  radius: 600,     // the orb's radius at rest
};

// ---- Clip ------------------------------------------------------------------

// Without an analysis the orb stands at rest.
const clip = { fps: 50, frames: 0, level: [], tone: [], onsets: [], spoken: [] };

function prepare(analysis) {
  Object.assign(clip, analysis);
  // Seconds of full-level speech up to each frame, for motion that
  // accumulates with the voice, frame by frame without history.
  clip.spoken = new Float64Array(clip.frames + 1);
  for (let i = 0; i < clip.frames; i++) clip.spoken[i + 1] = clip.spoken[i] + clip.level[i] / clip.fps;
  if (design.prepare) design.prepare(clip);
}

// A per-frame series at time t, linear between frames, held at the ends.
function at(series, t, fallback) {
  const n = series.length;
  if (n === 0) return fallback;
  const x = Math.min(Math.max(t * clip.fps, 0), n - 1);
  const i = Math.floor(x), f = x - i;
  return i + 1 < n ? series[i] * (1 - f) + series[i + 1] * f : series[i];
}

function spokenAt(t) {
  return at(clip.spoken, t, 0);
}

// A turn by `size` radians per full-strength syllable, each taking `time`
// seconds and easing out, summed over the syllables up to t.
function jolted(t, size, time) {
  let angle = 0;
  for (const [start, strength] of clip.onsets) {
    if (start > t) break;
    const x = Math.min(1, (t - start) / time);
    angle += size * strength * (1 - (1 - x) ** 3);
  }
  return angle;
}

// A series smoothed forwards and backwards with the same time constant, so
// it neither lags nor leads.
function smoothBoth(series, seconds, fps) {
  const keep = Math.exp(-1 / (seconds * fps));
  const n = series.length;
  const forward = new Float64Array(n), out = new Float64Array(n);
  let y = 0;
  for (let i = 0; i < n; i++) forward[i] = y = keep * y + (1 - keep) * series[i];
  y = 0;
  for (let i = n - 1; i >= 0; i--) out[i] = y = keep * y + (1 - keep) * forward[i];
  return out;
}

// Smoothstep on [0, 1], clamped: eases in and out.
function ease(x) {
  const c = Math.min(1, Math.max(0, x));
  return c * c * (3 - 2 * c);
}

// Seeded, so every render of a frame is identical.
function makeRandom(seed) {
  let s = seed >>> 0;
  return () => {
    s = (s + 0x6d2b79f5) >>> 0;
    let r = Math.imul(s ^ (s >>> 15), 1 | s);
    r = (r + Math.imul(r ^ (r >>> 7), 61 | r)) ^ r;
    return ((r ^ (r >>> 14)) >>> 0) / 4294967296;
  };
}

// ---- Drawing ---------------------------------------------------------------

const canvas = document.getElementById("frame");
const ctx = canvas.getContext("2d");
let mark = null;
let design = null;

// Called by the design's script: { drawOrb(t), prepare(clip) optional }.
function registerDesign(d) {
  design = d;
}

function offscreen(width, height) {
  const c = document.createElement("canvas");
  c.width = width;
  c.height = height;
  return c;
}

function disc(c, radius, color) {
  c.beginPath();
  c.arc(LAYOUT.orbX, LAYOUT.orbY, radius, 0, 2 * Math.PI);
  c.fillStyle = color;
  c.fill();
}

// Sectors of the orb from radius `inner` to `reach`, one per wedge
// ({angle, width}), turned by `angle` and widened by `scale`.
function sectors(wedges, angle, scale, inner, reach) {
  const { orbX, orbY } = LAYOUT;
  const path = new Path2D();
  for (const w of wedges) {
    const a = w.angle + angle, half = w.width * scale / 2;
    path.moveTo(orbX + inner * Math.cos(a - half), orbY + inner * Math.sin(a - half));
    path.arc(orbX, orbY, reach, a - half, a + half);
    path.arc(orbX, orbY, inner, a + half, a - half, true);
    path.closePath();
  }
  return path;
}

function draw(t) {
  ctx.fillStyle = COLOR.ground;
  ctx.fillRect(0, 0, W, H);
  design.drawOrb(t);
  drawMark();
  drawName();
}

function drawMark() {
  const s = LAYOUT.markSize;
  ctx.drawImage(mark, (W - s) / 2, LAYOUT.markTop, s, s);
}

function drawName() {
  const size = LAYOUT.nameSize;
  ctx.font = `400 ${size}px Michroma`;
  ctx.letterSpacing = `${LAYOUT.nameTrack * size}px`;
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillStyle = COLOR.bone;
  // Tracking also follows the last letter; the shift keeps the word centred.
  ctx.fillText("ATHENE", W / 2 + LAYOUT.nameTrack * size / 2, LAYOUT.nameY);
}

// ---- Modes -----------------------------------------------------------------

function loadImage(src) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = reject;
    img.src = src;
  });
}

function loadScript(src) {
  return new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = src;
    script.onload = resolve;
    script.onerror = () => reject(new Error(`cannot load ${src}`));
    document.head.appendChild(script);
  });
}

async function load(designName) {
  await loadScript(`/designs/${designName}.js`);
  const fonts = [
    new FontFace("Michroma", "url(/fonts/Michroma-Regular.ttf)"),
    new FontFace("IBM Plex Mono", "url(/fonts/IBMPlexMono-SemiBold.ttf)", { weight: "600" }),
  ];
  for (const font of fonts) document.fonts.add(await font.load());
  mark = await loadImage("/seestone.png");
  const res = await fetch("/clip.json");
  if (res.ok) prepare(await res.json());
}

// Preview: the clip plays and the frame follows its playhead.
async function preview() {
  const audio = new Audio();
  const res = await fetch("/clip.audio");
  if (res.ok) audio.src = URL.createObjectURL(await res.blob());
  const clock = document.getElementById("clock");
  const toggle = () => (audio.paused ? audio.play() : audio.pause());
  addEventListener("keydown", (e) => {
    if (e.code === "Space") { e.preventDefault(); toggle(); }
    else if (e.code === "ArrowLeft") audio.currentTime = Math.max(0, audio.currentTime - 2);
    else if (e.code === "ArrowRight") audio.currentTime += 2;
  });
  canvas.addEventListener("click", toggle);
  const tick = () => {
    draw(audio.currentTime);
    clock.textContent = `${audio.currentTime.toFixed(2)} s`;
    requestAnimationFrame(tick);
  };
  tick();
}

const params = new URLSearchParams(location.search);
const mode = params.get("mode") || "preview";
document.body.dataset.mode = mode;

load(params.get("design") || "planetary").then(() => {
  if (mode === "render") {
    // Render: the driver asks for frame i and receives it as a PNG data URL.
    window.athene = {
      ready: true,
      fps: clip.fps,
      frame(i) {
        draw(i / clip.fps);
        return canvas.toDataURL("image/png");
      },
    };
  } else {
    preview();
  }
});
