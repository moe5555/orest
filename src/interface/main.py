"""Serve the operator interface on the loopback interface.

    apollon-ui
    apollon-ui --video "OBS Virtual Camera" --model gemma4:26b
    apollon-ui --cast data/cast --send-td --send-ndi
    uv run apollon-ui --video "OBS Virtual Camera" --model gemma4:26b --window 15 --interval 5

Takes the same camera, microphone, window and output options as apollon-sitrep;
they apply to every live SITREP started from the page. The camera, sound
source and cast are chosen on the operator page and remembered
(interface/sources.py); --video, --audio, --audio-api, --audio-ndi and --cast
preselect them. Devices are
resolved when a run starts, not here, so a camera plugged in after the server
started is found.

Binds 127.0.0.1 by default. The page shows unreleased footage of identifiable
people, as the WISE server does (smartsearch/config.py, HOST).
"""

import argparse
import os
import pathlib
import sys

import uvicorn

from sitrep import cli, report, session, transcribe

from .app import create_app
from .live import LiveSitrep
from .sources import SOURCES_FILE, Selection, Sources

HOST = os.environ.get("APOLLON_UI_HOST", "127.0.0.1")
PORT = int(os.environ.get("APOLLON_UI_PORT", "9680"))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__.splitlines()[0],
        parents=[cli.sources(), cli.timing(), cli.resolution(), cli.touchdesigner()],
    )
    parser.add_argument("--model", default=report.MODEL)
    parser.add_argument("--cast", type=pathlib.Path,
                        help="folder of enrolment images; recognises the cast by "
                             "name, everyone else is reported as Unbekannt")
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
                        help="make a recommendation only when asked for (key E), "
                             "not whenever the live values raise the alarm")
    parser.add_argument("--host", default=HOST, help=f"address to bind (default: {HOST})")
    parser.add_argument("--port", type=int, default=PORT,
                        help=f"port to serve on (default: {PORT})")
    args = parser.parse_args(argv)

    selection = Selection.load(SOURCES_FILE, Sources.from_args(args))

    def open_session() -> session.Session:
        chosen = selection.sources
        video, audio = session.resolve_sources(chosen)
        options = session.Options.from_args(args).model_copy(
            update={"cast": pathlib.Path(chosen.cast) if chosen.cast else None})
        run = session.Session(video, audio, options)
        for path in run.missing_enrolment:
            print(f"no face found in {path}", file=sys.stderr)
        return run

    live = LiveSitrep(open_session)
    print(f"Apollon operator page: http://{args.host}:{args.port}/", flush=True)
    try:
        uvicorn.run(create_app(live, selection), host=args.host, port=args.port,
                    log_level="warning", timeout_graceful_shutdown=2)
    finally:
        live.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
