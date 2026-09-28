"""A representative SITREP, shared by the report and rendering tests."""

from datetime import datetime

import pytest

from sitrep import report


@pytest.fixture
def bericht() -> report.Lagebericht:
    return report.Lagebericht(
        beschreibung="Klara tritt an den Tisch und spricht Jakob an; Probenarbeit an einer Szene.",
        personen=[
            report.Person(
                name="Klara",
                beschreibung="Dunkles Hemd, kurze Haare, steht mittig, zugewandt",
                auffaelligkeit=3,
            ),
            report.Person(
                name="Vielleicht: Jakob",
                beschreibung="Sitzt am Tisch, notiert",
                auffaelligkeit=4,
            ),
        ],
        szene=report.Szene(relevanz=6, eskalation=3, gefahr=2),
        prognose=[
            report.Verlauf(verlauf="Unterbrechung der Probe.", wahrscheinlichkeit=20),
            report.Verlauf(verlauf="Fortsetzung der Szene.", wahrscheinlichkeit=60),
            report.Verlauf(verlauf="Wechsel an den Tisch.", wahrscheinlichkeit=15),
        ],
        empfehlung="",
    )


@pytest.fixture
def eskaliert(bericht) -> report.Lagebericht:
    """The same report, with a scene past the intervention threshold."""
    return report.Lagebericht.model_validate({
        **bericht.model_dump(exclude={"einschreiten"}),
        "szene": {"relevanz": 8, "eskalation": 7, "gefahr": 4},
        "empfehlung": "Probe unterbrechen.",
    })


@pytest.fixture
def sitrep(bericht) -> report.Sitrep:
    return report.Sitrep(
        zeitfenster=report.Zeitfenster(
            beginn=datetime(2026, 9, 10, 14, 30, 0),
            ende=datetime(2026, 9, 10, 14, 30, 30),
            dauer_s=30.0,
        ),
        quelle=report.Quelle(bilder=3, ton_s=30.0),
        gesagt="Noch einmal von vorne, bitte.",
        anwesend=[
            report.Anwesend(name="Klara", erkannt=True),
            report.Anwesend(name="Vielleicht: Jakob", erkannt=False),
        ],
        # Klara's body was read; Jakob's face was seen without it.
        handlungen=[
            report.Handlung(name="Klara", risiko=0, menschlichkeit=4,
                            anlass_menschlichkeit="hugging other person 0.81", lesungen=12),
        ],
        latenz_s=5.8,
        bericht=bericht,
    )
