from __future__ import annotations

import hashlib
import io
import json
import zipfile
from pathlib import Path

import pytest

from energie_vlaanderen.data.paths import DataPaths
from energie_vlaanderen.settings import Settings
from energie_vlaanderen.ingest.raw_store import (
    RawStore,
    RawStoreError,
)


KINDS_TO_FILENAMES = {
    "vtest": "vtest.xlsx",
    "energy_curves": "energy_curves.xlsx",
    "electricity_tariffs": "electricity_tariffs.xlsx",
    "gas_tariffs": "gas_tariffs.xlsx",
}


def make_xlsx_bytes(
    marker: str = "default",
) -> bytes:
    buffer = io.BytesIO()

    with zipfile.ZipFile(
        buffer,
        mode="w",
        compression=zipfile.ZIP_DEFLATED,
    ) as archive:
        archive.writestr(
            "[Content_Types].xml",
            (
                "<?xml version='1.0'?>"
                "<Types></Types>"
            ),
        )

        archive.writestr(
            "xl/workbook.xml",
            (
                "<?xml version='1.0'?>"
                f"<workbook>{marker}</workbook>"
            ),
        )

    return buffer.getvalue()


@pytest.fixture
def paths(
    tmp_path: Path,
) -> DataPaths:
    settings = Settings(
        project_root=tmp_path,
        data_root=tmp_path / "data",
    )

    result = DataPaths.from_settings(
        settings
    )

    result.ensure()

    return result


def write_raw_version(
    paths: DataPaths,
    version_id: str,
    marker: str = "default",
) -> Path:
    directory = paths.raw_dir(
        version_id
    )

    directory.mkdir(
        parents=True
    )

    artifacts: dict[str, dict[str, object]] = {}

    for kind, filename in KINDS_TO_FILENAMES.items():
        content = make_xlsx_bytes(
            f"{marker}-{kind}"
        )

        path = directory / filename
        path.write_bytes(content)

        artifacts[kind] = {
            "kind": kind,
            "source_page_url": (
                "https://www.example.test/page"
            ),
            "source_url": (
                "https://assets."
                "vlaamsenutsregulator.be/"
                f"{filename}"
            ),
            "original_filename": filename,
            "stored_filename": filename,
            "sha256": hashlib.sha256(
                content
            ).hexdigest(),
            "size_bytes": len(content),
            "downloaded_at": (
                "2026-08-20T12:00:00+00:00"
            ),
        }

    manifest = {
        "schema_version": 1,
        "version_id": version_id,
        "created_at": (
            "2026-08-20T12:00:00+00:00"
        ),
        "artifacts": artifacts,
    }

    manifest_path = directory / "manifest.json"

    manifest_path.write_text(
        json.dumps(
            manifest,
            indent=2,
        ),
        encoding="utf-8",
    )

    return directory


def test_load_and_verify_valid_raw_version(
    paths: DataPaths,
):
    version_id = "20260820T120000Z-1234abcd"

    write_raw_version(
        paths,
        version_id,
    )

    store = RawStore(paths)

    manifest = store.load_manifest(
        version_id
    )

    assert manifest.version_id == version_id

    assert set(manifest.artifacts) == set(
        KINDS_TO_FILENAMES
    )

    report = store.verify(
        version_id
    )

    assert report.valid
    assert report.checked_files == 4
    assert report.errors == ()


def test_verify_detects_changed_file(
    paths: DataPaths,
):
    version_id = "20260820T120000Z-1234abcd"

    directory = write_raw_version(
        paths,
        version_id,
    )

    changed_file = directory / "vtest.xlsx"

    with changed_file.open("ab") as handle:
        handle.write(
            b"beschadiging"
        )

    report = RawStore(paths).verify(
        version_id
    )

    assert not report.valid

    assert any(
        "vtest" in error
        and (
            "bestandsgrootte" in error
            or "SHA-256" in error
        )
        for error in report.errors
    )


def test_verify_detects_missing_file(
    paths: DataPaths,
):
    version_id = "20260820T120000Z-1234abcd"

    directory = write_raw_version(
        paths,
        version_id,
    )

    missing_file = (
        directory
        / "gas_tariffs.xlsx"
    )

    missing_file.unlink()

    report = RawStore(paths).verify(
        version_id
    )

    assert not report.valid

    assert any(
        "gas_tariffs.xlsx" in error
        for error in report.errors
    )

def test_verify_reports_unexpected_file_as_warning(
    paths: DataPaths,
):
    version_id = "20260820T120000Z-1234abcd"

    directory = write_raw_version(
        paths,
        version_id,
    )

    (
        directory / "notitie.txt"
    ).write_text(
        "extra",
        encoding="utf-8",
    )

    report = RawStore(paths).verify(
        version_id
    )

    assert report.valid
    assert any(
        "notitie.txt" in warning
        for warning in report.warnings
    )

def test_load_rejects_wrong_version_id(
    paths: DataPaths,
):
    version_id = "20260820T120000Z-1234abcd"

    directory = write_raw_version(
        paths,
        version_id,
    )

    manifest_path = directory / "manifest.json"
    data = json.loads(
        manifest_path.read_text(
            encoding="utf-8"
        )
    )

    data["version_id"] = (
        "20260820T120000Z-deadbeef"
    )

    manifest_path.write_text(
        json.dumps(data),
        encoding="utf-8",
    )

    with pytest.raises(
        RawStoreError,
        match="komt niet overeen",
    ):
        RawStore(paths).load_manifest(
            version_id
        )


def test_load_rejects_invalid_checksum(
    paths: DataPaths,
):
    version_id = "20260820T120000Z-1234abcd"

    directory = write_raw_version(
        paths,
        version_id,
    )

    manifest_path = directory / "manifest.json"
    data = json.loads(
        manifest_path.read_text(
            encoding="utf-8"
        )
    )

    data["artifacts"]["vtest"]["sha256"] = (
        "geen-checksum"
    )

    manifest_path.write_text(
        json.dumps(data),
        encoding="utf-8",
    )

    with pytest.raises(
        RawStoreError,
        match="Ongeldige SHA-256",
    ):
        RawStore(paths).load_manifest(
            version_id
        )

def test_find_duplicate_detects_identical_content(
    paths: DataPaths,
):
    first = "20260820T120000Z-11111111"
    second = "20260820T130000Z-22222222"

    write_raw_version(
        paths,
        first,
        marker="identiek",
    )

    write_raw_version(
        paths,
        second,
        marker="identiek",
    )

    duplicate = RawStore(
        paths
    ).find_duplicate(second)

    assert duplicate is not None
    assert duplicate.version_id == first


def test_find_duplicate_ignores_changed_content(
    paths: DataPaths,
):
    first = "20260820T120000Z-11111111"
    second = "20260820T130000Z-22222222"

    write_raw_version(
        paths,
        first,
        marker="oud",
    )

    write_raw_version(
        paths,
        second,
        marker="nieuw",
    )

    duplicate = RawStore(
        paths
    ).find_duplicate(second)

    assert duplicate is None