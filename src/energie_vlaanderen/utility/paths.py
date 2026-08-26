from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from ..settings import Settings


SAFE_VERSION_PATTERN = re.compile(
    r"^[0-9]{8}T[0-9]{6}Z-[a-f0-9]{8}$"
)


class DataPathsError(RuntimeError):
    pass


@dataclass(frozen=True)
class DataPaths:
    root: Path
    raw: Path
    staging: Path
    versions: Path
    failed: Path
    current_legacy: Path
    current_pointer: Path

    @classmethod
    def from_settings(
        cls,
        settings: Settings,
    ) -> "DataPaths":
        root = settings.data_root.expanduser().resolve()

        return cls(
            root=root,
            raw=root / "raw",
            staging=root / "staging",
            versions=root / "versions",
            failed=root / "failed",
            current_legacy=root / "current",
            current_pointer=root / "current.txt",
        )

    def ensure(self) -> None:
        """
        Maak alleen de vaste infrastructuurmappen aan.

        Er wordt nog geen actieve versie aangemaakt of gewijzigd.
        """

        for path in (
            self.root,
            self.raw,
            self.staging,
            self.versions,
            self.failed,
        ):
            path.mkdir(parents=True, exist_ok=True)

    def new_version_id(
        self,
        now: datetime | None = None,
    ) -> str:
        moment = now or datetime.now(timezone.utc)

        utc_moment = (
            moment.replace(tzinfo=timezone.utc)
            if moment.tzinfo is None
            else moment.astimezone(timezone.utc)
        )

        timestamp = utc_moment.strftime("%Y%m%dT%H%M%SZ")
        suffix = uuid4().hex[:8]

        return f"{timestamp}-{suffix}"

    def staging_dir(self, version_id: str) -> Path:
        self.validate_version_id(version_id)
        return self.staging / version_id

    def version_dir(self, version_id: str) -> Path:
        self.validate_version_id(version_id)
        return self.versions / version_id

    def raw_dir(self, version_id: str) -> Path:
        self.validate_version_id(version_id)
        return self.raw / version_id

    def failed_dir(self, version_id: str) -> Path:
        self.validate_version_id(version_id)
        return self.failed / version_id

    def current_version(self) -> str | None:
        """
        Geef de actieve versie terug.

        Tijdens de overgang ondersteunen we ook de bestaande
        data/current-map zonder current.txt.
        """

        if self.current_pointer.is_file():
            version_id = self.current_pointer.read_text(
                encoding="utf-8"
            ).strip()

            if not version_id:
                raise DataPathsError(
                    f"Lege versiepointer: {self.current_pointer}"
                )

            self.validate_version_id(version_id)
            return version_id

        return None

    def current_data_dir(self) -> Path:
        """
        Resolveer de map die DataRepository mag gebruiken.

        Prioriteit:
        1. current.txt met een gepubliceerde versie;
        2. bestaande data/current-map als overgangsoplossing.
        """

        version_id = self.current_version()

        if version_id is not None:
            target = self.version_dir(version_id)

            if not target.is_dir():
                raise DataPathsError(
                    "De actieve dataversie bestaat niet: "
                    f"{target}"
                )

            return target

        if self.current_legacy.is_dir():
            return self.current_legacy

        raise DataPathsError(
            "Er is nog geen actieve dataset. "
            f"Geen {self.current_pointer.name} en geen "
            f"{self.current_legacy} gevonden."
        )

    def activate(self, version_id: str) -> None:
        """
        Activeer een reeds volledig opgebouwde versie.

        Deze methode bouwt of valideert de dataset niet. Zij wijzigt
        uitsluitend de versiepointer.
        """

        target = self.version_dir(version_id)

        if not target.is_dir():
            raise DataPathsError(
                f"Versiemap bestaat niet: {target}"
            )

        temporary = self.current_pointer.with_suffix(".tmp")

        temporary.write_text(
            f"{version_id}\n",
            encoding="utf-8",
        )

        os.replace(
            temporary,
            self.current_pointer,
        )

    @staticmethod
    def validate_version_id(version_id: str) -> None:
        if not SAFE_VERSION_PATTERN.fullmatch(version_id):
            raise DataPathsError(
                f"Ongeldige versie-id: {version_id!r}"
            )