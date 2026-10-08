// Operator page: the camera, sound source and cast of the next live SITREP,
// chosen from what this machine offers. The server keeps the selection, so the
// SITREP page, opened from here or restarted there, opens whatever is selected.
"use strict";

const $ = (id) => document.getElementById(id);

// A sound option's value holds the fields of the selection it stands for.
const microphoneValue = (name, api) => JSON.stringify({ audio: name, audio_api: api });
const ndiValue = (name) => JSON.stringify({ audio_ndi: name });

let selection = null;   // the selection as the server last confirmed it
let microphones = [];
let ndi = null;         // NDI source names, once the search has finished
let casts = [];

function option(text, value, disabled = false) {
  const node = document.createElement("option");
  node.textContent = text;
  node.value = value;
  node.disabled = disabled;
  return node;
}

function group(label, options) {
  const node = document.createElement("optgroup");
  node.label = label;
  node.append(...options);
  return node;
}

const soundValue = (sound) =>
  !sound ? "" : sound.kind === "ndi" ? ndiValue(sound.name) : microphoneValue(sound.name, sound.api);

function notice(text, error = false) {
  $("notice").textContent = text;
  $("notice").classList.toggle("error", error);
}

function ndiGroup() {
  const names = ndi ?? [];
  const options = names.map((name) => option(name, ndiValue(name)));
  // The selected source stays selectable while it is not, or not yet, announced.
  const selected = selection?.sound?.kind === "ndi" ? selection.sound.name : null;
  if (selected && !names.includes(selected)) {
    options.unshift(option(ndi ? `${selected} (nicht gefunden)` : selected, ndiValue(selected)));
  }
  if (!ndi) options.push(option("Suche läuft …", "", true));
  else if (!names.length) options.push(option("Keine Quelle gefunden", "", true));
  return group("NDI", options);
}

function renderCameras(cameras) {
  const select = $("camera");
  select.replaceChildren(...cameras.map((name) => option(name, name)));
  select.value = selection?.camera ?? "";
}

// Microphones are grouped by host API: one microphone appears under each.
function renderSound() {
  const select = $("sound");
  const shown = select.disabled
    ? soundValue(selection?.sound)
    : select.value || soundValue(selection?.sound);
  const byApi = new Map();
  for (const { name, api } of microphones) {
    if (!byApi.has(api)) byApi.set(api, []);
    byApi.get(api).push(option(name, microphoneValue(name, api)));
  }
  select.replaceChildren(ndiGroup(), ...[...byApi].map(([api, options]) => group(api, options)));
  select.value = shown;
}

// A cast folder is listed with the people it enrols. The selected one stays
// listed even outside the default folder, e.g. given with --cast.
function renderCasts() {
  const select = $("cast");
  const listed = [...casts];
  const selected = selection?.cast;
  if (selected && !listed.some((cast) => cast.path === selected.path)) listed.push(selected);
  select.replaceChildren(
    option("Ohne Besetzung: niemand wird erkannt", ""),
    ...listed.map((cast) => option(`${cast.label} · ${cast.names.join(", ")}`, cast.path)),
  );
  select.value = selected?.path ?? "";
}

function revert() {
  $("camera").value = selection?.camera ?? "";
  $("sound").value = soundValue(selection?.sound);
  $("cast").value = selection?.cast?.path ?? "";
}

async function choose() {
  const chosen = {
    video: $("camera").value || null,
    ...JSON.parse($("sound").value || "{}"),
    cast: $("cast").value || null,
  };
  notice("Wird gespeichert …");
  try {
    const response = await fetch("/api/sources", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(chosen),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail ?? `HTTP ${response.status}`);
    selection = data.selection;
    await runNotice("Gespeichert.");
  } catch (error) {
    revert();
    notice(`Nicht übernommen: ${error.message}`, true);
  }
}

// A run already under way keeps its sources; a new selection applies from
// the next start.
async function runNotice(otherwise) {
  try {
    const state = await (await fetch("/api/sitrep/state")).json();
    if (state.quelle && (state.status === "running" || state.status === "starting")) {
      notice(`Läuft mit ${state.quelle.kamera} · ${state.quelle.mikrofon}. `
             + "Die Auswahl gilt ab dem nächsten Start.");
      return;
    }
  } catch {
    // The run state is only a note; the selection stands without it.
  }
  notice(otherwise);
}

async function load() {
  try {
    const response = await fetch("/api/sources");
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    selection = data.selection;
    microphones = data.microphones;
    casts = data.casts;
    renderCameras(data.cameras);
    renderSound();
    renderCasts();
    for (const id of ["camera", "sound", "cast"]) $(id).disabled = false;
    if (selection.errors.length) notice(selection.errors.join("\n"), true);
    else await runNotice("");
  } catch (error) {
    notice(`Geräte konnten nicht gelesen werden: ${error.message}`, true);
  }
}

async function searchNdi() {
  try {
    const response = await fetch("/api/sources/ndi");
    ndi = response.ok ? (await response.json()).sources : [];
  } catch {
    ndi = [];
  }
  renderSound();
}

$("camera").addEventListener("change", choose);
$("sound").addEventListener("change", choose);
$("cast").addEventListener("change", choose);
load();
searchNdi();
