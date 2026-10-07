// Prototype 2 of the live SITREP display (knowledge/components/03_render.md,
// "Live SITREP"): the picture in the centre, each person's live values set
// beside their box in the picture, and beneath it the scene's Relevanz,
// Eskalation and Gefahr. Nothing else of the run is shown.
//
// The server draws the people's values into the picture (feed ?ratings=1),
// where the boxes are; drawn on the page they would trail the video. The
// scene's values are the newest of the Chronik, the Lagebericht and the
// Empfehlung (live.latest_scene), each named with its time and source.
//
// Einschreiten and the report on R replace the whole page, as in Prototype 1
// (sitrep.js, fullPage).
"use strict";

(() => {
  const SOURCE_TEXT = { chronik: "Chronik", bericht: "Lagebericht", empfehlung: "Empfehlung" };

  function renderScene(scene, status) {
    const meters = $("p2-scene-meters");
    if (!scene) {
      meters.replaceChildren();
      $("p2-scene-source").textContent = status === "running"
        ? "Noch keine Einschätzung der Szene. Die Chronik bewertet sie nach dem ersten Abschnitt."
        : "";
      return;
    }
    const threshold = scene.threshold;
    meters.replaceChildren(
      meter("Relevanz", scene.relevanz, 10, "calm"),
      meter("Eskalation", scene.eskalation, 10, sceneLevel(scene.eskalation, threshold), threshold),
      meter("Gefahr", scene.gefahr, 10, sceneLevel(scene.gefahr, threshold), threshold),
    );
    $("p2-scene-source").textContent = `Stand ${clock(scene.time)} · ${SOURCE_TEXT[scene.source]}`;
  }

  function render(snapshot) {
    if (changed("p2-scene", [snapshot.status, snapshot.scene])) {
      renderScene(snapshot.scene, snapshot.status);
    }
  }

  ANSICHTEN.p2 = {
    render,
    feed: "&ratings=1",
    taste: (key) => fullPage.key(key),
    verlassen: () => fullPage.leave(),
  };
  if (current) render(current);
})();
