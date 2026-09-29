"""One request to the model at a time, the most urgent first.

Ollama on the production machine serves one request at a time and queues the
rest in arrival order (measured 2026-09-29: a 60-token request sent while a
400-token one ran took 1.2 s instead of 0.23 s). Orest makes requests of very
different urgency: rating a line that was just said, recommending a measure
after an alarm, a report the operator asked for, and the background summary
of the scene. Left to Ollama's queue, a line rating could wait behind a
summary nobody is waiting for.

So Orest's requests pass this gate: at most one is with Ollama, and when it
finishes the most urgent waiting one goes next. A request already running is
never interrupted, so the wait for an urgent one is at most the rest of the
running one.
"""

import heapq
import itertools
import threading
from contextlib import contextmanager

import ollama

# Priorities, most urgent first.
ZEILEN = 0          # lines just said (speech.py)
EMPFEHLUNG = 1      # a measure after an alarm (report.empfehlen)
BERICHT = 2         # the report the operator asked for (report.analyse)
CHRONIK = 3         # the background summary of the scene (chronik.py)


class Gate:
    """Admits one holder at a time, the lowest priority number first, then first come."""

    def __init__(self):
        self._condition = threading.Condition()
        self._busy = False
        self._waiting: list[tuple[int, int]] = []
        self._order = itertools.count()

    @contextmanager
    def turn(self, priority: int):
        ticket = (priority, next(self._order))
        with self._condition:
            heapq.heappush(self._waiting, ticket)
            while self._busy or self._waiting[0] != ticket:
                self._condition.wait()
            heapq.heappop(self._waiting)
            self._busy = True
        try:
            yield
        finally:
            with self._condition:
                self._busy = False
                self._condition.notify_all()


# One gate per process: every request goes to the same Ollama.
GATE = Gate()


def turn(priority: int):
    """Wait for this request's turn with the model."""
    return GATE.turn(priority)


def pruefen(model: str):
    """Raise RuntimeError unless Ollama is running and has the model.

    Checked when a run starts: every part of a run asks the model, and a
    missing model would otherwise fail each request separately while the
    run goes on without ratings, summaries or reports.
    """
    try:
        installed = [entry.model for entry in ollama.list().models]
    except ConnectionError as error:
        raise RuntimeError(f"Ollama is not reachable: {error}") from error
    # A name without a tag means Ollama's "latest".
    wanted = model if ":" in model else f"{model}:latest"
    if wanted not in installed:
        raise RuntimeError(f"Model {model!r} is not in Ollama. Installed: "
                           f"{', '.join(installed) or 'none'}. Choose one with --model, "
                           f"or pull it with `ollama pull {model}`.")
