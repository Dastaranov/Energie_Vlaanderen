"""Synergrid-verbruiksprofielen: bron ontdekken/downloaden, verifiëren, parsen.

Aparte groep naast `source`/`raw` (die de VREG-bronnen beheren): Synergrid
publiceert jaarlijks in plaats van maandelijks, in .xlsb in plaats van
.xlsx, en heeft daarom een eigen raw-store (`SynergridRawStore`) met een
eigen manifestvorm — zie `ingest/synergrid_downloader.py` voor de reden om
dit niet in `ArtifactDownloader`/`RawStore` te persen.
"""

from __future__ import annotations

import argparse
import logging

from energie_vlaanderen.cli.helpers import fail
from energie_vlaanderen.cli.output import emit
from energie_vlaanderen.data.paths import DataPaths
from energie_vlaanderen.ingest.profielen.pipeline import ProfielenPipeline, ProfielenPipelineError
from energie_vlaanderen.ingest.synergrid_downloader import (
    SynergridDownloader,
    SynergridRawStore,
    SynergridRawStoreError,
)
from energie_vlaanderen.ingest.synergrid_sources import SynergridSourceScraper
from energie_vlaanderen.settings import Settings

LOG = logging.getLogger("energievergelijker")

# (profiel_type, energie_type, artifact_kind in het Synergrid-manifest)
_PROFIEL_COMBINATIES = (
    ("slp_ex", None, "slp_ex"),
    ("rlp0n", "elektriciteit", "rlp0n_elektriciteit"),
    ("rlp0n", "gas", "rlp0n_gas"),
    ("spp", None, "spp"),
)


# ---------------------------------------------------------
# synergrid list
# ---------------------------------------------------------

def run_synergrid_list(args: argparse.Namespace, settings: Settings) -> int:
    scraper = SynergridSourceScraper(settings)
    sources = scraper.discover(args.year)

    def _text() -> None:
        for kind, artifact in sources.items():
            print(kind)
            print(f"  bestandsnaam : {artifact.filename}")
            print(f"  url          : {artifact.url}")
            print()

    emit(
        args,
        text_fn=_text,
        json_obj={kind: artifact.as_dict() for kind, artifact in sources.items()},
    )
    return 0


# ---------------------------------------------------------
# synergrid download
# ---------------------------------------------------------

def run_synergrid_download(args: argparse.Namespace, settings: Settings) -> int:
    paths = DataPaths.from_settings(settings)
    scraper = SynergridSourceScraper(settings)
    downloader = SynergridDownloader(settings)

    LOG.info("Synergrid-profielen ontdekken voor jaar %s ...", args.year)
    sources = scraper.discover(args.year)

    LOG.info("%d bron(nen) gevonden, downloaden ...", len(sources))
    batch = downloader.download_batch(sources=sources, paths=paths)

    LOG.info("Download voltooid, registreren in de Synergrid raw store ...")
    store = SynergridRawStore(paths)
    registration = store.register_batch(batch)

    if not registration.kept:
        def _unchanged_text() -> None:
            print(
                "Geen nieuwe Synergrid-brondata: inhoud is identiek aan "
                f"raw-versie {registration.duplicate_of}."
            )

        emit(
            args,
            text_fn=_unchanged_text,
            json_obj={
                "status": "unchanged",
                "version_id": registration.version_id,
                "duplicate_of": registration.duplicate_of,
            },
        )
        return 0

    def _text() -> None:
        print(f"Synergrid raw-versie : {batch.version_id}")
        print(f"Map                  : {batch.directory}")
        print()
        for kind, artifact in batch.artifacts.items():
            print(kind)
            print(f"  bestand   : {artifact.stored_filename}")
            print(f"  bronnaam  : {artifact.original_filename}")
            print(f"  grootte   : {artifact.size_bytes} bytes")
            print(f"  sha256    : {artifact.sha256}")
            print()

    emit(
        args,
        text_fn=_text,
        json_obj={
            "version_id": batch.version_id,
            "directory": str(batch.directory),
            "artifacts": {
                kind: artifact.as_manifest_dict() for kind, artifact in batch.artifacts.items()
            },
        },
    )
    return 0


# ---------------------------------------------------------
# synergrid verify
# ---------------------------------------------------------

def run_synergrid_verify(args: argparse.Namespace, settings: Settings) -> int:
    paths = DataPaths.from_settings(settings)
    store = SynergridRawStore(paths)
    report = store.verify(args.version)

    def _text() -> None:
        print(f"Synergrid raw-versie : {report.version_id}")
        print(f"Map                  : {report.directory}")
        print(f"Gecontroleerd        : {report.checked_files} bestanden")
        print(f"Geldig               : {'ja' if report.valid else 'nee'}")
        if report.warnings:
            print()
            print("Waarschuwingen:")
            for warning in report.warnings:
                print(f"  - {warning}")
        if report.errors:
            print()
            print("Fouten:")
            for error in report.errors:
                print(f"  - {error}")

    emit(
        args,
        text_fn=_text,
        json_obj={
            "version_id": report.version_id,
            "directory": str(report.directory),
            "valid": report.valid,
            "checked_files": report.checked_files,
            "errors": list(report.errors),
            "warnings": list(report.warnings),
        },
    )
    return 0 if report.valid else 2


# ---------------------------------------------------------
# synergrid status
# ---------------------------------------------------------

def run_synergrid_status(args: argparse.Namespace, settings: Settings) -> int:
    paths = DataPaths.from_settings(settings)
    store = SynergridRawStore(paths)
    manifests = store.list_manifests()

    rows: list[dict[str, object]] = []
    for manifest in manifests:
        report = store.verify(manifest.version_id)
        rows.append(
            {
                "version_id": manifest.version_id,
                "created_at": manifest.created_at.isoformat(),
                "valid": report.valid,
                "checked_files": report.checked_files,
                "errors": list(report.errors),
                "warnings": list(report.warnings),
            }
        )

    def _text() -> None:
        if not rows:
            print("Geen Synergrid raw-versies gevonden.")
            return
        for row in rows:
            print(row["version_id"])
            print(f"  aangemaakt : {row['created_at']}")
            print(f"  geldig     : {'ja' if row['valid'] else 'nee'}")
            print()

    emit(args, text_fn=_text, json_obj=rows)
    return 0


# ---------------------------------------------------------
# staging parse --only profielen
# ---------------------------------------------------------

def run_parse_profielen(args: argparse.Namespace, settings: Settings) -> int:
    """Verwerk de vier Synergrid-profielbestanden naar staging.

    Gebruikt bewust een eigen `--synergrid-version` i.p.v. de gewone
    `--version`: die laatste wijst naar een VREG raw-versie
    (`RawStore`/`ArtifactDownloader`), Synergrid heeft een eigen raw-store
    met een eigen, jaarlijkse cadans (`SynergridRawStore`). De
    stagingbestemming zelf (`staging/<--version>/profielen/`) volgt wél de
    gewone `--version`, zodat profielen naast vtest/tariffs/curves in
    dezelfde stagingmap kunnen landen.
    """
    synergrid_version = getattr(args, "synergrid_version", None)
    if not synergrid_version:
        return fail(
            "--synergrid-version is verplicht bij --only profielen "
            "(de raw-versie van 'energievergelijker synergrid download')."
        )

    jaar = getattr(args, "jaar", None)
    if not jaar:
        return fail("--jaar is verplicht bij --only profielen.")

    paths = DataPaths.from_settings(settings)
    store = SynergridRawStore(paths)

    try:
        report = store.verify(synergrid_version)
    except SynergridRawStoreError as exc:
        return fail("%s", exc)

    if not report.valid:
        details = "\n".join(f"  - {e}" for e in report.errors)
        return fail("Synergrid raw-versie %s is ongeldig.\n%s", synergrid_version, details)

    manifest = store.load_manifest(synergrid_version)
    staging_dest = paths.staging / args.version
    pipeline = ProfielenPipeline()

    processed: list[dict[str, object]] = []
    for profiel_type, energie_type, artifact_kind in _PROFIEL_COMBINATIES:
        artifact = manifest.artifacts[artifact_kind]
        label = f"{profiel_type}/{energie_type}" if energie_type else profiel_type

        LOG.info("Profiel %s verwerken ...", label)
        try:
            result = pipeline.process(
                source_path=artifact.path,
                destination=staging_dest,
                version_id=args.version,
                profiel_type=profiel_type,
                energie_type=energie_type,
                jaar=jaar,
                overwrite=args.overwrite,
            )
        except ProfielenPipelineError as exc:
            return fail("Profielenpipeline [%s] geweigerd: %s", label, exc)

        print(f"[{label}] {result.rows} rijen -> {result.csv_path}")
        processed.append(
            {
                "profiel_type": profiel_type,
                "energie_type": energie_type,
                "rows": result.rows,
                "csv_path": str(result.csv_path),
                "report_json": str(result.report_json),
            }
        )

    if args.json:
        from energie_vlaanderen.cli.output import print_json

        print_json(processed)
    return 0
