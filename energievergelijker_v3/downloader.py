from __future__ import annotations

import json
import logging
import os
import shutil
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from tempfile import NamedTemporaryFile
from urllib.parse import urlparse

import requests

from .config import Settings
from .paths import DataPaths
from .sources import SourceArtifact


LOG = logging.getLogger(__name__)

XLSX_MAGIC = b"PK\x03\x04"

EXPECTED_XLSX_MEMBERS = {
    "[Content_Types].xml",
    "xl/workbook.xml",
}


class DownloadError(RuntimeError):
    """Een bronbestand kon niet veilig worden gedownload."""


@dataclass(frozen=True)
class DownloadedArtifact:
    kind: str
    source_page_url: str
    source_url: str
    original_filename: str
    stored_filename: str
    path: Path
    sha256: str
    size_bytes: int
    downloaded_at: datetime

    def as_manifest_dict(
        self,
    ) -> dict[str, object]:
        return {
            "kind": self.kind,
            "source_page_url": self.source_page_url,
            "source_url": self.source_url,
            "original_filename": self.original_filename,
            "stored_filename": self.stored_filename,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
            "downloaded_at": self.downloaded_at.isoformat(),
        }


@dataclass(frozen=True)
class DownloadBatch:
    version_id: str
    directory: Path
    manifest_path: Path
    artifacts: dict[str, DownloadedArtifact]


class ArtifactDownloader:
    STORED_FILENAMES = {
        "vtest": "vtest.xlsx",
        "energy_curves": "energy_curves.xlsx",
        "electricity_tariffs": "electricity_tariffs.xlsx",
        "gas_tariffs": "gas_tariffs.xlsx",
    }

    def __init__(
        self,
        settings: Settings,
        *,
        session: requests.Session | None = None,
    ):
        self.settings = settings
        self.session = session or requests.Session()

        self.session.headers.update(
            {
                "User-Agent": settings.user_agent,
                "Accept": (
                    "application/vnd.openxmlformats-"
                    "officedocument.spreadsheetml.sheet,"
                    "application/octet-stream;q=0.9,"
                    "*/*;q=0.1"
                ),
            }
        )

    def download_batch(
        self,
        *,
        sources: dict[str, SourceArtifact],
        paths: DataPaths,
        version_id: str | None = None,
    ) -> DownloadBatch:
        paths.ensure()

        active_version_id = (
            version_id
            if version_id is not None
            else paths.new_version_id()
        )

        paths.validate_version_id(active_version_id)

        destination = paths.raw_dir(active_version_id)

        if destination.exists():
            raise DownloadError(
                f"Downloadmap bestaat al: {destination}"
            )

        destination.mkdir(
            parents=True,
            exist_ok=False,
        )

        artifacts: dict[str, DownloadedArtifact] = {}

        try:
            self._validate_source_set(sources)

            for kind in self.STORED_FILENAMES:
                artifact = self.download_one(
                    source=sources[kind],
                    destination=destination,
                )

                artifacts[kind] = artifact

            manifest_path = self.write_manifest(
                version_id=active_version_id,
                destination=destination,
                artifacts=artifacts,
            )

            return DownloadBatch(
                version_id=active_version_id,
                directory=destination,
                manifest_path=manifest_path,
                artifacts=artifacts,
            )
        except Exception:
            shutil.rmtree(
                destination,
                ignore_errors=True,
            )
            raise

    def download_one(
        self,
        *,
        source: SourceArtifact,
        destination: Path,
    ) -> DownloadedArtifact:
        self._validate_source(source)

        stored_filename = self.STORED_FILENAMES.get(
            source.kind
        )

        if stored_filename is None:
            raise DownloadError(
                f"Onbekend brontype: {source.kind}"
            )

        target = destination / stored_filename

        if target.exists():
            raise DownloadError(
                f"Doelbestand bestaat al: {target}"
            )

        try:
            response = self.session.get(
                source.url,
                timeout=self.settings.request_timeout_seconds,
                stream=True,
                allow_redirects=True,
            )

            response.raise_for_status()
        except requests.RequestException as exc:
            raise DownloadError(
                f"Download mislukt voor {source.kind}: {exc}"
            ) from exc

        self._validate_final_url(
            response.url,
            source.kind,
        )

        content_length = response.headers.get(
            "Content-Length"
        )

        if content_length:
            try:
                declared_size = int(content_length)
            except ValueError as exc:
                raise DownloadError(
                    f"Ongeldige Content-Length voor "
                    f"{source.kind}: {content_length!r}"
                ) from exc

            if declared_size > self.settings.max_download_bytes:
                raise DownloadError(
                    f"{source.kind} is volgens Content-Length "
                    f"te groot: {declared_size} bytes"
                )

        temporary_path: Path | None = None

        try:
            with NamedTemporaryFile(
                mode="wb",
                prefix=f".{source.kind}-",
                suffix=".part",
                dir=destination,
                delete=False,
            ) as handle:
                temporary_path = Path(handle.name)

                digest = sha256()
                size_bytes = 0

                for chunk in response.iter_content(
                    chunk_size=(
                        self.settings.download_chunk_bytes
                    )
                ):
                    if not chunk:
                        continue

                    size_bytes += len(chunk)

                    if (
                        size_bytes
                        > self.settings.max_download_bytes
                    ):
                        raise DownloadError(
                            f"{source.kind} overschrijdt de "
                            "maximale downloadgrootte van "
                            f"{self.settings.max_download_bytes} "
                            "bytes"
                        )

                    digest.update(chunk)
                    handle.write(chunk)

            if size_bytes == 0:
                raise DownloadError(
                    f"Lege download ontvangen voor {source.kind}"
                )

            self._validate_xlsx(
                temporary_path,
                source.kind,
            )

            os.replace(
                temporary_path,
                target,
            )

            temporary_path = None

            downloaded = DownloadedArtifact(
                kind=source.kind,
                source_page_url=source.page_url,
                source_url=source.url,
                original_filename=source.filename,
                stored_filename=stored_filename,
                path=target,
                sha256=digest.hexdigest(),
                size_bytes=size_bytes,
                downloaded_at=datetime.now(
                    timezone.utc
                ),
            )

            LOG.info(
                "%s gedownload: %s bytes, SHA-256 %s",
                source.kind,
                size_bytes,
                downloaded.sha256,
            )

            return downloaded
        finally:
            if temporary_path is not None:
                temporary_path.unlink(
                    missing_ok=True
                )

            close = getattr(
                response,
                "close",
                None,
            )

            if callable(close):
                close()

    def write_manifest(
        self,
        *,
        version_id: str,
        destination: Path,
        artifacts: dict[str, DownloadedArtifact],
    ) -> Path:
        manifest_path = destination / "manifest.json"
        temporary_path = destination / ".manifest.json.tmp"

        manifest = {
            "schema_version": 1,
            "version_id": version_id,
            "created_at": datetime.now(
                timezone.utc
            ).isoformat(),
            "artifacts": {
                kind: artifact.as_manifest_dict()
                for kind, artifact
                in artifacts.items()
            },
        }

        temporary_path.write_text(
            json.dumps(
                manifest,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )

        os.replace(
            temporary_path,
            manifest_path,
        )

        return manifest_path

    def _validate_source_set(
        self,
        sources: dict[str, SourceArtifact],
    ) -> None:
        expected = set(self.STORED_FILENAMES)
        actual = set(sources)

        missing = expected - actual
        unexpected = actual - expected

        if missing:
            raise DownloadError(
                "Ontbrekende bronnen: "
                + ", ".join(sorted(missing))
            )

        if unexpected:
            raise DownloadError(
                "Onverwachte bronnen: "
                + ", ".join(sorted(unexpected))
            )

        for kind, artifact in sources.items():
            if artifact.kind != kind:
                raise DownloadError(
                    f"Bronsleutel {kind!r} komt niet overeen "
                    f"met artifact.kind {artifact.kind!r}"
                )

    def _validate_source(
        self,
        source: SourceArtifact,
    ) -> None:
        if source.kind not in self.STORED_FILENAMES:
            raise DownloadError(
                f"Onbekend brontype: {source.kind}"
            )

        self._validate_url(
            source.url,
            source.kind,
        )

    def _validate_url(
        self,
        url: str,
        kind: str,
    ) -> None:
        parsed = urlparse(url)

        if parsed.scheme != "https":
            raise DownloadError(
                f"{kind} gebruikt geen HTTPS-URL"
            )

        host = (
            parsed.hostname.casefold()
            if parsed.hostname
            else ""
        )

        allowed_hosts = {
            value.casefold()
            for value
            in self.settings.allowed_download_hosts
        }

        if host not in allowed_hosts:
            raise DownloadError(
                f"{kind} gebruikt een niet-toegelaten host: "
                f"{host!r}"
            )

        if not parsed.path.casefold().endswith(".xlsx"):
            raise DownloadError(
                f"{kind} verwijst niet naar een XLSX-bestand"
            )

    def _validate_final_url(
        self,
        url: str,
        kind: str,
    ) -> None:
        try:
            self._validate_url(
                url,
                kind,
            )
        except DownloadError as exc:
            raise DownloadError(
                f"Redirect voor {kind} eindigde op een "
                f"ongeldige URL: {url}"
            ) from exc

    @staticmethod
    def _validate_xlsx(
        path: Path,
        kind: str,
    ) -> None:
        with path.open("rb") as handle:
            signature = handle.read(
                len(XLSX_MAGIC)
            )

        if signature != XLSX_MAGIC:
            raise DownloadError(
                f"{kind} heeft geen geldige ZIP/XLSX-signatuur"
            )

        if not zipfile.is_zipfile(path):
            raise DownloadError(
                f"{kind} is geen geldige ZIP-container"
            )

        try:
            with zipfile.ZipFile(
                path,
                mode="r",
            ) as archive:
                bad_member = archive.testzip()

                if bad_member is not None:
                    raise DownloadError(
                        f"{kind} bevat een beschadigd "
                        f"ZIP-lid: {bad_member}"
                    )

                members = set(
                    archive.namelist()
                )

                missing = (
                    EXPECTED_XLSX_MEMBERS
                    - members
                )

                if missing:
                    raise DownloadError(
                        f"{kind} mist verplichte "
                        "XLSX-onderdelen: "
                        + ", ".join(sorted(missing))
                    )
        except zipfile.BadZipFile as exc:
            raise DownloadError(
                f"{kind} is geen geldige XLSX-container"
            ) from exc
