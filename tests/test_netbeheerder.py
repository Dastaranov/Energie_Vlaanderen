"""Tests voor de postcode->netbeheerder-koppeling.

`Calculator.grid_cost()` riep `repo.dnb_for(postcode, gemeente)` aan zonder dat
die methode bestond: alleen een fake in `tests/test_calculator_heffingen.py`
hield de berekening draaiend, waardoor de nettarieven nog nooit tegen echte
data gedraaid waren.

Het scherpe geval zit in de brondata zelf: postcode 2387 dekt zowel
Zondereigen (gas: Fluvius Kempen) als Baarle-Hertog (gas: Enexis Netbeheer, een
Belgische enclave in Nederland). Op augustus 2026 is dat de enige postcode van
de 519 waar de gaskolommen uiteenlopen — maar het bewijst dat de postcode
alleen niet volstaat.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from energie_vlaanderen.nettarieven.netbeheerder import (
    NetbeheerderError,
    NetbeheerderRegister,
    dnb_code,
)
from energie_vlaanderen.utility.constants import DNB_CODES

GEMEENTE_CSV = Path(__file__).resolve().parents[1] / "data" / "current" / "DnbPerGemeente.csv"


@pytest.fixture(scope="module")
def register() -> NetbeheerderRegister:
    if not GEMEENTE_CSV.is_file():
        pytest.skip(f"{GEMEENTE_CSV.name} ontbreekt in deze werkkopie.")
    return NetbeheerderRegister.load(GEMEENTE_CSV)


class TestDnbCode:
    def test_bekende_namen_krijgen_hun_afkorting(self):
        for naam, code in DNB_CODES.items():
            assert dnb_code(naam) == code

    def test_een_onbekende_naam_gaat_als_naam_door_en_waarschuwt(self, caplog):
        """Stil een bestaande code kiezen zou tarieven van de verkeerde
        netbeheerder toepassen."""
        with caplog.at_level("WARNING"):
            assert dnb_code("Onbekende Netbeheerder") == "Onbekende Netbeheerder"
        assert "DNB_CODES" in caplog.text


class TestOpzoeken:
    def test_een_gewone_postcode_geeft_naam_en_code(self, register):
        naam, code = register.dnb_for("9300", "Aalst")
        assert (naam, code) == ("Fluvius Midden-Vlaanderen", "FMV")

    def test_elektriciteit_en_gas_worden_apart_opgezocht(self, register):
        """Het bronbestand heeft twee kolommen; ze kunnen uiteenlopen."""
        assert register.dnb_for("2387", "Zondereigen", "elektriciteit")[1] == "FK"
        assert register.dnb_for("2387", "Zondereigen", "gas")[1] == "FK"
        assert (
            register.dnb_for("2387", "Baarle-Hertog (uitgezonderd Zondereigen)", "gas")[1]
            == "ENEXIS"
        )

    def test_een_dubbelzinnige_postcode_eist_de_gemeente(self, register):
        """Zonder gemeente is er geen eenduidig antwoord, en gokken zou stil het
        verkeerde tarief opleveren."""
        with pytest.raises(NetbeheerderError, match="meerdere netbeheerders"):
            register.dnb_for("2387", "", "gas")

    def test_de_foutmelding_noemt_de_gemeenten_zoals_ze_geschreven_staan(self, register):
        with pytest.raises(NetbeheerderError) as fout:
            register.dnb_for("2387", "", "gas")
        assert "Zondereigen" in str(fout.value)
        assert "Baarle-Hertog" in str(fout.value)

    def test_een_onbekende_postcode_is_een_fout_geen_lege_waarde(self, register):
        with pytest.raises(NetbeheerderError, match="Geen netbeheerder"):
            register.dnb_for("0000", "Nergens")

    def test_een_onbekende_energievorm_wordt_geweigerd(self, register):
        with pytest.raises(NetbeheerderError, match="energievorm"):
            register.dnb_for("9300", "Aalst", "waterstof")


class TestTarieven:
    def test_enexis_heeft_geen_tarieven_in_deze_dataset(self, register):
        """Enexis (Baarle-Hertog) staat onder toezicht van de Nederlandse ACM en
        publiceert in een werkboek dat deze pipeline niet inleest. Een
        gasberekening daar hoort te stoppen, niet stilzwijgend een
        Fluvius-tarief te gebruiken. Zie `DNB_ZONDER_TARIEVEN`.
        """
        naam, code = register.dnb_for(
            "2387", "Baarle-Hertog (uitgezonderd Zondereigen)", "gas"
        )
        assert code == "ENEXIS"
        assert not register.heeft_tarieven(code)
        with pytest.raises(NetbeheerderError, match="geen gastarieven"):
            register.dnb_met_tarieven(
                "2387", "Baarle-Hertog (uitgezonderd Zondereigen)", "gas"
            )

    def test_fluvius_heeft_wel_tarieven(self, register):
        assert register.dnb_met_tarieven("9300", "Aalst") == (
            "Fluvius Midden-Vlaanderen",
            "FMV",
        )


class TestOntbrekendBestand:
    def test_een_ontbrekend_bestand_is_een_duidelijke_fout(self, tmp_path):
        with pytest.raises(NetbeheerderError, match="niet gevonden"):
            NetbeheerderRegister.load(tmp_path / "bestaat_niet.csv")

    def test_een_bestand_zonder_de_verwachte_kolommen_wordt_geweigerd(self, tmp_path):
        pad = tmp_path / "DnbPerGemeente.csv"
        pad.write_text("Postcode;Gemeente\n9300;Aalst\n", encoding="utf-8-sig")
        with pytest.raises(NetbeheerderError, match="mist de kolom"):
            NetbeheerderRegister.load(pad)
