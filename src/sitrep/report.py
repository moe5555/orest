"""SITREP generation: turns a capture window into a structured German report.

Implements step 5 of the Realtime-SITREP implementation steps in
knowledge/components/02_processing.md ("Write SITREP report JSON format").

Nothing is written to disk. Frames arrive as in-memory bytes from capture.py,
and a finished report is yielded to whatever is consuming the stream and then
dropped: the live SITREP leaves no record behind.

Speech is transcribed by Whisper (transcribe.py) and given to the model as
text; the model never hears the audio. The transcript is written into the
report verbatim as "gesagt" rather than generated, so what was said cannot be
embellished.

Who is present is measured in the same way: the presence tracker
(presence.py) names every face it follows, from the cast enrolment or as a
marked guess, and the model may only use those names. The grammar holds each
person's name to that list, so the model cannot invent one, and each name is
drawn above its face in the frames (annotate.py), so the model reads which
person carries which name rather than guessing it.

Whether to intervene is decided here, not by the model: a scene rated above
SCHWELLE for escalation or danger triggers the recommendation, and below it
any measure the model wrote is discarded.

A Sitrep keeps the model's Lagebericht as a nested field rather than merging
it into the surrounding document. Time frame, source, transcript and the
people present are measured, and the separation keeps a generated field from
ever taking the place of a measured one.

Ollama is given the schema as a grammar constraint, so the reply parses as JSON
without repair. Field descriptions are part of that schema and steer the model,
so they are kept short: every token in the schema and the reply costs latency,
which step 6 caps.

A run is assembled by session.py, which owns the camera and the microphone and
feeds `sitreps()` the windows they produce.
"""

from __future__ import annotations

import sys
import time
from collections.abc import Callable, Iterable, Iterator
from datetime import datetime
from typing import TYPE_CHECKING

from ollama import ResponseError, chat
from pydantic import (BaseModel, Field, ValidationError, computed_field, field_validator,
                      model_validator)

from . import capture, transcribe

if TYPE_CHECKING:
    from . import presence

# e4b fits well on an 8GB GPU.
MODEL = "gemma4:e4b"

# Cap on generated tokens. A three-person report with its three forecasts needs
# roughly 500. The reply is only parseable if generation finishes: the schema
# grammar guarantees well-formed JSON, but a reply cut off at the cap is
# truncated mid-string and fails to parse, so the cap has to sit clear of a
# normal report.
NUM_PREDICT = 1000

CONTEXT = 8192

# Low but non-zero: near-deterministic wording, still able to phrase a scene it
# has no set phrase for.
TEMPERATURE = 0.2

# e4b is prone to degenerate repetition, which runs a reply into the token cap
# and truncates the JSON. Penalising repeats keeps generations terminating.
REPEAT_PENALTY = 1.2

# Scene ratings above this, for escalation or danger, call for intervention.
SCHWELLE = 6

ANWEISUNG = f"""Du bist Orest, ein Ueberwachungssystem.
Du erhaeltst Standbilder aus einem Zeitfenster, das Transkript dessen, was
dort gesprochen wurde, und die Anwesenheitsliste der Gesichtserkennung. In
den Bildern steht der Name jeder erfassten Person in einem Schild ueber ihrem
Gesicht. Erstelle daraus einen Lagebericht.

Regeln:
- Berichte ausschliesslich, was in den Bildern und im Transkript belegt ist.
  Keine Spekulation, keine Ausschmueckung.
- Das Transkript ist die einzige Quelle fuer Gesprochenes. Erfinde keine
  weiteren Aeusserungen, Stimmen oder Geraeusche.
- Beschreibung: kurz und knapp, was passiert ist und wer was getan hat.
- Personen: den Namen aus dem Schild ueber dem Gesicht uebernehmen. Wer ohne
  Schild zu sehen ist, heisst "Unbekannt".
- Bewertungen je Person 0-5: 0 trifft nicht zu, 5 trifft stark zu. Relevanz:
  wie sehr die Person das Geschehen bestimmt.
- Szene: Relevanz, Eskalation und Gefahr der Szene, 0-10, von niedrig bis hoch.
- Prognose: die drei wahrscheinlichsten Verlaeufe, jeweils mit
  Wahrscheinlichkeit in Prozent, zusammen hoechstens 100.
- Empfehlung: nur wenn Eskalation oder Gefahr der Szene ueber {SCHWELLE} liegt,
  eine konkrete Massnahme zum Einschreiten. Sonst leer.
- Knapp und nominal, Behoerdenstil. Keine Anrede, keine Erzaehlsaetze.
- Ist etwas nicht erkennbar, lass das Feld leer statt zu raten."""

# Name for a person in frame whom the presence tracker has not followed, e.g.
# someone who never faced the camera.
UNBEKANNT = "Unbekannt"


class Person(BaseModel):
    name: str = Field(description="Name aus dem Schild ueber dem Gesicht")
    beschreibung: str = Field(description="Wie die Person wahrgenommen wird, knapp")
    kollaborativ: int = Field(ge=0, le=5)
    relevanz: int = Field(ge=0, le=5)
    verantwortungsvoll: int = Field(ge=0, le=5)
    menschlich: int = Field(ge=0, le=5)
    gefahr: int = Field(ge=0, le=5)


# The 0-5 rating categories, in the order they are asked for. Derived from the
# model so that renaming a category cannot leave a renderer addressing a field
# that no longer exists.
BEWERTUNGEN = tuple(name for name, field in Person.model_fields.items()
                    if field.annotation is int)


class Verlauf(BaseModel):
    """One way the situation may develop."""

    verlauf: str = Field(description="Moeglicher weiterer Verlauf, ein Satz")
    wahrscheinlichkeit: int = Field(ge=0, le=100, description="Prozent")


# Forecasts per report. The grammar holds the model to exactly this many.
PROGNOSEN = 3


class Szene(BaseModel):
    """The scene as a whole, rated 0-10 from low to high."""

    relevanz: int = Field(ge=0, le=10)
    eskalation: int = Field(ge=0, le=10)
    gefahr: int = Field(ge=0, le=10)


class Lagebericht(BaseModel):
    """The model-generated part of a SITREP."""

    beschreibung: str = Field(description="Was passiert ist, wer was getan hat")
    personen: list[Person]
    szene: Szene
    prognose: list[Verlauf] = Field(min_length=PROGNOSEN, max_length=PROGNOSEN)
    empfehlung: str = Field(
        description=f"Massnahme zum Einschreiten, nur bei Eskalation oder Gefahr "
                    f"ueber {SCHWELLE}, sonst leer")

    @computed_field
    @property
    def einschreiten(self) -> bool:
        """Whether the scene calls for intervention, by its own ratings.

        Derived rather than generated, so the rule is SCHWELLE and not the
        model's judgement. Absent from the schema the model is given.
        """
        return self.szene.eskalation > SCHWELLE or self.szene.gefahr > SCHWELLE

    @field_validator("prognose")
    @classmethod
    def _wahrscheinlichste_zuerst(cls, prognose: list[Verlauf]) -> list[Verlauf]:
        # Ordered here rather than trusted to the model, so a renderer can take
        # the first forecast as the most likely one.
        return sorted(prognose, key=lambda verlauf: -verlauf.wahrscheinlichkeit)

    @model_validator(mode="after")
    def _empfehlung_nur_ueber_schwelle(self) -> Lagebericht:
        # Below the threshold a model still tends to write a measure, often
        # one saying there is none ("Keine Massnahme."); only the rule decides.
        if not self.einschreiten:
            self.empfehlung = ""
        return self


class Anwesend(BaseModel):
    """One person the presence tracker saw during the window."""

    name: str
    # False for a guessed name ("Vielleicht: Jakob"), which is not a recognition.
    erkannt: bool


class Zeitfenster(BaseModel):
    """The stretch of rehearsal a report covers."""

    beginn: datetime
    ende: datetime
    dauer_s: float


class Quelle(BaseModel):
    """How much material the report was made from."""

    bilder: int
    ton_s: float


class Sitrep(BaseModel):
    """One report: what was measured about a window, and what the model made of it."""

    zeitfenster: Zeitfenster
    quelle: Quelle
    gesagt: str
    anwesend: list[Anwesend] = []
    latenz_s: float
    bericht: Lagebericht

    def erkannt(self, name: str) -> bool:
        """Whether a name in the report is a recognition rather than a guess."""
        return any(person.erkannt for person in self.anwesend if person.name == name)


def _prompt(transcript: str, anwesend: list[Anwesend] = ()) -> str:
    liste = "\n".join(f"- {person.name} ({'erkannt' if person.erkannt else 'vermutet'})"
                      for person in anwesend) or "(niemand erfasst)"
    return (f"{ANWEISUNG}\n\nAnwesenheitsliste:\n{liste}"
            f"\n\nTranskript:\n{transcript or '(keine Sprache erkannt)'}")


def schema(anwesend: list[Anwesend] = ()) -> dict:
    """The Lagebericht schema, with person names held to who is present."""
    document = Lagebericht.model_json_schema()
    document["$defs"]["Person"]["properties"]["name"]["enum"] = [
        *(person.name for person in anwesend), UNBEKANNT]
    return document


def analyse(frames: list[bytes], transcript: str = "", anwesend: list[Anwesend] = (),
            model=MODEL, num_predict=NUM_PREDICT) -> Lagebericht:
    """Run one SITREP generation over the given stills, transcript and roster."""
    response = chat(
        model=model,
        messages=[{"role": "user", "content": _prompt(transcript, anwesend),
                   "images": list(frames)}],
        think=False,
        keep_alive=-1,
        format=schema(anwesend),
        options={
            "num_ctx": CONTEXT,
            "num_predict": num_predict,
            "temperature": TEMPERATURE,
            "repeat_penalty": REPEAT_PENALTY,
        },
    )
    return Lagebericht.model_validate_json(response.message.content)


# A presence tracker's roster(since, until): who was seen during a stretch of time.
Roster = Callable[[datetime, datetime], "list[presence.Presence]"]


def sitrep(window: capture.Window, model=MODEL, roster: Roster | None = None) -> Sitrep:
    """Build the full SITREP document for a capture window.

    Latency covers transcription and generation together: both have to finish
    inside the window for the report to keep pace with the live feed.
    """
    started = time.monotonic()
    anwesend = [Anwesend(name=person.label, erkannt=person.known)
                for person in (roster(window.started, window.ended) if roster else [])]
    transcript = transcribe.transcribe(window.audio)
    bericht = analyse(window.frames, transcript, anwesend, model=model)
    return Sitrep(
        zeitfenster=Zeitfenster(beginn=window.started, ende=window.ended,
                                dauer_s=round(window.seconds, 1)),
        quelle=Quelle(bilder=len(window.frames), ton_s=round(window.audio_seconds, 1)),
        gesagt=transcript,
        anwesend=anwesend,
        latenz_s=round(time.monotonic() - started, 1),
        bericht=bericht,
    )


def sitreps(windows: Iterable[capture.Window], *, model=MODEL,
            roster: Roster | None = None) -> Iterator[Sitrep]:
    """Yield one SITREP per capture window.

    Takes the windows rather than the devices that produce them, so the caller
    decides where the camera comes from: a loop of its own, a shared stream, or
    a fixture. Runs until the caller stops consuming, and a window whose reply
    is unusable is skipped rather than ending the session.
    """
    for captured in windows:
        try:
            document = sitrep(captured, model=model, roster=roster)
        except (ValidationError, ResponseError) as error:
            # A reply that ran into the token cap is truncated and does not
            # parse; a rejected prompt returns an error. Losing one window
            # beats ending the session.
            kind = ("unparseable reply" if isinstance(error, ValidationError)
                    else "rejected prompt")
            print(f"window {captured.index}: {kind}, skipped", file=sys.stderr)
            continue

        yield document
