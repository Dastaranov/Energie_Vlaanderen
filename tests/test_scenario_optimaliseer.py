"""Tests voor `scenario.optimaliseer`: de "zware calculator" die elk
elektriciteitscontract tegen een dossier afzet, optioneel met een batterij.

`kandidaat_contracten()` wordt getoetst tegen een nep-connectie (de vorm van
de SQL-query, niet een echte databank — dat is het domein van de
integratietests). De orchestratielogica (`optimaliseer_elektriciteitscontract`)
wordt getoetst door `bereken_dossier`/`kandidaat_contracten`/
`BatterijScenario.simuleer_metingen` te vervangen door nepversies: die
functies zelf hebben elk hun eigen tests (`test_gebruikers_orchestratie.py`,
`test_scenario_batterij.py`), hier gaat het om de opzoeklogica die ze
samenbrengt — welke kandidaat wint, en of een fout op één kandidaat de rest
niet laat vervallen (CLAUDE.md "Een fout op het ene punt laat het andere niet
vervallen").
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal as D

import pandas as pd
import pytest

from energie_vlaanderen.gebruikers.models import (
    Aansluitingspunt,
    Contracttype,
    EnergieType,
    Exactheidsklasse,
    Gebruiker,
    GebruikersError,
    Leveringscontract,
)
from energie_vlaanderen.gebruikers.orchestratie import DossierResultaat
from energie_vlaanderen.gebruikers.toml_io import Dossier
from energie_vlaanderen.scenario import optimaliseer
from energie_vlaanderen.scenario.batterij import BatterijScenario
from energie_vlaanderen.scenario.optimaliseer import (
    MET_BATTERIJ,
    MET_BATTERIJ_ARBITRAGE,
    ZONDER_BATTERIJ,
    kandidaat_contracten,
    optimaliseer_elektriciteitscontract,
)

pytestmark = pytest.mark.dossier


# ---------------------------------------------------------------------------
# kandidaat_contracten(): vorm van de SQL-query
# ---------------------------------------------------------------------------


class _NepResultaat:
    def __init__(self, rijen: list[tuple]) -> None:
        self._rijen = rijen

    def all(self):
        return self._rijen


class _NepConn:
    """Legt de query en de parameters vast, en geeft vaste rijen terug —
    genoeg om te toetsen dat `kandidaat_contracten()` de juiste filters en
    parameters gebruikt, zonder een echte databank."""

    def __init__(self, rijen: list[tuple]) -> None:
        self._rijen = rijen
        self.laatste_query = None
        self.laatste_params = None

    def execute(self, query, params=None):
        self.laatste_query = str(query)
        self.laatste_params = params
        return _NepResultaat(self._rijen)


def test_kandidaat_contracten_filtert_op_energie_type_segment_en_peildatum():
    conn = _NepConn([("Bolt", "Bolt Variabel", "variabel"), ("Bolt", "Bolt Variabel", "dynamisch")])

    kandidaten = kandidaat_contracten(conn, segment="Woning", peildatum=date(2026, 1, 1))

    assert "energie_type = 'elektriciteit'" in conn.laatste_query
    assert conn.laatste_params == {"segment": "Woning", "peildatum": date(2026, 1, 1)}
    assert kandidaten == [
        ("Bolt", "Bolt Variabel", Contracttype.VARIABEL),
        ("Bolt", "Bolt Variabel", Contracttype.DYNAMISCH),
    ]


def test_kandidaat_contracten_geeft_hetzelfde_product_in_twee_contracttypes_apart_terug():
    """Hetzelfde product kan zowel `variabel` als `dynamisch` bestaan (de
    optionele dynamische afrekening op hetzelfde contract) — dat zijn twee
    aparte keuzes voor een klant en dus twee aparte kandidaten, niet één."""
    conn = _NepConn([("Bolt", "Bolt Variabel", "variabel"), ("Bolt", "Bolt Variabel", "dynamisch")])

    kandidaten = kandidaat_contracten(conn, peildatum=date(2026, 1, 1))

    assert len(kandidaten) == 2
    assert len({c for _, _, c in kandidaten}) == 2


# ---------------------------------------------------------------------------
# optimaliseer_elektriciteitscontract(): orchestratie
# ---------------------------------------------------------------------------


def _punt() -> Aansluitingspunt:
    return Aansluitingspunt(Gebruiker().id, EnergieType.ELEKTRICITEIT, "9300", "Aalst")


def _dossier(punt: Aansluitingspunt, *, contracten=()) -> Dossier:
    return Dossier(
        bron=None, gebruiker=Gebruiker(), persoonsgegevens=None,
        aansluitingspunten=(punt,), meters=(), assets=(),
        contracten=contracten, verbruiksopgaven=(),
    )


class _NepBerekening:
    def __init__(self, totaal: D) -> None:
        self._totaal = totaal

    @property
    def totalen(self):
        return {"totaal": self._totaal}

    @property
    def exactheidsklasse(self):
        return Exactheidsklasse.SCENARIO


def _dossierresultaat(punt: Aansluitingspunt, totaal: D) -> DossierResultaat:
    return DossierResultaat(
        resultaten=((punt, _NepBerekening(totaal)),), mislukt=(), dataversie="test",
        nettarieven_jaren=(2026,), metingen=None, meetreeks=None,
        meetwaarschuwingen=(), markt=None,
    )


def _dossierresultaat_mislukt() -> DossierResultaat:
    return DossierResultaat(
        resultaten=(), mislukt=(("elektriciteit", "geen product gevonden"),), dataversie="test",
        nettarieven_jaren=(), metingen=None, meetreeks=None, meetwaarschuwingen=(), markt=None,
    )


def test_kiest_het_goedkoopste_contract_zonder_batterij(monkeypatch):
    punt = _punt()
    huidig_contract = Leveringscontract(
        aansluitingspunt_id=punt.id, leverancier="ENGIE", product="Easy",
        contracttype=Contracttype.VAST, geldig_van=date(2025, 1, 1),
    )
    dossier = _dossier(punt, contracten=(huidig_contract,))

    monkeypatch.setattr(
        optimaliseer, "kandidaat_contracten",
        lambda conn, **kw: [
            ("ENGIE", "Easy", Contracttype.VAST),
            ("Bolt", "Bolt Variabel", Contracttype.VARIABEL),
            ("Aspiravi", "Eco Plus", Contracttype.VARIABEL),
        ],
    )

    kosten = {"ENGIE": D("800"), "Bolt": D("650"), "Aspiravi": D("900")}

    def fake_bereken_dossier(dossier_variant, *, conn, settings, van, tot, **kwargs):
        (contract,) = dossier_variant.contracten
        return _dossierresultaat(punt, kosten[contract.leverancier])

    monkeypatch.setattr(optimaliseer, "bereken_dossier", fake_bereken_dossier)

    resultaat = optimaliseer_elektriciteitscontract(
        dossier, conn=object(), settings=object(), van=date(2026, 1, 1), tot=date(2027, 1, 1),
    )

    assert resultaat.huidige_kost_eur == D("800")
    assert resultaat.beste_zonder_batterij.leverancier == "Bolt"
    assert resultaat.beste_zonder_batterij.totaal_eur == D("650")
    assert resultaat.winst_contractwissel_alleen == D("150")
    assert resultaat.beste_met_batterij is None
    assert resultaat.winst_batterij_zelfde_contract is None


def test_een_opslagfout_verschijnt_als_waarschuwing_en_laat_het_resultaat_niet_vervallen(monkeypatch):
    """`conn=object()` heeft geen `.execute()` — `_bewaar_optimalisatie()`
    moet die fout opvangen (net als `ScenarioContext._bewaar_simulatie()`) en
    als waarschuwing teruggeven, niet de al berekende vergelijking laten
    crashen."""
    punt = _punt()
    dossier = _dossier(punt, contracten=(
        Leveringscontract(
            aansluitingspunt_id=punt.id, leverancier="ENGIE", product="Easy",
            contracttype=Contracttype.VAST, geldig_van=date(2025, 1, 1),
        ),
    ))
    monkeypatch.setattr(optimaliseer, "kandidaat_contracten", lambda conn, **kw: [])
    monkeypatch.setattr(optimaliseer, "bereken_dossier", lambda *a, **kw: _dossierresultaat(punt, D("800")))

    resultaat = optimaliseer_elektriciteitscontract(
        dossier, conn=object(), settings=object(), van=date(2026, 1, 1), tot=date(2027, 1, 1),
    )

    assert any("niet weggeschreven" in w for w in resultaat.warnings)
    assert resultaat.huidige_kost_eur == D("800")  # het resultaat zelf blijft geldig


def test_bewaar_false_slaat_niets_op_en_geeft_geen_opslagwaarschuwing(monkeypatch):
    punt = _punt()
    dossier = _dossier(punt, contracten=(
        Leveringscontract(
            aansluitingspunt_id=punt.id, leverancier="ENGIE", product="Easy",
            contracttype=Contracttype.VAST, geldig_van=date(2025, 1, 1),
        ),
    ))
    monkeypatch.setattr(optimaliseer, "kandidaat_contracten", lambda conn, **kw: [])
    monkeypatch.setattr(optimaliseer, "bereken_dossier", lambda *a, **kw: _dossierresultaat(punt, D("800")))

    aangeroepen = {"n": 0}

    def zou_niet_mogen(*a, **kw):
        aangeroepen["n"] += 1
        return None

    monkeypatch.setattr(optimaliseer, "_bewaar_optimalisatie", zou_niet_mogen)

    resultaat = optimaliseer_elektriciteitscontract(
        dossier, conn=object(), settings=object(), van=date(2026, 1, 1), tot=date(2027, 1, 1),
        bewaar=False,
    )

    assert aangeroepen["n"] == 0
    assert resultaat.warnings == ()


def test_een_falende_kandidaat_laat_de_rest_niet_vervallen(monkeypatch):
    """CLAUDE.md: "Een fout op het ene punt laat het andere niet vervallen"
    — hier toegepast op kandidaten in plaats van aansluitingspunten."""
    punt = _punt()
    huidig_contract = Leveringscontract(
        aansluitingspunt_id=punt.id, leverancier="ENGIE", product="Easy",
        contracttype=Contracttype.VAST, geldig_van=date(2025, 1, 1),
    )
    dossier = _dossier(punt, contracten=(huidig_contract,))

    monkeypatch.setattr(
        optimaliseer, "kandidaat_contracten",
        lambda conn, **kw: [
            ("ENGIE", "Easy", Contracttype.VAST),
            ("Weg", "Verdwenen Product", Contracttype.VARIABEL),
            ("Bolt", "Bolt Variabel", Contracttype.VARIABEL),
        ],
    )

    def fake_bereken_dossier(dossier_variant, *, conn, settings, van, tot, **kwargs):
        (contract,) = dossier_variant.contracten
        if contract.leverancier == "Weg":
            raise GebruikersError("Geen product gevonden voor maand 2026-03")
        if contract.leverancier == "ENGIE":
            return _dossierresultaat(punt, D("800"))
        return _dossierresultaat(punt, D("650"))

    monkeypatch.setattr(optimaliseer, "bereken_dossier", fake_bereken_dossier)

    resultaat = optimaliseer_elektriciteitscontract(
        dossier, conn=object(), settings=object(), van=date(2026, 1, 1), tot=date(2027, 1, 1),
    )

    gefaald = [k for k in resultaat.kandidaten if not k.gelukt]
    assert len(gefaald) == 1
    assert gefaald[0].leverancier == "Weg"
    assert "Geen product gevonden" in gefaald[0].fout
    # De echte winnaar staat er gewoon, ondanks de gefaalde kandidaat ertussen.
    assert resultaat.beste_zonder_batterij.leverancier == "Bolt"


def test_batterij_geeft_drie_modi_en_de_drie_gevraagde_deltas(monkeypatch):
    punt = _punt()
    huidig_contract = Leveringscontract(
        aansluitingspunt_id=punt.id, leverancier="ENGIE", product="Easy",
        contracttype=Contracttype.VAST, geldig_van=date(2025, 1, 1),
    )
    dossier = _dossier(punt, contracten=(huidig_contract,))
    batterij = BatterijScenario(merk="Marstek", model="Venus E")

    monkeypatch.setattr(
        optimaliseer, "kandidaat_contracten",
        lambda conn, **kw: [
            ("ENGIE", "Easy", Contracttype.VAST),
            ("Bolt", "Bolt Variabel", Contracttype.DYNAMISCH),
        ],
    )
    monkeypatch.setattr(
        BatterijScenario, "simuleer_metingen",
        lambda self, *a, **kw: (pd.DataFrame({"tijdstip": [], "afname_kwh": []}), (), ()),
    )
    monkeypatch.setattr(optimaliseer, "laad_markt", lambda settings, van, tot: None)

    # kost hangt af van (leverancier, of er metingen_override meegegeven is)
    def fake_bereken_dossier(dossier_variant, *, conn, settings, van, tot, **kwargs):
        (contract,) = [c for c in dossier_variant.contracten]
        met_batterij = "metingen_override" in kwargs
        if contract.leverancier == "ENGIE":
            return _dossierresultaat(punt, D("700") if met_batterij else D("800"))
        return _dossierresultaat(punt, D("600") if met_batterij else D("650"))

    monkeypatch.setattr(optimaliseer, "bereken_dossier", fake_bereken_dossier)

    resultaat = optimaliseer_elektriciteitscontract(
        dossier, conn=object(), settings=object(), van=date(2026, 1, 1), tot=date(2027, 1, 1),
        batterij=batterij,
    )

    assert resultaat.huidige_kost_eur == D("800")
    assert resultaat.beste_zonder_batterij.leverancier == "Bolt"
    assert resultaat.beste_zonder_batterij.totaal_eur == D("650")
    assert resultaat.beste_met_batterij.totaal_eur == D("600")
    assert resultaat.huidig_contract_met_batterij.totaal_eur == D("700")

    assert resultaat.winst_contractwissel_alleen == D("150")  # 800 - 650
    assert resultaat.winst_batterij_zelfde_contract == D("100")  # 800 - 700
    assert resultaat.winst_gecombineerd == D("200")  # 800 - 600

    # Zonder marktprijzen in de cache: geen aparte arbitragemodus, enkel
    # "zonder batterij" en "met batterij" per kandidaat.
    modi = {k.modus for k in resultaat.kandidaten}
    assert MET_BATTERIJ_ARBITRAGE not in modi
    assert {ZONDER_BATTERIJ, MET_BATTERIJ} <= modi


def test_dynamisch_contract_krijgt_ook_een_arbitragemodus_als_marktprijzen_beschikbaar_zijn(monkeypatch):
    punt = _punt()
    huidig_contract = Leveringscontract(
        aansluitingspunt_id=punt.id, leverancier="ENGIE", product="Easy",
        contracttype=Contracttype.VAST, geldig_van=date(2025, 1, 1),
    )
    dossier = _dossier(punt, contracten=(huidig_contract,))
    batterij = BatterijScenario(merk="Marstek", model="Venus E")

    monkeypatch.setattr(
        optimaliseer, "kandidaat_contracten",
        lambda conn, **kw: [
            ("ENGIE", "Easy", Contracttype.VAST),
            ("Bolt", "Bolt Variabel", Contracttype.DYNAMISCH),
        ],
    )
    monkeypatch.setattr(
        BatterijScenario, "simuleer_metingen",
        lambda self, *a, **kw: (pd.DataFrame({"tijdstip": [], "afname_kwh": []}), (), ()),
    )
    monkeypatch.setattr(
        optimaliseer, "laad_markt",
        lambda settings, van, tot: pd.DataFrame({"tijdstip": [date(2026, 1, 1)], "price_eur_mwh": [50.0]}),
    )

    def fake_bereken_dossier(dossier_variant, *, conn, settings, van, tot, **kwargs):
        (contract,) = dossier_variant.contracten
        return _dossierresultaat(punt, D("500"))

    monkeypatch.setattr(optimaliseer, "bereken_dossier", fake_bereken_dossier)

    resultaat = optimaliseer_elektriciteitscontract(
        dossier, conn=object(), settings=object(), van=date(2026, 1, 1), tot=date(2027, 1, 1),
        batterij=batterij,
    )

    dynamische_kandidaten = [k for k in resultaat.kandidaten if k.leverancier == "Bolt"]
    modi = {k.modus for k in dynamische_kandidaten}
    assert modi == {ZONDER_BATTERIJ, MET_BATTERIJ, MET_BATTERIJ_ARBITRAGE}

    # Het vaste ENGIE-contract krijgt geen arbitragemodus: die is enkel
    # zinvol op een dynamisch contract (zie `batterij.py`-moduledocstring).
    vaste_kandidaten = [k for k in resultaat.kandidaten if k.leverancier == "ENGIE"]
    assert MET_BATTERIJ_ARBITRAGE not in {k.modus for k in vaste_kandidaten}


def test_onvolledige_marktprijzen_schakelen_enkel_arbitrage_uit(monkeypatch):
    """De cache kan het venster gedeeltelijk dekken (ENTSO-E kent gaten) —
    dan geeft `simuleer_metingen()` een `DispatchError` bij de
    arbitrage-poging. Dat mag de rest van de vergelijking niet laten
    vervallen: enkel de arbitragemodus blijft dan achterwege."""
    from energie_vlaanderen.calculation.dispatch import DispatchError

    punt = _punt()
    huidig_contract = Leveringscontract(
        aansluitingspunt_id=punt.id, leverancier="ENGIE", product="Easy",
        contracttype=Contracttype.VAST, geldig_van=date(2025, 1, 1),
    )
    dossier = _dossier(punt, contracten=(huidig_contract,))
    batterij = BatterijScenario(merk="Marstek", model="Venus E")

    monkeypatch.setattr(
        optimaliseer, "kandidaat_contracten",
        lambda conn, **kw: [("Bolt", "Bolt Variabel", Contracttype.DYNAMISCH)],
    )

    aanroepen = {"n": 0}

    def fake_simuleer_metingen(self, *a, marktprijzen_override=None, **kw):
        aanroepen["n"] += 1
        if marktprijzen_override is not None:
            raise DispatchError("Voor 7159 van de 29760 dispatchintervallen is er geen marktprijs")
        return pd.DataFrame({"tijdstip": [], "afname_kwh": []}), (), ()

    monkeypatch.setattr(BatterijScenario, "simuleer_metingen", fake_simuleer_metingen)
    monkeypatch.setattr(
        optimaliseer, "laad_markt",
        lambda settings, van, tot: pd.DataFrame({"tijdstip": [date(2026, 1, 1)], "price_eur_mwh": [50.0]}),
    )
    monkeypatch.setattr(optimaliseer, "bereken_dossier", lambda *a, **kw: _dossierresultaat(punt, D("500")))

    resultaat = optimaliseer_elektriciteitscontract(
        dossier, conn=object(), settings=object(), van=date(2026, 1, 1), tot=date(2027, 1, 1),
        batterij=batterij,
    )

    assert aanroepen["n"] == 2  # de gewone batterijsimulatie én de mislukte arbitragepoging
    modi = {k.modus for k in resultaat.kandidaten}
    assert MET_BATTERIJ_ARBITRAGE not in modi
    assert {ZONDER_BATTERIJ, MET_BATTERIJ} <= modi


def test_weigert_zonder_elektriciteitsaansluiting():
    punt_gas = Aansluitingspunt(Gebruiker().id, EnergieType.GAS, "9300", "Aalst")
    dossier = _dossier(punt_gas)

    with pytest.raises(GebruikersError, match="geen elektriciteitsaansluiting"):
        optimaliseer_elektriciteitscontract(
            dossier, conn=object(), settings=object(), van=date(2026, 1, 1), tot=date(2027, 1, 1),
        )


def test_faalt_als_de_huidige_situatie_zelf_niet_doorgerekend_kan_worden(monkeypatch):
    punt = _punt()
    dossier = _dossier(punt)

    monkeypatch.setattr(optimaliseer, "kandidaat_contracten", lambda conn, **kw: [])
    monkeypatch.setattr(optimaliseer, "bereken_dossier", lambda *a, **kw: _dossierresultaat_mislukt())

    with pytest.raises(GebruikersError, match="basislijn"):
        optimaliseer_elektriciteitscontract(
            dossier, conn=object(), settings=object(), van=date(2026, 1, 1), tot=date(2027, 1, 1),
        )
