from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from energie_vlaanderen.data.paths import DataPaths

LOG = logging.getLogger(__name__)

class AuditError(RuntimeError):
    pass

@dataclass(frozen=True)
class AuditStatus:
    version_id: str
    status: str  # Keuzes: "quarantined", "approved", "rejected"
    updated_at: datetime
    notes: str

class ApprovalManager:
    def __init__(self, paths: DataPaths):
        self.paths = paths
        # Een centraal bestandje dat bijhoudt welke versie de 'Golden Master' is
        self.golden_pointer = self.paths.root / "golden_master.txt"

    def get_status(self, version_id: str) -> AuditStatus:
        """Haal de huidige goedkeuringsstatus op. Standaard is dit 'quarantined'."""
        status_file = self._status_file(version_id)
        if not status_file.exists():
            return AuditStatus(
                version_id=version_id,
                status="quarantined",
                updated_at=datetime.now(timezone.utc),
                notes="Nieuwe data, wacht op audit."
            )
        
        try:
            data = json.loads(status_file.read_text(encoding="utf-8"))
            return AuditStatus(
                version_id=data["version_id"],
                status=data["status"],
                updated_at=datetime.fromisoformat(data["updated_at"]),
                notes=data.get("notes", "")
            )
        except Exception as exc:
            LOG.warning("Kon audit-status voor %s niet lezen: %s", version_id, exc)
            return AuditStatus(
                version_id=version_id,
                status="quarantined",
                updated_at=datetime.now(timezone.utc),
                notes="Fout bij lezen status, veilige terugval naar quarantaine."
            )

    def approve(self, version_id: str, notes: str = "") -> AuditStatus:
        """Keur een versie officieel goed."""
        self.paths.validate_version_id(version_id)
        staging_dir = self.paths.staging / version_id
        
        if not staging_dir.exists():
            raise AuditError(f"Kan versie {version_id} niet goedkeuren: staging map bestaat niet.")
            
        status = AuditStatus(
            version_id=version_id,
            status="approved",
            updated_at=datetime.now(timezone.utc),
            notes=notes
        )
        self._write_status(status)
        LOG.info("Versie %s is goedgekeurd.", version_id)
        return status

    def reject(self, version_id: str, reason: str) -> AuditStatus:
        """Wijs een versie af (bijv. omdat de cijfers niet kloppen)."""
        status = AuditStatus(
            version_id=version_id,
            status="rejected",
            updated_at=datetime.now(timezone.utc),
            notes=reason
        )
        self._write_status(status)
        LOG.info("Versie %s is afgewezen: %s", version_id, reason)
        return status

    def set_golden_master(self, version_id: str) -> None:
        """Stel een versie in als de Golden Master (referentiekader voor de toekomst)."""
        status = self.get_status(version_id)
        if status.status != "approved":
            raise AuditError(
                f"Versie {version_id} moet eerst de status 'approved' "
                "hebben voordat het de Golden Master kan worden."
            )
        
        self.golden_pointer.write_text(version_id + "\n", encoding="utf-8")
        LOG.info("Golden Master is succesvol ingesteld op versie: %s", version_id)

    def get_golden_master(self) -> str | None:
        """Vraag op welke versie momenteel de Golden Master is."""
        if not self.golden_pointer.exists():
            return None
        return self.golden_pointer.read_text(encoding="utf-8").strip()

    def _status_file(self, version_id: str) -> Path:
        staging_dir = self.paths.staging / version_id
        staging_dir.mkdir(parents=True, exist_ok=True)
        return staging_dir / "audit_status.json"

    def _write_status(self, status: AuditStatus) -> None:
        status_file = self._status_file(status.version_id)
        data = {
            "version_id": status.version_id,
            "status": status.status,
            "updated_at": status.updated_at.isoformat(),
            "notes": status.notes
        }
        status_file.write_text(json.dumps(data, indent=2), encoding="utf-8")