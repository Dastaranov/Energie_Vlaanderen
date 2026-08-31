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
    leverancier_product,
    netbeheerder,
    netwerk_tarief,
    product_component,
    vtest_product,
    vtest_product_match,
    vtest_scrape_run,
)
from energie_vlaanderen.utility.constants import DNB_CODES

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

def _dnb_code(full_name: str) -> str:
    """Vertaal een volledige netbeheerdernaam naar zijn afkorting.

    Valt terug op de volledige naam als code wanneer de naam niet in
    DNB_CODES voorkomt (bv. 'Enexis Netbeheer', een niet-Fluvius DNB die
    voor een klein aantal grensgemeenten in DnbPerGemeente.csv verschijnt),
    zodat de import niet crasht.
    """
    code = DNB_CODES.get(full_name)
    if code is None:
        LOG.warning(
            "Netbeheerder %r staat niet in DNB_CODES; volledige naam "
            "wordt als code gebruikt.",
            full_name,
        )
        return full_name
    return code


def seed_netbeheerder(conn: sa.Connection) -> ImportResult:
    """Zaai de statische netbeheerder-referentietabel vanuit DNB_CODES.

    Version-onafhankelijke (Groep 1) referentiedata — idempotent en veilig
    om bij elke import opnieuw uit te voeren.
    """
    rows = [{"code": code, "naam": naam} for naam, code in DNB_CODES.items()]
    stmt = sa.dialects.postgresql.insert(netbeheerder).values(rows)
    stmt = stmt.on_conflict_do_nothing(index_elements=["code"])
    conn.execute(stmt)
    return ImportResult(domain="netbeheerder", rows_inserted=len(rows))


def import_gemeente(conn: sa.Connection, csv_path: Path) -> ImportResult:
    df = pd.read_csv(csv_path, sep=_SEP, dtype=str, encoding=_ENC).fillna("")
    # Collect unique DNB-namen first
    dnb_names: set[str] = set()
    for col in ("DNB Elektriciteit", "DNB Gas"):
        if col in df.columns:
            dnb_names.update(v.strip() for v in df[col].unique() if v.strip())

    code_by_name: dict[str, str] = {naam: _dnb_code(naam) for naam in dnb_names}

    if dnb_names:
        nb_rows = [
            {"code": code_by_name[naam], "naam": naam} for naam in dnb_names
        ]
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
        elek_naam = _str(r.get("DNB Elektriciteit"))
        gas_naam = _str(r.get("DNB Gas"))
        rows.append({
            "postcode": pc,
            "naam": _str(r.get("Gemeente")) or "",
            "dnb_elektriciteit": code_by_name.get(elek_naam) if elek_naam else None,
            "dnb_gas": code_by_name.get(gas_naam) if gas_naam else None,
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

def _eenheid(component_code: str) -> str:
    """Leid de eenheid af van de component-code."""
    return "EUR/jaar" if component_code.startswith("fixed_fee") else "ct/kWh"


def _btw_code(component_code: str) -> str:
    """Leid de btw-code af van de component-code."""
    return "pct21" if component_code == "energiedelen" else "pct6"


def import_product_components(
    conn: sa.Connection,
    vast_csv: Path,
    var_dyn_csv: Path,
    version_id: str,
) -> ImportResult:
    total_producten = 0
    total_componenten = 0

    for csv_path, bron_type_fallback in [(vast_csv, "vast"), (var_dyn_csv, None)]:
        if not csv_path.is_file():
            LOG.warning("Bestand niet gevonden, overgeslagen: %s", csv_path)
            continue

        df = pd.read_csv(csv_path, sep=_SEP, dtype=str, encoding=_ENC).fillna("")

        groep_cols = ["year", "month", "segment", "energy", "direction",
                      "supplier", "product", "product_type"]
        for groep_sleutel, groep in df.groupby(groep_cols, dropna=False):
            jaar, maand, segment, energie, richting, lev, prod, bron_type_raw = groep_sleutel
            bt = (_str(bron_type_raw) or bron_type_fallback or "onbekend").lower()
            source_sheet = _str(groep.iloc[0].get("source_sheet"))

            # Stap 1 — product-header upsert
            stmt = sa.dialects.postgresql.insert(leverancier_product).values(
                version_id=version_id,
                jaar=_int(jaar) or 0,
                maand=_int(maand) or 0,
                segment=_str(segment) or "",
                energie_type=_str(energie) or "",
                contract_richting=_str(richting) or "",
                leverancier=_str(lev) or "",
                product=_str(prod) or "",
                bron_type=bt,
                bron_bestand=csv_path.name,
                source_sheet=source_sheet,
            ).on_conflict_do_nothing(constraint="uq_leverancier_product").returning(
                leverancier_product.c.id
            )
            result = conn.execute(stmt)
            row = result.fetchone()
            if row is None:
                # Rij bestond al — ophalen via SELECT
                row = conn.execute(
                    sa.select(leverancier_product.c.id).where(
                        (leverancier_product.c.version_id == version_id)
                        & (leverancier_product.c.energie_type == (_str(energie) or ""))
                        & (leverancier_product.c.contract_richting == (_str(richting) or ""))
                        & (leverancier_product.c.leverancier == (_str(lev) or ""))
                        & (leverancier_product.c.product == (_str(prod) or ""))
                        & (leverancier_product.c.jaar == (_int(jaar) or 0))
                        & (leverancier_product.c.maand == (_int(maand) or 0))
                        & (leverancier_product.c.segment == (_str(segment) or ""))
                    )
                ).fetchone()
            product_id = row[0]
            total_producten += 1

            # Stap 2 — componenten invoegen
            comp_rows = []
            for _, r in groep.iterrows():
                code = _str(r.get("component")) or ""
                comp_rows.append({
                    "leverancier_product_id": product_id,
                    "component_code": code,
                    "component_label": _str(r.get("component_label")),
                    "eenheid": _eenheid(code),
                    "btw_code": _btw_code(code),
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
                    "source_row": _int(r.get("source_row")),
                })

            if comp_rows:
                conn.execute(sa.insert(product_component), comp_rows)
                total_componenten += len(comp_rows)

        LOG.info("product_component [%s]: klaar", csv_path.name)

    LOG.info("product_component totaal: %d producten, %d componenten ingevoegd",
             total_producten, total_componenten)
    return ImportResult(domain="product_component", rows_inserted=total_componenten)


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
        ("tariffs_electricity_hoogspanning.csv", "elektriciteit", None),
        ("tariffs_gas_afname.csv", "gas", "afname"),
        ("tariffs_gas_injectie.csv", "gas", "injectie"),
    ]
    total = 0

    jaar = int(version_id[:4])

    for filename, energie_type, richting in files:
        csv_path = tariff_dir / filename
        if not csv_path.is_file():
            LOG.warning("Tarief-CSV niet gevonden, overgeslagen: %s", csv_path)
            continue

        df = pd.read_csv(csv_path, sep=_SEP, dtype=str, encoding=_ENC).fillna("")
        rows = []
        overgeslagen = 0
        for _, r in df.iterrows():
            prijs = _dec(r.get("Prijs_num"))
            if prijs is None:
                # Rijen zonder geldige prijs zijn voetnoten of commentaarregels
                overgeslagen += 1
                continue
            # De hoogspanning-CSV bevat zowel afname- als injectierijen (geen
            # vast richting per bestand); leid de richting dan per rij af uit
            # de Contracttype-kolom i.p.v. de bestandsbrede `richting`.
            row_richting = richting or (_str(r.get("Contracttype")) or "").lower()
            if row_richting not in ("afname", "injectie"):
                LOG.warning(
                    "netwerk_tarief [%s]: onherkenbare Contracttype-waarde %r overgeslagen",
                    energie_type, r.get("Contracttype"),
                )
                overgeslagen += 1
                continue
            rows.append({
                "version_id": version_id,
                "jaar": jaar,
                "netbeheerder_code": _str(r.get("Netbeheerder")) or "",
                "energie_type": energie_type,
                "contract_richting": row_richting,
                "klanttype": _str(r.get("Klanttype")) or "",
                "tarieftype": _str(r.get("Tarieftype")),
                "tariefdetail": _str(r.get("Tariefdetail")),
                "tariefnotering": _str(r.get("Tariefnotering")),
                "prijs": prijs,
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
            LOG.info("netwerk_tarief [%s/%s]: %d rijen ingevoegd, %d voetnoten overgeslagen",
                     energie_type, richting or "gemengd", len(rows), overgeslagen)

    return ImportResult(domain="netwerk_tarief", rows_inserted=total)


# ---------------------------------------------------------------------------
# vtest_scrape_run (metadata van de scrape-sessie)
# ---------------------------------------------------------------------------

def import_vtest_scrape_run(
    conn: sa.Connection,
    version_id: str,
    meta_json_path: Path,
    vtest_dir: Path,
) -> int:
    """Registreer de scrape-run in de DB en geef het gegenereerde id terug."""
    import json as _json

    meta: dict = {}
    if meta_json_path.is_file():
        try:
            meta = _json.loads(meta_json_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    raw_ts = meta.get("scraped_at")
    scraped_at = (
        datetime.fromisoformat(raw_ts) if raw_ts else datetime.now(tz=timezone.utc)
    )

    dump_html = vtest_dir / "vtest_dump.html"
    dump_bestand = str(dump_html.relative_to(dump_html.parent.parent.parent)) if dump_html.is_file() else None

    result = conn.execute(
        sa.insert(vtest_scrape_run).values(
            version_id=version_id,
            scraped_at=scraped_at,
            postcode=meta.get("postcode") or None,
            browser=meta.get("browser") or None,
            headless=meta.get("headless"),
            products_found=meta.get("products_found"),
            dump_bestand=dump_bestand,
        ).returning(vtest_scrape_run.c.id)
    )
    run_id: int = result.scalar_one()
    LOG.info("vtest_scrape_run aangemaakt: id=%d (postcode=%s, %d producten)", run_id, meta.get("postcode"), meta.get("products_found") or 0)
    return run_id


# ---------------------------------------------------------------------------
# vtest_product (vtest_products.csv — optioneel)
# ---------------------------------------------------------------------------

def import_vtest_products(
    conn: sa.Connection,
    version_id: str,
    csv_path: Path,
    scrape_run_id: int | None = None,
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
            "scrape_run_id": scrape_run_id,
        })

    if not rows:
        return ImportResult(domain="vtest_product", rows_inserted=0)

    stmt = sa.dialects.postgresql.insert(vtest_product).values(rows)
    stmt = stmt.on_conflict_do_nothing(constraint="uq_vtest_product_version_vreg")
    conn.execute(stmt)
    LOG.info("vtest_product: %d rijen ingevoegd", len(rows))
    return ImportResult(domain="vtest_product", rows_inserted=len(rows))


# ---------------------------------------------------------------------------
# vtest_product_match (vtest_product_links.csv — optioneel, best-effort
# koppeling tussen vreg_id en de bulk-export van energie_vlaanderen.ingest.
# vtest.product_matcher). Vereist dat vtest_product al gevuld is (FK).
# ---------------------------------------------------------------------------

def import_vtest_product_links(
    conn: sa.Connection,
    version_id: str,
    csv_path: Path,
) -> ImportResult:
    if not csv_path.is_file():
        LOG.info("vtest_product_links.csv niet gevonden, overgeslagen: %s", csv_path)
        return ImportResult(domain="vtest_product_match", rows_inserted=0)

    df = pd.read_csv(csv_path, sep=";", encoding=_ENC).fillna("")
    now = datetime.now(tz=timezone.utc)
    rows = []
    for _, r in df.iterrows():
        vreg_id = _str(r.get("vreg_id")) or ""
        if not vreg_id:
            continue
        rows.append({
            "version_id": version_id,
            "vreg_id": vreg_id,
            "handelsnaam": _str(r.get("matched_handelsnaam")) or None,
            "productnaam": _str(r.get("matched_productnaam")) or None,
            "match_status": _str(r.get("match_status")) or "geen_match",
            "gekoppeld_op": now,
        })

    if not rows:
        return ImportResult(domain="vtest_product_match", rows_inserted=0)

    stmt = sa.dialects.postgresql.insert(vtest_product_match).values(rows)
    stmt = stmt.on_conflict_do_nothing(constraint="uq_vtest_product_match_version_vreg")
    conn.execute(stmt)
    LOG.info("vtest_product_match: %d rijen ingevoegd", len(rows))
    return ImportResult(domain="vtest_product_match", rows_inserted=len(rows))
