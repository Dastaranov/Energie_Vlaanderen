"""Tests voor TariffWorkbookParser — header-rij-selectie per sheettype.

De echte "* ELEK Injectie"-tabbladen hebben hun kop op Excel-rij 3, in
tegenstelling tot alle andere tarief-tabbladen (Afname, GAS Injectie) die hun
kop op Excel-rij 5 hebben. Deze tests bouwen een synthetisch workbook dat die
structuur nabootst en bewaken dat de header-rij-fix (workbook.py) enkel de
"* ELEK Injectie"-sheets raakt.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from energie_vlaanderen.ingest.tariffs.workbook import TariffWorkbookParser


def _write_rows(writer: pd.ExcelWriter, sheet_name: str, rows: list[list], startrow: int = 0) -> None:
    pd.DataFrame(rows).to_excel(writer, sheet_name=sheet_name, header=False, index=False, startrow=startrow)


def _build_workbook(path: Path) -> None:
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        # "FA ELEK Injectie": kop op Excel-rij 3 (index 2), data vanaf rij 4,
        # met een lege scheidingsrij op rij 4 — zoals in de echte bron.
        injectie_rows = [
            ["Nettarieven Elektriciteit 2026"],                                    # Excel rij 1
            [],                                                                     # Excel rij 2
            [None, "Injectieklanten op 26-36 kV, 1-26 kV, distributiecabine "
                   "of op laagspanningsnet met piekmeting", None, "Tarief", "Eenheid"],  # Excel rij 3 (header)
            [None, None, None, None, None],                                        # Excel rij 4 (leeg)
            [1, "Tarief voor het netgebruik", None, 0.001751, "EUR/kWh"],           # Excel rij 5
            [2, "Tarief databeheer", None, None, None],                            # Excel rij 6
            [None, "26-36 kV, 1-26 kV, distributiecabine", None, 57.65, "EUR/jaar"],  # Excel rij 7
            [None, "Laagspanningnet", None, 17.85, "EUR/jaar"],                     # Excel rij 8
        ]
        _write_rows(writer, "FA ELEK Injectie", injectie_rows)

        # "FA ELEK Afname": kop op Excel-rij 5 (index 4) — ongewijzigd gedrag.
        afname_rows = [
            ["Nettarieven Elektriciteit 2026"],   # Excel rij 1
            [],                                    # Excel rij 2
            [],                                    # Excel rij 3
            [],                                    # Excel rij 4
            ["1", "Netgebruik", None, "EUR/kWh"],  # Excel rij 5 (header)
            ["", "kWh-tarief", None, "EUR/kWh"] + [None] * 9 + [0.023, 0.023, 0.023],  # Excel rij 6
        ]
        _write_rows(writer, "FA ELEK Afname", afname_rows)

        # "FA GAS Injectie": kop op Excel-rij 5 — moet ongemoeid blijven.
        gas_rows = [
            ["Nettarieven Aardgas 2026"],   # Excel rij 1
            [],                              # Excel rij 2
            [],                              # Excel rij 3
            [],                              # Excel rij 4
            ["1)", "Systeembeheer", "EUR/kWh", None],  # Excel rij 5 (header)
            ["", "Het tarief voor het systeembeheer", "EUR/kWh", 0.000963],  # Excel rij 6
        ]
        _write_rows(writer, "FA GAS Injectie", gas_rows)


def test_elek_injectie_header_offset_is_fixed(tmp_path: Path):
    """Bug A: 'Tarief voor het netgebruik' (Excel rij 5) mag niet langer als
    header verbruikt worden — moet als eerste datarij naar buiten komen."""
    workbook_path = tmp_path / "tarieven_elek.xlsx"
    _build_workbook(workbook_path)

    parsed = TariffWorkbookParser().parse(workbook_path, energy_type="electricity")

    injectie = parsed.injectie
    assert not injectie.empty
    first = injectie.iloc[0]
    assert first.iloc[1] == "Tarief voor het netgebruik"
    assert first.iloc[3] == 0.001751
    assert int(first["source_row"]) == 5


def test_elek_afname_header_offset_unchanged(tmp_path: Path):
    """Regressiebewaking: Afname-sheets gebruiken nog steeds header=4 (Excel rij 5)."""
    workbook_path = tmp_path / "tarieven_elek.xlsx"
    _build_workbook(workbook_path)

    parsed = TariffWorkbookParser().parse(workbook_path, energy_type="electricity")

    afname = parsed.afname
    assert not afname.empty
    first = afname.iloc[0]
    assert first.iloc[1] == "kWh-tarief"
    assert int(first["source_row"]) == 6


def test_gas_injectie_header_offset_unaffected(tmp_path: Path):
    """GAS Injectie-sheets hadden de bug nooit — moeten header=4 blijven gebruiken."""
    workbook_path = tmp_path / "tarieven_elek.xlsx"
    _build_workbook(workbook_path)

    parsed = TariffWorkbookParser().parse(workbook_path, energy_type="gas")

    injectie = parsed.injectie
    assert not injectie.empty
    first = injectie.iloc[0]
    assert first.iloc[1] == "Het tarief voor het systeembeheer"
    assert int(first["source_row"]) == 6
