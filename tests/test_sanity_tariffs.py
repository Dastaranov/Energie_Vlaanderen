"""Tests voor de tariefcontrole in de sanity check.

Aanleiding: de controle zocht `tariffs_afname.csv` en `tariffs_injectie.csv`,
namen die de pipeline nooit gebruikt heeft — ze schrijft
`tariffs_electricity_afname.csv`, `tariffs_gas_afname.csv`, enzovoort. De
controle sloeg daardoor stil over en de sanity check meldde "geslaagd" zonder
één tariefrij bekeken te hebben.
"""

from __future__ import annotations

import pytest

from pathlib import Path

from energie_vlaanderen.audit.sanity import SanityChecker
from energie_vlaanderen.data.paths import DataPaths
from energie_vlaanderen.settings import Settings

VERSION_ID = "20260820T120000Z-1234abcd"

KOP = "Netbeheerder;Contracttype;Tarieftype;Tariefdetail;Tariefnotering;Klanttype;Prijs_num\n"


pytestmark = pytest.mark.databank


def _checker(tmp_path: Path, *bestanden: tuple[str, str]) -> SanityChecker:
    settings = Settings(project_root=tmp_path, data_root=tmp_path / "data")
    paths = DataPaths.from_settings(settings)
    paths.ensure()
    tariffs = paths.staging_dir(VERSION_ID) / "tariffs"
    tariffs.mkdir(parents=True)
    for naam, inhoud in bestanden:
        (tariffs / naam).write_text(KOP + inhoud, encoding="utf-8")
    return SanityChecker(paths)


def test_negatief_tarief_wordt_nu_wel_gevonden(tmp_path: Path):
    """Met de oude vaste bestandsnamen bleef dit onopgemerkt."""
    checker = _checker(
        tmp_path,
        (
            "tariffs_electricity_afname.csv",
            "FA;Afname;Netgebruik;kWh-tarief;EUR/kWh;ELEK_LS_DIGI;-0.05\n",
        ),
    )

    rapport = checker.check_version(VERSION_ID)

    assert not rapport.valid
    (schending,) = rapport.violations
    assert schending.file == "tariffs_electricity_afname.csv"
    assert "-0.05" in schending.message


def test_alle_energievormen_worden_gecontroleerd(tmp_path: Path):
    checker = _checker(
        tmp_path,
        (
            "tariffs_electricity_afname.csv",
            "FA;Afname;Netgebruik;kWh-tarief;EUR/kWh;ELEK_LS_DIGI;-0.01\n",
        ),
        (
            "tariffs_gas_afname.csv",
            "FA;Afname;;Proportionele term;EUR/kWh;GAS_T2;-0.02\n",
        ),
    )

    rapport = checker.check_version(VERSION_ID)

    bestanden = {v.file for v in rapport.violations}
    assert bestanden == {
        "tariffs_electricity_afname.csv",
        "tariffs_gas_afname.csv",
    }


def test_geldige_tarieven_geven_geen_schendingen(tmp_path: Path):
    checker = _checker(
        tmp_path,
        (
            "tariffs_electricity_afname.csv",
            "FA;Afname;Netgebruik;kWh-tarief;EUR/kWh;ELEK_LS_DIGI;0.0234492\n",
        ),
    )

    assert checker.check_version(VERSION_ID).valid


def test_lege_tariefmap_wordt_gemeld(tmp_path: Path):
    """Een tarievenmap zonder bestanden is geen geslaagde controle."""
    checker = _checker(tmp_path)

    rapport = checker.check_version(VERSION_ID)

    assert not rapport.valid
    assert "geen enkele tariffs_*.csv" in rapport.violations[0].message
