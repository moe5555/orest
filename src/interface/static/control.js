// Control page (Regie): the operator conducts the live SITREP from here,
// while the projection (/sitrep?follow) shows the run to the audience and
// takes nothing from the operator. The server holds the run and the scene,
// so both pages follow the same state over server-sent events.
//
// Three parts: the scene's text, whose marked passages set values when they
// are said (sitrep/scenetext.py); each character's values, set now or as the
// scene's starting values; and the bodies in view, named by hand as on the
// overview of the SITREP page (sitrep.js, renderInView).
//
// The keys of the scene in force, E and X work here as on the SITREP page.
// Text is set with textContent only.
"use strict";

const $ = (id) => document.getElementById(id);

const STATUS_TEXT = {
  idle: "Gestoppt", starting: "Startet", running: "Live",
  stopping: "Wird beendet", error: "Fehler",
};

// The feed as Prototype 4 projects it (prototyp4.js), so the boxes named
// here are the ones the audience sees.
const FEED = "/api/sitrep/video?ratings=1";

let current = null;   // the latest snapshot of the run
let control = null;   // the scene in force as /api/control describes it
let feedOpen = false;

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function option(text, value) {
  const node = el("option", null, text);
  node.value = value;
  return node;
}

// A whole value as text, a negative one with a typographic minus.
const levelText = (value) => (value < 0 ? `−${-value}` : String(value));

const clock = (iso) => (iso ? iso.slice(11, 19) : "");

// A value's level as the SITREP page colours it (sitrep.js, personLevel).
function personLevel(name, value) {
  if (name === "risiko") return value >= 4 ? "red" : value >= 2 ? "amber" : "calm";
  if (name === "aggression") return value >= 8 ? "red" : value >= 4 ? "amber" : "calm";
  if (name === "berechenbarkeit") return value <= -4 ? "red" : value <= -2 ? "amber" : "calm";
  return "calm";
}

function notice(id, text, error = false) {
  $(id).hidden = !text;
  $(id).textContent = text;
  $(id).dataset.level = error ? "red" : "";
}

async function request(method, path, body) {
  const response = await fetch(path, {
    method,
    headers: body === undefined ? {} : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail ?? `HTTP ${response.status}`);
  return data;
}

// Parts are redrawn only when their data changed, so a menu or an input in
// use is not replaced under the operator's hand.
const drawn = {};

function changed(part, data) {
  const key = JSON.stringify(data ?? null);
  if (drawn[part] === key) return false;
  drawn[part] = key;
  return true;
}

// ---- A scale of values -----------------------------------------------------

// One cell per whole value of the range, the one given marked. With
// `unset`, a first cell "—" stands for leaving the value as it is.
function scale(name, value, onPick, unset = false) {
  const [low, high] = control.ranges[name];
  const row = el("div", "scale");
  if (high - low > 10) row.classList.add("wide");
  const cells = [];
  if (unset) cells.push([null, "—"]);
  for (let level = low; level <= high; level += 1) cells.push([level, levelText(level)]);
  for (const [level, text] of cells) {
    const cell = el("button", "scale-cell", text);
    cell.type = "button";
    if (level === value) {
      cell.dataset.current = "";
      if (level !== null) cell.dataset.level = personLevel(name, level);
    }
    cell.addEventListener("click", () => onPick(level));
    row.append(cell);
  }
  return row;
}

// ---- 2 \ SITREP: values now and at the start -------------------------------

// Each character with every value the scene shows them with: the value now,
// which a click sets, and the value the scene starts with. A character with
// nothing measured or set reads 0, as on the projection.
function renderCharacters() {
  const list = $("characters");
  const live = new Map((current?.werte?.personen ?? []).map((person) => [person.name, person]));
  const inView = new Set(current?.im_bild ?? []);
  list.replaceChildren(...(control?.characters ?? []).map(({ name, values }) => {
    const card = el("article", "character");
    const head = el("div", "character-head");
    head.append(el("h2", null, name),
                el("span", "character-seen", inView.has(name) ? "im Bild" : "nicht im Bild"));
    card.dataset.seen = inView.has(name);
    card.append(head);
    for (const value of values) {
      const now = live.get(name)?.[value] ?? 0;
      const row = el("div", "value-row");
      const label = el("div", "value-label");
      label.append(el("span", "label", control.labels[value]));
      const cause = live.get(name)?.[`anlass_${value}`];
      if (cause) label.append(el("span", "value-cause", cause));
      const start = el("label", "value-start");
      const input = el("input");
      const [low, high] = control.ranges[value];
      Object.assign(input, { type: "number", min: low, max: high, step: 1 });
      input.value = control.initial?.[name]?.[value] ?? 0;
      input.addEventListener("change", () => saveInitial(name, value, input));
      start.append(el("span", null, "Start"), input);
      label.append(start);
      row.append(label, scale(value, now, (level) => setValue(name, value, level)));
      card.append(row);
    }
    return card;
  }));
  if (!control?.characters?.length) {
    list.append(el("div", "waiting", "Keine Personen: Die Szene vergibt keine Rollen und keine Besetzung ist gewählt."));
  }
}

async function setValue(character, value, level) {
  try {
    render(await request("POST", "/api/control/set", { character, value, level }));
    notice("values-notice", "");
  } catch (error) {
    notice("values-notice", `Nicht gesetzt: ${error.message}`, true);
  }
}

async function saveInitial(character, value, input) {
  const initial = structuredClone(control.initial ?? {});
  const [low, high] = control.ranges[value];
  const level = Math.min(high, Math.max(low, Math.round(Number(input.value) || 0)));
  input.value = level;
  (initial[character] ??= {})[value] = level;
  try {
    control = await request("PUT", "/api/control/initial", { initial });
    notice("values-notice", "Startwerte gespeichert. Sie gelten ab „Szene beginnen“ oder der nächsten Auswahl der Szene.");
  } catch (error) {
    notice("values-notice", `Nicht gespeichert: ${error.message}`, true);
  }
}

$("apply-initial").addEventListener("click", async () => {
  try {
    render(await request("POST", "/api/control/initial/apply"));
    notice("values-notice", "Startwerte gesetzt.");
  } catch (error) {
    notice("values-notice", `Nicht gesetzt: ${error.message}`, true);
  }
});

// ---- 1 \ The scene's text --------------------------------------------------

// The text as runs of plain text and marked passages, so that the characters
// of the container are exactly those of the text and a selection's offsets
// are offsets into it. A passage's values show beside it from its data
// attribute (style.css), outside the text.
function renderText() {
  const box = $("script-text");
  const text = control?.text ?? "";
  const nodes = [];
  let at = 0;
  for (const annotation of control?.annotations ?? []) {
    if (annotation.start > at) nodes.push(document.createTextNode(text.slice(at, annotation.start)));
    const mark = el("mark", "passage", text.slice(annotation.start, annotation.end));
    mark.dataset.id = annotation.id;
    mark.dataset.summary = annotation.summary || "keine Werte";
    mark.title = annotation.summary || "keine Werte";
    if (current?.cue?.id === annotation.id) mark.dataset.fired = "";
    nodes.push(mark);
    at = annotation.end;
  }
  if (at < text.length) nodes.push(document.createTextNode(text.slice(at)));
  box.replaceChildren(...nodes);
  box.hidden = !text;
  if (!text) openEditor();
}

// The offset into the text of a point in its container.
function offsetOf(node, offset) {
  const range = document.createRange();
  range.setStart($("script-text"), 0);
  range.setEnd(node, offset);
  return range.toString().length;
}

function openEditor() {
  $("script-input").value = control?.text ?? "";
  $("script-editor").hidden = false;
  $("cancel-text").hidden = !control?.text;
  $("script-input").focus();
}

$("edit-text").addEventListener("click", openEditor);
$("cancel-text").addEventListener("click", () => { $("script-editor").hidden = true; });

$("save-text").addEventListener("click", async () => {
  try {
    const data = await request("PUT", "/api/control/text", { text: $("script-input").value });
    control = data;
    $("script-editor").hidden = true;
    notice("script-notice", data.lost.length
      ? `${data.lost.length} Annotation(en) entfernt, deren Stelle sich geändert hat: `
        + data.lost.map((text) => `„${text.length > 40 ? `${text.slice(0, 39)}…` : text}“`).join(", ")
      : "Text übernommen.", data.lost.length > 0);
    renderText();
  } catch (error) {
    notice("script-notice", `Nicht übernommen: ${error.message}`, true);
  }
});

// ---- The annotation card ---------------------------------------------------

// The passage being annotated: its offsets, the values chosen so far, and
// its id once it exists.
let editing = null;

function openCard(passage, rect) {
  editing = passage;
  $("annotation-quote").textContent = control.text.slice(passage.start, passage.end);
  $("annotation-delete").hidden = !passage.id;
  notice("annotation-error", "");
  renderCardValues();
  const card = $("annotation-card");
  card.hidden = false;
  // Beneath the passage, or above it where the window ends.
  const width = card.offsetWidth;
  const height = card.offsetHeight;
  const left = Math.max(12, Math.min(rect.left, window.innerWidth - width - 12));
  const below = rect.bottom + 8;
  const top = below + height < window.innerHeight - 12 ? below : Math.max(12, rect.top - height - 8);
  card.style.left = `${left}px`;
  card.style.top = `${top}px`;
}

function closeCard() {
  editing = null;
  $("annotation-card").hidden = true;
}

function renderCardValues() {
  const box = $("annotation-values");
  box.replaceChildren(...control.characters.map(({ name, values }) => {
    const group = el("div", "annotation-character");
    group.append(el("h3", null, name));
    for (const value of values) {
      const row = el("div", "value-row");
      row.append(el("span", "label", control.labels[value]),
                 scale(value, editing.values[name]?.[value] ?? null, (level) => {
                   if (level === null) delete editing.values[name]?.[value];
                   else (editing.values[name] ??= {})[value] = level;
                   renderCardValues();
                 }, true));
      group.append(row);
    }
    return group;
  }));
  if (!control.characters.length) box.append(el("p", "hinweis", "Die Szene hat keine Personen."));
}

// Only the values chosen, per character with any.
function chosenValues() {
  return Object.fromEntries(Object.entries(editing.values)
    .filter(([, values]) => Object.keys(values).length));
}

$("annotation-save").addEventListener("click", async () => {
  try {
    control = editing.id
      ? await request("PUT", `/api/control/annotations/${editing.id}`, { values: chosenValues() })
      : await request("POST", "/api/control/annotations",
                      { start: editing.start, end: editing.end, values: chosenValues() });
    closeCard();
    window.getSelection().removeAllRanges();
    renderText();
  } catch (error) {
    notice("annotation-error", error.message, true);
  }
});

$("annotation-delete").addEventListener("click", async () => {
  try {
    control = await request("DELETE", `/api/control/annotations/${editing.id}`);
    closeCard();
    renderText();
  } catch (error) {
    notice("annotation-error", error.message, true);
  }
});

$("annotation-cancel").addEventListener("click", closeCard);

// A selection within the text opens the card for a new passage; a click on
// a marked passage opens it for that one.
$("script-text").addEventListener("mouseup", (event) => {
  const selection = window.getSelection();
  const box = $("script-text");
  if (selection.rangeCount && !selection.isCollapsed) {
    const range = selection.getRangeAt(0);
    if (!box.contains(range.startContainer) || !box.contains(range.endContainer)) return;
    const start = offsetOf(range.startContainer, range.startOffset);
    const end = offsetOf(range.endContainer, range.endOffset);
    if (!control.text.slice(start, end).trim()) return;
    const overlapping = control.annotations.find((other) => start < other.end && other.start < end);
    if (overlapping) {
      notice("script-notice", "Die Auswahl überschneidet eine annotierte Stelle. Diese anklicken, um sie zu ändern.", true);
      return;
    }
    notice("script-notice", "");
    openCard({ start, end, values: {} }, range.getBoundingClientRect());
    return;
  }
  const mark = event.target.closest?.("mark.passage");
  if (!mark) return;
  const annotation = control.annotations.find((kept) => kept.id === mark.dataset.id);
  if (annotation) {
    openCard({ id: annotation.id, start: annotation.start, end: annotation.end,
               values: structuredClone(annotation.values) }, mark.getBoundingClientRect());
  }
});

// The passage last recognised: named in the heading, marked in the text, and
// scrolled to while the operator is not editing.
function renderCue(cue) {
  $("cue").textContent = cue
    ? `Gehört ${clock(cue.time)} \\ ${cue.summary || "keine Werte"}` : "";
  for (const mark of $("script-text").querySelectorAll("mark.passage")) {
    if (mark.dataset.id === cue?.id) mark.dataset.fired = "";
    else delete mark.dataset.fired;
  }
  const mark = cue && $("script-text").querySelector(`mark.passage[data-id="${CSS.escape(cue.id)}"]`);
  if (mark && !editing && $("script-editor").hidden) mark.scrollIntoView({ block: "center", behavior: "smooth" });
}

// ---- 3 \ Renaming: the bodies in view ----------------------------------------

// Each body in view, left to right, with the names it can be given; a name
// given holds until "Automatisch" releases it (session.Session.assign).
function renderInView(snapshot) {
  const list = $("in-view");
  const names = snapshot.quelle?.namen ?? [];
  const bodies = snapshot.in_view ?? [];
  list.replaceChildren(...bodies.map((body) => {
    const row = el("div", "in-view-row");
    row.dataset.state = body.assigned ? "assigned"
      : names.includes(body.label) ? "recognised" : "unnamed";
    const select = el("select");
    select.setAttribute("aria-label", `${body.label} zuordnen`);
    select.append(option("Automatisch", ""), ...names.map((name) => option(name, name)));
    select.value = body.assigned ? body.label : "";
    select.disabled = !names.length;
    select.addEventListener("change", () => {
      select.blur();
      assign(body.body, select.value || null);
    });
    row.append(el("span", "in-view-label", body.label), select);
    return row;
  }));
  if (!bodies.length) {
    list.append(el("div", "waiting", snapshot.status !== "running" ? "Kein Lauf."
      : snapshot.quelle?.aktionen === false ? "Aktionserkennung aus: niemand wird verfolgt."
      : "Niemand im Bild."));
  } else if (!names.length) {
    list.append(el("p", "hinweis", "Keine Besetzung geladen. Auf der Startseite wählen."));
  }
}

async function assign(body, name) {
  try {
    render(await request("POST", "/api/sitrep/assign", { body, name }));
    notice("in-view-error", "");
  } catch (error) {
    notice("in-view-error", `Nicht zugeordnet: ${error.message}`, true);
  }
}

// ---- Scene and run ---------------------------------------------------------

async function loadScenes() {
  try {
    const data = await request("GET", "/api/scenes");
    $("scene").replaceChildren(...data.scenes.map(({ name }) => option(name, name)));
    $("scene").value = data.selected.name;
    $("scene").disabled = false;
  } catch (error) {
    $("meta").textContent = `Szenen konnten nicht gelesen werden: ${error.message}`;
  }
}

$("scene").addEventListener("change", async () => {
  try {
    await request("POST", "/api/scene", { name: $("scene").value });
  } catch (error) {
    $("scene").value = current?.scene?.name ?? "";
    $("meta").textContent = `Szene nicht übernommen: ${error.message}`;
  }
});

async function loadControl() {
  const data = await request("GET", "/api/control");
  if (data.scene !== control?.scene) closeCard();
  control = data;
  renderText();
  drawn.characters = null;
  if (current) render(current);
}

$("toggle").addEventListener("click", async () => {
  const active = current && ["running", "starting"].includes(current.status);
  render(await request("POST", active ? "/api/sitrep/stop" : "/api/sitrep/start"));
});

function render(snapshot) {
  current = snapshot;
  const status = snapshot.status;
  const running = status === "running";
  $("status").dataset.status = status;
  $("status").textContent = STATUS_TEXT[status] ?? status;
  const active = running || status === "starting";
  $("toggle").textContent = active ? "Stoppen" : "Starten";
  $("toggle").disabled = status === "stopping";

  const scene = snapshot.scene;
  if (scene && document.activeElement !== $("scene") && !$("scene").disabled) $("scene").value = scene.name;
  $("meta").textContent = [
    ...Object.entries(scene?.keys ?? {}).map(([key, bound]) => `${key.toUpperCase()}: ${bound.label}`),
    "E: Empfehlung", "X: Schließen / Override",
    ...(scene?.warnings ?? []), ...(snapshot.error ? [snapshot.error] : []),
  ].join(" \\ ");

  if (running && !feedOpen) {
    $("video").src = `${FEED}&t=${Date.now()}`;
    feedOpen = true;
  } else if (!running && feedOpen) {
    $("video").removeAttribute("src");
    feedOpen = false;
  }
  $("feed-empty").hidden = running;
  $("feed-empty").textContent = status === "starting" ? "Kamera und Modelle werden geladen …" : "Gestoppt.";

  // A new scene, or the cast of a run, changes the characters and the text.
  if (changed("control", [scene?.name, snapshot.quelle?.besetzung])) {
    loadControl().catch((error) => notice("script-notice", `Szenentext nicht geladen: ${error.message}`, true));
  }
  if (!control) return;

  if (!$("characters").contains(document.activeElement)
      && changed("characters", [control.characters, control.initial, snapshot.werte?.personen,
                                snapshot.im_bild])) {
    renderCharacters();
  }
  if (!$("in-view").contains(document.activeElement)
      && changed("in-view", [status, snapshot.in_view, snapshot.quelle?.namen,
                             snapshot.quelle?.aktionen])) {
    renderInView(snapshot);
  }
  if (changed("cue", snapshot.cue)) renderCue(snapshot.cue);
}

// A feed that drops while the run continues is reopened.
$("video").addEventListener("error", () => {
  if (current?.status !== "running") return;
  setTimeout(() => {
    if (current?.status === "running") $("video").src = `${FEED}&t=${Date.now()}`;
  }, 1000);
});

// ---- Keys --------------------------------------------------------------------

async function post(path) {
  try {
    render(await request("POST", path));
  } catch {
    // A key that does nothing now leaves the page as it is.
  }
}

// The scene's keys, E for a recommendation, and X, which closes a screen or
// the stroboscope, or overrides a recommendation to intervene; not while
// typing, and not with a modifier. Escape closes the annotation card.
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && editing) {
    closeCard();
    return;
  }
  if (event.repeat || event.ctrlKey || event.metaKey || event.altKey) return;
  if (event.target.closest?.("input, textarea, select, [contenteditable]")) return;
  if (editing) return;
  const key = event.key.toLowerCase();
  const scene = current?.scene;
  if (scene?.keys?.[key]) {
    post(`/api/sitrep/key/${encodeURIComponent(key)}`);
  } else if (key === "e") {
    if (current?.status === "running") post("/api/sitrep/empfehlung");
  } else if (key === "x") {
    if (scene?.screen || scene?.strobe) post("/api/sitrep/screen/close");
    else if (current?.empfehlung?.urteil?.einschreiten) {
      post(`/api/sitrep/override?nummer=${current.empfehlung.nummer}`);
    }
  } else {
    return;
  }
  event.preventDefault();
});

loadScenes();
const events = new EventSource("/api/sitrep/events");
events.onmessage = (message) => render(JSON.parse(message.data));
