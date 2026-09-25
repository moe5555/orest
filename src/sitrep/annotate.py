"""Names drawn onto the frames the model receives.

The report may only use names the presence tracker assigned (report.py). Given
those names as a bare list, the model would still have to guess which person
in the picture carries which one. Drawing each name above the face it belongs
to lets the model read the assignment instead.

Only the model's copy of a frame is marked. The camera feed to TouchDesigner
stays clean, and nothing is written to disk.

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


@lru_cache(maxsize=8)
def _font(size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(FONT, size)
    except OSError:
        return ImageFont.load_default(size)


def draw_names(frame: np.ndarray, named: list[tuple[np.ndarray, str]]) -> np.ndarray:
    """A copy of a BGR frame with each face boxed and its name set above it.

    A name that would leave the top of the frame is set below the face instead.
    """
    if not named:
        return frame

    image = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(image)
    size = max(MIN_TEXT, round(image.height * TEXT_SHARE))
    font = _font(size)
    padding = max(2, size // 4)
    line = max(2, size // 10)

    for box, name in named:
        x1, y1, x2, y2 = (int(round(float(value))) for value in box)
        draw.rectangle((x1, y1, x2, y2), outline=BOX, width=line)

        left, top, right, bottom = draw.textbbox((0, 0), name, font=font)
        width = right - left + 2 * padding
        height = bottom - top + 2 * padding
        x = min(max(0, x1), max(0, image.width - width))
        y = y1 - height if y1 - height >= 0 else y2
        draw.rectangle((x, y, x + width, y + height), fill=TAG)
        draw.text((x + padding - left, y + padding - top), name, font=font, fill=TEXT)

    return cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2BGR)
