"""SITREP generation: the report the operator asks for, and the recommendation.

Implements step 5 of the Realtime-SITREP implementation steps in
knowledge/components/02_processing.md ("Write SITREP report JSON format").

A report is made when the operator asks for one, not every window
(changelog.md, 2026-09-29). It reads the Chronik, the running summary of the
scene kept in the background (chronik.py), so it covers the last minutes and
how they developed, not only the last seconds; the live values (lage.py);
the last stretch's lines word for word; and stills from the last seconds.
Everything urgent reaches the operator before and without it, through the
fast lane (utterances.py, lage.py).

The recommendation (`empfehlen`) reads the same and writes a fraction of it:
whether to intervene now, and how. It is asked for when the live values
raise the alarm, or by the operator.

Nothing is written to disk. A finished report is handed to whoever asked for
it and then dropped: the live SITREP leaves no record behind.

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
speech, Risiko evidence from both is amplified (loudness.py).
Vorhersehbarkeit is measured from the same bodies, against the rehearsal
corpus (predictability.py). The model rates none of a person's values.

Whether to intervene is decided here, not by the model: a scene rated above
SCHWELLE for escalation or danger triggers the recommendation, and below it
any measure the model wrote is discarded.

A Sitrep keeps the model's Lagebericht as a nested field rather than merging
it into the surrounding document. Time frame, source, transcript and the
people present are measured, and the separation keeps a generated field from
ever taking the place of a measured one.

Ollama is given the schema as a grammar constraint, so the reply parses as JSON
without repair. Field descriptions are part of that schema and steer the model,
so they are kept short: every token in the schema and the reply costs latency.
"""

from __future__ import annotations

import time
from datetime import datetime

import numpy as np

from ollama import chat
from pydantic import BaseModel, Field, computed_field, field_validator, model_validator

from . import llm, loudness

# The model on the production machine (VSH-ARLT-5090, 32 GB). Any Ollama
# model can be chosen with --model; a run checks that it is installed
# (llm.pruefen).
MODEL = "gemma4:26b"

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

# Degenerate repetition runs a reply into the token cap and truncates the
# JSON; it was seen with gemma4:e4b. Penalising repeats keeps generations
# terminating.
REPEAT_PENALTY = 1.2

# Scene ratings above this, for escalation or danger, call for intervention.
SCHWELLE = 6

# What every prompt says about its sources: the Chronik's context, the
# transcript and the stills. Kept first and identical, so that Ollama can
# reuse its cache for the prompt's opening (live_sitrep_latency.md, fix 4).
QUELLEN = """Du bist Apollon, ein militaerisches Aufklaerungs- und Lagesystem.

Quellen:
- Rueckblick und Abschnitte: das laufende Protokoll der Szene, aelteste
  zuerst, mit Eskalation und Gefahr (0-10) und Tendenz je Abschnitt.
- Gemessen jetzt: Risiko und Menschlichkeit (0-5) je Person aus
  Aktionserkennung und Sprache, mit Anlass und Alter; Vorhersehbarkeit
  (-5 bis 5) je Person: wie sehr ihre Bewegung den Proben gleicht, -5 nie
  so geprobt, 5 oft geprobt.
- Transkript: das Woertliche der letzten Abschnitte. Vor jeder Aeusserung
  steht, wer sie gesagt hat. "(unklar)" heisst, der Sprecher ist nicht
  bestimmt. "(laut)" oder "(geschrien)" nach dem Namen ist die gemessene
  Lautstaerke, verglichen mit dem sonst ueblichen Sprechen im Raum.
- Standbilder der letzten Sekunden. In den Bildern steht der Name jeder
  erfassten Person in einem Schild ueber ihrem Gesicht.

Regeln fuer alles:
- Ausschliesslich, was in diesen Quellen belegt ist. Keine Spekulation,
  keine Ausschmueckung. Erfinde keine Aeusserungen, Stimmen oder Geraeusche.
- Militaerischer Meldestil wie im Gefechtsstand: knapp, nominal, Lage,
  Kraefte, Bedrohung, Wirkung. Erfasste Personen sind Kontakte, beim Namen
  genannt. Einschaetzungen mit Gewissheit: "mit hoher/mittlerer/geringer
  Sicherheit", "wahrscheinlich", "nahezu sicher". Keine Polizei- oder
  Verwaltungssprache, keine Anrede, keine Erzaehlsaetze.
- Ist etwas nicht erkennbar, lass das Feld leer statt zu raten."""

# The register of a measure, shared by the report and the recommendation.
MASSNAHMEN = ("Etwa: militaerische Intervention, Raum abriegeln, Kontakt "
              "isolieren, Einsatzkraefte heranfuehren.")

ANWEISUNG = f"""{QUELLEN}

Aufgabe: ein Lagebericht ueber die Szene bis jetzt.
- Verlauf: zwei bis drei Saetze, chronologisch: wie die Szene begann,
  die Wendepunkte mit Uhrzeit und Anlass, und wo die Lage jetzt steht.
- Beschreibung: die Lage jetzt, kurz: was geschieht, wer was tut.
- Personen: den Namen aus dem Schild ueber dem Gesicht uebernehmen. Wer ohne
  Schild zu sehen ist, heisst "Unbekannt". Beschreibung ein kurzer Satz.
- Szene: Relevanz, Eskalation und Gefahr der Lage jetzt, 0-10, von niedrig
  bis hoch.
- Prognose: die drei wahrscheinlichsten Verlaeufe, je ein kurzer Satz, mit
  Wahrscheinlichkeit in Prozent, zusammen hoechstens 100.
- Empfehlung: nur wenn Eskalation oder Gefahr der Szene ueber {SCHWELLE}
  liegt, eine konkrete militaerische Massnahme zum Einschreiten. {MASSNAHMEN}
  Sonst leer."""

# Name for a person in frame whom the presence tracker has not followed, e.g.
# someone who never faced the camera.
UNBEKANNT = "Unbekannt"


class Person(BaseModel):
    name: str = Field(description="Name aus dem Schild ueber dem Gesicht")
    beschreibung: str = Field(description="Wie die Person wahrgenommen wird, knapp")


class Handlung(BaseModel):
    """What the action recogniser measured for one person over a window.

    Risiko and Menschlichkeit are 0-5. Each `anlass_` field names the class
    that contributed most to that rating, with its probability; it is empty
    when the rating is 0. Vorhersehbarkeit is the mean of the person's scores
    against the rehearsals, -5 to +5, and None without a reference.
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
    vorhersehbarkeit: int | None = Field(default=None, ge=-5, le=5)


# Ratings measured as evidence, 0-5, from the action recogniser (actions.py)
# and from speech. Derived from the model so that renaming a category cannot
# leave a renderer addressing a field that no longer exists.
GEMESSEN = tuple(name for name, field in Handlung.model_fields.items()
                 if field.annotation is int and name not in ("lesungen",))

# The rating measured against the rehearsal corpus, -5 to +5 (predictability.py).
VORHERSEHBARKEIT = "vorhersehbarkeit"

# Every rating per person, in the order renderers show them.
BEWERTUNGEN = GEMESSEN + (VORHERSEHBARKEIT,)


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


def ueber_schwelle(szene: Szene) -> bool:
    """Whether a scene's ratings call for intervention."""
    return szene.eskalation > SCHWELLE or szene.gefahr > SCHWELLE


EMPFEHLUNG_FELD = (f"Militaerische Massnahme zum Einschreiten, nur bei Eskalation oder Gefahr "
                   f"ueber {SCHWELLE}, sonst leer")


class Lagebericht(BaseModel):
    """The model-generated part of a SITREP."""

    # First, so the model has stated how the scene developed before it
    # describes where it stands.
    verlauf: str = Field(description="Wie sich die Lage entwickelt hat, mit Wendepunkten")
    beschreibung: str = Field(description="Die Lage jetzt: was geschieht, wer was tut")
    personen: list[Person]
    szene: Szene
    prognose: list[Verlauf] = Field(min_length=PROGNOSEN, max_length=PROGNOSEN)
    empfehlung: str = Field(description=EMPFEHLUNG_FELD)

    @computed_field
    @property
    def einschreiten(self) -> bool:
        """Whether the scene calls for intervention, by its own ratings.

        Derived rather than generated, so the rule is SCHWELLE and not the
        model's judgement. Absent from the schema the model is given.
        """
        return ueber_schwelle(self.szene)

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
    """The stretch of rehearsal a report covers: from the start of the
    Chronik it read to the moment it was asked for."""

    beginn: datetime
    ende: datetime
    dauer_s: float


class Quelle(BaseModel):
    """How much material the report was made from."""

    bilder: int
    # Summarised stretches of the scene read (chronik.py), and the seconds of
    # them given word for word.
    abschnitte: int = 0
    woertlich_s: float = 0.0


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
        """A person's ratings in BEWERTUNGEN order.

        A rating is None when it was not measured: Risiko and Menschlichkeit
        when neither the recogniser nor speech attribution caught anything of
        the person, e.g. a face seen without its body and saying nothing, which
        is not the same as a reading of 0; Vorhersehbarkeit when the person
        was never classified alone against a reference.
        """
        handlung = self.handlung(person.name)
        return {**{name: self.bewertung(person.name, name)[0] for name in GEMESSEN},
                VORHERSEHBARKEIT: handlung.vorhersehbarkeit if handlung else None}


def _prompt(anweisung: str, transcript: str, anwesend: list[Anwesend] = (),
            kontext: str = "", werte: str = "", anlass: str = "") -> str:
    """The prompt, fixed part first: instructions, then the roster, the
    Chronik, the live values and the transcript, which change most."""
    liste = "\n".join(f"- {person.name} ({'erkannt' if person.erkannt else 'vermutet'})"
                      for person in anwesend) or "(niemand erfasst)"
    parts = [anweisung, f"Anwesenheitsliste:\n{liste}"]
    if kontext:
        parts.append(kontext)
    if werte:
        parts.append(f"Gemessen jetzt:\n{werte}")
    if anlass:
        parts.append(f"Anlass:\n{anlass}")
    parts.append(f"Transkript:\n{transcript or '(keine Sprache erkannt)'}")
    return "\n\n".join(parts)


def schema(anwesend: list[Anwesend] = ()) -> dict:
    """The Lagebericht schema, with person names held to who is present.

    The list of people is capped at one entry per name: without stills the
    model was seen to list "Unbekannt" until the token cap cut the reply off
    (the Chronik of a 405 s replay, text only)."""
    document = Lagebericht.model_json_schema()
    names = [*(person.name for person in anwesend), UNBEKANNT]
    document["$defs"]["Person"]["properties"]["name"]["enum"] = names
    document["properties"]["personen"]["maxItems"] = len(names)
    return document


def _chat(prompt: str, frames: list[bytes], format: dict, model: str, num_predict: int):
    return chat(
        model=model,
        messages=[{"role": "user", "content": prompt, "images": list(frames)}],
        think=False,
        keep_alive=-1,
        format=format,
        options={
            "num_ctx": CONTEXT,
            "num_predict": num_predict,
            "temperature": TEMPERATURE,
            "repeat_penalty": REPEAT_PENALTY,
        },
    )


def analyse(frames: list[bytes], transcript: str = "", anwesend: list[Anwesend] = (),
            model=MODEL, num_predict=NUM_PREDICT, kontext: str = "",
            werte: str = "") -> Lagebericht:
    """Run one SITREP generation over the given stills, transcript, roster and
    the Chronik's context."""
    with llm.turn(llm.BERICHT):
        response = _chat(_prompt(ANWEISUNG, transcript, anwesend, kontext, werte),
                         frames, schema(anwesend), model, num_predict)
    return Lagebericht.model_validate_json(response.message.content)


def bericht(*, beginn: datetime, ende: datetime, frames: list[bytes],
            aeusserungen: list[Aeusserung], anwesend: list[Anwesend] = (),
            handlungen: list[Handlung] = (), kontext: str = "", werte: str = "",
            abschnitte: int = 0, laut: loudness.Calibration | None = None,
            model=MODEL, started: float | None = None) -> Sitrep:
    """The report the operator asked for, from the Chronik and the last seconds.

    `beginn` is where the Chronik the report reads begins and `ende` the
    moment it was asked for. `aeusserungen` are the lines given word for
    word, `handlungen` what the recogniser measured over them. Latency runs
    from `started` (time.monotonic), the moment of the request.
    """
    started = time.monotonic() if started is None else started
    generated = analyse(frames, protokoll(aeusserungen), anwesend, model=model,
                        kontext=kontext, werte=werte)
    woertlich = (sum(loudness.seconds(line.beginn, line.ende) for line in aeusserungen))
    return Sitrep(
        zeitfenster=Zeitfenster(beginn=beginn, ende=ende,
                                dauer_s=round((ende - beginn).total_seconds(), 1)),
        quelle=Quelle(bilder=len(frames), abschnitte=abschnitte,
                      woertlich_s=round(woertlich, 1)),
        gesagt=" ".join(line.text for line in aeusserungen).strip(),
        anwesend=list(anwesend),
        handlungen=list(handlungen),
        aeusserungen=list(aeusserungen),
        pegel=pegel(laut),
        latenz_s=round(time.monotonic() - started, 1),
        bericht=generated,
    )


def pegel(laut: loudness.Calibration | None) -> Pegel | None:
    """The session's loudness calibration as it stands."""
    if laut is None:
        return None
    return Pegel(kalibriert=laut.calibrated, endgueltig=laut.settled,
                 gehoert_s=round(laut.heard, 1),
                 normal_db=None if laut.mean is None else round(laut.mean, 1),
                 streuung_db=None if laut.spread is None else round(laut.spread, 1))


# The recommendation: whether to intervene, asked for when the live values
# raise the alarm (lage.py) or by the operator. It reads what a report reads
# and writes a fraction of it, so it arrives in about a second.

ANWEISUNG_EMPFEHLUNG = f"""{QUELLEN}

Aufgabe: beurteilen, ob eingeschritten werden muss. Der Anlass sagt, warum
gefragt wird.
- Lage: ein Satz, was jetzt geschieht.
- Szene: Relevanz, Eskalation und Gefahr jetzt, 0-10. Wiege den Anlass gegen
  den Verlauf: ein einzelner Ausreisser in ruhiger Lage wiegt weniger als
  eine Zuspitzung ueber mehrere Abschnitte.
- Empfehlung: nur wenn Eskalation oder Gefahr ueber {SCHWELLE} liegt, eine
  konkrete militaerische Massnahme, ein Satz. {MASSNAHMEN} Sonst leer."""

# Tokens for a recommendation: a sentence, three numbers and a measure.
EMPFEHLUNG_TOKENS = 250


class Urteil(BaseModel):
    """The model-generated part of a recommendation."""

    lage: str = Field(description="Ein Satz: was jetzt geschieht")
    szene: Szene
    empfehlung: str = Field(description=EMPFEHLUNG_FELD)

    @computed_field
    @property
    def einschreiten(self) -> bool:
        """By the rule, as for a Lagebericht."""
        return ueber_schwelle(self.szene)

    @model_validator(mode="after")
    def _empfehlung_nur_ueber_schwelle(self) -> Urteil:
        if not self.einschreiten:
            self.empfehlung = ""
        return self


class Empfehlung(BaseModel):
    """A recommendation: when and why it was asked for, and the model's verdict."""

    zeit: datetime
    anlass: str
    latenz_s: float
    urteil: Urteil


def empfehlen(*, anlass: str, frames: list[bytes], aeusserungen: list[Aeusserung],
              anwesend: list[Anwesend] = (), kontext: str = "", werte: str = "",
              model=MODEL, started: float | None = None) -> Empfehlung:
    """Whether to intervene now, and how, weighed against the Chronik."""
    started = time.monotonic() if started is None else started
    zeit = datetime.now()
    with llm.turn(llm.EMPFEHLUNG):
        response = _chat(_prompt(ANWEISUNG_EMPFEHLUNG, protokoll(aeusserungen), anwesend,
                                 kontext, werte, anlass),
                         frames, Urteil.model_json_schema(), model, EMPFEHLUNG_TOKENS)
    return Empfehlung(zeit=zeit, anlass=anlass, latenz_s=round(time.monotonic() - started, 1),
                      urteil=Urteil.model_validate_json(response.message.content))
