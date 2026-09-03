"""Tests voor de C10/26-controle op de hardware-masterdata.

C10/26 is de Belgische lijst van productie-eenheden die aan C10/11 voldoen en
dus op een distributienet aangesloten mogen worden. Staat een toestel er niet
in, dan mag de netbeheerder de aansluiting weigeren — voor een gebruiker die in
een interface een batterij kiest is dat de eerste vraag die telt.

De lijst is ook de enige onafhankelijke bron op deze masterdata: al het andere
komt uit fabrikantsdatasheets. Alle gegevens hieronder komen uit de uitgave van
2026-08-26; het werkboek zelf valt buiten git (zie `data/datasheets/LEESMIJ.md`),
dus de tests bouwen de regels na in plaats van het bestand te lezen.
"""
from __future__ import annotations

import pytest

from energie_vlaanderen.hardware.homologatie import (
    C1026Lijst,
    C1026Vermelding,
    controleer_spec,
)
from energie_vlaanderen.hardware.models import BatterijSpec, OmvormerSpec

# Vier echte regels uit de lijst.
MARSTEK_VENUS_E = C1026Vermelding(
    synergrid_id="GLV265-07-0004", merk="MARSTEK", serie="Venus-E energy cube",
    model="MST-BIE5-2500", firmware="V137",
    power_control_system="external CT + TPM-100CTW",
    p_active_power_w=2500.0, smax_apparent_power_w=2500.0, num_phase=1,
)
MARSTEK_VENUS_E_KLEIN = C1026Vermelding(
    synergrid_id="GLV265-07-0002", merk="MARSTEK", serie="Venus-E energy cube",
    model="MST-BIE5-0800", firmware="V137",
    power_control_system="external CT + TPM-100CTW",
    p_active_power_w=800.0, smax_apparent_power_w=800.0, num_phase=1,
)
GROWATT_1F = C1026Vermelding(
    synergrid_id="GLV044-05-0005", merk="Growatt ", serie="SPH", model="SPH 5000",
    firmware="", power_control_system="",
    p_active_power_w=4999.0, smax_apparent_power_w=5000.0, num_phase=1,
)
GROWATT_3F = C1026Vermelding(
    synergrid_id="GLV044-04-0002", merk="Growatt", serie="SPH", model="SPH 5000TL3 BH",
    firmware="", power_control_system="",
    p_active_power_w=5000.0, smax_apparent_power_w=5000.0, num_phase=3,
)
VERVALLEN = C1026Vermelding(
    synergrid_id="GLV999-01-0001", merk="OudMerk", serie="Oud", model="OUD-1",
    firmware="", power_control_system="",
    p_active_power_w=3000.0, smax_apparent_power_w=3000.0, num_phase=1,
    vervallen=True,
)


@pytest.fixture
def lijst(tmp_path):
    return C1026Lijst(
        (MARSTEK_VENUS_E, MARSTEK_VENUS_E_KLEIN, GROWATT_1F, GROWATT_3F, VERVALLEN),
        tmp_path / "c10_26.xlsx",
    )


def batterij(**overrides) -> BatterijSpec:
    basis = dict(
        merk="Marstek", model="Venus E", synergrid_id="",
        power_control_system="external CT + TPM-100CTW",
        p_active_power_w=2500.0, smax_apparent_power_w=2500.0, num_phase=1,
        max_charge_w=2500.0, max_discharge_w=2500.0, max_capacity_kwh=5.12,
        minimum_capacity_pct=10.0, standby_power_w=15.0,
        round_trip_efficiency_pct=93.5, rte_ac_dc_pct=97.2, rte_dc_ac_pct=97.2,
        rte_storage_pct=99.0, ramp_up_time_s=0.5, max_cycle=6000,
        max_depth_of_discharge_pct=90.0, c_rate=0.5, eol_criteria_pct=80.0,
        geverifieerd=False, bron="datasheet", datasheet_versie="",
        datasheet_datum="", opgehaald_op="",
    )
    return BatterijSpec(**(basis | overrides))


def omvormer(**overrides) -> OmvormerSpec:
    basis = dict(
        merk="Growatt", model="SPH 5000", product_type="hybride",
        nominaal_ac_vermogen_w=5000.0, max_ac_vermogen_w=5000.0,
        max_dc_vermogen_w=6500.0, num_phase=1, europees_rendement_pct=97.0,
        geverifieerd=False, bron="datasheet", datasheet_versie="",
        datasheet_datum="", opgehaald_op="",
    )
    return OmvormerSpec(**(basis | overrides))


def _ernsten(bevindingen):
    return {b.ernst for b in bevindingen}


class TestZoeken:
    def test_merknaam_wordt_genormaliseerd(self, lijst):
        """De lijst schrijft "MARSTEK" en "Growatt " (met spatie)."""
        assert lijst.zoek("marstek")
        assert lijst.zoek("GROWATT")

    def test_model_matcht_op_deelstring_van_de_serie(self, lijst):
        """De masterdata noemt het "Venus E", de lijst "Venus-E energy cube"."""
        treffers = lijst.zoek("Marstek", "Venus E")
        assert {t.synergrid_id for t in treffers} == {"GLV265-07-0004", "GLV265-07-0002"}

    def test_een_onbekend_model_geeft_niets(self, lijst):
        assert lijst.zoek("Marstek", "Venus E 4.0") == ()


class TestHomologatie:
    def test_een_gehomologeerd_toestel_levert_alleen_info(self, lijst):
        bevindingen = controleer_spec(
            batterij(synergrid_id="GLV265-07-0004"), lijst, "batterij"
        )
        assert _ernsten(bevindingen) == {"info"}

    def test_een_ontbrekend_toestel_is_een_fout(self, lijst):
        """Venus E 4.0 en Venus E Mini staan niet in de uitgave van 2026-08-26,
        ook niet bij de vervallen homologaties. Zonder homologatie mag de
        netbeheerder de aansluiting weigeren."""
        bevindingen = controleer_spec(
            batterij(model="Venus E 4.0", p_active_power_w=3000.0), lijst, "batterij"
        )
        assert "fout" in _ernsten(bevindingen)
        assert "niet gehomologeerd" in bevindingen[0].bericht
        # De melding noemt wat er van dit merk wél in staat.
        assert "Venus-E energy cube" in bevindingen[0].bericht

    def test_een_vervallen_homologatie_is_ook_een_fout(self, lijst):
        spec = batterij(merk="OudMerk", model="OUD-1", p_active_power_w=3000.0)
        bevindingen = controleer_spec(spec, lijst, "batterij")
        assert "fout" in _ernsten(bevindingen)
        assert "vervallen" in bevindingen[0].bericht

    def test_een_onbekend_merk_wordt_als_zodanig_gemeld(self, lijst):
        bevindingen = controleer_spec(
            batterij(merk="Verzonnen", model="X"), lijst, "batterij"
        )
        assert "komt helemaal niet in de lijst voor" in bevindingen[0].bericht


class TestVergelijking:
    def test_een_afwijkend_schijnbaar_vermogen_wordt_gemeld(self, lijst):
        """De masterdata stond op 3500 VA waar de lijst 2500 VA zegt.

        Dat was geen datasheetwaarde maar een aanname, en ze overschatte het
        schijnbaar vermogen met 40%.
        """
        bevindingen = controleer_spec(
            batterij(synergrid_id="GLV265-07-0004", smax_apparent_power_w=3500.0),
            lijst, "batterij",
        )
        assert "waarschuwing" in _ernsten(bevindingen)
        assert any("3500" in b.bericht and "2500" in b.bericht for b in bevindingen)

    def test_een_ontbrekend_synergrid_id_wordt_voorgesteld(self, lijst):
        bevindingen = controleer_spec(batterij(), lijst, "batterij")
        assert any("GLV265-07-0004" in b.bericht for b in bevindingen)

    def test_een_verkeerd_synergrid_id_wordt_gemeld(self, lijst):
        bevindingen = controleer_spec(
            batterij(synergrid_id="GLV265-07-0002"), lijst, "batterij"
        )
        # GLV265-07-0002 is de 800 W-variant; bij 2500 W hoort -0004.
        assert "waarschuwing" in _ernsten(bevindingen)


class TestVariantkeuze:
    def test_het_aantal_fasen_weegt_zwaarder_dan_het_vermogen(self, lijst):
        """Growatt's SPH 5000 bestaat 1-fasig (4.999 W) en 3-fasig (5.000 W).

        De datasheet noemt 5.000 W, dus op vermogen alleen wint de 3-fasige
        variant — terwijl de masterdata 1-fasig zegt. Het aantal fasen is een
        harde eigenschap van de aansluiting en weegt daarom zwaarder.
        """
        bevindingen = controleer_spec(omvormer(), lijst, "omvormer")
        assert "waarschuwing" not in _ernsten(bevindingen)
        assert any("GLV044-05-0005" in b.bericht for b in bevindingen)

    def test_de_juiste_vermogensvariant_wordt_gekozen(self, lijst):
        """Venus-E staat er als 800 W en als 2500 W in."""
        bevindingen = controleer_spec(
            batterij(p_active_power_w=800.0, smax_apparent_power_w=800.0,
                     max_charge_w=800.0, max_discharge_w=800.0),
            lijst, "batterij",
        )
        assert any("GLV265-07-0002" in b.bericht for b in bevindingen)

    def test_een_vermogen_dat_nergens_op_slaat_wordt_gemeld(self, lijst):
        bevindingen = controleer_spec(
            batterij(p_active_power_w=1500.0), lijst, "batterij"
        )
        assert any("1500 W" in b.bericht for b in bevindingen)
