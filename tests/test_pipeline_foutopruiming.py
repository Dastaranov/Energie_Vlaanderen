"""Een schrijffout mag geen bestaand werk vernietigen.

Beide pipelines schreven hun uitvoer rechtstreeks op de eindbestemming en
ruimden bij een uitzondering op. Dat is de verkeerde volgorde: op het moment
dat het misgaat, is het oude al weg en het nieuwe nog niet af.

Twee vormen, en de eerste was de ergste:

- **`VTestPipeline`** deed `shutil.rmtree(target)` op `staging/<versie>/vtest/`
  — precies de map waarvan het commentaar erboven zegt dat de refine-output er
  niet uit mag verdwijnen. Eén schrijffout wiste dan een Selenium-scrape van
  een half uur plus alle opgehaalde contractdetailpanelen. Die zijn niet
  goedkoop opnieuw te maken; een CSV wel.
- **`TariffPipeline`** raakte alleen zijn eigen bestanden, maar met
  `--overwrite` waren die al overschreven. Een fout op het derde bestand kostte
  daarmee ook de twee geldige die er van de vorige run stonden.

Beide schrijven nu naar `.tijdelijk` en wisselen pas om als alles gelukt is.
De tests hieronder gaan door de gewone `process()`-ingang; er staat geen haak
voor tests in de productiecode.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

pytestmark = pytest.mark.parsers


def _vtest_werkboek(pad: Path) -> None:
    frame = pd.DataFrame([{
        "Jaar": 2026, "Maand": "aug", "Segment": "Woning",
        "Energietype": "Elektriciteit", "Contracttype": "Afname",
        "Handelsnaam": "Leverancier A", "Productnaam": "Product Vast",
        "Vast/variabel/dynamisch": "Vast",
        "Prijsonderdeel": "Enkelvoudige meter dagtarief", "Prijs": "30,50",
    }])
    with pd.ExcelWriter(pad, engine="openpyxl") as schrijver:
        frame.to_excel(schrijver, sheet_name="Vast", index=False)


class TestVtestPipelineLaatDeScrapeStaan:
    """Het geval waar het echt om gaat: de map deelt zijn inhoud met
    `staging refine`, en die kost een half uur Selenium."""

    def test_een_schrijffout_verwijdert_de_refine_output_niet(
        self, tmp_path, monkeypatch
    ):
        from energie_vlaanderen.ingest.vtest.pipeline import VTestPipeline

        werkboek = tmp_path / "vtest.xlsx"
        _vtest_werkboek(werkboek)

        bestemming = tmp_path / "staging"
        vtest = bestemming / "vtest"
        (vtest / "contractdetails").mkdir(parents=True)
        scrape = vtest / "vtest_products_woning_elektriciteit_9000.csv"
        scrape.write_text("dure;scrape;output\n", encoding="utf-8")
        paneel = vtest / "contractdetails" / "14972.html"
        paneel.write_text("<div>contractdetail</div>", encoding="utf-8")

        def stuk(frame: pd.DataFrame, pad: Path) -> None:
            raise OSError("schijf vol")

        monkeypatch.setattr(VTestPipeline, "_write_frame", staticmethod(stuk))

        with pytest.raises(OSError, match="schijf vol"):
            VTestPipeline().process(
                source_path=werkboek,
                destination=bestemming,
                version_id="20260820T120000Z-1234abcd",
            )

        assert scrape.is_file(), "de scrape-output is verdwenen"
        assert scrape.read_text(encoding="utf-8") == "dure;scrape;output\n"
        assert paneel.is_file(), "het contractdetailpaneel is verdwenen"
        assert not list(vtest.glob("*.tijdelijk"))

    def test_bij_een_geslaagde_run_blijft_er_niets_tijdelijks_staan(self, tmp_path):
        from energie_vlaanderen.ingest.vtest.pipeline import VTestPipeline

        werkboek = tmp_path / "vtest.xlsx"
        _vtest_werkboek(werkboek)
        resultaat = VTestPipeline().process(
            source_path=werkboek,
            destination=tmp_path / "staging",
            version_id="20260820T120000Z-1234abcd",
        )
        assert resultaat.fixed_csv.is_file()
        assert not list(resultaat.fixed_csv.parent.glob("*.tijdelijk"))


class TestTariefpipelineLaatBestaandeUitvoerStaan:
    def test_een_schrijffout_halverwege_raakt_de_vorige_run_niet(
        self, tmp_path, monkeypatch
    ):
        from tests.test_tariff_pipeline import _build_elek_workbook

        from energie_vlaanderen.ingest.tariffs.pipeline import TariffPipeline

        werkboek = tmp_path / "tarieven.xlsx"
        _build_elek_workbook(werkboek)

        bestemming = tmp_path / "staging"
        doel = bestemming / "tariffs"
        doel.mkdir(parents=True)
        vorige = {
            "tariffs_electricity_afname.csv": "geldige;data;van;gisteren\n",
            "tariffs_electricity_injectie.csv": "ook;geldig\n",
            "tariffs_electricity_report.json": '{"tarief_jaar": 2025}',
        }
        for naam, inhoud in vorige.items():
            (doel / naam).write_text(inhoud, encoding="utf-8")

        echt = TariffPipeline._write_frame
        beurten = {"n": 0}

        def stuk(frame: pd.DataFrame, pad: Path) -> None:
            beurten["n"] += 1
            if beurten["n"] == 2:      # de tweede van drie
                raise OSError("schijf vol")
            echt(frame, pad)

        monkeypatch.setattr(TariffPipeline, "_write_frame", staticmethod(stuk))

        with pytest.raises(OSError, match="schijf vol"):
            TariffPipeline().process(
                source_path=werkboek,
                destination=bestemming,
                version_id="20260820T120000Z-1234abcd",
                overwrite=True,
            )

        for naam, inhoud in vorige.items():
            assert (doel / naam).read_text(encoding="utf-8") == inhoud, (
                f"{naam} is aangetast door een mislukte run"
            )
        assert not list(doel.glob("*.tijdelijk"))
