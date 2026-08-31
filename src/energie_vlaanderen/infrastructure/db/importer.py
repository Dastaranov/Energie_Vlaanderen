from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone, date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import pandas as pd
import sqlalchemy as sa

from energie_vlaanderen.infrastructure.db.schema import (
    data_version,
    gemeente,
    leverancier,
    energie_product,
    tarief_afname,
    tarief_injectie,
    netbeheerder,
    netbeheerder_tarief,
    vtest_scrape_run,
    vtest_contract,
    vtest_postcode_prijs,
    overheidsheffing_accijns_schijf,
    overheidsheffing_energiefonds,
    overheidsheffing_btw,
)
from energie_vlaanderen.heffingen.repository import HeffingenRepository
from energie_vlaanderen.utility.constants import DNB_CODES

LOG = logging.getLogger(__name__)

_SEP = ";"
_ENC = "utf-8-sig"

# Meter-types die in de component-kolom voorkomen
METER_TYPES = {"single", "day", "night", "exclusive_night", "night_low", "piekuren", "daluren", "superdaluren", "dynamic"}


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
    """Vertaal een volledige netbeheerdernaam naar zijn afkorting."""
    code = DNB_CODES.get(full_name)
    if code is None:
        LOG.warning(
            "Netbeheerder %r staat niet in DNB_CODES; volledige naam wordt als code gebruikt.",
            full_name,
        )
        return full_name
    return code


def seed_netbeheerder(conn: sa.Connection) -> ImportResult:
    """Zaai de statische netbeheerder-referentietabel vanuit DNB_CODES."""
    rows = [{"code": code, "naam": naam} for naam, code in DNB_CODES.items()]
    stmt = sa.dialects.postgresql.insert(netbeheerder).values(rows)
    stmt = stmt.on_conflict_do_nothing(index_elements=["code"])
    conn.execute(stmt)
    return ImportResult(domain="netbeheerder", rows_inserted=len(rows))


def import_gemeente(conn: sa.Connection, csv_path: Path) -> ImportResult:
    df = pd.read_csv(csv_path, sep=_SEP, dtype=str, encoding=_ENC).fillna("")
    dnb_names: set[str] = set()
    for col in ("DNB Elektriciteit", "DNB Gas"):
        if col in df.columns:
            dnb_names.update(v.strip() for v in df[col].unique() if v.strip())

    code_by_name: dict[str, str] = {naam: _dnb_code(naam) for naam in dnb_names}

    if dnb_names:
        nb_rows = [{"code": code_by_name[naam], "naam": naam} for naam in dnb_names]
        stmt = sa.dialects.postgresql.insert(netbeheerder).values(nb_rows)
        stmt = stmt.on_conflict_do_nothing(index_elements=["code"])
        conn.execute(stmt)

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
# Component-to-tariff column mapping
# ---------------------------------------------------------------------------

def _map_component_code_to_field(component_code: str) -> str | None:
    """Map een component_code naar zijn tarief-kolom (of None als meter_type/onbekend)."""
    if not component_code:
        return None

    cc = str(component_code).lower().strip()

    # Energieprijs
    if cc in ("energieprijs", "energieprijs_kwh", "energy_price"):
        return "energieprijs_kwh"

    # Surcharge-componenten
    if "groene stroom" in cc or cc in ("groene_stroom_kwh", "groene_stroom", "green"):
        return "groene_stroom_kwh"
    if "wkk" in cc or cc in ("wkk_kwh",):
        return "wkk_kwh"
    if "energiebijdrage" in cc or "bijdrage" in cc:
        return "energiebijdrage_kwh"

    # Vaste vergoeding
    if "vaste vergoeding" in cc or "vast bedrag" in cc or cc.startswith("fixed_fee"):
        return "vaste_vergoeding_jaar"

    # Formule-parameters
    for param in ("a", "b", "c", "d", "z"):
        if cc in (f"param_{param}", f"parameter_{param}"):
            return f"param_{param}"

    # Index-namen en -waarden
    for idx in ("a", "b", "c", "d"):
        if cc in (f"index_name_{idx}", f"index_naam_{idx}"):
            return f"index_naam_{idx}"
        if cc in (f"index_value_{idx}", f"index_waarde_{idx}"):
            return f"index_waarde_{idx}"

    return None


# ---------------------------------------------------------------------------
# Leverancier en Energie Product (vervangt product_components)
# ---------------------------------------------------------------------------

def import_leverancier_en_product(
    conn: sa.Connection,
    vast_csv: Path,
    var_dyn_csv: Path,
) -> ImportResult:
    """Importeer leveranciers en hun productdata uit de CSV-bestanden."""
    total_producten = 0
    total_tarieven = 0
    unmapped_components: set[str] = set()

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

            # Stap 1 — leverancier upsert
            lev_naam = _str(lev) or ""
            if not lev_naam:
                continue

            lev_stmt = sa.dialects.postgresql.insert(leverancier).values(naam=lev_naam)
            lev_stmt = lev_stmt.on_conflict_do_nothing(index_elements=["naam"])
            conn.execute(lev_stmt)

            lev_result = conn.execute(
                sa.select(leverancier.c.id).where(leverancier.c.naam == lev_naam)
            ).fetchone()
            if not lev_result:
                continue
            lev_id = lev_result[0]

            # Stap 2 — energie_product upsert
            prod_naam = _str(prod) or ""
            ener_type = _str(energie) or ""
            seg = _str(segment) or ""
            if not (prod_naam and ener_type and seg):
                continue

            prod_stmt = sa.dialects.postgresql.insert(energie_product).values(
                leverancier_id=lev_id,
                product_naam=prod_naam,
                energie_type=ener_type,
                segment=seg,
            ).on_conflict_do_nothing(
                constraint="uq_energie_product_identiteit"
            ).returning(energie_product.c.id)

            prod_result = conn.execute(prod_stmt).fetchone()
            if prod_result is None:
                prod_result = conn.execute(
                    sa.select(energie_product.c.id).where(
                        (energie_product.c.leverancier_id == lev_id)
                        & (energie_product.c.product_naam == prod_naam)
                        & (energie_product.c.energie_type == ener_type)
                        & (energie_product.c.segment == seg)
                    )
                ).fetchone()
            prod_id = prod_result[0] if prod_result else None
            if not prod_id:
                continue
            total_producten += 1

            # Stap 3 — bepaal meter_types in deze groep
            geldig_van = date(int(jaar) if jaar else 1970, int(maand) if maand else 1, 1)
            richting_str = _str(richting or "").lower()

            meter_types_in_groep: set[str] = {"single"}
            for _, r in groep.iterrows():
                comp_code = _str(r.get("component")) or ""
                if comp_code.lower() in METER_TYPES:
                    meter_types_in_groep.add(comp_code.lower())

            # Voor elke meter_type, maak een tarief-rij
            for meter_type in meter_types_in_groep:
                tarief_row = {
                    "product_id": prod_id,
                    "meter_type": meter_type,
                    "prijs_type": bt,
                    "geldig_van": geldig_van,
                    "bron_bestand": csv_path.name,
                    "source_row": _int(groep.iloc[0].get("source_row")),
                }

                # Voeg parameters en indices toe
                first_row = groep.iloc[0]
                for param in ("a", "b", "c", "d", "z"):
                    val = _dec(first_row.get(param))
                    if val is not None:
                        tarief_row[f"param_{param}"] = val

                for idx in ("a", "b", "c", "d"):
                    val = _str(first_row.get(f"index_name_{idx}"))
                    if val:
                        tarief_row[f"index_naam_{idx}"] = val
                    val = _dec(first_row.get(f"index_value_{idx}"))
                    if val is not None:
                        tarief_row[f"index_waarde_{idx}"] = val

                # Voeg component-waarden toe
                for _, comp_r in groep.iterrows():
                    comp_code = _str(comp_r.get("component")) or ""
                    # Skip meter_type codes
                    if comp_code.lower() in METER_TYPES:
                        continue

                    prijs = _dec(comp_r.get("price"))
                    field = _map_component_code_to_field(comp_code)
                    if not field:
                        unmapped_components.add(comp_code)
                        continue
                    if prijs is not None:
                        tarief_row[field] = prijs

                # SCD2-upsert
                if richting_str == "afname" or richting_str not in ("injectie",):
                    _scd2_upsert(conn, tarief_afname, tarief_row)
                    total_tarieven += 1
                if richting_str == "injectie":
                    _scd2_upsert(conn, tarief_injectie, tarief_row)
                    total_tarieven += 1

        LOG.info("leverancier_en_product [%s]: klaar", csv_path.name)

    if unmapped_components:
        LOG.warning("Onbekende component-codes: %s", sorted(unmapped_components))

    LOG.info(
        "leverancier_en_product totaal: %d producten, %d tarief-snapshots",
        total_producten, total_tarieven
    )
    return ImportResult(domain="leverancier_product", rows_inserted=total_tarieven)


# ---------------------------------------------------------------------------
# SCD2 Upsert helper
# ---------------------------------------------------------------------------

def _scd2_upsert(
    conn: sa.Connection,
    tariff_table: sa.Table,
    row_data: dict[str, Any],
) -> None:
    """SCD Type 2 upsert voor tarief-tabellen."""
    product_id = row_data.get("product_id")
    meter_type = row_data.get("meter_type", "single")
    geldig_van = row_data.get("geldig_van")

    if not product_id or not geldig_van:
        return

    # Query open rij
    open_row = conn.execute(
        sa.select(tariff_table.c.id).where(
            (tariff_table.c.product_id == product_id)
            & (tariff_table.c.meter_type == meter_type)
            & (tariff_table.c.geldig_tot.is_(None))
        )
    ).fetchone()

    if open_row:
        open_id = open_row[0]
        # Sluit oude rij
        vorige_dag = date.fromordinal(geldig_van.toordinal() - 1)
        conn.execute(
            sa.update(tariff_table)
            .where(tariff_table.c.id == open_id)
            .values(geldig_tot=vorige_dag)
        )

    # Insert nieuwe open rij
    row_to_insert = {**row_data, "geldig_tot": None}
    conn.execute(sa.insert(tariff_table).values(**row_to_insert))


# ---------------------------------------------------------------------------
# Link vreg_id via product links
# ---------------------------------------------------------------------------

def link_energie_product_vreg_ids(
    conn: sa.Connection,
    vast_csv: Path,
    var_dyn_csv: Path,
    links_csv: Path,
) -> ImportResult:
    """Koppel energie_product.vreg_id via vtest_product_links.csv."""
    if not links_csv.is_file():
        LOG.info("vtest_product_links.csv niet gevonden")
        return ImportResult(domain="energie_product_vreg", rows_inserted=0)

    df_links = pd.read_csv(links_csv, sep=";", encoding=_ENC).fillna("")
    linked_count = 0

    for _, r in df_links.iterrows():
        vreg_id = _str(r.get("vreg_id"))
        matched_lev = _str(r.get("matched_handelsnaam"))
        matched_prod = _str(r.get("matched_productnaam"))

        if not (vreg_id and matched_lev and matched_prod):
            continue

        # Update energie_product met deze vreg_id
        result = conn.execute(
            sa.update(energie_product)
            .where(
                (sa.func.lower(energie_product.c.product_naam) == matched_prod.lower())
                & (
                    sa.select(leverancier.c.id).where(
                        sa.func.lower(leverancier.c.naam) == matched_lev.lower()
                    ).correlate(leverancier).scalar_subquery()
                    == energie_product.c.leverancier_id
                )
            )
            .values(vreg_id=vreg_id)
        )
        linked_count += result.rowcount or 0

    LOG.info("energie_product_vreg_links: %d gekoppeld", linked_count)
    return ImportResult(domain="energie_product_vreg", rows_inserted=linked_count)


# ---------------------------------------------------------------------------
# vtest_scrape_run
# ---------------------------------------------------------------------------

def import_vtest_scrape_run(
    conn: sa.Connection,
    version_id: str,
    meta_json_path: Path,
    vtest_dir: Path,
) -> int:
    """Registreer de scrape-run."""
    import json as _json

    meta: dict = {}
    if meta_json_path.is_file():
        try:
            meta = _json.loads(meta_json_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    raw_ts = meta.get("scraped_at")
    scraped_at = datetime.fromisoformat(raw_ts) if raw_ts else datetime.now(tz=timezone.utc)

    dump_html = vtest_dir / "vtest_dump.html"
    dump_bestand = str(dump_html.relative_to(dump_html.parent.parent.parent)) if dump_html.is_file() else None

    result = conn.execute(
        sa.insert(vtest_scrape_run).values(
            version_id=version_id,
            scraped_at=scraped_at,
            postcode=meta.get("postcode"),
            browser=meta.get("browser"),
            headless=meta.get("headless"),
            products_found=meta.get("products_found"),
            dump_bestand=dump_bestand,
        ).returning(vtest_scrape_run.c.id)
    )
    run_id: int = result.scalar_one()
    LOG.info("vtest_scrape_run aangemaakt: id=%d", run_id)
    return run_id


# ---------------------------------------------------------------------------
# vtest_contract + vtest_postcode_prijs
# ---------------------------------------------------------------------------

def import_vtest_contract_en_prijzen(
    conn: sa.Connection,
    version_id: str,
    csv_path: Path,
) -> ImportResult:
    """Importeer contractmetadata en prijzen per postcode."""
    if not csv_path.is_file():
        LOG.info("vtest_products.csv niet gevonden")
        return ImportResult(domain="vtest_postcode_prijs", rows_inserted=0)

    df = pd.read_csv(csv_path, sep=_SEP, dtype=str, encoding=_ENC).fillna("")

    contract_rows = []
    prijs_rows = []
    seen_vreg_ids: set[str] = set()

    for _, r in df.iterrows():
        vreg_id = _str(r.get("vreg_id")) or ""
        if not vreg_id:
            continue

        # Contract metadata (eenmaal per vreg_id)
        if vreg_id not in seen_vreg_ids:
            seen_vreg_ids.add(vreg_id)
            contract_rows.append({
                "vreg_id": vreg_id,
                "leverancier_raw": _str(r.get("supplier_raw")) or "",
                "product_raw": _str(r.get("product_raw")) or "",
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
                "link_tariefkaart": _str(r.get("link_tariefkaart")),
                "link_voorwaarden": _str(r.get("link_voorwaarden")),
                "link_supplier": _str(r.get("link_supplier")),
                "contracttype": _str(r.get("contracttype")),
                "supplier_id": _str(r.get("supplier_id")),
                "product_id": _str(r.get("product_id")),
                "green_type": _str(r.get("green_type")),
                "stars": _str(r.get("stars")),
                "complex_product": r.get("complex_product") == "True",
                "grayedout": r.get("grayedout") == "True",
                "laatst_gezien_versie": version_id,
                "laatst_gezien_op": datetime.now(tz=timezone.utc),
            })

        # Prijs per postcode
        postcode = _str(r.get("postcode")) or ""
        segment = _str(r.get("segment")) or ""
        prijs_rows.append({
            "vreg_id": vreg_id,
            "postcode": postcode,
            "segment": segment,
            "version_id": version_id,
            "discount_eur": _dec(r.get("discount_eur")),
            "total_excl_btw": _dec(r.get("total_excl_btw")),
            "total_incl_btw": _dec(r.get("total_incl_btw")),
            "btw_bedrag": _dec(r.get("btw_bedrag")),
            "totaal_verbruik_kwh": _dec(r.get("totaal_verbruik_kwh")),
            "prijs_indicatie_eur": _dec(r.get("prijs_indicatie_eur")),
            "scraped_at": _ts(r.get("scraped_at")) or datetime.now(tz=timezone.utc),
        })

    # Upsert contracts
    if contract_rows:
        stmt = sa.dialects.postgresql.insert(vtest_contract).values(contract_rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=["vreg_id"],
            set_={"laatst_gezien_versie": stmt.excluded.laatst_gezien_versie,
                  "laatst_gezien_op": stmt.excluded.laatst_gezien_op},
        )
        conn.execute(stmt)

    # Insert prijzen
    if prijs_rows:
        stmt = sa.dialects.postgresql.insert(vtest_postcode_prijs).values(prijs_rows)
        stmt = stmt.on_conflict_do_nothing(constraint="uq_vtest_postcode_prijs")
        conn.execute(stmt)

    total = len(contract_rows) + len(prijs_rows)
    LOG.info("vtest: %d contracts, %d prijsrijen", len(contract_rows), len(prijs_rows))
    return ImportResult(domain="vtest_postcode_prijs", rows_inserted=total)


# ---------------------------------------------------------------------------
# Netbeheerder Tarieve (SCD2)
# ---------------------------------------------------------------------------

def import_netbeheerder_tarieven(
    conn: sa.Connection,
    tariff_dir: Path,
    jaar: int,
) -> ImportResult:
    """Importeer netbeheerder-tarieven met SCD2."""
    files = [
        ("tariffs_electricity_afname.csv", "elektriciteit", "afname"),
        ("tariffs_electricity_injectie.csv", "elektriciteit", "injectie"),
        ("tariffs_electricity_hoogspanning.csv", "elektriciteit", None),
        ("tariffs_gas_afname.csv", "gas", "afname"),
        ("tariffs_gas_injectie.csv", "gas", "injectie"),
    ]
    total = 0

    for filename, energie_type, richting in files:
        csv_path = tariff_dir / filename
        if not csv_path.is_file():
            continue

        df = pd.read_csv(csv_path, sep=_SEP, dtype=str, encoding=_ENC).fillna("")
        geldig_van = date(jaar, 1, 1)

        for _, r in df.iterrows():
            prijs = _dec(r.get("Prijs_num"))
            if prijs is None:
                continue

            row_richting = richting or (_str(r.get("Contracttype")) or "").lower()
            if row_richting not in ("afname", "injectie"):
                continue

            row_data = {
                "netbeheerder_code": _str(r.get("Netbeheerder")) or "",
                "energie_type": energie_type,
                "contract_richting": row_richting,
                "klanttype": _str(r.get("Klanttype")) or "",
                "tarieftype": _str(r.get("Tarieftype")),
                "tariefdetail": _str(r.get("Tariefdetail")),
                "tariefnotering": _str(r.get("Tariefnotering")),
                "prijs": prijs,
                "geldig_van": geldig_van,
                "source_sheet": _str(r.get("source_sheet")),
                "source_row": _int(r.get("source_row")),
            }
            _scd2_upsert_netbeheerder(conn, row_data)
            total += 1

    LOG.info("netbeheerder_tarief: %d rijen", total)
    return ImportResult(domain="netbeheerder_tarief", rows_inserted=total)


def _scd2_upsert_netbeheerder(conn: sa.Connection, row_data: dict[str, Any]) -> None:
    """SCD2-upsert voor netbeheerder_tarief."""
    netbeheerder_code = row_data.get("netbeheerder_code")
    energie_type = row_data.get("energie_type")
    contract_richting = row_data.get("contract_richting")
    klanttype = row_data.get("klanttype")
    tarieftype = row_data.get("tarieftype")
    tariefdetail = row_data.get("tariefdetail")
    geldig_van = row_data.get("geldig_van")

    if not all([netbeheerder_code, energie_type, contract_richting, klanttype, geldig_van]):
        return

    # Sluit eventuele open rij
    open_row = conn.execute(
        sa.select(netbeheerder_tarief.c.id).where(
            (netbeheerder_tarief.c.netbeheerder_code == netbeheerder_code)
            & (netbeheerder_tarief.c.energie_type == energie_type)
            & (netbeheerder_tarief.c.contract_richting == contract_richting)
            & (netbeheerder_tarief.c.klanttype == klanttype)
            & (netbeheerder_tarief.c.tarieftype == tarieftype)
            & (netbeheerder_tarief.c.tariefdetail == tariefdetail)
            & (netbeheerder_tarief.c.geldig_tot.is_(None))
        )
    ).fetchone()

    if open_row:
        vorige_dag = date.fromordinal(geldig_van.toordinal() - 1)
        conn.execute(
            sa.update(netbeheerder_tarief)
            .where(netbeheerder_tarief.c.id == open_row[0])
            .values(geldig_tot=vorige_dag)
        )

    # Insert nieuwe open rij
    row_to_insert = {**row_data, "geldig_tot": None}
    conn.execute(sa.insert(netbeheerder_tarief).values(**row_to_insert))


# ---------------------------------------------------------------------------
# Overheidsheffingen
# ---------------------------------------------------------------------------

def import_overheidsheffingen(conn: sa.Connection, config_dir: Path) -> ImportResult:
    """Importeer heffingen uit config/heffingen/."""
    try:
        heffingenrepo = HeffingenRepository.load(config_dir)
    except Exception as exc:
        LOG.error("Kon heffingen niet laden: %s", exc)
        return ImportResult(domain="overheidsheffing", rows_inserted=0)

    # TRUNCATE
    conn.execute(sa.delete(overheidsheffing_btw))
    conn.execute(sa.delete(overheidsheffing_energiefonds))
    conn.execute(sa.delete(overheidsheffing_accijns_schijf))

    total = 0

    # Accijns
    try:
        accijns_tabellen = heffingenrepo.accijns_tabellen()
        accijns_rows = []
        for tabel in accijns_tabellen.values():
            for schijf in tabel.schijven:
                accijns_rows.append({
                    "energievorm": tabel.energievorm,
                    "klantcategorie": schijf.klantcategorie,
                    "van_mwh": schijf.van_mwh,
                    "tot_mwh": schijf.tot_mwh,
                    "accijns_eur_mwh": schijf.accijns_eur_mwh,
                    "bijzondere_accijns_eur_mwh": schijf.bijzondere_accijns_eur_mwh,
                    "energiebijdrage_eur_mwh": schijf.energiebijdrage_eur_mwh,
                    "bron": tabel.bron or "onbekend",
                })
        if accijns_rows:
            conn.execute(sa.insert(overheidsheffing_accijns_schijf), accijns_rows)
            total += len(accijns_rows)
    except Exception as exc:
        LOG.warning("Accijns-heffingen fout: %s", exc)

    # Energiefonds
    try:
        energiefonds_tarieven = heffingenrepo.energiefonds_tarieven()
        energiefonds_rows = []
        for tarief in energiefonds_tarieven:
            energiefonds_rows.append({
                "jaar": tarief.jaar,
                "spanningsniveau": tarief.spanningsniveau,
                "klantcategorie": tarief.klantcategorie or "",
                "eur_per_maand": tarief.eur_per_maand,
                "bron": tarief.bron or "onbekend",
            })
        if energiefonds_rows:
            conn.execute(sa.insert(overheidsheffing_energiefonds), energiefonds_rows)
            total += len(energiefonds_rows)
    except Exception as exc:
        LOG.warning("Energiefonds-heffingen fout: %s", exc)

    # BTW
    try:
        btw_tarieven = heffingenrepo.btw_tarieven()
        btw_rows = []
        for tarief in btw_tarieven:
            btw_rows.append({
                "component": tarief.component,
                "percentage": tarief.percentage,
                "vrijgesteld": tarief.vrijgesteld,
                "geldig_vanaf": tarief.geldig_vanaf,
                "bron": tarief.bron or "onbekend",
            })
        if btw_rows:
            conn.execute(sa.insert(overheidsheffing_btw), btw_rows)
            total += len(btw_rows)
    except Exception as exc:
        LOG.warning("BTW-heffingen fout: %s", exc)

    LOG.info("overheidsheffing: %d rijen", total)
    return ImportResult(domain="overheidsheffing", rows_inserted=total)
