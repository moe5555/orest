"""The gate to the model: one request at a time, the most urgent first."""

import threading
import time

import pytest

from sitrep import llm


def test_waiting_requests_go_in_order_of_urgency():
    gate = llm.Gate()
    order = []
    holding = threading.Event()
    release = threading.Event()

    def first():
        with gate.turn(llm.BERICHT):
            holding.set()
            release.wait(5)

    def waiting(priority):
        with gate.turn(priority):
            order.append(priority)

    running = threading.Thread(target=first)
    running.start()
    assert holding.wait(5)
    queued = [threading.Thread(target=waiting, args=(priority,))
              for priority in (llm.CHRONIK, llm.BERICHT, llm.ZEILEN, llm.EMPFEHLUNG)]
    for thread in queued:
        thread.start()
        time.sleep(0.02)
    release.set()
    for thread in [running, *queued]:
        thread.join(5)
    assert order == [llm.ZEILEN, llm.EMPFEHLUNG, llm.BERICHT, llm.CHRONIK]


def test_only_one_request_is_with_the_model_at_a_time():
    gate = llm.Gate()
    inside = []
    most = []

    def request():
        with gate.turn(llm.ZEILEN):
            inside.append(1)
            most.append(len(inside))
            time.sleep(0.01)
            inside.pop()

    threads = [threading.Thread(target=request) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(5)
    assert max(most) == 1


def test_a_failed_request_frees_the_gate():
    gate = llm.Gate()
    try:
        with gate.turn(llm.BERICHT):
            raise RuntimeError("model gone")
    except RuntimeError:
        pass
    with gate.turn(llm.CHRONIK):
        pass


class Listed:
    def __init__(self, *names):
        self.models = [type("Entry", (), {"model": name})() for name in names]


def test_a_model_ollama_has_passes_the_check(monkeypatch):
    monkeypatch.setattr(llm.ollama, "list", lambda: Listed("some-model:tag"))
    llm.pruefen("some-model:tag")


def test_a_missing_model_is_named_with_those_installed(monkeypatch):
    monkeypatch.setattr(llm.ollama, "list", lambda: Listed("some-model:tag"))
    with pytest.raises(RuntimeError, match=r"'other-model:7b' is not in Ollama\. Installed: some-model:tag"):
        llm.pruefen("other-model:7b")


def test_a_name_without_a_tag_means_latest(monkeypatch):
    monkeypatch.setattr(llm.ollama, "list", lambda: Listed("some-model:latest"))
    llm.pruefen("some-model")


def test_ollama_not_running_fails_the_check(monkeypatch):
    def refuse():
        raise ConnectionError("Failed to connect to Ollama.")

    monkeypatch.setattr(llm.ollama, "list", refuse)
    with pytest.raises(RuntimeError, match="not reachable"):
        llm.pruefen("some-model:tag")
