from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from energievergelijker_v3 import (
    DataPaths,
    DataPathsError,
    Settings,
)


@pytest.fixture
def paths(tmp_path: Path) -> DataPaths:
    settings = Settings(
        project_root=tmp_path,
        data_root=tmp_path / "data",
    )

    return DataPaths.from_settings(settings)


def test_ensure_creates_infrastructure(
    paths: DataPaths,
):
    paths.ensure()

    assert paths.root.is_dir()
    assert paths.raw.is_dir()
    assert paths.staging.is_dir()
    assert paths.versions.is_dir()
    assert paths.failed.is_dir()

    assert not paths.current_pointer.exists()


def test_new_version_id_is_safe(
    paths: DataPaths,
):
    version_id = paths.new_version_id(
        datetime(
            2026,
            8,
            20,
            10,
            30,
            tzinfo=timezone.utc,
        )
    )

    assert version_id.startswith("20260820T103000Z-")
    assert len(version_id) == 25

    paths.validate_version_id(version_id)


def test_current_data_dir_supports_legacy_current(
    paths: DataPaths,
):
    paths.current_legacy.mkdir(parents=True)

    assert (
        paths.current_data_dir()
        == paths.current_legacy
    )


def test_activate_and_resolve_version(
    paths: DataPaths,
):
    paths.ensure()

    version_id = "20260820T103000Z-1234abcd"
    version_dir = paths.version_dir(version_id)
    version_dir.mkdir()

    paths.activate(version_id)

    assert paths.current_version() == version_id
    assert paths.current_data_dir() == version_dir


def test_activate_rejects_missing_version(
    paths: DataPaths,
):
    paths.ensure()

    with pytest.raises(
        DataPathsError,
        match="Versiemap bestaat niet",
    ):
        paths.activate(
            "20260820T103000Z-1234abcd"
        )


def test_invalid_version_id_is_rejected(
    paths: DataPaths,
):
    with pytest.raises(
        DataPathsError,
        match="Ongeldige versie-id",
    ):
        paths.version_dir("../../ongewenst")


def test_missing_current_data_is_reported(
    paths: DataPaths,
):
    paths.ensure()

    with pytest.raises(
        DataPathsError,
        match="nog geen actieve dataset",
    ):
        paths.current_data_dir()