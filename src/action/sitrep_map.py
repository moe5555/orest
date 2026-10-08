"""The Action-to-SITREP mapping: what each NTU class says about a person.

knowledge/components/02_processing.md ("Calculating Values", Pose) keeps
activities and values apart: the recogniser names what a body does, and an
editable table says what that implies for the report's ratings per person.
The table is sitrep_map.csv beside this module, one row per NTU class:

    nr              class number, 1-120, in the order the network scores them
    klasse          the class name, as in label_map_ntu120.txt
    paar            1 for NTU's mutual actions, which it recorded with two people
    risiko,
    menschlichkeit  evidence for that rating, -5 to +5: positive raises it,
                    negative lowers it, 0 says nothing
    anmerkung       free text

A pair class has no direction: NTU does not record which of the two people
acts, so "punching/slapping other person" describes the one who hits and the
one who is hit alike.

`vorhersehbarkeit` has no column. It measures how closely a movement
resembles the rehearsals (sitrep/predictability.py), not a property of any
one activity.

The table holds evidence only. How it is weighed against the transcript,
trigger words and loudness is the SITREP formula's concern.
"""

import csv
from dataclasses import dataclass
from pathlib import Path

import numpy as np

TABLE = Path(__file__).with_name("sitrep_map.csv")

# Ratings the table carries evidence for, in column order. Each is a field of
# sitrep.report.Person.
RATINGS = ("risiko", "menschlichkeit")

CLASSES = 120
EVIDENCE = 5


@dataclass(frozen=True)
class Mapping:
    names: tuple[str, ...]      # (120,), NTU class order
    pair: np.ndarray            # (120,) bool
    evidence: np.ndarray        # (120, len(RATINGS)) int, -EVIDENCE to +EVIDENCE


def load(path: Path = TABLE) -> Mapping:
    """Read the table and check it covers every class once, in order, in range."""
    with open(path, encoding="utf-8", newline="") as file:
        rows = list(csv.DictReader(file))

    numbers = [int(row["nr"]) for row in rows]
    if numbers != list(range(1, CLASSES + 1)):
        raise ValueError(f"{path.name}: expected classes 1-{CLASSES} once each, in order")

    evidence = np.array([[int(row[rating]) for rating in RATINGS] for row in rows])
    if np.abs(evidence).max() > EVIDENCE:
        row = int(np.abs(evidence).max(axis=1).argmax()) + 1
        raise ValueError(f"{path.name}: class {row} has evidence outside ±{EVIDENCE}")

    return Mapping(
        names=tuple(row["klasse"] for row in rows),
        pair=np.array([row["paar"] == "1" for row in rows]),
        evidence=evidence,
    )
