"""Orkestreert workbook-parser + validator voor één profielbestand.

Zelfde vorm als `TariffPipeline`: één `process()`-aanroep per bronbestand
(niet per hele batch), zodat de CLI-laag kan lussen over de vier
Synergrid-artefacten zoals `run_parse_tariffs` al doet over
electricity/gas. `target.mkdir(exist_ok=True)` en per-bestand
overwrite-controle in plaats van de hele `profielen/`-map te wissen: een
andere `--only profielen`-aanroep voor een ander profieltype mag de rest
niet raken.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from energie_vlaanderen.ingest.profielen.validator import ProfielenValidator
from energie_vlaanderen.ingest.profielen.workbook import (
    ProfielenWorkbookError,
    ProfielenWorkbookParser,
)

# Per profiel_type/energie_type: welke engine, welke sheet, en welke
# leesfunctie (nationaal met één waardekolom, of breed met een kolom per
# netbeheerder). Zie workbook.py voor de brondata-analyse die hierachter zit.
_SPECS: dict[tuple[str, str | None], dict] = {
    # SLP-EX draagt na de waardekolom nog twee kalenderflags (BinL/BinH),
    # dus "laatste kolom = waarde" klopt hier niet — vandaar de expliciete
    # kolomnaam. RLP0N-gas en SPP eindigen dit jaar wél toevallig op hun
    # waardekolom (GOS_TOTU, SPPExanteBE), maar daar positioneel op
    # vertrouwen zou een stille fout worden zodra Synergrid een kolom
    # toevoegt — voor SPP zou dat zelfs onopgemerkt blijven, want daar
    # geldt geen som-tot-1-controle die het zou opvangen (zie
    # validator.py). Daarom overal een expliciete kolomnaam.
    #
    # "tijdkolom_is_cet_vast": RLP0N (elektriciteit én gas) labelt zijn
    # tijdas als "CET" maar zonder zomertijd (vaste +1u, net als SLP-EX'
    # eigen CET-sheet) — geverifieerd doordat elke dag exact 96 (elektr.)
    # resp. 24 (gas) rijen telt, ook op de twee Belgische DST-dagen in
    # 2026. SLP-EX zelf leest de aparte UTC-sheet (geen conversie nodig),
    # SPP levert al UTC. Zonder deze conversie interpreteert PostgreSQL de
    # naïeve string via de sessietijdzone (Europe/Brussels, mét DST) en
    # laat dat twee tijdstippen rond een DST-overgang op hetzelfde
    # UTC-instant vallen — een reëel opgetreden `CardinalityViolation` bij
    # de eerste echte import, niet een theoretisch risico.
    ("slp_ex", None): {
        "engine": "pyxlsb", "sheet_bevat": "utc", "vorm": "nationaal",
        "waarde_kolom": "ENU", "tijdkolom_is_cet_vast": False,
    },
    ("rlp0n", "elektriciteit"): {
        "engine": "pyxlsb", "sheet_bevat": "dgo", "vorm": "breed", "waarde_kolom": None,
    },
    ("rlp0n", "gas"): {
        "engine": "pyxlsb", "sheet_bevat": "gos", "vorm": "nationaal",
        "waarde_kolom": "GOS_TOTU", "tijdkolom_is_cet_vast": True,
    },
    ("spp", None): {
        "engine": "openpyxl", "sheet_bevat": "ex-ante", "vorm": "nationaal",
        "waarde_kolom": "SPPExanteBE", "tijdkolom_is_cet_vast": False,
    },
}


class ProfielenPipelineError(RuntimeError):
    pass


@dataclass(frozen=True)
class ProfielenPipelineResult:
    version_id: str
    profiel_type: str
    energie_type: str | None
    directory: Path
    csv_path: Path
    report_json: Path
    rows: int
    errors: int
    warnings: int


class ProfielenPipeline:
    def __init__(self) -> None:
        self.workbook_parser = ProfielenWorkbookParser()
        self.validator = ProfielenValidator()

    def process(
        self,
        *,
        source_path: Path,
        destination: Path,
        version_id: str,
        profiel_type: str,
        energie_type: str | None,
        jaar: int,
        overwrite: bool = False,
    ) -> ProfielenPipelineResult:
        spec = _SPECS.get((profiel_type, energie_type))
        if spec is None:
            raise ProfielenPipelineError(
                f"Onbekende combinatie profiel_type={profiel_type!r}, "
                f"energie_type={energie_type!r}."
            )

        try:
            if spec["vorm"] == "nationaal":
                parsed = self.workbook_parser.parse_nationaal(
                    source_path,
                    engine=spec["engine"],
                    sheet_bevat=spec["sheet_bevat"],
                    waarde_kolom=spec["waarde_kolom"],
                    tijdkolom_is_cet_vast=spec.get("tijdkolom_is_cet_vast", False),
                )
            else:
                parsed = self.workbook_parser.parse_breed_per_netbeheerder(
                    source_path, engine=spec["engine"], sheet_bevat=spec["sheet_bevat"]
                )
        except ProfielenWorkbookError as exc:
            raise ProfielenPipelineError(f"Werkboek kon niet gelezen worden: {exc}") from exc

        validation = self.validator.validate(
            parsed.rows, profiel_type=profiel_type, energie_type=energie_type, jaar=jaar
        )

        naam = f"{profiel_type}_{energie_type}" if energie_type else profiel_type
        target = destination / "profielen"
        csv_path = target / f"{naam}_{jaar}.csv"
        report_json = target / f"{naam}_{jaar}_report.json"

        if not overwrite and csv_path.exists():
            raise ProfielenPipelineError(
                f"{csv_path} bestaat al. Gebruik --overwrite om te herschrijven."
            )

        if not validation.valid:
            # Bewust niets wegschrijven: een half-geschreven of ongeldige CSV
            # is gevaarlijker dan geen CSV — dezelfde discipline als de
            # vtest-/tarievenpipelines.
            details = "; ".join(issue.message for issue in validation.errors)
            raise ProfielenPipelineError(f"Validatie mislukt voor {naam} ({jaar}): {details}")

        target.mkdir(parents=True, exist_ok=True)

        # De validator garandeert op dit punt dat elke (tijdstip,
        # netbeheerder)-combinatie hooguit één waarde draagt — een dubbele
        # GLN-kolom met een afwijkende waarde had hierboven al een
        # ProfielenPipelineError opgeleverd. Dedupliceren vóór het schrijven
        # voorkomt dat een paar dubbel voorkomende netbeheerders (zie
        # workbook.py) de CSV met exact herhaalde rijen opblazen.
        seen: set[tuple[str, str | None]] = set()
        unieke_rows = []
        for row in parsed.rows:
            key = (row.tijdstip, row.netbeheerder_gln)
            if key in seen:
                continue
            seen.add(key)
            unieke_rows.append(row)

        frame = pd.DataFrame(
            [
                {
                    "tijdstip": row.tijdstip,
                    "netbeheerder_gln": row.netbeheerder_gln or "",
                    "netbeheerder_naam": row.netbeheerder_naam or "",
                    "waarde": row.waarde,
                    "source_sheet": row.source_sheet,
                }
                for row in unieke_rows
            ]
        )
        frame.to_csv(csv_path, sep=";", index=False, encoding="utf-8-sig")

        report = {
            "schema_version": 1,
            "version_id": version_id,
            "profiel_type": profiel_type,
            "energie_type": energie_type,
            "jaar": jaar,
            "processed_at": datetime.now(timezone.utc).isoformat(),
            "source_path": str(parsed.source_path),
            "rows": len(unieke_rows),
            "rows_voor_deduplicatie": len(parsed.rows),
            "parse_warnings": list(parsed.warnings),
            "validation_errors": [
                {"code": i.code, "message": i.message} for i in validation.errors
            ],
            "validation_warnings": [
                {"code": i.code, "message": i.message} for i in validation.warnings
            ],
        }
        report_json.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

        return ProfielenPipelineResult(
            version_id=version_id,
            profiel_type=profiel_type,
            energie_type=energie_type,
            directory=target,
            csv_path=csv_path,
            report_json=report_json,
            rows=len(unieke_rows),
            errors=len(validation.errors),
            warnings=len(validation.warnings) + len(parsed.warnings),
        )
