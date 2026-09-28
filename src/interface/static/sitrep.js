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

const PERSON_RATINGS = ["risiko", "menschlichkeit", "auffaelligkeit"];

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

// Per-person risk on its 0-5 scale; the other ratings stay neutral.
function personLevel(name, value) {
  if (name !== "risiko") return "calm";
  return value >= 4 ? "red" : value >= 2 ? "amber" : "calm";
}

const clock = (iso) => (iso ? iso.slice(11, 19) : "");

// Evidence from the action table, signed, one decimal.
const signed = (value) => (value > 0 ? `+${value.toFixed(1)}` : value < 0 ? `−${(-value).toFixed(1)}` : "0");

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
    const value = person[name];
    const row = el("div", "rating");
    const pips = el("span", "pips");
    // null: the action recogniser read nothing of this person.
    if (value === null) {
      row.dataset.level = "calm";
      pips.append(el("span", "unmeasured", "nicht gemessen"));
      pips.title = "nicht gemessen";
    } else {
      row.dataset.level = personLevel(name, value);
      for (let i = 1; i <= 5; i++) pips.append(el("span", i <= value ? "pip on" : "pip"));
      pips.title = `${value} / 5`;
    }
    // The number as well as the pips: a 0 shows as empty pips alone.
    row.append(el("span", null, name), pips, el("span", "value num", value === null ? "–" : String(value)));
    ratings.append(row);
  }
  card.append(ratings);
  if (person.anlass.length) card.append(el("p", "anlass", person.anlass.join(" · ")));
  return card;
}

// One card per person the action recogniser measured, including anyone the
// model left out of its list of people.
function gemessenCard(handlung) {
  const card = el("div", "person");
  const title = el("h3", null, handlung.name);
  title.append(el("span", "guess", `${handlung.lesungen} Lesungen`));
  card.append(title,
    meter("risiko", handlung.risiko, 5, personLevel("risiko", handlung.risiko)),
    meter("menschlichkeit", handlung.menschlichkeit, 5, "calm"));
  const anlass = ["risiko", "menschlichkeit"]
    .filter((name) => handlung[`anlass_${name}`])
    .map((name) => `${name}: ${handlung[`anlass_${name}`]}`);
  if (anlass.length) card.append(el("p", "anlass", anlass.join(" · ")));
  return card;
}

// The recogniser's last classification, refreshed every second between reports.
function renderAktionen(aktionen, status) {
  const panel = $("aktionen");
  panel.hidden = !aktionen || status !== "running";
  if (panel.hidden) return;

  const hinweis = $("aktionen-hinweis");
  const liste = $("aktionen-liste");
  hinweis.dataset.level = "calm";
  if (!aktionen.aktiv) {
    hinweis.textContent = "Aus: Risiko und Menschlichkeit werden nicht gemessen.";
    liste.replaceChildren();
    return;
  }
  if (aktionen.fehler) {
    hinweis.dataset.level = "red";
    hinweis.textContent = `Gestoppt: ${aktionen.fehler}`;
    liste.replaceChildren();
    return;
  }
  hinweis.textContent = aktionen.stand
    ? `Klassifikation ${aktionen.stand} · jede Sekunde, über die letzten 4 s · ` +
      "Körper ohne Namen gehen nicht in den Bericht ein."
    : "Erste Klassifikation nach 4 s …";

  liste.replaceChildren(...aktionen.lesungen.map((lesung) => {
    const row = el("div", "aktion");
    row.dataset.level = lesung.risiko >= 3 ? "red" : lesung.risiko >= 1.5 ? "amber" : "calm";
    row.append(
      el("span", "wer", lesung.wer.join(" + ")),
      el("span", "handlung", `${lesung.handlung} ${Math.round(100 * lesung.wahrscheinlichkeit)} %`),
      el("span", "evidenz num risiko", `risiko ${signed(lesung.risiko)}`),
      el("span", "evidenz num", `menschlichkeit ${signed(lesung.menschlichkeit)}`),
    );
    return row;
  }));
  if (!aktionen.lesungen.length) liste.append(el("div", "waiting", "Niemand im Bild erkannt."));
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
  // Loudness: calibrating on the first speech, then the session's normal level.
  const pegel = report.pegel;
  if (pegel) {
    head.append(el("span", "num", pegel.kalibriert
      ? `Pegel normal ${Math.round(pegel.normal_db)} dBFS ±${Math.round(pegel.streuung_db)}` +
        (pegel.endgueltig ? "" : ` · lernt ${Math.round(pegel.gehoert_s)}/120 s`)
      : `Pegel kalibriert ${Math.round(pegel.gehoert_s)}/30 s`));
  }
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
  // One line per segment, with its speaker where the lips showed who it was.
  const gesagt = $("gesagt");
  if (report.aeusserungen.length) {
    gesagt.replaceChildren(...report.aeusserungen.map((line) => {
      const row = el("div", "zeile");
      const text = el("span", null, `„${line.text}“`);
      // A line's evidence, where the model read any, with its reason on hover.
      const evidence = ["risiko", "menschlichkeit"]
        .filter((name) => line[name])
        .map((name) => `${name} ${signed(line[name])}` +
             (name === "risiko" && line.verstaerkung > 1 ? ` ×${line.verstaerkung.toFixed(1)}` : ""));
      if (evidence.length) {
        const tag = el("span", "gewertet", evidence.join(" · "));
        tag.dataset.level = line.risiko >= 3 ? "red" : line.risiko >= 1 ? "amber" : "calm";
        text.append(" ", tag);
      }
      if (line.begruendung) text.title = line.begruendung;
      row.append(el("span", line.name ? "sprecher" : "sprecher unklar", line.name ?? "unklar"), text);
      return row;
    }));
  } else {
    gesagt.textContent = report.gesagt ? `„${report.gesagt}“` : "";
  }

  $("szene").replaceChildren(
    meter("relevanz", szene.relevanz, 10, "calm"),
    meter("eskalation", szene.eskalation, 10, sceneLevel(szene.eskalation, schwelle), schwelle),
    meter("gefahr", szene.gefahr, 10, sceneLevel(szene.gefahr, schwelle), schwelle),
  );

  const personen = $("personen");
  personen.replaceChildren(...bericht.personen.map(personCard));
  if (!bericht.personen.length) personen.append(el("div", "waiting", "Niemand erfasst."));

  const gemessen = $("gemessen");
  gemessen.replaceChildren(...report.handlungen.map(gemessenCard));
  if (!report.handlungen.length) {
    gemessen.append(el("div", "waiting", current?.quelle?.aktionen === false
      ? "Aktionserkennung aus." : "Niemand gemessen: kein Körper mit erkanntem Gesicht."));
  }

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
       quelle.aktionen ? "Aktionserkennung an" : "Aktionserkennung aus",
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

  renderAktionen(snapshot.aktionen, status);

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
