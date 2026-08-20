from __future__ import annotations

from pathlib import Path

import pytest

from energievergelijker_v3.config import (
    DEFAULT_TARIFF_PAGE,
    DEFAULT_VTEST_PAGE,
    Settings,
    discover_project_root,
)


def test_discover_project_root(tmp_path: Path):
    project = tmp_path / "project"
    nested = project / "src" / "package"

    nested.mkdir(parents=True)

    (project / "pyproject.toml").write_text(
        "[project]\nname = \"test\"\n",
        encoding="utf-8",
    )

    assert discover_project_root(nested) == project


def test_settings_uses_default_data_root(
    tmp_path: Path,
):
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname = \"test\"\n",
        encoding="utf-8",
    )

    settings = Settings.load(
        project_root=tmp_path,
        environ={},
    )

    assert settings.project_root == tmp_path.resolve()
    assert settings.data_root == (tmp_path / "data").resolve()
    assert settings.vtest_page_url == DEFAULT_VTEST_PAGE
    assert settings.tariff_page_url == DEFAULT_TARIFF_PAGE


def test_settings_uses_environment_data_root(
    tmp_path: Path,
):
    project = tmp_path / "project"
    external_data = tmp_path / "external-data"

    project.mkdir()

    settings = Settings.load(
        project_root=project,
        environ={
            "ENERGIEVERGELIJKER_DATA_DIR": str(
                external_data
            ),
        },
    )

    assert settings.data_root == external_data.resolve()


def test_settings_rejects_invalid_timeout(
    tmp_path: Path,
):
    with pytest.raises(
        ValueError,
        match="moet een getal zijn",
    ):
        Settings.load(
            project_root=tmp_path,
            environ={
                "ENERGIEVERGELIJKER_REQUEST_TIMEOUT": "later",
            },
        )


def test_settings_rejects_zero_timeout(
    tmp_path: Path,
):
    with pytest.raises(
        ValueError,
        match="groter zijn dan nul",
    ):
        Settings.load(
            project_root=tmp_path,
            environ={
                "ENERGIEVERGELIJKER_REQUEST_TIMEOUT": "0",
            },
        )

def test_settings_reads_download_limit(
    tmp_path: Path,
):
    settings = Settings.load(
        project_root=tmp_path,
        environ={
            "ENERGIEVERGELIJKER_MAX_DOWNLOAD_BYTES": "12345",
        },
    )

    assert settings.max_download_bytes == 12345


def test_settings_rejects_invalid_download_limit(
    tmp_path: Path,
):
    with pytest.raises(
        ValueError,
        match="moet een geheel getal zijn",
    ):
        Settings.load(
            project_root=tmp_path,
            environ={
                "ENERGIEVERGELIJKER_MAX_DOWNLOAD_BYTES": "veel",
            },
        )

def test_settings_rejects_zero_download_limit(
    tmp_path: Path,
):
    with pytest.raises(
        ValueError,
        match="groter zijn dan nul",
    ):
        Settings.load(
            project_root=tmp_path,
            environ={
                "ENERGIEVERGELIJKER_MAX_DOWNLOAD_BYTES": "0",
            },
        )