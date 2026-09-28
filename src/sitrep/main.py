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

from . import cli, loudness, report, session, transcribe

# Label column width, sized to the longest field name.
_LABEL = 12

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


def _bewertungen(ratings: dict[str, int | None], width: int, use_colour: bool) -> list[str]:
    """Pack the ratings into lines, never splitting a category from its score.

    A rating that was not measured shows as a dash. Length is measured on the
    unpainted text, since colour codes do not occupy columns on screen.
    """
    lines, current, length = [], [], 0
    for name, score in ratings.items():
        text = f"{name} {'–' if score is None else score}"
        separator = 3 if current else 0
        if current and length + separator + len(text) > width:
            lines.append(" · ".join(current))
            current, length = [], 0
            separator = 0
        colour = _risiko_colour(score) if name == "risiko" and score is not None else "dim"
        current.append(_paint(text, colour, use_colour))
        length += separator + len(text)
    if current:
        lines.append(" · ".join(current))
    return lines


def _gewertet(aeusserung: report.Aeusserung) -> str:
    """A line's non-zero evidence, e.g. " [risiko +3 ×1.5, menschlichkeit -3]"."""
    values = [f"{rating} {getattr(aeusserung, rating):+d}" for rating in report.GEMESSEN
              if getattr(aeusserung, rating)]
    if values and aeusserung.risiko and aeusserung.verstaerkung > 1.0:
        values[0] += f" ×{aeusserung.verstaerkung:.1f}"
    return f" [{', '.join(values)}]" if values else ""


def _pegel(pegel: report.Pegel | None) -> str:
    """The loudness calibration for the footer."""
    if pegel is None:
        return ""
    if not pegel.kalibriert:
        return f" · Pegel kalibriert {pegel.gehoert_s:.0f}/{loudness.PROVISIONAL:.0f}s"
    learning = "" if pegel.endgueltig else f", lernt {pegel.gehoert_s:.0f}/{loudness.CALIBRATION:.0f}s"
    return f" · Pegel normal {pegel.normal_db:.0f} dBFS ±{pegel.streuung_db:.0f}{learning}"


def _anlass(document: report.Sitrep, name: str, width: int) -> list[str]:
    """What set each measured rating above 0: an action, or a line."""
    causes = [f"{rating}: {document.bewertung(name, rating)[1]}" for rating in report.GEMESSEN
              if document.bewertung(name, rating)[1]]
    return _wrap(" · ".join(causes), width) if causes else []


def _risiko_colour(level: int) -> str:
    if level >= 4:
        return "red"
    if level >= 2:
        return "amber"
    return "dim"


def _szene_colour(level: int) -> str:
    """Red once a scene rating calls for intervention, amber on the way there."""
    if level > report.SCHWELLE:
        return "red"
    if level >= report.SCHWELLE - 2:
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

    lines += _field("BESCHREIBUNG", _wrap(bericht.beschreibung, value_width))

    personen = []
    for person in bericht.personen:
        # A recognised name stands alone; a guessed one is marked as such.
        name = _paint(person.name, "bold", use_colour)
        if person.name != report.UNBEKANNT and not document.erkannt(person.name):
            name += _paint(" (vermutet)", "dim", use_colour)
        personen.append(name)
        personen += [f"  {line}" for line in _wrap(person.beschreibung, value_width - 2)]
        personen += [f"  {line}" for line in _bewertungen(
            document.bewertungen(person), value_width - 2, use_colour)]
        personen += [f"  {_paint(line, 'dim', use_colour)}"
                     for line in _anlass(document, person.name, value_width - 2)]
    lines += _field("PERSONEN", personen)

    szene = bericht.szene
    lines += _field("SZENE", [" · ".join([
        _paint(f"relevanz {szene.relevanz}", "dim", use_colour),
        _paint(f"eskalation {szene.eskalation}", _szene_colour(szene.eskalation), use_colour),
        _paint(f"gefahr {szene.gefahr}", _szene_colour(szene.gefahr), use_colour),
    ])])

    if document.aeusserungen:
        gesagt = []
        for aeusserung in document.aeusserungen:
            gesagt += _wrap(f"{aeusserung.name or report.UNKLAR}: “{aeusserung.text}”"
                            f"{_gewertet(aeusserung)}", value_width)
        lines += _field("GESAGT", gesagt)
    elif document.gesagt:
        lines += _field("GESAGT", _wrap(f"“{document.gesagt}”", value_width))

    prognose = []
    for verlauf in bericht.prognose:
        wrapped = _wrap(verlauf.verlauf, value_width - 6)
        prognose.append(f"{verlauf.wahrscheinlichkeit:>3} % {wrapped[0] if wrapped else ''}")
        prognose += [f"      {line}" for line in wrapped[1:]]
    lines += _field("PROGNOSE", prognose)

    if bericht.einschreiten:
        lines += _field("EMPFEHLUNG", [_paint("EINSCHREITEN", "red", use_colour)]
                        + _wrap(bericht.empfehlung, value_width))
    else:
        lines += _field("EMPFEHLUNG", [_paint("Kein Einschreiten", "dim", use_colour)])

    footer = (f" {quelle.bilder} Bilder · {quelle.ton_s}s Ton · "
              f"Latenz {document.latenz_s}s{_pegel(document.pegel)}")
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
                        help="folder of enrolment images; recognises the cast by "
                             "name, everyone else is given a guessed name")
    parser.add_argument("--audio-ndi", metavar="SOURCE",
                        help="take the sound from this NDI source instead of a "
                             'microphone, e.g. "VSH-ARLT-5090 (OBS PGM)"')
    parser.add_argument("--language", default=transcribe.LANGUAGE,
                        help=f"language spoken, as a Whisper code, e.g. en for the "
                             f"test corpus (default: {transcribe.LANGUAGE})")
    parser.add_argument("--no-actions", action="store_true",
                        help="don't run the action recogniser; risiko and "
                             "menschlichkeit are then not measured")
    parser.add_argument("--json", action="store_true",
                        help="print raw report JSON instead of the console block")
    parser.add_argument("--no-colour", action="store_true", help="plain output")
    args = parser.parse_args(argv)

    try:
        video, audio = session.resolve_sources(args)
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
