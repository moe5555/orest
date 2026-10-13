"""Scene configurations of the live SITREP.

"Scene Configurations" in knowledge/components/02_processing.md: the play
uses the live SITREP in several scenes, each with settings of its own. The
scenes are kept in SCENES_FILE, editable without touching the code, and the
operator selects one on the start page. A scene sets only what differs from
the defaults of `Scene`, which also apply while no scene is selected
(DEFAULT_NAME).

The spec's settings, and where each takes effect:

- SITREP Spatial Value Rules: `podest`, the Podest count (podest.Counter) in
  the live values (lage.py). Off by default.
- Interference: `interference`, whether the alarm asks the model for a
  recommendation and an Einschreiten replaces the page (session.py,
  sitrep.js). Einschreiten is the only kind. On by default.
- Manual Interference: keys with `screen`, a page reading that text, opened
  with the key and closed with it or with X.
- Tracked Persons: `tracked`, the bodies boxed, named and judged on the
  Podest (actions.ActionRatings.tracked), and keys with `tracked`, which
  switch to another number and back. Four by default, the size of the cast.
- SITREP Values: `values`, and `values_per_person` for the people whose
  values differ. Only these are shown, sent and read by the alarm (lage.py).
- Manual SITREP Values: keys with `person`, `value` and `step`, which raise
  or lower a value that only the operator sets (MANUAL).
- Pre-recorded: `video`, played in place of the camera from the scene's
  selection on when `prerecorded` (recording.py). It is analysed as the
  camera is, and its sound replaces the microphone's while it plays.
- Record-Feed Transition: keys with `swap`, which switch between the live
  feed and `video`, the video from its start each time.

What the operator changes in a scene (`Current`): the number tracked, the
manual values, the screen open and whether the video plays. It lasts until a
scene is selected, across runs started meanwhile.
"""

import pathlib
import threading
import tomllib
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from . import report

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]

SCENES_FILE = pathlib.Path(__file__).with_name("scenes.toml")

# The scene in force while none is selected: the defaults alone.
DEFAULT_NAME = "Standard"

# Values only the operator sets; nothing measures them.
MANUAL = ("aggression",)

# Every value a person can be shown with, in the order they are shown.
VALUES = report.BEWERTUNGEN + MANUAL

LABELS = {"risiko": "Risiko", "menschlichkeit": "Menschlichkeit",
          "vorhersehbarkeit": "Vorhersehbarkeit", "aggression": "Aggression"}

# Each value's range, lowest and highest. Risiko, Menschlichkeit and
# Vorhersehbarkeit as measured (report.py); Aggression as the operator sets it
# in Szene 2.3.
RANGES = {"risiko": (0, 5), "menschlichkeit": (0, 5), "vorhersehbarkeit": (-5, 5),
          "aggression": (-10, 10)}


def extent(value: str) -> int:
    """The largest magnitude a value can take, which fills all its pips."""
    low, high = RANGES[value]
    return max(-low, high)


# Bodies tracked unless a scene says otherwise: as many as the cast.
TRACKED = 4

# Keys the SITREP page already uses: R report, E recommendation, X override.
RESERVED = frozenset("rex")


class PodestRule(BaseModel):
    """The Podest count of podest.Counter."""

    model_config = ConfigDict(extra="forbid")

    step: int = Field(default=1, ge=0)
    # The count is added to Risiko, so the floor is on Risiko's scale.
    floor: int = Field(default=2, ge=0, le=RANGES["risiko"][1])


class Key(BaseModel):
    """What one key does in a scene: exactly one of opening a screen,
    switching the number tracked, changing a manual value, or swapping the
    live feed for the video."""

    model_config = ConfigDict(extra="forbid")

    screen: str | None = None
    tracked: int | None = Field(default=None, ge=1)
    person: str | None = None
    value: str | None = None
    step: int | None = None
    swap: bool = False

    @model_validator(mode="after")
    def _one_action(self) -> "Key":
        adjust = (self.person, self.value, self.step)
        chosen = [self.screen is not None, self.tracked is not None,
                  any(part is not None for part in adjust), self.swap]
        if sum(chosen) != 1:
            raise ValueError("a key does exactly one of: screen, tracked, "
                             "person/value/step, swap")
        if chosen[2]:
            if any(part is None for part in adjust):
                raise ValueError("a manual value needs person, value and step")
            if self.value not in MANUAL:
                raise ValueError(f"only {', '.join(MANUAL)} can be set by hand, not {self.value!r}")
        return self

    @property
    def action(self) -> str:
        """"screen", "tracked", "adjust" or "swap"."""
        if self.screen is not None:
            return "screen"
        if self.tracked is not None:
            return "tracked"
        return "swap" if self.swap else "adjust"

    def label(self) -> str:
        """What the key does, as the operator reads it."""
        if self.action == "screen":
            return f"„{self.screen}“"
        if self.action == "tracked":
            return f"{self.tracked} Personen verfolgen"
        if self.action == "adjust":
            return f"{self.person}: {LABELS[self.value]} {self.step:+d}"
        return "Aufnahme ↔ Live"


def _check_values(values: list[str]) -> list[str]:
    unknown = [value for value in values if value not in VALUES]
    if unknown:
        raise ValueError(f"unknown values {unknown}; known: {list(VALUES)}")
    return values


class Scene(BaseModel):
    """One scene's settings. The defaults are the spec's, with Einschreiten
    on and four people tracked."""

    model_config = ConfigDict(extra="forbid")

    name: str = DEFAULT_NAME
    podest: PodestRule | None = None
    interference: bool = True
    tracked: int = Field(default=TRACKED, ge=1)
    values: list[str] = Field(default_factory=lambda: list(report.BEWERTUNGEN))
    values_per_person: dict[str, list[str]] = Field(default_factory=dict)
    video: pathlib.Path | None = None
    prerecorded: bool = False
    keys: dict[str, Key] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check(self) -> "Scene":
        _check_values(self.values)
        for values in self.values_per_person.values():
            _check_values(values)
        for key in self.keys:
            if len(key) != 1 or key != key.lower() or not key.isalnum():
                raise ValueError(f"a key is one lower-case letter or digit, not {key!r}")
            if key in RESERVED:
                raise ValueError(f"key {key!r} is taken by the SITREP page (R, E, X)")
        if self.video is not None and not self.video.is_absolute():
            self.video = REPO_ROOT / self.video
        return self

    def values_of(self, name: str) -> list[str]:
        """The values a person is shown with."""
        return self.values_per_person.get(name, self.values)

    def all_values(self) -> list[str]:
        """Every value anyone in the scene is shown with, in VALUES order."""
        used = set(self.values).union(*self.values_per_person.values())
        return [value for value in VALUES if value in used]

    def wants_video(self) -> bool:
        return self.prerecorded or any(key.swap for key in self.keys.values())

    def warnings(self) -> list[str]:
        """What keeps the scene from running as configured on this machine."""
        if not self.wants_video():
            return []
        if self.video is None:
            return [f"{self.name}: kein Video hinterlegt ({SCENES_FILE.name}); es läuft das Live-Bild."]
        if not self.video.is_file():
            return [f"{self.name}: Video nicht gefunden: {self.video}"]
        return []


def load(path: pathlib.Path = SCENES_FILE) -> dict[str, Scene]:
    """The scenes by name, the default first. Raises ValueError naming the
    scene of a setting that is not understood."""
    scenes = {DEFAULT_NAME: Scene()}
    if not path.is_file():
        return scenes
    with path.open("rb") as file:
        tables = tomllib.load(file)
    for name, settings in tables.items():
        if name == DEFAULT_NAME:
            raise ValueError(f"{path.name}: {DEFAULT_NAME!r} is the defaults and is not configured")
        try:
            scenes[name] = Scene(name=name, **settings)
        except (ValidationError, TypeError) as error:
            raise ValueError(f"{path.name}, scene {name!r}: {error}") from None
    return scenes


class Current:
    """The scene in force and what the operator changed in it since it was
    selected. Safe to read and change from any thread."""

    def __init__(self, scene: Scene | None = None):
        self._lock = threading.Lock()
        self.generation = 0
        self.select(scene or Scene())

    def select(self, scene: Scene):
        """Put a scene in force, as configured."""
        with self._lock:
            self.scene = scene
            self.tracked = scene.tracked
            self.screen: str | None = None
            self.recorded = scene.prerecorded
            self._manual: dict[str, dict[str, tuple[int, datetime]]] = {}
            # A problem the run met in carrying out the scene, e.g. a video
            # that does not open.
            self.problem: str | None = None
            # Rises with every selection, so the live values know to start
            # the scene's Podest count afresh.
            self.generation += 1

    def press(self, key: str) -> str | None:
        """Carry out what a key does in this scene. Returns its action, or
        None when the key does nothing here."""
        with self._lock:
            bound = self.scene.keys.get(key.lower())
            if bound is None:
                return None
            if bound.action == "screen":
                self.screen = None if self.screen == bound.screen else bound.screen
            elif bound.action == "tracked":
                self.tracked = self.scene.tracked if self.tracked == bound.tracked else bound.tracked
            elif bound.action == "adjust":
                held = self._manual.setdefault(bound.person, {})
                value = held.get(bound.value, (0, None))[0] + bound.step
                low, high = RANGES[bound.value]
                held[bound.value] = (min(high, max(low, value)), datetime.now())
            else:
                self.recorded = not self.recorded
            return bound.action

    def close_screen(self) -> bool:
        """Close the screen a key opened. False when none is open."""
        with self._lock:
            if self.screen is None:
                return False
            self.screen = None
            return True

    def values_of(self, name: str) -> list[str]:
        return self.scene.values_of(name)

    def manual(self) -> dict[str, dict[str, tuple[int, datetime]]]:
        """The values set by hand, by person and value, with when each was last set."""
        with self._lock:
            return {name: dict(values) for name, values in self._manual.items()}

    def video(self) -> pathlib.Path | None:
        """The video to show now in place of the camera, if any."""
        with self._lock:
            scene, recorded = self.scene, self.recorded
        if not recorded or scene.warnings():
            return None
        return scene.video

    def snapshot(self) -> dict:
        """The scene as the page shows it and the keys it answers to."""
        with self._lock:
            scene = self.scene
            return {
                "name": scene.name,
                "interference": scene.interference,
                "podest": scene.podest is not None,
                "tracked": self.tracked,
                "screen": self.screen,
                "recorded": self.recorded and scene.video is not None,
                "video": scene.video.name if scene.video else None,
                "keys": {key: {"action": bound.action, "label": bound.label()}
                         for key, bound in scene.keys.items()},
                "values": list(scene.values),
                "values_per_person": {name: list(values)
                                      for name, values in scene.values_per_person.items()},
                "manual": {name: {value: wert for value, (wert, _) in values.items()}
                           for name, values in self._manual.items()},
                "warnings": scene.warnings() + ([self.problem] if self.problem else []),
            }
