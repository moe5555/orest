"""Video and audio input device enumeration, selection and verification.

Implements step 2 of the Realtime-SITREP in knowledge/components/02_processing.md
("Set up capture loop - select video and audio source").

Devices are addressed by name rather than by index. DirectShow and PortAudio
indices shift whenever hardware is attached or removed, and the rehearsal setup
replaces the test webcam with dedicated cameras and microphones
(knowledge/components/01_capture.md, "Hardware"), so an index recorded today
will not refer to the same device on the Probebuehne. Names survive re-plugging
and reboots.

Video enumeration goes through DirectShow and is therefore Windows-only,
matching the inference PC the SITREP runs on.

Run directly to list devices or to verify a selection:

    python -m sitrep.devices --list
    python -m sitrep.devices --check --video "FHD WebCam" --audio-api WASAPI
"""

import argparse
import sys
import time
from dataclasses import dataclass

import cv2
import numpy as np
import sounddevice as sd
from pygrabber.dshow_graph import FilterGraph

from . import cli

# Level meter floor. Room tone on the built-in array sits around -75 dBFS.
_DBFS_FLOOR = -80.0

# Width in pixels of the preview level meter.
_METER_WIDTH = 300


@dataclass(frozen=True)
class VideoDevice:
    index: int
    name: str


@dataclass(frozen=True)
class AudioDevice:
    index: int
    name: str
    hostapi: str
    hostapi_index: int
    channels: int
    samplerate: float


def list_video_devices() -> list[VideoDevice]:
    """Enumerate DirectShow video capture devices.

    Indices are the ones cv2.VideoCapture accepts under the CAP_DSHOW backend.
    Virtual cameras (OBS, headset passthrough) are listed alongside physical
    ones and are indistinguishable at this layer; the name tells them apart.
    """
    return [VideoDevice(i, name) for i, name in enumerate(FilterGraph().get_input_devices())]


def list_audio_devices() -> list[AudioDevice]:
    """Enumerate input-capable audio devices.

    A single physical microphone is reported once per host API (MME,
    DirectSound, WASAPI, WDM-KS on Windows), so duplicate names are expected.
    The host API determines latency and how much processing Windows applies
    before the signal arrives: MME additionally truncates names at 31
    characters, WDM-KS bypasses the audio engine and delivers the hottest
    signal but may demand exclusive access to the device.
    """
    hostapis = sd.query_hostapis()
    return [
        AudioDevice(
            index=index,
            name=device["name"],
            hostapi=hostapis[device["hostapi"]]["name"],
            hostapi_index=device["hostapi"],
            channels=device["max_input_channels"],
            samplerate=device["default_samplerate"],
        )
        for index, device in enumerate(sd.query_devices())
        if device["max_input_channels"] > 0
    ]


def _select(spec, devices, kind, describe):
    """Resolve a device index or case-insensitive name fragment to one device."""
    if not devices:
        raise RuntimeError(f"No {kind} input devices found.")

    if spec is None:
        return devices[0]

    text = str(spec).strip()
    if text.isdigit():
        index = int(text)
        for device in devices:
            if device.index == index:
                return device
        raise ValueError(f"No {kind} device with index {index}. Available:\n{describe(devices)}")

    matches = [d for d in devices if text.casefold() in d.name.casefold()]
    if not matches:
        raise ValueError(f"No {kind} device matching {text!r}. Available:\n{describe(devices)}")
    if len(matches) > 1:
        raise ValueError(
            f"{text!r} matches {len(matches)} {kind} devices. "
            f"Narrow the name or give an index:\n{describe(matches)}"
        )
    return matches[0]


def resolve_video_device(spec=None) -> VideoDevice:
    """Resolve a camera by index or name fragment; defaults to the first camera."""
    return _select(spec, list_video_devices(), "video", format_video_devices)


def resolve_audio_device(spec=None, hostapi=None) -> AudioDevice:
    """Resolve a microphone by index or name fragment.

    Defaults to the PortAudio default input, which follows the microphone
    selected in the Windows sound settings. Because one microphone appears
    under every host API, a name fragment alone is usually ambiguous; pass
    hostapi to narrow it.
    """
    candidates = list_audio_devices()
    default_index = sd.default.device[0]
    publisher = "PortAudio"

    if hostapi is not None:
        match = next(
            ((index, api) for index, api in enumerate(sd.query_hostapis())
             if hostapi.casefold() in api["name"].casefold()),
            None,
        )
        if match is None:
            raise ValueError(f"No audio host API matching {hostapi!r}.")
        api_index, api = match
        candidates = [d for d in candidates if d.hostapi_index == api_index]
        # Each host API publishes its own default input.
        default_index = api["default_input_device"]
        publisher = api["name"]

    if spec is None:
        for device in candidates:
            if device.index == default_index:
                return device
        # PortAudio reports -1 where a host API publishes no default input.
        # Naming a device is then the only way to say which one is wanted:
        # taking the first of the list would select whatever enumerates first,
        # such as a virtual microphone.
        raise ValueError(
            f"{publisher} publishes no default input device. Select one by "
            f"name or index:\n{format_audio_devices(candidates)}"
        )

    return _select(spec, candidates, "audio", format_audio_devices)


def resolve(video_spec=None, audio_spec=None, hostapi=None) -> tuple[VideoDevice, AudioDevice]:
    """Resolve the camera and the microphone for a capture session."""
    return resolve_video_device(video_spec), resolve_audio_device(audio_spec, hostapi)


def describe(video: VideoDevice, audio: AudioDevice) -> str:
    """One line per selected source, for an entry point to print at startup."""
    return (f"video:  [{video.index}] {video.name}\n"
            f"audio:  [{audio.index}] {audio.name} ({audio.hostapi})")


def open_video(device: VideoDevice, width=None, height=None) -> cv2.VideoCapture:
    """Open a camera, optionally requesting a capture resolution.

    Cameras silently fall back to a supported mode when the requested
    resolution is unavailable, so read the actual size back from the capture
    rather than assuming the request was honoured.
    """
    capture = cv2.VideoCapture(device.index, cv2.CAP_DSHOW)
    if not capture.isOpened():
        raise RuntimeError(f"Could not open video device [{device.index}] {device.name!r}.")
    if width:
        capture.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    if height:
        capture.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    return capture


def dbfs(rms: float) -> float:
    """Convert a linear RMS amplitude to dBFS, floored for display."""
    return max(_DBFS_FLOOR, 20 * np.log10(rms)) if rms > 0 else _DBFS_FLOOR


def format_video_devices(devices) -> str:
    return "\n".join(f"  [{d.index}] {d.name}" for d in devices)


def format_audio_devices(devices) -> str:
    return "\n".join(
        f"  [{d.index:>2}] {d.name:<48} {d.hostapi:<20} "
        f"{d.channels}ch @ {d.samplerate / 1000:g} kHz"
        for d in devices
    )


def check(video_spec=None, audio_spec=None, hostapi=None, seconds=10.0, preview=True,
          width=None, height=None):
    """Capture from the selected camera and microphone and report what arrives."""
    video = resolve_video_device(video_spec)
    audio = resolve_audio_device(audio_spec, hostapi)

    print(f"video: [{video.index}] {video.name}")
    print(f"audio: [{audio.index}] {audio.name} ({audio.hostapi})")

    level = {"rms": 0.0, "peak": 0.0}

    def on_audio(indata, frames, time_info, status):
        if status:
            print(f"audio status: {status}", file=sys.stderr)
        level["rms"] = float(np.sqrt(np.mean(indata**2)))
        level["peak"] = max(level["peak"], float(np.max(np.abs(indata))))

    capture = open_video(video, width, height)
    width_actual = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    height_actual = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    frames = 0
    started = time.monotonic()

    try:
        with sd.InputStream(
            device=audio.index,
            channels=1,
            samplerate=int(audio.samplerate),
            callback=on_audio,
        ):
            while True:
                elapsed = time.monotonic() - started
                if seconds and elapsed >= seconds:
                    break

                ok, frame = capture.read()
                if not ok:
                    print("video read failed", file=sys.stderr)
                    break
                frames += 1

                if preview:
                    _draw_overlay(frame, video, audio, frames / max(elapsed, 1e-6), level["rms"])
                    cv2.imshow("Orest SITREP - source check", frame)
                    if cv2.waitKey(1) & 0xFF in (ord("q"), 27):
                        break
                elif frames % 30 == 0:
                    print(f"  {elapsed:5.1f}s  {frames:4d} frames  {dbfs(level['rms']):6.1f} dBFS")
    finally:
        capture.release()
        if preview:
            cv2.destroyAllWindows()

    elapsed = time.monotonic() - started
    print(
        f"\n{frames} frames in {elapsed:.1f}s ({frames / max(elapsed, 1e-6):.1f} fps) "
        f"at {width_actual}x{height_actual}\n"
        f"audio peak {dbfs(level['peak']):.1f} dBFS"
    )


def _draw_overlay(frame, video, audio, fps, rms):
    """Draw source names, frame rate and an audio level meter onto a preview frame."""
    lines = [
        f"{video.name}  {fps:.1f} fps",
        f"{audio.name} ({audio.hostapi})",
    ]
    for row, text in enumerate(lines):
        origin = (10, 24 + row * 22)
        # Dark stroke behind the text keeps it legible over a bright stage.
        cv2.putText(frame, text, origin, cv2.FONT_HERSHEY_SIMPLEX, 0.55,
                    (0, 0, 0), 3, cv2.LINE_AA)
        cv2.putText(frame, text, origin, cv2.FONT_HERSHEY_SIMPLEX, 0.55,
                    (255, 255, 255), 1, cv2.LINE_AA)

    level = dbfs(rms)
    filled = int(_METER_WIDTH * (level - _DBFS_FLOOR) / -_DBFS_FLOOR)
    top = frame.shape[0] - 34
    cv2.rectangle(frame, (10, top), (10 + _METER_WIDTH, top + 16), (60, 60, 60), -1)
    cv2.rectangle(frame, (10, top), (10 + filled, top + 16), (80, 220, 80), -1)
    cv2.putText(frame, f"{level:6.1f} dBFS", (20 + _METER_WIDTH, top + 14),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__.splitlines()[0],
        parents=[cli.sources(), cli.resolution()],
    )
    parser.add_argument("--list", action="store_true", help="list available devices and exit")
    parser.add_argument("--check", action="store_true", help="capture from the selected devices")
    parser.add_argument("--seconds", type=float, default=10.0,
                        help="check duration; 0 runs until q/ESC in the preview "
                             "window, or Ctrl+C without it (default: 10)")
    parser.add_argument("--no-preview", action="store_true",
                        help="report levels on stdout instead of opening a window")
    args = parser.parse_args(argv)

    if args.check:
        try:
            check(
                video_spec=args.video,
                audio_spec=args.audio,
                hostapi=args.audio_api,
                seconds=args.seconds,
                preview=not args.no_preview,
                width=args.width,
                height=args.height,
            )
        except (ValueError, RuntimeError) as error:
            print(error, file=sys.stderr)
            return 1
        return 0

    print("Video devices")
    print(format_video_devices(list_video_devices()) or "  none")
    print("\nAudio input devices")
    print(format_audio_devices(list_audio_devices()) or "  none")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
