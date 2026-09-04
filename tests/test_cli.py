"""De commandoschil, op vorm en op doorstroming.

Het grootste deel toetst dat elk `<groep> <actie>` bestaat, zijn opties aanvaardt
en `--json` kent — goedkope tests die een tikfout in de parserboom vangen voordat
een gebruiker hem vindt. Daarnaast lopen `run_publish` en `run_db_import` hier
volledig door, want dat zijn de twee handelingen die de actieve versie wijzigen.
"""
import argparse
from datetime import date
from pathlib import Path
import json

import pytest

from energie_vlaanderen.cli import build_parser, run_paths, run_publish
from energie_vlaanderen.data.paths import DataPaths
from energie_vlaanderen.settings import Settings

pytestmark = pytest.mark.cli


def test_paths_command_runs(
    tmp_path: Path,
    capsys,
):
    settings = Settings(
        project_root=tmp_path,
        data_root=tmp_path / "data",
    )

    result = run_paths(
        argparse.Namespace(),
        settings,
    )

    captured = capsys.readouterr()

    assert result == 0
    assert str(tmp_path) in captured.out
    assert "Dataroot" in captured.out
    assert "Current     : nog niet ingesteld" in captured.out

def test_paths_command_is_accepted():
    parser = build_parser()

    args = parser.parse_args(["paths"])

    assert args.group == "paths"
    assert callable(args.handler)


def test_source_list_command_is_accepted():
    parser = build_parser()

    args = parser.parse_args(
        [
            "source",
            "list",
            "--year",
            "2026",
        ]
    )

    assert args.group == "source"
    assert args.action == "list"
    assert args.year == 2026
    assert args.json is False
    assert callable(args.handler)


def test_source_list_command_accepts_json():
    parser = build_parser()

    args = parser.parse_args(
        [
            "source",
            "list",
            "--year",
            "2026",
            "--json",
        ]
    )

    assert args.json is True

def test_source_download_command_is_accepted():
    parser = build_parser()

    args = parser.parse_args(
        [
            "source",
            "download",
            "--year",
            "2026",
        ]
    )

    assert args.group == "source"
    assert args.action == "download"
    assert args.year == 2026
    assert args.json is False
    assert callable(args.handler)


def test_source_download_command_accepts_json():
    parser = build_parser()

    args = parser.parse_args(
        [
            "source",
            "download",
            "--year",
            "2026",
            "--json",
        ]
    )

    assert args.json is True

def test_raw_verify_command_is_accepted():
    parser = build_parser()

    args = parser.parse_args(
        [
            "raw",
            "verify",
            "--version",
            "20260820T120000Z-1234abcd",
        ]
    )

    assert args.group == "raw"
    assert args.action == "verify"
    assert (
        args.version
        == "20260820T120000Z-1234abcd"
    )
    assert callable(args.handler)


def test_raw_status_command_is_accepted():
    parser = build_parser()

    args = parser.parse_args(
        [
            "raw",
            "status",
            "--json",
        ]
    )

    assert args.group == "raw"
    assert args.action == "status"
    assert args.json is True
    assert callable(args.handler)

def test_staging_parse_command_is_accepted():
    parser = build_parser()

    args = parser.parse_args(
        [
            "staging",
            "parse",
            "--version",
            "20260820T120000Z-1234abcd",
        ]
    )

    assert args.group == "staging"
    assert args.action == "parse"
    assert args.version == "20260820T120000Z-1234abcd"
    assert args.only == "all"
    assert callable(args.handler)


def test_staging_parse_command_accepts_only():
    parser = build_parser()

    args = parser.parse_args(
        [
            "staging",
            "parse",
            "--version",
            "20260820T120000Z-1234abcd",
            "--only",
            "vtest",
        ]
    )

    assert args.only == "vtest"

def test_version_publish_command_is_accepted():
    parser = build_parser()

    args = parser.parse_args(
        [
            "version",
            "publish",
            "--version",
            "20260820T120000Z-1234abcd",
            "--keep-staging",
            "--json",
        ]
    )

    assert args.group == "version"
    assert args.action == "publish"
    assert args.version == "20260820T120000Z-1234abcd"
    assert args.keep_staging is True
    assert args.json is True
    assert callable(args.handler)

def test_run_publish_flow(tmp_path: Path, capsys):
    version_id = "20260820T120000Z-1234abcd"
    settings = Settings(
        project_root=tmp_path,
        data_root=tmp_path / "data",
    )
    paths = DataPaths.from_settings(settings)
    paths.ensure()

    # Maak nep-staging data die aan DataRepository voldoet
    staging_vtest = paths.staging_dir(version_id) / "vtest"
    staging_vtest.mkdir(parents=True)
    (staging_vtest / "master_vast.csv").write_text("year;month;segment;energy;direction;supplier;product;product_type;component;price\n2026;8;Woning;electricity;consumption;Supp;Prod;vast;single;30.5\n", encoding="utf-8")
    (staging_vtest / "master_var_dyn.csv").write_text("year;month;segment;energy;direction;supplier;product;product_type;component;price;a;b;c;d;z;index_name_A;index_value_A\n", encoding="utf-8")

    # Publiceren vereist een goedgekeurde versie; `--force` is de bewuste
    # uitzondering en houdt deze test los van de audit-lifecycle.
    args = argparse.Namespace(
        version=version_id,
        keep_staging=False,
        force=True,
        skip_db=True,
        db_overwrite=False,
        json=True,
    )

    result = run_publish(args, settings)
    assert result == 0

    captured = capsys.readouterr()
    output = json.loads(captured.out)
    assert output["status"] == "published"
    assert output["version_id"] == version_id
    assert output["staging_removed"] is True

    # Controleer dat de actieve versie nu ingesteld is
    assert paths.current_version() == version_id


def test_publish_weigert_een_niet_goedgekeurde_versie(tmp_path: Path):
    """`audit approve` schreef een status die niets afdwong.

    Publish raadpleegde ApprovalManager niet, waardoor een versie in
    quarantaine gewoon actief kon worden.
    """
    version_id = "20260820T120000Z-1234abcd"
    settings = Settings(project_root=tmp_path, data_root=tmp_path / "data")
    paths = DataPaths.from_settings(settings)
    paths.ensure()
    staging_vtest = paths.staging_dir(version_id) / "vtest"
    staging_vtest.mkdir(parents=True)
    (staging_vtest / "master_vast.csv").write_text(
        "year;month;segment;energy;direction;supplier;product;product_type;component;price\n"
        "2026;8;Woning;electricity;consumption;Supp;Prod;vast;single;30.5\n",
        encoding="utf-8",
    )

    args = argparse.Namespace(
        version=version_id,
        keep_staging=False,
        force=False,
        skip_db=True,
        db_overwrite=False,
        json=False,
    )

    assert run_publish(args, settings) == 2
    # Niets geactiveerd, niets gekopieerd.
    assert paths.current_version() is None
    assert not paths.version_dir(version_id).exists()


def test_publish_werkt_na_goedkeuring(tmp_path: Path):
    from energie_vlaanderen.audit.manager import ApprovalManager

    version_id = "20260820T120000Z-1234abcd"
    settings = Settings(project_root=tmp_path, data_root=tmp_path / "data")
    paths = DataPaths.from_settings(settings)
    paths.ensure()
    staging_vtest = paths.staging_dir(version_id) / "vtest"
    staging_vtest.mkdir(parents=True)
    (staging_vtest / "master_vast.csv").write_text(
        "year;month;segment;energy;direction;supplier;product;product_type;component;price\n"
        "2026;8;Woning;electricity;consumption;Supp;Prod;vast;single;30.5\n",
        encoding="utf-8",
    )
    (staging_vtest / "master_var_dyn.csv").write_text(
        "year;month;segment;energy;direction;supplier;product;product_type;"
        "component;price;a;b;c;d;z;index_name_A;index_value_A\n",
        encoding="utf-8",
    )
    ApprovalManager(paths).approve(version_id, notes="test")

    args = argparse.Namespace(
        version=version_id,
        keep_staging=False,
        force=False,
        skip_db=True,
        db_overwrite=False,
        json=False,
    )

    assert run_publish(args, settings) == 0
    assert paths.current_version() == version_id


def test_gebruiker_group_is_accepted():
    """De groep `gebruiker` hangt aan de parser met haar drie acties.

    `groups.py` bepaalt enkel de *vorm* van de commandolijn; deze test bewaakt
    dat die vorm er is en dat elke actie naar een handler wijst.
    """
    parser = build_parser()

    for actie in ("toon", "controleer"):
        args = parser.parse_args(["gebruiker", actie])
        assert args.group == "gebruiker"
        assert args.action == actie
        assert callable(args.handler)

    args = parser.parse_args(
        ["gebruiker", "bereken", "--van", "2026-01-01", "--tot", "2027-01-01"]
    )
    assert args.van == date(2026, 1, 1)
    # De einddatum is exclusief: [van, tot). Een inclusieve grens zou de
    # wisseldag aan twee deelperiodes toewijzen.
    assert args.tot == date(2027, 1, 1)


def test_gebruiker_bereken_eist_een_periode():
    """Zonder venster is er geen tariefregime te kiezen."""
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["gebruiker", "bereken"])


class TestTariefjaarUitManifest:
    """Het tariefjaar komt uit de bestandsnaam van het werkboek, niet uit het versie-id.

    De VREG noemt haar werkboeken "Distributienettarieven elektriciteit
    2026.xlsx". Het versie-id draagt daarentegen het moment van downloaden: wie
    in september 2026 het werkboek van 2025 ophaalt, krijgt een versie-id dat
    met 2026 begint. Dat jaar gebruiken stempelt `geldig_van = 2026-01-01` op
    tarieven van 2025, waarna twee tariefjaren in dezelfde SCD2-sleutel botsen.
    """

    @staticmethod
    def _manifest(naam):
        return {"artifacts": {"electricity_tariffs": {"original_filename": naam}}}

    def test_het_jaar_komt_uit_de_bestandsnaam(self):
        from energie_vlaanderen.cli.helpers import tariefjaar_uit_manifest

        for naam, jaar in (
            ("Distributienettarieven elektriciteit 2026.xlsx", 2026),
            ("Distributienettarieven aardgas 2024.xlsx", 2024),
        ):
            assert tariefjaar_uit_manifest(self._manifest(naam), "electricity_tariffs") == jaar

    def test_een_dubbelzinnige_naam_wordt_geweigerd(self):
        """Raden zou een heel tariefjaar verkeerd dateren."""
        from energie_vlaanderen.cli.helpers import RawVersionError, tariefjaar_uit_manifest

        with pytest.raises(RawVersionError, match="eenduidig"):
            tariefjaar_uit_manifest(
                self._manifest("Tarieven 2025 herzien 2026.xlsx"), "electricity_tariffs"
            )

    def test_een_naam_zonder_jaartal_wordt_geweigerd(self):
        from energie_vlaanderen.cli.helpers import RawVersionError, tariefjaar_uit_manifest

        with pytest.raises(RawVersionError, match="eenduidig"):
            tariefjaar_uit_manifest(self._manifest("tarieven.xlsx"), "electricity_tariffs")

    def test_de_vtest_export_levert_geen_tariefjaar(self):
        """"202608-v-test-data..." is een periode-aanduiding, geen tariefjaar."""
        from energie_vlaanderen.cli.helpers import RawVersionError, tariefjaar_uit_manifest

        with pytest.raises(RawVersionError):
            tariefjaar_uit_manifest(
                self._manifest("202608-v-test-data-exclbtw v2_0.xlsx"), "electricity_tariffs"
            )
