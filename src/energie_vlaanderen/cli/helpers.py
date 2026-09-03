"""Gedeelde business-logica-glue voor de CLI-handlers.

Vervangt duplicatie die vroeger bijna letterlijk herhaald werd in meerdere
run_*-handlers: raw-versie verifiëren + manifest inlezen, artifact opzoeken,
en het generieke "log fout, geef exitcode 2 terug"-patroon.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
from pathlib import Path

from energie_vlaanderen.data.paths import DataPaths
from energie_vlaanderen.ingest.raw_store import RawStore, RawVerificationReport

LOG = logging.getLogger("energievergelijker")


class RawVersionError(Exception):
    """Een raw-versie of een van haar artifacts is ongeldig of onvindbaar."""


def fail(message: str, *args: object) -> int:
    """Log een foutmelding en geef de standaard fout-exitcode (2) terug."""

    LOG.error(message, *args)
    return 2


def require_valid_raw_version(
    paths: DataPaths,
    version_id: str,
) -> tuple[RawVerificationReport, dict]:
    """Verifieer een raw-versie en lever haar manifest-data.

    Raist RawVersionError met een klaar-om-te-loggen boodschap zodra de
    raw-versie ongeldig is of het manifest niet leesbaar is.
    """

    store = RawStore(paths)
    raw_report = store.verify(version_id)

    if not raw_report.valid:
        details = "\n".join(f"  - {error}" for error in raw_report.errors)
        raise RawVersionError(
            f"Raw-versie {version_id} is ongeldig.\n{details}"
        )

    manifest_path = raw_report.directory / "manifest.json"
    try:
        manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RawVersionError(f"Manifest is ongeldig: {exc}") from exc

    return raw_report, manifest_data


def resolve_artifact(
    manifest_data: dict,
    raw_report: RawVerificationReport,
    artifact_key: str,
) -> Path:
    """Zoek een artifact op in het manifest en geef het pad naar het bestand.

    Raist RawVersionError zodra de sleutel ontbreekt of het bestand niet bestaat.
    """

    try:
        artifact = manifest_data["artifacts"][artifact_key]
        stored_filename = artifact["stored_filename"]
    except (KeyError, TypeError) as exc:
        raise RawVersionError(
            f"Artifact {artifact_key!r} ontbreekt in manifest: {exc}"
        ) from exc

    source_path = raw_report.directory / stored_filename
    if not source_path.is_file():
        raise RawVersionError(f"Werkboek niet gevonden: {source_path}")

    return source_path


_JAAR_IN_NAAM = re.compile(r"\b(20\d{2})\b")


def tariefjaar_uit_manifest(manifest_data: dict, artifact_key: str) -> int:
    """Het tariefjaar van een werkboek, uit zijn oorspronkelijke bestandsnaam.

    Bewust *niet* uit het versie-id afgeleid. Een versie-id draagt het moment van
    downloaden, niet het jaar waarvoor de tarieven gelden: wie in september 2026
    het werkboek van 2025 ophaalt, krijgt een versie-id dat met 2026 begint. De
    databankimport stempelde daar `geldig_van = 2026-01-01` mee, waardoor twee
    tariefjaren in dezelfde SCD2-sleutel belanden en elkaar overschrijven.

    De VREG noemt haar werkboeken "Distributienettarieven elektriciteit
    2026.xlsx"; het manifest bewaart die naam in `original_filename`. Staan er
    meerdere jaartallen in, dan is de naam niet eenduidig en volgt een fout —
    raden zou hier een heel tariefjaar verkeerd dateren.
    """
    try:
        naam = manifest_data["artifacts"][artifact_key]["original_filename"]
    except (KeyError, TypeError) as exc:
        raise RawVersionError(
            f"Artifact {artifact_key!r} heeft geen original_filename in het "
            "manifest; het tariefjaar is niet te bepalen."
        ) from exc

    jaren = {int(j) for j in _JAAR_IN_NAAM.findall(str(naam))}
    if len(jaren) != 1:
        raise RawVersionError(
            f"Uit bestandsnaam {naam!r} is geen eenduidig tariefjaar af te "
            f"leiden (gevonden: {sorted(jaren) or 'geen'})."
        )
    return jaren.pop()


def relative_or_absolute(path: Path, project_root: Path) -> Path:
    """Geef path relatief aan project_root indien mogelijk, anders absoluut."""

    try:
        return path.relative_to(project_root)
    except ValueError:
        return path


def positive_integer(value: str) -> int:
    try:
        number = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "moet een geheel getal zijn"
        ) from exc

    if number <= 0:
        raise argparse.ArgumentTypeError(
            "moet groter zijn dan nul"
        )

    return number
