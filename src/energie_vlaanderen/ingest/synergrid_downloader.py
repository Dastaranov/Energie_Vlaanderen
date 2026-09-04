"""Download en verificatie van Synergrid-verbruiksprofielen.

Bewust een aparte, kleinere set klassen naast `downloader.py`/`raw_store.py`
in plaats van een uitbreiding daarvan: `ArtifactDownloader.STORED_FILENAMES`
en `RawStore.EXPECTED_KINDS` zijn *all-or-nothing* rond precies de 4
VREG-bronnen (maandelijkse cadans, altijd .xlsx). Synergrid publiceert
jaarlijks, in .xlsb, en hoeft niet in dezelfde batch als de VREG-bronnen te
zitten — elke maandelijkse `source download` zou anders 50+ MB aan
jaarbestanden meeslepen die niet gewijzigd zijn.

Zelfde disciplines als de VREG-variant: HTTPS + hostwhitelist, gestreamde
download met een grootte-limiet, SHA-256, een geldig-ZIP-containercheck vóór
het bestand als geldig geregistreerd wordt, en een schrijf-naar-tempfile +
atomische rename voor het manifest.
"""

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
from typing import Any
from urllib.parse import urlparse

import requests

from energie_vlaanderen.data.paths import DataPaths, DataPathsError
from energie_vlaanderen.ingest.zip_guard import (
    ZipBegrenzingOverschreden,
    controleer_zip_begrensd,
)
from energie_vlaanderen.ingest.sources import SourceArtifact
from energie_vlaanderen.settings import Settings

LOG = logging.getLogger(__name__)

XLSX_MAGIC = b"PK\x03\x04"
EXPECTED_XLSX_MEMBERS = {"[Content_Types].xml", "xl/workbook.xml"}
# Een .xlsb is ook een ZIP-container, maar met een binair werkboek in plaats
# van XML: xl/workbook.bin i.p.v. xl/workbook.xml.
EXPECTED_XLSB_MEMBERS = {"[Content_Types].xml", "xl/workbook.bin"}


class SynergridDownloadError(RuntimeError):
    """Een Synergrid-bronbestand kon niet veilig worden gedownload."""


class SynergridRawStoreError(RuntimeError):
    """Een Synergrid raw-versie of manifest is ongeldig."""


@dataclass(frozen=True)
class DownloadedSynergridArtifact:
    kind: str
    source_page_url: str
    source_url: str
    original_filename: str
    stored_filename: str
    path: Path
    sha256: str
    size_bytes: int
    downloaded_at: datetime

    def as_manifest_dict(self) -> dict[str, object]:
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
class SynergridDownloadBatch:
    version_id: str
    directory: Path
    manifest_path: Path
    artifacts: dict[str, DownloadedSynergridArtifact]


class SynergridDownloader:
    STORED_FILENAMES = {
        "slp_ex": "slp_ex.xlsb",
        "rlp0n_elektriciteit": "rlp0n_elektriciteit.xlsb",
        "rlp0n_gas": "rlp0n_gas.xlsb",
        "spp": "spp.xlsx",
    }

    def __init__(self, settings: Settings, *, session: requests.Session | None = None):
        self.settings = settings
        self.session = session or requests.Session()
        self.session.headers.update(
            {
                "User-Agent": settings.user_agent,
                "Accept": "application/octet-stream;q=0.9,*/*;q=0.1",
            }
        )

    def download_batch(
        self,
        *,
        sources: dict[str, SourceArtifact],
        paths: DataPaths,
        version_id: str | None = None,
    ) -> SynergridDownloadBatch:
        paths.ensure()

        active_version_id = version_id if version_id is not None else paths.new_version_id()
        paths.validate_version_id(active_version_id)

        # Synergrid-raw-versies leven in een eigen submap van raw/, niet
        # tussen de VREG-manifesten: de manifestvorm verschilt (andere
        # kinds), en RawStore.load_manifest zou een Synergrid-manifest
        # afwijzen als het in dezelfde map als een VREG-manifest stond.
        destination = paths.raw / "synergrid" / active_version_id

        if destination.exists():
            raise SynergridDownloadError(f"Downloadmap bestaat al: {destination}")

        destination.mkdir(parents=True, exist_ok=False)

        artifacts: dict[str, DownloadedSynergridArtifact] = {}

        try:
            self._validate_source_set(sources)

            for kind in self.STORED_FILENAMES:
                artifacts[kind] = self.download_one(source=sources[kind], destination=destination)

            manifest_path = self.write_manifest(
                version_id=active_version_id, destination=destination, artifacts=artifacts
            )

            return SynergridDownloadBatch(
                version_id=active_version_id,
                directory=destination,
                manifest_path=manifest_path,
                artifacts=artifacts,
            )
        except Exception:
            shutil.rmtree(destination, ignore_errors=True)
            raise

    def download_one(self, *, source: SourceArtifact, destination: Path) -> DownloadedSynergridArtifact:
        self._validate_source(source)

        stored_filename = self.STORED_FILENAMES.get(source.kind)
        if stored_filename is None:
            raise SynergridDownloadError(f"Onbekend brontype: {source.kind}")

        target = destination / stored_filename
        if target.exists():
            raise SynergridDownloadError(f"Doelbestand bestaat al: {target}")

        try:
            response = self.session.get(
                source.url,
                timeout=self.settings.request_timeout_seconds,
                stream=True,
                allow_redirects=True,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise SynergridDownloadError(f"Download mislukt voor {source.kind}: {exc}") from exc

        self._validate_final_url(response.url, source.kind)

        content_length = response.headers.get("Content-Length")
        if content_length:
            try:
                declared_size = int(content_length)
            except ValueError as exc:
                raise SynergridDownloadError(
                    f"Ongeldige Content-Length voor {source.kind}: {content_length!r}"
                ) from exc
            if declared_size > self.settings.max_download_bytes:
                raise SynergridDownloadError(
                    f"{source.kind} is volgens Content-Length te groot: {declared_size} bytes"
                )

        temporary_path: Path | None = None
        try:
            with NamedTemporaryFile(
                mode="wb", prefix=f".{source.kind}-", suffix=".part", dir=destination, delete=False
            ) as handle:
                temporary_path = Path(handle.name)
                digest = sha256()
                size_bytes = 0

                for chunk in response.iter_content(chunk_size=self.settings.download_chunk_bytes):
                    if not chunk:
                        continue
                    size_bytes += len(chunk)
                    if size_bytes > self.settings.max_download_bytes:
                        raise SynergridDownloadError(
                            f"{source.kind} overschrijdt de maximale downloadgrootte van "
                            f"{self.settings.max_download_bytes} bytes"
                        )
                    digest.update(chunk)
                    handle.write(chunk)

            if size_bytes == 0:
                raise SynergridDownloadError(f"Lege download ontvangen voor {source.kind}")

            self._validate_container(temporary_path, source.kind)

            os.replace(temporary_path, target)
            temporary_path = None

            downloaded = DownloadedSynergridArtifact(
                kind=source.kind,
                source_page_url=source.page_url,
                source_url=source.url,
                original_filename=source.filename,
                stored_filename=stored_filename,
                path=target,
                sha256=digest.hexdigest(),
                size_bytes=size_bytes,
                downloaded_at=datetime.now(timezone.utc),
            )
            LOG.info("%s gedownload: %s bytes, SHA-256 %s", source.kind, size_bytes, downloaded.sha256)
            return downloaded
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
            close = getattr(response, "close", None)
            if callable(close):
                close()

    def write_manifest(
        self, *, version_id: str, destination: Path, artifacts: dict[str, DownloadedSynergridArtifact]
    ) -> Path:
        manifest_path = destination / "manifest.json"
        temporary_path = destination / ".manifest.json.tmp"

        manifest = {
            "schema_version": 1,
            "source": "synergrid",
            "version_id": version_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "artifacts": {kind: artifact.as_manifest_dict() for kind, artifact in artifacts.items()},
        }

        temporary_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary_path, manifest_path)
        return manifest_path

    def _validate_source_set(self, sources: dict[str, SourceArtifact]) -> None:
        expected = set(self.STORED_FILENAMES)
        actual = set(sources)
        missing = expected - actual
        unexpected = actual - expected
        if missing:
            raise SynergridDownloadError("Ontbrekende bronnen: " + ", ".join(sorted(missing)))
        if unexpected:
            raise SynergridDownloadError("Onverwachte bronnen: " + ", ".join(sorted(unexpected)))
        for kind, artifact in sources.items():
            if artifact.kind != kind:
                raise SynergridDownloadError(
                    f"Bronsleutel {kind!r} komt niet overeen met artifact.kind {artifact.kind!r}"
                )

    def _validate_source(self, source: SourceArtifact) -> None:
        if source.kind not in self.STORED_FILENAMES:
            raise SynergridDownloadError(f"Onbekend brontype: {source.kind}")
        self._validate_url(source.url, source.kind)

    def _validate_url(self, url: str, kind: str) -> None:
        parsed = urlparse(url)
        if parsed.scheme != "https":
            raise SynergridDownloadError(f"{kind} gebruikt geen HTTPS-URL")

        host = parsed.hostname.casefold() if parsed.hostname else ""
        allowed_hosts = {value.casefold() for value in self.settings.allowed_download_hosts}
        if host not in allowed_hosts:
            raise SynergridDownloadError(f"{kind} gebruikt een niet-toegelaten host: {host!r}")

        path = parsed.path.casefold()
        if not (path.endswith(".xlsx") or path.endswith(".xlsb")):
            raise SynergridDownloadError(f"{kind} verwijst niet naar een XLSX- of XLSB-bestand")

    def _validate_final_url(self, url: str, kind: str) -> None:
        try:
            self._validate_url(url, kind)
        except SynergridDownloadError as exc:
            raise SynergridDownloadError(f"Redirect voor {kind} eindigde op een ongeldige URL: {url}") from exc

    @staticmethod
    def _validate_container(path: Path, kind: str) -> None:
        """Controleer dat het bestand een geldige ZIP-container is met de
        verplichte onderdelen van ofwel .xlsx ofwel .xlsb — de twee
        formaten die Synergrid publiceert."""
        with path.open("rb") as handle:
            signature = handle.read(len(XLSX_MAGIC))
        if signature != XLSX_MAGIC:
            raise SynergridDownloadError(f"{kind} heeft geen geldige ZIP-signatuur")

        if not zipfile.is_zipfile(path):
            raise SynergridDownloadError(f"{kind} is geen geldige ZIP-container")

        try:
            with zipfile.ZipFile(path, mode="r") as archive:
                # Begrensd, niet `testzip()` -- zie ingest/zip_guard.py. Juist
                # hier telt het: de Synergrid-werkboeken zijn de grootste
                # downloads die deze pipeline doet.
                try:
                    controleer_zip_begrensd(path, archive)
                except ZipBegrenzingOverschreden as exc:
                    raise SynergridDownloadError(
                        f"{kind} overschrijdt de ZIP-grenzen: {exc}"
                    ) from exc

                members = set(archive.namelist())
                if EXPECTED_XLSX_MEMBERS <= members:
                    return
                if EXPECTED_XLSB_MEMBERS <= members:
                    return

                raise SynergridDownloadError(
                    f"{kind} mist de verplichte onderdelen van een XLSX- of "
                    "XLSB-werkboek."
                )
        except zipfile.BadZipFile as exc:
            raise SynergridDownloadError(f"{kind} is geen geldige ZIP-container") from exc


@dataclass(frozen=True)
class SynergridRawArtifactRecord:
    kind: str
    source_page_url: str
    source_url: str
    original_filename: str
    stored_filename: str
    sha256: str
    size_bytes: int
    downloaded_at: datetime
    path: Path


@dataclass(frozen=True)
class SynergridRawManifest:
    schema_version: int
    version_id: str
    created_at: datetime
    directory: Path
    artifacts: dict[str, SynergridRawArtifactRecord]


@dataclass(frozen=True)
class SynergridRawVerificationReport:
    version_id: str
    directory: Path
    valid: bool
    checked_files: int
    errors: tuple[str, ...]
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class SynergridRawRegistrationResult:
    kept: bool
    version_id: str
    directory: Path
    duplicate_of: str | None = None


class SynergridRawStore:
    EXPECTED_KINDS = frozenset(SynergridDownloader.STORED_FILENAMES)

    def __init__(self, paths: DataPaths):
        self.paths = paths
        self._root = paths.raw / "synergrid"

    def load_manifest(self, version_id: str) -> SynergridRawManifest:
        self.paths.validate_version_id(version_id)

        directory = self._root / version_id
        manifest_path = directory / "manifest.json"

        if not directory.is_dir():
            raise SynergridRawStoreError(f"Synergrid raw-versie bestaat niet: {directory}")
        if not manifest_path.is_file():
            raise SynergridRawStoreError(f"Manifest ontbreekt: {manifest_path}")

        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise SynergridRawStoreError(f"Manifest is geen geldige JSON: {manifest_path}: {exc}") from exc

        if not isinstance(data, dict):
            raise SynergridRawStoreError(f"Manifest moet een JSON-object zijn: {manifest_path}")

        schema_version = self._required_integer(data, "schema_version")
        if schema_version != 1:
            raise SynergridRawStoreError(f"Niet-ondersteunde manifestversie: {schema_version}")

        manifest_version_id = self._required_text(data, "version_id")
        if manifest_version_id != version_id:
            raise SynergridRawStoreError(
                f"Versie-id in manifest komt niet overeen met de map: "
                f"{manifest_version_id!r} tegenover {version_id!r}"
            )

        created_at = self._parse_datetime(self._required_text(data, "created_at"), field_name="created_at")

        artifact_data = data.get("artifacts")
        if not isinstance(artifact_data, dict):
            raise SynergridRawStoreError("Manifestveld 'artifacts' moet een object zijn.")

        actual_kinds = set(artifact_data)
        missing = self.EXPECTED_KINDS - actual_kinds
        unexpected = actual_kinds - self.EXPECTED_KINDS
        if missing:
            raise SynergridRawStoreError("Manifest mist brontypes: " + ", ".join(sorted(missing)))
        if unexpected:
            raise SynergridRawStoreError("Manifest bevat onverwachte brontypes: " + ", ".join(sorted(unexpected)))

        artifacts: dict[str, SynergridRawArtifactRecord] = {}
        for kind in sorted(self.EXPECTED_KINDS):
            item = artifact_data[kind]
            if not isinstance(item, dict):
                raise SynergridRawStoreError(f"Manifestrecord voor {kind} moet een object zijn.")

            record_kind = self._required_text(item, "kind")
            if record_kind != kind:
                raise SynergridRawStoreError(f"Manifestrecord {kind!r} bevat kind {record_kind!r}")

            stored_filename = self._required_text(item, "stored_filename")
            expected_filename = SynergridDownloader.STORED_FILENAMES[kind]
            if stored_filename != expected_filename:
                raise SynergridRawStoreError(f"Onverwachte bestandsnaam voor {kind}: {stored_filename!r}")
            if Path(stored_filename).name != stored_filename:
                raise SynergridRawStoreError(f"Onveilige bestandsnaam voor {kind}: {stored_filename!r}")

            digest = self._required_text(item, "sha256").casefold()
            if not self._is_sha256(digest):
                raise SynergridRawStoreError(f"Ongeldige SHA-256 voor {kind}: {digest!r}")

            size_bytes = self._required_integer(item, "size_bytes")
            if size_bytes <= 0:
                raise SynergridRawStoreError(f"Ongeldige bestandsgrootte voor {kind}: {size_bytes}")

            artifacts[kind] = SynergridRawArtifactRecord(
                kind=kind,
                source_page_url=self._required_text(item, "source_page_url"),
                source_url=self._required_text(item, "source_url"),
                original_filename=self._required_text(item, "original_filename"),
                stored_filename=stored_filename,
                sha256=digest,
                size_bytes=size_bytes,
                downloaded_at=self._parse_datetime(
                    self._required_text(item, "downloaded_at"), field_name=f"artifacts.{kind}.downloaded_at"
                ),
                path=directory / stored_filename,
            )

        return SynergridRawManifest(
            schema_version=schema_version,
            version_id=version_id,
            created_at=created_at,
            directory=directory,
            artifacts=artifacts,
        )

    def verify(self, version_id: str) -> SynergridRawVerificationReport:
        errors: list[str] = []
        warnings: list[str] = []
        checked_files = 0

        try:
            manifest = self.load_manifest(version_id)
        except (SynergridRawStoreError, DataPathsError) as exc:
            return SynergridRawVerificationReport(
                version_id=version_id,
                directory=self._root / version_id,
                valid=False,
                checked_files=0,
                errors=(str(exc),),
                warnings=(),
            )

        expected_files = {a.stored_filename for a in manifest.artifacts.values()}
        expected_files.add("manifest.json")

        actual_files = {p.name for p in manifest.directory.iterdir() if p.is_file()}
        for filename in sorted(expected_files - actual_files):
            errors.append(f"Bestand ontbreekt: {filename}")
        for filename in sorted(actual_files - expected_files):
            warnings.append(f"Onverwacht bestand aanwezig: {filename}")

        for kind, artifact in manifest.artifacts.items():
            if not artifact.path.is_file():
                continue
            checked_files += 1

            actual_size = artifact.path.stat().st_size
            if actual_size != artifact.size_bytes:
                errors.append(
                    f"{kind}: bestandsgrootte wijkt af: manifest={artifact.size_bytes}, werkelijk={actual_size}"
                )

            actual_digest = self._file_sha256(artifact.path)
            if actual_digest != artifact.sha256:
                errors.append(f"{kind}: SHA-256 wijkt af: manifest={artifact.sha256}, werkelijk={actual_digest}")

            try:
                SynergridDownloader._validate_container(artifact.path, kind)
            except Exception as exc:
                errors.append(f"{kind}: containervalidatie mislukt: {exc}")

        return SynergridRawVerificationReport(
            version_id=version_id,
            directory=manifest.directory,
            valid=not errors,
            checked_files=checked_files,
            errors=tuple(errors),
            warnings=tuple(warnings),
        )

    def list_manifests(self) -> list[SynergridRawManifest]:
        if not self._root.is_dir():
            return []

        manifests: list[SynergridRawManifest] = []
        for directory in sorted(self._root.iterdir(), reverse=True):
            if not directory.is_dir():
                continue
            try:
                self.paths.validate_version_id(directory.name)
                manifests.append(self.load_manifest(directory.name))
            except (SynergridRawStoreError, DataPathsError) as exc:
                LOG.warning("Synergrid raw-map %s overgeslagen: %s", directory, exc)
                continue
        return manifests

    def find_duplicate(self, version_id: str) -> SynergridRawManifest | None:
        candidate = self.load_manifest(version_id)
        candidate_fp = self._fingerprint(candidate)
        for manifest in self.list_manifests():
            if manifest.version_id == version_id:
                continue
            if self._fingerprint(manifest) == candidate_fp:
                return manifest
        return None

    def register_batch(self, batch: SynergridDownloadBatch) -> SynergridRawRegistrationResult:
        report = self.verify(batch.version_id)
        if not report.valid:
            formatted = "\n".join(f"  - {error}" for error in report.errors)
            shutil.rmtree(batch.directory, ignore_errors=True)
            raise SynergridRawStoreError(
                f"Nieuwe Synergrid raw-versie is ongeldig en werd verwijderd:\n{formatted}"
            )

        duplicate = self.find_duplicate(batch.version_id)
        if duplicate is not None:
            shutil.rmtree(batch.directory, ignore_errors=True)
            LOG.info(
                "Synergrid raw-versie %s verwijderd omdat ze identiek is aan %s",
                batch.version_id, duplicate.version_id,
            )
            return SynergridRawRegistrationResult(
                kept=False, version_id=batch.version_id, directory=batch.directory,
                duplicate_of=duplicate.version_id,
            )

        return SynergridRawRegistrationResult(
            kept=True, version_id=batch.version_id, directory=batch.directory, duplicate_of=None,
        )

    @staticmethod
    def _fingerprint(manifest: SynergridRawManifest) -> tuple[tuple[str, str], ...]:
        return tuple(sorted((kind, artifact.sha256) for kind, artifact in manifest.artifacts.items()))

    @staticmethod
    def _required_text(value: dict[str, Any], key: str) -> str:
        result = value.get(key)
        if not isinstance(result, str):
            raise SynergridRawStoreError(f"Manifestveld {key!r} moet tekst zijn.")
        result = result.strip()
        if not result:
            raise SynergridRawStoreError(f"Manifestveld {key!r} mag niet leeg zijn.")
        return result

    @staticmethod
    def _required_integer(value: dict[str, Any], key: str) -> int:
        result = value.get(key)
        if not isinstance(result, int) or isinstance(result, bool):
            raise SynergridRawStoreError(f"Manifestveld {key!r} moet een geheel getal zijn.")
        return result

    @staticmethod
    def _parse_datetime(value: str, *, field_name: str) -> datetime:
        try:
            result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise SynergridRawStoreError(f"Ongeldige datum in {field_name}: {value!r}") from exc
        if result.tzinfo is None:
            raise SynergridRawStoreError(f"Datum in {field_name} mist tijdzone: {value!r}")
        return result

    @staticmethod
    def _is_sha256(value: str) -> bool:
        return len(value) == 64 and all(c in "0123456789abcdef" for c in value)

    @staticmethod
    def _file_sha256(path: Path) -> str:
        digest = sha256()
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
        return digest.hexdigest()
