from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from energie_vlaanderen.data.paths import DataPaths

LOG = logging.getLogger(__name__)


class DataSampler:
    def __init__(self, paths: DataPaths):
        self.paths = paths

    def generate_samples(self, version_id: str, n_samples: int = 3) -> None:
        """Haal willekeurige rijen op uit de verschillende domeinen en print ze."""
        self.paths.validate_version_id(version_id)
        staging_dir = self.paths.staging / version_id
        
        if not staging_dir.exists():
            raise RuntimeError(f"Staging map voor {version_id} bestaat niet.")

        print(f"\n{'='*60}")
        print(f"🔍 STEEKPROEF AUDIT VOOR VERSIE: {version_id}")
        print(f"{'='*60}")
        print("Controleer deze waarden visueel in de originele Excel-bestanden.\n")

        # 1. V-test (Vast)
        self._sample_file(
            staging_dir / "vtest" / "master_vast.csv", 
            "V-TEST (VAST)", 
            n_samples,
            cols_to_print=["supplier", "product", "component", "price", "source_sheet", "source_row"]
        )

        # 2. Tarieven (Afname)
        self._sample_file(
            staging_dir / "tariffs" / "tariffs_afname.csv", 
            "TARIEVEN (AFNAME)", 
            n_samples,
            cols_to_print=["Netbeheerder", "Klanttype", "Tariefdetail", "Prijs_num"]
        )

        # 3. Curves (Timeseries)
        self._sample_file(
            staging_dir / "curves" / "curves_timeseries.csv", 
            "CURVES (TIMESERIES)", 
            n_samples,
            cols_to_print=["Timestamp", "CurveType", "EnergyType", "Variant", "Waarde", "SourceSheet"]
        )
        
        print(f"{'='*60}")
        print("Als alle steekproeven kloppen, kun je deze versie goedkeuren met:")
        print(f"python -m energie_vlaanderen.cli audit-approve --version {version_id}")
        print(f"{'='*60}\n")

    def _sample_file(self, file_path: Path, title: str, n: int, cols_to_print: list[str]) -> None:
        if not file_path.exists():
            return

        df = pd.read_csv(file_path, sep=";")
        if df.empty:
            return

        # Pak n willekeurige rijen (of minder als het bestand kleiner is)
        sample_size = min(n, len(df))
        sample_df = df.sample(n=sample_size)

        print(f"--- {title} ---")
        print(f"Bestand: {file_path.name} (Totaal: {len(df)} rijen)")
        
        for idx, row in sample_df.iterrows():
            print(f"  Rij {idx}:")
            for col in cols_to_print:
                if col in row:
                    print(f"    - {col.ljust(15)}: {row[col]}")
            
            # Help de auditor zoeken in de originele file
            if "source_sheet" in row and "source_row" in row:
                print(f"    👉 KIJK IN EXCEL: Tabblad '{row['source_sheet']}', Excel-rij {row['source_row']}")
            elif "SourceSheet" in row:
                print(f"    👉 KIJK IN EXCEL: Tabblad '{row['SourceSheet']}'")
            print("")