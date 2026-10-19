/* Athene: a living high-dimensional space that answers a recorded voice, for
   the LED wall.

   A frame depends on its time and the clip's analysis (athene/analyse.py)
   alone, so the preview with sound and the frame-by-frame render
   (athene/render.py) draw the same pictures, in any order.

   This page holds what every design shares: the black frame, the clip, and
   the preview and render modes. The picture is drawn by a design in
   designs/, chosen with ?design=NAME:
     axes        a living high-dimensional coordinate system, white lines on black
     axes2       the coordinate system grown into a branching star, with clusters of clips
     axes3       the branching star growing like a slime mould, moved by time, not the voice
     axes4       the slime mould webbed, carrying clusters of clips, lit by the voice
     rehearsal   the scenes of the play, performed live from the keyboard (athene/live.py)

   Athene stands outside the Seestone universe: no mark, no name, no CI. The
   Seestone-branded prototypes are kept in athene/archive. */

"use strict";

const W = 3840, H = 2160;

// ---- Clip ------------------------------------------------------------------

// Without an analysis Athene stands at rest.
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
let design = null;

// Called by the design's script: { draw(t), prepare(clip) optional,
// load() optional, awaited before the clip is prepared, live() optional,
// which takes over the page in live mode }.
function registerDesign(d) {
  design = d;
}

function offscreen(width, height) {
  const c = document.createElement("canvas");
  c.width = width;
  c.height = height;
  return c;
}

function draw(t) {
  ctx.fillStyle = "#000000";
  ctx.fillRect(0, 0, W, H);
  design.draw(t);
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
  if (design.load) await design.load();
  const res = await fetch("/clip.json");
  if (res.ok) prepare(await res.json());
}

// Preview: the clip plays and the frame follows its playhead.
async function preview() {
  const audio = new Audio();
  const res = await fetch("/clip.audio");
  if (res.ok) audio.src = URL.createObjectURL(await res.blob());
  // The playhead survives a reload of the tab, so an edited design shows at
  // the same moment.
  let saved = 0;
  try { saved = Number(sessionStorage.getItem("athene.playhead")) || 0; } catch {}
  audio.addEventListener("loadedmetadata", () => { audio.currentTime = saved; }, { once: true });
  addEventListener("pagehide", () => {
    try { sessionStorage.setItem("athene.playhead", String(audio.currentTime)); } catch {}
  });
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

load(params.get("design") || "axes4").then(() => {
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
  } else if (mode === "live" && design.live) {
    // Live: the design runs the page itself, from the keyboard.
    design.live();
  } else {
    preview();
  }
});
