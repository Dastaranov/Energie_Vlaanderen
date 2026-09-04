"""Een onbekende sleutel in een dossier wordt geweigerd, niet genegeerd.

`[[verbruiksopgave]] afname_kwh = 1600` in plaats van `afname_dag_kwh` leverde
een opgave van 0 kWh op. De berekening liep gewoon door en gaf 21,40 EUR terug
waar 291,56 hoorde te staan — geen fout, geen waarschuwing, alleen een bedrag
dat te laag was. Het viel enkel op omdat het cijfer wantrouwen wekte.

Dat is dezelfde foutklasse als elke andere stille nul in dit project. Een
dossier is invoer van een mens, en een typfout in een veldnaam is de meest
waarschijnlijke fout die er is; ze stil overslaan maakt van een tikfout een
verkeerd bedrag.
"""
from __future__ import annotations

import pytest

from energie_vlaanderen.gebruikers.models import GebruikersError
from energie_vlaanderen.gebruikers.toml_io import _controleer_sleutels


pytestmark = pytest.mark.dossier


class TestOnbekendeSleutel:
    def test_de_sleutel_die_dit_veroorzaakte_wordt_geweigerd(self):
        with pytest.raises(GebruikersError, match="afname_kwh"):
            _controleer_sleutels({"afname_kwh": 1600}, "verbruiksopgave")

    def test_de_melding_wijst_de_bedoelde_sleutel_aan(self):
        """De fout is bijna altijd een typfout of een half onthouden veldnaam."""
        with pytest.raises(GebruikersError, match="afname_dag_kwh"):
            _controleer_sleutels({"afname_kwh": 1600}, "verbruiksopgave")
        with pytest.raises(GebruikersError, match="postcode"):
            _controleer_sleutels({"postkode": "9000"}, "gebruiker")

    def test_bekende_sleutels_gaan_door(self):
        _controleer_sleutels(
            {"periode_van": "2025-01-01", "afname_dag_kwh": 100, "bron": "manueel"},
            "verbruiksopgave",
        )

    def test_een_sectie_met_achtervoegsel_gebruikt_dezelfde_sleutels(self):
        """`[[contract.elektriciteit]]` en `[huidig_contract.gas]` kennen
        dezelfde velden als `contract`."""
        _controleer_sleutels(
            {"leverancier": "ENGIE", "product": "Easy", "type": "vast"},
            "contract.elektriciteit",
        )
        with pytest.raises(GebruikersError, match="leveranciet"):
            _controleer_sleutels({"leveranciet": "ENGIE"}, "huidig_contract.gas")

    def test_een_onbekende_sectie_wordt_niet_getoetst(self):
        """`[analyse]` en `[uitvoer]` worden door deze lezer niet verwerkt;
        ze hier weigeren zou bestaande bestanden breken."""
        _controleer_sleutels({"wat_dan_ook": 1}, "analyse")


class TestBestaandeDossiersBlijvenGeldig:
    """De controle mag niets breken wat vandaag werkt."""

    @pytest.mark.parametrize("naam", [
        "gebruiker.voorbeeld.toml",
        "tests/fixturen/dossiers/synthetisch_woning.toml",
    ])
    def test_dossier_leest_zonder_klacht(self, naam, project_root):
        import tomllib

        from energie_vlaanderen.gebruikers.toml_io import _SLEUTELS

        pad = project_root / naam
        if not pad.is_file():
            pytest.skip(f"{naam} ontbreekt.")
        ruw = tomllib.loads(pad.read_text(encoding="utf-8"))

        for sectie in ("gebruiker", "aansluiting", "verbruik"):
            if isinstance(ruw.get(sectie), dict):
                _controleer_sleutels(ruw[sectie], sectie)
        for rij in ruw.get("verbruiksopgave") or []:
            _controleer_sleutels(rij, "verbruiksopgave")
        for energie, rijen in (ruw.get("contract") or {}).items():
            for rij in rijen if isinstance(rijen, list) else [rijen]:
                _controleer_sleutels(rij, f"contract.{energie}")
        assert _SLEUTELS  # de kaart is niet leeg
