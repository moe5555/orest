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

Risiko and Menschlichkeit are measured too: the action recogniser rates each
named person from what their body does (actions.py), a separate text-only
request rates what each line says (speech.py), and a person's rating is the
higher of the two. Where the room was louder than the session's normal
speech, Risiko evidence from both is amplified (loudness.py). The report's
model rates only Auffälligkeit.

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
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

import numpy as np

from ollama import ResponseError, chat
from pydantic import (BaseModel, Field, ValidationError, computed_field, field_validator,
                      model_validator)

from . import capture, loudness, transcribe

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
- Vor jeder Aeusserung im Transkript steht, wer sie gesagt hat. "(unklar)"
  heisst, der Sprecher ist nicht bestimmt. "(laut)" oder "(geschrien)" nach
  dem Namen ist die gemessene Lautstaerke, verglichen mit dem sonst ueblichen
  Sprechen im Raum.
- "Zuvor gesagt" ist der Zusammenhang aus dem vorigen Zeitfenster. Bewerte,
  was in diesem Zeitfenster geschieht, und ob sich die Lage gegenueber vorher
  zuspitzt oder beruhigt.
- Beschreibung: kurz und knapp, was passiert ist und wer was getan hat.
- Personen: den Namen aus dem Schild ueber dem Gesicht uebernehmen. Wer ohne
  Schild zu sehen ist, heisst "Unbekannt".
- Auffaelligkeit je Person 0-5: wie stark das Verhalten der Person von dem
  der anderen Anwesenden abweicht. 0 gar nicht, 5 sehr stark.
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
    # Rated by the model against the others in the window, the only reference
    # it has. The deviation from a person's past behaviour is to be measured
    # outside the model (knowledge/components/02_processing.md, Auffälligkeit).
    auffaelligkeit: int = Field(ge=0, le=5)


class Handlung(BaseModel):
    """What the action recogniser measured for one person over a window.

    Ratings are 0-5, as the model's are. Each `anlass_` field names the class
    that contributed most to that rating, with its probability; it is empty
    when the rating is 0.
    """

    name: str
    risiko: int = Field(ge=0, le=5)
    menschlichkeit: int = Field(ge=0, le=5)
    anlass_risiko: str = ""
    anlass_menschlichkeit: str = ""
    # Classifications the person took part in, alone or in a pair.
    lesungen: int
    # The loudness gain on the reading that set Risiko (loudness.py).
    verstaerkung: float = 1.0


# Ratings measured from the action recogniser (actions.py) rather than
# generated, and the ratings the model generates. Both are derived from their
# models so that renaming a category cannot leave a renderer addressing a
# field that no longer exists.
GEMESSEN = tuple(name for name, field in Handlung.model_fields.items()
                 if field.annotation is int and name not in ("lesungen",))
GENERIERT = tuple(name for name, field in Person.model_fields.items()
                  if field.annotation is int)

# Every 0-5 rating per person, in the order renderers show them.
BEWERTUNGEN = GEMESSEN + GENERIERT


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


class Aeusserung(BaseModel):
    """One stretch of speech, and who said it where that was measured.

    `name` is a roster label, UNBEKANNT for a speaker whose body carries no
    name, or None when the speaker could not be told (speakers.py).
    """

    name: str | None = None
    text: str
    beginn: datetime
    ende: datetime
    # The model's literal reading of the line (speech.py): a reason, and
    # evidence from -5 to +5 for each measured rating. None until rated.
    begruendung: str = ""
    risiko: int | None = Field(default=None, ge=-5, le=5)
    menschlichkeit: int | None = Field(default=None, ge=-5, le=5)
    # How loud the line was (dBFS), and the gain that loudness puts on its
    # Risiko (loudness.py). 1 until the session is calibrated.
    pegel_db: float | None = None
    verstaerkung: float = 1.0
    # "laut" or "geschrien" where the line stood out from normal speech.
    lautstaerke: str = ""

    @property
    def risiko_verstaerkt(self) -> float | None:
        """Risiko evidence amplified by the line's loudness."""
        return None if self.risiko is None else loudness.amplified(self.risiko, self.verstaerkung)


# How the transcript names a line whose speaker could not be told.
UNKLAR = "(unklar)"


def protokoll(aeusserungen: list[Aeusserung]) -> str:
    """The transcript as the model reads it: one line per segment, speaker
    first, with the line's loudness where it stood out."""
    return "\n".join(
        f"{aeusserung.name or UNKLAR}"
        f"{f' ({aeusserung.lautstaerke})' if aeusserung.lautstaerke else ''}: {aeusserung.text}"
        for aeusserung in aeusserungen)


class Pegel(BaseModel):
    """The session's loudness calibration, as it stood for a report."""

    # Loudness takes effect (provisionally, while still learning).
    kalibriert: bool
    # The normal level is fixed for the rest of the session.
    endgueltig: bool = False
    # Seconds of speech calibrated on so far, up to loudness.CALIBRATION.
    gehoert_s: float
    # The normal speaking level and its spread, once calibrated.
    normal_db: float | None = None
    streuung_db: float | None = None


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
    handlungen: list[Handlung] = []
    aeusserungen: list[Aeusserung] = []
    pegel: Pegel | None = None
    latenz_s: float
    bericht: Lagebericht

    def erkannt(self, name: str) -> bool:
        """Whether a name in the report is a recognition rather than a guess."""
        return any(person.erkannt for person in self.anwesend if person.name == name)

    def handlung(self, name: str) -> Handlung | None:
        """What was measured for a named person, or None if nothing was."""
        if name == UNBEKANNT:
            return None
        return next((handlung for handlung in self.handlungen if handlung.name == name), None)

    def gesprochen(self, name: str) -> list[Aeusserung]:
        """The rated lines attributed to a named person."""
        if name == UNBEKANNT:
            return []
        return [line for line in self.aeusserungen if line.name == name and line.risiko is not None]

    def bewertung(self, name: str, rating: str) -> tuple[int | None, str]:
        """One measured rating of a person, and what caused it.

        The higher of what the person did (their Handlung) and what they said
        (the peak of their rated lines, clipped to 0-5). None, with no cause,
        when neither was measured; the cause is empty for a rating of 0.
        """
        found = []
        handlung = self.handlung(name)
        if handlung:
            found.append((getattr(handlung, rating), getattr(handlung, f"anlass_{rating}")))
        lines = self.gesprochen(name)
        if lines:
            def evidence(line: Aeusserung) -> float:
                return line.risiko_verstaerkt if rating == "risiko" else getattr(line, rating)

            line = max(lines, key=evidence)
            value = int(max(0, min(5, float(np.floor(evidence(line) + 0.5)))))
            cause = f"„{line.text}“: {line.begruendung}" if value else ""
            if cause and rating == "risiko" and line.verstaerkung > 1.0:
                cause += f" · laut ×{line.verstaerkung:.1f}"
            found.append((value, cause))
        if not found:
            return None, ""
        return max(found, key=lambda candidate: candidate[0])

    def bewertungen(self, person: Person) -> dict[str, int | None]:
        """A person's ratings in BEWERTUNGEN order, measured and generated.

        A measured rating is None when neither the recogniser nor speech
        attribution caught anything of the person, e.g. a face seen without
        its body and saying nothing, which is not the same as a reading of 0.
        """
        return {**{name: self.bewertung(person.name, name)[0] for name in GEMESSEN},
                **{name: getattr(person, name) for name in GENERIERT}}


def _prompt(transcript: str, anwesend: list[Anwesend] = (), vorher: str = "") -> str:
    liste = "\n".join(f"- {person.name} ({'erkannt' if person.erkannt else 'vermutet'})"
                      for person in anwesend) or "(niemand erfasst)"
    zuvor = f"\n\nZuvor gesagt:\n{vorher}" if vorher else ""
    return (f"{ANWEISUNG}\n\nAnwesenheitsliste:\n{liste}{zuvor}"
            f"\n\nTranskript:\n{transcript or '(keine Sprache erkannt)'}")


def schema(anwesend: list[Anwesend] = ()) -> dict:
    """The Lagebericht schema, with person names held to who is present."""
    document = Lagebericht.model_json_schema()
    document["$defs"]["Person"]["properties"]["name"]["enum"] = [
        *(person.name for person in anwesend), UNBEKANNT]
    return document


def analyse(frames: list[bytes], transcript: str = "", anwesend: list[Anwesend] = (),
            model=MODEL, num_predict=NUM_PREDICT, vorher: str = "") -> Lagebericht:
    """Run one SITREP generation over the given stills, transcript and roster."""
    response = chat(
        model=model,
        messages=[{"role": "user", "content": _prompt(transcript, anwesend, vorher),
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

# What the action recogniser measured up to a moment and has not yet reported,
# with a loudness gain on Risiko (actions.ActionRatings.take).
Handlungen = Callable[[datetime, Callable[[datetime, datetime], float] | None], list[Handlung]]

# Who spoke each segment, given the segments and the moment the audio began
# (speakers.Speakers.attribute, with the names known at the time).
Sprecher = Callable[[list[transcribe.Segment], datetime], list[Aeusserung]]

# The lines with their literal reading filled in (speech.rate).
Einschaetzen = Callable[[list[Aeusserung]], list[Aeusserung]]


# A line whose segment ends this close to the end of its window's sound was
# most likely cut off by the window's end (Whisper's voice detection ends a
# segment where the sound stops).
CUT = 0.5

# The longest sound held back for the next window. A longer line is reported
# as it stands, so that a monologue does not delay its report indefinitely.
MAX_CARRY = 10.0

# Sound kept before a held-back line's start, so its first word is not clipped.
CARRY_LEAD = 0.2

# Lines of the previous report given to the model as context.
VORHER = 8


def _held_back(segmente: list[transcribe.Segment],
               window: capture.Window) -> tuple[list[transcribe.Segment], np.ndarray | None]:
    """The segments to report now, and the sound of a line cut off by the window's end."""
    if not segmente:
        return segmente, None
    last = segmente[-1]
    if (last.end < window.audio_seconds - CUT
            or window.audio_seconds - last.start > MAX_CARRY):
        return segmente, None
    samples, rate = capture.decode_wav(window.audio)
    return segmente[:-1], samples[max(0, int((last.start - CARRY_LEAD) * rate)):]


def sitrep(window: capture.Window, model=MODEL, roster: Roster | None = None,
           handlungen: Handlungen | None = None, sprecher: Sprecher | None = None,
           einschaetzen: Einschaetzen | None = None,
           laut: loudness.Calibration | None = None,
           language: str = transcribe.LANGUAGE, vorher: list[Aeusserung] = ()) -> Sitrep:
    """Build the full SITREP document for a capture window.

    Latency covers transcription and generation together: both have to finish
    inside the window for the report to keep pace with the live feed.
    """
    return _sitrep(window, model=model, roster=roster, handlungen=handlungen,
                   sprecher=sprecher, einschaetzen=einschaetzen, laut=laut,
                   language=language, vorher=vorher)[0]


def _sitrep(window: capture.Window, model=MODEL, roster: Roster | None = None,
            handlungen: Handlungen | None = None, sprecher: Sprecher | None = None,
            einschaetzen: Einschaetzen | None = None,
            laut: loudness.Calibration | None = None,
            language: str = transcribe.LANGUAGE, vorher: list[Aeusserung] = (),
            hold_back: bool = False) -> tuple[Sitrep, np.ndarray | None]:
    """sitrep(), and with `hold_back` the sound of a line cut off by the
    window's end: left out of this report, for the next window to begin with."""
    started = time.monotonic()
    anwesend = [Anwesend(name=person.label, erkannt=person.known)
                for person in (roster(window.started, window.ended) if roster else [])]
    segmente = transcribe.segments(window.audio, language=language)
    carry = None
    if hold_back:
        segmente, carry = _held_back(segmente, window)
    # The recorder cuts the sound when the window ends, so its first sample
    # was recorded this long before the window's end.
    audio_start = window.ended - timedelta(seconds=window.audio_seconds)

    # Loudness: the session learns its normal speaking level from its first
    # speech, then amplifies Risiko where the room was louder (loudness.py).
    timeline = loudness.Timeline(window.audio, audio_start) if laut else None
    if laut:
        for segment in segmente:
            laut.learn(timeline.level(audio_start + timedelta(seconds=segment.start),
                                      audio_start + timedelta(seconds=segment.end)),
                       segment.end - segment.start)

    def gain(begins: datetime, ends: datetime) -> float:
        return loudness.gain_over(timeline, laut, begins, ends)

    gemessen = handlungen(window.ended, gain if laut else None) if handlungen else []
    aeusserungen = (sprecher(segmente, audio_start) if sprecher else
                    [Aeusserung(text=segment.text,
                                beginn=audio_start + timedelta(seconds=segment.start),
                                ende=audio_start + timedelta(seconds=segment.end))
                     for segment in segmente])
    if laut:
        aeusserungen = [line.model_copy(update={
                            "pegel_db": timeline.level(line.beginn, line.ende),
                            "verstaerkung": round(gain(line.beginn, line.ende), 2),
                            "lautstaerke": loudness.label(laut, timeline.level(line.beginn,
                                                                               line.ende))})
                        for line in aeusserungen]
    if einschaetzen and aeusserungen:
        # Rating the lines needs neither the frames nor the report, so it runs
        # alongside the report's own request.
        with ThreadPoolExecutor(max_workers=1) as pool:
            eingeschaetzt = pool.submit(einschaetzen, aeusserungen)
            bericht = analyse(window.frames, protokoll(aeusserungen), anwesend, model=model,
                              vorher=protokoll(list(vorher)))
            aeusserungen = eingeschaetzt.result()
    else:
        bericht = analyse(window.frames, protokoll(aeusserungen), anwesend, model=model,
                          vorher=protokoll(list(vorher)))
    return Sitrep(
        zeitfenster=Zeitfenster(beginn=window.started, ende=window.ended,
                                dauer_s=round(window.seconds, 1)),
        quelle=Quelle(bilder=len(window.frames), ton_s=round(window.audio_seconds, 1)),
        gesagt=transcribe.join(segmente),
        anwesend=anwesend,
        handlungen=gemessen,
        aeusserungen=aeusserungen,
        pegel=Pegel(kalibriert=laut.calibrated, endgueltig=laut.settled,
                    gehoert_s=round(laut.heard, 1),
                    normal_db=None if laut.mean is None else round(laut.mean, 1),
                    streuung_db=None if laut.spread is None else round(laut.spread, 1))
              if laut else None,
        latenz_s=round(time.monotonic() - started, 1),
        bericht=bericht,
    ), carry


def sitreps(windows: Iterable[capture.Window], *, model=MODEL,
            roster: Roster | None = None,
            handlungen: Handlungen | None = None,
            sprecher: Sprecher | None = None,
            einschaetzen: Einschaetzen | None = None,
            laut: loudness.Calibration | None = None,
            language: str = transcribe.LANGUAGE) -> Iterator[Sitrep]:
    """Yield one SITREP per capture window.

    Takes the windows rather than the devices that produce them, so the caller
    decides where the camera comes from: a loop of its own, a shared stream, or
    a fixture. Runs until the caller stops consuming, and a window whose reply
    is unusable is skipped rather than ending the session.

    A line still being spoken when its window ended is held back and reported
    whole with the next window. Each report's model is shown the previous
    report's last lines, so that it can see a scene building up.
    """
    carry = None
    vorher: list[Aeusserung] = []
    for captured in windows:
        if carry is not None:
            captured = capture.prepend(carry, captured)
        try:
            document, carry = _sitrep(captured, model=model, roster=roster,
                                      handlungen=handlungen, sprecher=sprecher,
                                      einschaetzen=einschaetzen, laut=laut, language=language,
                                      vorher=vorher, hold_back=True)
        except (ValidationError, ResponseError) as error:
            # A reply that ran into the token cap is truncated and does not
            # parse; a rejected prompt returns an error. Losing one window
            # beats ending the session.
            kind = ("unparseable reply" if isinstance(error, ValidationError)
                    else "rejected prompt")
            print(f"window {captured.index}: {kind}, skipped", file=sys.stderr)
            carry = None
            continue

        vorher = document.aeusserungen[-VORHER:]
        yield document
