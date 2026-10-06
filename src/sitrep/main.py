"""Apollon live SITREP: runs the live SITREP and prints it to the console.

Entry point for the Realtime-SITREP of knowledge/components/02_processing.md.
Prints each line as it is rated, the live values and the alarm, each stretch
the Chronik summarised, and each recommendation, as they happen. A full report
is made only when asked for:

    r    Lagebericht
    e    Empfehlung

On Windows the key alone does it; elsewhere the key and Enter. Nothing is
retained; the camera feed itself is handled separately and is not displayed
here.

    apollon-sitrep
    apollon-sitrep --window 30 --interval 10 --audio-api WASAPI
    apollon-sitrep --json

Equivalently, without the installed entry point:

    python -m sitrep.main
"""

import argparse
import pathlib
import sys
import textwrap
import threading

from . import chronik, cli, lage, loudness, report, session, transcribe

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

    heading = (f" APOLLON · SITREP{' ' * 4}{zeit.beginn:%H:%M:%S} – {zeit.ende:%H:%M:%S}"
               f"   ({zeit.dauer_s}s)")

    lines = [
        _paint(_RULE * width, "dim", use_colour),
        _paint(heading, "accent", use_colour),
        _paint(_RULE * width, "dim", use_colour),
    ]

    lines += _field("VERLAUF", _wrap(bericht.verlauf, value_width))
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

    footer = (f" {quelle.abschnitte} Abschnitte · {quelle.woertlich_s}s wörtlich · "
              f"{quelle.bilder} Bilder · Latenz {document.latenz_s}s{_pegel(document.pegel)}")
    lines.append(_paint(_RULE * width, "dim", use_colour))
    lines.append(_paint(footer, "dim", use_colour))
    return "\n".join(lines)


def format_zeile(line: report.Aeusserung, use_colour=True) -> str:
    """One line as it was said, on one console line."""
    lautstaerke = f" ({line.lautstaerke})" if line.lautstaerke else ""
    text = (f" {line.ende:%H:%M:%S}  {line.name or report.UNKLAR}{lautstaerke}: "
            f"“{line.text}”{_gewertet(line)}")
    colour = _risiko_colour(line.risiko) if line.risiko and line.risiko > 1 else "dim"
    return _paint(text, colour, use_colour)


def format_abschnitt(abschnitt: chronik.Abschnitt, use_colour=True) -> str:
    """One stretch the Chronik summarised."""
    zeit = f"{abschnitt.beginn:%H:%M:%S}–{abschnitt.ende:%H:%M:%S}"
    summary = abschnitt.zusammenfassung
    if summary is None:
        return _paint(f" ── CHRONIK {zeit}: ohne Zusammenfassung", "dim", use_colour)
    szene = summary.szene
    head = _paint(f" ── CHRONIK {zeit} · ", "accent", use_colour)
    werte = (_paint(f"eskalation {szene.eskalation}", _szene_colour(szene.eskalation), use_colour)
             + " · " + _paint(f"gefahr {szene.gefahr}", _szene_colour(szene.gefahr), use_colour)
             + f" · {summary.tendenz}")
    return f"{head}{werte}\n    {summary.zusammenfassung}"


def format_werte(stand: lage.Stand, use_colour=True) -> str:
    """The live values above 0 on one line, the alarm first when it is raised."""
    people = " · ".join(
        f"{name} " + " ".join(f"{rating} {wert.wert}" for rating, wert in werte.items() if wert.wert)
        for name, werte in stand.personen.items()
        if any(wert.wert for wert in werte.values())) or "alle 0"
    if stand.alarm.aktiv:
        wer = stand.alarm.wer or report.UNKLAR
        return (_paint(f" ALARM {wer} Risiko {stand.alarm.wert}: {stand.alarm.anlass}",
                       "red", use_colour)
                + _paint(f"   [{people}]", "dim", use_colour))
    return _paint(f" WERTE {people}", "dim", use_colour)


def format_empfehlung(empfehlung: report.Empfehlung, width=78, use_colour=True) -> str:
    """A recommendation as a short console block."""
    urteil = empfehlung.urteil
    szene = urteil.szene
    verdict = (_paint("EINSCHREITEN", "red", use_colour) if urteil.einschreiten
               else _paint("Kein Einschreiten", "dim", use_colour))
    lines = [f" EMPFEHLUNG {empfehlung.zeit:%H:%M:%S}  {verdict} · eskalation {szene.eskalation}"
             f" · gefahr {szene.gefahr} · Latenz {empfehlung.latenz_s}s"]
    lines += [f"    {line}" for line in _wrap(urteil.lage, width - 4)]
    lines += [f"    {_paint(line, 'red', use_colour)}"
              for line in _wrap(urteil.empfehlung, width - 4)]
    lines += [_paint(f"    {'Anlass: ' if index == 0 else '        '}{line}", "dim", use_colour)
              for index, line in enumerate(_wrap(empfehlung.anlass, width - 12))]
    return "\n".join(lines)


def _keys(live: session.Session):
    """Ask for a report on r and a recommendation on e, typed in the console."""
    def press(key: str):
        key = key.strip().lower()
        if key == "r" and not live.bericht():
            print(" Bericht läuft; ein weiterer folgt danach.", flush=True)
        elif key == "e" and not live.empfehlung():
            print(" Empfehlung läuft; eine weitere folgt danach.", flush=True)

    def loop():
        try:
            import msvcrt
        except ImportError:
            for typed in sys.stdin:
                press(typed)
            return
        while True:
            press(msvcrt.getwch())

    threading.Thread(target=loop, daemon=True).start()


class Konsole:
    """What the console prints for each of the run's events.

    The live values are printed only when what they show changed: they are
    announced whenever any whole number changes, including a person newly
    seen at 0, which would otherwise fill the console.
    """

    def __init__(self, use_colour=True, as_json=False):
        self.use_colour = use_colour
        self.as_json = as_json
        self._werte = None

    def text(self, event) -> str | None:
        if isinstance(event, session.Werte):
            shown = format_werte(event.stand, use_colour=False)
            if shown == self._werte:
                return None
            self._werte = shown
        return format_event(event, self.use_colour, self.as_json)


def format_event(event, use_colour=True, as_json=False) -> str | None:
    """What the console prints for one of the run's events, or None.

    A line is printed when it is transcribed, and again once rated only if
    its rating found something."""
    if isinstance(event, session.Zeilen):
        lines = [line for line in event.zeilen
                 if not event.bewertet or line.risiko or line.menschlichkeit]
        return "\n".join(format_zeile(line, use_colour) for line in lines) or None
    if isinstance(event, session.Werte):
        return format_werte(event.stand, use_colour)
    if isinstance(event, session.Ton):
        if event.stumm:
            return _paint(f" KEIN TON von {event.quelle} seit {session.STUMM:g} s: ohne Ton "
                          "keine Zeilen. Tonquelle prüfen (--audio, --audio-ndi).", "red", use_colour)
        return _paint(f" Ton von {event.quelle} wieder da.", "dim", use_colour)
    if isinstance(event, session.NeuerAbschnitt):
        return format_abschnitt(event.abschnitt, use_colour)
    if isinstance(event, session.Angefordert):
        was = "Bericht" if event.was == "bericht" else "Empfehlung"
        return _paint(f" {was} wird erstellt …", "dim", use_colour)
    if isinstance(event, session.NeuerBericht):
        return (event.sitrep.model_dump_json(indent=2) if as_json
                else format_sitrep(event.sitrep, use_colour=use_colour))
    if isinstance(event, session.NeueEmpfehlung):
        return format_empfehlung(event.empfehlung, use_colour=use_colour)
    if isinstance(event, session.Fehlgeschlagen):
        return _paint(f" {event.was} fehlgeschlagen: {event.fehler}", "red", use_colour)
    return None


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
    parser.add_argument("--no-auto-empfehlung", action="store_true",
                        help="make a recommendation only when asked for (e), not "
                             "whenever the live values raise the alarm")
    parser.add_argument("--json", action="store_true",
                        help="print a report as raw JSON instead of the console block")
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
    print("r: Lagebericht · e: Empfehlung · Ctrl+C: beenden", flush=True)
    _keys(live)
    konsole = Konsole(not args.no_colour, args.json)

    try:
        with live:
            for event in live.events():
                text = konsole.text(event)
                if text:
                    print(text, flush=True)
    except KeyboardInterrupt:
        print()
    except (ValueError, RuntimeError) as error:
        print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
