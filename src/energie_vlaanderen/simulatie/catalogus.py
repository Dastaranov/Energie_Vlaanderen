"""Opzoekingen: welke leveranciers, welke contracten, welk contract precies.

Dit bestand raakt de databank alleen lezend en bevat geen rekenregel — dat
is de scheiding die `experiments/remove/data_repository.py` (zie CLAUDE.md
"De CSV-lezer staat niet meer in `src/`") ook bewaakte: opzoeken en rekenen
zijn twee lagen.

`vtest_contract` draagt de scrape-metadata van vtest.be (looptijd,
doelgroepen, links, SCD2-tijdas op de scrapedatum); `energie_product` draagt
de canonieke leverancier- en segmentindeling waarop de tariefhistoriek
(`tarief_afname`/`tarief_injectie`) hangt. Eén contract is pas compleet met
allebei: de koppeling loopt via `vreg_id`, dat in `energie_product` uniek is
maar in `vtest_contract` een SCD2-sleutel (`vreg_id`, `geldig_van`).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING, Optional

import sqlalchemy as sa

if TYPE_CHECKING:
    from energie_vlaanderen.simulatie.context import SimulatieContext


class CatalogusError(RuntimeError):
    """Een opzoeking in de contractcatalogus kon niet eenduidig beantwoord worden."""


@dataclass(frozen=True)
class Leverancier:
    id: int
    naam: str
    juridische_entiteit: Optional[str]


@dataclass(frozen=True)
class ContractMetadata:
    """Eén contractsnapshot: de vtest.be-scrape, aangevuld met de canonieke
    leverancier-/productidentiteit waarop de tariefhistoriek hangt.

    De velden met een `datum_*`/`geldig_*` naam zijn hetzelfde onderscheid
    dat CLAUDE.md maakt bij `vtest_contract`: `geldig_van`/`geldig_tot` zegt
    vanaf/tot wanneer déze beschrijving bij vtest.be zo stond,
    `gepubliceerd_op` wanneer wij ze publiceerden. Beide zijn iets anders dan
    `datum_intekenen_*` (wanneer je op dit contract kunt intekenen) en
    `datum_start_levering_*`.
    """

    vreg_id: str
    leverancier: str
    product_naam: str
    energie_type: Optional[str]
    segment: Optional[str]
    tarief_type: Optional[str]
    contracttype: Optional[str]
    looptijd_tekst: Optional[str]
    looptijd_maanden: Optional[int]
    datum_intekenen_van: Optional[date]
    datum_intekenen_tot: Optional[date]
    datum_start_levering_van: Optional[date]
    datum_start_levering_tot: Optional[date]
    doelgroep_zonnepanelen: Optional[str]
    doelgroep_ev: Optional[str]
    doelgroep_energiedelen: Optional[str]
    doelgroep_leegstand: Optional[str]
    doelgroep_groepsaankoop: Optional[str]
    prijszekerheid_termijn: Optional[str]
    link_tariefkaart: Optional[str]
    link_voorwaarden: Optional[str]
    link_supplier: Optional[str]
    tariefkaart_url: Optional[str]
    bijzondere_voorwaarden_url: Optional[str]
    groene_stroom: Optional[bool]
    groene_stroom_type: Optional[str]
    complex_product: Optional[bool]
    grayedout: Optional[bool]
    geldig_van: date
    geldig_tot: Optional[date]
    gepubliceerd_op: Optional[object]
    laatst_gezien_versie: str


_CONTRACT_QUERY = """
    select vc.vreg_id, coalesce(l.naam, vc.leverancier_raw) as leverancier,
           coalesce(ep.product_naam, vc.product_raw) as product_naam,
           coalesce(ep.energie_type, vc.energie_type) as energie_type,
           ep.segment, vc.tarief_type, vc.contracttype,
           vc.looptijd_tekst, vc.looptijd_maanden,
           vc.datum_intekenen_van, vc.datum_intekenen_tot,
           vc.datum_start_levering_van, vc.datum_start_levering_tot,
           vc.doelgroep_zonnepanelen, vc.doelgroep_ev, vc.doelgroep_energiedelen,
           vc.doelgroep_leegstand, vc.doelgroep_groepsaankoop,
           vc.prijszekerheid_termijn,
           vc.link_tariefkaart, vc.link_voorwaarden, vc.link_supplier,
           ep.tariefkaart_url, ep.bijzondere_voorwaarden_url,
           ep.groene_stroom, ep.groene_stroom_type,
           vc.complex_product, vc.grayedout,
           vc.geldig_van, vc.geldig_tot, vc.gepubliceerd_op, vc.laatst_gezien_versie
      from vtest_contract vc
      left join energie_product ep on ep.vreg_id = vc.vreg_id
      left join leverancier l on l.id = ep.leverancier_id
"""


def _naar_metadata(rij: sa.RowMapping) -> ContractMetadata:
    velden = dict(rij)
    return ContractMetadata(**velden)


def lijst_leveranciers(ctx: "SimulatieContext") -> list[Leverancier]:
    """Alle leveranciers die minstens één product in de databank hebben."""
    rijen = ctx.conn.execute(
        sa.text(
            "select id, naam, juridische_entiteit from leverancier order by naam"
        )
    ).mappings().all()
    return [Leverancier(id=r["id"], naam=r["naam"], juridische_entiteit=r["juridische_entiteit"]) for r in rijen]


def lijst_contracten(
    ctx: "SimulatieContext",
    *,
    energie_type: Optional[str] = None,
    segment: Optional[str] = None,
    leverancier: Optional[str] = None,
    actief_op: Optional[date] = None,
    alleen_actueel: bool = True,
) -> list[ContractMetadata]:
    """Contracten uit de vtest.be-catalogus, gefilterd.

    `alleen_actueel=True` (de standaard) geeft per `vreg_id` alleen het
    lopende snapshot terug (`geldig_tot is null`) — de beschrijving zoals
    vtest.be ze vandaag toont. Zet ze op `False`, of geef `actief_op` mee, om
    een historisch snapshot op te vragen; zonder een van beide zou een
    contract dat intussen gewijzigd is meerdere keren in de lijst staan.
    """
    voorwaarden = []
    params: dict[str, object] = {}

    if actief_op is not None:
        voorwaarden.append("vc.geldig_van <= :actief_op")
        voorwaarden.append("(vc.geldig_tot is null or vc.geldig_tot >= :actief_op)")
        params["actief_op"] = actief_op
    elif alleen_actueel:
        voorwaarden.append("vc.geldig_tot is null")

    if energie_type:
        voorwaarden.append("lower(coalesce(ep.energie_type, vc.energie_type)) = :energie_type")
        params["energie_type"] = energie_type.casefold()
    if segment:
        voorwaarden.append("lower(ep.segment) = :segment")
        params["segment"] = segment.casefold()
    if leverancier:
        voorwaarden.append("lower(coalesce(l.naam, vc.leverancier_raw)) = :leverancier")
        params["leverancier"] = leverancier.casefold()

    query = _CONTRACT_QUERY
    if voorwaarden:
        query += " where " + " and ".join(voorwaarden)
    query += " order by leverancier, product_naam, vc.geldig_van desc"

    rijen = ctx.conn.execute(sa.text(query), params).mappings().all()
    return [_naar_metadata(r) for r in rijen]


def haal_contract(
    ctx: "SimulatieContext",
    vreg_id: str,
    *,
    op_datum: Optional[date] = None,
) -> ContractMetadata:
    """Eén contract met alle metadata, op een gegeven datum (standaard: het
    lopende snapshot).

    Raises `CatalogusError` als het `vreg_id` niet bestaat, in plaats van
    `None` terug te geven: een onbekend contract in een simulatie is een
    fout in de invoer, geen leeg resultaat om stil mee door te rekenen.
    """
    query = _CONTRACT_QUERY + " where vc.vreg_id = :vreg_id"
    params: dict[str, object] = {"vreg_id": vreg_id}
    if op_datum is not None:
        query += " and vc.geldig_van <= :op_datum and (vc.geldig_tot is null or vc.geldig_tot >= :op_datum)"
        params["op_datum"] = op_datum
    else:
        query += " and vc.geldig_tot is null"
    query += " order by vc.geldig_van desc limit 1"

    rij = ctx.conn.execute(sa.text(query), params).mappings().first()
    if rij is None:
        raise CatalogusError(
            f"Geen contract met vreg_id={vreg_id!r} gevonden"
            + (f" op {op_datum}." if op_datum else " (lopend snapshot).")
        )
    return _naar_metadata(rij)
