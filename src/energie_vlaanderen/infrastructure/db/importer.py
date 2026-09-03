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
    nettarief_transport,
    vtest_scrape_run,
    marktcurve,
    vtest_contract,
    vtest_postcode_prijs,
    overheidsheffing_accijns_schijf,
    overheidsheffing_energiefonds,
    overheidsheffing_btw,
    verbruiksprofiel_waarde,
)
from energie_vlaanderen.heffingen.repository import HeffingenRepository
from energie_vlaanderen.ingest.vtest.normalizer import FORMULA_COMPONENTS
from energie_vlaanderen.utility.constants import DNB_CODES
from energie_vlaanderen.utility.normalizer import ontleed_leveranciersnaam

LOG = logging.getLogger(__name__)

_SEP = ";"
_ENC = "utf-8-sig"

# Meter-types die in de component-kolom voorkomen
# Componentcodes die een eigen prijsband vormen: elk krijgt een eigen rij in
# tarief_afname/tarief_injectie met zijn eigen energieprijs. De naam
# "meter_type" is historisch — het gaat niet alleen om de meteropstelling
# (single/day/night) maar ook om contractuele banden: tijdsblokken van een
# ToU-contract, het gewaarborgde vaste deel van een variabel contract, of
# zelfverbruik.
#
# Alles wat hier niet in staat en ook geen toeslagkolom is, wordt bij de
# import weggegooid. Dat gebeurde met 295 prijsrijen: de ToU-banden stonden er
# nog onder hun oude Nederlandse namen (daluren/piekuren/superdaluren), en de
# _vast-varianten stonden er nooit in.
#
# De afgeleide varianten worden daarom niet met de hand opgesomd maar uit de
# vocabulaire van de normalizer opgebouwd. Die maakt "<code>_vast" voor het
# gewaarborgde deel van een variabel contract en "<code>_low" voor de lage
# verbruiksschijf; met de hand bijhouden liet er telkens een paar wegvallen.
_BASIS_PRIJSBANDEN = {
    # Meteropstelling
    "single",
    "day",
    "night",
    "exclusive_night",
    # Ebem bundelt dag- en exclusief-nachttarief in één regel
    "single_and_exclusive_night",
    # Tijdsblokken van ToU-contracten (ENGIE Empower met Flextime)
    "tou_peak",
    "tou_offpeak",
    "tou_super_offpeak",
    # Zelfverbruik uit de eigen installatie (EnergyVision)
    "self_consumption",
    # Dynamisch uurtarief
    "dynamic",
    # Lekt uit VREG's eigen datamodel (ENGIE Easy); als eigen band bewaard
    # zodat de prijs niet verdwijnt zonder te doen alsof het iets anders is.
    "consumptiontotal",
}

METER_TYPES = (
    _BASIS_PRIJSBANDEN
    | {f"{code}_vast" for code in FORMULA_COMPONENTS}
    | {f"{code}_low" for code in _BASIS_PRIJSBANDEN}
    | {f"{code}_vast_low" for code in FORMULA_COMPONENTS}
)


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
    """Registreer de versie, zonder een actieve versie terug te zetten.

    Een herimport van de actieve versie zette de status terug op "staged"
    terwijl `geactiveerd_op` gevuld bleef. De twee velden spraken elkaar dan
    tegen: `db verify` zag de versie als actief, het statusveld zei van niet.
    """
    ts = datetime.now(tz=timezone.utc)
    stmt = sa.dialects.postgresql.insert(data_version).values(
        version_id=version_id,
        aangemaakt_op=ts,
        status=status,
    ).on_conflict_do_update(
        index_elements=["version_id"],
        set_={
            "status": sa.case(
                (data_version.c.geactiveerd_op.isnot(None), data_version.c.status),
                else_=status,
            )
        },
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

# Welke meteropstelling bij welke vaste-vergoedingsvariant hoort. Alleen de
# eenduidige gevallen staan hier: `fixed_fee_double` is de twee-registermeter,
# dus dag én nacht. Een variant die hier niet in staat wordt niet geraden maar
# als bevinding gemeld — een verkeerde vaste vergoeding is een stil verkeerd
# bedrag, en dat is precies wat dit project probeert te vermijden.
_VASTE_VERGOEDING_PER_METERTYPE: dict[str, tuple[str, ...]] = {
    "fixed_fee_single": ("single",),
    "fixed_fee_double": ("day", "night"),
    "fixed_fee_exclusive_night": ("exclusive_night",),
}


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

    # Vaste vergoeding. Alleen de algemene vorm: `fixed_fee_single`,
    # `fixed_fee_double` en `fixed_fee_exclusive_night` horen bij één
    # meteropstelling en worden apart afgehandeld
    # (`_VASTE_VERGOEDING_PER_METERTYPE`). Ze hier allemaal op dezelfde kolom
    # laten uitkomen liet de laatst verwerkte variant winnen — en dat voor
    # élk metertype in de groep. Bij Ebem "Groen B@sic+" kreeg de
    # single-meter zo 33,06 (het tarief voor exclusief nacht) in plaats van
    # 70,75.
    if cc in ("fixed_fee", "vaste vergoeding", "vast bedrag"):
        return "vaste_vergoeding_jaar"
    if cc.startswith("fixed_fee_"):
        return None
    if "vaste vergoeding" in cc or "vast bedrag" in cc:
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
    onbekende_annotaties: set[str] = set()
    afname_rijen: list[dict[str, Any]] = []
    injectie_rijen: list[dict[str, Any]] = []
    product_cache: dict[tuple, int] = {}

    # Leveranciers in het geheugen bijhouden: er zijn ruim tienduizend
    # productgroepen maar amper vijfendertig leveranciers, dus per groep naar
    # de databank gaan is verspilde rondreistijd.
    leverancier_cache: dict[str, int] = {
        naam.casefold(): id_
        for id_, naam in conn.execute(
            sa.select(leverancier.c.id, leverancier.c.naam)
        ).fetchall()
    }

    for csv_path, bron_type_fallback in [(vast_csv, "vast"), (var_dyn_csv, None)]:
        if not csv_path.is_file():
            LOG.warning("Bestand niet gevonden, overgeslagen: %s", csv_path)
            continue

        df = pd.read_csv(csv_path, sep=_SEP, dtype=str, encoding=_ENC).fillna("")

        groep_cols = ["year", "month", "segment", "energy", "direction",
                      "supplier", "product", "product_type"]

        # Chronologisch verwerken. De CSV wordt met dtype=str gelezen, dus
        # groupby sorteert de maanden als tekst: 1, 10, 11, 12, 2, 3, ...
        # De SCD2-historiek werd daardoor in de verkeerde volgorde opgebouwd —
        # na december kwamen februari tot september nog langs, elk als een
        # terugwerkende wijziging die de decemberrij afsloot met een geldig_tot
        # vóór zijn eigen begin.
        def _periode(sleutel) -> tuple[int, int]:
            try:
                return int(sleutel[0] or 0), int(sleutel[1] or 0)
            except (TypeError, ValueError):
                return 0, 0

        groepen = sorted(
            df.groupby(groep_cols, dropna=False), key=lambda kv: _periode(kv[0])
        )
        for groep_sleutel, groep in groepen:
            jaar, maand, segment, energie, richting, lev, prod, bron_type_raw = groep_sleutel
            bt = (_str(bron_type_raw) or bron_type_fallback or "onbekend").lower()

            # Stap 1 — leverancier upsert
            #
            # De VREG-export spelt dezelfde leverancier niet altijd gelijk:
            # "Dots Energy" (36 rijen) en "Dots energy" (38) staan er beide in.
            # Op naam alleen levert dat twee leverancierrijen op, waarna de
            # producten van één leverancier over twee records verdeeld raken —
            # en de vreg_id-koppeling, die op lower(naam) zoekt, twee rijen
            # terugkrijgt en de import laat klappen.
            #
            # Daarnaast schrijft VREG dezelfde leverancier soms met en soms
            # zonder juridische entiteit: "ENGIE" naast "ENGIE (handelsnaam
            # van Electrabel)". We splitsen dat: de merknaam is de identiteit,
            # de entiteit een eigenschap.
            lev_ruw = _str(lev) or ""
            if not lev_ruw:
                continue
            ontleed = ontleed_leveranciersnaam(lev_ruw)
            lev_naam, lev_entiteit = ontleed.naam, ontleed.juridische_entiteit
            if not lev_naam:
                continue
            if ontleed.onbekende_annotatie:
                # Een nieuwe schrijfwijze zou anders stil een tweede
                # leverancier worden; melden zodat de normalisatie meegroeit.
                onbekende_annotaties.add(lev_ruw)

            lev_id = leverancier_cache.get(lev_naam.casefold())
            if lev_id is None:
                lev_stmt = sa.dialects.postgresql.insert(leverancier).values(
                    naam=lev_naam, juridische_entiteit=lev_entiteit
                )
                lev_stmt = lev_stmt.on_conflict_do_nothing(index_elements=["naam"])
                conn.execute(lev_stmt)
                lev_result = conn.execute(
                    sa.select(leverancier.c.id).where(
                        sa.func.lower(leverancier.c.naam) == lev_naam.casefold()
                    )
                ).fetchone()
                if not lev_result:
                    continue
                lev_id = lev_result[0]
                leverancier_cache[lev_naam.casefold()] = lev_id
            elif lev_entiteit:
                # De korte schrijfwijze kwam eerst; vul de entiteit alsnog aan.
                conn.execute(
                    sa.update(leverancier)
                    .where(
                        (leverancier.c.id == lev_id)
                        & leverancier.c.juridische_entiteit.is_(None)
                    )
                    .values(juridische_entiteit=lev_entiteit)
                )

            # Stap 2 — energie_product upsert
            prod_naam = _str(prod) or ""
            ener_type = _energievorm(energie) or ""
            seg = _str(segment) or ""
            if not (prod_naam and ener_type and seg):
                continue

            # Dezelfde productidentiteit komt in veel groepen terug (één per
            # maand), dus onthouden scheelt twee rondreizen per groep.
            prod_sleutel = (lev_id, prod_naam, ener_type, seg)
            prod_id = product_cache.get(prod_sleutel)

            if prod_id is None:
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
                product_cache[prod_sleutel] = prod_id
            total_producten += 1

            # Stap 3 — bepaal meter_types in deze groep
            geldig_van = date(int(jaar) if jaar else 1970, int(maand) if maand else 1, 1)
            richting_str = _str(richting or "").lower()

            # Eén keer naar dicts: `iterrows()` bouwt per rij een Series, en
            # de lus hieronder liep de groep opnieuw door voor elk meter_type.
            # Bij vier meter_types werd dezelfde groep dus vijf keer met
            # pandas doorlopen; dat was het grootste deel van de importtijd.
            groep_rijen = groep.to_dict("records")

            meter_types_in_groep: set[str] = {"single"}
            for r in groep_rijen:
                comp_code = _str(r.get("component")) or ""
                if comp_code.lower() in METER_TYPES:
                    meter_types_in_groep.add(comp_code.lower())

            # De componentrij per code. Elk register draagt zijn eigen prijs,
            # zijn eigen formuleparameters en zijn eigen indexwaarde: bij
            # "Bolt Variabel" staat de coëfficiënt van `single` in kolom a en
            # die van `day` in kolom b, op twee verschillende rijen. Ze uit
            # `groep.iloc[0]` lezen gaf élk metertype de vector van de eerste
            # rij van de groep — meestal `green` of `fixed_fee`, die geen van
            # beide een formule dragen.
            rij_per_component: dict[str, dict[str, Any]] = {}
            for r in groep_rijen:
                code = (_str(r.get("component")) or "").lower()
                if code and code not in rij_per_component:
                    rij_per_component[code] = r

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

                # De prijs, de formule en de index van dít register.
                #
                # De energieprijs stond nooit in de databank: de code die de
                # componenten doorloopt slaat de registercodes over (ze dienen
                # als meter_type), en `_map_component_code_to_field` kende
                # alleen namen als "energieprijs" die in de brondata niet
                # voorkomen. Alle 25.937 tariefrijen hadden daardoor een lege
                # `energieprijs_kwh` — de grootste post van elke factuur.
                #
                # Bij een vast product staat de prijs in `price`. Bij een
                # variabel of dynamisch product is `price` meestal leeg en is
                # de formule de prijs; beide worden overgenomen wanneer ze er
                # zijn, zodat de databank hetzelfde draagt als
                # `DataRepository.products()` uit het CSV haalt.
                bron_rij = rij_per_component.get(meter_type)
                if bron_rij is not None:
                    prijs = _dec(bron_rij.get("price"))
                    if prijs is not None:
                        tarief_row["energieprijs_kwh"] = prijs

                    for param in ("a", "b", "c", "d", "z"):
                        val = _dec(bron_rij.get(param))
                        if val is not None:
                            tarief_row[f"param_{param}"] = val

                    # De kolommen heten `index_name_A`..`index_name_D` met een
                    # hoofdletter; met de kleine letter vond de opzoeking nooit
                    # iets en bleef ook de indexwaarde leeg. Zonder die waarde
                    # is een formule als `0,1145 x index + 1,645` onbruikbaar.
                    for idx in ("a", "b", "c", "d"):
                        naam = _str(bron_rij.get(f"index_name_{idx.upper()}"))
                        if naam:
                            tarief_row[f"index_naam_{idx}"] = naam
                        waarde = _dec(bron_rij.get(f"index_value_{idx.upper()}"))
                        if waarde is not None:
                            tarief_row[f"index_waarde_{idx}"] = waarde

                # De componenten die voor het hele product gelden (groene
                # stroom, WKK, bijdrage op de energie, vaste vergoeding).
                for comp_r in groep_rijen:
                    comp_code = _str(comp_r.get("component")) or ""
                    cc = comp_code.lower()
                    # De registercodes zijn hierboven al verwerkt, elk op hun
                    # eigen rij.
                    if cc in METER_TYPES:
                        continue

                    comp_prijs = _dec(comp_r.get("price"))

                    # Een vaste vergoeding die bij één meteropstelling hoort,
                    # geldt alleen op de rijen van die opstelling.
                    if cc in _VASTE_VERGOEDING_PER_METERTYPE:
                        if meter_type in _VASTE_VERGOEDING_PER_METERTYPE[cc]:
                            if comp_prijs is not None:
                                tarief_row["vaste_vergoeding_jaar"] = comp_prijs
                        continue
                    if cc.startswith("fixed_fee_"):
                        # Een variant waarvan we de meteropstelling niet
                        # kennen. Raden zou een verkeerd bedrag opleveren dat
                        # nergens opvalt.
                        unmapped_components.add(comp_code)
                        continue

                    field = _map_component_code_to_field(comp_code)
                    if not field:
                        unmapped_components.add(comp_code)
                        continue
                    if comp_prijs is not None:
                        tarief_row[field] = comp_prijs

                # Verzamelen in plaats van meteen schrijven: de SCD2-beslissing
                # is rekenwerk, en per rij naar de databank gaan kostte twee
                # tot vier rondreizen. Zie _scd2_bulk_upsert.
                if richting_str == "injectie":
                    injectie_rijen.append(tarief_row)
                else:
                    afname_rijen.append(tarief_row)
                total_tarieven += 1

        LOG.info("leverancier_en_product [%s]: gelezen", csv_path.name)

    LOG.info(
        "Tariefhistoriek bijwerken: %d afname- en %d injectierijen ...",
        len(afname_rijen), len(injectie_rijen),
    )
    _scd2_bulk_upsert(conn, tarief_afname, afname_rijen)
    _scd2_bulk_upsert(conn, tarief_injectie, injectie_rijen)

    if unmapped_components:
        LOG.warning("Onbekende component-codes: %s", sorted(unmapped_components))

    if onbekende_annotaties:
        LOG.warning(
            "Leveranciersnamen met een onbekende annotatie tussen haakjes: %s. "
            "Deze blijven als aparte leverancier staan; breid "
            "utility.normalizer._ANNOTATIES uit als het om dezelfde aanbieder gaat.",
            sorted(onbekende_annotaties),
        )

    LOG.info(
        "leverancier_en_product totaal: %d producten, %d tarief-snapshots",
        total_producten, total_tarieven
    )
    return ImportResult(domain="leverancier_product", rows_inserted=total_tarieven)


# ---------------------------------------------------------------------------
# SCD2 Upsert helper
# ---------------------------------------------------------------------------

def _scd2_bulk_upsert(
    conn: sa.Connection,
    tariff_table: sa.Table,
    rijen: list[dict[str, Any]],
) -> None:
    """Werk de SCD2-historiek bij voor een hele lading tariefrijen tegelijk.

    De rij-voor-rij variant deed twee tot vier queries per momentopname. Bij
    25.937 momentopnames is dat ruim 75.000 rondreizen naar de databank, en op
    een server aan de andere kant van een VPN weegt elke rondreis. De
    beslissing zelf is puur rekenwerk: welke periodes bestaan er al, welke
    komen erbij, en waar loopt de ene over in de andere.

    Werkwijze: haal de bestaande rijen voor de betrokken producten in één
    query op, bepaal per reeks (product, metertype, prijstype) de gewenste
    eindtoestand uit de vereniging van bestaande en nieuwe periodes, en schrijf
    het verschil weg met twee bulkbewerkingen.

    De semantiek is dezelfde als voorheen, inclusief de twee regels die eerder
    zijn ingevoerd: een periode die al bestaat wordt bijgewerkt in plaats van
    gedupliceerd, en een periode die ouder is dan wat er al staat zonder er te
    zijn wordt overgeslagen met een waarschuwing in plaats van de historiek
    achterstevoren te herschrijven.
    """
    bruikbaar = [
        rij for rij in rijen
        if rij.get("product_id") and rij.get("geldig_van")
    ]
    if not bruikbaar:
        return

    def sleutel(rij: dict[str, Any]) -> tuple:
        return (
            rij["product_id"],
            rij.get("meter_type", "single"),
            rij.get("prijs_type"),
        )

    product_ids = {rij["product_id"] for rij in bruikbaar}
    bestaand: dict[tuple, dict[date, int]] = {}
    for row in conn.execute(
        sa.select(
            tariff_table.c.id,
            tariff_table.c.product_id,
            tariff_table.c.meter_type,
            tariff_table.c.prijs_type,
            tariff_table.c.geldig_van,
        ).where(tariff_table.c.product_id.in_(product_ids))
    ):
        bestaand.setdefault(
            (row.product_id, row.meter_type, row.prijs_type), {}
        )[row.geldig_van] = row.id

    # Laatste rij per (reeks, periode) wint, net als bij de rij-voor-rij
    # variant waar een latere aanroep de eerdere overschreef.
    gewenst: dict[tuple, dict[date, dict[str, Any]]] = {}
    for rij in bruikbaar:
        gewenst.setdefault(sleutel(rij), {})[rij["geldig_van"]] = rij

    bij_te_werken: list[dict[str, Any]] = []
    in_te_voegen: list[dict[str, Any]] = []
    overgeslagen: list[tuple] = []

    for reeks, periodes in gewenst.items():
        al_aanwezig = bestaand.get(reeks, {})
        # De einddatum volgt uit de vereniging: een nieuwe maand sluit de
        # vorige af, ook als die al in de databank stond.
        alle_periodes = sorted(set(al_aanwezig) | set(periodes))
        opvolger = {
            periode: alle_periodes[i + 1] if i + 1 < len(alle_periodes) else None
            for i, periode in enumerate(alle_periodes)
        }
        oudste_bestaande = min(al_aanwezig) if al_aanwezig else None

        for periode, rij in sorted(periodes.items()):
            volgende = opvolger[periode]
            geldig_tot = (
                date.fromordinal(volgende.toordinal() - 1) if volgende else None
            )
            bestaande_id = al_aanwezig.get(periode)

            if bestaande_id is not None:
                bij_te_werken.append(
                    {
                        "b_id": bestaande_id,
                        **{k: v for k, v in rij.items() if k != "geldig_van"},
                        "geldig_tot": geldig_tot,
                    }
                )
                continue

            if oudste_bestaande is not None and periode < oudste_bestaande:
                # Ouder dan alles wat er staat: invoegen zou de reeks
                # achterstevoren herschrijven.
                overgeslagen.append((reeks, periode, oudste_bestaande))
                continue

            in_te_voegen.append({**rij, "geldig_tot": geldig_tot})

        # Een bestaande periode die door een nieuwere wordt opgevolgd moet
        # afgesloten worden, ook als ze zelf niet opnieuw aangeleverd is.
        for periode, bestaande_id in al_aanwezig.items():
            if periode in periodes:
                continue
            volgende = opvolger[periode]
            if volgende is None:
                continue
            bij_te_werken.append(
                {
                    "b_id": bestaande_id,
                    "geldig_tot": date.fromordinal(volgende.toordinal() - 1),
                }
            )

    for reeks, periode, oudste in overgeslagen[:5]:
        LOG.warning(
            "Overgeslagen: %s voor product %s/%s begint op %s terwijl de "
            "oudste bestaande rij op %s begint.",
            tariff_table.name, reeks[0], reeks[1], periode, oudste,
        )
    if len(overgeslagen) > 5:
        LOG.warning(
            "... en %d andere terugwerkende rijen voor %s.",
            len(overgeslagen) - 5, tariff_table.name,
        )

    # Bulkbewerkingen. De updates worden per kolomsamenstelling gegroepeerd:
    # executemany vereist dat elke rij dezelfde parameters draagt.
    per_vorm: dict[tuple, list[dict[str, Any]]] = {}
    for rij in bij_te_werken:
        per_vorm.setdefault(tuple(sorted(rij)), []).append(rij)

    for kolommen, groep in per_vorm.items():
        waarden = {k: sa.bindparam(k) for k in kolommen if k != "b_id"}
        conn.execute(
            sa.update(tariff_table)
            .where(tariff_table.c.id == sa.bindparam("b_id"))
            .values(**waarden),
            groep,
        )

    if in_te_voegen:
        per_vorm_insert: dict[tuple, list[dict[str, Any]]] = {}
        for rij in in_te_voegen:
            per_vorm_insert.setdefault(tuple(sorted(rij)), []).append(rij)
        for _, groep in per_vorm_insert.items():
            conn.execute(sa.insert(tariff_table), groep)


def _scd2_upsert(
    conn: sa.Connection,
    tariff_table: sa.Table,
    row_data: dict[str, Any],
) -> None:
    """SCD Type 2 upsert voor één tariefrij.

    Dunne schil om `_scd2_bulk_upsert`, zodat er één implementatie van de
    semantiek bestaat en de twee paden niet uiteen kunnen lopen.
    """
    _scd2_bulk_upsert(conn, tariff_table, [row_data])


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
    overgeslagen = 0

    for _, r in df_links.iterrows():
        vreg_id = _str(r.get("vreg_id"))
        matched_lev = _str(r.get("matched_handelsnaam"))
        matched_prod = _str(r.get("matched_productnaam"))
        energie_type = _str(r.get("energy"))
        segment = _str(r.get("segment"))

        if not (vreg_id and matched_lev and matched_prod):
            continue

        if not (energie_type and segment):
            # Zonder energievorm en segment is de rij niet eenduidig te
            # koppelen; overslaan is beter dan de verkeerde rij raken.
            overgeslagen += 1
            continue

        # De identiteit van een product is (leverancier, naam, energievorm,
        # segment). Matchen op naam en leverancier alleen raakte álle
        # varianten tegelijk: "Sociaal tarief" bestaat voor elektriciteit én
        # gas, en beide kregen dan dezelfde vreg_id — wat botst op de unieke
        # sleutel van energie_product.vreg_id.
        result = conn.execute(
            sa.update(energie_product)
            .where(
                (sa.func.lower(energie_product.c.product_naam) == matched_prod.lower())
                & (sa.func.lower(energie_product.c.energie_type) == energie_type.lower())
                & (sa.func.lower(energie_product.c.segment) == segment.lower())
                & (
                    sa.select(leverancier.c.id).where(
                        sa.func.lower(leverancier.c.naam) == matched_lev.lower()
                    ).correlate(leverancier).scalar_subquery()
                    == energie_product.c.leverancier_id
                )
            )
            .values(vreg_id=vreg_id)
        )
        if (result.rowcount or 0) > 1:
            # Kan niet meer voorkomen met de volledige sleutel, maar als het
            # toch gebeurt is stil doorgaan het slechtste antwoord: dan zou de
            # unieke sleutel de import alsnog opblazen, of erger, een vreg_id
            # bij het verkeerde product belanden.
            raise ValueError(
                f"vreg_id {vreg_id} matchte {result.rowcount} productrijen "
                f"({matched_lev} / {matched_prod} / {energie_type} / {segment}); "
                "er hoort er precies één te zijn."
            )
        linked_count += result.rowcount or 0

    if overgeslagen:
        LOG.warning(
            "%d koppelingen overgeslagen: energievorm of segment ontbrak in %s.",
            overgeslagen, links_csv.name,
        )
    LOG.info("energie_product_vreg_links: %d gekoppeld", linked_count)
    return ImportResult(domain="energie_product_vreg", rows_inserted=linked_count)


# Classificatie van vtest.be. GREENLOCAL is lokaal opgewekte groene stroom;
# dat onderscheid met GREEN telt voor een vergelijker en wordt daarom naast de
# boolean bewaard. Aardgas krijgt altijd NONE.
GROENE_STROOM_TYPES = {"GREEN", "GREENLOCAL"}


def import_energie_product_kenmerken(
    conn: sa.Connection, vtest_csv: Path
) -> ImportResult:
    """Vul de producteigenschappen die alleen de live scrape kent.

    De bulk-export levert de prijzen maar niet of een product groene stroom
    is; dat staat als `data-greentype` op de resultatenpagina van vtest.be.
    Die kolom bleef daardoor leeg, terwijl de gegevens wel gescrapet waren.

    Koppelt via vreg_id, dus enkel producten die `link_energie_product_vreg_ids`
    heeft kunnen matchen krijgen deze velden. Producten die alleen in de
    bulk-export voorkomen — bijvoorbeeld omdat ze niet meer aangeboden worden —
    houden NULL, wat het verschil zichtbaar houdt met "niet groen".
    """
    if not vtest_csv.is_file():
        LOG.warning("Bestand niet gevonden, overgeslagen: %s", vtest_csv)
        return ImportResult(domain="energie_product_kenmerken", rows_inserted=0)

    df = pd.read_csv(vtest_csv, sep=_SEP, dtype=str, encoding=_ENC).fillna("")

    # Eén rij per product: hetzelfde contract komt per postcode terug, maar de
    # producteigenschappen verschillen daar niet. Per veld aanvullen wat leeg
    # is, want niet elke combinatie draagt alles (het sociaal tarief heeft
    # bijvoorbeeld geen eigen tariefkaart).
    per_vreg: dict[str, dict[str, str]] = {}
    for rij in df.to_dict("records"):
        vreg_id = _str(rij.get("vreg_id"))
        if not vreg_id:
            continue
        bron = {
            "green_type": (_str(rij.get("green_type")) or "").upper(),
            "link_tariefkaart": _str(rij.get("link_tariefkaart")) or "",
            "link_voorwaarden": _str(rij.get("link_voorwaarden")) or "",
        }
        doel = per_vreg.setdefault(vreg_id, {"green_type": "", "link_tariefkaart": "", "link_voorwaarden": ""})
        for sleutel, waarde in bron.items():
            if waarde and not doel[sleutel]:
                doel[sleutel] = waarde

    bijgewerkt = 0
    for vreg_id, velden in per_vreg.items():
        soort = velden["green_type"]
        waarden: dict[str, Any] = {}
        if soort:
            waarden["groene_stroom"] = soort in GROENE_STROOM_TYPES
            waarden["groene_stroom_type"] = soort
        # De tariefkaart en de algemene voorwaarden komen uit het detailpaneel
        # van vtest.be. Die stonden hier nooit: deze functie vulde alleen het
        # groene-stroomtype, waardoor `tariefkaart_url` en
        # `bijzondere_voorwaarden_url` op alle 686 producten leeg bleven ook
        # nadat de scrape ze wél binnenhaalde.
        #
        # Een leeg veld overschrijft niets: een run zonder detailpanelen mag
        # een eerder opgehaalde link niet wissen (zelfde regel als bij
        # `vtest_contract`).
        if velden["link_tariefkaart"]:
            waarden["tariefkaart_url"] = velden["link_tariefkaart"]
        if velden["link_voorwaarden"]:
            waarden["bijzondere_voorwaarden_url"] = velden["link_voorwaarden"]
        if not waarden:
            continue
        resultaat = conn.execute(
            sa.update(energie_product)
            .where(energie_product.c.vreg_id == vreg_id)
            .values(**waarden)
        )
        bijgewerkt += resultaat.rowcount or 0

    LOG.info(
        "energie_product_kenmerken: %d producten bijgewerkt (%d unieke vreg_ids)",
        bijgewerkt, len(per_vreg),
    )
    return ImportResult(domain="energie_product_kenmerken", rows_inserted=bijgewerkt)


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

# De velden die samen "de beschrijving van dit contract" vormen. Wijzigt er
# hier iets, dan is dat een nieuw snapshot waard; `laatst_gezien_*` en de
# tijdas zelf horen er dus niet bij.
_CONTRACT_INHOUD = tuple(
    c.name for c in vtest_contract.columns
    if c.name not in (
        "id", "vreg_id", "geldig_van", "geldig_tot", "gepubliceerd_op",
        "laatst_gezien_versie", "laatst_gezien_op",
    )
)


def _scd2_contract_snapshots(
    conn: sa.Connection, contract_rows: list[dict[str, Any]]
) -> int:
    """Schrijf de contractmetadata als tijdreeks weg (SCD2 op de scrapedatum).

    Er komt alleen een nieuw snapshot bij wanneer de beschrijving werkelijk
    wijzigt. Zonder die regel zou elke scrape 355 rijen toevoegen en zou de
    tabel binnen een jaar honderdduizenden rijen tellen zonder één extra feit.

    Afwezigheid geldt niet als wijziging: een run zonder detailpanelen levert
    lege velden, en die mogen noch de bestaande metadata overschrijven, noch
    een nieuw snapshot uitlokken. Een leeg veld valt terug op wat er stond;
    draagt de nieuwe rij iets dat er nog niet was, dan vult dat het huidige
    snapshot aan in plaats van er een nieuw naast te zetten — het is dezelfde
    waarneming, alleen vollediger.
    """
    if not contract_rows:
        return 0

    vreg_ids = [r["vreg_id"] for r in contract_rows]
    bestaand: dict[str, dict[str, Any]] = {}
    for rij in conn.execute(
        sa.select(vtest_contract).where(
            vtest_contract.c.vreg_id.in_(vreg_ids)
            & vtest_contract.c.geldig_tot.is_(None)
        )
    ).mappings():
        bestaand[rij["vreg_id"]] = dict(rij)

    in_te_voegen: list[dict[str, Any]] = []
    for rij in contract_rows:
        vreg_id = rij["vreg_id"]
        scrape_datum = rij.pop("_scrape_datum", None)
        if scrape_datum is None:
            # Zonder scrapedatum is er geen tijdas om op te ankeren. Raden zou
            # het snapshot op de verkeerde dag zetten.
            LOG.warning(
                "Contract %s heeft geen scraped_at; overgeslagen voor de "
                "contracthistoriek.", vreg_id,
            )
            continue

        huidig = bestaand.get(vreg_id)
        inhoud = {k: rij.get(k) for k in _CONTRACT_INHOUD}

        if huidig is None:
            in_te_voegen.append({
                **inhoud,
                "vreg_id": vreg_id,
                "geldig_van": scrape_datum,
                "geldig_tot": None,
                "laatst_gezien_versie": rij["laatst_gezien_versie"],
                "laatst_gezien_op": rij["laatst_gezien_op"],
            })
            continue

        # Leeg overschrijft niets: het effectieve snapshot is de nieuwe waarde
        # waar die er is, en anders wat er stond.
        effectief = {
            k: (v if _heeft_waarde(v) else huidig.get(k)) for k, v in inhoud.items()
        }
        gewijzigd = any(effectief[k] != huidig.get(k) for k in _CONTRACT_INHOUD)

        if not gewijzigd or scrape_datum <= huidig["geldig_van"]:
            # Ongewijzigd, of een waarneming van dezelfde dag of ouder: het
            # bestaande snapshot bijwerken. Een oudere scrape mag de tijdas
            # niet terugdraaien, maar mag wel gaten vullen.
            conn.execute(
                sa.update(vtest_contract)
                .where(vtest_contract.c.id == huidig["id"])
                .values(
                    **effectief,
                    laatst_gezien_versie=rij["laatst_gezien_versie"],
                    laatst_gezien_op=rij["laatst_gezien_op"],
                )
            )
            continue

        # Echt gewijzigd en nieuwer: het lopende snapshot afsluiten op de dag
        # vóór de nieuwe waarneming, en een nieuw snapshot openen.
        conn.execute(
            sa.update(vtest_contract)
            .where(vtest_contract.c.id == huidig["id"])
            .values(geldig_tot=date.fromordinal(scrape_datum.toordinal() - 1))
        )
        in_te_voegen.append({
            **effectief,
            "vreg_id": vreg_id,
            "geldig_van": scrape_datum,
            "geldig_tot": None,
            "laatst_gezien_versie": rij["laatst_gezien_versie"],
            "laatst_gezien_op": rij["laatst_gezien_op"],
        })

    if in_te_voegen:
        conn.execute(sa.insert(vtest_contract), in_te_voegen)
    return len(in_te_voegen)


def _heeft_waarde(waarde: Any) -> bool:
    """Leeg is "niets waargenomen", niet "de waarde is leeg".

    False is wél een waarde (grayedout/complex_product), dus een simpele
    waarheidstoets zou die als afwezig lezen.
    """
    if waarde is None:
        return False
    if isinstance(waarde, str):
        return waarde.strip() != ""
    return True


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

    # Eén rij per contract, over alle segment/energie/postcode-combinaties
    # heen. Niet "de eerste wint": bij een hervatte matrixrun kan de eerste
    # combinatie nog van vóór de contractdetails komen en de latere wél
    # gevuld zijn. Er wordt daarom per veld aangevuld wat leeg is.
    contract_per_vreg_id: dict[str, dict[str, Any]] = {}
    prijs_rows = []

    for _, r in df.iterrows():
        vreg_id = _str(r.get("vreg_id")) or ""
        if not vreg_id:
            continue

        # De scrapedatum is de tijdas van dit contract: vanaf wanneer deze
        # metadata bij vtest.be zo stond.
        gescrapet = _ts(r.get("scraped_at"))
        rij = {
            "vreg_id": vreg_id,
            "_scrape_datum": gescrapet.date() if gescrapet is not None else None,
            "leverancier_raw": _str(r.get("supplier_raw")) or "",
            "product_raw": _str(r.get("product_raw")) or "",
            "energie_type": _energievorm(r.get("energy")),
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
        }
        bestaand = contract_per_vreg_id.get(vreg_id)
        if bestaand is None:
            contract_per_vreg_id[vreg_id] = rij
        else:
            for sleutel, waarde in rij.items():
                if sleutel == "_scrape_datum":
                    # De vroegste waarneming in deze run bepaalt de tijdas.
                    if waarde and (not bestaand.get(sleutel) or waarde < bestaand[sleutel]):
                        bestaand[sleutel] = waarde
                elif not bestaand.get(sleutel) and waarde:
                    bestaand[sleutel] = waarde

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

    contract_rows = list(contract_per_vreg_id.values())
    nieuwe_snapshots = _scd2_contract_snapshots(conn, contract_rows)

    # Insert prijzen
    if prijs_rows:
        stmt = sa.dialects.postgresql.insert(vtest_postcode_prijs).values(prijs_rows)
        stmt = stmt.on_conflict_do_nothing(constraint="uq_vtest_postcode_prijs")
        conn.execute(stmt)

    total = len(contract_rows) + len(prijs_rows)
    LOG.info(
        "vtest: %d contracten (%d nieuwe snapshots), %d prijsrijen",
        len(contract_rows), nieuwe_snapshots, len(prijs_rows),
    )
    return ImportResult(domain="vtest_postcode_prijs", rows_inserted=total)


# ---------------------------------------------------------------------------
# Netbeheerder Tarieve (SCD2)
# ---------------------------------------------------------------------------

def import_netbeheerder_tarieven(
    conn: sa.Connection,
    tariff_dir: Path,
    jaar: int,
    version_id: str | None = None,
) -> ImportResult:
    """Importeer netbeheerder-tarieven met SCD2.

    `version_id` is de bronversie waaruit deze tarieven komen en wordt op elke
    rij vastgelegd. `source_sheet`/`source_row` zeggen wáár in een werkboek een
    rij stond, niet uit wélk werkboek — en met meerdere tariefjaren naast elkaar
    is dat het verschil tussen data die klopt en data die herbouwbaar is.
    """
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
        # VREG stelt de distributienettarieven per kalenderjaar vast, dus een
        # tariefjaar loopt af op 31 december. `geldig_tot = NULL` liet elke
        # rij "nog lopend" heten en zou een berekening over 2027 stil met de
        # tarieven van 2026 laten rekenen — dezelfde stille-verkeerde-waarde
        # als de accijnzen die na hun laatste ingangsdatum doorrekenen.
        #
        # Inclusieve einddatum (31 december, niet 1 januari): dat is de
        # conventie die deze tabel al hanteert, waar een voorganger afgesloten
        # wordt op `geldig_van - 1 dag`. De half-open conventie in de
        # commentaar bij `schema.py` geldt voor de gebruikerstabellen uit
        # migratie 0017, een andere familie.
        geldig_tot = date(jaar, 12, 31)

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
                # Leeg wordt "" en niet None: de notering zit in de unieke
                # sleutel, en PostgreSQL ziet NULLs daarin als onderling
                # verschillend — een echt dubbel zou er dan alsnog in mogen.
                "tariefnotering": _str(r.get("Tariefnotering")) or "",
                "prijs": prijs,
                "geldig_van": geldig_van,
                "geldig_tot": geldig_tot,
                "source_sheet": _str(r.get("source_sheet")),
                "source_row": _int(r.get("source_row")),
                "bron_versie": version_id,
            }
            _scd2_upsert_netbeheerder(conn, row_data)
            total += 1

    LOG.info("netbeheerder_tarief: %d rijen", total)
    return ImportResult(domain="netbeheerder_tarief", rows_inserted=total)


def _scd2_upsert_netbeheerder(conn: sa.Connection, row_data: dict[str, Any]) -> None:
    """SCD2-upsert voor netbeheerder_tarief.

    De "huidige" rij wordt gezocht op de hoogste `geldig_van` voor de sleutel,
    niet op `geldig_tot IS NULL`. Dat laatste werkte zolang elke rij open
    stond, maar sinds een tariefjaar op 31 december afgesloten wordt is er
    geen open rij meer: de opzoeking vond dan niets, viel door naar de insert
    onderaan, en die botste op `uq_netbeheerder_tarief`. Een herimport van
    dezelfde versie liep zo stuk met een IntegrityError.

    De uniciteit hangt daardoor volledig aan `uq_netbeheerder_tarief` (de
    volledige sleutel plus `geldig_van`); de partiële index
    `ix_netbeheerder_tarief_open` bewaakte alleen open rijen en is met
    migratie 0018 geschrapt.
    """
    netbeheerder_code = row_data.get("netbeheerder_code")
    energie_type = row_data.get("energie_type")
    contract_richting = row_data.get("contract_richting")
    klanttype = row_data.get("klanttype")
    tarieftype = row_data.get("tarieftype")
    tariefdetail = row_data.get("tariefdetail")
    tariefnotering = row_data.get("tariefnotering") or ""
    geldig_van = row_data.get("geldig_van")

    if not all([netbeheerder_code, energie_type, contract_richting, klanttype, geldig_van]):
        return

    # De notering hoort bij de sleutel: dezelfde tariefnaam komt voor met
    # verschillende eenheden (bij FA staat het prosumententarief zowel als
    # 51,54 EUR/kW/jaar als 1,8984501 zonder eenheid). Zonder de notering zou
    # de ene versie als de vorige rij van de andere gelden en die afsluiten —
    # een tariefhistoriek die zichzelf overschrijft.
    sleutel = (
        (netbeheerder_tarief.c.netbeheerder_code == netbeheerder_code)
        & (netbeheerder_tarief.c.energie_type == energie_type)
        & (netbeheerder_tarief.c.contract_richting == contract_richting)
        & (netbeheerder_tarief.c.klanttype == klanttype)
        & (netbeheerder_tarief.c.tarieftype == tarieftype)
        & (netbeheerder_tarief.c.tariefdetail == tariefdetail)
        & (netbeheerder_tarief.c.tariefnotering == tariefnotering)
    )
    bestaand = conn.execute(
        sa.select(
            netbeheerder_tarief.c.id,
            netbeheerder_tarief.c.geldig_van,
            netbeheerder_tarief.c.geldig_tot,
        ).where(sleutel).order_by(netbeheerder_tarief.c.geldig_van)
    ).all()

    # Zelfde periode: bijwerken in plaats van een nieuwe historiekrij. Blind
    # afsluiten en invoegen liet een herimport van dezelfde versie stuklopen op
    # de unieke sleutel.
    for rij_id, rij_van, _ in bestaand:
        if rij_van == geldig_van:
            conn.execute(
                sa.update(netbeheerder_tarief)
                .where(netbeheerder_tarief.c.id == rij_id)
                .values(**{k: v for k, v in row_data.items() if k != "geldig_van"})
            )
            return

    # Een oudere jaargang bijladen moet kunnen. De eerste vorm van deze functie
    # sloeg zo'n rij over ("begint op 2025-01-01 terwijl de laatste rij al op
    # 2026-01-01 begint"), wat terugwerkend herschrijven voorkwam maar ook
    # verhinderde om het tariefjaar 2025 alsnog in te laden — en zonder dat jaar
    # is een factuur die de jaarwissel kruist niet uit de databank te berekenen.
    #
    # De rij wordt daarom op haar plaats in de reeks gezet: de voorganger sluit
    # af op de dag ervóór, en de nieuwe rij loopt tot de dag vóór haar opvolger.
    vorige = [r for r in bestaand if r[1] < geldig_van]
    volgende = [r for r in bestaand if r[1] > geldig_van]

    if vorige:
        vorige_id, _, vorige_tot = vorige[-1]
        vorige_dag = date.fromordinal(geldig_van.toordinal() - 1)
        if vorige_tot is None or vorige_tot > vorige_dag:
            conn.execute(
                sa.update(netbeheerder_tarief)
                .where(netbeheerder_tarief.c.id == vorige_id)
                .values(geldig_tot=vorige_dag)
            )

    if volgende:
        grens = date.fromordinal(volgende[0][1].toordinal() - 1)
        huidig_tot = row_data.get("geldig_tot")
        if huidig_tot is None or huidig_tot > grens:
            row_data = {**row_data, "geldig_tot": grens}

    conn.execute(sa.insert(netbeheerder_tarief).values(**row_data))


# ---------------------------------------------------------------------------
# Overheidsheffingen
# ---------------------------------------------------------------------------

def import_nettarief_transport(conn: sa.Connection, config_dir: Path) -> ImportResult:
    """Importeer de vervoerstarieven uit config/nettarieven/.

    `config_dir` is de map met de tariefbestanden zelf — `config/nettarieven/`.

    Faalt hard, om dezelfde reden als de heffingen: een gasfactuur zonder
    vervoerstarief is per definitie ongeveer 25 EUR per jaar te laag, en dat
    hoort niet met een waarschuwing weggeschreven te worden.
    """
    from energie_vlaanderen.nettarieven.transport import TransportTariefRepository

    repo = TransportTariefRepository.load(config_dir)

    # Masterdata zonder version_id: bij elke import wordt de volledige set
    # vervangen door wat er nu in config/nettarieven/ staat.
    conn.execute(sa.delete(nettarief_transport))

    rijen = [
        {
            "energievorm": tarief.energievorm,
            "klantcategorie": tarief.klantcategorie,
            "eur_per_kwh": tarief.eur_per_kwh,
            "geldig_vanaf": tarief.geldig_vanaf,
            "geverifieerd": tarief.geverifieerd,
            "bron": tarief.bron or "onbekend",
        }
        for tarief in repo.tarieven()
    ]
    if not rijen:
        raise ValueError(
            f"Geen vervoerstarieven gevonden in {config_dir}; "
            "een databank zonder vervoerstarief rekent elke gasfactuur te laag."
        )

    conn.execute(sa.insert(nettarief_transport), rijen)
    LOG.info("nettarief_transport: %d rijen", len(rijen))
    return ImportResult(domain="nettarief_transport", rows_inserted=len(rijen))


def import_overheidsheffingen(conn: sa.Connection, config_dir: Path) -> ImportResult:
    """Importeer heffingen naar de databank.

    `config_dir` is de map met de heffingenbestanden zelf — `config/heffingen/`,
    niet `config/`.

    Deze functie faalt hard. Ze deed dat niet: elk blok stond in een
    `try/except` die de fout naar een LOG.warning schreef en daarna een
    succesvolle ImportResult teruggaf. Een mislukte accijnsinsert leverde zo
    een databank zonder accijnzen op, met een groene melding erboven — precies
    het patroon dat een verkeerd tarief jarenlang onopgemerkt liet.

    De heffingen zijn de kern van de factuur en de databank is het eindstation;
    een onvolledige import hoort de hele transactie terug te draaien.
    """
    heffingenrepo = HeffingenRepository.load(config_dir)

    # Heffingen zijn masterdata zonder version_id: bij elke import wordt de
    # volledige set vervangen door wat er nu in config/heffingen/ staat.
    conn.execute(sa.delete(overheidsheffing_btw))
    conn.execute(sa.delete(overheidsheffing_energiefonds))
    conn.execute(sa.delete(overheidsheffing_accijns_schijf))

    total = 0

    accijns_rows = [
        {
            "energievorm": tabel.energievorm,
            "klantcategorie": schijf.klantcategorie,
            "van_mwh": schijf.van_mwh,
            "tot_mwh": schijf.tot_mwh,
            "accijns_eur_mwh": schijf.accijns_eur_mwh,
            "bijzondere_accijns_eur_mwh": schijf.bijzondere_accijns_eur_mwh,
            "energiebijdrage_eur_mwh": schijf.energiebijdrage_eur_mwh,
            # Zonder de ingangsdatum slaat de tabel de regimes plat: 46,00 en
            # 47,4811 EUR/MWh zouden niet meer uit elkaar te houden zijn.
            "geldig_vanaf": schijf.geldig_vanaf,
            "geverifieerd": schijf.geverifieerd,
            # De schijf draagt een preciezere bronvermelding dan het bestand:
            # per regime staat er hoe dat cijfer gecontroleerd is.
            "bron": schijf.bron or tabel.bron or "onbekend",
        }
        for tabel in heffingenrepo.accijns_tabellen().values()
        for schijf in tabel.schijven
    ]
    if not accijns_rows:
        raise ValueError(
            f"Geen accijnsschijven gevonden in {config_dir}; "
            "een databank zonder accijnzen rekent elke factuur te laag."
        )
    conn.execute(sa.insert(overheidsheffing_accijns_schijf), accijns_rows)
    total += len(accijns_rows)

    energiefonds_rows = [
        {
            "jaar": tarief.jaar,
            "spanningsniveau": tarief.spanningsniveau,
            "klantcategorie": tarief.klantcategorie or "",
            "eur_per_maand": tarief.eur_per_maand,
            "bron": tarief.bron or "onbekend",
        }
        for tarief in heffingenrepo.energiefonds_tarieven()
    ]
    if energiefonds_rows:
        conn.execute(sa.insert(overheidsheffing_energiefonds), energiefonds_rows)
        total += len(energiefonds_rows)

    btw_rows = [
        {
            "component": tarief.component,
            "percentage": tarief.percentage,
            "vrijgesteld": tarief.vrijgesteld,
            "geldig_vanaf": tarief.geldig_vanaf,
            "bron": tarief.bron or "onbekend",
        }
        for tarief in heffingenrepo.btw_tarieven()
    ]
    if btw_rows:
        conn.execute(sa.insert(overheidsheffing_btw), btw_rows)
        total += len(btw_rows)

    LOG.info(
        "overheidsheffing: %d rijen (%d accijnsschijven, %d energiefonds, %d btw)",
        total, len(accijns_rows), len(energiefonds_rows), len(btw_rows),
    )
    return ImportResult(domain="overheidsheffing", rows_inserted=total)


# ---------------------------------------------------------------------------
# Verbruiksprofielen (Synergrid: SLP-EX, RLP0N, SPP)
# ---------------------------------------------------------------------------

# Bestandsnaam -> (profiel_type, energie_type). energie_type "" i.p.v. None:
# zie de toelichting bij verbruiksprofiel_waarde in schema.py — NULL in de
# unieke sleutel zou de ON CONFLICT-upsert breken.
_PROFIEL_BESTANDSVOORVOEGSELS: dict[str, tuple[str, str]] = {
    "slp_ex": ("slp_ex", ""),
    "rlp0n_elektriciteit": ("rlp0n", "elektriciteit"),
    "rlp0n_gas": ("rlp0n", "gas"),
    "spp": ("spp", ""),
}

# PostgreSQL/psycopg staat maximaal 65.535 bind-parameters per query toe.
# Bij 8 kolommen per rij is dat hooguit 8.191 rijen per multi-row INSERT —
# 10.000 (8 x 10.000 = 80.000 parameters) liep hier stuk op een echte
# databank met "number of parameters must be between 0 and 65535", een fout
# die tegen SQLite of via offline SQL-compilatie niet zichtbaar wordt.
_PROFIELEN_CHUNK_SIZE = 5_000

# Sentinel-netbeheerder voor "geen netbeheerder van toepassing" (de
# nationale profielen SLP-EX/RLP0N-gas/SPP). Aangemaakt door migratie 0016;
# hier nogmaals als on_conflict_do_nothing-vangnet voor een databank die
# deze rij om een andere reden nog niet heeft.
_GEEN_NETBEHEERDER_CODE = ""


def _profiel_meta_uit_bestandsnaam(bestandsnaam: str) -> tuple[str, str, int]:
    """Leid (profiel_type, energie_type, jaar) af uit bv. 'rlp0n_gas_2026.csv'."""
    stem = Path(bestandsnaam).stem
    for voorvoegsel, (profiel_type, energie_type) in _PROFIEL_BESTANDSVOORVOEGSELS.items():
        prefix = f"{voorvoegsel}_"
        if stem.startswith(prefix) and stem[len(prefix):].isdigit():
            return profiel_type, energie_type, int(stem[len(prefix):])
    raise ValueError(
        f"Onbekend profielenbestand: {bestandsnaam!r} — verwacht "
        f"'<{'|'.join(_PROFIEL_BESTANDSVOORVOEGSELS)}>_<jaar>.csv'."
    )


# ---------------------------------------------------------------------------
# Marktcurves (VREG-prijscurves)
# ---------------------------------------------------------------------------

_CURVES_CHUNK_SIZE = 5_000

# Het werkboek noemt de energievorm in vier vormen door elkaar: één letter
# ("E"/"G"), voluit, als voorvoegsel van een marktplaats ("Gas TTF", "Gas ZTP")
# en met een achtervoegsel voor de richting ("Elektriciteit_Injectie"). Zonder
# normalisatie belanden die alle vier als aparte energie_type-waarde in de
# databank en levert een filter op "gas" niets op.
_ENERGIE_UIT_CURVES = {"e": "elektriciteit", "g": "gas"}


# De energievorm wordt in kleine letters opgeslagen. De V-test-export schrijft
# "Elektriciteit" en "Gas" met hoofdletter, de tarief- en curvebestanden zonder,
# en zo belandden beide schrijfwijzen in de databank: `energie_product` en
# `vtest_contract` met hoofdletter, `netbeheerder_tarief`, `marktcurve` en
# `verbruiksprofiel_waarde` zonder. Een join tussen die twee families op
# `energie_type` gaf daardoor stil nul rijen — geen fout, geen resultaat.
#
# Kleine letters, omdat `EnergieType` in het domeinmodel dat al is
# ("elektriciteit" / "gas") en omdat drie van de vijf tabellen het al zo deden.
_ENERGIEVORMEN = {"elektriciteit", "gas"}


def _energievorm(waarde: Any) -> str | None:
    """Normaliseer de energievorm naar de schrijfwijze van het domeinmodel."""
    tekst = _str(waarde)
    if tekst is None:
        return None
    klein = tekst.casefold()
    if klein in _ENERGIEVORMEN:
        return klein
    # Een onbekende vorm wordt niet geraden maar ruw doorgegeven, zodat ze
    # opvalt in `db audit` in plaats van stil als elektriciteit door te gaan.
    return tekst


def _curve_energie(waarde: Any) -> str | None:
    tekst = (_str(waarde) or "").strip().lower()
    if not tekst:
        return None
    if tekst in _ENERGIE_UIT_CURVES:
        return _ENERGIE_UIT_CURVES[tekst]
    if "elektriciteit" in tekst:
        return "elektriciteit"
    if "gas" in tekst or "ttf" in tekst or "ztp" in tekst:
        return "gas"
    # Liever de ruwe waarde dan een gok: een onbekende vorm hoort op te
    # vallen, niet stil als elektriciteit door te gaan.
    return _str(waarde)


def import_marktcurves(conn: sa.Connection, bron_dir: Path, version_id: str) -> ImportResult:
    """Importeer de gestagede VREG-prijscurves naar `marktcurve`.

    `curves/` werd wel geparsed maar nooit ingelezen: de tabel stond leeg
    terwijl de CSV's al maanden in staging klaarstonden.

    De drie bestanden dragen verschillende vormen en gaan op één generieke
    tabel:

    - `curves_spot.csv` — één waarde per groep/parameter, zonder tijdstip.
    - `curves_forward.csv` — per datum en energievorm twee waarden, voor
      afname en teruglevering. Die worden twee rijen, uit elkaar gehouden
      door `groep`; ze in één rij persen zou een van beide laten vallen.
    - `curves_timeseries.csv` — de eigenlijke tijdreeksen (~132.000 rijen),
      met het curvetype in de data zelf (EPC, ...).

    Er is bewust geen unieke sleutel en dus geen ON CONFLICT: de natuurlijke
    sleutel zou `datum` en `tijdstip` moeten bevatten, en die zijn per
    bestandsvorm afwisselend NULL — PostgreSQL ziet NULLs in een unieke
    sleutel als onderling verschillend, waardoor een echt duplicaat er alsnog
    in mag (dezelfde valkuil als `netbeheerder_tarief.tariefnotering`). In de
    plaats daarvan wordt alles van deze versie eerst verwijderd: een versie
    levert de curves in hun geheel, niet aanvullend.
    """
    curves_dir = bron_dir / "curves"
    if not curves_dir.is_dir():
        LOG.info("Geen curves/-map in %s, overgeslagen.", bron_dir)
        return ImportResult(domain="marktcurve", rows_inserted=0)

    verwijderd = conn.execute(
        sa.delete(marktcurve).where(marktcurve.c.version_id == version_id)
    ).rowcount
    if verwijderd:
        LOG.info("marktcurve: %d bestaande rijen van deze versie verwijderd.", verwijderd)

    totaal = 0
    totaal += _import_curves_spot(conn, curves_dir / "curves_spot.csv", version_id)
    totaal += _import_curves_forward(conn, curves_dir / "curves_forward.csv", version_id)
    totaal += _import_curves_timeseries(conn, curves_dir / "curves_timeseries.csv", version_id)

    LOG.info("marktcurve: %d rijen", totaal)
    return ImportResult(domain="marktcurve", rows_inserted=totaal)


def _schrijf_curverijen(conn: sa.Connection, rijen: list[dict[str, Any]]) -> int:
    """Schrijft in stukken weg, zoals de profielenimport, zodat een reeks van
    honderdduizenden rijen niet als één statement de databank in moet."""
    geschreven = 0
    for start in range(0, len(rijen), _CURVES_CHUNK_SIZE):
        blok = rijen[start:start + _CURVES_CHUNK_SIZE]
        conn.execute(sa.insert(marktcurve), blok)
        geschreven += len(blok)
    return geschreven


def _import_curves_spot(conn: sa.Connection, csv_path: Path, version_id: str) -> int:
    if not csv_path.is_file():
        return 0
    df = pd.read_csv(csv_path, sep=_SEP, dtype=str, encoding=_ENC).fillna("")
    rijen = []
    for _, r in df.iterrows():
        waarde = _dec(r.get("Waarde"))
        if waarde is None:
            continue
        groep = _str(r.get("Groep"))
        rijen.append({
            "version_id": version_id,
            "curve_type": "spot",
            # De groep draagt de energievorm ("Elektriciteit - afname"); die
            # blijft staan zoals ze is en wordt er ook uit afgeleid.
            "energie_type": _curve_energie((groep or "").split(" - ")[0]),
            "groep": groep,
            "parameter": _str(r.get("Parameter")),
            "datum": None,
            "tijdstip": None,
            "waarde": waarde,
            "source_sheet": _str(r.get("SourceSheet")),
        })
    return _schrijf_curverijen(conn, rijen)


def _import_curves_forward(conn: sa.Connection, csv_path: Path, version_id: str) -> int:
    if not csv_path.is_file():
        return 0
    df = pd.read_csv(csv_path, sep=_SEP, dtype=str, encoding=_ENC).fillna("")
    rijen = []
    for _, r in df.iterrows():
        tijdstip = _ts(r.get("Datum"))
        basis = {
            "version_id": version_id,
            "curve_type": "forward",
            "energie_type": _curve_energie(r.get("Energietype")),
            "parameter": _str(r.get("Indexatieparameter")),
            "datum": tijdstip.date() if tijdstip is not None else None,
            "tijdstip": None,
            "source_sheet": _str(r.get("SourceSheet")),
        }
        # Twee waarden per bronrij: afname en teruglevering zijn aparte
        # grootheden en krijgen elk een rij.
        for kolom, groep in (("Afname_VNR", "afname"), ("Teruglevering_VNR", "teruglevering")):
            waarde = _dec(r.get(kolom))
            if waarde is None:
                continue
            rijen.append({**basis, "groep": groep, "waarde": waarde})
    return _schrijf_curverijen(conn, rijen)


def _import_curves_timeseries(conn: sa.Connection, csv_path: Path, version_id: str) -> int:
    if not csv_path.is_file():
        return 0
    df = pd.read_csv(csv_path, sep=_SEP, dtype=str, encoding=_ENC).fillna("")
    rijen: list[dict[str, Any]] = []
    geschreven = 0
    for _, r in df.iterrows():
        waarde = _dec(r.get("Waarde"))
        tijdstip = _ts(r.get("Timestamp"))
        if waarde is None or tijdstip is None:
            continue
        rijen.append({
            "version_id": version_id,
            "curve_type": _str(r.get("CurveType")) or "tijdreeks",
            "energie_type": _curve_energie(r.get("EnergyType")),
            "groep": _str(r.get("Variant")),
            "parameter": _str(r.get("Resolution")),
            "datum": tijdstip.date(),
            "tijdstip": tijdstip,
            "waarde": waarde,
            "source_sheet": _str(r.get("SourceSheet")),
        })
        # Meteen wegschrijven per blok i.p.v. eerst alle ~132.000 rijen in
        # het geheugen op te bouwen — zelfde reden als bij de profielen.
        if len(rijen) >= _CURVES_CHUNK_SIZE:
            geschreven += _schrijf_curverijen(conn, rijen)
            rijen = []
    geschreven += _schrijf_curverijen(conn, rijen)
    return geschreven


def import_verbruiksprofielen(conn: sa.Connection, bron_dir: Path, version_id: str) -> ImportResult:
    """Importeer de gestagede Synergrid-profielen-CSV's naar de databank.

    `bron_dir` is de map met de verwerkte CSV's — `versions/<id>/` of
    `staging/<id>/`, net als de andere import_*-functies. Optioneel: een
    versie zonder `profielen/`-submap (bv. omdat enkel vtest/tariffs/curves
    verwerkt zijn) levert gewoon 0 geïmporteerde rijen op, geen fout — dit
    is de enige dataset die niet bij elke versie hoort te bestaan.
    """
    profielen_dir = bron_dir / "profielen"
    if not profielen_dir.is_dir():
        LOG.info("Geen profielen/-map in %s, overgeslagen.", bron_dir)
        return ImportResult(domain="verbruiksprofiel_waarde", rows_inserted=0)

    csv_paths = sorted(p for p in profielen_dir.glob("*.csv"))
    if not csv_paths:
        return ImportResult(domain="verbruiksprofiel_waarde", rows_inserted=0)

    conn.execute(
        sa.dialects.postgresql.insert(netbeheerder)
        .values(code=_GEEN_NETBEHEERDER_CODE, naam="(nationaal, geen netbeheerder)")
        .on_conflict_do_nothing(index_elements=["code"])
    )

    totaal = 0
    for csv_path in csv_paths:
        totaal += _import_een_profielenbestand(conn, csv_path, version_id)

    LOG.info("verbruiksprofiel_waarde: %d rijen uit %d bestand(en)", totaal, len(csv_paths))
    return ImportResult(domain="verbruiksprofiel_waarde", rows_inserted=totaal)


def _import_een_profielenbestand(conn: sa.Connection, csv_path: Path, version_id: str) -> int:
    profiel_type, energie_type, jaar = _profiel_meta_uit_bestandsnaam(csv_path.name)
    df = pd.read_csv(csv_path, sep=_SEP, dtype=str, encoding=_ENC).fillna("")
    if df.empty:
        return 0

    # Netbeheerders die deze CSV meebrengt en nog geen rij hebben, eerst
    # zaaien/aanvullen met hun GLN — anders faalt de FK op
    # verbruiksprofiel_waarde. _dnb_code() hergebruikt de bestaande
    # Vlaamse code (bv. "Fluvius Antwerpen" -> "FA") wanneer die naam al in
    # DNB_CODES voorkomt, en valt anders terug op de volledige naam als
    # code — precies wat import_gemeente ook al doet.
    unieke_nb = (
        df[df["netbeheerder_gln"] != ""][["netbeheerder_gln", "netbeheerder_naam"]]
        .drop_duplicates()
    )
    code_by_gln: dict[str, str] = {}
    if not unieke_nb.empty:
        nb_rows = []
        for _, r in unieke_nb.iterrows():
            gln = r["netbeheerder_gln"]
            naam = r["netbeheerder_naam"] or gln
            code = _dnb_code(naam)
            code_by_gln[gln] = code
            nb_rows.append({"code": code, "naam": naam, "gln": gln})

        # `gln` draagt een UNIQUE-constraint (migratie 0016). Zou Synergrid
        # ooit een netbeheerder een nieuwe GLN geven onder dezelfde naam
        # (dus dezelfde afgeleide `code`), dan botst deze upsert met de rij
        # die de oude GLN nog draagt — een IntegrityError die de hele import
        # terugdraait. Dat is met opzet geen stille aanname: de code kent
        # geen "welke GLN is de juiste" en hoort dat ook niet te gokken.
        stmt = sa.dialects.postgresql.insert(netbeheerder).values(nb_rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=["code"],
            set_={"gln": stmt.excluded.gln, "bijgewerkt_op": sa.func.now()},
        )
        conn.execute(stmt)

    # itertuples i.p.v. iterrows, en de batch in stukken van
    # _PROFIELEN_CHUNK_SIZE meteen wegschrijven i.p.v. eerst alle ~770.000
    # rijen (RLP0N-elektriciteit) als dict op te bouwen: dat laatste piekte
    # op 1-2 GB voor niets, terwijl enkel de write al gechunkt was.
    totaal = 0
    batch: list[dict] = []
    for r in df.itertuples(index=False):
        gln = r.netbeheerder_gln or None
        batch.append(
            {
                "version_id": version_id,
                "profiel_type": profiel_type,
                "energie_type": energie_type,
                "jaar": jaar,
                "netbeheerder_code": code_by_gln.get(gln, _GEEN_NETBEHEERDER_CODE),
                "tijdstip": _ts(r.tijdstip),
                "waarde": float(r.waarde) if r.waarde not in ("", "nan") else None,
                "bron_bestand": csv_path.name,
            }
        )
        if len(batch) >= _PROFIELEN_CHUNK_SIZE:
            _upsert_verbruiksprofiel_batch(conn, batch)
            totaal += len(batch)
            batch = []

    if batch:
        _upsert_verbruiksprofiel_batch(conn, batch)
        totaal += len(batch)

    return totaal


def _upsert_verbruiksprofiel_batch(conn: sa.Connection, batch: list[dict]) -> None:
    stmt = sa.dialects.postgresql.insert(verbruiksprofiel_waarde).values(batch)
    stmt = stmt.on_conflict_do_update(
        constraint="uq_verbruiksprofiel_waarde",
        set_={
            "waarde": stmt.excluded.waarde,
            "bron_bestand": stmt.excluded.bron_bestand,
            "version_id": stmt.excluded.version_id,
        },
    )
    conn.execute(stmt)
