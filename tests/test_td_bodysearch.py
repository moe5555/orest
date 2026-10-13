"""The TouchDesigner module that turns result messages into the `results` table.

Every player on the video wall shows one row of the table, so a wrong row
reaches the stage as the wrong clip in a tile. Runs the module as
TouchDesigner would, against a stand-in Table DAT, with messages from Apollon's
own builders. Needs no TouchDesigner.
"""

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

from smartsearch import td
from smartsearch.client import Hit
from smartsearch.clips import Clip

MODULE = Path(__file__).resolve().parents[1] / "TouchDesigner" / "code" / "bodysearch_osc.py"

HIT = Hit(
    media_id="3", filename="Theaterprobe.mp4", ts=1008.0, te=1012.0, score=0.94,
    target="video", vector_id="0/3/2016", media_url="http://127.0.0.1:9670/p/media/3",
    thumbnail_url="",
)


class Cell:
    def __init__(self, val):
        self.val = val


class Table:
    """The part of TouchDesigner's Table DAT the module uses. Cells are strings."""

    def __init__(self, rows=()):
        self.rows = [[str(value) for value in row] for row in rows]

    @property
    def numRows(self):
        return len(self.rows)

    def clear(self):
        self.rows = []

    def appendRow(self, values):
        self.rows.append([str(value) for value in values])

    def replaceRow(self, index, values):
        self.rows[index] = [str(value) for value in values]

    def deleteRow(self, index):
        del self.rows[index]

    def row(self, index):
        return [Cell(value) for value in self.rows[index]]

    def clips(self):
        column = self.rows[0].index("clip_path")
        return [row[column] for row in self.rows[1:]]


@pytest.fixture
def table():
    return Table()


@pytest.fixture
def component():
    """The body search component, without the wall's `Tiles` parameter."""
    return SimpleNamespace(par=SimpleNamespace())


@pytest.fixture
def module(table, component):
    spec = importlib.util.spec_from_file_location("bodysearch_osc", MODULE)
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    loaded.op = lambda name: table
    loaded.parent = lambda: component
    return loaded


def build_wall(component, tiles):
    component.par.Tiles = SimpleNamespace(eval=lambda: tiles)


@pytest.fixture
def reversing(module, monkeypatch):
    """Shuffles by reversing, so the order rows are written in is known."""
    monkeypatch.setattr(module.random, "shuffle", lambda rows: rows.reverse())
    return module


def search(module, query_id, clips, end=True):
    """Deliver one search's messages, as `apollon-search --send-td` frames them."""
    module.handle(*td.begin_message(query_id, len(clips)))
    for rank, name in enumerate(clips, start=1):
        module.handle(*td.hit_message(query_id, rank, Clip(Path(name), 0.0), HIT))
    if end:
        module.handle(*td.end_message(query_id))


def names(table):
    return [Path(clip).name for clip in table.clips()]


def test_a_search_fills_one_row_per_rank_under_the_header(module, table):
    search(module, "q1", ["a.mp4", "b.mp4", "c.mp4"])
    assert table.rows[0] == module.RESULTS_HEADER
    assert names(table) == ["a.mp4", "b.mp4", "c.mp4"]
    assert [row[0] for row in table.rows[1:]] == ["1", "2", "3"]


def test_the_previous_clips_stay_until_each_is_replaced(module, table):
    search(module, "q1", ["a.mp4", "b.mp4", "c.mp4"])
    module.handle(*td.begin_message("q2", 3))
    assert names(table) == ["a.mp4", "b.mp4", "c.mp4"]
    module.handle(*td.hit_message("q2", 1, Clip(Path("x.mp4"), 0.0), HIT))
    assert names(table) == ["x.mp4", "b.mp4", "c.mp4"]


def test_rows_a_smaller_search_did_not_reach_are_removed_at_its_end(module, table):
    search(module, "q1", ["a.mp4", "b.mp4", "c.mp4"])
    search(module, "q2", ["x.mp4"], end=False)
    assert names(table) == ["x.mp4", "b.mp4", "c.mp4"]
    module.handle(*td.end_message("q2"))
    assert names(table) == ["x.mp4"]


def test_hits_of_an_earlier_search_are_dropped(module, table):
    search(module, "q1", ["a.mp4"], end=False)
    module.handle(*td.begin_message("q2", 1))
    module.handle(*td.hit_message("q1", 1, Clip(Path("late.mp4"), 0.0), HIT))
    module.handle(*td.end_message("q1"))
    assert names(table) == ["a.mp4"]


def test_a_lost_hit_leaves_an_empty_row_rather_than_shifting_the_ranks(module, table):
    module.handle(*td.begin_message("q1", 3))
    module.handle(*td.hit_message("q1", 1, Clip(Path("a.mp4"), 0.0), HIT))
    module.handle(*td.hit_message("q1", 3, Clip(Path("c.mp4"), 0.0), HIT))
    assert names(table) == ["a.mp4", "", "c.mp4"]


def test_a_table_with_another_header_is_reset(module, table):
    table.rows = [["rank", "clip"], ["1", "old.mp4"]]
    search(module, "q1", ["a.mp4"])
    assert table.rows[0] == module.RESULTS_HEADER
    assert names(table) == ["a.mp4"]


def test_other_addresses_are_left_to_other_modules(module, table):
    assert module.handle("/apollon/sitrep/begin", ["t1"]) is False
    assert table.rows == []


def ranks(table):
    return [row[0] for row in table.rows[1:]]


def test_on_a_wall_the_tiles_receive_their_hits_in_shuffled_order(reversing, table, component):
    build_wall(component, 4)
    search(reversing, "q1", ["a.mp4", "b.mp4", "c.mp4", "d.mp4"], end=False)
    assert names(table) == ["d.mp4", "c.mp4", "b.mp4", "a.mp4"]
    assert ranks(table) == ["4", "3", "2", "1"]


def test_the_previous_clips_on_a_wall_stay_until_each_is_replaced(reversing, table, component):
    build_wall(component, 3)
    search(reversing, "q1", ["a.mp4", "b.mp4", "c.mp4"])
    reversing.handle(*td.begin_message("q2", 3))
    reversing.handle(*td.hit_message("q2", 1, Clip(Path("x.mp4"), 0.0), HIT))
    assert names(table) == ["c.mp4", "b.mp4", "x.mp4"]


def test_ranks_beyond_the_tiles_keep_their_own_rows(reversing, table, component):
    build_wall(component, 2)
    search(reversing, "q1", ["a.mp4", "b.mp4", "c.mp4", "d.mp4"])
    assert names(table) == ["b.mp4", "a.mp4", "c.mp4", "d.mp4"]


def test_a_search_smaller_than_the_wall_shuffles_only_its_own_rows(reversing, table, component):
    build_wall(component, 9)
    search(reversing, "q1", ["a.mp4", "b.mp4"])
    assert names(table) == ["b.mp4", "a.mp4"]


def test_every_search_on_a_wall_fills_each_row_once(module, table, component):
    build_wall(component, 9)
    for query in range(20):
        clips = [f"{query}_{rank}.mp4" for rank in range(1, 10)]
        search(module, f"q{query}", clips)
        assert sorted(ranks(table), key=int) == [str(rank) for rank in range(1, 10)]
        assert sorted(names(table)) == sorted(clips)
