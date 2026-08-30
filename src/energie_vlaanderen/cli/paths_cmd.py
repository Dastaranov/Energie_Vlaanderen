"""Commando: paths — toon de gebruikte configuratie- en datamappen."""

from __future__ import annotations

import argparse

from energie_vlaanderen.data.paths import DataPaths, DataPathsError
from energie_vlaanderen.settings import Settings


def show_paths(settings: Settings | None = None) -> int:
    active_settings = settings or Settings.load()

    paths = DataPaths.from_settings(active_settings)
    paths.ensure()

    print(f"Projectroot : {active_settings.project_root}")
    print(f"Dataroot    : {paths.root}")
    print(f"Raw         : {paths.raw}")
    print(f"Staging     : {paths.staging}")
    print(f"Versions    : {paths.versions}")
    print(f"Failed      : {paths.failed}")

    try:
        print(f"Current     : {paths.current_data_dir()}")
    except DataPathsError:
        print("Current     : nog niet ingesteld")

    return 0


def run_paths(args: argparse.Namespace, settings: Settings) -> int:
    del args
    return show_paths(settings)
