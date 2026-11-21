// Prototype 4 of the live SITREP display (knowledge/components/03_render.md,
// "Live SITREP"): the picture in the centre, Alex's and Lena's live values to
// the left and to the right of it, as large as the room there allows, each
// tied to its person's box by a white line, and beneath it the scene's
// Relevanz, Eskalation and Gefahr. Nothing else of the run is shown.
//
// The server draws the bands, the cards and the lines into the feed (feed
// ?ratings=1), where the boxes are; drawn on the page they would trail the
// video. It frames the picture between the bands, so the cards stand outside
// it. In scenes that rate bodies, each body's values stand on a card above
// its head. The scene's values are the newest of the Chronik, the
// Lagebericht and the Empfehlung (snapshot.scene_rating, live.latest_scene),
// each named with its time and source.
//
// Einschreiten and the report on R replace the whole page (sitrep.js,
// fullPage).
"use strict";

(() => {
  const SOURCE_TEXT = { chronik: "Chronik", bericht: "Lagebericht", empfehlung: "Empfehlung" };

  function renderScene(rating, status) {
    const meters = $("p4-scene-meters");
    if (!rating) {
      meters.replaceChildren();
      $("p4-scene-source").textContent = status === "running"
        ? "Noch keine Einschätzung der Szene. Die Chronik bewertet sie nach dem ersten Abschnitt."
        : "";
      return;
    }
    const threshold = rating.threshold;
    meters.replaceChildren(
      meter("Relevanz", rating.relevanz, 10, "calm"),
      meter("Eskalation", rating.eskalation, 10, sceneLevel(rating.eskalation, threshold), threshold),
      meter("Gefahr", rating.gefahr, 10, sceneLevel(rating.gefahr, threshold), threshold),
    );
    $("p4-scene-source").textContent = `Stand ${clock(rating.time)} \\ ${SOURCE_TEXT[rating.source]}`;
  }

  function render(snapshot) {
    if (changed("p4-scene", [snapshot.status, snapshot.scene_rating])) {
      renderScene(snapshot.scene_rating, snapshot.status);
    }
  }

  ANSICHTEN.p4 = {
    render,
    feed: "&ratings=1",
    taste: (key) => fullPage.key(key),
    verlassen: () => fullPage.leave(),
  };
  if (current) render(current);
})();
