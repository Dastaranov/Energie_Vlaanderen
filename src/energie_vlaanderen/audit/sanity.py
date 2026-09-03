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

    # Kolommen die uit het detailpaneel van vtest.be komen. Ze bleven
    # maandenlang leeg zonder dat er iets faalde: de scraper haalde het paneel
    # niet op, de parser kreeg dus niets, en `vtest_contract` kwam leeg in de
    # databank. Een lege kolom is hier geen geldige uitkomst maar een
    # ontbrekende scrape.
    #
    # Niet elk veld hoort bij elk contract, en dat onderscheid moet erin:
    # nagerekend op 2.485 gescrapete contracten (2026-09-03) draagt gas géén
    # vraag over zonnepanelen, elektrisch voertuig of energiedelen — die
    # secties staan enkel in een elektriciteitspaneel (0% op 776 gasrijen,
    # 99% op 1.709 elektriciteitsrijen). Ze meetellen voor gas zou een
    # gas-only run vals laten falen.
    _DETAILVELDEN = (
        "looptijd_tekst",
        "datum_intekenen_van", "datum_intekenen_tot",
        "datum_start_levering_van", "datum_start_levering_tot",
        "doelgroep_groepsaankoop", "prijszekerheid_termijn",
        "link_tariefkaart", "link_voorwaarden", "link_supplier",
    )

    # Enkel in een elektriciteitspaneel.
    _DETAILVELDEN_ELEKTRICITEIT = (
        "doelgroep_zonnepanelen", "doelgroep_ev", "doelgroep_energiedelen",
    )

    # `doelgroep_leegstand` staat bewust in geen van beide lijsten: die vraag
    # wordt ook binnen elektriciteit maar door een deel van de leveranciers
    # beantwoord (29% elektriciteit, 43% gas). Leeg is daar een geldig
    # antwoord en geen signaal.

    @staticmethod
    def _volledig_leeg(df, kolom: str) -> bool:
        if kolom not in df.columns:
            return True
        return df[kolom].fillna("").astype(str).str.strip().eq("").all()

    def _check_contractdetails(
        self, vtest_dir: Path, violations: list[SanityViolation]
    ) -> None:
        """Meldt kolommen uit het detailpaneel die volledig leeg zijn.

        Volledig leeg, niet gedeeltelijk: enkele contracten dragen terecht
        geen tariefkaart (het sociaal tarief verwijst naar de CREG) en
        "Onbepaald" levert terecht geen looptijd in maanden. Een kolom die
        voor *elk* contract leeg is, betekent dat het paneel niet opgehaald
        werd — dat is het signaal dat telt.
        """
        products_csv = vtest_dir / "vtest_products.csv"
        if not products_csv.is_file():
            return
        try:
            df = pd.read_csv(products_csv, sep=";", encoding="utf-8-sig", dtype=str)
        except (OSError, ValueError, pd.errors.ParserError):
            return
        if df.empty:
            return

        leeg = [k for k in self._DETAILVELDEN if self._volledig_leeg(df, k)]

        # De elektriciteitsvelden alleen toetsen op de elektriciteitsrijen, en
        # alleen wanneer die er zijn.
        if "energy" in df.columns:
            elek = df[df["energy"].fillna("").str.strip().str.lower() == "elektriciteit"]
            if not elek.empty:
                leeg += [
                    k for k in self._DETAILVELDEN_ELEKTRICITEIT
                    if self._volledig_leeg(elek, k)
                ]

        if leeg:
            violations.append(SanityViolation(
                file=products_csv.name,
                rule="Contractmetadata ontbreekt",
                message=(
                    f"{len(leeg)} kolom(men) uit het detailpaneel zijn voor alle "
                    f"{len(df)} contracten leeg: {', '.join(leeg)}. "
                    "Draai `staging refine` zonder --zonder-contractdetails, of "
                    "herparse met --no-download als de panelen al onder "
                    "vtest/contractdetails/ staan."
                ),
            ))

    def _check_vtest(self, vtest_dir: Path, violations: list[SanityViolation]) -> None:
        self._check_contractdetails(vtest_dir, violations)

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
        # De pipeline schrijft per energievorm: tariffs_electricity_afname.csv,
        # tariffs_gas_afname.csv, tariffs_electricity_hoogspanning.csv, ...
        # Er werd hier gezocht naar "tariffs_afname.csv" en
        # "tariffs_injectie.csv" — namen die de pipeline nooit gebruikt heeft.
        # Gevolg: deze controle sloeg stil over en de sanity check meldde
        # "geslaagd" zonder één tariefrij bekeken te hebben. Globben in plaats
        # van een vaste lijst houdt dat ook vol als er een energievorm bijkomt.
        bestanden = sorted(tariffs_dir.glob("tariffs_*.csv"))
        if not bestanden:
            violations.append(SanityViolation(
                file=tariffs_dir.name,
                rule="Tariefdata ontbreekt",
                message=(
                    "De tarieven-stagingmap bestaat maar bevat geen enkele "
                    "tariffs_*.csv — er valt hier niets te controleren."
                ),
                row_index=None,
            ))
            return

        for file_path in bestanden:
            filename = file_path.name
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