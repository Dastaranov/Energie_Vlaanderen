from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from energie_vlaanderen.data.paths import DataPaths

LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class SanityViolation:
    file: str
    rule: str
    message: str
    row_index: int | None = None


@dataclass(frozen=True)
class SanityReport:
    version_id: str
    valid: bool
    violations: tuple[SanityViolation, ...]


class SanityChecker:
    def __init__(self, paths: DataPaths):
        self.paths = paths

    def check_version(self, version_id: str) -> SanityReport:
        self.paths.validate_version_id(version_id)
        staging_dir = self.paths.staging / version_id
        
        if not staging_dir.exists():
            raise RuntimeError(f"Staging map voor {version_id} bestaat niet.")
            
        violations: list[SanityViolation] = []
        
        # 1. Controleer V-test data
        vtest_dir = staging_dir / "vtest"
        if vtest_dir.exists():
            self._check_vtest(vtest_dir, violations)
            
        # 2. Controleer Net-tarieven
        tariffs_dir = staging_dir / "tariffs"
        if tariffs_dir.exists():
            self._check_tariffs(tariffs_dir, violations)
            
        # 3. Controleer Energiecurves
        curves_dir = staging_dir / "curves"
        if curves_dir.exists():
            self._check_curves(curves_dir, violations)
            
        return SanityReport(
            version_id=version_id,
            valid=len(violations) == 0,
            violations=tuple(violations)
        )

    def _check_vtest(self, vtest_dir: Path, violations: list[SanityViolation]) -> None:
        vast_csv = vtest_dir / "master_vast.csv"
        var_csv = vtest_dir / "master_var_dyn.csv"
        
        for file_path in [vast_csv, var_csv]:
            if not file_path.exists():
                continue
                
            df = pd.read_csv(file_path, sep=";")
            
            if "price" in df.columns:
                # Converteer string bedragen (met komma's) veilig naar getallen
                df["price_num"] = pd.to_numeric(
                    df["price"].astype(str).str.replace(",", "."), 
                    errors="coerce"
                )
                
                # RECHTSREGEL 1: Vaste vergoedingen mogen niet absurd hoog zijn (bijv. > €500)
                vaste_kosten = df[df["component"] == "fixed_fee"]
                bizar_hoog = vaste_kosten[vaste_kosten["price_num"] > 500]
                for idx, row in bizar_hoog.iterrows():
                    violations.append(SanityViolation(
                        file=file_path.name,
                        rule="Max vaste vergoeding overschreden",
                        message=f"Vaste vergoeding {row['price_num']} is onrealistisch hoog voor {row.get('supplier')} - {row.get('product')}.",
                        row_index=idx
                    ))
                
                # RECHTSREGEL 2: Geen extreme negatieve prijzen
                negatief = df[df["price_num"] < -100]
                for idx, row in negatief.iterrows():
                    violations.append(SanityViolation(
                        file=file_path.name,
                        rule="Extreem negatieve prijs",
                        message=f"Prijs is absurd negatief ({row['price_num']}) voor component {row.get('component')}.",
                        row_index=idx
                    ))

    def _check_tariffs(self, tariffs_dir: Path, violations: list[SanityViolation]) -> None:
        for filename in ["tariffs_afname.csv", "tariffs_injectie.csv"]:
            file_path = tariffs_dir / filename
            if not file_path.exists():
                continue
                
            df = pd.read_csv(file_path, sep=";")
            if "Prijs_num" in df.columns:
                # RECHTSREGEL 3: Netwerktarieven zijn in principe nooit negatief
                negatief = df[df["Prijs_num"] < 0]
                for idx, row in negatief.iterrows():
                    violations.append(SanityViolation(
                        file=filename,
                        rule="Geen negatieve tarieven",
                        message=f"Negatief tarief gevonden ({row['Prijs_num']}) bij '{row.get('Tarieftype')}'.",
                        row_index=idx
                    ))

    def _check_curves(self, curves_dir: Path, violations: list[SanityViolation]) -> None:
        ts_csv = curves_dir / "curves_timeseries.csv"
        if ts_csv.exists():
            df = pd.read_csv(ts_csv, sep=";")
            
            # RECHTSREGEL 4: Fysieke profielen (verbruik RLP / opwek SPP) kunnen NOOIT onder 0 vallen.
            if "CurveType" in df.columns and "Waarde" in df.columns:
                rlp_spp = df[df["CurveType"].isin(["RLP", "SPP"])]
                negatief = rlp_spp[rlp_spp["Waarde"] < 0]
                
                if not negatief.empty:
                    # Report max 5 rijen om de console niet vol te spammen (timeseries zijn enorm)
                    for idx, row in negatief.head(5).iterrows():
                        violations.append(SanityViolation(
                            file=ts_csv.name,
                            rule="RLP/SPP altijd positief",
                            message=f"Curve {row['Variant']} daalt onder de nul: {row['Waarde']} op {row['Timestamp']}.",
                            row_index=idx
                        ))
                    if len(negatief) > 5:
                        violations.append(SanityViolation(
                            file=ts_csv.name,
                            rule="RLP/SPP altijd positief",
                            message=f"... en nog {len(negatief) - 5} andere fysiek onmogelijke negatieve profielwaarden verborgen."
                        ))