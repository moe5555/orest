"""The text of a scene, with passages annotated with the values they set.

The operator pastes the full text of a scene on the control page and marks
passages in it. Each annotation names, per character, the values to set when
the passage is said. The lines heard live (utterances.py) are compared with
the annotated passages (`Listener`); when one is recognised, its values are set
at that moment (scenes.Current.set_value), in place of what was measured
until then, and the system carries on from them as usual (lage.measure).

A passage is recognised by its opening words (CUE_WORDS): a long speech
sets its values as it begins, not once it has ended. Words are compared
in lower case and without punctuation, in the order said, within the lines
of the last WINDOW_S seconds, so a passage split over two transcribed lines
is recognised too. Whisper mishears a word now and then, so SHARE of the
opening words suffice.

A revised text keeps the annotations of the passages it contains unchanged
(`revise`). Each scene's text, annotations and starting values are kept in
a file of their own (`Store`).
"""

import json
import re
import threading
import unicodedata
import uuid
from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from pathlib import Path

from pydantic import BaseModel, Field, model_validator

from . import report, scenes

# The opening words of a passage that recognise it.
CUE_WORDS = 8

# The share of a passage's opening words that must be heard, in order.
SHARE = 0.75

# Seconds of lines a passage may be heard across.
WINDOW_S = 20.0

# Seconds before the same passage can be recognised again: longer than
# WINDOW_S, so the lines that recognised it once do not do so twice.
COOLDOWN_S = 30.0

# Characters of a passage compared before and after it, to tell repeated
# passages apart when a revised text holds the same words more than once.
CONTEXT = 200

# The cause shown with a value a passage set.
ANLASS = "Szenentext"

# The cause shown with a starting value.
STARTWERT = "Startwert"


def words(text: str) -> list[str]:
    """The words of a text, in lower case and without punctuation."""
    folded = unicodedata.normalize("NFKC", text).casefold()
    return re.findall(r"\w+", folded)


def check_values(values: dict[str, dict[str, int]]) -> dict[str, dict[str, int]]:
    """Per character, values by name, each within its range (scenes.RANGES).
    Raises ValueError for a value not known."""
    for character, own in values.items():
        for value, wert in own.items():
            if value not in scenes.RANGES:
                raise ValueError(f"Unbekannter Wert {value!r} für {character}.")
            low, high = scenes.RANGES[value]
            if not low <= wert <= high:
                raise ValueError(f"{scenes.LABELS[value]} reicht von {low} bis {high}, nicht {wert}.")
    return values


class Annotation(BaseModel):
    """A passage of the text, by its characters' offsets, and the values it
    sets per character when said."""

    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    start: int = Field(ge=0)
    end: int
    text: str
    values: dict[str, dict[str, int]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check(self) -> "Annotation":
        if self.end <= self.start:
            raise ValueError("an annotation spans at least one character")
        check_values(self.values)
        return self

    def cue(self) -> list[str]:
        """The opening words that recognise the passage."""
        return words(self.text)[:CUE_WORDS]

    def summary(self) -> str:
        """The values the passage sets, as the operator reads them."""
        return "; ".join(
            f"{character}: " + ", ".join(f"{scenes.LABELS[value]} {wert}"
                                         for value, wert in own.items())
            for character, own in self.values.items() if own)


class SceneText(BaseModel):
    """One scene's text, its annotations in the order of the text, and each
    character's starting values (absent ones start at 0)."""

    text: str = ""
    annotations: list[Annotation] = Field(default_factory=list)
    initial: dict[str, dict[str, int]] = Field(default_factory=dict)

    def annotate(self, start: int, end: int, values: dict[str, dict[str, int]]) -> Annotation:
        """Annotate the passage from `start` to `end`. Raises ValueError for a
        passage outside the text or overlapping an annotated one."""
        if not 0 <= start < end <= len(self.text):
            raise ValueError("Die Stelle liegt nicht im Text.")
        start, end = trimmed(self.text, start, end)
        if start == end:
            raise ValueError("Die Stelle enthält keinen Text.")
        if any(start < other.end and other.start < end for other in self.annotations):
            raise ValueError("Die Stelle überschneidet eine annotierte Stelle.")
        annotation = Annotation(start=start, end=end, text=self.text[start:end], values=values)
        self.annotations = sorted([*self.annotations, annotation], key=lambda kept: kept.start)
        return annotation

    def find(self, annotation_id: str) -> Annotation:
        """The annotation by id. Raises KeyError."""
        for annotation in self.annotations:
            if annotation.id == annotation_id:
                return annotation
        raise KeyError(annotation_id)


def trimmed(text: str, start: int, end: int) -> tuple[int, int]:
    """The span without the white space at its ends."""
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return start, end


def _context(before: str, after: str, old_before: str, old_after: str) -> int:
    """How many characters around a passage match its surroundings in the old text."""
    shared = 0
    for a, b in zip(reversed(before[-CONTEXT:]), reversed(old_before[-CONTEXT:])):
        if a != b:
            break
        shared += 1
    for a, b in zip(after[:CONTEXT], old_after[:CONTEXT]):
        if a != b:
            break
        shared += 1
    return shared


def revise(old: SceneText, text: str) -> tuple[SceneText, list[Annotation]]:
    """The scene text replaced by `text`, and the annotations it lost.

    An annotation is kept where its passage occurs unchanged in the new text.
    Where it occurs more than once, the occurrence whose surroundings match
    the old ones best is taken, then the one nearest the old place in the
    text. An annotation that would overlap one already placed is lost.
    """
    text = text.replace("\r\n", "\n")
    kept, lost = [], []
    for annotation in old.annotations:
        old_before, old_after = old.text[:annotation.start], old.text[annotation.end:]
        share = annotation.start / max(1, len(old.text))
        found = [match.start() for match in re.finditer(re.escape(annotation.text), text)]
        found = [start for start in found
                 if not any(start < other.end and other.start < start + len(annotation.text)
                            for other in kept)]
        if not found:
            lost.append(annotation)
            continue
        start = max(found, key=lambda at: (
            _context(text[:at], text[at + len(annotation.text):], old_before, old_after),
            -abs(at / max(1, len(text)) - share)))
        kept.append(annotation.model_copy(update={"start": start,
                                                  "end": start + len(annotation.text)}))
    revised = SceneText(text=text, annotations=sorted(kept, key=lambda annotation: annotation.start),
                        initial=old.initial)
    return revised, lost


@dataclass(frozen=True)
class Cue:
    """A passage recognised in what was said: which, when, and the words heard."""

    annotation: Annotation
    at: datetime
    heard: str


class Listener:
    """Recognises the annotated passages of a scene's text in the lines said.

    `heard` takes lines as they arrive, transcribed or rated: each line counts
    once, by its start and text.
    """

    def __init__(self):
        self._lines: deque[tuple[datetime, list[str], str]] = deque()
        self._seen: deque[tuple[datetime, str]] = deque(maxlen=200)
        self._fired: dict[str, datetime] = {}

    def heard(self, lines: Iterable[report.Aeusserung],
              annotations: list[Annotation]) -> list[Cue]:
        """The passages the lines complete, given the lines heard before."""
        new = False
        for line in lines:
            key = (line.beginn, line.text)
            if key in self._seen:
                continue
            self._seen.append(key)
            self._lines.append((line.ende, words(line.text), line.text))
            new = True
        if not new:
            return []
        latest = max(ende for ende, _, _ in self._lines)
        while self._lines and self._lines[0][0] < latest - timedelta(seconds=WINDOW_S):
            self._lines.popleft()
        recent = [word for _, said, _ in sorted(self._lines, key=lambda held: held[0])
                  for word in said]
        heard = " ".join(text for _, _, text in self._lines)
        cues = []
        for annotation in annotations:
            cue = annotation.cue()
            if not cue or not annotation.values:
                continue
            fired = self._fired.get(annotation.id)
            if fired is not None and latest - fired < timedelta(seconds=COOLDOWN_S):
                continue
            matched = sum(block.size for block in
                          SequenceMatcher(None, cue, recent, autojunk=False).get_matching_blocks())
            if matched / len(cue) >= SHARE:
                self._fired[annotation.id] = latest
                cues.append(Cue(annotation, latest, heard))
        return cues


def _filename(scene: str) -> str:
    """A file name for a scene's name: "Szene 1.2" is szene_1_2.json."""
    return "_".join(words(scene)) + ".json" if words(scene) else "standard.json"


class Store:
    """Each scene's text, kept in a file of its own in `folder`, read once
    and written on every change; without `folder`, in memory only. Safe to
    use from any thread."""

    def __init__(self, folder: Path | None = None):
        self.folder = folder
        self._held: dict[str, SceneText] = {}
        self._lock = threading.Lock()

    def get(self, scene: str) -> SceneText:
        """A copy of the scene's text, empty for a scene without one."""
        with self._lock:
            return self._load(scene).model_copy(deep=True)

    def put(self, scene: str, held: SceneText):
        with self._lock:
            self._held[scene] = held.model_copy(deep=True)
            if self.folder is None:
                return
            self.folder.mkdir(parents=True, exist_ok=True)
            path = self.folder / _filename(scene)
            path.write_text(json.dumps({"scene": scene, **held.model_dump()}, ensure_ascii=False,
                                       indent=1), encoding="utf-8")

    def _load(self, scene: str) -> SceneText:
        if scene not in self._held and self.folder is None:
            self._held[scene] = SceneText()
        if scene not in self._held:
            path = self.folder / _filename(scene)
            try:
                saved = json.loads(path.read_text(encoding="utf-8"))
                saved.pop("scene", None)
                self._held[scene] = SceneText(**saved)
            except (OSError, ValueError):
                self._held[scene] = SceneText()
        return self._held[scene]
