"""Tests voor TariffPipeline — hoogspanning/middenspanning-CSV-split."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from energie_vlaanderen.ingest.tariffs.pipeline import TariffPipeline


def _write_rows(writer: pd.ExcelWriter, sheet_name: str, rows: list[list]) -> None:
    pd.DataFrame(rows).to_excel(writer, sheet_name=sheet_name, header=False, index=False)


def _build_elek_workbook(path: Path) -> None:
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        # FA ELEK Afname: header op Excel-rij 5, één rij met zowel LS- als
        # HS/MS-waarden (kolommen 5,6,8,9,11 = HS/MS/DC, 13,14,15 = LS).
        afname_rows = [
            ["Nettarieven Elektriciteit 2026"],
            [], [], [],
            ["1", "Netgebruik", None, "EUR/kWh"] + [None] * 12,  # Excel rij 5 (header)
            ["", "kWh-tarief", None, "EUR/kWh", None,
             0.02, 0.02, None, 0.02, 0.02, None, 0.02, None,
             0.023, 0.023, 0.023],  # Excel rij 6
        ]
        _write_rows(writer, "FA ELEK Afname", afname_rows)

        # FA ELEK Injectie: header op Excel-rij 3 (Bug A-structuur).
        injectie_rows = [
            ["Nettarieven Elektriciteit 2026"],
            [],
            [None, "Injectieklanten op 26-36 kV, 1-26 kV, distributiecabine "
                   "of op laagspanningsnet met piekmeting", None, "Tarief", "Eenheid"],
            [None, None, None, None, None],
            [1, "Tarief voor het netgebruik", None, 0.001751, "EUR/kWh"],
            [2, "Tarief databeheer", None, None, None],
            [None, "26-36 kV, 1-26 kV, distributiecabine", None, 57.65, "EUR/jaar"],
            [None, "Laagspanningnet", None, 17.85, "EUR/jaar"],
        ]
        _write_rows(writer, "FA ELEK Injectie", injectie_rows)


def _read_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, sep=";", encoding="utf-8-sig")


LS_KLANTTYPES = {"ELEK_LS_DIGI", "ELEK_LS_ANA", "ELEK_LS_ANA_PRO"}
HS_MS_KLANTTYPES = {"ELEK_HS1", "ELEK_HS2", "ELEK_MS1", "ELEK_MS2", "ELEK_LS_DC"}


def test_electricity_run_splits_hoogspanning_into_separate_csv(tmp_path: Path):
    workbook = tmp_path / "tarieven_elek.xlsx"
    _build_elek_workbook(workbook)

    result = TariffPipeline().process(
        source_path=workbook,
        destination=tmp_path / "staging",
        version_id="20260821T160221Z-ff1992b3",
        energy_type="electricity",
        overwrite=True,
    )

    assert result.hoogspanning_csv is not None
    assert result.hoogspanning_csv.is_file()

    afname = _read_csv(result.afname_csv)
    injectie = _read_csv(result.injectie_csv)
    hoogspanning = _read_csv(result.hoogspanning_csv)

    assert set(afname["Klanttype"]) <= LS_KLANTTYPES
    assert set(injectie["Klanttype"]) <= LS_KLANTTYPES
    assert set(hoogspanning["Klanttype"]) <= HS_MS_KLANTTYPES

    # Beide richtingen zitten in het gecombineerde hoogspanning-bestand.
    assert set(hoogspanning["Contracttype"]) == {"Afname", "Injectie"}

    # Steekproef: de HS/MS-waarde uit Injectie ("26-36 kV, ...") komt terug
    # voor de 5 HS/MS/DC-klanttypes, niet voor de LS-klanttypes.
    hs_injectie = hoogspanning[
        (hoogspanning["Contracttype"] == "Injectie") & (hoogspanning["Prijs_num"] == 57.65)
    ]
    assert set(hs_injectie["Klanttype"]) == HS_MS_KLANTTYPES


def test_gas_run_has_no_hoogspanning_csv(tmp_path: Path):
    """Regressiebewaking: gas kent geen HS/MS-equivalent, dus geen 3e bestand."""
    workbook = tmp_path / "tarieven_elek.xlsx"
    _build_elek_workbook(workbook)  # bevat geen GAS-sheets → lege frames voor gas

    result = TariffPipeline().process(
        source_path=workbook,
        destination=tmp_path / "staging",
        version_id="20260821T160221Z-ff1992b3",
        energy_type="gas",
        overwrite=True,
    )

    assert result.hoogspanning_csv is None
    assert not (result.directory / "tariffs_gas_hoogspanning.csv").exists()
