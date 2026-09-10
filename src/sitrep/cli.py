"""Command-line arguments shared by the SITREP entry points.

Capture sources, window timing and capture resolution are selected the same
way wherever they appear, so each group is defined once and attached to a
parser as a parent.

This module deliberately depends on nothing else in the package: the device
layer builds its own command line from these groups.
"""

import argparse

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
                        help=f"seconds per SITREP window (default: {WINDOW:g})")
    parser.add_argument("--windows", type=int, help="stop after this many windows")
    return parser


def resolution() -> argparse.ArgumentParser:
    """Requested camera capture resolution."""
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--width", type=int, help="requested capture width")
    parser.add_argument("--height", type=int, help="requested capture height")
    return parser
