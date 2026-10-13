"""Command-line arguments shared by the SITREP entry points.

Capture sources, window timing and capture resolution are selected the same
way wherever they appear, so each group is defined once and attached to a
parser as a parent.

`devices` builds its own command line from these groups, so this module must
not import anything that imports `devices`. `feed` is safe on that count and
supplies the defaults its flags advertise, which keeps one definition of each.
"""

import argparse

import osc

from . import feed, podest, scenes

# Defaults for the command line only. The library functions take window and
# interval as required arguments, because step 6 of
# knowledge/components/02_processing.md makes the window a measured property
# of the machine ("only processes as many seconds as it can keep up with")
# rather than something a library should pick on a caller's behalf.
INTERVAL = 10.0
WINDOW = 30.0


def sources() -> argparse.ArgumentParser:
    """Camera and microphone selection."""
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--video", help="camera index or name fragment")
    parser.add_argument("--audio", help="microphone index or name fragment")
    parser.add_argument("--audio-api", help="host API filter, e.g. WASAPI, MME")
    return parser


def timing() -> argparse.ArgumentParser:
    """Window length and how often a frame is sampled within it."""
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--interval", type=float, default=INTERVAL,
                        help=f"seconds between sampled frames (default: {INTERVAL:g})")
    parser.add_argument("--window", type=float, default=WINDOW,
                        help=f"seconds per window: the stretch the Chronik summarises at a time (default: {WINDOW:g})")
    parser.add_argument("--windows", type=int, help="stop after this many windows")
    return parser


def resolution() -> argparse.ArgumentParser:
    """Requested camera capture resolution."""
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--width", type=int, help="requested capture width")
    parser.add_argument("--height", type=int, help="requested capture height")
    return parser


def podest_region() -> argparse.ArgumentParser:
    """Where the Podest stands in the camera image (podest.py)."""
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--podest", type=podest.parse_polygon, metavar="POINTS",
                        help="the Podest's top surface in the camera image, as x,y "
                             "points in shares of width and height, e.g. "
                             f'"{podest.format_polygon(podest.POLYGON)}" (the default); '
                             "used in the scenes with a Podest rule")
    parser.add_argument("--no-podest", action="store_true",
                        help="turn the Podest rule off in every scene")
    return parser


def scene() -> argparse.ArgumentParser:
    """The scene a run starts in (scenes.py)."""
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--scene", metavar="NAME",
                        help=f'a scene of {scenes.SCENES_FILE.name}, e.g. "Szene 1" '
                             f"(default: {scenes.DEFAULT_NAME})")
    return parser


def chosen_scene(args) -> scenes.Scene:
    """The scene named by --scene, or the defaults. Raises ValueError for a
    name the scenes file does not hold."""
    available = scenes.load()
    name = getattr(args, "scene", None) or scenes.DEFAULT_NAME
    if name not in available:
        raise ValueError(f"no scene {name!r}; scenes: {', '.join(available)}")
    return available[name]


def touchdesigner() -> argparse.ArgumentParser:
    """The two channels a run can open to TouchDesigner.

    Pixels and messages travel separately (knowledge/components/03_render.md),
    so each is turned on by its own flag. Host and port stay environment-only,
    as they are for the search side: the Probebuehne machine is not the machine
    this was written on.
    """
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--send-td", action="store_true",
                        help=f"announce each SITREP and the roster over OSC to "
                             f"{osc.TD_HOST}:{osc.TD_PORT}")
    parser.add_argument("--send-ndi", action="store_true",
                        help="publish the camera as an NDI source for TouchDesigner")
    parser.add_argument("--ndi-name", default=feed.NAME,
                        help=f"NDI source name (default: {feed.NAME})")
    parser.add_argument("--ndi-fps", type=float, default=feed.FPS,
                        help=f"frames per second sent (default: {feed.FPS:g})")
    return parser
