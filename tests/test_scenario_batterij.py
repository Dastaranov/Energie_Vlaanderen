"""Tests voor `scenario.batterij.BatterijScenario` en `scenario.reeksen`.

`voer_uit()` zelf (de volledige dispatch + herberekening) heeft een echte
databank nodig en wordt niet hier getoetst — dat is het domein van
`test_dispatch.py` (de fysieke dispatchlus) en de bestaande
`Kostberekening`-tests (de financiële kant). Wat hier zonder databank
getoetst wordt: dossiersurgerie (`pas_toe()`) en de reeksopbouw in
`scenario.reeksen`, met een minimale nep-connectie.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal as D

import pandas as pd
import pytest

from energie_vlaanderen.gebruikers.models import (
    Aansluitingspunt,
    AssetType,
    Contracttype,
    EnergieType,
    Gebruiker,
    InstallatieAsset,
    Leveringscontract,
    Topologie,
    Verbruiksopgave,
)
from energie_vlaanderen.gebruikers.orchestratie import DossierResultaat
from energie_vlaanderen.gebruikers.schatting import SchattingError
from energie_vlaanderen.gebruikers.toml_io import Dossier
from energie_vlaanderen.scenario.batterij import BatterijScenario, contract_is_overal_dynamisch
from energie_vlaanderen.scenario.reeksen import productiereeks, verbruiksreeks

pytestmark = pytest.mark.dossier


class _NepResultaat:
    """Ondersteunt zowel `.all()` als rechtstreekse iteratie, want
    `gewichten_uit_databank()` gebruikt het eerste en
    `dichtstbijzijnd_beschikbaar_jaar()` het tweede."""

    def __init__(self, rijen: list[tuple]) -> None:
        self._rijen = rijen

    def all(self):
        return self._rijen

    def __iter__(self):
        return iter(self._rijen)


class _NepConn:
    """Beantwoordt zowel de "select distinct jaar"-opzoeking van
    `dichtstbijzijnd_beschikbaar_jaar()` (afgeleid uit de jaren van `rijen`
    zelf) als de eigenlijke "tijdstip, waarde"-opzoeking van
    `gewichten_uit_databank()` (`rijen` rechtstreeks)."""

    def __init__(self, rijen: list[tuple]) -> None:
        self._rijen = rijen

    def execute(self, query, _params=None):
        if "distinct jaar" in str(query):
            jaren = sorted({pd.Timestamp(r[0]).year for r in self._rijen})
            return _NepResultaat([(j,) for j in jaren])
        return _NepResultaat(self._rijen)


def _elektriciteitspunt() -> Aansluitingspunt:
    return Aansluitingspunt(Gebruiker().id, EnergieType.ELEKTRICITEIT, "9300", "Aalst")


def _dossier(punt: Aansluitingspunt, *, assets=(), verbruiksopgaven=(), contracten=()) -> Dossier:
    return Dossier(
        bron=None, gebruiker=Gebruiker(), persoonsgegevens=None,
        aansluitingspunten=(punt,), meters=(), assets=assets,
        contracten=contracten, verbruiksopgaven=verbruiksopgaven,
    )


def _lege_dossierresultaat(*, metingen=None) -> DossierResultaat:
    return DossierResultaat(
        resultaten=(), mislukt=(), dataversie=None, nettarieven_jaren=(),
        metingen=metingen, meetreeks=None, meetwaarschuwingen=(), markt=None,
    )


class TestPasToe:
    def test_voegt_een_batterij_asset_toe(self):
        punt = _elektriciteitspunt()
        dossier = _dossier(punt)
        scenario = BatterijScenario(merk="Marstek", model="Venus E")

        gewijzigd = scenario.pas_toe(dossier)

        (asset,) = gewijzigd.assets
        assert asset.type is AssetType.BATTERIJ
        assert asset.merk == "Marstek"
        assert asset.model == "Venus E"
        assert asset.topologie is Topologie.DC_GEKOPPELD

    def test_muteert_het_origineel_niet(self):
        punt = _elektriciteitspunt()
        dossier = _dossier(punt)
        scenario = BatterijScenario(merk="Marstek", model="Venus E")

        scenario.pas_toe(dossier)

        assert dossier.assets == ()

    def test_weigert_zonder_elektriciteitsaansluiting(self):
        punt = Aansluitingspunt(Gebruiker().id, EnergieType.GAS, "9300", "Aalst")
        dossier = _dossier(punt)
        scenario = BatterijScenario(merk="Marstek", model="Venus E")

        with pytest.raises(ValueError, match="geen elektriciteitsaansluiting"):
            scenario.pas_toe(dossier)

    def test_naam_wordt_automatisch_ingevuld(self):
        scenario = BatterijScenario(merk="Marstek", model="Venus E")
        assert "Marstek" in scenario.naam
        assert "Venus E" in scenario.naam


class TestVerbruiksreeks:
    def test_gebruikt_de_fluvius_meting_als_die_er_is(self):
        punt = _elektriciteitspunt()
        dossier = _dossier(punt)
        metingen = pd.DataFrame({
            "tijdstip": pd.date_range("2026-01-01", periods=2, freq="15min", tz="UTC"),
            "afname_kwh": [0.5, 0.6],
        })
        basislijn = _lege_dossierresultaat(metingen=metingen)

        reeks, aanname = verbruiksreeks(
            dossier, basislijn, conn=_NepConn([]), van=date(2026, 1, 1),
            tot=date(2027, 1, 1), jaarverbruik_kwh=None,
        )

        assert aanname is None
        assert list(reeks["kwh"]) == [0.5, 0.6]

    def test_telt_dag_en_nacht_registers_op_bij_een_echte_fluvius_meting(self):
        """`FluviusReeks.intervallen` draagt voor elektriciteit geen
        samengevoegde `afname_kwh`-kolom maar aparte dag-/nacht-/
        exclusief-nacht-registers (zie `metering/fluvius_csv.py`) — een
        eerdere versie ging hier stuk met "['kwh'] not in index"."""
        punt = _elektriciteitspunt()
        dossier = _dossier(punt)
        metingen = pd.DataFrame({
            "tijdstip": pd.date_range("2026-01-01", periods=2, freq="15min", tz="UTC"),
            "afname_dag_kwh": [0.3, 0.4],
            "afname_nacht_kwh": [0.1, 0.05],
            "injectie_dag_kwh": [0.0, 0.0],
        })
        basislijn = _lege_dossierresultaat(metingen=metingen)

        reeks, aanname = verbruiksreeks(
            dossier, basislijn, conn=_NepConn([]), van=date(2026, 1, 1),
            tot=date(2027, 1, 1), jaarverbruik_kwh=None,
        )

        assert aanname is None
        assert list(reeks["kwh"]) == pytest.approx([0.4, 0.45])

    def test_valt_terug_op_slp_ex_zonder_meting(self):
        punt = _elektriciteitspunt()
        dossier = _dossier(punt)
        basislijn = _lege_dossierresultaat(metingen=None)
        # Vier kwartierpunten die samen tot 1 sommeren (SLP-EX is een
        # verdeling) — vereist door `controleer_som()` in `verdeel_jaarverbruik()`.
        conn = _NepConn([
            ("2026-01-01T00:00:00+00:00", 0.25),
            ("2026-01-01T00:15:00+00:00", 0.25),
            ("2026-01-01T00:30:00+00:00", 0.25),
            ("2026-01-01T00:45:00+00:00", 0.25),
        ])

        reeks, aanname = verbruiksreeks(
            dossier, basislijn, conn=conn, van=date(2026, 1, 1),
            tot=date(2027, 1, 1), jaarverbruik_kwh=D("4000"),
        )

        assert aanname is not None
        assert aanname.geverifieerd is False
        assert sum(reeks["kwh"]) == pytest.approx(4000.0)

    def test_weigert_zonder_meting_en_zonder_jaarverbruik(self):
        punt = _elektriciteitspunt()
        dossier = _dossier(punt)  # geen verbruiksopgaven
        basislijn = _lege_dossierresultaat(metingen=None)

        with pytest.raises(SchattingError, match="verbruiksreeks nodig"):
            verbruiksreeks(
                dossier, basislijn, conn=_NepConn([]), van=date(2026, 1, 1),
                tot=date(2027, 1, 1), jaarverbruik_kwh=None,
            )

    def test_leidt_jaarverbruik_af_uit_de_verbruiksopgaven(self):
        punt = _elektriciteitspunt()
        opgave = Verbruiksopgave(
            punt.id, date(2026, 1, 1), date(2027, 1, 1),
            afname_dag_kwh=D("2000"), afname_nacht_kwh=D("1000"),
        )
        dossier = _dossier(punt, verbruiksopgaven=(opgave,))
        basislijn = _lege_dossierresultaat(metingen=None)
        conn = _NepConn([
            ("2026-01-01T00:00:00+00:00", 0.5),
            ("2026-01-01T00:15:00+00:00", 0.5),
        ])

        reeks, aanname = verbruiksreeks(
            dossier, basislijn, conn=conn, van=date(2026, 1, 1),
            tot=date(2027, 1, 1), jaarverbruik_kwh=None,
        )

        assert sum(reeks["kwh"]) == pytest.approx(3000.0)


class TestProductiereeks:
    def test_geen_pv_geeft_lege_reeks_en_waarschuwing(self):
        punt = _elektriciteitspunt()
        dossier = _dossier(punt)
        basislijn = _lege_dossierresultaat(metingen=None)

        reeks, waarschuwing = productiereeks(dossier, punt, basislijn, conn=_NepConn([]), jaar=2026)

        assert reeks.empty
        assert "zonnepanelen" in waarschuwing

    def test_pv_asset_levert_een_productiereeks(self):
        punt = _elektriciteitspunt()
        pv = InstallatieAsset(aansluitingspunt_id=punt.id, type=AssetType.PV, kwp=D("5"))
        dossier = _dossier(punt, assets=(pv,))
        basislijn = _lege_dossierresultaat(metingen=None)
        # SPP is vermogen, geen verdeling — geen som-tot-1-vereiste.
        conn = _NepConn([
            ("2026-01-01T00:00:00+00:00", 0.5),
            ("2026-01-01T00:15:00+00:00", 0.6),
        ])

        reeks, waarschuwing = productiereeks(dossier, punt, basislijn, conn=conn, jaar=2026)

        assert waarschuwing is None
        assert len(reeks) == 2
        assert (reeks["kwh"] > 0).all()

    def test_gebruikt_de_gemeten_injectie_en_niet_nogmaals_spp_bij_bestaande_pv(self):
        """Een bestaande PV-installatie zit al in de Fluvius-meting verrekend
        (injectie = wat de zon al opleverde, netto van zelfconsumptie). Een
        nieuwe SPP-synthese daar bovenop zou diezelfde zon dubbel tellen."""
        punt = _elektriciteitspunt()
        pv = InstallatieAsset(aansluitingspunt_id=punt.id, type=AssetType.PV, kwp=D("5"))
        dossier = _dossier(punt, assets=(pv,))
        metingen = pd.DataFrame({
            "tijdstip": pd.date_range("2026-01-01", periods=2, freq="15min", tz="UTC"),
            "afname_kwh": [0.1, 0.2],
            "injectie_kwh": [0.9, 0.8],
        })
        basislijn = _lege_dossierresultaat(metingen=metingen)
        # Deze nep-connectie zou bij een SPP-opzoeking een fout geven — als de
        # test slaagt, is de databank dus nooit bevraagd.
        conn = _NepConn([])

        reeks, waarschuwing = productiereeks(dossier, punt, basislijn, conn=conn, jaar=2026)

        assert waarschuwing is None
        assert list(reeks["kwh"]) == [0.9, 0.8]


class TestContractIsOveralDynamisch:
    """`prijsarbitrage` mag enkel aan op een dossier dat voor de hele
    gevraagde periode een dynamisch contract heeft — anders stuurt de
    dispatch op een prijs die niet is wat de klant betaalt."""

    def _contract(self, contracttype, van, tot, punt) -> Leveringscontract:
        return Leveringscontract(
            aansluitingspunt_id=punt.id, leverancier="Test", product="Test",
            contracttype=contracttype, geldig_van=van, geldig_tot=tot,
        )

    def test_volledig_dynamisch_contract_dekt_de_periode(self):
        punt = _elektriciteitspunt()
        contract = self._contract(Contracttype.DYNAMISCH, date(2025, 1, 1), None, punt)
        dossier = _dossier(punt, contracten=(contract,))

        assert contract_is_overal_dynamisch(dossier, punt, date(2026, 1, 1), date(2027, 1, 1))

    def test_vast_contract_faalt_de_toets(self):
        punt = _elektriciteitspunt()
        contract = self._contract(Contracttype.VAST, date(2025, 1, 1), None, punt)
        dossier = _dossier(punt, contracten=(contract,))

        assert not contract_is_overal_dynamisch(dossier, punt, date(2026, 1, 1), date(2027, 1, 1))

    def test_gedeeltelijk_dynamisch_faalt_de_toets(self):
        """Half het venster dynamisch, half vast — de dispatch zou voor het
        vaste deel op een niet-bestaand tarief sturen."""
        punt = _elektriciteitspunt()
        contracten = (
            self._contract(Contracttype.VAST, date(2026, 1, 1), date(2026, 7, 1), punt),
            self._contract(Contracttype.DYNAMISCH, date(2026, 7, 1), None, punt),
        )
        dossier = _dossier(punt, contracten=contracten)

        assert not contract_is_overal_dynamisch(dossier, punt, date(2026, 1, 1), date(2027, 1, 1))

    def test_gat_in_de_contracthistoriek_faalt_de_toets(self):
        punt = _elektriciteitspunt()
        contract = self._contract(Contracttype.DYNAMISCH, date(2026, 6, 1), None, punt)
        dossier = _dossier(punt, contracten=(contract,))

        assert not contract_is_overal_dynamisch(dossier, punt, date(2026, 1, 1), date(2027, 1, 1))


class TestPrijsarbitrageInScenario:
    def test_waarschuwt_en_schakelt_uit_zonder_dynamisch_contract(self):
        punt = _elektriciteitspunt()
        contract = Leveringscontract(
            aansluitingspunt_id=punt.id, leverancier="ENGIE", product="Easy",
            contracttype=Contracttype.VAST, geldig_van=date(2025, 1, 1),
        )
        dossier = _dossier(punt, contracten=(contract,))
        scenario = BatterijScenario(merk="Marstek", model="Venus E", prijsarbitrage=True)

        # `pas_toe()` alleen raakt geen contracten, dus de toets op het
        # gewijzigde dossier ziet nog steeds het bestaande vaste contract.
        gewijzigd = scenario.pas_toe(dossier)
        assert not contract_is_overal_dynamisch(gewijzigd, punt, date(2026, 1, 1), date(2027, 1, 1))
