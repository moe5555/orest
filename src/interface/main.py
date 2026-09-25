"""Serve the operator interface on the loopback interface.

    orest-ui
    orest-ui --video "OBS Virtual Camera" --model gemma4:26b
    orest-ui --cast data/cast --send-td --send-ndi

Takes the same camera, microphone, window and output options as orest-sitrep;
they apply to every live SITREP started from the page. Devices are resolved
when a run starts, not here, so a camera plugged in after the server started
is found.

Binds 127.0.0.1 by default. The page shows unreleased footage of identifiable
people, as the WISE server does (smartsearch/config.py, HOST).
"""

import argparse
import os
import pathlib
import sys

import uvicorn

from sitrep import cli, devices, report, session

from .app import create_app
from .live import LiveSitrep

HOST = os.environ.get("OREST_UI_HOST", "127.0.0.1")
PORT = int(os.environ.get("OREST_UI_PORT", "9680"))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__.splitlines()[0],
        parents=[cli.sources(), cli.timing(), cli.resolution(), cli.touchdesigner()],
    )
    parser.add_argument("--model", default=report.MODEL)
    parser.add_argument("--cast", type=pathlib.Path,
                        help="folder of enrolment images; recognises the cast by "
                             "name, everyone else is given a guessed name")
    parser.add_argument("--host", default=HOST, help=f"address to bind (default: {HOST})")
    parser.add_argument("--port", type=int, default=PORT,
                        help=f"port to serve on (default: {PORT})")
    args = parser.parse_args(argv)

    def open_session() -> session.Session:
        video, audio = devices.resolve(args.video, args.audio, args.audio_api)
        run = session.Session(video, audio, session.Options.from_args(args))
        for path in run.missing_enrolment:
            print(f"no face found in {path}", file=sys.stderr)
        return run

    live = LiveSitrep(open_session)
    print(f"Orest operator page: http://{args.host}:{args.port}/", flush=True)
    try:
        uvicorn.run(create_app(live), host=args.host, port=args.port,
                    log_level="warning", timeout_graceful_shutdown=2)
    finally:
        live.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
