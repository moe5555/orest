"""The Chronik: a running summary of the scene, kept in the background.

A report is made only when the operator asks for one (report.py), and it
should say what happened over the last minutes, not only in the last
seconds. Summarising minutes of footage at that moment would take too long,
so the summary is written as the scene goes on, in three layers:

1. Lines. Every rated line (utterances.py), word for word.
2. Abschnitte. Every `laenge` seconds (the --window of the command line) the
   stretch since the last cut becomes an Abschnitt. Its measured part is
   what the stretch held: the lines, the action ratings (actions.py), who was
   present, how many stills. The model reads it with the Chronik so far and
   two stills and writes one or two sentences, the scene's Eskalation and
   Gefahr, and whether the scene is sharpening, steady or easing
   (Zusammenfassung). This is the trajectory the report reads.
3. Rueckblick. Abschnitte older than DETAIL seconds are folded, FALTEN at a
   time, into one short chronological Rueckblick, and their lines deleted.
   The context a report reads therefore stays the same size however long the
   run is. The scene's Eskalation and Gefahr per Abschnitt are kept as
   numbers for the whole run (Kurve), so the shape of the scene outlives the
   words.

This is the pattern of an incident log with periodic consolidation: detail
for the recent past, a digest for the rest. The summaries go to the model
last of all Apollon's requests (llm.CHRONIK), so they never delay a line's
rating or a report asked for; if one fails, the Abschnitt keeps its lines and
the report reads those instead.

Nothing is written to disk, and closing the run deletes all of it.
"""

import sys
import threading
import time
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Literal

from ollama import ResponseError, chat
from pydantic import BaseModel, Field, ValidationError

from . import llm, report

# Seconds of Abschnitte kept in detail before they are folded into the
# Rueckblick: the last five minutes are what an operator asking "what just
# happened" means.
DETAIL = 300.0

# Abschnitte folded into the Rueckblick at once: one request per FALTEN
# Abschnitte rather than one for each.
FALTEN = 4

# Sentences a Rueckblick may have.
RUECKBLICK_SAETZE = 6

# Stills per Abschnitt. The Abschnitt's measured part says what was said and
# done; the stills show where people are and what the transcript cannot.
BILDER = 2

# Abschnitte whose summaries are given as context to the next one.
ZUSAMMENHANG = 3

# Points of the Kurve given to a prompt, most recent last.
KURVE_PROMPT = 20

# Tokens for a summary and for a Rueckblick.
ABSCHNITT_TOKENS = 300
RUECKBLICK_TOKENS = 400

ANWEISUNG = """Du bist Apollon, ein Ueberwachungssystem, und fuehrst das
laufende Protokoll einer Szene.
Du erhaeltst das Protokoll bisher, Standbilder aus dem neuesten Abschnitt,
was dort an Handlungen gemessen wurde, und sein Transkript. In den Bildern
steht der Name jeder erfassten Person ueber ihrem Gesicht. Vor jeder
Aeusserung steht, wer sie gesagt hat, "(unklar)" wenn das nicht bestimmt ist,
und "(laut)" oder "(geschrien)", wenn sie lauter war als sonst im Raum.

Fasse den neuesten Abschnitt zusammen.
- Zusammenfassung: ein bis zwei Saetze, was geschah, wer was tat oder sagte.
  Woertliche Zitate nur, wenn sie entscheidend sind.
- Szene: Relevanz, Eskalation und Gefahr in diesem Abschnitt, 0-10.
- Tendenz gegenueber dem Protokoll bisher: zuspitzend, gleichbleibend oder
  beruhigend.
- Ausschliesslich, was belegt ist. Knapp und nominal, Behoerdenstil."""

ANWEISUNG_RUECKBLICK = f"""Du bist Apollon, ein Ueberwachungssystem, und fuehrst das
laufende Protokoll einer Szene. Verdichte den bisherigen Rueckblick und die
folgenden Abschnitte zu einem neuen Rueckblick.
- Chronologisch, hoechstens {RUECKBLICK_SAETZE} Saetze.
- Erhalten bleiben: Wendepunkte, wer eskalierte oder beruhigte, entscheidende
  Aeusserungen, und wie sich Eskalation und Gefahr entwickelt haben.
- Nichts hinzufuegen, was nicht im Protokoll steht. Knapp, Behoerdenstil."""


class Zusammenfassung(BaseModel):
    """The model's summary of one Abschnitt."""

    zusammenfassung: str = Field(description="Ein bis zwei Saetze: was geschah, wer was tat")
    szene: report.Szene
    tendenz: Literal["zuspitzend", "gleichbleibend", "beruhigend"]


class Rueckblick(BaseModel):
    rueckblick: str = Field(description="Der Verlauf bisher, chronologisch, knapp")


class Abschnitt(BaseModel):
    """One stretch of the scene: what was measured, and the model's summary of it."""

    beginn: datetime
    ende: datetime
    anwesend: list[report.Anwesend] = []
    handlungen: list[report.Handlung] = []
    aeusserungen: list[report.Aeusserung] = []
    bilder: int = 0
    # None when the model could not summarise it; the report then reads its lines.
    zusammenfassung: Zusammenfassung | None = None
    latenz_s: float | None = None

    def zeile(self) -> str:
        """The Abschnitt as one entry of the Chronik a prompt reads."""
        zeit = f"{self.beginn:%H:%M:%S}-{self.ende:%H:%M:%S}"
        if self.zusammenfassung is None:
            gesagt = report.protokoll(self.aeusserungen).replace("\n", " / ")
            return f"- {zeit} (ohne Zusammenfassung): {gesagt or 'nichts gesagt'}"
        szene = self.zusammenfassung.szene
        return (f"- {zeit} · Eskalation {szene.eskalation} · Gefahr {szene.gefahr} · "
                f"{self.zusammenfassung.tendenz}: {self.zusammenfassung.zusammenfassung}")


class Punkt(BaseModel):
    """The scene's ratings at the end of one Abschnitt, kept for the whole run."""

    ende: datetime
    eskalation: int
    gefahr: int


# Who was seen during a stretch (presence tracker's roster); ratings over a
# stretch (actions.ActionRatings.between); stills of a stretch
# (capture.FrameRing.between).
Roster = Callable[[datetime, datetime], list]
Handlungen = Callable[[datetime, datetime], list[report.Handlung]]
Bilder = Callable[[datetime, datetime, int], list[bytes]]


class Chronik:
    """The scene's lines, Abschnitte and Rueckblick for one run.

    `add` takes lines as they are rated; `schneiden` closes an Abschnitt and
    has it summarised, which `start` does every `laenge` seconds on a thread
    of its own; `kontext` is what a report or recommendation reads.
    """

    def __init__(self, *, laenge: float, model: str = report.MODEL,
                 roster: Roster | None = None, handlungen: Handlungen | None = None,
                 bilder: Bilder | None = None,
                 on_abschnitt: Callable[[Abschnitt], None] | None = None,
                 began: datetime | None = None):
        self.laenge = laenge
        self._model = model
        self._roster = roster
        self._handlungen = handlungen
        self._bilder = bilder
        self._on_abschnitt = on_abschnitt
        self._lock = threading.Lock()
        self._zeilen: list[report.Aeusserung] = []
        self.abschnitte: list[Abschnitt] = []
        self.rueckblick = ""
        # The stretch the Rueckblick covers.
        self.rueckblick_von: datetime | None = None
        self.rueckblick_bis: datetime | None = None
        self.kurve: list[Punkt] = []
        self.began = began or datetime.now()
        self._cut = self.began
        self._stop = threading.Event()
        self._thread = None

    # Lines ------------------------------------------------------------------

    def add(self, lines: list[report.Aeusserung]):
        """Keep lines; a line already kept, now rated, takes its place."""
        with self._lock:
            kept = {(line.beginn, line.text): index for index, line in enumerate(self._zeilen)}
            for line in lines:
                index = kept.get((line.beginn, line.text))
                if index is None:
                    self._zeilen.append(line)
                else:
                    self._zeilen[index] = line

    def zeilen_seit(self, since: datetime) -> list[report.Aeusserung]:
        """The lines kept that ended after `since`."""
        with self._lock:
            return [line for line in self._zeilen if line.ende > since]

    @property
    def cut(self) -> datetime:
        """Where the Abschnitt under way began."""
        with self._lock:
            return self._cut

    # Abschnitte -------------------------------------------------------------

    def start(self) -> "Chronik":
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        return self

    def _loop(self):
        while not self._stop.wait(max(0.0, (self.cut + timedelta(seconds=self.laenge)
                                            - datetime.now()).total_seconds())):
            try:
                self.schneiden()
            except Exception as error:
                print(f"chronik: {error!r}", file=sys.stderr)

    def schneiden(self, now: datetime | None = None) -> Abschnitt:
        """Close the Abschnitt under way, summarise it, and fold old ones."""
        now = now or datetime.now()
        with self._lock:
            beginn, self._cut = self._cut, now
            lines = [line for line in self._zeilen if beginn < line.ende <= now]
        abschnitt = Abschnitt(
            beginn=beginn, ende=now,
            anwesend=[report.Anwesend(name=person.label, erkannt=person.known)
                      for person in (self._roster(beginn, now) if self._roster else [])],
            handlungen=self._handlungen(beginn, now) if self._handlungen else [],
            aeusserungen=lines)
        frames = self._bilder(beginn, now, BILDER) if self._bilder else []
        abschnitt = abschnitt.model_copy(update={"bilder": len(frames)})

        started = time.monotonic()
        try:
            summary = self._zusammenfassen(abschnitt, frames)
        except (ValidationError, ResponseError) as error:
            print(f"chronik: Abschnitt {beginn:%H:%M:%S} ohne Zusammenfassung: {error!r}",
                  file=sys.stderr)
            summary = None
        abschnitt = abschnitt.model_copy(update={
            "zusammenfassung": summary, "latenz_s": round(time.monotonic() - started, 1)})

        with self._lock:
            self.abschnitte.append(abschnitt)
            if summary is not None:
                self.kurve.append(Punkt(ende=now, eskalation=summary.szene.eskalation,
                                        gefahr=summary.szene.gefahr))
        if self._on_abschnitt:
            self._on_abschnitt(abschnitt)
        self._falten(now)
        return abschnitt

    def _zusammenfassen(self, abschnitt: Abschnitt, frames: list[bytes]) -> Zusammenfassung:
        liste = "\n".join(f"- {person.name}" for person in abschnitt.anwesend) or "(niemand erfasst)"
        gemessen = "\n".join(
            f"- {handlung.name}: risiko {handlung.risiko}"
            f"{f' ({handlung.anlass_risiko})' if handlung.anlass_risiko else ''}, "
            f"menschlichkeit {handlung.menschlichkeit}"
            f"{f' ({handlung.anlass_menschlichkeit})' if handlung.anlass_menschlichkeit else ''}"
            for handlung in abschnitt.handlungen) or "(nichts gemessen)"
        prompt = "\n\n".join([
            ANWEISUNG,
            f"Protokoll bisher:\n{self.kontext(ZUSAMMENHANG) or '(Beginn der Szene)'}",
            f"Neuester Abschnitt {abschnitt.beginn:%H:%M:%S}-{abschnitt.ende:%H:%M:%S}",
            f"Anwesend:\n{liste}",
            f"Handlungen:\n{gemessen}",
            f"Transkript:\n{report.protokoll(abschnitt.aeusserungen) or '(nichts gesagt)'}",
        ])
        with llm.turn(llm.CHRONIK):
            response = chat(
                model=self._model,
                messages=[{"role": "user", "content": prompt, "images": frames}],
                think=False, keep_alive=-1, format=Zusammenfassung.model_json_schema(),
                options={"num_ctx": report.CONTEXT, "num_predict": ABSCHNITT_TOKENS,
                         "temperature": report.TEMPERATURE,
                         "repeat_penalty": report.REPEAT_PENALTY})
        return Zusammenfassung.model_validate_json(response.message.content)

    # Rueckblick -------------------------------------------------------------

    def _falten(self, now: datetime):
        """Fold the Abschnitte older than DETAIL into the Rueckblick, FALTEN at a time."""
        with self._lock:
            alt = [abschnitt for abschnitt in self.abschnitte
                   if (now - abschnitt.ende).total_seconds() > DETAIL]
            if len(alt) < FALTEN:
                return
            alt = alt[:FALTEN]
            bisher = self.rueckblick
        prompt = "\n\n".join([
            ANWEISUNG_RUECKBLICK,
            f"Bisheriger Rueckblick:\n{bisher or '(keiner)'}",
            "Abschnitte:\n" + "\n".join(abschnitt.zeile() for abschnitt in alt),
        ])
        try:
            with llm.turn(llm.CHRONIK):
                response = chat(
                    model=self._model, messages=[{"role": "user", "content": prompt}],
                    think=False, keep_alive=-1, format=Rueckblick.model_json_schema(),
                    options={"num_ctx": report.CONTEXT, "num_predict": RUECKBLICK_TOKENS,
                             "temperature": report.TEMPERATURE,
                             "repeat_penalty": report.REPEAT_PENALTY})
            neu = Rueckblick.model_validate_json(response.message.content).rueckblick
        except (ValidationError, ResponseError) as error:
            # The Abschnitte stay in detail and are folded with the next ones.
            print(f"chronik: Rueckblick nicht verdichtet: {error!r}", file=sys.stderr)
            return
        bis = alt[-1].ende
        with self._lock:
            self.rueckblick = neu
            self.rueckblick_von = self.rueckblick_von or alt[0].beginn
            self.rueckblick_bis = bis
            self.abschnitte = [abschnitt for abschnitt in self.abschnitte if abschnitt.ende > bis]
            # The words of folded Abschnitte are not kept.
            self._zeilen = [line for line in self._zeilen if line.ende > bis]

    # Reading ----------------------------------------------------------------

    def kontext(self, abschnitte: int | None = None) -> str:
        """The Chronik as a prompt reads it: Rueckblick, then the Abschnitte
        in detail (the last `abschnitte` of them, or all), then the Kurve."""
        with self._lock:
            rueckblick, von, bis = self.rueckblick, self.rueckblick_von, self.rueckblick_bis
            detail = list(self.abschnitte)
            kurve = list(self.kurve)
        if abschnitte is not None:
            detail = detail[-abschnitte:] if abschnitte else []
        parts = []
        if rueckblick:
            parts.append(f"Rueckblick {von:%H:%M:%S}-{bis:%H:%M:%S}:\n{rueckblick}")
        if detail:
            parts.append("Abschnitte:\n" + "\n".join(abschnitt.zeile() for abschnitt in detail))
        if len(kurve) > 1:
            punkte = kurve[-KURVE_PROMPT:]
            parts.append(f"Eskalation je Abschnitt seit {punkte[0].ende:%H:%M:%S}: "
                         + " ".join(str(punkt.eskalation) for punkt in punkte))
        return "\n\n".join(parts)

    def woertlich_seit(self) -> datetime:
        """Where the lines a report is given word for word begin: the start
        of the last summarised Abschnitt, so they overlap its summary."""
        with self._lock:
            return self.abschnitte[-1].beginn if self.abschnitte else self._cut

    def von(self) -> datetime:
        """Where the Chronik begins: the Rueckblick, the first Abschnitt, or the run."""
        with self._lock:
            if self.rueckblick_von:
                return self.rueckblick_von
            return self.abschnitte[0].beginn if self.abschnitte else self._cut

    def clear(self):
        """Delete everything kept."""
        with self._lock:
            self._zeilen = []
            self.abschnitte = []
            self.rueckblick = ""
            self.rueckblick_von = self.rueckblick_bis = None
            self.kurve = []

    def close(self):
        self._stop.set()
        if self._thread:
            # A summary under way finishes; the thread is a daemon either way.
            self._thread.join(timeout=0.5)
