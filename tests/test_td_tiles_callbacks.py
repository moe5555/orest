"""The replicator callbacks that keep the video wall's grid listing every tile.

Runs the TouchDesigner callback module against stand-ins for the replicator,
its tiles and the Layout TOP. Needs no TouchDesigner.
"""

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

MODULE = Path(__file__).resolve().parents[1] / "TouchDesigner" / "code" / "tiles_callbacks.py"


class Tile:
    def __init__(self, replicator, number):
        self.replicator = replicator
        self.digits = number
        self.path = f"/project1/bodysearch/tiles/tile{number}"

    def destroy(self):
        self.replicator.children.remove(self)


class Replicator:
    def __init__(self, numbers):
        self.children = [Tile(self, number) for number in numbers]


@pytest.fixture
def wall():
    spec = importlib.util.spec_from_file_location("tiles_callbacks", MODULE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    layout = SimpleNamespace(par=SimpleNamespace(top=""))
    module.op = lambda name: layout
    return module, layout


def listed(layout):
    return [path.rsplit("/", 2)[-2] for path in layout.par.top.split()]


def test_tiles_are_listed_by_number_so_ten_follows_nine(wall):
    module, layout = wall
    replicator = Replicator([10, 2, 1, 9, 11])
    module.onReplicate(replicator, replicator.children, [], None, None)
    assert listed(layout) == ["tile1", "tile2", "tile9", "tile10", "tile11"]
    assert layout.par.top.split()[0] == "/project1/bodysearch/tiles/tile1/out1"


def test_a_removed_tile_leaves_the_list(wall):
    module, layout = wall
    replicator = Replicator([1, 2, 3])
    module.onRemoveReplicant(replicator, replicator.children[2])
    assert listed(layout) == ["tile1", "tile2"]
