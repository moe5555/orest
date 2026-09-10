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

A Sitrep keeps the model's Lagebericht as a nested field rather than merging
it into the surrounding document. Time frame, source and transcript are
measured, and the separation keeps a generated field from ever taking the
place of a measured one.

Ollama is given the schema as a grammar constraint, so the reply parses as JSON
without repair. Field descriptions are part of that schema and steer the model,
so they are kept short: every token in the schema and the reply costs latency,
which step 6 caps.

The live loop is run from main.py.
"""

import sys
import time
from datetime import datetime

from ollama import ResponseError, chat
from pydantic import BaseModel, Field, ValidationError

from . import capture, devices, transcribe

# e4b fits well on an 8GB GPU.
MODEL = "gemma4:e4b"

# Cap on generated tokens. A three-person report needs roughly 400. The reply
# is only parseable if generation finishes: the schema grammar guarantees
# well-formed JSON, but a reply cut off at the cap is truncated mid-string and
# fails to parse, so the cap has to sit clear of a normal report.
NUM_PREDICT = 700

CONTEXT = 8192

# Low but non-zero: near-deterministic wording, still able to phrase a scene it
# has no set phrase for.
TEMPERATURE = 0.2

# e4b is prone to degenerate repetition, which runs a reply into the token cap
# and truncates the JSON. Penalising repeats keeps generations terminating.
REPEAT_PENALTY = 1.2

ANWEISUNG = """Du bist Orest, ein Ueberwachungssystem.
Du erhaeltst Standbilder aus einem Zeitfenster und das Transkript dessen, was
dort gesprochen wurde. Erstelle daraus einen Lagebericht.

Regeln:
- Berichte ausschliesslich, was in den Bildern und im Transkript belegt ist.
  Keine Spekulation, keine Ausschmueckung.
- Das Transkript ist die einzige Quelle fuer Gesprochenes. Erfinde keine
  weiteren Aeusserungen, Stimmen oder Geraeusche.
- Bezeichne Personen als P-01, P-02 in der Reihenfolge ihres Auftretens.
- Knapp und nominal, Behoerdenstil. Keine Anrede, keine Erzaehlsaetze.
- Bewertungen 0-5: 0 trifft nicht zu, 5 trifft stark zu.
- Ist etwas nicht erkennbar, lass das Feld leer statt zu raten."""


class Person(BaseModel):
    kennung: str = Field(description="P-01, P-02 ...")
    merkmale: str = Field(description="Aeussere Merkmale, knapp")
    taetigkeit: str = Field(description="Beobachtete Handlung")
    verantwortungsvoll: int = Field(ge=0, le=5)
    menschlich: int = Field(ge=0, le=5)
    gefahr: int = Field(ge=0, le=5)
    kollaborativ: int = Field(ge=0, le=5)


# The 0-5 rating categories of 02_processing.md, in the order they are asked
# for. Derived from the model so that renaming a category cannot leave a
# renderer addressing a field that no longer exists.
BEWERTUNGEN = tuple(name for name, field in Person.model_fields.items()
                    if field.annotation is int)


class Lagebericht(BaseModel):
    """The model-generated part of a SITREP."""

    lage: str = Field(description="Gesamtlage in einem Satz")
    personen: list[Person]
    ereignisse: list[str] = Field(description="Beobachtete Vorgaenge, Stichpunkte")
    prognose: str = Field(description="Zu erwartende Entwicklung")
    empfehlung: str = Field(description="Vorgeschlagene Massnahme")
    vertrauen: int = Field(ge=0, le=5, description="Sicherheit des Berichts")


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
    latenz_s: float
    bericht: Lagebericht


def _prompt(transcript: str) -> str:
    return f"{ANWEISUNG}\n\nTranskript:\n{transcript or '(keine Sprache erkannt)'}"


def analyse(frames: list[bytes], transcript: str = "",
            model=MODEL, num_predict=NUM_PREDICT) -> Lagebericht:
    """Run one SITREP generation over the given stills and transcript."""
    response = chat(
        model=model,
        messages=[{"role": "user", "content": _prompt(transcript), "images": list(frames)}],
        think=False,
        keep_alive=-1,
        format=Lagebericht.model_json_schema(),
        options={
            "num_ctx": CONTEXT,
            "num_predict": num_predict,
            "temperature": TEMPERATURE,
            "repeat_penalty": REPEAT_PENALTY,
        },
    )
    return Lagebericht.model_validate_json(response.message.content)


def sitrep(window: capture.Window, model=MODEL) -> Sitrep:
    """Build the full SITREP document for a capture window.

    Latency covers transcription and generation together: both have to finish
    inside the window for the report to keep pace with the live feed.
    """
    started = time.monotonic()
    transcript = transcribe.transcribe(window.audio)
    bericht = analyse(window.frames, transcript, model=model)
    return Sitrep(
        zeitfenster=Zeitfenster(beginn=window.started, ende=window.ended,
                                dauer_s=round(window.seconds, 1)),
        quelle=Quelle(bilder=len(window.frames), ton_s=round(window.audio_seconds, 1)),
        gesagt=transcript,
        latenz_s=round(time.monotonic() - started, 1),
        bericht=bericht,
    )


def run_live(video: devices.VideoDevice, audio: devices.AudioDevice, *,
             interval: float, window: float, model=MODEL):
    """Yield one SITREP per capture window.

    Runs until the caller stops consuming. A window whose reply is unusable is
    skipped rather than ending the session.
    """
    windows = capture.run(video, audio, interval=interval, window=window)

    try:
        for captured in windows:
            try:
                document = sitrep(captured, model=model)
            except (ValidationError, ResponseError) as error:
                # A reply that ran into the token cap is truncated and does not
                # parse; a rejected prompt returns an error. Losing one window
                # beats ending the session.
                kind = ("unparseable reply" if isinstance(error, ValidationError)
                        else "rejected prompt")
                print(f"window {captured.index}: {kind}, skipped", file=sys.stderr)
                continue

            yield document
    finally:
        windows.close()
