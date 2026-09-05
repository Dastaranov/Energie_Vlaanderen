"""De brug tussen een fysiek assetmodel en een tijdreeks die de rekenengine
kan doorrekenen.

`calculation.batterySpec.Battery` (en de andere assetklassen in dit pakket)
simuleren stap voor stap — `laad()`/`ontlaad()` geven telkens één scalaire kWh
terug voor één interval. Niets in het project verbond dat voorheen met een
tijdreeks: de enige bestaande asset->tijdreeks-functie was
`gebruikers.schatting.productie_uit_kwp()` (PV, via het SPP-profiel, zonder
een simulatieobject). Dit bestand vult dat gat voor batterijdispatch, EV-laden
en warmtepompverwarming, en blijft daarbij bewust **puur fysiek**: geen import
van `Calculator`/`heffingen`. Dat is de scheiding die ROADMAP.md §14
("fysieke en financiële modellen blijven gescheiden") voorschrijft — dit
bestand levert een tijdreeks (`tijdstip`, `afname_kwh`, `injectie_kwh`, exact
de vorm die `Calculator.supplier_cost(intervals=...)` en
`FluviusReeks.voor_berekening()` al gebruiken), en de financiële laag blijft
onwetend van hoe die reeks tot stand kwam.

**Elke oproep bouwt of ontvangt een verse asset-instantie.** `Battery` (en de
andere assetklassen) zijn stateful en zelfmuterend — `state_of_charge`/
`state_of_health` veranderen permanent bij elke `laad()`/`ontlaad()`-aanroep.
Twee scenario's die tegen dezelfde batterij afgezet worden (bv. contract A vs.
contract B) moeten dus elk hun eigen `Battery.from_masterdata(spec)` krijgen;
een gedeelde instantie tussen twee runs geeft een resultaat dat afhangt van de
volgorde waarin ze draaiden.
"""
from __future__ import annotations

import math
from typing import TYPE_CHECKING, Optional

import pandas as pd

from decimal import Decimal

from energie_vlaanderen.gebruikers.models import Aanname, Topologie
from energie_vlaanderen.gebruikers.schatting import intervalduur_uren, verdeel_jaarverbruik
from energie_vlaanderen.utility.constants import D

if TYPE_CHECKING:
    from datetime import date

    from energie_vlaanderen.calculation.batterySpec import Battery
    from energie_vlaanderen.calculation.elektrische_wagenSpec import ElektrischeWagen
    from energie_vlaanderen.calculation.warmtepompSpec import Warmtepomp


class DispatchError(RuntimeError):
    """De aangeboden tijdreeksen konden niet tegen elkaar afgezet worden."""


def _duur_s(reeks: pd.DataFrame) -> float:
    return float(intervalduur_uren(reeks)) * 3600.0


def _samengevoegd(verbruik: pd.DataFrame, productie: pd.DataFrame) -> pd.DataFrame:
    """Voegt verbruiks- en productiereeks samen op `tijdstip`.

    Een `outer` join en niet `inner`: een tijdstip dat maar in één van de twee
    reeksen voorkomt mag niet stil verdwijnen (dat zou energie laten
    verdampen), het wordt als 0 voor de ontbrekende kant behandeld en gemeld
    via `DispatchError` als er te veel gaten zijn.
    """
    samen = pd.merge(
        verbruik.rename(columns={"kwh": "verbruik_kwh"}),
        productie.rename(columns={"kwh": "productie_kwh"}),
        on="tijdstip", how="outer", indicator=True,
    ).sort_values("tijdstip").reset_index(drop=True)

    ontbrekend = samen["_merge"].ne("both").sum()
    if ontbrekend:
        totaal = len(samen)
        if ontbrekend / totaal > 0.05:
            raise DispatchError(
                f"{ontbrekend} van {totaal} tijdstippen komen niet in beide "
                "reeksen voor (verbruik/productie) — de reeksen dekken "
                "vermoedelijk niet dezelfde periode of resolutie."
            )
    samen["verbruik_kwh"] = samen["verbruik_kwh"].fillna(0.0)
    samen["productie_kwh"] = samen["productie_kwh"].fillna(0.0)
    return samen.drop(columns="_merge")


def _koppel_marktprijzen(samen: pd.DataFrame, marktprijzen: pd.DataFrame) -> pd.DataFrame:
    """Koppelt `price_eur_mwh` aan elk dispatchinterval.

    Zelfde regel als `Calculator.supplier_cost()`'s dynamische tak: de
    marktprijs staat per uur (of per kwartier, bij PT15M-prijzen), het
    dispatchinterval kan fijner zijn — er wordt naar beneden afgerond op de
    resolutie van de prijsreeks, niet omgekeerd geïnterpoleerd.
    """
    prijzen = marktprijzen[["timestamp", "price_eur_mwh"]].copy().sort_values("timestamp")
    resolutie = prijzen["timestamp"].diff().dropna().median()
    vlag = "h" if pd.isna(resolutie) or resolutie >= pd.Timedelta(minutes=60) else "15min"

    uit = samen.copy()
    uit["market_ts"] = pd.to_datetime(uit["tijdstip"], utc=True).dt.floor(vlag)
    gekoppeld = uit.merge(
        prijzen, left_on="market_ts", right_on="timestamp", how="left", suffixes=("", "_markt"),
    )
    ontbrekend = gekoppeld["price_eur_mwh"].isna().sum()
    if ontbrekend:
        totaal = len(gekoppeld)
        if ontbrekend / totaal > 0.05:
            raise DispatchError(
                f"Voor {ontbrekend} van de {totaal} dispatchintervallen is er "
                "geen marktprijs — vul de cache aan met "
                "`energievergelijker market sync --start --end` vóór prijsarbitrage."
            )
    return gekoppeld.drop(columns=["market_ts", "timestamp"])


def _arbitragedrempels(
    gekoppeld: pd.DataFrame, batterij: "Battery", duur_uren: float,
) -> pd.Series:
    """Per lokale kalenderdag: onder welke prijs kopen, boven welke verkopen.

    Een dagvenster, want Belpex day-ahead-prijzen worden per kalenderdag
    gepubliceerd en de batterij cyclust hooguit een paar keer per dag rond.
    De drempel is niet geraden maar afgeleid uit de batterij zelf: het aantal
    kwartieren dat nodig is om haar **vanaf leeg volledig te laden** (aan
    `max_charge_w`) bepaalt hoeveel van de goedkoopste uren "koop" zijn; het
    aantal om haar **volledig te ontladen tot de minimumgrens** (aan
    `max_discharge_w`) bepaalt hoeveel van de duurste uren "verkoop" zijn.
    Dat is een dagvooruitzicht-heuristiek (perfect-foresight binnen de dag),
    geen optimale oplossing over meerdere dagen — vandaar dat de oproeper dit
    als `Aanname` meegeeft.

    De eerste en laatste kalenderdag van het venster zijn vaak fragmenten
    (een venster in UTC begint zelden op lokale middernacht). Een fragment
    van bv. één enkel uur zou dat ene punt triviaal als "goedkoopste uur van
    de dag" bestempelen — geen echte koopkans, een artefact van de
    venstergrens. Een dag met minder dan de helft van het typische aantal
    punten krijgt daarom geen drempel (nooit arbitrage die dag, wel gewoon
    zelfconsumptie).
    """
    laad_kwh_per_slot = batterij.max_charge_w / 1000.0 * duur_uren
    ontlaad_kwh_per_slot = batterij.max_discharge_w / 1000.0 * duur_uren
    bruikbare_capaciteit = batterij.max_capacity * (batterij.max_depth_of_discharge / 100.0)

    laad_sloten = max(1, math.ceil(batterij.max_capacity / laad_kwh_per_slot)) if laad_kwh_per_slot > 0 else 0
    ontlaad_sloten = max(1, math.ceil(bruikbare_capaciteit / ontlaad_kwh_per_slot)) if ontlaad_kwh_per_slot > 0 else 0

    dag = pd.to_datetime(gekoppeld["tijdstip"], utc=True).dt.tz_convert("Europe/Brussels").dt.date
    prijs = gekoppeld["price_eur_mwh"]

    groepsgroottes = prijs.groupby(dag).size()
    minimale_groepsgrootte = groepsgroottes.median() / 2.0

    koopdrempel_per_dag: dict = {}
    verkoopdrempel_per_dag: dict = {}
    for dagwaarde, groep in prijs.groupby(dag):
        n = len(groep)
        if n < minimale_groepsgrootte:
            koopdrempel_per_dag[dagwaarde] = float("-inf")
            verkoopdrempel_per_dag[dagwaarde] = float("inf")
            continue
        koopdrempel_per_dag[dagwaarde] = (
            groep.nsmallest(min(laad_sloten, n)).max() if laad_sloten else float("-inf")
        )
        verkoopdrempel_per_dag[dagwaarde] = (
            groep.nlargest(min(ontlaad_sloten, n)).min() if ontlaad_sloten else float("inf")
        )

    return dag.map(koopdrempel_per_dag), dag.map(verkoopdrempel_per_dag)


def _bestaande_maandpiek_kwh(samen: pd.DataFrame) -> pd.Series:
    """De piek-kWh per interval die de kalendermaand van dat interval **zonder
    batterij** al zou halen — gebruikt om arbitragekoop te begrenzen.

    Zelfde regel als `Kostberekening._maandpieken()`: de piek van een maand is
    het hoogste kwartier(of uur)verbruik in die maand, in lokale tijd
    (Europe/Brussels, hetzelfde tijdschema als het capaciteitstarief). Zonder
    deze grens zou prijsarbitrage tijdens een goedkoop uur maximaal kunnen
    laden, zelfs als dat net samenvalt met het duurste kwartier van de maand
    — en dan verhoogt de "besparing" op de energiekost per ongeluk het
    capaciteitstarief, de grootste post van de netkost bij een digitale meter.
    """
    netto = samen["productie_kwh"] - samen["verbruik_kwh"]
    afname_zonder_batterij = (-netto).clip(lower=0.0)
    lokaal = pd.to_datetime(samen["tijdstip"], utc=True).dt.tz_convert("Europe/Brussels")
    maand_sleutel = lokaal.dt.year * 100 + lokaal.dt.month
    piek_per_maand = afname_zonder_batterij.groupby(maand_sleutel).transform("max")
    return piek_per_maand


def simuleer_batterij_dispatch(
    batterij: "Battery",
    verbruik: pd.DataFrame,
    productie: pd.DataFrame,
    *,
    topologie: Topologie,
    marktprijzen: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    """Simuleert de batterijdispatch, interval per interval.

    `verbruik`/`productie` zijn DataFrames met kolommen `tijdstip` en `kwh` —
    dezelfde vorm als `gebruikers.schatting.verdeel_jaarverbruik()` en
    `productie_uit_kwp()` teruggeven, of `FluviusReeks.voor_berekening()` voor
    een echte meting.

    **Zonder `marktprijzen`** (standaard): zelfconsumptie-eerst. Overschot
    (productie > verbruik) laadt de batterij, tekort wordt uit de batterij
    gehaald. Wat ze niet kan opnemen gaat naar injectie; wat ze niet kan
    leveren komt van het net.

    **Met `marktprijzen`** (kolommen `timestamp`, `price_eur_mwh`, zoals
    `EntsoeMarketData.load()` teruggeeft): prijsarbitrage komt erbij, alleen
    zinvol op een **dynamisch** contract — de oproeper moet dat zelf toetsen,
    deze functie rekent met de ruwe Belpex-prijs en niet met een
    retailformule (zie `scenario.batterij` voor de contracttoets). Onder de
    dagelijkse koopdrempel (zie `_arbitragedrempels()`) laadt de batterij
    maximaal, ook zonder productieoverschot; boven de verkoopdrempel ontlaadt
    ze maximaal, ook zonder verbruikstekort. Daartussenin blijft het
    zelfconsumptie-gedrag hierboven gewoon gelden.

    **Arbitragekoop overschrijdt nooit de bestaande maandpiek** (zie
    `_bestaande_maandpiek_kwh()`): laden vanuit het net tijdens een goedkoop
    uur mag de resulterende afname van dat uur niet boven de piek tillen die
    de kalendermaand *zonder* batterij al had. Zonder die grens zou een
    energiebesparing via arbitrage het capaciteitstarief kunnen verhogen —
    voor een digitale meter de grootste post van de netkost. Ontladen
    (zelfconsumptie én arbitrageverkoop) heeft deze grens niet nodig: het
    verlaagt de afname of verhoogt de injectie, nooit omgekeerd.

    Eén boekhoudregel dekt beide gevallen: het net ziet
    `(verbruik - productie) + laad - ontlaad`. Positief is afname, negatief is
    injectie — of de batterij nu laadde/ontlaadde voor zelfconsumptie of voor
    arbitrage maakt voor die boekhouding niets uit.

    `topologie` wordt vandaag enkel doorgegeven ter documentatie in het
    resultaat: `Battery` kent geen AC/DC-conversieverlies-onderscheid naar
    koppeling (dat zit al in `rte_ac_dc`/`rte_dc_ac`, vast per toestel). Een
    `AC_GEKOPPELD`-batterij ondervindt in werkelijkheid twee omvormerstappen
    (PV-omvormer -> net -> batterij-omvormer) waar `DC_GEKOPPELD` er één
    overslaat; dat verschil zit in dit model nog niet en is een bewuste
    vereenvoudiging, geen verzwegen fout — vandaar dat de kolom in de uitvoer
    staat en niet in de berekening zelf.

    Geeft een DataFrame terug met `tijdstip`, `afname_kwh`, `injectie_kwh` (de
    vorm die `Calculator.supplier_cost(intervals=...)` verwacht), plus
    `batterij_soc_pct`, `batterij_laad_kwh`, `batterij_ontlaad_kwh` en
    `modus` (`"zelfconsumptie"`, `"arbitrage_koop"` of `"arbitrage_verkoop"`)
    voor wie de dispatch zelf wil inspecteren.
    """
    samen = _samengevoegd(verbruik, productie)
    duur_s = _duur_s(samen)
    duur_uren = duur_s / 3600.0

    if marktprijzen is not None and not marktprijzen.empty:
        samen = _koppel_marktprijzen(samen, marktprijzen)
        koopdrempel, verkoopdrempel = _arbitragedrempels(samen, batterij, duur_uren)
        samen = samen.assign(
            koopdrempel=koopdrempel.to_numpy(), verkoopdrempel=verkoopdrempel.to_numpy(),
            piekgrens_kwh=_bestaande_maandpiek_kwh(samen).to_numpy(),
        )
    else:
        samen = samen.assign(
            price_eur_mwh=float("nan"), koopdrempel=float("nan"), verkoopdrempel=float("nan"),
            piekgrens_kwh=float("nan"),
        )

    rijen = []
    for rij in samen.itertuples(index=False):
        netto_kwh = rij.productie_kwh - rij.verbruik_kwh  # >0 overschot, <0 tekort

        modus = "zelfconsumptie"
        if not math.isnan(rij.price_eur_mwh):
            if rij.price_eur_mwh <= rij.koopdrempel:
                modus = "arbitrage_koop"
                # Nooit meer laden dan de bestaande maandpiek toelaat: laad_kwh
                # zodanig dat de resulterende afname (-netto_kwh + laad_kwh)
                # de piek van die maand niet overschrijdt.
                wenselijk_kwh = min(
                    batterij.max_charge_w / 1000.0 * duur_uren,
                    max(0.0, rij.piekgrens_kwh + netto_kwh),
                )
            elif rij.price_eur_mwh >= rij.verkoopdrempel:
                modus = "arbitrage_verkoop"
                wenselijk_kwh = -(batterij.max_discharge_w / 1000.0 * duur_uren)
            else:
                wenselijk_kwh = netto_kwh
        else:
            wenselijk_kwh = netto_kwh

        laad_kwh = 0.0
        ontlaad_kwh = 0.0
        if wenselijk_kwh > 0:
            vermogen_w = (wenselijk_kwh / duur_uren) * 1000.0
            laad_kwh = batterij.laad(vermogen_w=vermogen_w, duur_s=duur_s)
        elif wenselijk_kwh < 0:
            vermogen_w = (-wenselijk_kwh / duur_uren) * 1000.0
            ontlaad_kwh = batterij.ontlaad(vermogen_w=vermogen_w, duur_s=duur_s)

        netto_net_kwh = -netto_kwh + laad_kwh - ontlaad_kwh
        afname_kwh = max(netto_net_kwh, 0.0)
        injectie_kwh = max(-netto_net_kwh, 0.0)

        rijen.append({
            "tijdstip": rij.tijdstip,
            "afname_kwh": afname_kwh,
            "injectie_kwh": injectie_kwh,
            "batterij_soc_pct": batterij.state_of_charge,
            "batterij_laad_kwh": laad_kwh,
            "batterij_ontlaad_kwh": ontlaad_kwh,
            "modus": modus,
        })

    return pd.DataFrame(rijen)


def simuleer_ev_laadprofiel(
    ev: "ElektrischeWagen",
    *,
    km_per_jaar: Decimal,
    van: "date",
    tot: "date",
    laadvenster: tuple[int, int] = (22, 6),
) -> tuple[pd.DataFrame, Aanname]:
    """Een EV-laadprofiel over `[van, tot)`, uit een jaarkilometrage.

    Er is geen rijgedrag- of laadprofiel in dit project (in tegenstelling tot
    PV/batterij, die op SPP/RLP0 kunnen steunen) — dit is dus bewust een
    eenvoudig, gedocumenteerd model: `km_per_jaar` wordt via
    `ev.verbruik_per_100km_kwh` omgezet naar kWh, naar rato van de dagen in
    `[van, tot)` (dezelfde pro-rata-aanname als `dagaandeel()` elders in dit
    project maakt), en vervolgens **vlak verdeeld over een nachtelijk
    laadvenster** (standaard 22u-6u lokale tijd, elke dag opnieuw) —
    "s nachts opladen" is de gangbare aanbeveling en de eenvoudigste vorm die
    niet a priori een piekbelasting op het net veronderstelt.

    Geeft een `Aanname` terug die dit expliciet maakt: elk ander laadgedrag
    (overdag op het werk, enkel in het weekend, ...) geeft een andere
    tijdsverdeling — en dus een andere netkost — met hetzelfde jaartotaal.

    Raises `DispatchError` als het laadvenster fysiek te kort is om de
    gevraagde energie binnen `ev.max_laadvermogen_ac_w` te laden.
    """
    dagen = (tot - van).days
    if dagen <= 0:
        raise DispatchError(f"[{van}, {tot}) loopt niet vooruit.")

    jaarverbruik_kwh = km_per_jaar * D(str(ev.verbruik_per_100km_kwh)) / D("100")
    kwh_periode = jaarverbruik_kwh * D(dagen) / D("365")

    tijdstippen = pd.date_range(van, tot, freq="15min", tz="Europe/Brussels", inclusive="left")
    lokaal_uur = tijdstippen.hour
    start, einde = laadvenster
    if start <= einde:
        in_venster = (lokaal_uur >= start) & (lokaal_uur < einde)
    else:  # het venster loopt over middernacht heen, bv. 22u-6u
        in_venster = (lokaal_uur >= start) | (lokaal_uur < einde)

    aantal_sloten = int(in_venster.sum())
    if aantal_sloten == 0:
        raise DispatchError(f"Laadvenster {laadvenster} bevat geen enkel kwartier in [{van}, {tot}).")

    max_kwh_per_slot = ev.max_laadvermogen_ac_w * 0.25 / 1000.0
    kwh_per_slot = float(kwh_periode) / aantal_sloten
    if kwh_per_slot > max_kwh_per_slot:
        raise DispatchError(
            f"Het laadvenster {laadvenster} ({aantal_sloten} kwartieren) is te kort om "
            f"{kwh_periode:.0f} kWh te laden binnen {ev.max_laadvermogen_ac_w:.0f} W AC "
            f"({max_kwh_per_slot * aantal_sloten:.0f} kWh maximaal beschikbaar)."
        )

    kwh = pd.Series(0.0, index=range(len(tijdstippen)))
    kwh[in_venster] = kwh_per_slot

    reeks = pd.DataFrame({
        "tijdstip": pd.to_datetime(tijdstippen, utc=True),
        "kwh": kwh.to_numpy(),
    })
    aanname = Aanname(
        veld="ev_laadprofiel",
        waarde=f"{km_per_jaar} km/jaar, laadvenster {laadvenster[0]}u-{laadvenster[1]}u",
        bron="Gemodelleerd: vlakke verdeling over een nachtelijk laadvenster",
        geverifieerd=False,
        beinvloedt_bedrag=True,
        motivering=(
            f"Geen rijgedrag-/laadprofiel beschikbaar; {jaarverbruik_kwh:.0f} kWh/jaar "
            f"({km_per_jaar} km x {ev.verbruik_per_100km_kwh} kWh/100km) is vlak verdeeld "
            f"over het laadvenster {laadvenster[0]}u-{laadvenster[1]}u lokale tijd. Een "
            "ander laadgedrag geeft een andere tijdsverdeling en dus een andere netkost "
            "bij dezelfde jaarenergie."
        ),
    )
    return reeks, aanname


def simuleer_warmtepomp_profiel(
    wp: "Warmtepomp",
    *,
    warmtevraag_kwh_jaar: Decimal,
    profielgewichten: pd.DataFrame,
) -> tuple[pd.DataFrame, Aanname]:
    """Elektrisch verbruik van een warmtepomp, uit een jaarwarmtevraag.

    Er bestaat geen warmtevraagprofiel in dit project; `profielgewichten`
    hoort daarom het **RLP0-gasprofiel** te zijn (via
    `gebruikers.schatting.gewichten_uit_databank(conn, "rlp0n", jaar,
    "gas")`) — dat profiel is al "winterzwaar" opgebouwd voor de verdeling
    van een gasjaarverbruik over de tariefperiodes (zie CLAUDE.md
    "Aardgas: drie grootheden die niet hetzelfde schalen"), en diezelfde
    seizoensvorm is een redelijke proxy voor de vorm van een warmtevraag —
    beide volgen het buitenklimaat.

    De COP blijft op elk interval de **nominale** waarde
    (`wp.t_bron_nominaal_c`/`wp.t_afgifte_nominaal_c`, bv. A7/W35): er is geen
    buitentemperatuurreeks om `wp.verwarm()` een echte bron-/afgiftetemperatuur
    per interval te geven. Bij lagere buitentemperaturen (net wanneer de vraag
    het hoogst is) ligt de werkelijke COP lager dan de nominale — dit model
    onderschat het elektrisch verbruik dus systematisch in de koudste
    intervallen. Vandaar de `Aanname` met `geverifieerd=False`.

    Geeft `(reeks, aanname)` terug, `reeks` in de vorm `tijdstip`/`kwh`
    (elektrisch verbruik) — rechtstreeks bruikbaar als extra afnamereeks.
    """
    thermische_vraag = verdeel_jaarverbruik(warmtevraag_kwh_jaar, profielgewichten, "rlp0n")
    duur_s = _duur_s(thermische_vraag)
    duur_uren = duur_s / 3600.0

    elektrisch_kwh = []
    for thermisch_kwh in thermische_vraag["kwh"]:
        vermogen_w = (thermisch_kwh / duur_uren) * 1000.0 if duur_uren else 0.0
        _, verbruikt_kwh = wp.verwarm(
            vermogen_w, wp.t_bron_nominaal_c, wp.t_afgifte_nominaal_c, duur_s,
        )
        elektrisch_kwh.append(verbruikt_kwh)

    reeks = pd.DataFrame({
        "tijdstip": thermische_vraag["tijdstip"],
        "kwh": elektrisch_kwh,
    })
    aanname = Aanname(
        veld="warmtepomp_elektrisch_verbruik",
        waarde=f"{warmtevraag_kwh_jaar} kWh warmtevraag/jaar, RLP0-gasvorm, COP nominaal ({wp.cop_nominaal})",
        bron="Gemodelleerd: RLP0-gasprofiel als proxy voor warmtevraag-seizoenaliteit, vaste nominale COP",
        geverifieerd=False,
        beinvloedt_bedrag=True,
        motivering=(
            "Geen warmtevraagprofiel of buitentemperatuurreeks beschikbaar; de "
            "seizoensvorm van het RLP0-gasprofiel is gebruikt als proxy en de COP "
            "blijft op elk interval de nominale waarde staan. Bij koud weer, "
            "wanneer de vraag het hoogst is, ligt de werkelijke COP lager — dit "
            "model onderschat het elektrisch verbruik dus in de koudste periodes."
        ),
    )
    return reeks, aanname
