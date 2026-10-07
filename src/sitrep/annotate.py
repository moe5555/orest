"""Names drawn onto the frames the model receives.

The report may only use names the presence tracker assigned (report.py). Given
those names as a bare list, the model would still have to guess which person
in the picture carries which one. Drawing each name above the face it belongs
to lets the model read the assignment instead.

Only the model's copy of a frame is marked. The camera feed to TouchDesigner
stays clean, and nothing is written to disk.

The operator's picture is marked the same way. Prototype 2 of the live
display (knowledge/components/03_render.md) also sets each person's live
ratings beside their box (draw_ratings).

Text is set with Pillow rather than OpenCV, whose built-in fonts cover ASCII
only: a cast name with an umlaut has to appear on the frame exactly as it
appears in the name list, or the model cannot match the two.
"""

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

# Ratings beside a box: text a little smaller than the name, pips in the
# operator page's colours (style.css: --accent, --amber, --red; empty #232a33).
RATING_SHARE = 0.8
PIPS = 5
PIP_OFF = (35, 42, 51)
LEVEL = {"calm": (108, 196, 255), "amber": (243, 169, 59), "red": (255, 90, 95)}


@lru_cache(maxsize=8)
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
    font = _font(max(MIN_TEXT, round(size * RATING_SHARE)))
    ascent = font.getbbox("Hg")
    row_height = ascent[3] - ascent[1]
    pip = max(4, row_height // 2)
    gap = max(2, pip // 3)
    label_width = max((draw.textlength(label, font=font) for _, _, rows in rated
                       for label, _, _ in rows), default=0)
    number_width = draw.textlength("5", font=font)
    width = int(3 * padding + label_width + PIPS * (pip + gap) + gap + number_width)

    for box, name, rows in rated:
        x1, y1, x2, _ = _name(draw, image, box, name)
        if not rows:
            continue
        height = 2 * padding + len(rows) * row_height + (len(rows) - 1) * gap
        x = x2 + line if x2 + line + width <= image.width else x1 - line - width
        x = min(max(0, x), max(0, image.width - width))
        y = min(max(0, y1), max(0, image.height - height))
        draw.rectangle((x, y, x + width, y + height), fill=TAG)

        for index, (label, value, level) in enumerate(rows):
            top = y + padding + index * (row_height + gap)
            draw.text((x + padding, top - ascent[1]), label, font=font, fill=TEXT)
            pips_left = x + 2 * padding + label_width
            pip_top = top + (row_height - pip) // 2
            for slot in range(PIPS):
                left = pips_left + slot * (pip + gap)
                colour = LEVEL.get(level, LEVEL["calm"]) if slot < value else PIP_OFF
                draw.rectangle((left, pip_top, left + pip, pip_top + pip), fill=colour)
            draw.text((pips_left + PIPS * (pip + gap) + gap, top - ascent[1]), str(value),
                      font=font, fill=LEVEL["red"] if level == "red" else TEXT)

    return cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2BGR)
