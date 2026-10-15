// Prototype 4 of the live SITREP display (knowledge/components/03_render.md,
// "Live SITREP"): Prototype 3, except that the people's values stand to the
// left and to the right of the picture rather than beneath it, as large as
// the room there allows, and only Alex's and Lena's are shown. Each is tied
// to its person's box by a white line. The picture keeps Prototype 3's size
// (style.css).
//
// The server draws the bands, the cards and the lines into the picture (feed
// ?ratings=1&sides=1), where the boxes are. The scene beneath the picture is
// Prototype 2's section, kept current by prototyp2.js; Einschreiten and the
// report on R replace the whole page, as in Prototypes 1 to 3 (sitrep.js,
// fullPage).
"use strict";

ANSICHTEN.p4 = {
  feed: "&ratings=1&sides=1",
  taste: (key) => fullPage.key(key),
  verlassen: () => fullPage.leave(),
};
