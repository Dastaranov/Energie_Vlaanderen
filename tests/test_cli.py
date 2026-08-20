import argparse
from pathlib import Path

from energievergelijker_v3.cli import build_parser, run_paths
from energievergelijker_v3.config import Settings

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