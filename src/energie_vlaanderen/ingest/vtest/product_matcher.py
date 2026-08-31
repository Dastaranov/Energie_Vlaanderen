"""Best-effort koppeling tussen de live vtest.be-scrape (`vreg_id`, de
unieke contract-id — de "QR-code" van het contract) en de VREG-bulk-export
(`vtest.xlsx` / `master_vast.csv` / `master_var_dyn.csv`).

De bulk-export heeft géén ID-kolom, enkel Handelsnaam + Productnaam
(bevestigd door het ruwe workbook rechtstreeks te inspecteren) — koppelen
kan dus alleen via tekstmatching, nooit 100% dekkend (productnamen kunnen
jaar-op-jaar licht wijzigen, bv. "Flex Online Pro" -> "Flex Online Pro EL").
Mismatches worden expliciet gerapporteerd i.p.v. stil genegeerd
(manifest.md §12).
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

import pandas as pd

_SUFFIXES = (" el", " elektriciteit", " electricity", " gas")


def normalize_name(text: str) -> str:
    """Normaliseert leverancier-/productnamen voor matching: lowercase,
    samengevoegde witruimte, veelvoorkomende energietype-achtervoegsels
    gestript."""
    folded = re.sub(r"\s+", " ", (text or "").strip()).casefold()
    for suffix in _SUFFIXES:
        if folded.endswith(suffix):
            folded = folded[: -len(suffix)].strip()
    return folded


@dataclass(frozen=True)
class ProductMatch:
    vreg_id: str
    supplier_raw: str
    product_raw: str
    segment: str
    energy: str
    matched_handelsnaam: str
    matched_productnaam: str
    match_status: str  # "exact" | "genormaliseerd" | "geen_match"


@dataclass(frozen=True)
class MatchReport:
    totaal_vtest_producten: int
    exact: int
    genormaliseerd: int
    geen_match: int
    voorbeelden_vtest_zonder_match: tuple[str, ...] = field(default_factory=tuple)
    voorbeelden_bulk_ongebruikt: tuple[str, ...] = field(default_factory=tuple)


def _bulk_key(handelsnaam: str, productnaam: str, segment: str, energie: str) -> tuple[str, str, str, str]:
    return (
        (handelsnaam or "").strip().casefold(),
        (productnaam or "").strip().casefold(),
        (segment or "").strip().casefold(),
        (energie or "").strip().casefold(),
    )


def _bulk_key_normalized(handelsnaam: str, productnaam: str, segment: str, energie: str) -> tuple[str, str, str, str]:
    return (
        normalize_name(handelsnaam),
        normalize_name(productnaam),
        (segment or "").strip().casefold(),
        (energie or "").strip().casefold(),
    )


def match_products(
    vtest_df: pd.DataFrame,
    bulk_df: pd.DataFrame,
    max_voorbeelden: int = 20,
) -> tuple[list[ProductMatch], MatchReport]:
    """`vtest_df` kolommen: vreg_id, supplier_raw, product_raw, segment, energy.
    `bulk_df` kolommen (master_vast.csv/master_var_dyn.csv): Handelsnaam,
    Productnaam, Segment, Energietype."""

    bulk_rows = bulk_df[["Handelsnaam", "Productnaam", "Segment", "Energietype"]].drop_duplicates()

    exact_lookup: dict[tuple[str, str, str, str], tuple[str, str]] = {}
    normalized_lookup: dict[tuple[str, str, str, str], tuple[str, str]] = {}
    for row in bulk_rows.itertuples(index=False):
        target = (row.Handelsnaam, row.Productnaam)
        exact_lookup.setdefault(_bulk_key(row.Handelsnaam, row.Productnaam, row.Segment, row.Energietype), target)
        normalized_lookup.setdefault(
            _bulk_key_normalized(row.Handelsnaam, row.Productnaam, row.Segment, row.Energietype), target
        )

    gebruikte_bulk_targets: set[tuple[str, str]] = set()
    matches: list[ProductMatch] = []
    onbekend: list[str] = []

    vtest_unique = vtest_df[["vreg_id", "supplier_raw", "product_raw", "segment", "energy"]].drop_duplicates()
    for row in vtest_unique.itertuples(index=False):
        exact_key = _bulk_key(row.supplier_raw, row.product_raw, row.segment, row.energy)
        norm_key = _bulk_key_normalized(row.supplier_raw, row.product_raw, row.segment, row.energy)

        if exact_key in exact_lookup:
            target = exact_lookup[exact_key]
            status = "exact"
        elif norm_key in normalized_lookup:
            target = normalized_lookup[norm_key]
            status = "genormaliseerd"
        else:
            target = ("", "")
            status = "geen_match"
            onbekend.append(f"{row.supplier_raw} / {row.product_raw} ({row.segment}, {row.energy})")

        if status != "geen_match":
            gebruikte_bulk_targets.add(target)

        matches.append(ProductMatch(
            vreg_id=row.vreg_id,
            supplier_raw=row.supplier_raw,
            product_raw=row.product_raw,
            segment=row.segment,
            energy=row.energy,
            matched_handelsnaam=target[0],
            matched_productnaam=target[1],
            match_status=status,
        ))

    ongebruikt = [
        f"{h} / {p}"
        for h, p in bulk_rows[["Handelsnaam", "Productnaam"]].drop_duplicates().itertuples(index=False)
        if (h, p) not in gebruikte_bulk_targets
    ]

    report = MatchReport(
        totaal_vtest_producten=len(matches),
        exact=sum(1 for m in matches if m.match_status == "exact"),
        genormaliseerd=sum(1 for m in matches if m.match_status == "genormaliseerd"),
        geen_match=sum(1 for m in matches if m.match_status == "geen_match"),
        voorbeelden_vtest_zonder_match=tuple(onbekend[:max_voorbeelden]),
        voorbeelden_bulk_ongebruikt=tuple(ongebruikt[:max_voorbeelden]),
    )
    return matches, report


def write_links_csv(matches: list[ProductMatch], path: Path) -> None:
    df = pd.DataFrame([asdict(m) for m in matches])
    df.to_csv(path, sep=";", index=False, encoding="utf-8-sig")


def write_report_json(report: MatchReport, path: Path) -> None:
    path.write_text(json.dumps(asdict(report), ensure_ascii=False, indent=2), encoding="utf-8")
