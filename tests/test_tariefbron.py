"""Beide gegevensbronnen voldoen aan hetzelfde contract.

`Calculator` en `Kostberekening` waren getypeerd op `DataRepository`, de
CSV-lezer. Toen `DbDataRepository` erbij kwam werkte dat alleen doordat de twee
toevallig dezelfde methodes hadden: de uitwisselbaarheid was nergens vastgelegd,
en niets zou gemeld hebben als een van beide was gaan afwijken.

`TariefBron` legt die afspraak vast. Deze tests bewaken dat allebei de
implementaties eraan blijven voldoen — zonder databank, dus ze draaien in CI.
"""
from __future__ import annotations

import inspect

import pytest

from energie_vlaanderen.data.bron import TariefBron
from energie_vlaanderen.data.db_repository import DbDataRepository
from energie_vlaanderen.data.repository import DataRepository

BRONNEN = (DataRepository, DbDataRepository)


pytestmark = pytest.mark.rekenen


@pytest.mark.parametrize("bron", BRONNEN, ids=lambda k: k.__name__)
class TestContract:
    def test_alle_leden_van_het_protocol_bestaan(self, bron):
        for naam in ("dnb", "tariefjaar", "products", "dnb_for"):
            assert hasattr(bron, naam), f"{bron.__name__} mist {naam}"

    def test_products_heeft_dezelfde_parameters(self, bron):
        """De aanroeper geeft jaar, maand en segment positioneel mee en
        `energy`/`direction` als sleutelwoord. Wijkt een bron daarvan af, dan
        breekt ze pas bij een aanroep — en dat is precies waar deze test voor
        bestaat."""
        params = inspect.signature(bron.products).parameters
        for naam in ("year", "month", "segment", "energy", "direction"):
            assert naam in params, f"{bron.__name__}.products mist {naam}"
        for naam in ("energy", "direction"):
            assert params[naam].kind is inspect.Parameter.KEYWORD_ONLY

    def test_dnb_for_heeft_dezelfde_parameters(self, bron):
        params = inspect.signature(bron.dnb_for).parameters
        for naam in ("postcode", "gemeente", "energie_type"):
            assert naam in params, f"{bron.__name__}.dnb_for mist {naam}"


def test_het_protocol_beschrijft_precies_wat_de_berekening_aanraakt():
    """Het contract is bewust klein: groeit het, dan groeit ook wat een derde
    bron moet leveren. `Calculator` gebruikt `dnb`, `dnb_for` en `products`;
    `Kostberekening` daarnaast `tariefjaar`."""
    leden = {
        naam for naam in vars(TariefBron)
        if not naam.startswith("_") and naam != "mro"
    }
    assert leden == {"dnb", "tariefjaar", "products", "dnb_for"}
