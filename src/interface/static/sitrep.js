// Live SITREP page: starts the run on opening and follows its state over
// server-sent events. The live values, lines and Chronik update as they
// change; a report is made only when asked for (R), a recommendation when the
// alarm is raised or when asked for (E).
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

const PERSON_RATINGS = ["risiko", "menschlichkeit", "vorhersehbarkeit"];
// Ratings measured as evidence from actions and lines, 0-5.
const LIVE_RATINGS = ["risiko", "menschlichkeit"];
// Ratings shown per person live: the evidence and Vorhersehbarkeit, -5 to +5.
const LIVE_SHOWN = [...LIVE_RATINGS, "vorhersehbarkeit"];

// A recommendation older than this is shown dimmed.
const EMPFEHLUNG_FRISCH_MS = 60000;

const TENDENZ = { zuspitzend: "↗", gleichbleibend: "→", beruhigend: "↘" };

let current = null;
let feedOpen = false;

// Views over the same snapshot, by the name their tab carries. A view may
// define render(snapshot), taste(key) returning true for a key it handles in
// place of the page's own, verlassen() when another tab is chosen, and feed,
// a query the camera feed is opened with while the view is shown.
// Prototype scripts add themselves here.
const ANSICHTEN = { uebersicht: {} };

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

// Per-person risk on its 0-5 scale, and Vorhersehbarkeit mirrored on its
// -5 to +5; the other ratings stay neutral.
function personLevel(name, value) {
  if (name === "risiko") return value >= 4 ? "red" : value >= 2 ? "amber" : "calm";
  if (name === "vorhersehbarkeit") return value <= -4 ? "red" : value <= -2 ? "amber" : "calm";
  return "calm";
}

// A whole rating as text, a negative one with a typographic minus.
const ratingText = (value) => (value < 0 ? `−${-value}` : String(value));

const clock = (iso) => (iso ? iso.slice(11, 19) : "");

const ago = (iso) => (iso ? `vor ${Math.max(0, Math.round((Date.now() - Date.parse(iso)) / 1000))} s` : "");

// Evidence, signed, one decimal.
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

// One rating as pips and its number; null means not measured. A negative
// value fills as many pips as its magnitude.
function ratingRow(name, value) {
  const row = el("div", "rating");
  const pips = el("span", "pips");
  if (value === null || value === undefined) {
    row.dataset.level = "calm";
    pips.append(el("span", "unmeasured", "nicht gemessen"));
    pips.title = "nicht gemessen";
  } else {
    row.dataset.level = personLevel(name, value);
    for (let i = 1; i <= 5; i++) pips.append(el("span", i <= Math.abs(value) ? "pip on" : "pip"));
    pips.title = name === "vorhersehbarkeit" ? `${ratingText(value)} (−5 bis 5)` : `${value} / 5`;
  }
  // The number as well as the pips: a 0 shows as empty pips alone.
  row.append(el("span", null, name), pips,
             el("span", "value num", value === null || value === undefined ? "–" : ratingText(value)));
  return row;
}

// ---- Live lane ------------------------------------------------------------

// The sound's level in the header; a silent source as a warning above all.
function renderTon(ton, running) {
  const level = $("ton");
  level.hidden = !running || !ton;
  $("stumm").hidden = !running || !ton?.stumm;
  if (level.hidden) return;
  level.dataset.stumm = String(ton.stumm);
  level.textContent = ton.pegel_db === null ? "Ton –" : `Ton ${Math.round(ton.pegel_db)} dBFS`;
  $("stumm-text").textContent =
    `Von „${ton.quelle}“ kommt seit ${Math.round(ton.still_s)} s kein Ton. Ohne Ton entstehen ` +
    "keine Zeilen, und die Chronik sieht nur Standbilder. Tonquelle prüfen: --audio oder " +
    "--audio-ndi, z. B. --audio-ndi \"VSH-ARLT-5090 (OBS PGM)\".";
}

function renderAlarm(werte, laeuft) {
  const panel = $("alarm");
  const alarm = werte?.alarm;
  const aktiv = Boolean(alarm?.aktiv);
  panel.dataset.aktiv = String(aktiv);
  $("alarm-verdict").textContent = aktiv
    ? `Alarm · ${alarm.wer ?? "Sprecher unklar"} · Risiko ${alarm.wert}`
    : "Ruhig";
  $("alarm-grund").textContent = aktiv
    ? alarm.anlass + (laeuft?.empfehlung ? " · Empfehlung wird erstellt …" : "")
    : (werte ? `Kein Messwert über Risiko 2 · Stand ${clock(werte.zeit)}` : "Noch keine Messwerte.");
}

function renderEmpfehlung(empfehlung, laeuft, fehler) {
  const panel = $("empfehlung");
  const urteil = empfehlung?.urteil;
  panel.classList.toggle("alarm", Boolean(urteil?.einschreiten));
  panel.dataset.laeuft = String(Boolean(laeuft?.empfehlung));
  if (!empfehlung) {
    $("verdict").textContent = laeuft?.empfehlung ? "Empfehlung wird erstellt …" : "Keine Empfehlung";
    $("empfehlung-zeit").textContent = "";
    $("massnahme").textContent = "";
    $("lage-satz").textContent = fehler?.empfehlung
      ? `Fehlgeschlagen: ${fehler.empfehlung}`
      : "Entsteht bei Alarm oder mit E.";
    $("empfehlung-anlass").textContent = "";
    return;
  }
  $("verdict").textContent = (urteil.einschreiten ? "Einschreiten" : "Kein Einschreiten") +
    (laeuft?.empfehlung ? " · neue wird erstellt …" : "");
  $("empfehlung-zeit").dataset.zeit = empfehlung.zeit;
  $("empfehlung-zeit").textContent =
    `${clock(empfehlung.zeit)} · ${ago(empfehlung.zeit)} · Eskalation ${urteil.szene.eskalation} · ` +
    `Gefahr ${urteil.szene.gefahr}`;
  $("massnahme").textContent = urteil.empfehlung;
  $("lage-satz").textContent = urteil.lage;
  $("empfehlung-anlass").textContent = `Anlass: ${empfehlung.anlass}`;
}

// Strongest first; people measured at 0 on everything share one line.
function renderLivePersonen(werte) {
  const list = $("live-personen");
  const strength = (person) => Math.max(...LIVE_RATINGS.map((name) => person[name] ?? 0));
  const personen = (werte?.personen ?? []).slice().sort((a, b) => strength(b) - strength(a));
  const ruhig = personen.filter((person) => strength(person) === 0);
  list.replaceChildren(...personen.filter((person) => strength(person) > 0).map((person) => {
    const card = el("div", "person");
    card.append(el("h3", null, person.name));
    const ratings = el("div", "ratings");
    for (const name of LIVE_SHOWN) ratings.append(ratingRow(name, person[name]));
    card.append(ratings);
    const anlass = LIVE_RATINGS.filter((name) => person[`anlass_${name}`])
      .map((name) => `${name}: ${person[`anlass_${name}`]}`);
    if (anlass.length) {
      const text = el("p", "anlass", anlass.join(" · "));
      text.title = text.textContent;
      card.append(text);
    }
    return card;
  }));
  if (ruhig.length) {
    list.append(el("p", "ruhig", `Ohne Befund: ${ruhig.map((person) => person.name).join(", ")}`));
  }
  if (!personen.length) {
    list.append(el("div", "waiting", current?.quelle?.aktionen === false
      ? "Aktionserkennung aus; nur Zeilen mit Sprecher werden gemessen."
      : "Niemand gemessen."));
  }
}

function zeileRow(line) {
  const row = el("div", "zeile");
  const text = el("span", null, `„${line.text}“`);
  const evidence = LIVE_RATINGS
    .filter((name) => line[name])
    .map((name) => `${name} ${signed(line[name])}` +
         (name === "risiko" && line.verstaerkung > 1 ? ` ×${line.verstaerkung.toFixed(1)}` : ""));
  if (evidence.length) {
    const tag = el("span", "gewertet", evidence.join(" · "));
    tag.dataset.level = line.risiko >= 3 ? "red" : line.risiko >= 1 ? "amber" : "calm";
    text.append(" ", tag);
  } else if (line.bewertet === false) {
    // Transcribed; its rating follows within about a second.
    text.append(" ", el("span", "gewertet", "…"));
  }
  if (line.lautstaerke) text.append(" ", el("span", "gewertet", line.lautstaerke));
  if (line.begruendung) text.title = line.begruendung;
  const wer = el("span", line.name ? "sprecher" : "sprecher unklar", line.name ?? "unklar");
  if (line.zeit) wer.title = clock(line.zeit);
  row.append(wer, text);
  return row;
}

function renderZeilen(zeilen) {
  const list = $("zeilen");
  list.replaceChildren(...zeilen.map(zeileRow).reverse());
  if (!zeilen.length) list.append(el("div", "waiting", "Noch nichts gesagt."));
}

// ---- Chronik --------------------------------------------------------------

const SVG = "http://www.w3.org/2000/svg";

function svg(tag, attributes) {
  const node = document.createElementNS(SVG, tag);
  for (const [key, value] of Object.entries(attributes)) node.setAttribute(key, value);
  return node;
}

// Eskalation and Gefahr per Abschnitt, 0-10, with the intervention threshold.
function renderKurve(kurve, schwelle) {
  const box = $("kurve");
  if (kurve.length < 2) {
    box.replaceChildren(el("div", "hinweis", "Die Kurve entsteht ab dem zweiten Abschnitt."));
    return;
  }
  const width = 600, height = 64, pad = 4;
  const x = (i) => pad + (i * (width - 2 * pad)) / (kurve.length - 1);
  const y = (v) => height - pad - (v * (height - 2 * pad)) / 10;
  const chart = svg("svg", { viewBox: `0 0 ${width} ${height}`, preserveAspectRatio: "none",
                             role: "img", "aria-label": "Eskalation und Gefahr je Abschnitt" });
  chart.append(svg("line", { x1: 0, x2: width, y1: y(schwelle), y2: y(schwelle), class: "schwelle" }));
  for (const [name, cls] of [["gefahr", "gefahr"], ["eskalation", "eskalation"]]) {
    chart.append(svg("polyline", {
      points: kurve.map((punkt, i) => `${x(i)},${y(punkt[name])}`).join(" "),
      class: cls, "vector-effect": "non-scaling-stroke",
    }));
  }
  const legend = el("div", "kurve-legende num",
    `${clock(kurve[0].ende)} – ${clock(kurve[kurve.length - 1].ende)} · `);
  legend.append(el("span", "eskalation", "Eskalation"), " · ", el("span", "gefahr", "Gefahr"),
                ` · Schwelle ${schwelle}`);
  box.replaceChildren(chart, legend);
}

function renderChronik(chronik, schwelle) {
  if (!chronik) {
    $("kurve").replaceChildren();
    $("abschnitte").replaceChildren();
    $("rueckblick").hidden = true;
    return;
  }
  renderKurve(chronik.kurve, schwelle);
  const list = $("abschnitte");
  // Newest first: the Chronik is read from the present backwards.
  list.replaceChildren(...chronik.abschnitte.slice().reverse().map((abschnitt) => {
    const row = el("div", "abschnitt");
    const summary = abschnitt.zusammenfassung;
    const head = el("span", "wann num", `${clock(abschnitt.beginn)}–${clock(abschnitt.ende)}`);
    if (!summary) {
      row.append(head, el("span", "text dim", "ohne Zusammenfassung"));
      return row;
    }
    const szene = summary.szene;
    const level = sceneLevel(Math.max(szene.eskalation, szene.gefahr), schwelle);
    const werte = el("span", "werte num",
      `E ${szene.eskalation} · G ${szene.gefahr} ${TENDENZ[summary.tendenz] ?? ""}`);
    werte.dataset.level = level;
    werte.title = summary.tendenz;
    row.append(head, werte, el("span", "text", summary.zusammenfassung));
    return row;
  }));
  const hinweis = el("div", "hinweis", `Nächster Abschnitt ${clock(chronik.naechster)}.`);
  list.prepend(hinweis);
  const rueckblick = $("rueckblick");
  rueckblick.hidden = !chronik.rueckblick;
  rueckblick.textContent = chronik.rueckblick
    ? `Rückblick bis ${clock(chronik.rueckblick_bis)}: ${chronik.rueckblick}` : "";
}

// ---- Report, on request ---------------------------------------------------

// One card per person the action recogniser measured, including anyone the
// model left out of its list of people.
function gemessenCard(handlung) {
  const card = el("div", "person");
  const title = el("h3", null, handlung.name);
  title.append(el("span", "guess", `${handlung.lesungen} Lesungen`));
  card.append(title,
    meter("risiko", handlung.risiko, 5, personLevel("risiko", handlung.risiko)),
    meter("menschlichkeit", handlung.menschlichkeit, 5, "calm"));
  if (handlung.vorhersehbarkeit !== null) {
    card.append(ratingRow("vorhersehbarkeit", handlung.vorhersehbarkeit));
  }
  const anlass = LIVE_RATINGS
    .filter((name) => handlung[`anlass_${name}`])
    .map((name) => `${name}: ${handlung[`anlass_${name}`]}`);
  if (anlass.length) card.append(el("p", "anlass", anlass.join(" · ")));
  return card;
}

function personCard(person) {
  const card = el("div", "person");
  const title = el("h3", null, person.name);
  card.append(title);
  if (person.beschreibung) card.append(el("p", null, person.beschreibung));
  const ratings = el("div", "ratings");
  for (const name of PERSON_RATINGS) ratings.append(ratingRow(name, person[name]));
  card.append(ratings);
  if (person.anlass.length) card.append(el("p", "anlass", person.anlass.join(" · ")));
  return card;
}

function renderReportStatus(snapshot) {
  const status = $("report-status");
  const laeuft = snapshot.laeuft?.bericht;
  const fehler = snapshot.fehler?.bericht;
  status.hidden = !laeuft && !fehler;
  status.dataset.level = fehler && !laeuft ? "red" : "calm";
  status.textContent = laeuft ? "Lagebericht wird erstellt …"
    : fehler ? `Lagebericht fehlgeschlagen: ${fehler}` : "";
  $("report-bereich").hidden = !snapshot.report && status.hidden;
}

function renderReport(report) {
  const bericht = report.bericht;
  const zeit = report.zeitfenster;
  const szene = bericht.szene;
  const schwelle = report.schwelle;

  const head = $("report-head");
  head.replaceChildren(
    el("strong", null, `LAGEBERICHT ${report.nummer}`),
    el("span", "num", `${clock(zeit.beginn)} – ${clock(zeit.ende)}`),
    el("span", "num", `${report.quelle.abschnitte} Abschnitte · ${report.quelle.woertlich_s} s wörtlich · ` +
                      `${report.quelle.bilder} Bilder`),
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

  $("verlauf").textContent = bericht.verlauf || "—";

  const empfehlung = $("report-empfehlung");
  empfehlung.classList.toggle("alarm", bericht.einschreiten);
  $("report-verdict").textContent = bericht.einschreiten ? "Einschreiten" : "Kein Einschreiten";
  $("report-massnahme").textContent = bericht.einschreiten
    ? (bericht.empfehlung || "Keine Maßnahme angegeben.")
    : "";
  $("report-grund").textContent = `Eskalation ${szene.eskalation} · Gefahr ${szene.gefahr} · Schwelle ${schwelle}`;

  $("beschreibung").textContent = bericht.beschreibung || "—";
  const gesagt = $("gesagt");
  if (report.aeusserungen.length) {
    gesagt.replaceChildren(...report.aeusserungen.map((line) => zeileRow({ ...line, zeit: line.ende })));
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

// ---- Action recogniser ----------------------------------------------------

// The recogniser's last classification, refreshed every second.
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
      "Körper ohne Namen gehen nicht in die Werte ein."
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

// ---- People in view: naming by hand ----------------------------------------

// Each body in view, left to right as in the picture, with the cast names it
// can be given. A name given here holds until "Automatisch" releases it
// (session.Session.assign).
function renderInView(snapshot) {
  const list = $("in-view");
  const cast = snapshot.quelle?.besetzung ?? [];
  const bodies = snapshot.in_view ?? [];
  list.replaceChildren(...bodies.map((body) => {
    const row = el("div", "in-view-row");
    row.dataset.state = body.assigned ? "assigned"
      : cast.includes(body.label) ? "recognised" : "unnamed";
    const select = el("select");
    select.setAttribute("aria-label", `${body.label} zuordnen`);
    select.append(el("option", null, "Automatisch"),
                  ...cast.map((name) => el("option", null, name)));
    select.options[0].value = "";
    select.value = body.assigned ? body.label : "";
    select.disabled = !cast.length;
    select.addEventListener("change", () => {
      select.blur();
      assign(body.body, select.value || null);
    });
    row.append(el("span", "in-view-label", body.label), select);
    return row;
  }));
  if (!bodies.length) {
    list.append(el("div", "waiting", snapshot.status !== "running" ? ""
      : snapshot.quelle?.aktionen === false ? "Aktionserkennung aus: niemand wird verfolgt."
      : "Niemand im Bild."));
  } else if (!cast.length) {
    list.append(el("p", "hinweis", "Keine Besetzung geladen. Auf der Startseite wählen."));
  }
}

async function assign(body, name) {
  const response = await fetch("/api/sitrep/assign", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ body, name }),
  });
  const data = await response.json();
  $("in-view-error").hidden = response.ok;
  $("in-view-error").textContent = response.ok ? "" : `Nicht zugeordnet: ${data.detail}`;
  if (response.ok) render(data);
}

// ---- The whole page -------------------------------------------------------

// Parts are redrawn only when their data changed: a report or the Chronik
// redrawn every second would reset a reader's selection.
const drawn = {};

function changed(part, data) {
  const key = JSON.stringify(data ?? null);
  if (drawn[part] === key) return false;
  drawn[part] = key;
  return true;
}

function render(snapshot) {
  current = snapshot;
  const status = snapshot.status;
  const quelle = snapshot.quelle;
  const running = status === "running";

  $("status").dataset.status = status;
  $("status").textContent = STATUS_TEXT[status] ?? status;
  $("meta").textContent = quelle
    ? [quelle.kamera, quelle.mikrofon, quelle.modell, `Abschnitt ${quelle.fenster_s} s`,
       quelle.aktionen ? "Aktionserkennung an" : "Aktionserkennung aus",
       quelle.auto_empfehlung ? "Empfehlung bei Alarm" : "Empfehlung nur auf E",
       quelle.besetzung.length ? `Besetzung: ${quelle.besetzung.join(", ")}`
                               : "ohne Besetzung, niemand erkannt"].join(" · ")
    : "";

  const active = running || status === "starting";
  $("toggle").textContent = active ? "Stoppen" : "Neu starten";
  $("toggle").disabled = status === "stopping";
  $("ask-bericht").disabled = !running || Boolean(snapshot.laeuft?.bericht);
  $("ask-empfehlung").disabled = !running || Boolean(snapshot.laeuft?.empfehlung);

  if (running && !feedOpen) {
    $("video").src = feedSrc();
    feedOpen = true;
  } else if (!running && feedOpen) {
    $("video").removeAttribute("src");
    feedOpen = false;
  }
  $("feed-empty").hidden = running;
  $("feed-empty").textContent = FEED_TEXT[status] ?? "";
  $("feed-tag").hidden = !running;

  $("error").hidden = status !== "error";
  $("error-text").textContent = snapshot.error ?? "";

  renderTon(snapshot.ton, running);
  renderAlarm(snapshot.werte, snapshot.laeuft);
  if (changed("empfehlung", [snapshot.empfehlung, snapshot.laeuft?.empfehlung, snapshot.fehler?.empfehlung])) {
    renderEmpfehlung(snapshot.empfehlung, snapshot.laeuft, snapshot.fehler);
  }
  if (changed("werte", snapshot.werte?.personen)) renderLivePersonen(snapshot.werte);
  // Not redrawn while one of its menus is in use, which would close it.
  if (!$("in-view").contains(document.activeElement)
      && changed("in-view", [snapshot.status, snapshot.in_view, snapshot.quelle?.besetzung,
                             snapshot.quelle?.aktionen])) {
    renderInView(snapshot);
  }
  if (changed("zeilen", snapshot.zeilen)) renderZeilen(snapshot.zeilen);
  const schwelle = snapshot.report?.schwelle ?? snapshot.empfehlung?.schwelle ?? 6;
  if (changed("chronik", snapshot.chronik)) renderChronik(snapshot.chronik, schwelle);
  renderAktionen(snapshot.aktionen, status);

  // The last report stays on screen after a stop; a new run clears it.
  renderReportStatus(snapshot);
  $("report").hidden = !snapshot.report;
  if (snapshot.report && changed("report", snapshot.report)) renderReport(snapshot.report);

  document.body.dataset.screen = fullPage.state(snapshot);
  renderIntervene(snapshot.empfehlung?.urteil);
  for (const view of Object.values(ANSICHTEN)) view.render?.(snapshot);
}

// ---- Display prototypes ---------------------------------------------------

// Prototypes 1 to 3 (knowledge/components/03_render.md, "Live SITREP") share
// two states that replace the whole page, set on the body as data-screen. A
// recommendation to intervene shows alone, with its reason and measure, until
// the next recommendation or until the operator overrides it (X). R shows the
// report alone, and R again returns. The report takes precedence, since it
// was asked for.
const fullPage = {
  // The report is on screen, from one R to the next.
  report: false,

  state(snapshot) {
    if (this.report) return "report";
    const intervene = snapshot?.status === "running" && Boolean(snapshot.empfehlung?.urteil?.einschreiten);
    return intervene ? "intervene" : "normal";
  },

  // Override sets the shown recommendation aside on the server, which returns
  // every view to its regular state. It names the recommendation by number,
  // so one that arrived meanwhile is not set aside unseen.
  override() {
    if (!current || this.state(current) !== "intervene") return;
    post(`/api/sitrep/override?nummer=${current.empfehlung.nummer}`);
  },

  // R shows the report and asks for a new one while the run is live; with no
  // run and no earlier report there is nothing to show. X overrides a
  // recommendation to intervene while it is on screen.
  key(key) {
    if (key === "x" && current && this.state(current) === "intervene") {
      this.override();
      return true;
    }
    if (key !== "r") return false;
    if (this.report) {
      this.report = false;
    } else if (current?.status === "running" || current?.report) {
      this.report = true;
      askBericht();
    }
    if (current) render(current);
    return true;
  },

  leave() {
    this.report = false;
    document.body.dataset.screen = current ? this.state(current) : "normal";
  },
};

// Why the model recommends intervening (its sentence on what is happening)
// and what it recommends doing. Set as text: both are model output.
function renderIntervene(urteil) {
  $("intervene-why").textContent = urteil?.lage ?? "";
  $("intervene-measure").textContent = urteil?.empfehlung ?? "";
  $("intervene-why-row").hidden = !urteil?.lage;
  $("intervene-measure-row").hidden = !urteil?.empfehlung;
}

$("intervene-override").addEventListener("click", () => fullPage.override());

// ---- Views ----------------------------------------------------------------

const TABS = [...document.querySelectorAll(".ansichten [data-ansicht]")];

// The camera feed's address, with the query of the view shown.
function feedSrc() {
  return `/api/sitrep/video?t=${Date.now()}${ANSICHTEN[document.body.dataset.ansicht]?.feed ?? ""}`;
}

// The chosen view is kept in the address (#p1), so a reload stays on it.
function setAnsicht(name) {
  if (!TABS.some((tab) => tab.dataset.ansicht === name)) name = "uebersicht";
  const previous = document.body.dataset.ansicht;
  if (previous !== name) ANSICHTEN[previous]?.verlassen?.();
  document.body.dataset.ansicht = name;
  for (const tab of TABS) {
    if (tab.dataset.ansicht === name) tab.setAttribute("aria-current", "page");
    else tab.removeAttribute("aria-current");
  }
  history.replaceState(null, "", name === "uebersicht" ? location.pathname : `#${name}`);
  // A view that marks the picture differently gets a feed of its own.
  if (feedOpen && (ANSICHTEN[previous]?.feed ?? "") !== (ANSICHTEN[name]?.feed ?? "")) {
    $("video").src = feedSrc();
  }
  if (current) render(current);
}

for (const tab of TABS) tab.addEventListener("click", () => setAnsicht(tab.dataset.ansicht));
setAnsicht(location.hash.slice(1));

function updateAge() {
  const age = $("age");
  const ende = current?.report?.zeitfenster?.ende;
  if (age && ende) age.textContent = ago(ende);
  const empfehlung = current?.empfehlung;
  if (empfehlung) {
    const urteil = empfehlung.urteil;
    // A recommendation describes a moment; once it is old, it no longer
    // claims the operator's attention.
    const alt = Date.now() - Date.parse(empfehlung.zeit) > EMPFEHLUNG_FRISCH_MS;
    $("empfehlung").classList.toggle("alt", alt);
    $("empfehlung").classList.toggle("alarm", Boolean(urteil.einschreiten) && !alt);
    $("empfehlung-zeit").textContent =
      `${clock(empfehlung.zeit)} · ${ago(empfehlung.zeit)} · Eskalation ${urteil.szene.eskalation} · ` +
      `Gefahr ${urteil.szene.gefahr}`;
  }
}

async function post(path) {
  const response = await fetch(path, { method: "POST" });
  render(await response.json());
}

function askBericht() {
  if (current?.status === "running") post("/api/sitrep/bericht");
}

function askEmpfehlung() {
  if (current?.status === "running") post("/api/sitrep/empfehlung");
}

// A feed that drops while the run continues (a server restart, a network
// hiccup) is reopened rather than left blank.
$("video").addEventListener("error", () => {
  if (current?.status !== "running") return;
  setTimeout(() => {
    if (current?.status === "running") $("video").src = feedSrc();
  }, 1000);
});

$("toggle").addEventListener("click", () => {
  const active = current && (current.status === "running" || current.status === "starting");
  post(active ? "/api/sitrep/stop" : "/api/sitrep/start");
});
$("ask-bericht").addEventListener("click", askBericht);
$("ask-empfehlung").addEventListener("click", askEmpfehlung);

// R asks for a report, E for a recommendation; not while typing, and not with
// a modifier, so the browser's own shortcuts keep working.
document.addEventListener("keydown", (event) => {
  if (event.repeat || event.ctrlKey || event.metaKey || event.altKey) return;
  if (event.target.closest?.("input, textarea, select, [contenteditable]")) return;
  const key = event.key.toLowerCase();
  if (ANSICHTEN[document.body.dataset.ansicht]?.taste?.(key)) {
    event.preventDefault();
    return;
  }
  if (key === "r") askBericht();
  else if (key === "e") askEmpfehlung();
  else return;
  event.preventDefault();
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
