"""Verdeelt een jaarverbruik over kwartieren met de Synergrid-profielen.

Manifest §9 zet de voorkeursvolgorde: werkelijke intervalmetingen, dan
maandmetingen, dan een officieel profiel (RLP0N, SLP-EX), dan een
gedocumenteerd aangepast profiel, en pas als laatste een vlak profiel — en dat
laatste uitsluitend voor demonstratie. Deze module dekt stap 3.

Drie eigenschappen van de brondata die hier hard afgedwongen worden, omdat ze
door elkaar halen een stil verkeerd getal oplevert:

- **SLP-EX en RLP0N sommeren tot 1.** Het zijn verdelingen: `kWh_t =
  jaarverbruik x gewicht_t`.
- **SPP sommeert níet tot 1.** Het is productie *per kWp geïnstalleerd
  vermogen*: `kWh_t = kWp x spp_t`. Wie SPP als verdeling gebruikt, verdeelt
  een jaarproductie die hij niet kent over gewichten die geen verdeling zijn.
- **Een genormaliseerd profiel geeft geen maandpiek.** De piek van het profiel
  is de piek van een gemiddelde over duizenden aansluitingen, niet die van dit
  gezin. Het capaciteitstarief erop baseren geeft een bedrag dat er plausibel
  uitziet en het niet is. `maandpieken_uit_profiel()` bestaat daarom alleen om
  te weigeren.

RLP0N-elektriciteit is per netbeheerder (kolom per GLN); RLP0N-gas is een
nationaal profiel op uurresolutie met de gasdag die om 06:00 CET begint.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Optional

import pandas as pd

from energie_vlaanderen.gebruikers.models import (
    Aanname,
    Exactheidsklasse,
    GebruikersError,
)
from energie_vlaanderen.utility.constants import D

# Profielen die een verdeling zijn en dus tot 1 sommeren over het jaar.
GENORMALISEERDE_PROFIELEN = frozenset({"slp_ex", "rlp0n"})
# Profielen die een opbrengst per eenheid vermogen zijn.
PRODUCTIEPROFIELEN = frozenset({"spp"})

# Marge op de som-tot-1-controle. De brondata heeft tot 16 decimalen en wordt
# als double bewaard (zie `verbruiksprofiel_waarde.waarde` in schema.py); over
# 35.040 kwartieren stapelt de afrondingsfout van floating point zich op. Een
# afwijking van meer dan een tienduizendste is geen afronding meer maar een
# onvolledig of dubbel ingelezen profiel.
SOM_MARGE = 1e-4


class SchattingError(GebruikersError):
    """Het verbruik is niet te schatten met de beschikbare profielen."""


@dataclass(frozen=True)
class Reeks:
    """Een tijdreeks met de herkomst en de betrouwbaarheid erbij."""

    waarden: pd.DataFrame  # kolommen: tijdstip, kwh
    exactheidsklasse: Exactheidsklasse
    aannames: tuple[Aanname, ...] = ()
    dekkingsgraad: Decimal = D("1")

    @property
    def totaal_kwh(self) -> Decimal:
        return D(str(self.waarden["kwh"].sum()))


class ProfielenUitCsv:
    """Leest de profielen die `ingest/profielen/pipeline.py` heeft weggeschreven.

    Leest uit `<staging|versie>/profielen/`, niet uit de databank: zo werkt het
    schatten zonder databankverbinding en is het in een test te draaien. De
    databankvariant leest dezelfde kolommen uit `verbruiksprofiel_waarde`.
    """

    def __init__(self, directory: Path) -> None:
        self.directory = Path(directory)
        if not self.directory.is_dir():
            raise SchattingError(
                f"Profielenmap niet gevonden: {self.directory}. Draai eerst "
                "`energievergelijker staging parse --only profielen`."
            )

    def _pad(self, profiel_type: str, energie_type: str, jaar: int) -> Path:
        stam = f"{profiel_type}_{energie_type}_{jaar}" if energie_type else f"{profiel_type}_{jaar}"
        pad = self.directory / f"{stam}.csv"
        if not pad.is_file():
            beschikbaar = ", ".join(sorted(p.name for p in self.directory.glob("*.csv"))) or "geen"
            raise SchattingError(
                f"Profiel {stam} niet gevonden in {self.directory}. "
                f"Beschikbaar: {beschikbaar}."
            )
        return pad

    def gewichten(
        self,
        profiel_type: str,
        jaar: int,
        energie_type: str = "",
        netbeheerder_gln: Optional[str] = None,
    ) -> pd.DataFrame:
        """De profielreeks als `tijdstip` (UTC) + `gewicht`."""
        pad = self._pad(profiel_type, energie_type, jaar)
        df = pd.read_csv(
            pad,
            sep=";",
            encoding="utf-8-sig",
            usecols=["tijdstip", "netbeheerder_gln", "waarde"],
            dtype={"netbeheerder_gln": "string"},
        )
        if netbeheerder_gln:
            df = df[df["netbeheerder_gln"].fillna("") == str(netbeheerder_gln)]
            if df.empty:
                raise SchattingError(
                    f"Profiel {profiel_type} {jaar} bevat geen kolom voor "
                    f"netbeheerder-GLN {netbeheerder_gln}."
                )
        else:
            # Nationale profielen dragen geen GLN. Staat er wél een, dan is dit
            # een breed profiel en zou zonder filter elke netbeheerder
            # opgeteld worden — een som van acht verdelingen is geen verdeling.
            met_gln = df["netbeheerder_gln"].fillna("").ne("")
            if met_gln.any():
                raise SchattingError(
                    f"Profiel {profiel_type} {jaar} is per netbeheerder "
                    "opgebouwd; geef een netbeheerder-GLN mee. Zonder filter "
                    "zouden alle netbeheerders bij elkaar opgeteld worden."
                )
        df = df.rename(columns={"waarde": "gewicht"})[["tijdstip", "gewicht"]]
        df["tijdstip"] = pd.to_datetime(df["tijdstip"], utc=True)
        return df.sort_values("tijdstip").reset_index(drop=True)


def dichtstbijzijnd_beschikbaar_jaar(
    conn, profiel_type: str, energie_type: str, gevraagd_jaar: int,
) -> tuple[int, bool]:
    """Het jaar van `profiel_type` in de databank dat het dichtst bij
    `gevraagd_jaar` ligt, en of dat een substitutie was.

    Zelfde regel als `gasaandeel_uit_rlp0()`: Synergrid publiceert per jaar,
    maar niet elk jaar staat (nog) in de databank — vandaag enkel 2026.
    Weigeren zou een scenario over 2025 onmogelijk maken terwijl de
    seizoensvorm van een profiel zich jaar na jaar herhaalt. De oproeper is
    verantwoordelijk om de substitutie in een `Aanname` te vermelden zodra
    die niet `False` teruggeeft.
    """
    import sqlalchemy as sa

    voorwaarden = ["profiel_type = :profiel_type"]
    params: dict[str, object] = {"profiel_type": profiel_type}
    if energie_type:
        voorwaarden.append("energie_type = :energie_type")
        params["energie_type"] = energie_type

    beschikbaar = sorted(
        int(r[0]) for r in conn.execute(
            sa.text(
                "select distinct jaar from verbruiksprofiel_waarde where "
                + " and ".join(voorwaarden)
            ),
            params,
        )
    )
    if not beschikbaar:
        raise SchattingError(
            f"Geen {profiel_type}-profiel in de databank. Laad het met "
            "`synergrid download` en `staging parse --only profielen`."
        )
    if gevraagd_jaar in beschikbaar:
        return gevraagd_jaar, False
    return min(beschikbaar, key=lambda j: (abs(j - gevraagd_jaar), j)), True


def gewichten_uit_databank(
    conn,
    profiel_type: str,
    jaar: int,
    energie_type: str = "",
    netbeheerder_code: Optional[str] = None,
) -> pd.DataFrame:
    """Zelfde contract als `ProfielenUitCsv.gewichten()` (`tijdstip`, `gewicht`),
    maar rechtstreeks uit `verbruiksprofiel_waarde` in de databank.

    Deze functie bestaat naast de CSV-lezer, niet in de plaats ervan:
    `ProfielenUitCsv` werkt zonder databankverbinding (handig in een test), dit
    hier is voor code die toch al een `conn` open heeft — zoals
    `scenario.batterij`/`scenario.zonnepaneel`, die de databank sowieso nodig
    hebben voor de kostberekening. Zelfde regel als `gasaandeel_uit_rlp0()`
    hierboven: per-netbeheerderprofielen (RLP0N-elektriciteit) eisen een
    `netbeheerder_code`, nationale profielen (SLP-EX, SPP, RLP0N-gas) nemen
    geen filter.
    """
    import sqlalchemy as sa

    voorwaarden = ["profiel_type = :profiel_type", "jaar = :jaar"]
    params: dict[str, object] = {"profiel_type": profiel_type, "jaar": jaar}
    if energie_type:
        voorwaarden.append("energie_type = :energie_type")
        params["energie_type"] = energie_type
    if netbeheerder_code:
        voorwaarden.append("netbeheerder_code = :netbeheerder_code")
        params["netbeheerder_code"] = netbeheerder_code

    query = (
        "select tijdstip, waarde from verbruiksprofiel_waarde where "
        + " and ".join(voorwaarden)
        + " order by tijdstip"
    )
    rijen = conn.execute(sa.text(query), params).all()
    if not rijen:
        raise SchattingError(
            f"Geen {profiel_type}-profiel in de databank voor jaar {jaar}"
            + (f", netbeheerder {netbeheerder_code}" if netbeheerder_code else "")
            + ". Laad het met `synergrid download` en "
            "`staging parse --only profielen`."
        )

    df = pd.DataFrame(rijen, columns=["tijdstip", "gewicht"])
    # Naar UTC normaliseren vóór elke vergelijking of telling op `tijdstip`:
    # twee aware datetimes met dezelfde wandkloktijd maar een andere `fold`
    # (de dubbele lokale 2u-nacht bij de terugval naar wintertijd) vergelijken
    # in kale Python als *gelijk* — `fold` wordt genegeerd bij `==`/`hash()`
    # zodra beide dezelfde tzinfo dragen (een gedocumenteerde CPython-
    # eigenaardigheid, geen bug in de data). Op de databank staat dat uur wél
    # correct als twee verschillende UTC-instanten (2026-10-25 00:00 en
    # 01:00 UTC) — enkel de naïeve Python-vergelijking zag ze als één.
    df["tijdstip"] = pd.to_datetime(df["tijdstip"], utc=True)

    if netbeheerder_code is None and profiel_type in GENORMALISEERDE_PROFIELEN:
        # Dezelfde vangrail als `ProfielenUitCsv.gewichten()`: zonder filter op
        # een per-netbeheerderprofiel zou de query hierboven alle
        # netbeheerders bij elkaar optellen als er meer dan één rij per
        # tijdstip bestaat (geen fout, gewoon een verkeerd getal).
        aantal_tijdstippen = df["tijdstip"].nunique()
        if aantal_tijdstippen and len(df) > aantal_tijdstippen:
            raise SchattingError(
                f"Profiel {profiel_type} {jaar} is per netbeheerder "
                "opgebouwd; geef een netbeheerder_code mee. Zonder filter "
                "zouden alle netbeheerders bij elkaar opgeteld worden."
            )

    return df.sort_values("tijdstip").reset_index(drop=True)


def controleer_som(gewichten: pd.DataFrame, profiel_type: str) -> float:
    """Toetst de som-tot-1-eis, en alleen waar die geldt."""
    som = float(gewichten["gewicht"].sum())
    if profiel_type in GENORMALISEERDE_PROFIELEN and abs(som - 1.0) > SOM_MARGE:
        raise SchattingError(
            f"Profiel {profiel_type} sommeert tot {som:.8f} in plaats van 1. "
            "Een verdeling die niet tot 1 sommeert verdeelt het jaarverbruik "
            "verkeerd; de berekening stopt in plaats van een te hoog of te "
            "laag verbruik door te rekenen."
        )
    return som


def verdeel_jaarverbruik(
    jaarverbruik_kwh: Decimal,
    gewichten: pd.DataFrame,
    profiel_type: str,
) -> pd.DataFrame:
    """`kWh_t = jaarverbruik x gewicht_t` voor een genormaliseerd profiel."""
    if profiel_type not in GENORMALISEERDE_PROFIELEN:
        raise SchattingError(
            f"{profiel_type} is geen verdeling en mag niet gebruikt worden om "
            "een jaarverbruik te spreiden. SPP is productie per kWp — gebruik "
            "`productie_uit_kwp()`."
        )
    controleer_som(gewichten, profiel_type)
    uit = gewichten.copy()
    uit["kwh"] = uit["gewicht"] * float(jaarverbruik_kwh)
    return uit[["tijdstip", "kwh"]]


def intervalduur_uren(gewichten: pd.DataFrame) -> Decimal:
    """De lengte van één interval in uren, uit de tijdstempels zelf.

    Niet vastgezet op een kwartier: RLP0N-gas is uurresolutie. De mediaan en
    niet het eerste verschil, zodat een gat in de reeks de duur niet bepaalt.
    """
    stap = pd.to_datetime(gewichten["tijdstip"], utc=True).diff().dropna().median()
    if pd.isna(stap) or stap <= pd.Timedelta(0):
        raise SchattingError(
            "De profielreeks heeft geen bruikbare tijdstap; de intervalduur is "
            "niet af te leiden."
        )
    return D(str(stap / pd.Timedelta(hours=1)))


def productie_uit_kwp(kwp: Decimal, gewichten: pd.DataFrame) -> pd.DataFrame:
    """`kWh_t = kWp x spp_t x dt_uren` — SPP is *vermogen*, geen energie.

    Het SPP-werkboek zegt het zelf, op het blad "Read Me First": *"SPP-value
    expressed in mW/mWp"*, dus MW per MWp — een dimensieloze
    vermogensverhouding, gelijk aan kW per kWp. Om er energie van te maken moet
    er met de intervalduur vermenigvuldigd worden.

    Dat is geen detail: over 2026 sommeren de kwartierwaarden tot 4.119,94. Als
    energie gelezen zou dat 4.120 kWh per kWp per jaar zijn — vier keer de
    werkelijke Vlaamse opbrengst. Maal 0,25 uur wordt het 1.030 kWh/kWp/jaar,
    wat wél klopt met wat een PV-installatie in Vlaanderen opbrengt. Precies de
    soort fout die dit project telkens raakt: geen crash, alleen een bedrag dat
    er vier keer naast zit.

    Er is hier bewust géén som-tot-1-controle: die zou op SPP altijd falen, en
    ze uitzetten voor alle profielen zou de controle op SLP-EX en RLP0N mee
    uitschakelen.
    """
    if kwp is None or kwp <= 0:
        raise SchattingError(
            "PV-productie schatten vereist een paneelvermogen in kWp groter "
            "dan nul; SPP is opbrengst per kWp."
        )
    duur = intervalduur_uren(gewichten)
    uit = gewichten.copy()
    uit["kwh"] = uit["gewicht"] * float(kwp) * float(duur)
    return uit[["tijdstip", "kwh"]]


def maandpieken_uit_profiel(*_args, **_kwargs):
    """Bestaat om te weigeren.

    De piek van een genormaliseerd profiel is de piek van het gemiddelde over
    duizenden aansluitingen en niet die van dit gezin: profielen zijn glad waar
    een echt huishouden schokt. Het capaciteitstarief erop baseren geeft een
    bedrag dat plausibel oogt en systematisch te laag is. Manifest §12 laat bij
    ontbrekende maandpieken alleen een *gedocumenteerde* schatting toe — dat is
    `Profile.geschatte_maandpiek_kw` (4,218 kW, teruggerekend uit vtest.be), niet
    een afgeleide van een profiel.
    """
    raise SchattingError(
        "Uit een genormaliseerd verbruiksprofiel is geen maandpiek af te "
        "leiden. Gebruik gemeten kwartierdata (`maandpieken_uit_metingen`) of "
        "de gedocumenteerde standaardpiek uit het gebruikersprofiel."
    )


def maandpieken_uit_metingen(metingen: pd.DataFrame, jaar: int) -> tuple[Decimal, ...]:
    """De twaalf maandpieken in kW uit werkelijke kwartierdata.

    Een maandpiek is het hoogste kwartiergemiddelde in die maand, uitgedrukt in
    kW: `max(afname_kwh per kwartier) x 4`. De factor 4 zet kWh per kwartier om
    naar kW gemiddeld vermogen — vergeten wordt de piek een kwart van wat ze is.

    Maanden zonder meting krijgen geen piek van nul: dat zou de laagste maand
    van het jaar verzinnen. Ze worden overgeslagen, en de oproeper ziet aan de
    lengte van de uitkomst dat het jaar niet volledig gedekt is.
    """
    if metingen.empty:
        return ()
    df = metingen.copy()
    df["tijdstip"] = pd.to_datetime(df["tijdstip"], utc=True)
    df = df[df["tijdstip"].dt.year == jaar]
    if df.empty:
        return ()
    stap = df["tijdstip"].diff().dropna().median()
    if pd.isna(stap) or stap <= pd.Timedelta(0):
        raise SchattingError("De meetreeks heeft geen bruikbare tijdstap.")
    per_uur = D(str(pd.Timedelta(hours=1) / stap))
    per_maand = df.groupby(df["tijdstip"].dt.month)["afname_kwh"].max()
    return tuple(D(str(waarde)) * per_uur for _, waarde in sorted(per_maand.items()))


def dekkingsgraad(metingen: pd.DataFrame, van: date, tot: date) -> Decimal:
    """Welk deel van `[van, tot)` de meetreeks werkelijk dekt.

    Manifest §9 en §12: onvoldoende meetdekking wordt zichtbaar gerapporteerd,
    nooit stil aangevuld. De uitkomst verlaagt de exactheidsklasse van elk
    bedrag dat op deze reeks steunt.
    """
    if metingen.empty:
        return D("0")
    df = metingen.copy()
    df["tijdstip"] = pd.to_datetime(df["tijdstip"], utc=True)
    grens_van = pd.Timestamp(datetime(van.year, van.month, van.day), tz="UTC")
    grens_tot = pd.Timestamp(datetime(tot.year, tot.month, tot.day), tz="UTC")
    binnen = df[(df["tijdstip"] >= grens_van) & (df["tijdstip"] < grens_tot)]
    if binnen.empty:
        return D("0")
    stap = binnen["tijdstip"].diff().dropna().median()
    if pd.isna(stap) or stap <= pd.Timedelta(0):
        return D("0")
    verwacht = (grens_tot - grens_van) / stap
    if verwacht <= 0:
        return D("0")
    aandeel = D(str(len(binnen))) / D(str(verwacht))
    return min(aandeel, D("1"))


def gasaandeel_uit_rlp0(
    conn,
    van: date,
    tot: date,
    jaar_profiel: int | None = None,
) -> tuple[Decimal, Aanname]:
    """Welk deel van een jaarverbruik gas in `[van, tot)` valt, volgens RLP0.

    Het VREG-werkboek schrijft dit voor: "Voor de effectief toe te passen
    tarieven dienen de gemeten kWh over de verschillende tariefperioden
    verdeeld te worden op basis van het reëel lastprofiel RLP0."

    Naar dagen verdelen is bij aardgas geen benadering maar een systematische
    fout. Over 25/06/2025-30/04/2026 valt 53,8% van het volume in de 120 dagen
    van januari tot april, waar dagen 32,9% zouden geven — en die maanden
    liggen in het duurdere tariefjaar. Wie naar dagen verdeelt, rekent te
    weinig aan.

    Er komt een `Aanname` mee terug, en die hoort er: het profiel is dat van
    een gemiddelde aansluiting, niet van deze. Voor een huis met een
    warmtepomp of een gasfornuis-only aansluiting is de vorm anders. Zodra er
    een gasmeetreeks is, hoort die voor te gaan.
    """
    import sqlalchemy as sa

    beschikbaar = sorted(
        int(r[0])
        for r in conn.execute(
            sa.text(
                "select distinct jaar from verbruiksprofiel_waarde "
                "where energie_type = 'gas' and profiel_type = 'rlp0n'"
            )
        )
    )
    if not beschikbaar:
        raise SchattingError(
            "Geen RLP0N-gasprofiel in de databank. Zonder profiel is het "
            "jaarverbruik niet over de tariefperiodes te verdelen; laad het "
            "met `synergrid download` en `staging parse --only profielen`."
        )

    gevraagd = jaar_profiel if jaar_profiel is not None else tot.year
    # Synergrid publiceert per jaar, maar niet elk jaar staat in de databank.
    # Weigeren zou een berekening over 2025 onmogelijk maken terwijl alleen het
    # profiel van 2026 er is -- en de seizoensvorm van gasverbruik herhaalt
    # zich. Het dichtstbijzijnde jaar wordt gebruikt, en dát wordt gezegd: de
    # aanname reist mee tot in het eindbedrag.
    jaar_profiel = (
        gevraagd if gevraagd in beschikbaar
        else min(beschikbaar, key=lambda j: (abs(j - gevraagd), j))
    )

    rijen = conn.execute(
        sa.text(
            """
            select tijdstip at time zone 'Europe/Brussels' as lokaal, waarde
              from verbruiksprofiel_waarde
             where energie_type = 'gas'
               and profiel_type = 'rlp0n'
               and jaar = :jaar
            """
        ),
        {"jaar": jaar_profiel},
    ).all()

    # Het profiel is een kalenderjaar; het venster kan een jaargrens kruisen.
    # De vorm herhaalt zich, dus elk tijdstip wordt op zijn dag-van-het-jaar
    # gelegd en zo tegen het venster gehouden.
    totaal = Decimal("0")
    binnen = Decimal("0")
    dagen_in_venster = {
        (van + timedelta(days=i)).timetuple().tm_yday
        for i in range((tot - van).days)
    }
    for lokaal, waarde in rijen:
        w = Decimal(str(waarde))
        totaal += w
        if lokaal.timetuple().tm_yday in dagen_in_venster:
            binnen += w

    if totaal <= 0:
        raise SchattingError(
            f"Het RLP0N-gasprofiel voor {jaar_profiel} sommeert tot {totaal}; "
            "verdelen is dan niet mogelijk."
        )

    aandeel = binnen / totaal
    naar_dagen = Decimal((tot - van).days) / Decimal("365")
    ander_jaar = jaar_profiel != gevraagd
    return aandeel, Aanname(
        veld="gasverdeling_over_de_tariefperiodes",
        waarde=f"{aandeel:.4f}",
        bron=f"RLP0N-gasprofiel {jaar_profiel} (Synergrid), uit de databank",
        # Het profiel zelf is geverifieerde brondata; het toepassen op een
        # ánder jaar is dat niet.
        geverifieerd=not ander_jaar,
        beinvloedt_bedrag=True,
        motivering=(
            f"Het jaarverbruik is met het reëel lastprofiel RLP0 over de "
            f"periode verdeeld, zoals het VREG-werkboek voorschrijft: "
            f"{aandeel:.1%} valt in dit venster tegenover {naar_dagen:.1%} bij "
            "een verdeling naar dagen. Het profiel is dat van een gemiddelde "
            "aansluiting, niet van deze."
            + (
                f" Het profiel van {jaar_profiel} is gebruikt voor een periode "
                f"in {gevraagd}; die jaargang staat niet in de databank. De "
                "seizoensvorm van gasverbruik herhaalt zich, maar het is een "
                "aanname."
                if ander_jaar
                else ""
            )
        ),
    )
