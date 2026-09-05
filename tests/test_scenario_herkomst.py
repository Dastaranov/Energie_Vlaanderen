"""Tests voor `scenario.herkomst`: genoeg vastleggen om een simulatie later
exact te reproduceren, zonder persoonsgegevens of lokale bestandspaden mee te
nemen."""
from __future__ import annotations

from decimal import Decimal as D
from pathlib import Path

import pytest

from energie_vlaanderen.gebruikers.models import (
    Aansluitingspunt,
    EnergieType,
    Gebruiker,
    Persoonsgegevens,
    Topologie,
)
from energie_vlaanderen.gebruikers.toml_io import Dossier
from energie_vlaanderen.scenario import herkomst
from energie_vlaanderen.scenario.batterij import BatterijScenario

pytestmark = pytest.mark.dossier


def _dossier(**overrides) -> Dossier:
    punt = Aansluitingspunt(
        gebruiker_id=Gebruiker().id, energie_type=EnergieType.ELEKTRICITEIT,
        postcode="9300", gemeente="Aalst", ean_code="541448820063436172",
    )
    basis = dict(
        bron=Path("/home/gebruiker/geheim/gebruiker.toml"),
        gebruiker=Gebruiker(),
        persoonsgegevens=Persoonsgegevens(gebruiker_id=Gebruiker().id, naam="Jan Voorbeeld"),
        aansluitingspunten=(punt,), meters=(), assets=(), contracten=(),
        verbruiksopgaven=(), fluvius_csv=Path("/home/gebruiker/geheim/meting.csv"),
    )
    basis.update(overrides)
    return Dossier(**basis)


class TestDossierSnapshot:
    def test_bevat_geen_persoonsgegevens(self):
        snapshot = herkomst.dossier_snapshot(_dossier())
        assert "persoonsgegevens" not in snapshot
        assert "Jan Voorbeeld" not in str(snapshot)

    def test_bevat_geen_ean_code(self):
        snapshot = herkomst.dossier_snapshot(_dossier())
        assert snapshot["aansluitingspunten"][0]["ean_code"] is None
        assert "541448820063436172" not in str(snapshot)

    def test_bevat_geen_lokaal_bestandspad(self):
        snapshot = herkomst.dossier_snapshot(_dossier())
        assert "/home/gebruiker/geheim" not in str(snapshot)

    def test_registreert_wel_dat_er_een_meting_was(self):
        met_meting = herkomst.dossier_snapshot(_dossier())
        zonder_meting = herkomst.dossier_snapshot(_dossier(fluvius_csv=None))
        assert met_meting["heeft_fluvius_meting"] is True
        assert zonder_meting["heeft_fluvius_meting"] is False

    def test_bewaart_wel_de_rekenkundig_relevante_velden(self):
        snapshot = herkomst.dossier_snapshot(_dossier())
        assert snapshot["aansluitingspunten"][0]["postcode"] == "9300"
        assert snapshot["aansluitingspunten"][0]["gemeente"] == "Aalst"


class TestDossierHash:
    def test_is_deterministisch(self):
        snapshot = herkomst.dossier_snapshot(_dossier())
        assert herkomst.dossier_hash(snapshot) == herkomst.dossier_hash(snapshot)

    def test_verschilt_bij_een_ander_dossier(self):
        a = herkomst.dossier_snapshot(_dossier())
        b = herkomst.dossier_snapshot(_dossier(fluvius_csv=None))
        assert herkomst.dossier_hash(a) != herkomst.dossier_hash(b)

    def test_is_een_sha256_hex_string(self):
        snapshot = herkomst.dossier_snapshot(_dossier())
        h = herkomst.dossier_hash(snapshot)
        assert len(h) == 64
        int(h, 16)  # gooit ValueError als het geen geldige hex is


class TestHuidigeCommit:
    def test_geeft_none_en_false_buiten_een_git_repo(self, tmp_path):
        commit, dirty = herkomst.huidige_commit(tmp_path)
        assert commit is None
        assert dirty is False

    def test_geeft_none_en_false_op_een_niet_bestaand_pad(self):
        commit, dirty = herkomst.huidige_commit(Path("/pad/dat/niet/bestaat"))
        assert commit is None
        assert dirty is False


class TestScenarioParameters:
    def test_geeft_de_dataclass_velden_van_het_scenario(self):
        scenario = BatterijScenario(
            merk="Marstek", model="Venus E", topologie=Topologie.AC_GEKOPPELD,
            ac_vermogen_max_w=D("800"),
        )
        parameters = herkomst.scenario_parameters(scenario)
        assert parameters["merk"] == "Marstek"
        assert parameters["model"] == "Venus E"
        assert parameters["topologie"] == "ac_gekoppeld"
        assert parameters["ac_vermogen_max_w"] == "800"

    def test_naam_en_omschrijving_zitten_er_niet_in(self):
        """Die twee staan al apart in `simulatie.scenario_naam` — ze horen
        niet nogmaals in `scenario_parameters` (en zijn ook geen
        dataclass-velden van de basisklasse, dus dit zou vanzelf al kloppen;
        deze test legt dat vast)."""
        scenario = BatterijScenario(merk="Marstek", model="Venus E")
        parameters = herkomst.scenario_parameters(scenario)
        assert "naam" not in parameters
        assert "omschrijving" not in parameters
