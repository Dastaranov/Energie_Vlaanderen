"""Elke module van het pakket is importeerbaar.

Aanleiding: bij het hernoemen van `calculation/battery.py` naar
`batterySpec.py` bleef `simulator_battery.py` de oude naam importeren. De
volledige suite bleef groen — 809 tests — omdat geen enkele test die module
aanraakt. Ze was gewoon stuk, en dat zou pas gebleken zijn wanneer iemand het
simulatorscript startte.

Dat is dezelfde vorm als de rest van de fouten hier: niets faalt, er gebeurt
alleen minder dan je denkt. Een import is de goedkoopste controle die er is en
dekt precies het gat dat achterblijft bij een hernoeming, een verplaatsing naar
`experiments/remove/`, of een verwijderde functie die elders nog geïmporteerd
wordt.

Deze test doet bewust niet meer dan importeren. Wat een module *doet* hoort in
haar eigen testbestand; dat ze bestáát hoort hier.
"""
from __future__ import annotations

import importlib
from pathlib import Path

import pytest

pytestmark = pytest.mark.suite

PAKKET = Path(__file__).resolve().parents[1] / "src" / "energie_vlaanderen"


def _modulenamen() -> list[str]:
    namen = []
    for pad in sorted(PAKKET.rglob("*.py")):
        if "__pycache__" in pad.parts:
            continue
        # `__main__.py` draait bij import zijn eigen instappunt
        if pad.name == "__main__.py":
            continue
        delen = pad.relative_to(PAKKET.parent).with_suffix("").parts
        naam = ".".join(delen)
        namen.append(naam[: -len(".__init__")] if naam.endswith(".__init__") else naam)
    return namen


def test_er_zijn_modules_gevonden():
    # Een verkeerd pad zou elke test hieronder op een lege lijst laten slagen.
    assert len(_modulenamen()) > 40


@pytest.mark.parametrize("modulenaam", _modulenamen())
def test_module_importeert(modulenaam: str):
    importlib.import_module(modulenaam)
