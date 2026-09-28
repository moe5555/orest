"""The Action-to-SITREP table: complete, in range, and aligned with its targets."""

import pytest

from action import model, sitrep_map
from sitrep import report


def test_the_table_covers_every_class_once_in_range():
    mapping = sitrep_map.load()
    assert len(mapping.names) == sitrep_map.CLASSES
    assert mapping.evidence.shape == (sitrep_map.CLASSES, len(sitrep_map.RATINGS))
    assert abs(mapping.evidence).max() <= sitrep_map.EVIDENCE


def test_every_mapped_rating_is_a_rating_of_the_report():
    assert set(sitrep_map.RATINGS) <= set(report.BEWERTUNGEN)


def test_mutual_classes_are_marked_as_pairs():
    mapping = sitrep_map.load()
    mutual = {*range(50, 61), *range(106, 121)}
    assert {index + 1 for index in mapping.pair.nonzero()[0]} == mutual


def test_class_names_match_the_model_labels():
    try:
        labels = model.labels()
    except FileNotFoundError:
        pytest.skip("NTU class list not present (data/models is gitignored)")
    assert sitrep_map.load().names == labels


@pytest.mark.parametrize("edit, message", [
    (lambda rows: rows[:-1], "classes 1-120"),
    (lambda rows: [rows[0].replace(",0,0,0,", ",0,6,0,", 1), *rows[1:]], "outside"),
])
def test_a_broken_table_is_refused(tmp_path, edit, message):
    header, *rows = sitrep_map.TABLE.read_text(encoding="utf-8").splitlines()
    broken = tmp_path / "sitrep_map.csv"
    broken.write_text("\n".join([header, *edit(rows)]), encoding="utf-8")
    with pytest.raises(ValueError, match=message):
        sitrep_map.load(broken)
