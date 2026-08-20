from __future__ import annotations

import io
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pytest
import requests

from energievergelijker_v3 import (
    DataPaths,
    Settings,
)
from energievergelijker_v3.downloader import (
    ArtifactDownloader,
    DownloadError,
)
from energievergelijker_v3.sources import (
    SourceArtifact,
)


def make_xlsx_bytes(
    *,
    extra_content: bytes = b"",
) -> bytes:
    buffer = io.BytesIO()

    with zipfile.ZipFile(
        buffer,
        mode="w",
        compression=zipfile.ZIP_DEFLATED,
    ) as archive:
        archive.writestr(
            "[Content_Types].xml",
            b"<?xml version='1.0'?>"
            b"<Types></Types>",
        )

        archive.writestr(
            "xl/workbook.xml",
            b"<?xml version='1.0'?>"
            b"<workbook></workbook>"
            + extra_content,
        )

    return buffer.getvalue()

class FakeResponse:
    def __init__(
        self,
        *,
        content: bytes,
        url: str,
        status_code: int = 200,
        headers: dict[str, str] | None = None,
    ):
        self.content = content
        self.url = url
        self.status_code = status_code
        self.headers = headers or {}
        self.closed = False

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            response = requests.Response()
            response.status_code = self.status_code
            response.url = self.url

            raise requests.HTTPError(
                f"HTTP {self.status_code}",
                response=response,
            )

    def iter_content(
        self,
        chunk_size: int,
    ):
        for start in range(
            0,
            len(self.content),
            chunk_size,
        ):
            yield self.content[
                start:start + chunk_size
            ]

    def close(self) -> None:
        self.closed = True


class FakeSession:
    def __init__(
        self,
        responses: dict[str, FakeResponse],
    ):
        self.responses = responses
        self.headers: dict[str, str] = {}
        self.calls: list[str] = []

    def get(
        self,
        url: str,
        *,
        timeout: float,
        stream: bool,
        allow_redirects: bool,
    ) -> FakeResponse:
        del timeout
        del stream
        del allow_redirects

        self.calls.append(url)
        return self.responses[url]

@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        project_root=tmp_path,
        data_root=tmp_path / "data",
        max_download_bytes=1024 * 1024,
        download_chunk_bytes=64,
    )


@pytest.fixture
def paths(settings: Settings) -> DataPaths:
    return DataPaths.from_settings(settings)


@pytest.fixture
def sources(
    settings: Settings,
) -> dict[str, SourceArtifact]:
    discovered_at = datetime(
        2026,
        8,
        20,
        12,
        0,
        tzinfo=timezone.utc,
    )

    result: dict[str, SourceArtifact] = {}

    for kind, filename in (
        ("vtest", "vtest-data.xlsx"),
        ("energy_curves", "energy-curves.xlsx"),
        (
            "electricity_tariffs",
            "electricity-tariffs.xlsx",
        ),
        ("gas_tariffs", "gas-tariffs.xlsx"),
    ):
        url = (
            "https://"
            + settings.allowed_download_hosts[0]
            + "/tests/"
            + filename
        )

        result[kind] = SourceArtifact(
            kind=kind,
            page_url="https://www.example.test/source-page",
            url=url,
            filename=filename,
            discovered_at=discovered_at,
        )

    return result


def fake_session_for_sources(
    sources: dict[str, SourceArtifact],
    *,
    content: bytes | None = None,
) -> FakeSession:
    workbook = (
        make_xlsx_bytes()
        if content is None
        else content
    )

    responses = {
        source.url: FakeResponse(
            content=workbook,
            url=source.url,
            headers={
                "Content-Length": str(len(workbook)),
            },
        )
        for source in sources.values()
    }

    return FakeSession(responses)

def test_download_batch_writes_four_files_and_manifest(
    settings: Settings,
    paths: DataPaths,
    sources: dict[str, SourceArtifact],
):
    session = fake_session_for_sources(
        sources
    )

    downloader = ArtifactDownloader(
        settings,
        session=session,
    )

    version_id = "20260820T120000Z-1234abcd"

    batch = downloader.download_batch(
        sources=sources,
        paths=paths,
        version_id=version_id,
    )

    assert batch.version_id == version_id
    assert batch.directory == paths.raw_dir(
        version_id
    )

    expected_files = {
        "vtest.xlsx",
        "energy_curves.xlsx",
        "electricity_tariffs.xlsx",
        "gas_tariffs.xlsx",
        "manifest.json",
    }

    actual_files = {
        path.name
        for path in batch.directory.iterdir()
    }

    assert actual_files == expected_files
    assert set(batch.artifacts) == set(
        ArtifactDownloader.STORED_FILENAMES
    )

    manifest = json.loads(
        batch.manifest_path.read_text(
            encoding="utf-8"
        )
    )

    assert manifest["schema_version"] == 1
    assert manifest["version_id"] == version_id
    assert set(
        manifest["artifacts"]
    ) == set(
        ArtifactDownloader.STORED_FILENAMES
    )

    for kind, artifact in batch.artifacts.items():
        assert artifact.path.is_file()
        assert artifact.size_bytes > 0
        assert len(artifact.sha256) == 64
        assert (
            manifest["artifacts"][kind]["sha256"]
            == artifact.sha256
        )

def test_download_rejects_html_instead_of_xlsx(
    settings: Settings,
    paths: DataPaths,
    sources: dict[str, SourceArtifact],
):
    session = fake_session_for_sources(
        sources,
        content=b"Dit is HTML en geen XLSX",
    )

    downloader = ArtifactDownloader(
        settings,
        session=session,
    )

    version_id = "20260820T120000Z-1234abcd"

    with pytest.raises(
        DownloadError,
        match="geen geldige ZIP/XLSX-signatuur",
    ):
        downloader.download_batch(
            sources=sources,
            paths=paths,
            version_id=version_id,
        )

    assert not paths.raw_dir(
        version_id
    ).exists()


def test_download_rejects_unexpected_host(
    settings: Settings,
    paths: DataPaths,
    sources: dict[str, SourceArtifact],
):
    original = sources["vtest"]

    sources["vtest"] = SourceArtifact(
        kind=original.kind,
        page_url=original.page_url,
        url="https://example.com/vtest.xlsx",
        filename=original.filename,
        discovered_at=original.discovered_at,
    )

    session = fake_session_for_sources(
        sources
    )

    downloader = ArtifactDownloader(
        settings,
        session=session,
    )

    with pytest.raises(
        DownloadError,
        match="niet-toegelaten host",
    ):
        downloader.download_batch(
            sources=sources,
            paths=paths,
            version_id=(
                "20260820T120000Z-1234abcd"
            ),
        )


def test_download_rejects_missing_source(
    settings: Settings,
    paths: DataPaths,
    sources: dict[str, SourceArtifact],
):
    del sources["gas_tariffs"]

    downloader = ArtifactDownloader(
        settings,
        session=FakeSession({}),
    )

    with pytest.raises(
        DownloadError,
        match="Ontbrekende bronnen",
    ):
        downloader.download_batch(
            sources=sources,
            paths=paths,
            version_id=(
                "20260820T120000Z-1234abcd"
            ),
        )


def test_download_rejects_declared_oversize(
    settings: Settings,
    paths: DataPaths,
    sources: dict[str, SourceArtifact],
):
    workbook = make_xlsx_bytes()

    responses = {
        source.url: FakeResponse(
            content=workbook,
            url=source.url,
            headers={
                "Content-Length": str(
                    settings.max_download_bytes + 1
                ),
            },
        )
        for source in sources.values()
    }

    downloader = ArtifactDownloader(
        settings,
        session=FakeSession(responses),
    )

    with pytest.raises(
        DownloadError,
        match="Content-Length",
    ):
        downloader.download_batch(
            sources=sources,
            paths=paths,
            version_id=(
                "20260820T120000Z-1234abcd"
            ),
        )


def test_download_rejects_existing_batch_directory(
    settings: Settings,
    paths: DataPaths,
    sources: dict[str, SourceArtifact],
):
    paths.ensure()

    version_id = "20260820T120000Z-1234abcd"
    paths.raw_dir(version_id).mkdir()

    downloader = ArtifactDownloader(
        settings,
        session=fake_session_for_sources(
            sources
        ),
    )

    with pytest.raises(
        DownloadError,
        match="bestaat al",
    ):
        downloader.download_batch(
            sources=sources,
            paths=paths,
            version_id=version_id,
        )