"""Elk testbestand draagt precies één categoriemarker.

`tests/README.md` deelt de suite in acht domeinen in en stelt dat hun som de
hele suite is. Dat klopt vandaag, en zonder deze controle verjaart het bij het
eerste bestand dat erbij komt: een testbestand zonder marker draait nog steeds
mee in `pytest -q`, maar valt weg uit `pytest -m <categorie>`. De tests slagen,
de CI is groen, en toch wordt er een heel bestand niet meer gedraaid zodra
iemand per domein begint te draaien.

Dat is de foutvorm van dit project — stil minder doen, zonder uitzondering — en
daarom staat de indeling hier vast in plaats van in een afspraak.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.suite

CATEGORIEEN = frozenset(
    {
        "bronnen",
        "parsers",
        "scrape",
        "databank",
        "masterdata",
        "rekenen",
        "dossier",
        "cli",
        "suite",
    }
)

TESTMAP = Path(__file__).parent


def _module_markers(pad: Path) -> list[str]:
    """De markers uit `pytestmark` op modulehoogte, als lijst van namen."""
    boom = ast.parse(pad.read_text(encoding="utf-8"))
    gevonden: list[str] = []
    for knoop in boom.body:  # enkel modulehoogte, geen markers op klasse of functie
        if not isinstance(knoop, ast.Assign):
            continue
        if not any(
            isinstance(doel, ast.Name) and doel.id == "pytestmark"
            for doel in knoop.targets
        ):
            continue
        waarden = (
            knoop.value.elts
            if isinstance(knoop.value, (ast.List, ast.Tuple))
            else [knoop.value]
        )
        for waarde in waarden:
            # pytest.mark.<naam>, eventueel aangeroepen: pytest.mark.<naam>(...)
            if isinstance(waarde, ast.Call):
                waarde = waarde.func
            if isinstance(waarde, ast.Attribute):
                gevonden.append(waarde.attr)
    return gevonden


def _testbestanden() -> list[Path]:
    return sorted(TESTMAP.glob("test_*.py"))


def test_er_zijn_testbestanden_gevonden():
    # Zonder deze controle zou een verkeerd pad elke test hieronder laten
    # slagen op een lege lijst — geslaagd, en niets gecontroleerd.
    assert len(_testbestanden()) > 50


@pytest.mark.parametrize("pad", _testbestanden(), ids=lambda p: p.name)
def test_elk_testbestand_draagt_een_bekende_categorie(pad: Path):
    markers = _module_markers(pad)
    assert markers, (
        f"{pad.name} draagt geen `pytestmark` op modulehoogte. Voeg er één toe "
        f"uit {sorted(CATEGORIEEN)} en beschrijf het bestand in tests/README.md."
    )
    onbekend = set(markers) - CATEGORIEEN
    assert not onbekend, (
        f"{pad.name} draagt onbekende marker(s) {sorted(onbekend)}. "
        f"Bekend zijn {sorted(CATEGORIEEN)}; registreer nieuwe in pyproject.toml."
    )
    assert len(markers) == 1, (
        f"{pad.name} draagt {len(markers)} categorieën ({markers}). Eén bestand "
        "hoort in één domein, anders telt het dubbel in de som."
    )


def test_de_som_van_de_categorieen_is_de_hele_suite():
    """Geen enkel bestand valt tussen de categorieën door.

    De marker `integration` staat hier bewust buiten: die is orthogonaal en
    komt náást een categorie voor, niet in de plaats ervan.
    """
    per_categorie: dict[str, int] = {}
    for pad in _testbestanden():
        (marker,) = _module_markers(pad)
        per_categorie[marker] = per_categorie.get(marker, 0) + 1
    assert sum(per_categorie.values()) == len(_testbestanden())
    assert set(per_categorie) <= CATEGORIEEN
