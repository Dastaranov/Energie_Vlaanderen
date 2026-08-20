from __future__ import annotations

import hashlib
import json
import logging
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .downloader import (
    ArtifactDownloader,
    DownloadBatch,
)
from .paths import DataPaths, DataPathsError


LOG = logging.getLogger(__name__)


class RawStoreError(RuntimeError):
    """Een raw-versie of manifest is ongeldig."""


@dataclass(frozen=True)
class RawArtifactRecord:
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
class RawManifest:
    schema_version: int
    version_id: str
    created_at: datetime
    directory: Path
    artifacts: dict[str, RawArtifactRecord]

    @property
    def manifest_path(self) -> Path:
        return self.directory / "manifest.json"

    def content_fingerprint(self) -> tuple[tuple[str, str], ...]:
        """
        Vergelijkbare representatie van de inhoud.

        Timestamps, URLs en bestandsnamen worden bewust niet gebruikt.
        Alleen brontype en checksum bepalen of de inhoud gelijk is.
        """

        return tuple(
            sorted(
                (
                    kind,
                    artifact.sha256,
                )
                for kind, artifact in self.artifacts.items()
            )
        )


@dataclass(frozen=True)
class RawVerificationReport:
    version_id: str
    directory: Path
    valid: bool
    checked_files: int
    errors: tuple[str, ...]
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class RawRegistrationResult:
    kept: bool
    version_id: str
    directory: Path
    duplicate_of: str | None = None


class RawStore:
    EXPECTED_KINDS = frozenset(
        ArtifactDownloader.STORED_FILENAMES
    )

    def __init__(
        self,
        paths: DataPaths,
    ):
        self.paths = paths

    def load_manifest(
        self,
        version_id: str,
    ) -> RawManifest:
        self.paths.validate_version_id(version_id)

        directory = self.paths.raw_dir(version_id)
        manifest_path = directory / "manifest.json"

        if not directory.is_dir():
            raise RawStoreError(
                f"Raw-versie bestaat niet: {directory}"
            )

        if not manifest_path.is_file():
            raise RawStoreError(
                f"Manifest ontbreekt: {manifest_path}"
            )

        try:
            data = json.loads(
                manifest_path.read_text(
                    encoding="utf-8"
                )
            )
        except json.JSONDecodeError as exc:
            raise RawStoreError(
                f"Manifest is geen geldige JSON: "
                f"{manifest_path}: {exc}"
            ) from exc

        if not isinstance(data, dict):
            raise RawStoreError(
                f"Manifest moet een JSON-object zijn: "
                f"{manifest_path}"
            )

        schema_version = self._required_integer(
            data,
            "schema_version",
        )

        if schema_version != 1:
            raise RawStoreError(
                "Niet-ondersteunde manifestversie: "
                f"{schema_version}"
            )

        manifest_version_id = self._required_text(
            data,
            "version_id",
        )

        if manifest_version_id != version_id:
            raise RawStoreError(
                "Versie-id in manifest komt niet overeen "
                f"met de map: {manifest_version_id!r} "
                f"tegenover {version_id!r}"
            )

        created_at = self._parse_datetime(
            self._required_text(
                data,
                "created_at",
            ),
            field_name="created_at",
        )

        artifact_data = data.get("artifacts")

        if not isinstance(artifact_data, dict):
            raise RawStoreError(
                "Manifestveld 'artifacts' moet "
                "een object zijn."
            )

        actual_kinds = set(artifact_data)
        missing = self.EXPECTED_KINDS - actual_kinds
        unexpected = actual_kinds - self.EXPECTED_KINDS

        if missing:
            raise RawStoreError(
                "Manifest mist brontypes: "
                + ", ".join(sorted(missing))
            )

        if unexpected:
            raise RawStoreError(
                "Manifest bevat onverwachte brontypes: "
                + ", ".join(sorted(unexpected))
            )

        artifacts: dict[str, RawArtifactRecord] = {}

        for kind in sorted(self.EXPECTED_KINDS):
            item = artifact_data[kind]

            if not isinstance(item, dict):
                raise RawStoreError(
                    f"Manifestrecord voor {kind} "
                    "moet een object zijn."
                )

            record_kind = self._required_text(
                item,
                "kind",
            )

            if record_kind != kind:
                raise RawStoreError(
                    f"Manifestrecord {kind!r} bevat "
                    f"kind {record_kind!r}"
                )

            stored_filename = self._required_text(
                item,
                "stored_filename",
            )

            expected_filename = (
                ArtifactDownloader
                .STORED_FILENAMES[kind]
            )

            if stored_filename != expected_filename:
                raise RawStoreError(
                    f"Onverwachte bestandsnaam voor {kind}: "
                    f"{stored_filename!r}"
                )

            if (
                Path(stored_filename).name
                != stored_filename
            ):
                raise RawStoreError(
                    f"Onveilige bestandsnaam voor {kind}: "
                    f"{stored_filename!r}"
                )

            digest = self._required_text(
                item,
                "sha256",
            ).casefold()

            if not self._is_sha256(digest):
                raise RawStoreError(
                    f"Ongeldige SHA-256 voor {kind}: "
                    f"{digest!r}"
                )

            size_bytes = self._required_integer(
                item,
                "size_bytes",
            )

            if size_bytes <= 0:
                raise RawStoreError(
                    f"Ongeldige bestandsgrootte voor "
                    f"{kind}: {size_bytes}"
                )

            artifacts[kind] = RawArtifactRecord(
                kind=kind,
                source_page_url=self._required_text(
                    item,
                    "source_page_url",
                ),
                source_url=self._required_text(
                    item,
                    "source_url",
                ),
                original_filename=self._required_text(
                    item,
                    "original_filename",
                ),
                stored_filename=stored_filename,
                sha256=digest,
                size_bytes=size_bytes,
                downloaded_at=self._parse_datetime(
                    self._required_text(
                        item,
                        "downloaded_at",
                    ),
                    field_name=(
                        f"artifacts."
                        f"{kind}.downloaded_at"
                    ),
                ),
                path=directory / stored_filename,
            )

        return RawManifest(
            schema_version=schema_version,
            version_id=version_id,
            created_at=created_at,
            directory=directory,
            artifacts=artifacts,
        )

    def verify(
        self,
        version_id: str,
    ) -> RawVerificationReport:
        errors: list[str] = []
        warnings: list[str] = []
        checked_files = 0

        try:
            manifest = self.load_manifest(
                version_id
            )
        except (
            RawStoreError,
            DataPathsError,
        ) as exc:
            return RawVerificationReport(
                version_id=version_id,
                directory=self.paths.raw / version_id,
                valid=False,
                checked_files=0,
                errors=(str(exc),),
                warnings=(),
            )

        expected_files = {
            artifact.stored_filename
            for artifact
            in manifest.artifacts.values()
        }

        expected_files.add("manifest.json")

        actual_files = {
            path.name
            for path in manifest.directory.iterdir()
            if path.is_file()
        }

        missing_files = expected_files - actual_files

        for filename in sorted(missing_files):
            errors.append(
                f"Bestand ontbreekt: {filename}"
            )

        unexpected_files = actual_files - expected_files

        for filename in sorted(unexpected_files):
            warnings.append(
                f"Onverwacht bestand aanwezig: {filename}"
            )

        for kind, artifact in manifest.artifacts.items():
            if not artifact.path.is_file():
                continue

            checked_files += 1

            actual_size = artifact.path.stat().st_size

            if actual_size != artifact.size_bytes:
                errors.append(
                    f"{kind}: bestandsgrootte wijkt af: "
                    f"manifest={artifact.size_bytes}, "
                    f"werkelijk={actual_size}"
                )

            actual_digest = self._file_sha256(
                artifact.path
            )

            if actual_digest != artifact.sha256:
                errors.append(
                    f"{kind}: SHA-256 wijkt af: "
                    f"manifest={artifact.sha256}, "
                    f"werkelijk={actual_digest}"
                )

            try:
                ArtifactDownloader._validate_xlsx(
                    artifact.path,
                    kind,
                )
            except Exception as exc:
                errors.append(
                    f"{kind}: XLSX-validatie mislukt: "
                    f"{exc}"
                )

        return RawVerificationReport(
            version_id=version_id,
            directory=manifest.directory,
            valid=not errors,
            checked_files=checked_files,
            errors=tuple(errors),
            warnings=tuple(warnings),
        )

    def list_manifests(
        self,
    ) -> list[RawManifest]:
        if not self.paths.raw.is_dir():
            return []

        manifests: list[RawManifest] = []

        for directory in sorted(
            self.paths.raw.iterdir(),
            reverse=True,
        ):
            if not directory.is_dir():
                continue

            try:
                self.paths.validate_version_id(
                    directory.name
                )

                manifest = self.load_manifest(
                    directory.name
                )
            except (
                RawStoreError,
                DataPathsError,
            ) as exc:
                LOG.warning(
                    "Raw-map %s overgeslagen: %s",
                    directory,
                    exc,
                )
                continue

            manifests.append(manifest)

        return manifests

    def find_duplicate(
        self,
        version_id: str,
    ) -> RawManifest | None:
        candidate = self.load_manifest(
            version_id
        )

        candidate_fingerprint = (
            candidate.content_fingerprint()
        )

        for manifest in self.list_manifests():
            if manifest.version_id == version_id:
                continue

            if (
                manifest.content_fingerprint()
                == candidate_fingerprint
            ):
                return manifest

        return None

    def register_batch(
        self,
        batch: DownloadBatch,
    ) -> RawRegistrationResult:
        report = self.verify(
            batch.version_id
        )

        if not report.valid:
            formatted = "\n".join(
                f"  - {error}"
                for error in report.errors
            )

            shutil.rmtree(
                batch.directory,
                ignore_errors=True,
            )

            raise RawStoreError(
                "Nieuwe raw-versie is ongeldig en werd "
                f"verwijderd:\n{formatted}"
            )

        duplicate = self.find_duplicate(
            batch.version_id
        )

        if duplicate is not None:
            shutil.rmtree(
                batch.directory,
                ignore_errors=True,
            )

            LOG.info(
                "Raw-versie %s verwijderd omdat ze "
                "identiek is aan %s",
                batch.version_id,
                duplicate.version_id,
            )

            return RawRegistrationResult(
                kept=False,
                version_id=batch.version_id,
                directory=batch.directory,
                duplicate_of=duplicate.version_id,
            )

        return RawRegistrationResult(
            kept=True,
            version_id=batch.version_id,
            directory=batch.directory,
            duplicate_of=None,
        )

    @staticmethod
    def _required_text(
        value: dict[str, Any],
        key: str,
    ) -> str:
        result = value.get(key)

        if not isinstance(result, str):
            raise RawStoreError(
                f"Manifestveld {key!r} moet tekst zijn."
            )

        result = result.strip()

        if not result:
            raise RawStoreError(
                f"Manifestveld {key!r} mag niet leeg zijn."
            )

        return result

    @staticmethod
    def _required_integer(
        value: dict[str, Any],
        key: str,
    ) -> int:
        result = value.get(key)

        if (
            not isinstance(result, int)
            or isinstance(result, bool)
        ):
            raise RawStoreError(
                f"Manifestveld {key!r} "
                "moet een geheel getal zijn."
            )

        return result

    @staticmethod
    def _parse_datetime(
        value: str,
        *,
        field_name: str,
    ) -> datetime:
        try:
            result = datetime.fromisoformat(
                value.replace(
                    "Z",
                    "+00:00",
                )
            )
        except ValueError as exc:
            raise RawStoreError(
                f"Ongeldige datum in {field_name}: "
                f"{value!r}"
            ) from exc

        if result.tzinfo is None:
            raise RawStoreError(
                f"Datum in {field_name} mist tijdzone: "
                f"{value!r}"
            )

        return result

    @staticmethod
    def _is_sha256(
        value: str,
    ) -> bool:
        if len(value) != 64:
            return False

        return all(
            character in "0123456789abcdef"
            for character in value
        )

    @staticmethod
    def _file_sha256(
        path: Path,
    ) -> str:
        digest = hashlib.sha256()

        with path.open("rb") as handle:
            while chunk := handle.read(
                1024 * 1024
            ):
                digest.update(chunk)

        return digest.hexdigest()