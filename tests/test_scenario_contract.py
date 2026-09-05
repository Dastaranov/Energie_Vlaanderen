"""Tests voor `scenario.contract.AnderContractScenario`.

`pas_toe()` is pure dossiersurgerie (geen databank, geen rekenengine) — het
vervangt de contracten van één aansluitingspunt door een hypothetisch contract
via `dataclasses.replace()`. Wat hier vastligt: het origineel wordt nooit
gemuteerd, alleen het aansluitingspunt van het gekozen `energie_type` wordt
geraakt, en zonder expliciete periode volgt het hypothetische contract exact
dezelfde contractgrenzen als het dossier al had.

Die laatste eigenschap is een regressietest voor een echte fout: een eerdere
versie verving de hele contracthistoriek door één doorlopend contract. Tegen
de echte databank gaf dat "Meerdere verbruiksopgaven overlappen ..." — twee
opgaven die elk bij hun eigen contractperiode hoorden, overlapten plots
dezelfde, bredere deelperiode zodra de contractwissel ertussen verdween.
"""
from __future__ import annotations

from datetime import date

import pytest

from energie_vlaanderen.gebruikers.models import (
    Contracttype,
    EnergieType,
    Gebruiker,
    Leveringscontract,
)
from energie_vlaanderen.gebruikers.toml_io import Dossier
from energie_vlaanderen.scenario.contract import AnderContractScenario

pytestmark = pytest.mark.dossier


def _dossier(*, elektriciteit, gas=None) -> Dossier:
    gebruiker = Gebruiker()
    aansluitingspunten = [elektriciteit] + ([gas] if gas is not None else [])
    contracten = []
    for punt in aansluitingspunten:
        contracten.append(
            Leveringscontract(
                aansluitingspunt_id=punt.id,
                leverancier="Bestaand",
                product="Bestaand Vast",
                contracttype=Contracttype.VAST,
                geldig_van=date(2024, 1, 1),
            )
        )
    return Dossier(
        bron=None,  # type: ignore[arg-type]
        gebruiker=gebruiker,
        persoonsgegevens=None,
        aansluitingspunten=tuple(aansluitingspunten),
        meters=(),
        assets=(),
        contracten=tuple(contracten),
        verbruiksopgaven=(),
    )


@pytest.fixture
def elektriciteitspunt():
    from energie_vlaanderen.gebruikers.models import Aansluitingspunt

    return Aansluitingspunt(Gebruiker().id, EnergieType.ELEKTRICITEIT, "9300", "Aalst")


@pytest.fixture
def gaspunt():
    from energie_vlaanderen.gebruikers.models import Aansluitingspunt

    return Aansluitingspunt(Gebruiker().id, EnergieType.GAS, "9300", "Aalst")


def test_vervangt_het_contract_van_het_gekozen_energietype(elektriciteitspunt):
    dossier = _dossier(elektriciteit=elektriciteitspunt)
    scenario = AnderContractScenario(
        energie_type=EnergieType.ELEKTRICITEIT,
        leverancier="Bolt",
        product="Bolt Variabel",
        contracttype=Contracttype.VARIABEL,
    )

    gewijzigd = scenario.pas_toe(dossier)

    (contract,) = gewijzigd.contracten_van(elektriciteitspunt)
    assert contract.leverancier == "Bolt"
    assert contract.product == "Bolt Variabel"
    assert contract.contracttype is Contracttype.VARIABEL
    assert contract.bron == "scenario:ander_contract"


def test_muteert_het_origineel_niet(elektriciteitspunt):
    dossier = _dossier(elektriciteit=elektriciteitspunt)
    origineel_contracten = dossier.contracten
    scenario = AnderContractScenario(
        energie_type=EnergieType.ELEKTRICITEIT,
        leverancier="Bolt",
        product="Bolt Variabel",
        contracttype=Contracttype.VARIABEL,
    )

    scenario.pas_toe(dossier)

    assert dossier.contracten is origineel_contracten
    assert dossier.contracten_van(elektriciteitspunt)[0].leverancier == "Bestaand"


def test_raakt_het_andere_aansluitingspunt_niet(elektriciteitspunt, gaspunt):
    dossier = _dossier(elektriciteit=elektriciteitspunt, gas=gaspunt)
    scenario = AnderContractScenario(
        energie_type=EnergieType.ELEKTRICITEIT,
        leverancier="Bolt",
        product="Bolt Variabel",
        contracttype=Contracttype.VARIABEL,
    )

    gewijzigd = scenario.pas_toe(dossier)

    assert gewijzigd.contracten_van(gaspunt)[0].leverancier == "Bestaand"
    assert gewijzigd.contracten_van(elektriciteitspunt)[0].leverancier == "Bolt"
    # Het totaal aantal contracten blijft gelijk: één vervangen, niet toegevoegd.
    assert len(gewijzigd.contracten) == len(dossier.contracten)


def test_weigert_een_onbekend_aansluitingspunt(elektriciteitspunt):
    dossier = _dossier(elektriciteit=elektriciteitspunt)
    scenario = AnderContractScenario(
        energie_type=EnergieType.GAS,
        leverancier="Bolt",
        product="Bolt Vast",
        contracttype=Contracttype.VAST,
    )

    with pytest.raises(ValueError, match="geen aansluitingspunt"):
        scenario.pas_toe(dossier)


def test_bewaart_bestaande_contractgrenzen_bij_meerdere_contracten(elektriciteitspunt):
    """De regressietest zelf: twee opeenvolgende contracten moeten twee
    hypothetische contracten opleveren, elk met dezelfde grenzen als het
    origineel — niet één doorlopend contract dat de wissel wegveegt."""
    dossier = Dossier(
        bron=None, gebruiker=Gebruiker(), persoonsgegevens=None,
        aansluitingspunten=(elektriciteitspunt,), meters=(), assets=(),
        contracten=(
            Leveringscontract(
                aansluitingspunt_id=elektriciteitspunt.id, leverancier="Eerste",
                product="Eerste Vast", contracttype=Contracttype.VAST,
                geldig_van=date(2025, 6, 25), geldig_tot=date(2025, 10, 28),
            ),
            Leveringscontract(
                aansluitingspunt_id=elektriciteitspunt.id, leverancier="Tweede",
                product="Tweede Vast", contracttype=Contracttype.VAST,
                geldig_van=date(2025, 10, 28), geldig_tot=None,
            ),
        ),
        verbruiksopgaven=(),
    )
    scenario = AnderContractScenario(
        energie_type=EnergieType.ELEKTRICITEIT,
        leverancier="Bolt", product="Bolt Variabel", contracttype=Contracttype.VARIABEL,
    )

    gewijzigd = scenario.pas_toe(dossier)

    contracten = sorted(gewijzigd.contracten_van(elektriciteitspunt), key=lambda c: c.geldig_van)
    assert len(contracten) == 2
    assert contracten[0].geldig_van == date(2025, 6, 25)
    assert contracten[0].geldig_tot == date(2025, 10, 28)
    assert contracten[1].geldig_van == date(2025, 10, 28)
    assert contracten[1].geldig_tot is None
    assert all(c.leverancier == "Bolt" for c in contracten)


def test_expliciete_periode_geeft_wel_een_doorlopend_contract(elektriciteitspunt):
    """Wie zelf `geldig_van`/`geldig_tot` meegeeft, vraagt bewust om één
    doorlopend contract (bv. "wat als ik van bij het begin dit ene contract
    had") — dat blijft de expliciete-override-vorm."""
    dossier = Dossier(
        bron=None, gebruiker=Gebruiker(), persoonsgegevens=None,
        aansluitingspunten=(elektriciteitspunt,), meters=(), assets=(),
        contracten=(
            Leveringscontract(
                aansluitingspunt_id=elektriciteitspunt.id, leverancier="Eerste",
                product="Eerste Vast", contracttype=Contracttype.VAST,
                geldig_van=date(2025, 6, 25), geldig_tot=date(2025, 10, 28),
            ),
            Leveringscontract(
                aansluitingspunt_id=elektriciteitspunt.id, leverancier="Tweede",
                product="Tweede Vast", contracttype=Contracttype.VAST,
                geldig_van=date(2025, 10, 28), geldig_tot=None,
            ),
        ),
        verbruiksopgaven=(),
    )
    scenario = AnderContractScenario(
        energie_type=EnergieType.ELEKTRICITEIT,
        leverancier="Bolt", product="Bolt Variabel", contracttype=Contracttype.VARIABEL,
        geldig_van=date(2025, 6, 25),
    )

    gewijzigd = scenario.pas_toe(dossier)

    (contract,) = gewijzigd.contracten_van(elektriciteitspunt)
    assert contract.geldig_van == date(2025, 6, 25)
    assert contract.geldig_tot is None


def test_zonder_bestaand_contract_geeft_een_doorlopend_contract(elektriciteitspunt):
    dossier = Dossier(
        bron=None, gebruiker=Gebruiker(), persoonsgegevens=None,
        aansluitingspunten=(elektriciteitspunt,), meters=(), assets=(),
        contracten=(), verbruiksopgaven=(),
    )
    scenario = AnderContractScenario(
        energie_type=EnergieType.ELEKTRICITEIT,
        leverancier="Bolt", product="Bolt Variabel", contracttype=Contracttype.VARIABEL,
    )

    gewijzigd = scenario.pas_toe(dossier)

    (contract,) = gewijzigd.contracten_van(elektriciteitspunt)
    assert contract.geldig_tot is None


def test_naam_en_omschrijving_worden_automatisch_ingevuld(elektriciteitspunt):
    scenario = AnderContractScenario(
        energie_type=EnergieType.ELEKTRICITEIT,
        leverancier="Bolt",
        product="Bolt Variabel",
        contracttype=Contracttype.VARIABEL,
    )
    assert "Bolt" in scenario.naam
    assert "Bolt Variabel" in scenario.omschrijving
