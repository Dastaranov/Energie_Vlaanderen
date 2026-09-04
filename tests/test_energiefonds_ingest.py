"""Tests voor de parser van de energiefonds-tarieftabel.

`config/heffingen/bijdrage_energiefonds.toml` is handgeschreven en werd tot nu
toe met de hand tegen vlaanderen.be gelegd — het soort controle dat precies één
keer per jaar nodig is en daarom vergeten wordt.

De tests draaien op een opgeslagen kopie van de pagina
(`tests/fixturen/heffingen/`), dus zonder netwerk. Alle bedragen hieronder komen
uit die kopie, geraadpleegd op 2026-08-31 en op 2026-09-03 opnieuw tegen de live
pagina bevestigd.
"""
from __future__ import annotations

from decimal import Decimal as D
from pathlib import Path

import pytest

pytest.importorskip("bs4")

from energie_vlaanderen.ingest.heffingen.energiefonds import (
    EnergiefondsError,
    lees_bestand,
    parse_tabel,
)

FIXTUUR = (
    Path(__file__).resolve().parents[1]
    / "tests" / "fixturen" / "heffingen" / "vlaanderen_energiefonds_2026.html"
)


pytestmark = pytest.mark.masterdata


@pytest.fixture(scope="module")
def rijen():
    if not FIXTUUR.is_file():
        pytest.skip(f"{FIXTUUR.name} ontbreekt.")
    return lees_bestand(FIXTUUR)


def _waarde(rijen, jaar, spanningsniveau, klantcategorie):
    (gevonden,) = [
        r for r in rijen
        if r.jaar == jaar
        and r.spanningsniveau == spanningsniveau
        and r.klantcategorie == klantcategorie
    ]
    return gevonden.eur_per_maand


class TestParsing:
    def test_alle_categorieen_en_jaren(self, rijen):
        """Vijf categorieën maal vijf jaargangen (2022 t/m 2026)."""
        assert len(rijen) == 25
        assert {r.jaar for r in rijen} == {2022, 2023, 2024, 2025, 2026}
        assert {(r.spanningsniveau, r.klantcategorie) for r in rijen} == {
            ("laag", "residentieel"),
            ("laag", "niet_residentieel"),
            ("laag", "beschermd"),
            ("midden", ""),
            ("hoog", ""),
        }

    def test_residentieel_werd_nul_na_2022(self, rijen):
        """0,45 EUR/maand in 2022, daarna afgeschaft voor gezinnen."""
        assert _waarde(rijen, 2022, "laag", "residentieel") == D("0.45")
        for jaar in (2023, 2024, 2025, 2026):
            assert _waarde(rijen, jaar, "laag", "residentieel") == D("0.00")

    def test_niet_residentieel_stijgt_elk_jaar(self, rijen):
        """8,49 -> 9,54 -> 9,57 -> 9,88 -> 10,07 EUR/maand."""
        verwacht = ["8.49", "9.54", "9.57", "9.88", "10.07"]
        for jaar, bedrag in zip((2022, 2023, 2024, 2025, 2026), verwacht):
            assert _waarde(rijen, jaar, "laag", "niet_residentieel") == D(bedrag)

    def test_niet_residentieel_wordt_niet_met_residentieel_verward(self, rijen):
        """"niet-residentiële afnemer" bevat "residentiële afnemer".

        Zonder de specifiekere eerst te toetsen kreeg de residentiële categorie
        de bedragen van de niet-residentiële: 10,07 in plaats van 0,00 EUR per
        maand voor een gezin in 2026.
        """
        assert _waarde(rijen, 2026, "laag", "residentieel") == D("0.00")
        assert _waarde(rijen, 2026, "laag", "niet_residentieel") == D("10.07")

    def test_belgische_duizendtalnotatie(self, rijen):
        """"1.120,66" is elfhonderdtwintig komma zesenzestig, niet 1,12066."""
        assert _waarde(rijen, 2026, "hoog", "") == D("1120.66")
        assert _waarde(rijen, 2023, "hoog", "") == D("1060.83")

    def test_middenspanning(self, rijen):
        assert _waarde(rijen, 2022, "midden", "") == D("161.98")
        assert _waarde(rijen, 2026, "midden", "") == D("192.11")

    def test_beschermde_klanten_betalen_niets(self, rijen):
        for jaar in (2022, 2023, 2024, 2025, 2026):
            assert _waarde(rijen, jaar, "laag", "beschermd") == D("0.00")


class TestFoutafhandeling:
    def test_zonder_tabel_volgt_een_fout(self):
        with pytest.raises(EnergiefondsError, match="Geen tabel"):
            parse_tabel("<html><body><p>niets</p></body></html>")

    def test_zonder_jaartallen_in_de_kop_volgt_een_fout(self):
        """Een lege uitkomst zou als "niets gewijzigd" gelezen worden."""
        html = "<table><tr><td>Categorieën</td><td>Tarief</td></tr>" \
               "<tr><td>Residentiële afnemer</td><td>0,45</td></tr></table>"
        with pytest.raises(EnergiefondsError, match="Geen jaartallen"):
            parse_tabel(html)

    def test_onbekende_rijlabels_leveren_een_fout(self):
        """Wijzigt de pagina haar bewoording, dan moet dat opvallen."""
        html = (
            "<table><tr><td>Categorieën</td><td>Tarief (2026)</td></tr>"
            "<tr><td>Iets heel anders</td><td>1,00</td></tr></table>"
        )
        with pytest.raises(EnergiefondsError, match="Geen enkele categorie"):
            parse_tabel(html)

    def test_een_ontbrekend_bestand_is_een_duidelijke_fout(self, tmp_path):
        with pytest.raises(EnergiefondsError, match="niet gevonden"):
            lees_bestand(tmp_path / "bestaat_niet.html")


class TestTegenDeMasterdata:
    def test_de_gepubliceerde_tabel_komt_overeen_met_config(self, rijen):
        """Het invariant dat `scripts/check_energiefonds.py` bewaakt."""
        from energie_vlaanderen.heffingen.repository import HeffingenRepository

        repo = HeffingenRepository.load(
            Path(__file__).resolve().parents[1] / "config" / "heffingen"
        )
        eigen = {
            (t.jaar, t.spanningsniveau, t.klantcategorie): t.eur_per_maand
            for t in repo.energiefonds_tarieven()
        }
        for rij in rijen:
            assert eigen.get(rij.sleutel) == rij.eur_per_maand, rij.sleutel
