"""SITREP generation: turns a capture window into a structured German report.

Implements step 5 of the Realtime-SITREP implementation steps in
knowledge/components/02_processing.md ("Write SITREP report JSON format").

Frames and audio arrive as in-memory bytes from capture.py and are never
written out; only the SITREP text is logged, as one JSON object per line
("write log file, but not necessary to time-sync with footage").

Time frame and source are known exactly from the capture window and are written
directly, rather than spending tokens asking the model to restate what it
cannot verify. Ollama is given the schema as a grammar constraint, so the reply
parses as JSON without repair. Field descriptions are part of that schema and
steer the model, so they are kept short: every token in the schema and the reply
costs latency, which step 6 caps.

Run directly to report on a live camera and microphone:

    python src/sitrep/report.py --window 30 --interval 10
"""

import argparse
import itertools
import json
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from ollama import ResponseError, chat
from pydantic import BaseModel, Field, ValidationError

import capture

# The 12b build needs 8.5GB against this machine's 8.1GB of VRAM and runs
# ~30% on CPU as a result, which puts p95 latency far outside any usable
# window. e4b fits entirely on the GPU.
MODEL = "gemma4:e4b"

# Cap on generated tokens. A three-person report needs roughly 400. The reply
# is only parseable if generation finishes: the schema grammar guarantees
# well-formed JSON, but a reply cut off at the cap is truncated mid-string and
# fails to parse, so the cap has to sit clear of a normal report.
NUM_PREDICT = 700

CONTEXT = 8192

# Low but non-zero: near-deterministic wording, still able to phrase a scene it
# has no set phrase for.
TEMPERATURE = 0.2

# e4b is prone to degenerate repetition, which runs a reply into the token cap
# and truncates the JSON. Penalising repeats keeps generations terminating.
REPEAT_PENALTY = 1.2

ANWEISUNG = """Du bist Orest, ein Ueberwachungssystem auf einer Theaterprobe.
Du erhaeltst Standbilder aus einem Zeitfenster und die zugehoerige Tonaufnahme.
Erstelle daraus einen Lagebericht.

Regeln:
- Berichte ausschliesslich, was in Bild und Ton belegt ist. Keine Spekulation,
  keine Ausschmueckung, keine erfundenen Geraeusche.
- Ist keine Sprache zu hoeren, bleibt "gesagt" leer.
- Bezeichne Personen als P-01, P-02 in der Reihenfolge ihres Auftretens.
- Knapp und nominal, Behoerdenstil. Keine Anrede, keine Erzaehlsaetze.
- Bewertungen 0-5: 0 trifft nicht zu, 5 trifft stark zu.
- Ist etwas nicht erkennbar, lass das Feld leer statt zu raten."""


class Person(BaseModel):
    kennung: str = Field(description="P-01, P-02 ...")
    merkmale: str = Field(description="Aeussere Merkmale, knapp")
    taetigkeit: str = Field(description="Beobachtete Handlung")
    verantwortungsvoll: int = Field(ge=0, le=5)
    menschlich: int = Field(ge=0, le=5)
    gefahr: int = Field(ge=0, le=5)
    kollaborativ: int = Field(ge=0, le=5)


class Lagebericht(BaseModel):
    """The model-generated part of a SITREP."""

    lage: str = Field(description="Gesamtlage in einem Satz")
    personen: list[Person]
    ereignisse: list[str] = Field(description="Beobachtete Vorgaenge, Stichpunkte")
    gesagt: str = Field(description="Woertliches Zitat des Gesprochenen, sonst leer")
    prognose: str = Field(description="Zu erwartende Entwicklung")
    empfehlung: str = Field(description="Vorgeschlagene Massnahme")
    vertrauen: int = Field(ge=0, le=5, description="Sicherheit des Berichts")


@dataclass(frozen=True)
class Analyse:
    bericht: Lagebericht
    latenz_s: float


def analyse(frames: list[bytes], audio: bytes | None = None,
            model=MODEL, num_predict=NUM_PREDICT) -> Analyse:
    """Run one SITREP generation over the given stills and audio.

    Ollama takes both images and audio in the `images` field, base64-encoding
    the bytes it is given; the file type decides how each is handled.
    """
    media = list(frames)
    if audio is not None:
        media.append(audio)

    started = time.monotonic()
    response = chat(
        model=model,
        messages=[{"role": "user", "content": ANWEISUNG, "images": media}],
        think=False,
        keep_alive=-1,
        format=Lagebericht.model_json_schema(),
        options={
            "num_ctx": CONTEXT,
            "num_predict": num_predict,
            "temperature": TEMPERATURE,
            "repeat_penalty": REPEAT_PENALTY,
        },
    )
    latency = time.monotonic() - started
    return Analyse(Lagebericht.model_validate_json(response.message.content), latency)


def sitrep(window: capture.Window, model=MODEL) -> dict:
    """Build the full SITREP document for a capture window."""
    result = analyse(window.frames, window.audio, model=model)
    return {
        "zeitfenster": {
            "beginn": window.started.isoformat(timespec="seconds"),
            "ende": window.ended.isoformat(timespec="seconds"),
            "dauer_s": round(window.seconds, 1),
        },
        "quelle": {"bilder": len(window.frames), "ton_s": round(window.audio_seconds, 1)},
        **result.bericht.model_dump(),
        "latenz_s": round(result.latenz_s, 1),
    }


def run_live(video_spec=None, audio_spec=None, hostapi=None, interval=10.0,
             window=30.0, model=MODEL, log_dir="data/sitrep"):
    """Yield one SITREP document per capture window, logging each as JSON.

    Runs until the caller stops consuming. A window whose reply is unusable is
    skipped rather than ending the session.
    """
    log_path = Path(log_dir) / f"{datetime.now().strftime('%Y%m%d-%H%M%S')}.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"log:    {log_path}")

    windows = capture.run(
        video_spec=video_spec,
        audio_spec=audio_spec,
        hostapi=hostapi,
        interval=interval,
        window=window,
    )

    try:
        with log_path.open("w", encoding="utf-8") as log:
            for captured in windows:
                try:
                    document = sitrep(captured, model=model)
                except (ValidationError, ResponseError) as error:
                    # A reply that ran into the token cap is truncated and does
                    # not parse; a rejected prompt returns an error. Losing one
                    # window beats ending the session.
                    kind = ("unparseable reply" if isinstance(error, ValidationError)
                            else "rejected prompt")
                    print(f"window {captured.index}: {kind}, skipped", file=sys.stderr)
                    continue

                log.write(json.dumps(document, ensure_ascii=False) + "\n")
                log.flush()
                yield document
    finally:
        windows.close()


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
    parser.add_argument("--model", default=MODEL)
    parser.add_argument("--log", default="data/sitrep",
                        help="directory for the SITREP log (text only)")
    args = parser.parse_args(argv)

    reports = run_live(
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
            print(json.dumps(document, ensure_ascii=False, indent=2))
    except KeyboardInterrupt:
        print("\nstopped")
    except (ValueError, RuntimeError) as error:
        print(error, file=sys.stderr)
        return 1
    finally:
        reports.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
