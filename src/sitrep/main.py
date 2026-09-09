"""Orest live SITREP: runs the capture and reporting loop, prints to console.

Entry point for the Realtime-SITREP of knowledge/components/02_processing.md.
Reports are printed as they arrive and appended to a JSON log; the camera feed
itself is handled separately and is not displayed here.

    python src/sitrep/main.py
    python src/sitrep/main.py --window 30 --interval 10 --audio-api WASAPI
"""

import argparse
import itertools
import sys

import report

# Label column width, sized to the longest field name.
_LABEL = 10

_RULE = "─"

# The rating categories from 02_processing.md, in the order they are shown.
_BEWERTUNGEN = ("verantwortungsvoll", "menschlich", "gefahr", "kollaborativ")

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
    """Break text into lines that fit the value column."""
    lines, current = [], ""
    for word in text.split():
        candidate = f"{current} {word}".strip()
        if len(candidate) <= width or not current:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _field(label: str, values: list[str], colour=None, use_colour=True) -> list[str]:
    """Render one labelled field, continuation lines indented under the value."""
    if not values:
        return []
    rendered = []
    for index, value in enumerate(values):
        name = label if index == 0 else ""
        painted = _paint(value, colour, use_colour) if colour else value
        rendered.append(f" {name:<{_LABEL}} {painted}")
    return rendered


def _bewertungen(person: dict, width: int, use_colour: bool) -> list[str]:
    """Pack the ratings into lines, never splitting a category from its score.

    Length is measured on the unpainted text, since colour codes do not occupy
    columns on screen.
    """
    lines, current, length = [], [], 0
    for name in _BEWERTUNGEN:
        text = f"{name} {person[name]}"
        separator = 3 if current else 0
        if current and length + separator + len(text) > width:
            lines.append(" · ".join(current))
            current, length = [], 0
            separator = 0
        colour = _gefahr_colour(person[name]) if name == "gefahr" else "dim"
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


def format_sitrep(document: dict, width=78, use_colour=True) -> str:
    """Render a SITREP document as a console block."""
    value_width = width - _LABEL - 2
    zeit = document["zeitfenster"]
    quelle = document["quelle"]

    beginn = zeit["beginn"][11:]
    ende = zeit["ende"][11:]
    heading = f" OREST · SITREP{' ' * 4}{beginn} – {ende}   ({zeit['dauer_s']}s)"

    lines = [
        _paint(_RULE * width, "dim", use_colour),
        _paint(heading, "accent", use_colour),
        _paint(_RULE * width, "dim", use_colour),
    ]

    lines += _field("LAGE", _wrap(document["lage"], value_width), use_colour=use_colour)

    personen = []
    for person in document["personen"]:
        personen.append(_paint(person["kennung"], "bold", use_colour))
        personen += [f"  {line}" for line in _wrap(person["taetigkeit"], value_width - 2)]
        if person["merkmale"]:
            personen += [_paint(f"  {line}", "dim", use_colour)
                         for line in _wrap(person["merkmale"], value_width - 2)]
        personen += [f"  {line}" for line in _bewertungen(person, value_width - 2, use_colour)]
    lines += _field("PERSONEN", personen, use_colour=use_colour)

    ereignisse = []
    for ereignis in document["ereignisse"]:
        wrapped = _wrap(ereignis, value_width - 2)
        ereignisse.append(f"· {wrapped[0]}")
        ereignisse += [f"  {line}" for line in wrapped[1:]]
    lines += _field("EREIGNIS", ereignisse, use_colour=use_colour)

    if document["gesagt"]:
        lines += _field("GESAGT", _wrap(f"“{document['gesagt']}”", value_width),
                        use_colour=use_colour)
    lines += _field("PROGNOSE", _wrap(document["prognose"], value_width),
                    use_colour=use_colour)
    lines += _field("EMPFEHLUNG", _wrap(document["empfehlung"], value_width),
                    use_colour=use_colour)

    footer = (f" {quelle['bilder']} Bilder · {quelle['ton_s']}s Ton · "
              f"Latenz {document['latenz_s']}s · "
              f"Vertrauen {document['vertrauen']}/5")
    lines.append(_paint(_RULE * width, "dim", use_colour))
    lines.append(_paint(footer, "dim", use_colour))
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--video", help="camera index or name fragment")
    parser.add_argument("--audio", help="microphone index or name fragment")
    parser.add_argument("--audio-api", help="host API filter, e.g. WASAPI, MME")
    parser.add_argument("--interval", type=float, default=10.0,
                        help="seconds between sampled frames (default: 10)")
    parser.add_argument("--window", type=float, default=30.0,
                        help="seconds per SITREP window (default: 30)")
    parser.add_argument("--windows", type=int, help="stop after this many reports")
    parser.add_argument("--model", default=report.MODEL)
    parser.add_argument("--log", default="data/sitrep",
                        help="directory for the SITREP log (text only)")
    parser.add_argument("--no-colour", action="store_true", help="plain output")
    args = parser.parse_args(argv)

    reports = report.run_live(
        video_spec=args.video,
        audio_spec=args.audio,
        hostapi=args.audio_api,
        interval=args.interval,
        window=args.window,
        model=args.model,
        log_dir=args.log,
    )

    try:
        for document in itertools.islice(reports, args.windows):
            print(format_sitrep(document, use_colour=not args.no_colour), flush=True)
    except KeyboardInterrupt:
        print("\ngestoppt")
    except (ValueError, RuntimeError) as error:
        print(error, file=sys.stderr)
        return 1
    finally:
        reports.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
