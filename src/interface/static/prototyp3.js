// Prototype 3 of the live SITREP display (knowledge/components/03_render.md,
// "Live SITREP"): Prototype 2, except that the people's values stand still.
// They are set in fixed slots on a strip beneath the picture, each tied to
// its person's box by a white line, so they neither cover the scene nor
// follow the people around it.
//
// The server draws the strip and the lines into the picture (feed
// ?ratings=1&strip=1), where the boxes are. The scene beneath the picture is
// Prototype 2's section, kept current by prototyp2.js; Einschreiten and the
// report on R replace the whole page, as in Prototypes 1 and 2 (sitrep.js,
// fullPage).
"use strict";

ANSICHTEN.p3 = {
  feed: "&ratings=1&strip=1",
  taste: (key) => fullPage.key(key),
  verlassen: () => fullPage.leave(),
};
