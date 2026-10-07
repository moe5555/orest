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
(draw_ratings_strip).

Text is set with Pillow rather than OpenCV, whose built-in fonts cover ASCII
only: a cast name with an umlaut has to appear on the frame exactly as it
appears in the name list, or the model cannot match the two.
"""

import threading
from functools import lru_cache

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

# Bold sans for legibility at small sizes. Found in the Windows font folder;
# elsewhere Pillow's bundled font stands in.
FONT = "arialbd.ttf"

# Text height as a share of the frame height, with a floor for small frames.
# About 38 px on 1080p: readable to the model without covering the faces.
TEXT_SHARE = 1 / 28
MIN_TEXT = 14

# Yellow box on the face, white text on a black tag: legible under stage light
# of any colour.
BOX = (255, 214, 0)
TAG = (0, 0, 0)
TEXT = (255, 255, 255)

# Ratings beside a box: text the size of the name; pips in the operator page's
# colours (style.css: --accent, --amber, --red; empty #232a33).
RATING_SHARE = 1.0
PIPS = 5
PIP_OFF = (35, 42, 51)
LEVEL = {"calm": (108, 196, 255), "amber": (243, 169, 59), "red": (255, 90, 95)}

# Prototype 3: one slot per person the recogniser follows
# (recognizer.MAX_PEOPLE). A slot stays with its person for HOLD seconds after
# they leave the view, so a body track lost for a moment returns to the same
# place.
SLOTS = 4
HOLD = 5.0
LINK = (255, 255, 255)


@lru_cache(maxsize=16)
def _font(size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(FONT, size)
    except OSError:
        return ImageFont.load_default(size)


def _layout(image: Image.Image) -> tuple[int, ImageFont.FreeTypeFont, int, int]:
    """Text size, font, padding and line width for a frame of this height."""
    size = max(MIN_TEXT, round(image.height * TEXT_SHARE))
    return size, _font(size), max(2, size // 4), max(2, size // 10)


def _name(draw: ImageDraw.ImageDraw, image: Image.Image, box, name: str) -> tuple[int, ...]:
    """Box a person and set their name above the box, or below it at the top of the frame.

    Returns the box in whole pixels.
    """
    _, font, padding, line = _layout(image)
    x1, y1, x2, y2 = (int(round(float(value))) for value in box)
    draw.rectangle((x1, y1, x2, y2), outline=BOX, width=line)

    left, top, right, bottom = draw.textbbox((0, 0), name, font=font)
    width = right - left + 2 * padding
    height = bottom - top + 2 * padding
    x = min(max(0, x1), max(0, image.width - width))
    y = y1 - height if y1 - height >= 0 else y2
    draw.rectangle((x, y, x + width, y + height), fill=TAG)
    draw.text((x + padding - left, y + padding - top), name, font=font, fill=TEXT)
    return x1, y1, x2, y2


def draw_names(frame: np.ndarray, named: list[tuple[np.ndarray, str]]) -> np.ndarray:
    """A copy of a BGR frame with each face boxed and its name set above it.

    A name that would leave the top of the frame is set below the face instead.
    """
    if not named:
        return frame

    image = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(image)
    for box, name in named:
        _name(draw, image, box, name)
    return cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2BGR)


class _RatingRows:
    """Rating rows set in one font: the label, five pips and the number.

    Measured on the labels given, so panels drawn with one instance line up.
    """

    def __init__(self, draw: ImageDraw.ImageDraw, font: ImageFont.FreeTypeFont,
                 labels, padding: int):
        self.font, self.padding = font, padding
        self.ascent = font.getbbox("Hg")
        self.row = self.ascent[3] - self.ascent[1]
        self.pip = max(4, self.row // 2)
        self.gap = max(2, self.pip // 3)
        self.label_width = max((draw.textlength(label, font=font) for label in labels), default=0)
        self.width = int(3 * padding + self.label_width + PIPS * (self.pip + self.gap)
                         + self.gap + draw.textlength("5", font=font))

    def height(self, count: int) -> int:
        """Height of `count` rows, without the panel's padding."""
        return count * self.row + max(0, count - 1) * self.gap

    def text(self, draw: ImageDraw.ImageDraw, x: int, top: int, text: str, fill) -> None:
        """Text whose row starts at `top`."""
        draw.text((x, top - self.ascent[1]), text, font=self.font, fill=fill)

    def draw(self, draw: ImageDraw.ImageDraw, x: int, top: int,
             rows: list[tuple[str, int, str]]) -> None:
        """The rows of a panel whose left edge is `x`, the first row starting at `top`."""
        for index, (label, value, level) in enumerate(rows):
            row_top = top + index * (self.row + self.gap)
            self.text(draw, x + self.padding, row_top, label, TEXT)
            pips_left = x + 2 * self.padding + self.label_width
            pip_top = row_top + (self.row - self.pip) // 2
            for slot in range(PIPS):
                left = pips_left + slot * (self.pip + self.gap)
                colour = LEVEL.get(level, LEVEL["calm"]) if slot < value else PIP_OFF
                draw.rectangle((left, pip_top, left + self.pip, pip_top + self.pip), fill=colour)
            self.text(draw, pips_left + PIPS * (self.pip + self.gap) + self.gap, row_top,
                      str(value), LEVEL["red"] if level == "red" else TEXT)


def draw_ratings(frame: np.ndarray,
                 rated: list[tuple[np.ndarray, str, list[tuple[str, int, str]]]]) -> np.ndarray:
    """A copy of a BGR frame with each person boxed and named, and their ratings beside the box.

    Each person comes with rows of (label, value 0-5, level), the level being
    "calm", "amber" or "red" as the page colours it. A row shows the label,
    five pips and the number. The panel sits against the box's right edge, at
    its top, or against its left edge where the frame ends.
    """
    if not rated:
        return frame

    image = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(image)
    size, _, padding, line = _layout(image)
    layout = _RatingRows(draw, _font(max(MIN_TEXT, round(size * RATING_SHARE))),
                         [label for _, _, rows in rated for label, _, _ in rows], padding)
    width = layout.width

    for box, name, rows in rated:
        x1, y1, x2, _ = _name(draw, image, box, name)
        if not rows:
            continue
        height = 2 * padding + layout.height(len(rows))
        x = x2 + line if x2 + line + width <= image.width else x1 - line - width
        x = min(max(0, x), max(0, image.width - width))
        y = min(max(0, y1), max(0, image.height - height))
        draw.rectangle((x, y, x + width, y + height), fill=TAG)
        layout.draw(draw, x, y + padding, rows)

    return cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2BGR)


class Slots:
    """Which person's ratings stand in which slot of the strip (draw_ratings_strip).

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
                       rated: list[tuple[np.ndarray, str, list[tuple[str, int, str]]]],
                       slots: dict[str, int], labels: list[str],
                       count: int = SLOTS) -> np.ndarray:
    """A copy of a BGR frame with a strip beneath it holding the people's ratings.

    In the picture each person is boxed and named. The strip is divided into
    `count` slots of equal width that do not move with the people. A person
    with rows and a slot in `slots` has their name and rows set in that slot,
    and a white line runs from above the name to the foot of their box.
    The strip's height and font follow from `labels`, all the rating labels
    there can be, so the picture keeps its size from frame to frame. The font
    is the name's size, smaller where a slot is too narrow for it.
    """
    base = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
    size, _, padding, line = _layout(base)
    slot_width = base.width // count
    probe = ImageDraw.Draw(base)
    text = max(MIN_TEXT, round(size * RATING_SHARE))
    layout = _RatingRows(probe, _font(text), labels, padding)
    while layout.width > slot_width - 2 * padding and text > MIN_TEXT:
        text = max(MIN_TEXT, min(text - 1, int(text * (slot_width - 2 * padding) / layout.width)))
        layout = _RatingRows(probe, _font(text), labels, padding)

    strip = 3 * padding + layout.row + layout.height(len(labels)) + padding
    image = Image.new("RGB", (base.width, base.height + strip), TAG)
    image.paste(base, (0, 0))
    draw = ImageDraw.Draw(image)

    for box, name, rows in rated:
        x1, _, x2, y2 = _name(draw, base, box, name)
        slot = slots.get(name)
        if not rows or slot is None:
            continue
        x = slot * slot_width + (slot_width - layout.width) // 2
        y = base.height + padding
        above_name = x + padding + int(draw.textlength(name, font=layout.font)) // 2
        foot = (x1 + x2) // 2, min(max(0, y2), base.height - 1)
        draw.line(((above_name, base.height), foot), fill=LINK, width=line)
        layout.text(draw, x + padding, y, name, TEXT)
        layout.draw(draw, x, y + layout.row + 2 * padding, rows)

    return cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2BGR)
