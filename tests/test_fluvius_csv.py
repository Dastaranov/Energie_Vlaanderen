"""Tests voor het inlezen van een Fluvius-verbruikshistoriek.

De monsters in `tests/fixturen/metering/` zijn geanonimiseerde stukken uit een
echte export van drie jaar: EAN en meternummer zijn vervangen, de structuur en
de waarden zijn onaangeroerd. Ze bevatten met opzet een winterdag, een zomerdag
met injectie, en beide zomertijdovergangen.

Elke test hieronder dekt een eigenschap van het echte bestand waarop de vorige
implementatie stukliep.
"""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal as D
from pathlib import Path

import pandas as pd
import pytest

from energie_vlaanderen.metering.fluvius_csv import FluviusDataError, FluviusIntervals
from energie_vlaanderen.utility.constants import LOCAL_TZ

FIXTUREN = Path(__file__).resolve().parents[1] / "tests" / "fixturen" / "metering"
ELEK = FIXTUREN / "fluvius_elektriciteit_kwartier.voorbeeld.csv"
GAS = FIXTUREN / "fluvius_gas_uur.voorbeeld.csv"


@pytest.fixture(scope="module")
def elek():
    if not ELEK.is_file():
        pytest.skip(f"{ELEK.name} ontbreekt.")
    return FluviusIntervals.read(ELEK)


@pytest.fixture(scope="module")
def gas():
    if not GAS.is_file():
        pytest.skip(f"{GAS.name} ontbreekt.")
    return FluviusIntervals.read(GAS)


class TestRegisters:
    def test_de_vier_registers_blijven_apart(self, elek):
        """"Afname Dag", "Afname Nacht", "Injectie Dag", "Injectie Nacht".

        Alleen op "afname" en "injectie" matchen gooit het dag-/nachtonderscheid
        weg — precies wat het nettarief en de meeste leveranciersproducten nodig
        hebben. Op de referentiefactuur ging het om 2.599 kWh piek tegenover
        4.218 kWh dal, met een ander tarief per register.
        """
        assert {
            "afname_dag_kwh", "afname_nacht_kwh",
            "injectie_dag_kwh", "injectie_nacht_kwh",
        } <= set(elek.intervallen.columns)
        assert elek.energie == "elektriciteit"

    def test_dag_en_nacht_dragen_allebei_verbruik(self, elek):
        assert elek.intervallen["afname_dag_kwh"].sum() > 0
        assert elek.intervallen["afname_nacht_kwh"].sum() > 0

    def test_een_onbekend_register_stopt_het_inlezen(self, tmp_path):
        """Overslaan zou verbruik laten verdwijnen zonder dat iemand het merkt."""
        pad = tmp_path / "raar.csv"
        pad.write_text(
            "Van (datum);Van (tijdstip);Register;Volume;Eenheid;Validatiestatus\n"
            "15-01-2026;00:00:00;Iets Anders;1,000;kWh;Uitgelezen\n",
            encoding="utf-8-sig",
        )
        with pytest.raises(FluviusDataError, match="Onbekende registers"):
            FluviusIntervals.read(pad)


class TestGas:
    def test_de_kubieke_meter_regels_worden_overgeslagen(self, gas):
        """Een gasexport bevat elk interval twee keer: in m³ én in kWh.

        Optellen per tijdstip telt volume en energie bij elkaar op, en dat getal
        betekent niets. Bij deze export zou het verbruik daardoor ruwweg
        verdubbelen.
        """
        assert gas.energie == "gas"
        assert any("m³" in w for w in gas.waarschuwingen)
        # Eén rij per uur, niet twee.
        assert gas.resolutie == timedelta(hours=1)
        assert len(gas.intervallen) == gas.intervallen["tijdstip"].nunique()

    def test_gas_kent_geen_dag_nachtregister(self, gas):
        assert "afname_kwh" in gas.intervallen.columns
        assert "afname_dag_kwh" not in gas.intervallen.columns


class TestValidatiestatus:
    def test_geen_verbruik_wordt_geen_gemeten_nul(self, tmp_path):
        """"Geen verbruik" betekent dat er géén meting is; het volume is leeg.

        Dat op nul zetten maakt van een ontbrekende meting een gemeten nul —
        precies wat Manifest §12 verbiedt. In de aangeleverde export ging het om
        193 kwartieren.
        """
        pad = tmp_path / "leeg.csv"
        pad.write_text(
            "Van (datum);Van (tijdstip);Register;Volume;Eenheid;Validatiestatus\n"
            "15-01-2026;00:00:00;Afname Dag;1,000;kWh;Uitgelezen\n"
            "15-01-2026;00:15:00;Afname Dag;;kWh;Geen verbruik\n"
            "15-01-2026;00:30:00;Afname Dag;2,000;kWh;Uitgelezen\n",
            encoding="utf-8-sig",
        )
        reeks = FluviusIntervals.read(pad)

        assert reeks.ontbrekende_intervallen == 1
        assert len(reeks.intervallen) == 2          # niet drie
        assert reeks.afname_kwh == D("3.0")          # niet 3,0 met een nul erbij
        assert any("zonder meting" in w for w in reeks.waarschuwingen)

    def test_geschatte_intervallen_worden_gemeld(self, tmp_path):
        """Fluvius schat zelf ook; dan is het resultaat in zoverre geen meting."""
        pad = tmp_path / "geschat.csv"
        pad.write_text(
            "Van (datum);Van (tijdstip);Register;Volume;Eenheid;Validatiestatus\n"
            "15-01-2026;00:00:00;Afname Dag;1,000;kWh;Uitgelezen\n"
            "15-01-2026;00:15:00;Afname Dag;1,500;kWh;Geschat\n",
            encoding="utf-8-sig",
        )
        reeks = FluviusIntervals.read(pad)

        assert reeks.geschatte_intervallen == 1
        assert reeks.afname_kwh == D("2.5")   # de waarde telt wél mee
        assert any("geschat" in w for w in reeks.waarschuwingen)


class TestZomertijd:
    def test_de_dubbele_uren_van_oktober_blijven_apart(self, elek):
        """Op de laatste zondag van oktober telt de dag 100 kwartieren.

        Tussen 02:00 en 03:00 komt elk lokaal tijdstip twee keer voor: eerst in
        zomertijd, dan in wintertijd. Groeperen op het lokale tijdstip plakt die
        twee uren samen en laat een uur verbruik verdwijnen. In UTC zijn het
        wél twee verschillende momenten.
        """
        lokaal = elek.intervallen["tijdstip"].dt.tz_convert(LOCAL_TZ)
        oktober = elek.intervallen[lokaal.dt.date == pd.Timestamp("2025-10-26").date()]
        assert len(oktober) == 100
        # Alle honderd zijn verschillende momenten in UTC.
        assert oktober["tijdstip"].nunique() == 100

    def test_het_ontbrekende_uur_van_maart_blijft_ontbreken(self, elek):
        """Bij de overgang naar zomertijd bestaat 02:00-03:00 lokaal niet."""
        lokaal = elek.intervallen["tijdstip"].dt.tz_convert(LOCAL_TZ)
        maart = elek.intervallen[lokaal.dt.date == pd.Timestamp("2026-03-29").date()]
        assert len(maart) == 92

    def test_de_reeks_is_in_utc_en_strikt_oplopend(self, elek):
        tijdstippen = elek.intervallen["tijdstip"]
        assert str(tijdstippen.dt.tz) == "UTC"
        assert tijdstippen.is_monotonic_increasing
        assert tijdstippen.is_unique


class TestAfgeleiden:
    def test_de_ean_wordt_uit_de_excelformule_gehaald(self, elek):
        """De export schrijft de EAN als ="541448...", een Excel-formule."""
        assert elek.ean.isdigit()
        assert len(elek.ean) == 18

    def test_maandpieken_worden_in_kw_uitgedrukt(self, elek):
        """Een maandpiek is het hoogste kwartiergemiddelde maal vier.

        De factor zet kWh per kwartier om naar kW gemiddeld vermogen; hem
        vergeten maakt de piek een kwart van wat ze is, en daarmee het
        capaciteitstarief ook.
        """
        pieken = elek.maandpieken_kw(2026)
        assert pieken
        for piek in pieken:
            assert piek > D("0")
        # Het monster bevat drie dagen uit 2026: 15 januari, 29 maart (de
        # overgang naar zomertijd) en 15 juni. Maanden zonder meting krijgen
        # géén piek van nul — dat zou de laagste maand van het jaar verzinnen.
        assert len(pieken) == 3

    def test_voor_berekening_telt_dag_en_nacht_samen(self, elek):
        """Een dynamisch product rekent per kwartier en kent geen dag/nacht."""
        frame = elek.voor_berekening()
        assert list(frame.columns) == ["tijdstip", "afname_kwh", "injectie_kwh"]
        assert D(str(frame["afname_kwh"].sum())) == elek.afname_kwh

    def test_tussen_snijdt_de_reeks(self, elek):
        heel = len(elek.intervallen)
        stuk = elek.tussen("2026-06-15", "2026-06-16")
        assert 0 < len(stuk.intervallen) < heel


class TestFoutafhandeling:
    def test_een_ontbrekend_bestand_is_een_duidelijke_fout(self, tmp_path):
        with pytest.raises(FluviusDataError, match="niet gevonden"):
            FluviusIntervals.read(tmp_path / "bestaat_niet.csv")

    def test_een_bestand_zonder_de_verwachte_kolommen(self, tmp_path):
        pad = tmp_path / "raar.csv"
        pad.write_text("a;b;c\n1;2;3\n", encoding="utf-8-sig")
        with pytest.raises(FluviusDataError, match="mist de kolom"):
            FluviusIntervals.read(pad)
