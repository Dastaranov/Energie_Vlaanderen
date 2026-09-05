"""De "zware calculator": elk elektriciteitscontract op de markt, in detail
tegen dit dossier afgezet — met en zonder batterij, en met of zonder
prijsarbitrage op wie dynamisch is.

Dit is geen vuistregel of terugverdientijd-schatting: elke kandidaat wordt
via `AnderContractScenario` en `gebruikers.orchestratie.bereken_dossier()`
door dezelfde `Kostberekening` gerekend als een echte afrekening — inclusief
dag/nacht-tarief, het exclusief-nachtregister ("superdal", zie
CLAUDE.md "De referentiefactuur nagerekend" — hetzelfde register dat ENGIE
zo noemt) en het capaciteitstarief. Wat dit bestand toevoegt is enkel de
opzoeklogica: welke contracten bestaan er, en hoe worden ze efficiënt
allemaal doorgerekend.

**De dure stap gebeurt precies één keer.** De batterijdispatch (zelfconsumptie
én, bij prijsarbitrage, de Belpex-drempels) hangt af van verbruik, productie
en marktprijs — nooit van de retailformule van één specifiek product (zie
`BatterijScenario.simuleer_metingen()`). Twee dispatchruns (met en zonder
arbitrage) volstaan dus voor alle honderden kandidaten samen; per kandidaat
blijft enkel de goedkope stap over: dezelfde reeks tegen een andere
tariefformule prijzen.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Optional

from energie_vlaanderen.calculation.dispatch import DispatchError
from energie_vlaanderen.gebruikers.models import (
    Contracttype,
    EnergieType,
    Exactheidsklasse,
    GebruikersError,
)
from energie_vlaanderen.gebruikers.orchestratie import bereken_dossier, laad_markt
from energie_vlaanderen.gebruikers.toml_io import Dossier
from energie_vlaanderen.scenario.batterij import BatterijScenario
from energie_vlaanderen.scenario.contract import AnderContractScenario
from energie_vlaanderen.settings import Settings
from energie_vlaanderen.utility.constants import D

ZONDER_BATTERIJ = "zonder batterij"
MET_BATTERIJ = "met batterij"
MET_BATTERIJ_ARBITRAGE = "met batterij + arbitrage"


@dataclass(frozen=True)
class ContractResultaat:
    """Eén kandidaat, in één modus, met zijn totale elektriciteitskost — of
    de reden waarom die niet te berekenen viel (bv. het product bestaat niet
    voor elke maand van het venster)."""

    leverancier: str
    product: str
    contracttype: Contracttype
    modus: str
    totaal_eur: Optional[Decimal]
    exactheidsklasse: Optional[Exactheidsklasse]
    fout: Optional[str] = None

    @property
    def gelukt(self) -> bool:
        return self.fout is None


@dataclass(frozen=True)
class OptimalisatieResultaat:
    """Het volledige overzicht: elke kandidaat/modus-combinatie, plus de
    concrete antwoorden op "wat levert wat op"."""

    kandidaten: tuple[ContractResultaat, ...]
    huidige_kost_eur: Decimal
    beste_zonder_batterij: Optional[ContractResultaat]
    beste_met_batterij: Optional[ContractResultaat]
    huidig_contract_met_batterij: Optional[ContractResultaat]

    @property
    def winst_contractwissel_alleen(self) -> Optional[Decimal]:
        """Enkel van leverancier/type wisselen, geen batterij."""
        if self.beste_zonder_batterij is None or self.beste_zonder_batterij.totaal_eur is None:
            return None
        return self.huidige_kost_eur - self.beste_zonder_batterij.totaal_eur

    @property
    def winst_batterij_zelfde_contract(self) -> Optional[Decimal]:
        """Enkel een batterij bijplaatsen, contract ongewijzigd."""
        if self.huidig_contract_met_batterij is None or self.huidig_contract_met_batterij.totaal_eur is None:
            return None
        return self.huidige_kost_eur - self.huidig_contract_met_batterij.totaal_eur

    @property
    def winst_gecombineerd(self) -> Optional[Decimal]:
        """Het beste van beide: batterij én het beste contract erbij."""
        if self.beste_met_batterij is None or self.beste_met_batterij.totaal_eur is None:
            return None
        return self.huidige_kost_eur - self.beste_met_batterij.totaal_eur


def kandidaat_contracten(
    conn, *, segment: str = "Woning", peildatum: date,
) -> list[tuple[str, str, Contracttype]]:
    """Elk (leverancier, productnaam, contracttype) dat op `peildatum` een
    elektriciteitsprijs draagt voor dit segment.

    Eén rij per échte keuze die een klant kan maken — "Bolt Variabel" bestaat
    bijvoorbeeld zowel als `variabel` als `dynamisch` in de export (de
    optionele dynamische afrekening op hetzelfde contract), en dat zijn hier
    dus bewust twee aparte kandidaten.
    """
    import sqlalchemy as sa

    rijen = conn.execute(
        sa.text(
            """
            select l.naam, ep.product_naam, ta.prijs_type
              from tarief_afname ta
              join energie_product ep on ep.id = ta.product_id
              join leverancier l on l.id = ep.leverancier_id
             where ep.energie_type = 'elektriciteit'
               and ep.segment = :segment
               and ta.geldig_van <= :peildatum
               and (ta.geldig_tot is null or ta.geldig_tot >= :peildatum)
             group by 1, 2, 3
             order by 1, 2
            """
        ),
        {"segment": segment, "peildatum": peildatum},
    ).all()
    return [(leverancier, product, Contracttype(prijs_type)) for leverancier, product, prijs_type in rijen]


def _reken_kandidaat(
    dossier_variant: Dossier,
    *,
    conn,
    settings: Settings,
    van: date,
    tot: date,
    metingen_override,
    leverancier: str,
    product: str,
    contracttype: Contracttype,
    modus: str,
) -> ContractResultaat:
    kwargs = {} if metingen_override is None else {"metingen_override": metingen_override}
    try:
        resultaat = bereken_dossier(dossier_variant, conn=conn, settings=settings, van=van, tot=tot, **kwargs)
    except GebruikersError as exc:
        return ContractResultaat(leverancier, product, contracttype, modus, None, None, fout=str(exc))

    elektriciteit = next(
        (r for punt, r in resultaat.resultaten if punt.energie_type is EnergieType.ELEKTRICITEIT),
        None,
    )
    if elektriciteit is None:
        mislukking = next((m for s, m in resultaat.mislukt if s == "elektriciteit"), "onbekende reden")
        return ContractResultaat(leverancier, product, contracttype, modus, None, None, fout=mislukking)

    return ContractResultaat(
        leverancier, product, contracttype, modus,
        elektriciteit.totalen["totaal"], elektriciteit.exactheidsklasse,
    )


def optimaliseer_elektriciteitscontract(
    dossier: Dossier,
    *,
    conn,
    settings: Settings,
    van: date,
    tot: date,
    batterij: Optional[BatterijScenario] = None,
    segment: str = "Woning",
    peildatum: Optional[date] = None,
) -> OptimalisatieResultaat:
    """De volledige markt tegen dit dossier afzetten — optioneel mét batterij.

    `peildatum` bepaalt welke productencatalogus geraadpleegd wordt
    (standaard `van`); een contract dat pas halverwege het venster verdwijnt
    of verschijnt, geeft dan een `fout` in plaats van een bedrag voor die
    kandidaat (`Kostberekening.zoek_product()` weigert per maand die het
    product niet vindt) — precies zoals dat ook bij een echte, bestaande
    afrekening gebeurt.
    """
    punt = dossier.punt(EnergieType.ELEKTRICITEIT)
    if punt is None:
        raise GebruikersError("Dit dossier heeft geen elektriciteitsaansluiting.")

    peildatum = peildatum or van
    kandidaten = kandidaat_contracten(conn, segment=segment, peildatum=peildatum)

    huidig = bereken_dossier(dossier, conn=conn, settings=settings, van=van, tot=tot)
    huidige_elek = next(
        (r for p, r in huidig.resultaten if p.energie_type is EnergieType.ELEKTRICITEIT), None,
    )
    if huidige_elek is None:
        raise GebruikersError(
            "Het bestaande dossier zelf kon niet doorgerekend worden voor "
            "elektriciteit; er is dan geen basislijn om tegen te vergelijken."
        )
    huidige_kost = huidige_elek.totalen["totaal"]

    metingen_batterij: Optional[object] = None
    metingen_batterij_arbitrage: Optional[object] = None
    if batterij is not None:
        metingen_batterij, _, _ = batterij.simuleer_metingen(
            dossier, conn=conn, settings=settings, van=van, tot=tot, basislijn=huidig,
        )
        marktprijzen = laad_markt(settings, van, tot)
        if marktprijzen is not None and not marktprijzen.empty:
            try:
                metingen_batterij_arbitrage, _, _ = batterij.simuleer_metingen(
                    dossier, conn=conn, settings=settings, van=van, tot=tot, basislijn=huidig,
                    marktprijzen_override=marktprijzen,
                )
            except DispatchError:
                # De cache dekt het venster niet volledig (ENTSO-E kent
                # gaten, zie CLAUDE.md "De marktprijscache was niet
                # herbruikbaar") — dan is er geen prijs voor elk interval en
                # weigert de dispatch terecht. Dat mag de rest van deze
                # vergelijking niet laten vervallen: enkel de arbitragemodus
                # blijft dan achterwege, de "zonder batterij"/"met batterij"
                # modi hebben deze reeks niet nodig.
                metingen_batterij_arbitrage = None

    resultaten: list[ContractResultaat] = []
    huidig_contract_met_batterij: Optional[ContractResultaat] = None

    for leverancier, product, contracttype in kandidaten:
        kandidaat = AnderContractScenario(
            energie_type=EnergieType.ELEKTRICITEIT, leverancier=leverancier,
            product=product, contracttype=contracttype,
        )
        gewijzigd = kandidaat.pas_toe(dossier)

        resultaten.append(_reken_kandidaat(
            gewijzigd, conn=conn, settings=settings, van=van, tot=tot, metingen_override=None,
            leverancier=leverancier, product=product, contracttype=contracttype, modus=ZONDER_BATTERIJ,
        ))

        if batterij is not None:
            gewijzigd_met_batterij = batterij.pas_toe(gewijzigd)
            resultaten.append(_reken_kandidaat(
                gewijzigd_met_batterij, conn=conn, settings=settings, van=van, tot=tot,
                metingen_override=metingen_batterij,
                leverancier=leverancier, product=product, contracttype=contracttype, modus=MET_BATTERIJ,
            ))
            if contracttype is Contracttype.DYNAMISCH and metingen_batterij_arbitrage is not None:
                resultaten.append(_reken_kandidaat(
                    gewijzigd_met_batterij, conn=conn, settings=settings, van=van, tot=tot,
                    metingen_override=metingen_batterij_arbitrage,
                    leverancier=leverancier, product=product, contracttype=contracttype,
                    modus=MET_BATTERIJ_ARBITRAGE,
                ))

    # Het huidige contract, met batterij, is een van de "gewone" kandidaten
    # als het toevallig in de catalogus staat — maar dat is niet gegarandeerd
    # (een bevroren vast contract kan intussen van de markt zijn). Reken het
    # daarom altijd apart uit met het échte, ongewijzigde contract.
    if batterij is not None:
        dossier_met_batterij = batterij.pas_toe(dossier)
        huidige_contracten = dossier.contracten_van(punt)
        naam = (
            f"{huidige_contracten[0].leverancier} — {huidige_contracten[0].product}"
            if huidige_contracten else "huidig contract"
        )
        try:
            resultaat = bereken_dossier(
                dossier_met_batterij, conn=conn, settings=settings, van=van, tot=tot,
                metingen_override=metingen_batterij,
            )
            elek = next(
                (r for p, r in resultaat.resultaten if p.energie_type is EnergieType.ELEKTRICITEIT), None,
            )
            huidig_contract_met_batterij = ContractResultaat(
                naam, "(huidig)", huidige_contracten[0].contracttype if huidige_contracten else Contracttype.VAST,
                MET_BATTERIJ,
                elek.totalen["totaal"] if elek else None,
                elek.exactheidsklasse if elek else None,
            )
        except GebruikersError as exc:
            huidig_contract_met_batterij = ContractResultaat(
                naam, "(huidig)", Contracttype.VAST, MET_BATTERIJ, None, None, fout=str(exc),
            )

    gelukte = [r for r in resultaten if r.gelukt]
    beste_zonder = min(
        (r for r in gelukte if r.modus == ZONDER_BATTERIJ), key=lambda r: r.totaal_eur, default=None,
    )
    beste_met = min(
        (r for r in gelukte if r.modus in (MET_BATTERIJ, MET_BATTERIJ_ARBITRAGE)),
        key=lambda r: r.totaal_eur, default=None,
    )

    return OptimalisatieResultaat(
        kandidaten=tuple(sorted(
            resultaten, key=lambda r: (not r.gelukt, r.totaal_eur if r.gelukt else D("0")),
        )),
        huidige_kost_eur=huidige_kost,
        beste_zonder_batterij=beste_zonder,
        beste_met_batterij=beste_met,
        huidig_contract_met_batterij=huidig_contract_met_batterij,
    )
