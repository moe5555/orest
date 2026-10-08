"""The keyboard callbacks of the video wall: capture on space, tile count on digits.

Runs the TouchDesigner callback module against stand-ins for the component and
its OSC Out DAT. Needs no TouchDesigner.
"""

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

MODULE = Path(__file__).resolve().parents[1] / "TouchDesigner" / "code" / "wall_keys.py"


class OscOut:
    def __init__(self):
        self.sent = []

    def sendOSC(self, address, args):
        self.sent.append(address)


@pytest.fixture
def wall():
    """The loaded module, the component holding Tiles, and the OSC Out DAT."""
    spec = importlib.util.spec_from_file_location("wall_keys", MODULE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    component = SimpleNamespace(par=SimpleNamespace(Tiles=4))
    osc = OscOut()
    module.parent = lambda: component
    module.op = lambda name: osc
    return module, component, osc


def key(module, name, down):
    flags = dict.fromkeys(["alt", "lAlt", "rAlt", "ctrl", "lCtrl", "rCtrl", "shift",
                           "lShift", "rShift", "cmd", "lCmd", "rCmd"], False)
    module.onKey(None, name, name, state=down, time=0, **flags)


def press(module, *names):
    for name in names:
        key(module, name, True)


def release(module, *names):
    for name in names:
        key(module, name, False)


def test_space_held_captures_and_released_searches(wall):
    module, _, osc = wall
    press(module, "space")
    release(module, "space")
    assert osc.sent == ["/apollon/body/start", "/apollon/body/stop"]


def test_a_single_digit_sets_the_tile_count_on_release(wall):
    module, component, _ = wall
    press(module, "6")
    assert component.par.Tiles == 4
    release(module, "6")
    assert component.par.Tiles == 6


def test_a_digit_pressed_while_another_is_held_adds_a_digit(wall):
    module, component, _ = wall
    press(module, "1", "6")
    release(module, "1")
    assert component.par.Tiles == 4
    release(module, "6")
    assert component.par.Tiles == 16


def test_the_digits_count_in_the_order_they_were_pressed(wall):
    module, component, _ = wall
    press(module, "6", "1")
    release(module, "1", "6")
    assert component.par.Tiles == 61


def test_key_repeat_of_a_held_digit_adds_nothing(wall):
    module, component, _ = wall
    press(module, "1", "1", "1", "2")
    release(module, "2", "1")
    assert component.par.Tiles == 12


def test_each_entry_starts_afresh(wall):
    module, component, _ = wall
    press(module, "1", "6")
    release(module, "1", "6")
    press(module, "9")
    release(module, "9")
    assert component.par.Tiles == 9


def test_a_lost_release_does_not_block_later_entries(wall, monkeypatch):
    module, component, _ = wall
    clock = iter([0.0, 10.0])
    monkeypatch.setattr(module.time, "monotonic", lambda: next(clock))
    press(module, "2")  # its release never arrives
    press(module, "4")
    release(module, "4")
    assert component.par.Tiles == 4


def test_a_held_first_digit_kept_alive_by_key_repeat_still_combines(wall, monkeypatch):
    module, component, _ = wall
    clock = iter([0.0, 3.0, 6.0, 7.0])
    monkeypatch.setattr(module.time, "monotonic", lambda: next(clock))
    press(module, "1", "1", "1", "6")
    release(module, "1", "6")
    assert component.par.Tiles == 16


def test_zero_tiles_is_ignored_but_zero_works_as_a_second_digit(wall):
    module, component, _ = wall
    press(module, "0")
    release(module, "0")
    assert component.par.Tiles == 4
    press(module, "2", "0")
    release(module, "2", "0")
    assert component.par.Tiles == 20
