import argparse
from pathlib import Path
import json

from energie_vlaanderen.cli import build_parser, run_paths, run_publish
from energie_vlaanderen.data.paths import DataPaths
from energie_vlaanderen.settings import Settings

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

def test_sources_command_is_accepted():
    parser = build_parser()

    args = parser.parse_args(
        [
            "sources",
            "--year",
            "2026",
        ]
    )

    assert args.command == "sources"
    assert args.year == 2026
    assert args.json is False
    assert callable(args.handler)


def test_sources_command_accepts_json():
    parser = build_parser()

    args = parser.parse_args(
        [
            "sources",
            "--year",
            "2026",
            "--json",
        ]
    )

    assert args.json is True

def test_download_command_is_accepted():
    parser = build_parser()

    args = parser.parse_args(
        [
            "download",
            "--year",
            "2026",
        ]
    )

    assert args.command == "download"
    assert args.year == 2026
    assert args.json is False
    assert callable(args.handler)


def test_download_command_accepts_json():
    parser = build_parser()

    args = parser.parse_args(
        [
            "download",
            "--year",
            "2026",
            "--json",
        ]
    )

    assert args.json is True

def test_verify_raw_command_is_accepted():
    parser = build_parser()

    args = parser.parse_args(
        [
            "verify-raw",
            "--version",
            "20260820T120000Z-1234abcd",
        ]
    )

    assert args.command == "verify-raw"
    assert (
        args.version
        == "20260820T120000Z-1234abcd"
    )
    assert callable(args.handler)


def test_raw_status_command_is_accepted():
    parser = build_parser()

    args = parser.parse_args(
        [
            "raw-status",
            "--json",
        ]
    )

    assert args.command == "raw-status"
    assert args.json is True
    assert callable(args.handler)

def test_parse_vtest_command_is_accepted():
    parser = build_parser()

    args = parser.parse_args(
        [
            "parse-vtest",
            "--version",
            "20260820T120000Z-1234abcd",
        ]
    )

    assert args.command == "parse-vtest"
    assert args.version == "20260820T120000Z-1234abcd"
    assert callable(args.handler)

def test_publish_command_is_accepted():
    parser = build_parser()

    args = parser.parse_args(
        [
            "publish",
            "--version",
            "20260820T120000Z-1234abcd",
            "--keep-staging",
            "--json",
        ]
    )

    assert args.command == "publish"
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

    args = argparse.Namespace(
        version=version_id,
        keep_staging=False,
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