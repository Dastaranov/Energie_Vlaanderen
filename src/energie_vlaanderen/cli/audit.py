"""Auditcommando's: quarantaine → goedkeuring → Golden Master lifecycle."""

from __future__ import annotations

import argparse
import json
import logging

from energie_vlaanderen.audit.golden import TariffGoldenAuditor, VTestGoldenAuditor
from energie_vlaanderen.audit.manager import ApprovalManager, AuditError
from energie_vlaanderen.audit.sampler import DataSampler
from energie_vlaanderen.audit.sanity import SanityChecker
from energie_vlaanderen.cli.helpers import fail
from energie_vlaanderen.cli.output import emit
from energie_vlaanderen.data.paths import DataPaths
from energie_vlaanderen.ingest.raw_store import RawStore
from energie_vlaanderen.settings import Settings

LOG = logging.getLogger("energievergelijker")


# ---------------------------------------------------------
# audit-golden
# ---------------------------------------------------------

def run_audit_golden(args: argparse.Namespace, settings: Settings) -> int:
    """Vergelijk gestagede CSVs cel voor cel met de bron-XLSX."""
    paths = DataPaths.from_settings(settings)
    store = RawStore(paths)
    version_id = args.version

    raw_report = store.verify(version_id)
    if not raw_report.valid:
        return fail("Raw-versie %s is ongeldig.", version_id)

    manifest_path = raw_report.directory / "manifest.json"
    try:
        manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return fail("Manifest is ongeldig: %s", exc)

    staging_dir = paths.staging / version_id
    vtest_dir = staging_dir / "vtest"
    tariffs_dir = staging_dir / "tariffs"

    all_results = []

    # --- V-test ---
    try:
        vtest_artifact = manifest_data["artifacts"]["vtest"]
        vtest_xlsx = raw_report.directory / vtest_artifact["stored_filename"]
    except (KeyError, TypeError):
        LOG.warning("V-testartifact ontbreekt in manifest, audit overgeslagen.")
        vtest_xlsx = None

    if vtest_xlsx and vtest_xlsx.is_file():
        auditor = VTestGoldenAuditor()
        for domain, csv_name in [("vtest_vast", "master_vast.csv"), ("vtest_var_dyn", "master_var_dyn.csv")]:
            result = auditor.audit(
                staged_csv=vtest_dir / csv_name,
                source_xlsx=vtest_xlsx,
                domain=domain,
                version_id=version_id,
            )
            all_results.append(result)

    # --- Tarieven ---
    tariff_sources = {
        "electricity": "electricity_tariffs",
        "gas": "gas_tariffs",
    }
    t_auditor = TariffGoldenAuditor()
    for energy_type, artifact_key in tariff_sources.items():
        try:
            artifact = manifest_data["artifacts"][artifact_key]
            xlsx_path = raw_report.directory / artifact["stored_filename"]
        except (KeyError, TypeError):
            LOG.warning("Artifact %r ontbreekt, tarieven audit overgeslagen.", artifact_key)
            continue

        if not xlsx_path.is_file():
            LOG.warning("Tarieven-werkboek niet gevonden: %s", xlsx_path)
            continue

        # Elektriciteit heeft een derde bestand: de pipeline schrijft de
        # hoogspannings- en middenspanningsklanttypes apart weg. Dat bleef
        # tot nu toe volledig buiten de golden audit — 528 van de 776
        # elektriciteitsrijen werden dus nooit tegen het werkboek gelegd.
        richtingen = ("afname", "injectie")
        if energy_type == "electricity":
            richtingen = ("afname", "injectie", "hoogspanning")

        for direction in richtingen:
            csv_path = tariffs_dir / f"tariffs_{energy_type}_{direction}.csv"
            result = t_auditor.audit(
                staged_csv=csv_path,
                source_xlsx=xlsx_path,
                energy_type=energy_type,
                direction=direction,
                version_id=version_id,
            )
            all_results.append(result)

    if not all_results:
        return fail("Geen auditresultaten — is de versie volledig geparsed?")

    any_fail = False

    def _text() -> None:
        for res in all_results:
            status = "OK " if res.passed else "NOK"
            print(f"{status}  {res.domain:<30} {res.verified_rows}/{res.total_rows} rijen geverifieerd")
            if not res.passed:
                for mm in res.mismatches[:10]:
                    print(f"      [{mm.field}] {mm.row_key}")
                    print(f"        CSV : {mm.csv_value!r}")
                    print(f"        XLSX: {mm.xlsx_value!r}")
                if len(res.mismatches) > 10:
                    print(f"      ... en {len(res.mismatches) - 10} meer.")

    for res in all_results:
        if not res.passed:
            any_fail = True

    emit(
        args,
        text_fn=_text,
        json_obj=[
            {
                "domain": res.domain,
                "passed": res.passed,
                "verified_rows": res.verified_rows,
                "total_rows": res.total_rows,
                "mismatches": len(res.mismatches),
            }
            for res in all_results
        ],
    )
    return 2 if any_fail else 0


# ---------------------------------------------------------
# audit-status
# ---------------------------------------------------------

def run_audit_status(args: argparse.Namespace, settings: Settings) -> int:
    paths = DataPaths.from_settings(settings)
    manager = ApprovalManager(paths)
    status = manager.get_status(args.version)
    golden = manager.get_golden_master()
    is_golden = golden == args.version

    def _text() -> None:
        print(f"Versie     : {status.version_id}")
        print(f"Status     : {status.status.upper()}")
        print(f"Laatste up : {status.updated_at.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"Notities   : {status.notes}")
        if is_golden:
            print("\n*** DIT IS DE HUIDIGE GOLDEN MASTER ***")

    emit(
        args,
        text_fn=_text,
        json_obj={
            "version_id": status.version_id,
            "status": status.status,
            "updated_at": status.updated_at.isoformat(),
            "notes": status.notes,
            "is_golden": is_golden,
        },
    )
    return 0


# ---------------------------------------------------------
# audit-approve
# ---------------------------------------------------------

def run_audit_approve(args: argparse.Namespace, settings: Settings) -> int:
    paths = DataPaths.from_settings(settings)
    manager = ApprovalManager(paths)
    try:
        manager.approve(args.version, args.notes)
    except AuditError as exc:
        return fail("Kan niet goedkeuren: %s", exc)

    emit(
        args,
        text_fn=lambda: print(f"Versie {args.version} is nu succesvol goedgekeurd (APPROVED)."),
        json_obj={"version_id": args.version, "status": "approved"},
    )
    return 0


# ---------------------------------------------------------
# set-golden
# ---------------------------------------------------------

def run_set_golden(args: argparse.Namespace, settings: Settings) -> int:
    paths = DataPaths.from_settings(settings)
    manager = ApprovalManager(paths)
    try:
        manager.set_golden_master(args.version)
    except AuditError as exc:
        return fail("Fout bij instellen Golden Master: %s", exc)

    emit(
        args,
        text_fn=lambda: print(f"Versie {args.version} is nu de Golden Master."),
        json_obj={"version_id": args.version, "status": "golden"},
    )
    return 0


# ---------------------------------------------------------
# audit-sanity
# ---------------------------------------------------------

def run_audit_sanity(args: argparse.Namespace, settings: Settings) -> int:
    paths = DataPaths.from_settings(settings)
    checker = SanityChecker(paths)

    try:
        report = checker.check_version(args.version)
    except RuntimeError as exc:
        return fail("Sanity check mislukt om te starten: %s", exc)

    def _text() -> None:
        if report.valid:
            print(f"✅ Sanity check GESLAAGD voor versie {args.version}!")
            print(
                "Alle geteste datasets voldoen aan de harde business rules "
                "(geen onlogische extremen of onmogelijke waarden gevonden)."
            )
        else:
            print(f"❌ Sanity check GEFAALD voor versie {args.version}!")
            print(
                f"Er zijn {len(report.violations)} schendingen gevonden die "
                f"kritiek zijn voor een correcte berekening:\n"
            )
            for viol in report.violations:
                row_info = f" (rij {viol.row_index})" if viol.row_index is not None else ""
                print(f"  - [{viol.file}{row_info}] RULE '{viol.rule}': {viol.message}")
            print(
                "\nDit bestand moet gerepareerd worden (parser of data) voordat "
                "de goedkeuring ('audit-approve') kan doorgaan."
            )

    emit(
        args,
        text_fn=_text,
        json_obj={
            "version_id": args.version,
            "valid": report.valid,
            "violations": [
                {
                    "file": viol.file,
                    "row_index": viol.row_index,
                    "rule": viol.rule,
                    "message": viol.message,
                }
                for viol in report.violations
            ],
        },
    )
    return 0 if report.valid else 2


# ---------------------------------------------------------
# audit-sample
# ---------------------------------------------------------

def run_audit_sample(args: argparse.Namespace, settings: Settings) -> int:
    paths = DataPaths.from_settings(settings)
    sampler = DataSampler(paths)

    try:
        sampler.generate_samples(args.version, args.count)
    except RuntimeError as exc:
        return fail("Kan steekproef niet genereren: %s", exc)

    # DataSampler.generate_samples print zelf de steekproef; in --json modus
    # geven we enkel een bevestiging (de steekproef is bedoeld voor menselijke
    # visuele controle, niet voor machineverwerking).
    if getattr(args, "json", False):
        emit(
            args,
            text_fn=lambda: None,
            json_obj={"version_id": args.version, "count": args.count, "status": "generated"},
        )
    return 0




# ---------------------------------------------------------
# audit-heffingen
# ---------------------------------------------------------

def run_audit_heffingen(args: argparse.Namespace, settings: Settings) -> int:
    """Controleer config/heffingen/ zonder netwerk.

    Draait in CI bij elke commit: de masterdata is handgeschreven, dus een
    typfout in een schijfgrens komt er anders pas uit wanneer een berekening
    een verkeerd bedrag geeft — en dan valt het niemand op.
    """
    from datetime import date

    from energie_vlaanderen.heffingen.repository import (
        HeffingenError,
        HeffingenRepository,
    )
    from energie_vlaanderen.heffingen.validation import controleer_alles

    config_dir = settings.project_root / "config" / "heffingen"
    if args.datum:
        try:
            peildatum = date.fromisoformat(args.datum)
        except ValueError:
            return fail("--datum moet YYYY-MM-DD zijn, kreeg %r.", args.datum)
    else:
        peildatum = date.today()

    try:
        repo = HeffingenRepository.load(config_dir)
    except (HeffingenError, OSError, KeyError) as exc:
        return fail("Heffingen-masterdata kon niet geladen worden: %s", exc)

    bevindingen = controleer_alles(
        repo,
        peildatum,
        nettarieven_dir=settings.project_root / "config" / "nettarieven",
    )
    fouten = [b for b in bevindingen if b.ernst == "fout"]
    waarschuwingen = [b for b in bevindingen if b.ernst == "waarschuwing"]

    def _text() -> None:
        print(f"Configmap : {config_dir}")
        print(f"Peildatum : {peildatum.isoformat()}")
        print(f"Tabellen  : {', '.join(sorted(repo.accijns_tabellen()))}")
        print(f"Nettarieven: config/nettarieven/")
        for bevinding in bevindingen:
            merk = {"fout": "FOUT", "waarschuwing": "LET OP", "info": "info"}[
                bevinding.ernst
            ]
            print(f"[{merk:6s}] {bevinding.onderwerp}: {bevinding.bericht}")
        if not bevindingen:
            print("Geen bevindingen.")

    emit(
        args,
        text_fn=_text,
        json_obj={
            "config_dir": str(config_dir),
            "peildatum": peildatum.isoformat(),
            "energievormen": sorted(repo.accijns_tabellen()),
            "bevindingen": [
                {
                    "ernst": b.ernst,
                    "onderwerp": b.onderwerp,
                    "bericht": b.bericht,
                }
                for b in bevindingen
            ],
        },
    )

    if fouten:
        return 2
    if waarschuwingen and args.streng:
        return 2
    return 0


# ---------------------------------------------------------
# audit-hardware
# ---------------------------------------------------------

def run_audit_hardware(args: argparse.Namespace, settings: Settings) -> int:
    """Controleer config/hardware/ (batterijen/omvormers) zonder netwerk.

    Zelfde vorm als `run_audit_heffingen`: de masterdata is handgeschreven
    (er bestaat geen scrapebare bron voor batterij-/omvormerspecificaties,
    zie docs/research/technische_data_batterijen_en_omvormers.md), dus een
    typfout in een vermogen of percentage komt er anders pas uit wanneer een
    simulatie een vreemd resultaat geeft.
    """
    from energie_vlaanderen.hardware.repository import (
        BatterijRepository,
        HardwareError,
        OmvormerRepository,
    )
    from energie_vlaanderen.hardware.validation import controleer_alles

    batterijen_dir = settings.project_root / "config" / "hardware" / "batterijen"
    omvormers_dir = settings.project_root / "config" / "hardware" / "omvormers"

    try:
        batterij_repo = BatterijRepository.load(batterijen_dir)
        omvormer_repo = OmvormerRepository.load(omvormers_dir)
    except HardwareError as exc:
        return fail("Hardware-masterdata kon niet geladen worden: %s", exc)

    bevindingen = controleer_alles(batterij_repo, omvormer_repo)

    # De C10/26-lijst is de enige onafhankelijke bron op deze masterdata: alles
    # eromheen komt uit fabrikantsdatasheets. Ze is optioneel omdat het werkboek
    # buiten git valt (zie data/datasheets/LEESMIJ.md) — zonder het bestand
    # blijft de structurele controle gewoon werken.
    lijst_bron = None
    if getattr(args, "c10_26", False):
        from energie_vlaanderen.hardware.homologatie import (
            C1026Lijst,
            HomologatieError,
            controleer_hardware,
        )

        try:
            lijst = C1026Lijst.standaard(settings.project_root)
        except HomologatieError as exc:
            return fail("C10/26-lijst kon niet geladen worden: %s", exc)
        lijst_bron = lijst.bron
        bevindingen.extend(
            controleer_hardware(
                lijst,
                batterij_repo.batterijen().values(),
                omvormer_repo.omvormers().values(),
            )
        )

    fouten = [b for b in bevindingen if b.ernst == "fout"]
    waarschuwingen = [b for b in bevindingen if b.ernst == "waarschuwing"]

    def _text() -> None:
        print(f"Batterijen : {batterijen_dir}")
        if lijst_bron is not None:
            print(f"C10/26     : {lijst_bron}")
        print(f"Omvormers  : {omvormers_dir}")
        print(f"Modellen   : {', '.join(sorted(f'{m}/{mo}' for m, mo in batterij_repo.batterijen())) or '(geen)'}")
        for bevinding in bevindingen:
            merk = {"fout": "FOUT", "waarschuwing": "LET OP", "info": "info"}[
                bevinding.ernst
            ]
            print(f"[{merk:6s}] {bevinding.onderwerp}: {bevinding.bericht}")
        if not bevindingen:
            print("Geen bevindingen.")

    emit(
        args,
        text_fn=_text,
        json_obj={
            "batterijen_dir": str(batterijen_dir),
            "omvormers_dir": str(omvormers_dir),
            "batterijmodellen": sorted(f"{m}/{mo}" for m, mo in batterij_repo.batterijen()),
            "omvormermodellen": sorted(f"{m}/{mo}" for m, mo in omvormer_repo.omvormers()),
            "bevindingen": [
                {
                    "ernst": b.ernst,
                    "onderwerp": b.onderwerp,
                    "bericht": b.bericht,
                }
                for b in bevindingen
            ],
        },
    )

    if fouten:
        return 2
    if waarschuwingen and args.streng:
        return 2
    return 0
