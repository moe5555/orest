"""The camera, sound source and cast a live run opens, as chosen on the operator page.

The selection is kept by the server rather than the page, so a run started
from any tab, and a restart from the SITREP page, opens the same sources. It
is saved to SOURCES_FILE and survives a restart of apollon-ui. Sources named
on the command line take precedence over the saved selection.

Sources are kept by name, not index: indices shift when hardware is attached
(sitrep/devices.py).
"""

import os
import threading
from pathlib import Path

from pydantic import BaseModel

from face import gallery
from sitrep import devices

REPO_ROOT = Path(__file__).resolve().parents[2]

# Where the last selection is kept. data/ holds machine-local state and is not
# versioned.
SOURCES_FILE = Path(os.environ.get("APOLLON_UI_SOURCES",
                                   REPO_ROOT / "data" / "interface" / "sources.json"))


# The cast folder offered on the operator page: one folder per person, each
# holding enrolment photographs (face/gallery.py).
CAST_DIR = REPO_ROOT / "data" / "cast"


class Sources(BaseModel):
    """A camera, a sound source and a cast, named as on the command line.

    The fields carry the names of --video, --audio, --audio-api, --audio-ndi
    and --cast, so session.resolve_sources reads either. Unset fields fall
    back as they do there: the first camera, the default microphone, no cast.
    `cast` is an absolute path.
    """

    video: str | None = None
    audio: str | None = None
    audio_api: str | None = None
    audio_ndi: str | None = None
    cast: str | None = None

    @classmethod
    def from_args(cls, args) -> "Sources":
        cast = getattr(args, "cast", None)
        return cls(video=args.video, audio=args.audio,
                   audio_api=args.audio_api, audio_ndi=args.audio_ndi,
                   cast=str(Path(cast).resolve()) if cast else None)

    def overridden_by(self, other: "Sources") -> "Sources":
        """These sources, with the camera and the sound replaced where `other` names them.

        The sound is replaced as a whole: a microphone and an NDI source
        exclude each other, and a host API belongs to its microphone.
        """
        sound = other if (other.audio or other.audio_api or other.audio_ndi) else self
        return Sources(video=other.video or self.video, audio=sound.audio,
                       audio_api=sound.audio_api, audio_ndi=sound.audio_ndi,
                       cast=other.cast or self.cast)


def cast_members(path: Path) -> list[str]:
    """The people a cast folder enrols: its folders holding at least one image."""
    if not path.is_dir():
        return []
    return sorted(folder.name for folder in path.iterdir() if folder.is_dir()
                  and any(image.suffix.lower() in gallery.IMAGE_SUFFIXES
                          for image in folder.iterdir()))


def cast_entry(path: Path) -> dict:
    """A cast folder as the page lists it: its path, a short label, its people."""
    try:
        label = path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        label = str(path)
    return {"path": str(path), "label": label, "names": cast_members(path)}


def available() -> dict:
    """The cameras and microphones on this machine, as the page lists them."""
    return {
        "cameras": [device.name for device in devices.list_video_devices()],
        "microphones": [{"name": device.name, "api": device.hostapi}
                        for device in devices.list_audio_devices()],
        "casts": [cast_entry(CAST_DIR)] if cast_members(CAST_DIR) else [],
    }


def resolved(sources: Sources) -> dict:
    """The devices `sources` resolves to on this machine, by full name.

    The page marks these as selected. A source that does not resolve is None,
    and the reason is listed under `errors`.
    """
    shown = {"camera": None, "sound": None, "cast": None, "errors": []}
    try:
        shown["camera"] = devices.resolve_video_device(sources.video).name
    except (ValueError, RuntimeError) as error:
        shown["errors"].append(str(error))

    if sources.audio_ndi:
        shown["sound"] = {"kind": "ndi", "name": sources.audio_ndi}
    else:
        try:
            device = devices.resolve_audio_device(sources.audio, sources.audio_api)
            shown["sound"] = {"kind": "microphone", "name": device.name, "api": device.hostapi}
        except (ValueError, RuntimeError) as error:
            shown["errors"].append(str(error))

    if sources.cast:
        entry = cast_entry(Path(sources.cast))
        if entry["names"]:
            shown["cast"] = entry
        else:
            shown["errors"].append(f"No cast in {entry['label']}: it holds no folder of photographs.")
    return shown


class Selection:
    """The sources the next run opens. Safe to read and change from any thread."""

    def __init__(self, sources: Sources | None = None, path: Path | None = None):
        self._sources = sources or Sources()
        self._path = path
        self._lock = threading.Lock()

    @classmethod
    def load(cls, path: Path, given: Sources) -> "Selection":
        """The selection saved at `path`, overridden by the sources in `given`.

        A missing or unreadable file starts from `given` alone.
        """
        try:
            saved = Sources.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            saved = Sources()
        return cls(saved.overridden_by(given), path)

    @property
    def sources(self) -> Sources:
        with self._lock:
            return self._sources

    def choose(self, sources: Sources) -> dict:
        """Take a new selection and save it. Returns what it resolves to.

        Raises ValueError when a device it names is not on this machine. An
        NDI source is not looked for here; a missing one is reported when the
        run starts (ndi_audio.Receiving).
        """
        shown = resolved(sources)
        if shown["errors"]:
            raise ValueError("\n".join(shown["errors"]))
        with self._lock:
            self._sources = sources
            if self._path is not None:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                self._path.write_text(sources.model_dump_json(indent=2), encoding="utf-8")
        return shown
