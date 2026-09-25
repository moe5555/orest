// Live SITREP page: starts the run on opening, follows its state over
// server-sent events and renders each report beneath the camera feed.
// Report text is set with textContent only, so model output cannot inject markup.
"use strict";

const $ = (id) => document.getElementById(id);

const STATUS_TEXT = {
  idle: "Gestoppt", starting: "Startet", running: "Live",
  stopping: "Wird beendet", error: "Fehler",
};

const FEED_TEXT = {
  starting: "Kamera und Modelle werden geladen …",
  stopping: "Wird beendet …",
  idle: "Gestoppt.",
  error: "Kein Bild.",
};

const PERSON_RATINGS = ["kollaborativ", "relevanz", "verantwortungsvoll", "menschlich", "gefahr"];

let current = null;
let feedOpen = false;

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

// Scene ratings against the intervention threshold, as the console colours them.
function sceneLevel(value, schwelle) {
  if (value > schwelle) return "red";
  if (value >= schwelle - 2) return "amber";
  return "calm";
}

// Per-person danger on its 0-5 scale; the other ratings stay neutral.
function personLevel(name, value) {
  if (name !== "gefahr") return "calm";
  return value >= 4 ? "red" : value >= 2 ? "amber" : "calm";
}

const clock = (iso) => (iso ? iso.slice(11, 19) : "");

function meter(name, value, max, levelName, tickAt) {
  const row = el("div", "meter");
  row.dataset.level = levelName;
  row.append(el("span", "name", name));
  const track = el("div", "track");
  const fill = el("div", "fill");
  fill.style.width = `${(100 * value) / max}%`;
  track.append(fill);
  if (tickAt !== undefined) {
    const tick = el("div", "tick");
    tick.style.left = `${(100 * tickAt) / max}%`;
    tick.title = `Schwelle ${tickAt}`;
    track.append(tick);
  }
  row.append(track, el("span", "value num", String(value)));
  return row;
}

function personCard(person) {
  const card = el("div", "person");
  const title = el("h3", null, person.name);
  if (person.vermutet) title.append(el("span", "guess", "vermutet"));
  card.append(title);
  if (person.beschreibung) card.append(el("p", null, person.beschreibung));

  const ratings = el("div", "ratings");
  for (const name of PERSON_RATINGS) {
    const row = el("div", "rating");
    row.dataset.level = personLevel(name, person[name]);
    const pips = el("span", "pips");
    for (let i = 1; i <= 5; i++) pips.append(el("span", i <= person[name] ? "pip on" : "pip"));
    pips.title = `${person[name]} / 5`;
    row.append(el("span", null, name), pips);
    ratings.append(row);
  }
  card.append(ratings);
  return card;
}

function renderReport(report) {
  const bericht = report.bericht;
  const zeit = report.zeitfenster;
  const szene = bericht.szene;
  const schwelle = report.schwelle;

  const head = $("report-head");
  head.replaceChildren(
    el("strong", null, `SITREP ${report.nummer}`),
    el("span", "num", `${clock(zeit.beginn)} – ${clock(zeit.ende)}`),
    el("span", "num", `${report.quelle.bilder} Bilder · ${report.quelle.ton_s} s Ton`),
    el("span", "num", `Latenz ${report.latenz_s} s`),
  );
  const age = el("span", "num");
  age.id = "age";
  head.append(age);
  updateAge();

  const empfehlung = $("empfehlung");
  empfehlung.classList.toggle("alarm", bericht.einschreiten);
  $("verdict").textContent = bericht.einschreiten ? "Einschreiten" : "Kein Einschreiten";
  $("massnahme").textContent = bericht.einschreiten
    ? (bericht.empfehlung || "Keine Maßnahme angegeben.")
    : "";
  $("grund").textContent = `Eskalation ${szene.eskalation} · Gefahr ${szene.gefahr} · Schwelle ${schwelle}`;

  $("beschreibung").textContent = bericht.beschreibung || "—";
  $("gesagt").textContent = report.gesagt ? `„${report.gesagt}“` : "";

  $("szene").replaceChildren(
    meter("relevanz", szene.relevanz, 10, "calm"),
    meter("eskalation", szene.eskalation, 10, sceneLevel(szene.eskalation, schwelle), schwelle),
    meter("gefahr", szene.gefahr, 10, sceneLevel(szene.gefahr, schwelle), schwelle),
  );

  const personen = $("personen");
  personen.replaceChildren(...bericht.personen.map(personCard));
  if (!bericht.personen.length) personen.append(el("div", "waiting", "Niemand erfasst."));

  $("prognose").replaceChildren(...bericht.prognose.map((verlauf) => {
    const row = el("div", "verlauf");
    const track = el("div", "track");
    const fill = el("div", "fill");
    fill.style.width = `${verlauf.wahrscheinlichkeit}%`;
    track.append(fill);
    row.append(el("span", "pct num", `${verlauf.wahrscheinlichkeit} %`),
               el("span", "text", verlauf.verlauf), track);
    return row;
  }));
}

function render(snapshot) {
  current = snapshot;
  const status = snapshot.status;
  const quelle = snapshot.quelle;

  $("status").dataset.status = status;
  $("status").textContent = STATUS_TEXT[status] ?? status;
  $("meta").textContent = quelle
    ? [quelle.kamera, quelle.mikrofon, quelle.modell, `Fenster ${quelle.fenster_s} s`,
       quelle.besetzung.length ? `Besetzung: ${quelle.besetzung.join(", ")}`
                               : "ohne Besetzung, Namen vermutet"].join(" · ")
    : "";

  const active = status === "running" || status === "starting";
  $("toggle").textContent = active ? "Stoppen" : "Neu starten";
  $("toggle").disabled = status === "stopping";

  if (status === "running" && !feedOpen) {
    $("video").src = `/api/sitrep/video?t=${Date.now()}`;
    feedOpen = true;
  } else if (status !== "running" && feedOpen) {
    $("video").removeAttribute("src");
    feedOpen = false;
  }
  $("feed-empty").hidden = status === "running";
  $("feed-empty").textContent = FEED_TEXT[status] ?? "";
  $("feed-tag").hidden = status !== "running";

  $("error").hidden = status !== "error";
  $("error-text").textContent = snapshot.error ?? "";

  // The last report stays on screen after a stop; a new run clears it.
  const report = snapshot.report;
  $("report").hidden = !report;
  $("waiting").hidden = Boolean(report) || status !== "running";
  if (quelle) {
    $("waiting").textContent =
      `Warte auf den ersten Bericht … ein Fenster dauert ${quelle.fenster_s} s, danach rechnet das Modell.`;
  }
  if (report) renderReport(report);
}

function updateAge() {
  const age = $("age");
  const ende = current?.report?.zeitfenster?.ende;
  if (!age || !ende) return;
  const seconds = Math.max(0, Math.round((Date.now() - Date.parse(ende)) / 1000));
  age.textContent = `vor ${seconds} s`;
}

async function post(path) {
  const response = await fetch(path, { method: "POST" });
  render(await response.json());
}

// A feed that drops while the run continues (a server restart, a network
// hiccup) is reopened rather than left blank.
$("video").addEventListener("error", () => {
  if (current?.status !== "running") return;
  setTimeout(() => {
    if (current?.status === "running") $("video").src = `/api/sitrep/video?t=${Date.now()}`;
  }, 1000);
});

$("toggle").addEventListener("click", () => {
  const active = current && (current.status === "running" || current.status === "starting");
  post(active ? "/api/sitrep/stop" : "/api/sitrep/start");
});

function tick() {
  $("clock").textContent = new Date().toLocaleTimeString("de-DE");
  updateAge();
}
tick();
setInterval(tick, 1000);

// Opening this page is what "Start live SITREP" asks for.
post("/api/sitrep/start").finally(() => {
  const events = new EventSource("/api/sitrep/events");
  events.onmessage = (message) => render(JSON.parse(message.data));
});
