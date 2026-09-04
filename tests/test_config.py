"""`Settings`, de projectwortel en de netbeheerderlijst.

Een verkeerd gelezen instelling is stil: een timeout van 0 of een downloadlimiet
die als tekst blijft staan valt pas op als een download afbreekt. Daarom wordt
elke ondergrens hier expliciet geweigerd in plaats van overgenomen.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from energie_vlaanderen.settings import (
    DEFAULT_TARIFF_PAGE,
    DEFAULT_VTEST_PAGE,
    Settings,
    discover_project_root,
)


pytestmark = pytest.mark.bronnen


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

def test_enexis_is_een_bekende_netbeheerder_zonder_tarieven():
    """Baarle-Hertog (2387) krijgt zijn aardgas van Enexis, niet van Fluvius.

    De netbeheerder hoort herkend te worden — anders loopt de naam als
    onbekende code door de import — maar er zijn geen tarieven voor: die
    staan in een eigen, niet-ingelezen werkboek. Dat onderscheid moet
    expliciet blijven, anders gebruikt een gasberekening voor die postcode
    stilzwijgend een Fluvius-tarief.
    """
    from energie_vlaanderen.utility.constants import DNB_CODES, DNB_ZONDER_TARIEVEN

    assert DNB_CODES["Enexis Netbeheer"] == "ENEXIS"
    assert "ENEXIS" in DNB_ZONDER_TARIEVEN


def test_alle_netbeheerders_uit_de_gemeentelijst_zijn_bekend():
    """Een onbekende netbeheerder zou als volledige naam de databank in gaan."""
    import csv
    from pathlib import Path

    from energie_vlaanderen.utility.constants import DNB_CODES

    pad = Path(__file__).resolve().parents[1] / "data" / "current" / "DnbPerGemeente.csv"
    if not pad.is_file():
        import pytest

        pytest.skip("DnbPerGemeente.csv niet aanwezig")

    onbekend = set()
    with pad.open(encoding="utf-8-sig") as fh:
        for rij in csv.DictReader(fh, delimiter=";"):
            for kolom in ("DNB Elektriciteit", "DNB Gas"):
                naam = rij[kolom].strip()
                if naam and naam not in DNB_CODES:
                    onbekend.add(naam)

    assert onbekend == set()
