from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import pandas as pd
import sqlalchemy as sa

from energie_vlaanderen.infrastructure.db.schema import (
    data_version,
    gemeente,
    netbeheerder,
    netwerk_tarief,
    product_component,
    vtest_product,
)

LOG = logging.getLogger(__name__)

_SEP = ";"
_ENC = "utf-8-sig"


def _dec(val: Any) -> Decimal | None:
    if val is None or str(val).strip() in ("", "nan", "None"):
        return None
    try:
        return Decimal(str(val).replace(",", "."))
    except InvalidOperation:
        return None


def _int(val: Any) -> int | None:
    if val is None or str(val).strip() in ("", "nan", "None"):
        return None
    try:
        return int(float(str(val)))
    except (ValueError, TypeError):
        return None


def _str(val: Any) -> str | None:
    s = str(val).strip() if val is not None else ""
    return s if s and s != "nan" else None


def _date(val: Any) -> Any:
    s = _str(val)
    if not s:
        return None
    try:
        from datetime import date
        return date.fromisoformat(s)
    except (ValueError, TypeError):
        return None


def _ts(val: Any) -> Any:
    s = _str(val)
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except (ValueError, TypeError):
        return None


@dataclass(frozen=True)
class ImportResult:
    domain: str
    rows_inserted: int


# ---------------------------------------------------------------------------
# data_version upsert
# ---------------------------------------------------------------------------

def upsert_data_version(conn: sa.Connection, version_id: str, status: str = "staged") -> None:
    ts = datetime.now(tz=timezone.utc)
    stmt = sa.dialects.postgresql.insert(data_version).values(
        version_id=version_id,
        aangemaakt_op=ts,
        status=status,
    ).on_conflict_do_update(
        index_elements=["version_id"],
        set_={"status": status},
    )
    conn.execute(stmt)


def mark_imported(conn: sa.Connection, version_id: str) -> None:
    conn.execute(
        sa.update(data_version)
        .where(data_version.c.version_id == version_id)
        .values(geimporteerd_op=datetime.now(tz=timezone.utc))
    )


# ---------------------------------------------------------------------------
# Referentiedata: gemeente + netbeheerder
# ---------------------------------------------------------------------------

def import_gemeente(conn: sa.Connection, csv_path: Path) -> ImportResult:
    df = pd.read_csv(csv_path, sep=_SEP, dtype=str, encoding=_ENC).fillna("")
    # Collect unique DNB codes first
    dnb_codes: set[str] = set()
    for col in ("DNB Elektriciteit", "DNB Gas"):
        if col in df.columns:
            dnb_codes.update(v.strip() for v in df[col].unique() if v.strip())

    if dnb_codes:
        nb_rows = [{"code": c, "naam": c} for c in dnb_codes]
        stmt = sa.dialects.postgresql.insert(netbeheerder).values(nb_rows)
        stmt = stmt.on_conflict_do_nothing(index_elements=["code"])
        conn.execute(stmt)
        LOG.info("netbeheerder: %d codes upserted", len(nb_rows))

    seen: set[str] = set()
    rows = []
    for _, r in df.iterrows():
        pc = _str(r.get("Postcode"))
        if not pc or pc in seen:
            continue
        seen.add(pc)
        rows.append({
            "postcode": pc,
            "naam": _str(r.get("Gemeente")) or "",
            "dnb_elektriciteit": _str(r.get("DNB Elektriciteit")),
            "dnb_gas": _str(r.get("DNB Gas")),
            "gastype_oud": _str(r.get("GasType Oud")),
            "gastype_nieuw": _str(r.get("GasType Nieuw")),
        })

    stmt = sa.dialects.postgresql.insert(gemeente).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=["postcode"],
        set_={
            "naam": stmt.excluded.naam,
            "dnb_elektriciteit": stmt.excluded.dnb_elektriciteit,
            "dnb_gas": stmt.excluded.dnb_gas,
            "gastype_oud": stmt.excluded.gastype_oud,
            "gastype_nieuw": stmt.excluded.gastype_nieuw,
            "bijgewerkt_op": sa.func.now(),
        },
    )
    conn.execute(stmt)
    return ImportResult(domain="gemeente", rows_inserted=len(rows))


# ---------------------------------------------------------------------------
# Productcomponenten (master_vast.csv + master_var_dyn.csv)
# ---------------------------------------------------------------------------

def import_product_components(
    conn: sa.Connection,
    vast_csv: Path,
    var_dyn_csv: Path,
    version_id: str,
) -> ImportResult:
    total = 0

    for csv_path, bron_type_fallback in [(vast_csv, "vast"), (var_dyn_csv, None)]:
        if not csv_path.is_file():
            LOG.warning("Bestand niet gevonden, overgeslagen: %s", csv_path)
            continue

        df = pd.read_csv(csv_path, sep=_SEP, dtype=str, encoding=_ENC).fillna("")
        rows = []
        for _, r in df.iterrows():
            bt = _str(r.get("product_type")) or bron_type_fallback or "onbekend"
            rows.append({
                "version_id": version_id,
                "jaar": _int(r.get("year")),
                "maand": _int(r.get("month")),
                "segment": _str(r.get("segment")) or "",
                "energie_type": _str(r.get("energy")) or "",
                "contract_richting": _str(r.get("direction")) or "",
                "leverancier": _str(r.get("supplier")) or "",
                "product": _str(r.get("product")) or "",
                "bron_type": bt.lower() if bt else "onbekend",
                "component": _str(r.get("component")) or "",
                "component_label": _str(r.get("component_label")),
                "prijs": _dec(r.get("price")),
                "a": _dec(r.get("a")),
                "b": _dec(r.get("b")),
                "c": _dec(r.get("c")),
                "d": _dec(r.get("d")),
                "z": _dec(r.get("z")),
                "index_naam_a": _str(r.get("index_name_A")),
                "index_naam_b": _str(r.get("index_name_B")),
                "index_naam_c": _str(r.get("index_name_C")),
                "index_naam_d": _str(r.get("index_name_D")),
                "index_waarde_a": _dec(r.get("index_value_A")),
                "index_waarde_b": _dec(r.get("index_value_B")),
                "index_waarde_c": _dec(r.get("index_value_C")),
                "index_waarde_d": _dec(r.get("index_value_D")),
                "source_sheet": _str(r.get("source_sheet")),
                "source_row": _int(r.get("source_row")),
                "bron_bestand": csv_path.name,
            })

        if rows:
            conn.execute(sa.insert(product_component), rows)
            total += len(rows)
            LOG.info("product_component [%s]: %d rijen ingevoegd", csv_path.name, len(rows))

    return ImportResult(domain="product_component", rows_inserted=total)


# ---------------------------------------------------------------------------
# Netwerktarieven
# ---------------------------------------------------------------------------

def import_netwerk_tarieven(
    conn: sa.Connection,
    version_id: str,
    tariff_dir: Path,
) -> ImportResult:
    files = [
        ("tariffs_electricity_afname.csv", "elektriciteit", "afname"),
        ("tariffs_electricity_injectie.csv", "elektriciteit", "injectie"),
        ("tariffs_gas_afname.csv", "gas", "afname"),
        ("tariffs_gas_injectie.csv", "gas", "injectie"),
    ]
    total = 0

    for filename, energie_type, richting in files:
        csv_path = tariff_dir / filename
        if not csv_path.is_file():
            LOG.warning("Tarief-CSV niet gevonden, overgeslagen: %s", csv_path)
            continue

        df = pd.read_csv(csv_path, sep=_SEP, dtype=str, encoding=_ENC).fillna("")
        rows = []
        for _, r in df.iterrows():
            rows.append({
                "version_id": version_id,
                "netbeheerder_code": _str(r.get("Netbeheerder")) or "",
                "energie_type": energie_type,
                "contract_richting": richting,
                "klanttype": _str(r.get("Klanttype")) or "",
                "tarieftype": _str(r.get("Tarieftype")),
                "tariefdetail": _str(r.get("Tariefdetail")),
                "tariefnotering": _str(r.get("Tariefnotering")),
                "prijs": _dec(r.get("Prijs_num")),
                "source_sheet": _str(r.get("source_sheet")),
                "source_row": _int(r.get("source_row")),
            })

        if rows:
            stmt = sa.dialects.postgresql.insert(netwerk_tarief).values(rows)
            stmt = stmt.on_conflict_do_nothing(
                constraint="uq_netwerk_tarief",
            )
            conn.execute(stmt)
            total += len(rows)
            LOG.info("netwerk_tarief [%s/%s]: %d rijen ingevoegd", energie_type, richting, len(rows))

    return ImportResult(domain="netwerk_tarief", rows_inserted=total)


# ---------------------------------------------------------------------------
# vtest_product (vtest_products.csv — optioneel)
# ---------------------------------------------------------------------------

def import_vtest_products(
    conn: sa.Connection,
    version_id: str,
    csv_path: Path,
) -> ImportResult:
    if not csv_path.is_file():
        LOG.info("vtest_products.csv niet gevonden, overgeslagen: %s", csv_path)
        return ImportResult(domain="vtest_product", rows_inserted=0)

    df = pd.read_csv(csv_path, sep=_SEP, dtype=str, encoding=_ENC).fillna("")
    rows = []
    for _, r in df.iterrows():
        rows.append({
            "version_id": version_id,
            "vreg_id": _str(r.get("vreg_id")) or "",
            "scraped_at": _ts(r.get("scraped_at")) or datetime.now(tz=timezone.utc),
            "leverancier": _str(r.get("supplier_raw")) or "",
            "product": _str(r.get("product_raw")) or "",
            "energie_type": _str(r.get("energy")),
            "tarief_type": _str(r.get("tariff_type")),
            "looptijd_tekst": _str(r.get("looptijd_tekst")),
            "looptijd_maanden": _int(r.get("looptijd_maanden")),
            "datum_intekenen_van": _date(r.get("datum_intekenen_van")),
            "datum_intekenen_tot": _date(r.get("datum_intekenen_tot")),
            "datum_start_levering_van": _date(r.get("datum_start_levering_van")),
            "datum_start_levering_tot": _date(r.get("datum_start_levering_tot")),
            "doelgroep_zonnepanelen": _str(r.get("doelgroep_zonnepanelen")),
            "doelgroep_ev": _str(r.get("doelgroep_ev")),
            "doelgroep_energiedelen": _str(r.get("doelgroep_energiedelen")),
            "doelgroep_leegstand": _str(r.get("doelgroep_leegstand")),
            "doelgroep_groepsaankoop": _str(r.get("doelgroep_groepsaankoop")),
            "prijszekerheid_termijn": _str(r.get("prijszekerheid_termijn")),
            "prijs_indicatie_eur": _dec(r.get("prijs_indicatie_eur")),
            "link_tariefkaart": _str(r.get("link_tariefkaart")),
            "link_voorwaarden": _str(r.get("link_voorwaarden")),
            "link_supplier": _str(r.get("link_supplier")),
        })

    if not rows:
        return ImportResult(domain="vtest_product", rows_inserted=0)

    stmt = sa.dialects.postgresql.insert(vtest_product).values(rows)
    stmt = stmt.on_conflict_do_nothing(constraint="uq_vtest_product_version_vreg")
    conn.execute(stmt)
    LOG.info("vtest_product: %d rijen ingevoegd", len(rows))
    return ImportResult(domain="vtest_product", rows_inserted=len(rows))
