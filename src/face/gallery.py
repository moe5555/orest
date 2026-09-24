"""Cast enrolment: photographs of a person become that person's identity.

A gallery is built from a folder per cast member, each holding a few images of
them, and the folder name is the name the SITREP will report. This is the
"provide the system with images of each team member" of
knowledge/components/02_processing.md.

A person is kept as the set of their enrolled vectors rather than one average.
Enrolment images differ in angle and lighting on purpose, and averaging a
profile and a frontal view produces a vector that matches neither; taking the
best match over the set means one usable enrolment image is enough to recognise
a pose, and adding images can only help.

A match is a name only above a similarity threshold. Below it the face is
reported as unknown, which is a substantive choice: the alternative is a
confident wrong name on an actor the system has never seen, and the SITREP's
standing problem is invention rather than silence (claude_concerns.md, "The
SITREP content is not trustworthy yet").

Inspect an enrolment, and how confusable its members are, with:

    python -m face.gallery data/cast
"""

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from . import detect, embed

# Cosine similarity below which a face is reported as unknown rather than
# named. ArcFace places different identities near zero and the same identity
# well above it; this sits high in the ambiguous band, trading recall for the
# near-absence of wrong names.
THRESHOLD = 0.4

IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png", ".bmp", ".webp")

# Enrolment images are chosen by hand, so the face meant is the prominent one.
# A smaller face in the frame is a bystander.
_LARGEST = 0


@dataclass(frozen=True)
class Match:
    """The best enrolled identity for one probe face."""

    name: str | None
    similarity: float
    source: Path | None

    @property
    def known(self) -> bool:
        return self.name is not None


class Gallery:
    """Enrolled cast members, and the faces a probe is matched against."""

    def __init__(self, names: list[str], vectors: np.ndarray,
                 owners: np.ndarray, sources: list[Path]):
        self.names = names
        self.vectors = vectors    # (enrolled faces, 512)
        self.owners = owners      # index into names, per vector
        self.sources = sources    # image each vector came from

    def __len__(self) -> int:
        return len(self.names)

    def counts(self) -> dict[str, int]:
        """Enrolled faces per name."""
        return {name: int((self.owners == index).sum())
                for index, name in enumerate(self.names)}

    def match(self, probes: np.ndarray, threshold: float = THRESHOLD) -> list[Match]:
        """Identify probe embeddings against the gallery."""
        similarities = embed.similarity(probes, self.vectors)
        best = similarities.argmax(axis=1)
        return [
            Match(self.names[self.owners[column]], float(row[column]), self.sources[column])
            if row[column] >= threshold else Match(None, float(row[column]), None)
            for row, column in zip(similarities, best)
        ]

    def separation(self) -> np.ndarray:
        """Highest similarity between each pair of enrolled people.

        The diagonal is how consistent one person's own enrolment images are;
        everything off it is how confusable two cast members are, and a high
        off-diagonal value is a warning about the enrolment, not about the
        rehearsal.
        """
        similarities = embed.similarity(self.vectors, self.vectors)
        pairs = np.zeros((len(self.names), len(self.names)))
        for left in range(len(self.names)):
            for right in range(len(self.names)):
                block = similarities[np.ix_(self.owners == left, self.owners == right)]
                if left == right:
                    # Exclude each vector's similarity with itself, which is 1.
                    block = block[~np.eye(len(block), dtype=bool)]
                pairs[left, right] = block.max() if block.size else np.nan
        return pairs


def enrol_image(path: Path) -> np.ndarray | None:
    """Embed the principal face of one enrolment image."""
    image = cv2.imread(str(path))
    if image is None:
        raise RuntimeError(f"Could not read {path}")

    faces = detect.detect(image)
    if not faces:
        return None
    return embed.embed(image, [faces[_LARGEST]])[0]


def enrol(root: Path) -> tuple[Gallery, list[Path]]:
    """Build a gallery from a folder of per-person folders.

    Returns the gallery and the enrolment images in which no face was found,
    which are worth seeing: an image that contributes nothing is usually a
    photograph of the person from too far away.
    """
    names, vectors, owners, sources, skipped = [], [], [], [], []

    for folder in sorted(path for path in root.iterdir() if path.is_dir()):
        index = len(names)
        found = False
        for image in sorted(path for path in folder.iterdir()
                            if path.suffix.lower() in IMAGE_SUFFIXES):
            vector = enrol_image(image)
            if vector is None:
                skipped.append(image)
                continue
            vectors.append(vector)
            owners.append(index)
            sources.append(image)
            found = True
        if found:
            names.append(folder.name)

    if not names:
        raise RuntimeError(f"No enrolment images with a detectable face under {root}")

    return Gallery(names, np.stack(vectors), np.array(owners), sources), skipped


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("root", type=Path, help="folder holding one folder per person")
    args = parser.parse_args(argv)

    gallery, skipped = enrol(args.root)

    print(f"{len(gallery)} enrolled from {args.root}")
    for name, count in gallery.counts().items():
        print(f"  {name:<20} {count} face{'s' if count != 1 else ''}")
    for path in skipped:
        print(f"  no face found in {path}", file=sys.stderr)

    print("\nhighest similarity between enrolled people")
    pairs = gallery.separation()
    print(" " * 20 + "".join(f"{name[:11]:>12}" for name in gallery.names))
    for index, name in enumerate(gallery.names):
        row = "".join(f"{value:12.2f}" for value in pairs[index])
        print(f"  {name:<18}{row}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
