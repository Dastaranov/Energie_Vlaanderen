from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import pandas as pd

from energie_vlaanderen.ingest.vtest.workbook import VTestWorkbookParser
from energie_vlaanderen.ingest.vtest.normalizer import VTestDataNormalizer
from energie_vlaanderen.ingest.tariffs.workbook import TariffWorkbookParser
from energie_vlaanderen.ingest.tariffs.normalizer import TariffDataNormalizer
from energie_vlaanderen.ingest.tariffs.pipeline import TariffPipeline


@dataclass(frozen=True)
class FieldMismatch:
    domain: str
    source_sheet: str
    source_row: int | None
    field: str
    csv_value: str
    xlsx_value: str
    row_key: str


@dataclass(frozen=True)
class GoldenAuditResult:
    version_id: str
    domain: str
    source_xlsx: Path
    total_rows: int
    verified_rows: int
    mismatches: tuple[FieldMismatch, ...]
    # Gezet wanneer het gestagede CSV niet gevonden werd. Eerder leverde dat
    # een resultaat met 0 rijen en 0 verschillen op, en dus `passed = True`:
    # "OK 0/0 rijen geverifieerd" voor elk domein. Een audit die niets kon
    # vergelijken mag niet slagen — zeker niet deze, die de poort naar
    # publicatie bewaakt.
    ontbrekend_bestand: Path | None = None

    @property
    def passed(self) -> bool:
        if self.ontbrekend_bestand is not None:
            return False
        # Nul geverifieerde rijen is geen geslaagde audit maar een audit die
        # niet gelopen heeft.
        if self.verified_rows == 0:
            return False
        return not self.mismatches


class VTestGoldenAuditor:
    COMPARE_FIELDS = (
        "year", "month", "segment", "energy", "direction",
        "supplier", "product", "product_type", "component",
        "component_label", "price", "a", "b", "c", "d", "z",
        "index_name_A", "index_name_B", "index_name_C", "index_name_D",
        "index_value_A", "index_value_B", "index_value_C", "index_value_D",
    )

    DECIMAL_FIELDS = frozenset({
        "price", "a", "b", "c", "d", "z",
        "index_value_A", "index_value_B", "index_value_C", "index_value_D",
    })

    def audit(
        self,
        staged_csv: Path,
        source_xlsx: Path,
        domain: str,
        version_id: str,
    ) -> GoldenAuditResult:
        parsed = VTestWorkbookParser().parse(source_xlsx)
        if domain.endswith("_vast"):
            fresh_df = VTestDataNormalizer().normalize(parsed.fixed, pd.DataFrame()).fixed
        else:
            fresh_df = VTestDataNormalizer().normalize(pd.DataFrame(), parsed.variable_dynamic).variable_dynamic

        if not staged_csv.is_file():
            return GoldenAuditResult(
                version_id=version_id,
                domain=domain,
                source_xlsx=source_xlsx,
                total_rows=0,
                verified_rows=0,
                mismatches=(),
                ontbrekend_bestand=staged_csv,
            )

        staged_df = pd.read_csv(staged_csv, sep=";", dtype=str, encoding="utf-8-sig").fillna("")

        # Build lookup: (source_sheet, source_row) → dict of fresh values
        fresh_index: dict[tuple[str, int], dict[str, Any]] = {}
        for _, row in fresh_df.iterrows():
            ss = str(row.get("source_sheet", ""))
            sr_raw = row.get("source_row")
            try:
                sr = int(sr_raw)
            except (ValueError, TypeError):
                continue
            fresh_index[(ss, sr)] = dict(row)

        mismatches: list[FieldMismatch] = []
        verified = 0

        for _, csv_row in staged_df.iterrows():
            ss = str(csv_row.get("source_sheet", "")).strip()
            sr_raw = csv_row.get("source_row", "")
            try:
                sr = int(float(sr_raw))
            except (ValueError, TypeError):
                continue

            fresh_row = fresh_index.get((ss, sr))
            if fresh_row is None:
                continue

            row_key = (
                f"{csv_row.get('supplier', '')} / {csv_row.get('product', '')} / "
                f"{csv_row.get('year', '')}-{csv_row.get('month', '')} / "
                f"{csv_row.get('component', '')}"
            )
            verified += 1

            for field in self.COMPARE_FIELDS:
                csv_val = str(csv_row.get(field, "")).strip()
                fresh_val = fresh_row.get(field)

                if field in self.DECIMAL_FIELDS:
                    if not _decimals_equal(csv_val, fresh_val):
                        mismatches.append(FieldMismatch(
                            domain=domain,
                            source_sheet=ss,
                            source_row=sr,
                            field=field,
                            csv_value=csv_val,
                            xlsx_value=str(fresh_val),
                            row_key=row_key,
                        ))
                else:
                    fresh_str = str(fresh_val).strip() if fresh_val is not None else ""
                    if csv_val != fresh_str:
                        mismatches.append(FieldMismatch(
                            domain=domain,
                            source_sheet=ss,
                            source_row=sr,
                            field=field,
                            csv_value=csv_val,
                            xlsx_value=fresh_str,
                            row_key=row_key,
                        ))

        return GoldenAuditResult(
            version_id=version_id,
            domain=domain,
            source_xlsx=source_xlsx,
            total_rows=len(staged_df),
            verified_rows=verified,
            mismatches=tuple(mismatches),
        )


class TariffGoldenAuditor:
    COMPARE_FIELDS = (
        "Netbeheerder", "Contracttype", "Klanttype",
        "Tarieftype", "Tariefdetail", "Tariefnotering", "Prijs_num",
    )
    FLOAT_TOLERANCE = 1e-4
    # De vergelijking gebeurt op positie na sortering, dus de sortering moet
    # op beide kanten dezelfde volgorde geven én totaal zijn.
    #
    # "Tariefnotering" hoort erbij sinds de normalizer "of"-vervolgregels de
    # naam van de regel erboven geeft: verschillende eenheden van hetzelfde
    # tarief delen dan hun Tariefdetail, en zonder de notering is de volgorde
    # niet meer bepaald.
    SORT_KEYS = [
        "Netbeheerder", "Contracttype", "Klanttype", "Tarieftype",
        "Tariefdetail", "Tariefnotering", "source_sheet", "source_row",
    ]
    # Kolommen die als getal moeten sorteren. De gestagede CSV wordt met
    # dtype=str gelezen, dus "9" zou na "13" komen terwijl de verse kant, waar
    # het een int is, andersom sorteert. De twee kanten raakten daardoor uit
    # de pas en de positievergelijking legde ongelijke rijen naast elkaar —
    # 105 gemelde verschillen die geen van alle een echt dataverschil waren.
    NUMERIEKE_SORT_KEYS = {"source_row"}

    @classmethod
    def _sorteer(cls, frame: pd.DataFrame) -> pd.DataFrame:
        """Sorteer op de sleutelkolommen, met getallen als getal.

        Beide kanten moeten na sortering dezelfde volgorde hebben; anders
        vergelijkt de audit rijen die niets met elkaar te maken hebben.
        """
        sleutels = [k for k in cls.SORT_KEYS if k in frame.columns]
        if not sleutels:
            return frame.reset_index(drop=True)

        hulp = frame.copy()
        hulpkolommen = []
        for sleutel in sleutels:
            if sleutel in cls.NUMERIEKE_SORT_KEYS:
                naam = f"__sort_{sleutel}"
                hulp[naam] = pd.to_numeric(hulp[sleutel], errors="coerce")
                hulpkolommen.append(naam)
            else:
                hulpkolommen.append(sleutel)

        gesorteerd = hulp.sort_values(hulpkolommen, kind="mergesort")
        return gesorteerd.drop(
            columns=[k for k in hulpkolommen if k.startswith("__sort_")]
        ).reset_index(drop=True)

    def audit(
        self,
        staged_csv: Path,
        source_xlsx: Path,
        energy_type: str,
        direction: str,
        version_id: str,
        staged_frame: pd.DataFrame | None = None,
    ) -> GoldenAuditResult:
        """Leg de verwerkte tarieven cel voor cel naast het bronwerkboek.

        `staged_frame` laat de aanroeper kiezen wáár de verwerkte kant vandaan
        komt. Zonder dat argument wordt `staged_csv` gelezen — de oude weg.
        Mét een frame komt ze uit de databank, en dat is wat deze controle
        overeind houdt wanneer de CSV-weg verdwijnt: het werkboek blijft de
        onafhankelijke bron, alleen de kant die ermee vergeleken wordt
        verhuist.
        """
        domain = f"{energy_type}_{direction}"
        parsed = TariffWorkbookParser().parse(source_xlsx, energy_type=energy_type)
        # `kolomkaarten()` moet mee, net als in TariffPipeline. Zonder die
        # kaarten valt de normalisatie terug op de vaste kolomindices en leest
        # ze kolom 11 (ELEK_LS_DC) er alsnog bij: 528 hoogspanningsrijen
        # tegenover de 432 die de pipeline schrijft. De vergelijking loopt dan
        # op positie uit de pas en meldde 2.220 verschillen die geen van alle
        # een echt dataverschil waren — dezelfde soort fout als toen deze
        # audit de verse normalisatie tegen alleen het afname-bestand legde.
        genormaliseerd = TariffDataNormalizer().normalize(
            parsed.afname, parsed.injectie, parsed.kolomkaarten()
        )

        # De pipeline schrijft de hoogspannings- en middenspanningsklanttypes
        # naar een eigen CSV, met afname én injectie samen. De verse kant hier
        # bevat ze nog gewoon in beide frames, dus zonder dezelfde splitsing
        # wordt een 728-rijenframe vergeleken met een 200-rijen-CSV — op
        # positie, waardoor élke rij als verschil telt. Dat leverde 108
        # gemelde verschillen op die geen van alle een echt dataverschil
        # waren. Gas kent deze splitsing niet en slaagde daarom altijd.
        def _splits_hs(frame: pd.DataFrame, *, hoogspanning: bool) -> pd.DataFrame:
            if frame.empty:
                return frame
            is_hs = frame["Klanttype"].isin(TariffPipeline.HS_MS_KLANTTYPES)
            return frame[is_hs if hoogspanning else ~is_hs]

        if energy_type != "electricity":
            fresh_df = (
                genormaliseerd.afname if direction == "afname" else genormaliseerd.injectie
            )
        elif direction == "hoogspanning":
            fresh_df = pd.concat(
                [
                    _splits_hs(genormaliseerd.afname, hoogspanning=True),
                    _splits_hs(genormaliseerd.injectie, hoogspanning=True),
                ],
                ignore_index=True,
            )
        elif direction == "afname":
            fresh_df = _splits_hs(genormaliseerd.afname, hoogspanning=False)
        else:
            fresh_df = _splits_hs(genormaliseerd.injectie, hoogspanning=False)

        fresh_df = fresh_df.reset_index(drop=True)

        if staged_frame is not None:
            staged_df = staged_frame.fillna("").astype(str)
        elif not staged_csv.is_file():
            return GoldenAuditResult(
                version_id=version_id,
                domain=domain,
                source_xlsx=source_xlsx,
                total_rows=0,
                verified_rows=0,
                mismatches=(),
                ontbrekend_bestand=staged_csv,
            )
        else:
            staged_df = pd.read_csv(
                staged_csv, sep=";", dtype=str, encoding="utf-8-sig"
            ).fillna("")

        fresh_sorted = self._sorteer(fresh_df)
        staged_sorted = self._sorteer(staged_df)

        mismatches: list[FieldMismatch] = []
        total = len(staged_sorted)
        verified = min(len(fresh_sorted), len(staged_sorted))

        if len(fresh_sorted) != len(staged_sorted):
            mismatches.append(FieldMismatch(
                domain=domain,
                source_sheet="",
                source_row=None,
                field="_row_count",
                csv_value=str(len(staged_sorted)),
                xlsx_value=str(len(fresh_sorted)),
                row_key="totaal",
            ))
            # De vergelijking hieronder loopt op positie. Bij een verschillend
            # aantal rijen staan de twee kanten vanaf het eerste ontbrekende
            # element uit de pas, en dan telt bijna élk veld als verschil —
            # 2.220 stuks in het geval dat dit blootlegde, geen ervan echt.
            # Die lijst afdrukken stuurt de lezer een dwaalspoor op (waarom
            # staat ELEK_LS_DC naast ELEK_MS1?), terwijl de enige bruikbare
            # bevinding het rij-aantal zelf is. Eerst dat oplossen, dan pas
            # veld voor veld vergelijken.
            return GoldenAuditResult(
                version_id=version_id,
                domain=domain,
                source_xlsx=source_xlsx,
                total_rows=total,
                verified_rows=verified,
                mismatches=tuple(mismatches),
            )

        for idx in range(verified):
            fresh_row = fresh_sorted.iloc[idx]
            staged_row = staged_sorted.iloc[idx]

            ss = str(staged_row.get("source_sheet", "")).strip()
            sr_raw = staged_row.get("source_row", "")
            try:
                sr: int | None = int(float(sr_raw))
            except (ValueError, TypeError):
                sr = None

            row_key = (
                f"{staged_row.get('Netbeheerder', '')} / "
                f"{staged_row.get('Tariefdetail', '')} / "
                f"{staged_row.get('Klanttype', '')}"
            )

            for field in self.COMPARE_FIELDS:
                csv_val = str(staged_row.get(field, "")).strip()
                fresh_val = fresh_row.get(field)
                fresh_str = str(fresh_val) if fresh_val is not None else ""

                if field == "Prijs_num":
                    if not _floats_equal(csv_val, fresh_str, self.FLOAT_TOLERANCE):
                        mismatches.append(FieldMismatch(
                            domain=domain,
                            source_sheet=ss,
                            source_row=sr,
                            field=field,
                            csv_value=csv_val,
                            xlsx_value=fresh_str,
                            row_key=row_key,
                        ))
                else:
                    if csv_val != fresh_str.strip():
                        mismatches.append(FieldMismatch(
                            domain=domain,
                            source_sheet=ss,
                            source_row=sr,
                            field=field,
                            csv_value=csv_val,
                            xlsx_value=fresh_str,
                            row_key=row_key,
                        ))

        return GoldenAuditResult(
            version_id=version_id,
            domain=domain,
            source_xlsx=source_xlsx,
            total_rows=total,
            verified_rows=verified,
            mismatches=tuple(mismatches),
        )


def _decimals_equal(csv_val: str, fresh_val: Any) -> bool:
    """Compare a CSV decimal string (Belgian comma) with a fresh Decimal/None value."""
    # Parse fresh value
    if fresh_val is None or str(fresh_val) in ("None", "nan", ""):
        fresh_dec: Decimal | None = None
    else:
        try:
            fresh_dec = Decimal(str(fresh_val))
        except InvalidOperation:
            fresh_dec = None

    # Parse CSV value — Belgian comma format
    if csv_val in ("", "None", "nan"):
        csv_dec: Decimal | None = None
    else:
        try:
            csv_dec = Decimal(csv_val.replace(",", "."))
        except InvalidOperation:
            csv_dec = None

    if csv_dec is None and fresh_dec is None:
        return True
    if csv_dec is None:
        return fresh_dec == Decimal("0")
    if fresh_dec is None:
        return csv_dec == Decimal("0")
    return csv_dec == fresh_dec


def _floats_equal(csv_val: str, fresh_val: str, tolerance: float) -> bool:
    """Compare two float strings within a tolerance."""
    try:
        a = float(csv_val)
        b = float(fresh_val)
        return abs(a - b) <= tolerance
    except (ValueError, TypeError):
        return csv_val == fresh_val
