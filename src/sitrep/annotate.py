"""Names drawn onto the frames the model receives.

The report may only use names the presence tracker assigned (report.py). Given
those names as a bare list, the model would still have to guess which person
in the picture carries which one. Drawing each name above the face it belongs
to lets the model read the assignment instead.

Only the model's copy of a frame is marked. The camera feed to TouchDesigner
stays clean, and nothing is written to disk.

The operator's picture is marked the same way. Prototype 2 of the live
display (knowledge/components/03_render.md) also sets each person's live
ratings beside their box (draw_ratings); Prototype 3 sets them in fixed slots
on a strip beneath the picture, each tied to its box by a line
(draw_ratings_strip); Prototype 4 sets two people's, larger, in a band to each
side of the picture, tied to their boxes in the same way (draw_ratings_sides).

Text is set with Pillow rather than OpenCV, whose built-in fonts cover ASCII
only: a cast name with an umlaut has to appear on the frame exactly as it
appears in the name list, or the model cannot match the two.

The model's frames and the operator's picture are set in two styles. The
model's keep the plain yellow box and black tag it reads the names from. The
operator's follow Seestone's corporate identity
(knowledge/background/261009_Keynote_HITL.pdf, "CI \\ Farben", "CI \\
Typografie", "CI \\ Raster und Regeln"), like the operator pages
(interface/static/style.css).
"""

import math
import threading
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

# The CI's typefaces, shipped with the package because the theatre machine may
# be offline. The operator pages load the same files (interface/app.py, /fonts).
FONTS = Path(__file__).parent / "fonts"

# The CI's palette. VOID is the ground, BONE text and lines, STEEL secondary
# text, SIGNAL the accent and ALARM warnings. PANEL and RULE are the fill and
# outline of the deck's cards.
VOID = (3, 4, 10)
PANEL = (11, 13, 20)
RULE = (42, 46, 58)
BONE = (242, 242, 244)
STEEL = (140, 144, 156)
SIGNAL = (91, 155, 255)
ALARM = (229, 72, 58)


@dataclass(frozen=True)
class Style:
    """How boxes, names and ratings are set on a frame."""

    font: str                       # names and labels
    number_font: str                # rating values
    box: tuple[int, int, int]
    tag: tuple[int, int, int]       # behind the text, and the ground of the strip
    text: tuple[int, int, int]
    label: tuple[int, int, int]     # rating labels
    corners: bool                   # a box drawn as its four corners only
    capitals: bool                  # names and labels set in capitals
    tracking: float                 # space after each letter, as a share of the text size


# The model's frames: a yellow box on the face and white text on a black tag,
# legible under stage light of any colour. Arial Bold is found in the Windows
# font folder; elsewhere Pillow's bundled font stands in.
MODEL = Style(font="arialbd.ttf", number_font="arialbd.ttf",
              box=(255, 214, 0), tag=(0, 0, 0), text=(255, 255, 255), label=(255, 255, 255),
              corners=False, capitals=False, tracking=0.0)

# The operator's picture: each person framed by corner brackets (the CI's HUD
# motif), names and labels in IBM Plex Mono capitals with open tracking,
# values in Michroma.
DISPLAY = Style(font=str(FONTS / "IBMPlexMono-SemiBold.ttf"),
                number_font=str(FONTS / "Michroma-Regular.ttf"),
                box=BONE, tag=VOID, text=BONE, label=STEEL,
                corners=True, capitals=True, tracking=0.12)

# Text height as a share of the frame height, with a floor for small frames.
# About 38 px on 1080p: readable to the model without covering the faces.
TEXT_SHARE = 1 / 28
MIN_TEXT = 14

# Ratings beside a box: text the size of the name; pips in the operator page's
# level colours (style.css: --level-calm, --level-amber, --level-red), Steel
# when calm, Signal when raised, Alarm when red; empty in the card outline.
RATING_SHARE = 1.0
PIPS = 5
PIP_OFF = RULE
LEVEL = {"calm": STEEL, "amber": SIGNAL, "red": ALARM}

# Prototype 3: one slot per person the recogniser follows
# (recognizer.MAX_PEOPLE). A slot stays with its person for HOLD seconds after
# they leave the view, so a body track lost for a moment returns to the same
# place.
SLOTS = 4
HOLD = 5.0
LINK = BONE

# Prototype 4: a slot in a band to each side of the picture, each band
# SIDE_BAND_SHARE of the picture's width. The page shows the picture at
# Prototype 3's size (style.css), which on a 16:9 projection leaves this much
# room either side. The name, the pips and the numbers are set as large as the
# band allows, up to SIDE_SCALE times Prototype 3's values; the labels as
# large as the longest fits, up to the same.
SIDES = 2
SIDE_BAND_SHARE = 0.155
SIDE_SCALE = 2


@lru_cache(maxsize=32)
def _font(face: str, size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(face, size)
    except OSError:
        return ImageFont.load_default(size)


def _layout(image: Image.Image, style: Style) -> tuple[int, ImageFont.FreeTypeFont, int, int]:
    """Text size, font, padding and line width for a frame of this height."""
    size = max(MIN_TEXT, round(image.height * TEXT_SHARE))
    return size, _font(style.font, size), max(2, size // 4), max(2, size // 10)


def _cased(text: str, style: Style) -> str:
    return text.upper() if style.capitals else text


def _length(text: str, font: ImageFont.FreeTypeFont, tracking: float) -> float:
    """Advance of `text`, with `tracking` pixels between its letters."""
    return font.getlength(text) + tracking * max(0, len(text) - 1)


def _set(draw: ImageDraw.ImageDraw, xy: tuple[float, float], text: str,
         font: ImageFont.FreeTypeFont, fill, tracking: float = 0.0) -> None:
    """Text drawn at `xy`, with `tracking` pixels between its letters."""
    if not tracking:
        draw.text(xy, text, font=font, fill=fill)
        return
    x, y = xy
    for letter in text:
        draw.text((x, y), letter, font=font, fill=fill)
        x += font.getlength(letter) + tracking


def _corners(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], colour,
             width: int) -> None:
    """The four corners of a box, each a bracket a quarter of its shorter side long."""
    x1, y1, x2, y2 = box
    arm = max(3 * width, min(x2 - x1, y2 - y1) // 4)
    for x, y, dx, dy in ((x1, y1, 1, 1), (x2, y1, -1, 1), (x1, y2, 1, -1), (x2, y2, -1, -1)):
        inner_x, inner_y = x + dx * (width - 1), y + dy * (width - 1)
        draw.rectangle((min(x, x + dx * arm), min(y, inner_y), max(x, x + dx * arm),
                        max(y, inner_y)), fill=colour)
        draw.rectangle((min(x, inner_x), min(y, y + dy * arm), max(x, inner_x),
                        max(y, y + dy * arm)), fill=colour)


def _name(draw: ImageDraw.ImageDraw, image: Image.Image, box, name: str,
          style: Style) -> tuple[int, ...]:
    """Box a person and set their name above the box, or below it at the top of the frame.

    Returns the box in whole pixels.
    """
    size, font, padding, line = _layout(image, style)
    tracking = style.tracking * size
    text = _cased(name, style)
    x1, y1, x2, y2 = (int(round(float(value))) for value in box)
    if style.corners:
        _corners(draw, (x1, y1, x2, y2), style.box, line)
    else:
        draw.rectangle((x1, y1, x2, y2), outline=style.box, width=line)

    left, top, _, bottom = draw.textbbox((0, 0), text, font=font)
    width = round(_length(text, font, tracking)) + 2 * padding
    height = bottom - top + 2 * padding
    x = min(max(0, x1), max(0, image.width - width))
    y = y1 - height if y1 - height >= 0 else y2
    draw.rectangle((x, y, x + width, y + height), fill=style.tag)
    _set(draw, (x + padding - left, y + padding - top), text, font, style.text, tracking)
    return x1, y1, x2, y2


def draw_region(frame: np.ndarray, polygon: np.ndarray) -> np.ndarray:
    """A copy of a BGR frame with a region, a polygon in pixels, outlined in
    the accent colour, apart from the people's boxes."""
    marked = frame.copy()
    thickness = max(1, frame.shape[0] // 540)
    cv2.polylines(marked, [np.round(polygon).astype(np.int32)], True, SIGNAL[::-1], thickness,
                  cv2.LINE_AA)
    return marked


def draw_names(frame: np.ndarray, named: list[tuple[np.ndarray, str]],
               style: Style = MODEL) -> np.ndarray:
    """A copy of a BGR frame with each face boxed and its name set above it.

    A name that would leave the top of the frame is set below the face instead.
    The model's style unless `style` is given.
    """
    if not named:
        return frame

    image = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(image)
    for box, name in named:
        _name(draw, image, box, name, style)
    return cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2BGR)


class _RatingRows:
    """Rating rows: the label, five pips and the number.

    Labels are set in the style's font and colour, numbers in its number font.
    Measured on the labels given and on `widest`, the largest magnitude a
    value can take, so panels drawn with one instance line up. The pips fill
    in proportion to the value's magnitude on its scale (_filled). A negative
    value (Berechenbarkeit, Aggression) is set with its sign.
    """

    def __init__(self, draw: ImageDraw.ImageDraw, size: int, labels, padding: int,
                 style: Style, widest: int = PIPS):
        self.style, self.padding, self.size = style, padding, size
        self.font = _font(style.font, size)
        self.number_font = _font(style.number_font, size)
        self.tracking = style.tracking * size
        self.ascent = self.font.getbbox("Hg")
        self.row = self.ascent[3] - self.ascent[1]
        self.pip = max(4, self.row // 2)
        self.gap = max(2, self.pip // 3)
        self.label_width = max((_length(_cased(label, style), self.font, self.tracking)
                                for label in labels), default=0)
        self.meter_width = (PIPS * (self.pip + self.gap) + self.gap
                            + draw.textlength(_number(-widest), font=self.number_font))
        self.width = int(3 * padding + self.label_width + self.meter_width)

    def height(self, count: int) -> int:
        """Height of `count` rows, without the panel's padding."""
        return count * self.row + max(0, count - 1) * self.gap

    def text(self, draw: ImageDraw.ImageDraw, x: int, top: int, text: str, fill) -> None:
        """Text in the style's font and case, whose row starts at `top`.

        Capitals, which have no descenders, are centred on the row.
        """
        if self.style.capitals:
            _, cap_top, _, cap_bottom = self.font.getbbox("H")
            y = top + self.row // 2 - (cap_top + cap_bottom) // 2
        else:
            y = top - self.ascent[1]
        _set(draw, (x, y), _cased(text, self.style), self.font, fill, self.tracking)

    def number(self, draw: ImageDraw.ImageDraw, x: int, top: int, value: int, fill) -> None:
        """A value in the number font, centred on the row that starts at `top`."""
        _, number_top, _, number_bottom = self.number_font.getbbox("0")
        y = top + self.row // 2 - (number_top + number_bottom) // 2
        draw.text((x, y), _number(value), font=self.number_font, fill=fill)

    def draw(self, draw: ImageDraw.ImageDraw, x: int, top: int,
             rows: list[tuple[str, int, str, int]]) -> None:
        """The rows of a panel whose left edge is `x`, the first row starting at `top`."""
        for index, (label, value, level, scale) in enumerate(rows):
            row_top = top + index * (self.row + self.gap)
            self.text(draw, x + self.padding, row_top, label, self.style.label)
            self.meter(draw, x + 2 * self.padding + self.label_width, row_top, value, level, scale)

    def meter(self, draw: ImageDraw.ImageDraw, x: float, top: int, value: int, level: str,
              scale: int) -> None:
        """Five pips from `x` and the number after them, on the row that starts at `top`."""
        pip_top = top + (self.row - self.pip) // 2
        filled = _filled(value, scale)
        for slot in range(PIPS):
            left = int(x + slot * (self.pip + self.gap))
            colour = LEVEL.get(level, LEVEL["calm"]) if slot < filled else PIP_OFF
            draw.rectangle((left, pip_top, left + self.pip, pip_top + self.pip), fill=colour)
        self.number(draw, int(x + PIPS * (self.pip + self.gap) + self.gap), top,
                    value, LEVEL["red"] if level == "red" else self.style.text)


def _fitted(probe: ImageDraw.ImageDraw, size: int, labels, padding: int, style: Style,
            widest: int, room: float, measure) -> _RatingRows:
    """Rating rows at `size`, or smaller where `measure` of them exceeds
    `room`, though not below MIN_TEXT."""
    layout = _RatingRows(probe, size, labels, padding, style, widest)
    while measure(layout) > room and size > MIN_TEXT:
        size = max(MIN_TEXT, min(size - 1, int(size * room / measure(layout))))
        layout = _RatingRows(probe, size, labels, padding, style, widest)
    return layout


def _filled(value: int, scale: int) -> int:
    """Pips filled for a value whose largest magnitude is `scale`: its share of
    the five, rounded up so that any value but 0 shows. On a scale of 5, one
    pip per point (sitrep.js, ratingRow)."""
    return min(PIPS, math.ceil(PIPS * abs(value) / scale))


def _number(value: int) -> str:
    """A rating as set beside its pips, a negative one with a typographic minus."""
    return f"−{-value}" if value < 0 else str(value)


def draw_ratings(frame: np.ndarray,
                 rated: list[tuple[np.ndarray, str, list[tuple[str, int, str, int]]]]
                 ) -> np.ndarray:
    """A copy of a BGR frame with each person boxed and named, and their ratings beside the box.

    Each person comes with rows of (label, value, level, scale), the level being
    "calm", "amber" or "red" as the page colours it and the scale the largest
    magnitude the value can take (scenes.extent). A row shows the label, five
    pips and the number. The panel sits against the box's right edge, at its
    top, or against its left edge where the frame ends.
    """
    if not rated:
        return frame

    image = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(image)
    size, _, padding, line = _layout(image, DISPLAY)
    rows_drawn = [row for _, _, rows in rated for row in rows]
    layout = _RatingRows(draw, max(MIN_TEXT, round(size * RATING_SHARE)),
                         [label for label, _, _, _ in rows_drawn], padding, DISPLAY,
                         widest=max((scale for _, _, _, scale in rows_drawn), default=PIPS))
    width = layout.width

    for box, name, rows in rated:
        x1, y1, x2, _ = _name(draw, image, box, name, DISPLAY)
        if not rows:
            continue
        height = 2 * padding + layout.height(len(rows))
        x = x2 + line if x2 + line + width <= image.width else x1 - line - width
        x = min(max(0, x), max(0, image.width - width))
        y = min(max(0, y1), max(0, image.height - height))
        _card(draw, (x, y, x + width, y + height))
        layout.draw(draw, x, y + padding, rows)

    return cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2BGR)


def _card(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int]) -> None:
    """A card as in the CI's deck: dark fill, a thin outline, and corner
    brackets in the outline's colour just inside it."""
    x1, y1, x2, y2 = box
    draw.rectangle(box, fill=PANEL, outline=RULE, width=1)
    inset = _card_inset(x2 - x1, y2 - y1)
    if x2 - x1 > 4 * inset and y2 - y1 > 4 * inset:
        _corners(draw, (x1 + inset, y1 + inset, x2 - inset, y2 - inset), RULE,
                 max(1, inset // 3))


def _card_inset(width: int, height: int) -> int:
    """How far inside a card of this size its corner brackets stand."""
    return max(3, min(width, height) // 24)


class Slots:
    """Which person's ratings stand in which slot of the strip
    (draw_ratings_strip) or of the bands beside the picture (draw_ratings_sides).

    A person keeps their slot while in view and for `hold` seconds after. A
    person new to the view takes the free slot nearest their place in the
    picture, so their line starts short; with none free, the slot whose
    person has been gone longest. Called from every feed's thread.
    """

    def __init__(self, count: int = SLOTS, hold: float = HOLD):
        self.count, self.hold = count, hold
        self._held: list[tuple[str, float] | None] = [None] * count
        self._lock = threading.Lock()

    def assign(self, people: list[tuple[str, float]], now: float) -> dict[str, int]:
        """Slot by name for the people in view.

        `people` are (name, centre of the box as a share of the frame width),
        `now` a monotonic time in seconds.
        """
        in_view = {name for name, _ in people}
        with self._lock:
            slots = {}
            for index, held in enumerate(self._held):
                if held is not None and held[0] in in_view:
                    slots[held[0]] = index
                    self._held[index] = (held[0], now)
            for name, centre in sorted(people, key=lambda person: person[1]):
                if name in slots:
                    continue
                open_slots = [index for index, held in enumerate(self._held)
                              if held is None or held[0] not in in_view]
                if not open_slots:
                    continue
                expired = [index for index in open_slots if self._held[index] is None
                           or now - self._held[index][1] > self.hold]
                if expired:
                    index = min(expired, key=lambda slot: abs((slot + 0.5) / self.count - centre))
                else:
                    index = min(open_slots, key=lambda slot: self._held[slot][1])
                slots[name] = index
                self._held[index] = (name, now)
            return slots


def draw_ratings_strip(frame: np.ndarray,
                       rated: list[tuple[np.ndarray, str, list[tuple[str, int, str, int]]]],
                       slots: dict[str, int], labels: list[str],
                       count: int = SLOTS, rows: int | None = None,
                       widest: int = PIPS) -> np.ndarray:
    """A copy of a BGR frame with a strip beneath it holding the people's ratings.

    In the picture each person is boxed and named. The strip is divided into
    `count` slots of equal width that do not move with the people. A person
    with rows (as draw_ratings takes them) and a slot in `slots` has their
    name and rows set on a card in that slot, and a line in the text colour
    runs from above the name to the foot of their box.
    The strip's font follows from `labels`, all the rating labels there can
    be, and `widest`, the largest magnitude any of them can take; its height
    from `rows`, the most rows anyone can have (all the labels unless given).
    So the picture keeps its size from frame to frame.
    The font is the name's size, smaller where a slot is too narrow for it.
    """
    style = DISPLAY
    base = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
    size, _, padding, line = _layout(base, style)
    slot_width = base.width // count
    layout = _fitted(ImageDraw.Draw(base), max(MIN_TEXT, round(size * RATING_SHARE)), labels,
                     padding, style, widest, slot_width - 2 * padding, lambda rows: rows.width)

    strip = (3 * padding + layout.row
             + layout.height(len(labels) if rows is None else rows) + padding)
    image = Image.new("RGB", (base.width, base.height + strip), style.tag)
    image.paste(base, (0, 0))
    draw = ImageDraw.Draw(image)

    margin = max(1, padding // 2)
    for box, name, rows in rated:
        x1, _, x2, y2 = _name(draw, base, box, name, style)
        slot = slots.get(name)
        if not rows or slot is None:
            continue
        card_top = base.height + margin
        _card(draw, (slot * slot_width + margin, card_top,
                     (slot + 1) * slot_width - margin - 1, image.height - margin - 1))
        x = slot * slot_width + (slot_width - layout.width) // 2
        y = base.height + padding
        title = _cased(name, style)
        above_name = x + padding + int(_length(title, layout.font, layout.tracking)) // 2
        foot = (x1 + x2) // 2, min(max(0, y2), base.height - 1)
        draw.line(((above_name, card_top), foot), fill=LINK, width=line)
        layout.text(draw, x + padding, y, name, style.text)
        layout.draw(draw, x, y + layout.row + 2 * padding, rows)

    return cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2BGR)


def draw_ratings_sides(frame: np.ndarray,
                       rated: list[tuple[np.ndarray, str, list[tuple[str, int, str, int]]]],
                       slots: dict[str, int], labels: list[str],
                       rows: int | None = None, widest: int = PIPS) -> np.ndarray:
    """A copy of a BGR frame widened by a band to each side holding people's ratings.

    The picture keeps its size, between a band on the left, slot 0 of
    `slots`, and one on the right, slot 1, each SIDE_BAND_SHARE of its width.
    In the picture each person is boxed and named. A person with rows (as
    draw_ratings takes them) and a slot has their name and rows set on a card
    in that band, each label above its pips and number, and a line in the
    text colour runs from beside the name to the near side of their box.
    The text's sizes follow from the band's width, from `labels`, all the
    rating labels there can be, and from `widest`, the largest magnitude any
    of them can take; the cards' height from `rows`, the most rows anyone can
    have (all the labels unless given). So the frame keeps its size from frame
    to frame. A band is widened where the labels would not fit it at the
    smallest legible size. Both cards start at the same height, centred for
    the tallest card there can be.
    """
    style = DISPLAY
    base = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
    size, _, padding, line = _layout(base, style)
    probe = ImageDraw.Draw(base)
    margin = max(1, padding // 2)

    def card_inset(card_width: int) -> int:
        # Clear of the card's brackets, which are at most a third as wide as
        # they stand inside it (_corners).
        return _card_inset(card_width, card_width) * 4 // 3 + padding

    smallest = _RatingRows(probe, MIN_TEXT, labels, padding, style, widest)
    band = round(base.width * SIDE_BAND_SHARE)
    card_width = band - 2 * margin
    while (card_width - 2 * card_inset(card_width)
           < max(smallest.label_width, smallest.meter_width)):
        card_width += 1
    band = card_width + 2 * margin
    inset = card_inset(card_width)
    room = card_width - 2 * inset

    # Prototype 3's size for these values (draw_ratings_strip).
    strip = _fitted(probe, max(MIN_TEXT, round(size * RATING_SHARE)), labels, padding, style,
                    widest, base.width // SLOTS - 2 * padding, lambda layout: layout.width)
    largest = SIDE_SCALE * strip.size
    meters = _fitted(probe, largest, labels, padding, style, widest, room,
                     lambda layout: layout.meter_width)
    captions = _fitted(probe, largest, labels, padding, style, widest, room,
                       lambda layout: layout.label_width)
    value_height = captions.row + captions.gap + meters.row

    def card_height(count: int) -> int:
        return (2 * inset + meters.row + 2 * padding
                + count * value_height + max(0, count - 1) * padding)

    tallest = card_height(len(labels) if rows is None else rows)
    total = max(base.height, tallest + 2 * margin)
    top = (total - base.height) // 2
    card_top = (total - tallest) // 2

    marked = ImageDraw.Draw(base)
    boxes = [_name(marked, base, box, name, style) for box, name, _ in rated]
    image = Image.new("RGB", (base.width + 2 * band, total), style.tag)
    image.paste(base, (band, top))
    draw = ImageDraw.Draw(image)

    for (x1, y1, x2, y2), (_, name, rows) in zip(boxes, rated):
        slot = slots.get(name)
        if not rows or slot not in (0, 1):
            continue
        x = margin if slot == 0 else band + base.width + margin
        _card(draw, (x, card_top, x + card_width - 1, card_top + card_height(len(rows)) - 1))
        name_top = card_top + inset
        beside_name = (x + card_width - 1 if slot == 0 else x), name_top + meters.row // 2
        near_side = (band + (x1 if slot == 0 else x2),
                     top + min(max(0, (y1 + y2) // 2), base.height - 1))
        draw.line((beside_name, near_side), fill=LINK, width=line)
        # The name at the values' size, or at the labels' where it is too long for that.
        title = meters if _length(_cased(name, style), meters.font,
                                  meters.tracking) <= room else captions
        title.text(draw, x + inset, name_top + (meters.row - title.row) // 2, name, style.text)
        value_top = name_top + meters.row + 2 * padding
        for label, value, level, scale in rows:
            captions.text(draw, x + inset, value_top, label, style.label)
            meters.meter(draw, x + inset, value_top + captions.row + captions.gap, value, level,
                         scale)
            value_top += value_height + padding

    return cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2BGR)
