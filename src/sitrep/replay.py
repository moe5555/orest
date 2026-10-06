"""Play a recording into the live SITREP as if it were the room, in real time.

For measuring the live SITREP on the test corpus, and for trying it without a
camera or OBS (the OBS route is in todo_with_data.md). The picture is decoded
at its own pace and served as a camera's newest frame; the sound is fed to the
run in real time, as a microphone delivers it. Everything else is the live
run itself (session.py): the same models, threads and requests.

    python -m sitrep.replay "../test_data_orest/Improvised Four Dogs  a Bone with Erin Darke  Alex Dickson - FULL SCENE.mp4" --language en --model gemma4:26b --window 30 --interval 5 --dauer 405 --bericht-bei 150 300 400

Prints what apollon-sitrep prints. r and e ask for a report or a
recommendation as they do there; --bericht-bei asks for reports at set
positions, so that runs can be compared. At the end it prints the latencies
measured against the targets in knowledge/background/live_sitrep_latency.md
("How to measure it"), and, with --gpu, the GPU's load over the run.

Nothing is written to disk.
"""

import argparse
import pathlib
import subprocess
import sys
import threading
import time
from datetime import datetime

import cv2
import numpy as np
from faster_whisper.audio import decode_audio

from . import cli, devices, report, session, transcribe
from . import main as console

# Sound is fed in chunks of this many seconds, about what a sound card hands over.
CHUNK = 0.02

# Seconds the run goes on after the recording ends, for lines and requests
# still under way.
NACHLAUF = 10.0


class Wiedergabe:
    """The playback's clock: where in the recording the room is now.

    It starts when the sound starts, so that picture and sound stay together
    however long the models take to load; until then the picture holds its
    first frame.
    """

    def __init__(self, start: float):
        self.start = start
        self._began: float | None = None

    def begin(self):
        if self._began is None:
            self._began = time.monotonic()

    @property
    def position(self) -> float:
        """Seconds into the recording."""
        return self.start + (0.0 if self._began is None else time.monotonic() - self._began)

    @property
    def elapsed(self) -> float:
        return self.position - self.start


class Bild:
    """The recording's picture, served as a camera's newest frame."""

    def __init__(self, path: pathlib.Path, uhr: Wiedergabe):
        self.device = devices.VideoDevice(-1, f"Aufnahme {path.name}")
        self._capture = cv2.VideoCapture(str(path))
        if not self._capture.isOpened():
            raise RuntimeError(f"Could not open {path}")
        self._capture.set(cv2.CAP_PROP_POS_MSEC, uhr.start * 1000)
        self._uhr = uhr
        ok, self._frame = self._capture.read()
        if not ok:
            raise RuntimeError(f"No picture in {path} at {uhr.start:g} s")
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._play, daemon=True)
        self._thread.start()

    def _play(self):
        while not self._stop.is_set():
            shown = self._capture.get(cv2.CAP_PROP_POS_MSEC) / 1000
            if shown >= self._uhr.position:
                self._stop.wait(0.005)
                continue
            ok, frame = self._capture.read()
            if not ok:
                return
            with self._lock:
                self._frame = frame

    def latest(self):
        with self._lock:
            return self._frame.copy()

    def close(self):
        self._stop.set()
        self._thread.join(timeout=2.0)
        self._capture.release()


class Ton:
    """The recording's sound, delivered in real time like a microphone's."""

    samplerate = 48000.0

    def __init__(self, path: pathlib.Path, uhr: Wiedergabe, dauer: float | None):
        self.name = f"Aufnahme {path.name}"
        self._uhr = uhr
        rate = int(self.samplerate)
        samples = decode_audio(str(path), sampling_rate=rate)
        first = int(uhr.start * rate)
        last = len(samples) if dauer is None else first + int(dauer * rate)
        self.samples = samples[first:last].astype(np.float32)
        self.seconds = len(self.samples) / rate

    def receiving(self, on_audio):
        """A context manager that feeds the sound to `on_audio` while entered
        (capture.listen)."""
        return _Feeding(self, on_audio)


class _Feeding:
    def __init__(self, ton: Ton, on_audio):
        self._ton = ton
        self._on_audio = on_audio
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._feed, daemon=True)

    def __enter__(self):
        self._ton._uhr.begin()
        self._thread.start()
        return self

    def _feed(self):
        rate = int(self._ton.samplerate)
        fed = 0
        while not self._stop.is_set() and fed < len(self._ton.samples):
            due = min(len(self._ton.samples), int(self._ton._uhr.elapsed * rate))
            if due > fed:
                self._on_audio(self._ton.samples[fed:due])
                fed = due
            self._stop.wait(CHUNK)

    def __exit__(self, *exception):
        self._stop.set()
        self._thread.join(timeout=2.0)


class Messung:
    """Latencies of one run, collected from its events as they are printed."""

    def __init__(self):
        self.werte: list[float] = []
        self.berichte: list[float] = []
        self.empfehlungen: list[tuple[float, str]] = []
        self.abschnitte: list[float] = []
        self.alarme = 0
        self._alarm = False
        self._gesehen: set = set()

    def take(self, event, at: datetime):
        if isinstance(event, session.Werte):
            # A value is updated when a line not shown before sets it: from
            # the end of the line to the change on screen. Values set by an
            # action are shown at most WERTE_TAKT after its reading by
            # construction; one that first counts when its body is named
            # later is not a delay, so actions are left out here.
            for name, werte in event.stand.personen.items():
                for rating, wert in werte.items():
                    key = (name, rating, wert.zeit)
                    if (wert.wert and wert.zeit and wert.anlass.startswith("„")
                            and key not in self._gesehen):
                        self._gesehen.add(key)
                        self.werte.append((at - wert.zeit).total_seconds())
            if event.stand.alarm.aktiv and not self._alarm:
                self.alarme += 1
            self._alarm = event.stand.alarm.aktiv
        elif isinstance(event, session.NeuerBericht):
            self.berichte.append(event.sitrep.latenz_s)
        elif isinstance(event, session.NeueEmpfehlung):
            self.empfehlungen.append((event.empfehlung.latenz_s, event.empfehlung.anlass))
        elif isinstance(event, session.NeuerAbschnitt):
            if event.abschnitt.latenz_s is not None:
                self.abschnitte.append(event.abschnitt.latenz_s)


def _verteilung(values: list[float]) -> str:
    if not values:
        return "–"
    ordered = np.asarray(values)
    return (f"n {len(values)}, p50 {np.percentile(ordered, 50):.1f} s, "
            f"p95 {np.percentile(ordered, 95):.1f} s, max {ordered.max():.1f} s")


class Gpu:
    """The GPU's load and memory, sampled every second by nvidia-smi."""

    def __init__(self):
        self._process = subprocess.Popen(
            ["nvidia-smi", "--query-gpu=utilization.gpu,memory.used",
             "--format=csv,noheader,nounits", "-l", "1"],
            stdout=subprocess.PIPE, text=True)
        self.samples: list[tuple[float, float]] = []
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        for line in self._process.stdout:
            try:
                load, memory = (float(part) for part in line.split(","))
            except ValueError:
                continue
            self.samples.append((load, memory))

    def close(self) -> str:
        self._process.terminate()
        if not self.samples:
            return "gpu: no samples"
        loads = np.array([load for load, _ in self.samples])
        memory = max(memory for _, memory in self.samples)
        return (f"gpu: load mean {loads.mean():.0f} %, p95 {np.percentile(loads, 95):.0f} %, "
                f"max {loads.max():.0f} %; memory max {memory / 1024:.1f} GB")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                     parents=[cli.touchdesigner()])
    parser.add_argument("path", type=pathlib.Path)
    parser.add_argument("--start", type=float, default=0.0, help="seconds into the recording")
    parser.add_argument("--dauer", type=float, help="seconds to play (default: to the end)")
    parser.add_argument("--interval", type=float, default=cli.INTERVAL,
                        help=f"seconds between stills (default: {cli.INTERVAL:g})")
    parser.add_argument("--window", type=float, default=cli.WINDOW,
                        help=f"seconds per Abschnitt of the Chronik (default: {cli.WINDOW:g})")
    parser.add_argument("--model", default=report.MODEL)
    parser.add_argument("--language", default=transcribe.LANGUAGE)
    parser.add_argument("--cast", type=pathlib.Path)
    parser.add_argument("--no-actions", action="store_true")
    parser.add_argument("--no-auto-empfehlung", action="store_true")
    parser.add_argument("--bericht-bei", type=float, nargs="*", default=[],
                        help="ask for a report at these seconds of playback")
    parser.add_argument("--gpu", action="store_true", help="sample the GPU's load")
    parser.add_argument("--no-colour", action="store_true")
    args = parser.parse_args(argv)
    colour = not args.no_colour
    if not sys.stdout.isatty():
        # Written to a file for comparing runs; Windows would otherwise write
        # the local code page, which lacks the console's rules and quotes.
        sys.stdout.reconfigure(encoding="utf-8")

    uhr = Wiedergabe(args.start)
    ton = Ton(args.path, uhr, args.dauer)
    options = session.Options(
        interval=args.interval, window=args.window, model=args.model, language=args.language,
        cast=args.cast, actions=not args.no_actions, send_td=args.send_td,
        ndi=args.ndi_name if args.send_ndi else None, ndi_fps=args.ndi_fps,
        auto_empfehlung=not args.no_auto_empfehlung)
    bild = Bild(args.path, uhr)
    live = session.Session(None, ton, options, stream=bild)
    print(live.describe())
    print(f"replay: {args.start:g}-{args.start + ton.seconds:g} s; "
          "r: Lagebericht · e: Empfehlung · Ctrl+C: beenden", flush=True)
    console._keys(live)
    gpu = Gpu() if args.gpu else None
    messung = Messung()
    konsole = console.Konsole(colour)
    faellig = sorted(args.bericht_bei)

    def schedule():
        while faellig:
            if uhr.elapsed >= faellig[0]:
                faellig.pop(0)
                live.bericht()
            time.sleep(0.1)

    threading.Thread(target=schedule, daemon=True).start()
    ende = None
    try:
        with live:
            for event in live.events():
                messung.take(event, datetime.now())
                text = konsole.text(event)
                if text:
                    print(text, flush=True)
                if ende is None and uhr.elapsed >= ton.seconds:
                    ende = time.monotonic()
                if ende is not None and time.monotonic() - ende > NACHLAUF \
                        and not any(live.laeuft.values()):
                    break
    except KeyboardInterrupt:
        print()
    zeilen = list(live.utterances.latenzen) if live.utterances else []
    stufen = list(live.utterances.stufen) if live.utterances else []
    print("\nLatencies (targets from live_sitrep_latency.md):")
    print(f"  line on screen after its end (p95 ≤ 2.5 s):   {_verteilung(zeilen)}")
    print(f"  line rated after its end:                     "
          f"{_verteilung(list(live.utterances.bewertet) if live.utterances else [])}")
    for stufe in ("warten", "whisper", "bewerten"):
        print(f"    {stufe:<44}{_verteilung([getattr(one, stufe) for one in stufen])}")
    print(f"  person value after a line (p95 ≤ 3 s):        {_verteilung(messung.werte)}")
    print(f"  report from the request:                      {_verteilung(messung.berichte)}")
    print(f"  recommendation from its trigger:              "
          f"{_verteilung([latenz for latenz, _ in messung.empfehlungen])}")
    print(f"  Abschnitt summary:                            {_verteilung(messung.abschnitte)}")
    print(f"  alarms raised: {messung.alarme}; recommendations: {len(messung.empfehlungen)}")
    if gpu:
        print(f"  {gpu.close()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
