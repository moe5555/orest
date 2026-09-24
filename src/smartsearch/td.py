"""Announcing search results to TouchDesigner over OSC.

The control half of the Orest -> TouchDesigner interface in
knowledge/components/03_render.md: pixels travel as clip files, and OSC carries
where each clip is and what it is. One search is framed by a begin and an end
message, with one message per clip between them:

    /orest/results/begin  <query_id> <count>
    /orest/results/hit    <query_id> <rank> <clip_path> <ts> <te> <score> <source_file> <preroll>
    /orest/results/end    <query_id>

A hit is announced only once its clip is completely written, so TouchDesigner
can open every path it receives. `preroll` is how many seconds into the clip
file the hit begins: TouchDesigner does not honour the edit list that hides
the footage ahead of the hit in a fast clip, and trims it off instead. The query id tells a new search's results
apart from those of the search before it.

How many results are used, and how, is decided in TouchDesigner or by the QLab
cue driving it; Orest sends everything the search returned.
"""

import uuid
from pathlib import Path

from osc import Message, Sender  # noqa: F401  (Sender is re-exported)

from .client import Hit
from .clips import Clip

BEGIN = "/orest/results/begin"
HIT = "/orest/results/hit"
END = "/orest/results/end"


def new_query_id() -> str:
    return uuid.uuid4().hex[:8]


def begin_message(query_id: str, count: int) -> Message:
    return BEGIN, [query_id, count]


def hit_message(query_id: str, rank: int, clip: Clip, hit: Hit) -> Message:
    # Forward slashes: TouchDesigner accepts them on Windows, and a path with
    # backslashes breaks when it is used inside a Python expression there.
    return HIT, [query_id, rank, Path(clip.path).resolve().as_posix(),
                 hit.ts, hit.te, hit.score, hit.filename, clip.preroll]


def end_message(query_id: str) -> Message:
    return END, [query_id]
