// Prototype 1 of the live SITREP display (knowledge/components/03_render.md,
// "Live SITREP"), laid out for a landscape projection: the picture on the
// left; on the right the people in view, one above the other in the order
// they stand from left to right, with their live values, and beneath them the
// alarm while it is raised. Nothing else of the run is shown.
//
// Einschreiten and the report on R replace the whole page, as in Prototype 2
// (sitrep.js, fullPage).
//
// Draws from sitrep.js: the snapshot, its helpers and the report's markup.
"use strict";

(() => {
  // A person in view with no evidence in the last seconds has no entry among
  // the live values, and reads 0.
  function personCard(name, gemessen) {
    const card = el("article", "p1-person");
    card.append(el("h2", null, name));
    const ratings = el("div", "ratings");
    for (const rating of LIVE_SHOWN) ratings.append(ratingRow(rating, gemessen?.[rating] ?? 0));
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
    renderAlarm(snapshot);
    if (changed("p1-personen", [snapshot.status, snapshot.im_bild, snapshot.werte?.personen])) {
      renderPersonen(snapshot);
    }
  }

  ANSICHTEN.p1 = {
    render,
    taste: (key) => fullPage.key(key),
    verlassen: () => fullPage.leave(),
  };
  if (current) render(current);
})();
