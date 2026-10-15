"""Scene configurations: the scenes file, and what the operator's keys change in a scene."""

import pathlib

import pytest
from pydantic import ValidationError

from sitrep import scenes


def test_the_scenes_file_holds_the_scenes_of_the_play():
    loaded = scenes.load()
    assert list(loaded) == [scenes.DEFAULT_NAME, "Szene 1", "Szene 1.2", "Szene 2.3", "Szene 3"]
    eins = loaded["Szene 1"]
    assert (eins.podest, eins.tracked) == (scenes.PodestRule(step=1, floor=2), 30)
    assert eins.keys["t"].action == "strobe"
    assert eins.keys["p"].tracked == 3
    zwei_drei = loaded["Szene 2.3"]
    assert zwei_drei.values_of("Alex") == ["aggression"]
    assert zwei_drei.values_of("Lena") == ["risiko", "menschlichkeit", "berechenbarkeit"]
    assert loaded["Szene 1.2"].prerecorded
    assert loaded["Szene 3"].keys["c"].swap


def test_without_a_scene_the_defaults_apply():
    standard = scenes.Scene()
    assert standard.podest is None
    assert standard.interference
    assert standard.tracked == 4
    assert standard.values == ["risiko", "menschlichkeit", "berechenbarkeit"]
    assert not standard.prerecorded and standard.video is None and not standard.keys


def write(tmp_path, text) -> pathlib.Path:
    path = tmp_path / "scenes.toml"
    path.write_text(text, encoding="utf-8")
    return path


@pytest.mark.parametrize("text", [
    '["A"]\nkeys.r = { screen = "x" }\n',                      # taken by the page
    '["A"]\nkeys.t = { screen = "x", tracked = 3 }\n',          # two things at once
    '["A"]\nkeys.t = { screen = "x", strobe = true }\n',        # two pages at once
    '["A"]\nkeys.t = {}\n',                                     # nothing
    '["A"]\nkeys.w = { person = "Alex", value = "risiko", step = 1 }\n',  # measured, not manual
    '["A"]\nkeys.w = { person = "Alex", value = "aggression" }\n',        # no step
    '["A"]\nkeys.T = { screen = "x" }\n',                       # upper case
    '["A"]\nvalues = ["wut"]\n',                                # unknown value
    '["A"]\ntempo = 3\n',                                       # unknown setting
    '["Standard"]\ntracked = 3\n',                              # the defaults' name
])
def test_a_setting_not_understood_names_its_scene(tmp_path, text):
    with pytest.raises(ValueError, match="'A'|Standard"):
        scenes.load(write(tmp_path, text))


def test_a_video_is_found_from_the_repository_root(tmp_path):
    loaded = scenes.load(write(tmp_path, '["A"]\nvideo = "data/scenes/a.mp4"\n'))
    assert loaded["A"].video == scenes.REPO_ROOT / "data" / "scenes" / "a.mp4"


def test_a_scene_without_its_video_says_so_and_runs_live():
    current = scenes.Current(scenes.Scene(name="Szene 1.2", prerecorded=True))
    assert "kein Video hinterlegt" in current.snapshot()["warnings"][0]
    assert current.video() is None


def test_the_video_plays_from_the_selection_or_on_its_key(tmp_path):
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"")
    current = scenes.Current(scenes.Scene(name="Szene 1.2", video=clip, prerecorded=True))
    assert current.video() == clip
    current.select(scenes.Scene(name="Szene 3", video=clip, keys={"c": scenes.Key(swap=True)}))
    assert current.video() is None
    assert current.press("c") == "swap"
    assert current.video() == clip
    current.press("C")
    assert current.video() is None


def test_a_screen_opens_and_closes_with_its_key_or_closing():
    current = scenes.Current(scenes.Scene(keys={"t": scenes.Key(screen="TROJA IST GEFALLEN")}))
    current.press("t")
    assert current.snapshot()["screen"] == "TROJA IST GEFALLEN"
    current.press("t")
    assert current.snapshot()["screen"] is None
    current.press("t")
    assert current.close_screen()
    assert current.snapshot()["screen"] is None
    assert not current.close_screen()


def test_the_stroboscope_opens_and_closes_with_its_key_or_closing():
    current = scenes.Current(scenes.Scene(keys={"t": scenes.Key(strobe=True)}))
    assert current.snapshot()["strobe"] is False
    assert current.press("t") == "strobe"
    assert current.snapshot()["strobe"] is True
    current.press("t")
    assert current.snapshot()["strobe"] is False
    current.press("t")
    assert current.close_screen()
    assert current.snapshot()["strobe"] is False
    assert not current.close_screen()


def test_a_screen_and_the_stroboscope_are_never_open_together():
    current = scenes.Current(scenes.Scene(keys={"t": scenes.Key(strobe=True),
                                                "m": scenes.Key(screen="TROJA IST GEFALLEN")}))
    current.press("m")
    current.press("t")
    assert (current.snapshot()["screen"], current.snapshot()["strobe"]) == (None, True)
    current.press("m")
    assert (current.snapshot()["screen"], current.snapshot()["strobe"]) == ("TROJA IST GEFALLEN", False)


def test_a_key_switches_the_number_tracked_and_back():
    current = scenes.Current(scenes.Scene(tracked=30, keys={"p": scenes.Key(tracked=3)}))
    assert current.tracked == 30
    current.press("p")
    assert current.tracked == 3
    current.press("p")
    assert current.tracked == 30


def test_aggression_set_by_hand_stays_within_minus_ten_and_ten():
    up = scenes.Key(person="Alex", value="aggression", step=1)
    down = scenes.Key(person="Alex", value="aggression", step=-1)
    current = scenes.Current(scenes.Scene(keys={"w": up, "s": down}))
    current.press("s")
    assert current.snapshot()["manual"] == {"Alex": {"aggression": -1}}
    for _ in range(12):
        current.press("s")
    assert current.snapshot()["manual"] == {"Alex": {"aggression": -10}}
    for _ in range(25):
        current.press("w")
    assert current.snapshot()["manual"] == {"Alex": {"aggression": 10}}


def test_only_aggression_has_the_wider_range():
    assert scenes.RANGES == {"risiko": (0, 5), "menschlichkeit": (0, 5),
                             "berechenbarkeit": (-5, 5), "aggression": (-10, 10)}
    assert [scenes.extent(value) for value in scenes.VALUES] == [5, 5, 5, 10]


def test_the_podest_floor_stays_on_risikos_scale():
    """The Podest count is added to Risiko, 0 to 5."""
    assert scenes.PodestRule(floor=5).floor == 5
    with pytest.raises(ValidationError):
        scenes.PodestRule(floor=6)


def test_a_key_the_scene_does_not_have_does_nothing():
    assert scenes.Current().press("t") is None


def test_selecting_a_scene_undoes_what_the_operator_changed():
    scene = scenes.Scene(tracked=30, keys={"p": scenes.Key(tracked=3),
                                           "t": scenes.Key(screen="TROJA IST GEFALLEN"),
                                           "z": scenes.Key(strobe=True),
                                           "w": scenes.Key(person="Alex", value="aggression",
                                                           step=1)})
    current = scenes.Current(scene)
    before = current.generation
    for key in "pzw":
        current.press(key)
    current.select(scene)
    shown = current.snapshot()
    assert (shown["tracked"], shown["strobe"], shown["manual"]) == (30, False, {})
    assert current.generation == before + 1
    current.press("t")
    current.select(scene)
    assert current.snapshot()["screen"] is None


def test_the_page_is_told_the_keys_and_what_they_do():
    current = scenes.Current(scenes.Scene(name="Szene 2.3", keys={
        "w": scenes.Key(person="Alex", value="aggression", step=1),
        "m": scenes.Key(screen="Maximales Aggressionspotenzial erreicht."),
        "t": scenes.Key(strobe=True)}))
    keys = current.snapshot()["keys"]
    assert keys == {"w": {"action": "adjust", "label": "Alex: Aggression +1"},
                    "m": {"action": "screen",
                          "label": "„Maximales Aggressionspotenzial erreicht.“"},
                    "t": {"action": "strobe", "label": "Stroboskop"}}
