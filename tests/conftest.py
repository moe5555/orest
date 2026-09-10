"""A representative SITREP, shared by the report and rendering tests."""

from datetime import datetime

import pytest

from sitrep import report


@pytest.fixture
def bericht() -> report.Lagebericht:
    return report.Lagebericht(
        lage="Zwei Personen im Raum, Probenarbeit an einer Szene.",
        personen=[
            report.Person(
                kennung="P-01",
                merkmale="Dunkles Hemd, kurze Haare",
                taetigkeit="Steht mittig, spricht in Richtung P-02",
                verantwortungsvoll=3, menschlich=4, gefahr=0, kollaborativ=4,
            ),
            report.Person(
                kennung="P-02",
                merkmale="",
                taetigkeit="Sitzt am Tisch, notiert",
                verantwortungsvoll=2, menschlich=3, gefahr=5, kollaborativ=1,
            ),
        ],
        ereignisse=["P-01 tritt an den Tisch", "Kurze Unterbrechung"],
        prognose="Fortsetzung der Probe.",
        empfehlung="Keine Massnahme.",
        vertrauen=3,
    )


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
        latenz_s=5.8,
        bericht=bericht,
    )
