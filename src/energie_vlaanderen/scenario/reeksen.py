"""Gedeelde verbruiks-/productiereeksen voor scenario's die het volume
wijzigen (`scenario.batterij`, `scenario.zonnepaneel`, `scenario.elektrische_wagen`,
`scenario.warmtepomp`).

Apart van die modules gezet omdat ze allemaal exact dezelfde
verbruiksreeks-logica nodig hebben (Fluvius-meting bij voorkeur, anders
SLP-EX), en twee kopieën daarvan uiteen zouden kunnen lopen.

**Verbruik én productie komen uit dezelfde bron.** Heeft het dossier een
Fluvius-meting, dan is de gemeten `injectie_kwh` per interval al de
opbrengst van een eventuele *bestaande* PV-installatie, netto van wat
zichzelf al verbruikte. `productiereeks()` mag in dat geval niet ook nog een
`productie_uit_kwp()` uit de PV-asset van het dossier optellen — dat zou
dezelfde zonnepanelen twee keer meetellen: één keer zoals de meter ze al
verrekende, en één keer als een nieuwe SPP-synthese. Alleen zonder meting
(profielgebaseerd pad) is er geen andere bron dan de assets van het dossier.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Optional

import pandas as pd

from energie_vlaanderen.gebruikers.models import Aanname, AssetType, EnergieType
from energie_vlaanderen.gebruikers.orchestratie import DossierResultaat
from energie_vlaanderen.gebruikers.schatting import (
    SchattingError,
    dichtstbijzijnd_beschikbaar_jaar,
    gewichten_uit_databank,
    productie_uit_kwp,
    verdeel_jaarverbruik,
)
from energie_vlaanderen.gebruikers.toml_io import Dossier
from energie_vlaanderen.utility.constants import D

# Dezelfde kolomvolgorde-conventie als `gebruikers.berekening._afname()`/
# `_injectie()`: dag + nacht + exclusief-nacht opgeteld (elektriciteit), met
# `afname_kwh`/`injectie_kwh` als terugval voor een reeks die al één
# samengevoegde kolom draagt (bv. gas, of een eerder gesimuleerde reeks).
_AFNAME_KOLOMMEN = ("afname_dag_kwh", "afname_nacht_kwh", "afname_exclusief_nacht_kwh", "afname_kwh")
_INJECTIE_KOLOMMEN = ("injectie_dag_kwh", "injectie_nacht_kwh", "injectie_kwh")


def binnen_venster(reeks: pd.DataFrame, van: date, tot: date) -> pd.DataFrame:
    """Beperkt `reeks` tot `[van, tot)`.

    `basislijn.metingen` (`gebruikers.orchestratie.laad_metingen()`) draagt de
    **volledige** Fluvius-export — bij een export van drie jaar dus
    honderdduizenden kwartieren, niet enkel het gevraagde venster.
    `Kostberekening._snijd_metingen()` filtert dat later wel per deelperiode
    voor de kostberekening, maar de dispatchsimulatie zelf liep zonder deze
    filter over de hele geschiedenis: honderdduizend regels doorrekenen in
    plaats van een paar duizend, en (bij prijsarbitrage) een reeks die het
    venster van de marktprijscache ver overschrijdt. Vandaar dat elke
    verbruiks-/productiereeks hier eerst tot het gevraagde venster beperkt
    wordt, vóór er iets mee gesimuleerd wordt.
    """
    if reeks.empty:
        return reeks
    tijdstip = pd.to_datetime(reeks["tijdstip"], utc=True)
    grens_van = pd.Timestamp(van, tz="UTC")
    grens_tot = pd.Timestamp(tot, tz="UTC")
    return reeks[(tijdstip >= grens_van) & (tijdstip < grens_tot)].reset_index(drop=True)


def _kolommen_optellen(metingen: pd.DataFrame, kolommen: tuple[str, ...]) -> pd.DataFrame:
    """Telt de aanwezige kolommen uit `kolommen` op tot één `tijdstip`/`kwh`-reeks."""
    aanwezig = [k for k in kolommen if k in metingen.columns]
    kwh = metingen[aanwezig].sum(axis=1) if aanwezig else 0.0
    return pd.DataFrame({"tijdstip": metingen["tijdstip"], "kwh": kwh})


def dag_nacht_masker(metingen: Optional[pd.DataFrame]) -> Optional[pd.DataFrame]:
    """`tijdstip`/`is_dag` — welk register een interval oorspronkelijk droeg.

    Een dubbeltariefmeter registreert elk kwartier in precies één van de twee
    registers (dag óf nacht) — dat onderscheid volgt het klokschema van de
    netbeheerder, niet het verbruik zelf. Dit project houdt nergens een eigen
    dag/nacht-klokschema bij (het komt altijd al gesplitst binnen, uit de
    Fluvius-export); een gesimuleerde reeks kan dat onderscheid dus alleen
    *overnemen* van een bestaande meting, niet zelf afleiden.

    Geeft `None` als `metingen` geen dag/nacht-registers draagt (bv. een
    profielgebaseerde reeks, die geen tijdschema kent) — de oproeper valt dan
    terug op alles als dag, met een zichtbare waarschuwing: dat is de enige
    informatie die er dan is, en die aanname moet zichtbaar blijven in plaats
    van een stille misclassificatie te worden (zie CLAUDE.md, "Dal is geen
    exclusief nacht" voor exact dit soort registerverwarring eerder in dit
    project).
    """
    if metingen is None or metingen.empty:
        return None
    if "afname_dag_kwh" not in metingen.columns and "afname_nacht_kwh" not in metingen.columns:
        return None
    dag = metingen.get("afname_dag_kwh", 0.0) + metingen.get("injectie_dag_kwh", 0.0)
    nacht = metingen.get("afname_nacht_kwh", 0.0) + metingen.get("injectie_nacht_kwh", 0.0)
    return pd.DataFrame({
        "tijdstip": metingen["tijdstip"],
        "is_dag": (pd.Series(dag) >= pd.Series(nacht)).to_numpy(),
    })


def verdeel_dag_nacht(
    reeks: pd.DataFrame, masker: Optional[pd.DataFrame], voorvoegsel: str,
) -> tuple[pd.DataFrame, Optional[str]]:
    """Splitst een gesimuleerde `tijdstip`/`kwh`-reeks in `{voorvoegsel}_dag_kwh`/
    `{voorvoegsel}_nacht_kwh`, via `masker` (zie `dag_nacht_masker()`).

    Zonder masker (geen dag/nacht-informatie beschikbaar) komt alles in het
    dagslot terecht — dezelfde terugval als `Kostberekening._periodevolumes()`
    al hanteert voor een reeks zonder registers — en geeft een waarschuwing
    terug in plaats van dat stil te laten passeren: bij een contract met een
    dag/nacht-tariefverschil (en zeker bij EV-laden of warmtepompverwarming,
    die net vaak 's nachts gebeuren) overschat "alles dag" de kost.
    """
    dag_kolom, nacht_kolom = f"{voorvoegsel}_dag_kwh", f"{voorvoegsel}_nacht_kwh"
    if masker is None or masker.empty:
        uit = reeks.copy()
        uit[dag_kolom] = uit["kwh"]
        uit[nacht_kolom] = 0.0
        waarschuwing = (
            f"Geen dag/nacht-onderscheid beschikbaar voor de gesimuleerde "
            f"{voorvoegsel}reeks; alles is als dagverbruik gerekend. Bij een "
            "tariefverschil tussen dag en nacht overschat dit de kost, vooral "
            "voor verbruik dat net 's nachts geconcentreerd is (EV-laden, "
            "warmtepomp)."
        )
        return uit[["tijdstip", dag_kolom, nacht_kolom]], waarschuwing

    samen = pd.merge(reeks, masker, on="tijdstip", how="left")
    # onbekend tijdstip: veilige kant (duurder) — expliciet naar bool casten,
    # want `fillna(True)` op een kolom met NaN's (van de left join) laat
    # pandas het dtype naar object/float optrekken, en `.where()` eist bool.
    samen["is_dag"] = samen["is_dag"].fillna(True).astype(bool)
    samen[dag_kolom] = samen["kwh"].where(samen["is_dag"], 0.0)
    samen[nacht_kolom] = samen["kwh"].where(~samen["is_dag"], 0.0)
    return samen[["tijdstip", dag_kolom, nacht_kolom]], None


def verbruiksreeks(
    dossier: Dossier,
    basislijn: DossierResultaat,
    *,
    conn,
    van: date,
    tot: date,
    jaarverbruik_kwh: Optional[Decimal],
) -> tuple[pd.DataFrame, Optional[Aanname]]:
    """Fluvius-meting bij voorkeur; anders SLP-EX geschaald naar het
    opgegeven (of uit de verbruiksopgaven afgeleide) jaarverbruik."""
    if basislijn.metingen is not None and not basislijn.metingen.empty:
        reeks = _kolommen_optellen(basislijn.metingen, _AFNAME_KOLOMMEN)
        return binnen_venster(reeks, van, tot), None

    if jaarverbruik_kwh is None:
        punt = dossier.punt(EnergieType.ELEKTRICITEIT)
        jaarverbruik_kwh = sum(
            (
                o.afname_dag_kwh + o.afname_nacht_kwh + o.afname_exclusief_nacht_kwh
                for o in dossier.opgaven_van(punt)
            ),
            D("0"),
        )
        if jaarverbruik_kwh <= 0:
            raise SchattingError(
                "Geen Fluvius-meting en geen jaarverbruik gekend (dossier noch "
                "`jaarverbruik_kwh`) — de dispatchsimulatie heeft een "
                "verbruiksreeks nodig om iets te simuleren."
            )

    jaar_profiel, ander_jaar = dichtstbijzijnd_beschikbaar_jaar(conn, "slp_ex", "elektriciteit", van.year)
    gewichten = gewichten_uit_databank(conn, "slp_ex", jaar_profiel, "elektriciteit")
    reeks = verdeel_jaarverbruik(jaarverbruik_kwh, gewichten, "slp_ex")
    aanname = Aanname(
        veld="scenario_verbruiksreeks",
        waarde=f"SLP-EX {jaar_profiel}, {jaarverbruik_kwh} kWh/jaar",
        bron="Synergrid SLP-EX-profiel, uit de databank",
        geverifieerd=False,
        beinvloedt_bedrag=True,
        motivering=(
            "Geen Fluvius-kwartiermeting in dit dossier; de dispatchsimulatie "
            "gebruikt daarom het genormaliseerde SLP-EX-profiel geschaald "
            "naar het opgegeven jaarverbruik. Dat is de vorm van een "
            "gemiddelde aansluiting, niet van deze."
            + (
                f" Het profiel van {jaar_profiel} is gebruikt voor {van.year}; "
                "die jaargang staat niet in de databank. De seizoensvorm "
                "herhaalt zich, maar het is een aanname."
                if ander_jaar else ""
            )
        ),
    )
    return reeks, aanname


def productiereeks(
    dossier: Dossier, punt, basislijn: DossierResultaat, *, conn, jaar: int,
    van: Optional[date] = None, tot: Optional[date] = None,
) -> tuple[pd.DataFrame, Optional[str]]:
    """PV-productie: de gemeten injectie bij voorkeur, anders uit een
    bestaande PV-asset in het dossier via SPP.

    `basislijn` moet dezelfde zijn als die aan `verbruiksreeks()` gegeven
    werd — anders zou verbruik uit de meting kunnen komen en productie uit een
    los SPP-profiel, wat een bestaande PV-installatie dubbel zou tellen (zie
    de moduledocstring). `van`/`tot` beperken de reeks tot het gevraagde
    venster (zie `binnen_venster()`) — zonder die twee blijft de volledige
    meetreeks staan, wat voor prijsarbitrage een marktprijsvenster van jaren
    zou vergen in plaats van het gevraagde venster.
    """
    if basislijn.metingen is not None and not basislijn.metingen.empty:
        reeks = _kolommen_optellen(basislijn.metingen, _INJECTIE_KOLOMMEN)
        if van is not None and tot is not None:
            reeks = binnen_venster(reeks, van, tot)
        return reeks, None

    pv_assets = [
        a for a in dossier.assets
        if a.type is AssetType.PV and a.aansluitingspunt_id == punt.id and a.kwp
    ]
    if not pv_assets:
        leeg = pd.DataFrame({"tijdstip": [], "kwh": []})
        return leeg, (
            "Geen zonnepanelen in dit dossier: er is geen eigen productie om "
            "de batterij mee te laden. Dit dispatchmodel doet "
            "zelfconsumptie, geen prijsarbitrage — zonder PV verandert de "
            "kost dus niet."
        )

    kwp = sum((a.kwp for a in pv_assets), D("0"))
    jaar_profiel, _ = dichtstbijzijnd_beschikbaar_jaar(conn, "spp", "", jaar)
    gewichten = gewichten_uit_databank(conn, "spp", jaar_profiel)
    reeks = productie_uit_kwp(kwp, gewichten)
    if van is not None and tot is not None:
        reeks = binnen_venster(reeks, van, tot)
    return reeks, None
