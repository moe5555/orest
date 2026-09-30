// Prototype 1 of the live SITREP display (knowledge/components/03_render.md,
// "Live SITREP"), laid out for a landscape projection: the picture on the
// left; on the right the two people in view, one above the other in the order
// they stand from left to right, with their live values, and beneath them the
// alarm while it is raised. Nothing else of the run is shown.
//
// Two states replace the whole page. A recommendation to intervene shows
// alone, with its reason and measure, until the next recommendation; R shows the report alone, and R again
// returns. The report takes precedence, since it was asked for.
//
// Draws from sitrep.js: the snapshot, its helpers and the report's markup.
"use strict";

(() => {
  // The report is on screen, from one R to the next.
  let bericht = false;

  function modus(snapshot) {
    if (bericht) return "bericht";
    const einschreiten = snapshot?.status === "running" && Boolean(snapshot.empfehlung?.urteil?.einschreiten);
    return einschreiten ? "einschreiten" : "normal";
  }

  // A person in view with no evidence in the last seconds has no entry among
  // the live values, and reads 0.
  function personCard(name, gemessen) {
    const card = el("article", "p1-person");
    card.append(el("h2", null, name));
    const ratings = el("div", "ratings");
    for (const rating of LIVE_RATINGS) ratings.append(ratingRow(rating, gemessen?.[rating] ?? 0));
    card.append(ratings);
    return card;
  }

  function renderPersonen(snapshot) {
    const list = $("p1-personen");
    const werte = new Map((snapshot.werte?.personen ?? []).map((person) => [person.name, person]));
    const namen = snapshot.im_bild ?? [];
    list.replaceChildren(...namen.map((name) => personCard(name, werte.get(name))));
    if (!namen.length) {
      list.append(el("div", "waiting", snapshot.status !== "running" ? ""
        : snapshot.quelle?.aktionen === false ? "Aktionserkennung aus: niemand wird verfolgt."
        : "Niemand im Bild."));
    }
  }

  // Why the model recommends intervening (its sentence on what is happening)
  // and what it recommends doing. Set as text: both are model output.
  function renderEinschreiten(urteil) {
    $("p1-warum").textContent = urteil?.lage ?? "";
    $("p1-massnahme").textContent = urteil?.empfehlung ?? "";
    $("p1-warum-zeile").hidden = !urteil?.lage;
    $("p1-massnahme-zeile").hidden = !urteil?.empfehlung;
  }

  // The live alarm beneath the people, while it is raised; otherwise nothing.
  function renderAlarm(snapshot) {
    const alarm = snapshot.werte?.alarm;
    const aktiv = snapshot.status === "running" && Boolean(alarm?.aktiv);
    $("p1-alarm").hidden = !aktiv;
    $("p1-alarm-kopf").textContent = aktiv
      ? `Alarm · ${alarm.wer ?? "Sprecher unklar"} · Risiko ${alarm.wert}` : "";
    $("p1-alarm-anlass").textContent = aktiv ? alarm.anlass : "";
  }

  function render(snapshot) {
    document.body.dataset.p1 = modus(snapshot);
    renderEinschreiten(snapshot.empfehlung?.urteil);
    renderAlarm(snapshot);
    if (changed("p1-personen", [snapshot.status, snapshot.im_bild, snapshot.werte?.personen])) {
      renderPersonen(snapshot);
    }
  }

  // R shows the report and asks for a new one while the run is live; with no
  // run and no earlier report there is nothing to show.
  function taste(key) {
    if (key !== "r") return false;
    if (bericht) {
      bericht = false;
    } else if (current?.status === "running" || current?.report) {
      bericht = true;
      askBericht();
    }
    if (current) render(current);
    return true;
  }

  function verlassen() {
    bericht = false;
    document.body.dataset.p1 = "normal";
  }

  ANSICHTEN.p1 = { render, taste, verlassen };
  if (current) render(current);
})();
