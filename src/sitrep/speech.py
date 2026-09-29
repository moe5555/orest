"""What was said, rated: Risiko and Menschlichkeit evidence per line of speech.

The Sentiment Analysis route under "Calculating Values" in
knowledge/components/02_processing.md. Each line of the transcript is
rated by the model, as evidence from -5 to +5, the scale of the action table
(action/sitrep_map.csv), so that speech and actions combine per person
(report.Sitrep.bewertungen).

Lines are taken at their word: as seriously meant, whether they might be acted
or quoted. A surveillance system does not know it is watching a play. Idioms
keep their ordinary meaning, so "Ich lach mich tot" is not a death.

The request carries text only, no frames. Lines are rated as soon as their
utterance ends (utterances.py), a few at a time, with the lines said just
before them as context that is not rated. It uses the report's model and
context size, so Ollama serves both from the one loaded model rather than
reloading it, and it goes to the model before any other request (llm.ZEILEN).

The schema puts each line's reason before its scores. The model writes JSON
in order, so it has stated what the line expresses before it scores it.

The prompt's examples come from speech_examples.csv beside this module. They
anchor the scale and stand in for a table of fixed trigger phrases: a line
that must score a certain way is added there.
"""

import csv
import sys
from pathlib import Path

from ollama import ResponseError, chat
from pydantic import BaseModel, Field, ValidationError

from . import llm, report

EXAMPLES = Path(__file__).with_name("speech_examples.csv")

EVIDENCE = 5

# Scoring should not vary between runs.
TEMPERATURE = 0.0

# Tokens per line: a sentence of reason and two numbers, with room to spare.
TOKENS_PER_LINE = 80

ANWEISUNG = """Du bist Orest, ein Ueberwachungssystem. Du bewertest, was in einem
Raum gesagt wurde, jede Aeusserung fuer sich und beim Wort genommen: als waere
sie ernst gemeint, auch wenn sie gespielt oder zitiert sein koennte.
Redewendungen haben dabei ihre uebliche Bedeutung.

Fuer jede nummerierte Aeusserung, in derselben Reihenfolge:
- begruendung: ein Satz, was die Aeusserung woertlich ausdrueckt.
- risiko -5 bis 5: wie sehr sie auf Gefahr durch den Sprecher hinweist:
  Drohung, Gewalt, Hass, duestere oder radikale Aussagen. Negativ nur, wenn
  sie eine angespannte Lage aktiv beruhigt; Freundlichkeit allein ist 0.
- menschlichkeit -5 bis 5: wie prosozial sie ist: Dank, Hilfe, Trost,
  Zuneigung, Positives. Negativ, wenn sie herabsetzt oder verachtet.
- 0, wenn nichts davon zutrifft, und fuer Bruchstuecke, Fuellwoerter oder
  Unverstaendliches.
Die Aeusserungen stehen im Zusammenhang: lies die anderen mit, auch was
zuvor gesagt wurde, bewerte aber jede nummerierte fuer sich.

Beispiele:
{beispiele}"""


class Einschaetzung(BaseModel):
    """The model's reading of one line. The reason comes first, as generated."""

    begruendung: str = Field(description="Ein Satz: was die Aeusserung woertlich ausdrueckt")
    risiko: int = Field(ge=-EVIDENCE, le=EVIDENCE)
    menschlichkeit: int = Field(ge=-EVIDENCE, le=EVIDENCE)


class Einschaetzungen(BaseModel):
    zeilen: list[Einschaetzung]


def examples(path: Path = EXAMPLES) -> str:
    """The example lines as the prompt lists them."""
    with open(path, encoding="utf-8", newline="") as file:
        rows = list(csv.DictReader(file))
    return "\n".join(f'"{row["satz"]}" risiko {row["risiko"]}, '
                     f'menschlichkeit {row["menschlichkeit"]}' for row in rows)


def prompt(lines: list[report.Aeusserung], vorher: list[report.Aeusserung] = ()) -> str:
    listed = "\n".join(f"{number}. {line.name or report.UNKLAR}: {line.text}"
                       for number, line in enumerate(lines, start=1))
    zuvor = ("\n\nZuvor gesagt, nicht bewerten:\n" + report.protokoll(list(vorher))
             if vorher else "")
    return f"{ANWEISUNG.format(beispiele=examples())}{zuvor}\n\nAeusserungen:\n{listed}"


def schema(count: int) -> dict:
    """The reply's schema, holding the model to exactly one reading per line."""
    document = Einschaetzungen.model_json_schema()
    document["properties"]["zeilen"].update(minItems=count, maxItems=count)
    return document


def rate(lines: list[report.Aeusserung], model: str = report.MODEL,
         vorher: list[report.Aeusserung] = ()) -> list[report.Aeusserung]:
    """The lines with each one's reason and evidence filled in.

    `vorher` are lines said just before, given as context and not rated. A
    reply that cannot be used leaves the lines unrated, so a failed rating
    costs the lines their evidence and not their place on screen.
    """
    if not lines:
        return lines
    try:
        with llm.turn(llm.ZEILEN):
            response = chat(
                model=model,
                messages=[{"role": "user", "content": prompt(lines, vorher)}],
                think=False,
                keep_alive=-1,
                format=schema(len(lines)),
                options={
                    # The report's own context size: a different one would
                    # make Ollama reload the model between the two requests.
                    "num_ctx": report.CONTEXT,
                    "num_predict": TOKENS_PER_LINE * len(lines) + 50,
                    "temperature": TEMPERATURE,
                },
            )
        readings = Einschaetzungen.model_validate_json(response.message.content).zeilen
    except (ValidationError, ResponseError) as error:
        print(f"speech rating skipped: {error!r}", file=sys.stderr)
        return lines
    if len(readings) != len(lines):
        print(f"speech rating skipped: {len(readings)} readings for {len(lines)} lines",
              file=sys.stderr)
        return lines
    return [line.model_copy(update={"begruendung": reading.begruendung,
                                    "risiko": reading.risiko,
                                    "menschlichkeit": reading.menschlichkeit})
            for line, reading in zip(lines, readings)]


# Lines with the scores they should get, none of them among the prompt's
# examples. `python -m sitrep.speech` rates them and counts the misses.
EVALUATION = Path(__file__).with_name("speech_eval.csv")

# A score counts as right within this distance of the expected one: the
# scale is coarse, and 3 against 4 for a threat is not a miss.
TOLERANCE = 1

# Lines per request in the evaluation, about what a 15 s window holds.
GROUP = 6


def main(argv=None) -> int:
    import argparse
    import time
    from datetime import datetime

    parser = argparse.ArgumentParser(description="Rate the evaluation lines and count misses.")
    parser.add_argument("--model", default=report.MODEL)
    parser.add_argument("--file", type=Path, default=EVALUATION)
    args = parser.parse_args(argv)

    with open(args.file, encoding="utf-8", newline="") as file:
        rows = list(csv.DictReader(file))
    now = datetime.now()
    misses, seconds = [], []
    for start in range(0, len(rows), GROUP):
        group = rows[start:start + GROUP]
        # Two alternating speakers, as in a scene.
        lines = [report.Aeusserung(name="AB"[index % 2], text=row["satz"], beginn=now, ende=now)
                 for index, row in enumerate(group)]
        began = time.monotonic()
        rated = rate(lines, model=args.model)
        seconds.append(time.monotonic() - began)
        for row, line in zip(group, rated):
            expected = (int(row["risiko"]), int(row["menschlichkeit"]))
            got = (line.risiko, line.menschlichkeit)
            wrong = None in got or any(abs(g - e) > TOLERANCE for g, e in zip(got, expected))
            misses += [row["art"]] if wrong else []
            print(f"{'MISS' if wrong else 'ok  '} {row['art']:14s} erwartet {expected[0]:+d}/{expected[1]:+d}"
                  f"  bekommen {got[0] if got[0] is None else f'{got[0]:+d}'}/"
                  f"{got[1] if got[1] is None else f'{got[1]:+d}'}  {row['satz']}  | {line.begruendung}")
    print(f"\n{len(rows) - len(misses)} of {len(rows)} within ±{TOLERANCE}; "
          f"misses by kind: {dict((kind, misses.count(kind)) for kind in dict.fromkeys(misses))}")
    ordered = sorted(seconds)
    print(f"{len(seconds)} requests of up to {GROUP} lines: median {ordered[len(ordered) // 2]:.1f} s, "
          f"slowest {ordered[-1]:.1f} s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
