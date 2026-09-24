"""Orest live SITREP: runs the capture and reporting loop, prints to console.

Entry point for the Realtime-SITREP of knowledge/components/02_processing.md.
Reports are printed as they arrive and not retained; the camera feed itself is
handled separately and is not displayed here.

    orest-sitrep
    orest-sitrep --window 30 --interval 10 --audio-api WASAPI
    orest-sitrep --json

Equivalently, without the installed entry point:

    python -m sitrep.main
"""

import argparse
import itertools
import pathlib
import sys
import textwrap

from . import cli, devices, report, session

# Label column width, sized to the longest field name.
_LABEL = 10

_RULE = "─"

ANSI = {
    "reset": "\033[0m",
    "dim": "\033[2m",
    "bold": "\033[1m",
    "accent": "\033[38;5;39m",
    "amber": "\033[38;5;214m",
    "red": "\033[38;5;203m",
}


def _paint(text: str, colour: str, enabled: bool) -> str:
    return f"{ANSI[colour]}{text}{ANSI['reset']}" if enabled else text


def _wrap(text: str, width: int) -> list[str]:
    """Break text into lines that fit the value column.

    Runs of whitespace are collapsed first, so a model reply containing
    newlines lays out as a paragraph rather than keeping its own line breaks.
    """
    return textwrap.wrap(" ".join(text.split()), width, break_long_words=False)


def _field(label: str, values: list[str]) -> list[str]:
    """Render one labelled field, continuation lines indented under the value.

    Values arrive already painted, so no colour is applied here.
    """
    if not values:
        return []
    return [f" {(label if index == 0 else ''):<{_LABEL}} {value}"
            for index, value in enumerate(values)]


def _bewertungen(person: report.Person, width: int, use_colour: bool) -> list[str]:
    """Pack the ratings into lines, never splitting a category from its score.

    Length is measured on the unpainted text, since colour codes do not occupy
    columns on screen.
    """
    lines, current, length = [], [], 0
    for name in report.BEWERTUNGEN:
        score = getattr(person, name)
        text = f"{name} {score}"
        separator = 3 if current else 0
        if current and length + separator + len(text) > width:
            lines.append(" · ".join(current))
            current, length = [], 0
            separator = 0
        colour = _gefahr_colour(score) if name == "gefahr" else "dim"
        current.append(_paint(text, colour, use_colour))
        length += separator + len(text)
    if current:
        lines.append(" · ".join(current))
    return lines


def _gefahr_colour(level: int) -> str:
    if level >= 4:
        return "red"
    if level >= 2:
        return "amber"
    return "dim"


def format_sitrep(document: report.Sitrep, width=78, use_colour=True) -> str:
    """Render a SITREP as a console block."""
    value_width = width - _LABEL - 2
    zeit = document.zeitfenster
    quelle = document.quelle
    bericht = document.bericht

    heading = (f" OREST · SITREP{' ' * 4}{zeit.beginn:%H:%M:%S} – {zeit.ende:%H:%M:%S}"
               f"   ({zeit.dauer_s}s)")

    lines = [
        _paint(_RULE * width, "dim", use_colour),
        _paint(heading, "accent", use_colour),
        _paint(_RULE * width, "dim", use_colour),
    ]

    lines += _field("LAGE", _wrap(bericht.lage, value_width))

    personen = []
    for person in bericht.personen:
        personen.append(_paint(person.kennung, "bold", use_colour))
        personen += [f"  {line}" for line in _wrap(person.taetigkeit, value_width - 2)]
        if person.merkmale:
            personen += [_paint(f"  {line}", "dim", use_colour)
                         for line in _wrap(person.merkmale, value_width - 2)]
        personen += [f"  {line}" for line in _bewertungen(person, value_width - 2, use_colour)]
    lines += _field("PERSONEN", personen)

    ereignisse = []
    for ereignis in bericht.ereignisse:
        wrapped = _wrap(ereignis, value_width - 2)
        ereignisse.append(f"· {wrapped[0]}")
        ereignisse += [f"  {line}" for line in wrapped[1:]]
    lines += _field("EREIGNIS", ereignisse)

    if document.gesagt:
        lines += _field("GESAGT", _wrap(f"“{document.gesagt}”", value_width))
    lines += _field("PROGNOSE", _wrap(bericht.prognose, value_width))
    lines += _field("EMPFEHLUNG", _wrap(bericht.empfehlung, value_width))

    footer = (f" {quelle.bilder} Bilder · {quelle.ton_s}s Ton · "
              f"Latenz {document.latenz_s}s · "
              f"Vertrauen {bericht.vertrauen}/5")
    lines.append(_paint(_RULE * width, "dim", use_colour))
    lines.append(_paint(footer, "dim", use_colour))
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__.splitlines()[0],
        parents=[cli.sources(), cli.timing(), cli.resolution(), cli.touchdesigner()],
    )
    parser.add_argument("--model", default=report.MODEL)
    parser.add_argument("--cast", type=pathlib.Path,
                        help="folder of enrolment images; names the people on stage")
    parser.add_argument("--json", action="store_true",
                        help="print raw report JSON instead of the console block")
    parser.add_argument("--no-colour", action="store_true", help="plain output")
    args = parser.parse_args(argv)

    try:
        video, audio = devices.resolve(args.video, args.audio, args.audio_api)
        live = session.Session(video, audio, session.Options.from_args(args))
    except (ValueError, RuntimeError) as error:
        print(error, file=sys.stderr)
        return 1

    print(live.describe())
    for path in live.missing_enrolment:
        print(f"no face found in {path}", file=sys.stderr)

    try:
        with live:
            for document in itertools.islice(live.reports(), args.windows):
                if args.json:
                    print(document.model_dump_json(indent=2))
                else:
                    print(format_sitrep(document, use_colour=not args.no_colour),
                          flush=True)
    except KeyboardInterrupt:
        print()
    except (ValueError, RuntimeError) as error:
        print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
