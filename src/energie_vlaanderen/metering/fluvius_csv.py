"""Leest een Fluvius-verbruikshistoriek in.

Fluvius levert de meetgegevens van een digitale meter als CSV: kwartiertotalen
voor elektriciteit, uurtotalen voor aardgas. Dat bestand is de enige bron van
werkelijk verbruik die een gebruiker zelf kan aanleveren, en het maakt het
verschil tussen een geschatte en een exacte factuurreconstructie.

Vier eigenschappen van het echte bestand bepalen de vorm van deze module. Alle
vier zijn gevonden door een export van drie jaar (210.625 regels elektriciteit,
52.657 gas) te ontleden; de vorige implementatie ging op alle vier de fout in.

**1. Er zijn vier registers, geen twee.** "Afname Dag", "Afname Nacht",
"Injectie Dag" en "Injectie Nacht". Alleen op "afname" en "injectie" matchen
gooit het dag-/nachtonderscheid weg — precies het onderscheid dat het
nettarief en de meeste leveranciersproducten nodig hebben.

**2. Een gasexport bevat elk interval twee keer**: één regel in m³ en één in
kWh. Optellen per tijdstip telt dan volume en energie bij elkaar op, en dat
getal betekent niets. Er wordt op `Eenheid == "kWh"` gefilterd.

**3. `Validatiestatus` onderscheidt drie dingen.** "Uitgelezen" is een echte
meting, "Geschat" een schatting van Fluvius zelf (mét waarde), en "Geen
verbruik" betekent dat er géén meting is — daar staat een leeg volume. Dat leeg
volume op nul zetten maakt van een ontbrekende meting een gemeten nul, en
Manifest §12 verbiedt precies dat. In de aangeleverde export ging het om 193
kwartieren zonder meting en 508 geschatte.

**4. De tijdstempels staan in lokale tijd, mét de zomertijdsprongen erin.** Op
de laatste zondag van oktober telt de dag 100 kwartieren op 96 unieke lokale
tijdstippen: 02:00 tot 02:45 komt twee keer voor. Groeperen op tijdstip plakt
die twee uren samen. In maart ontbreken die kwartieren juist. Elk register
wordt daarom apart omgezet, waarbij de volgorde binnen het register de twee
doorgangen uit elkaar houdt.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from typing import Optional

import pandas as pd

from energie_vlaanderen.utility.constants import D, LOCAL_TZ, UTC
from energie_vlaanderen.utility.normalizer import clean_text

LOG = logging.getLogger(__name__)

# Registernaam (kleingeschreven) -> kolom in de uitvoer.
REGISTERKOLOMMEN = {
    "afname dag": "afname_dag_kwh",
    "afname nacht": "afname_nacht_kwh",
    "injectie dag": "injectie_dag_kwh",
    "injectie nacht": "injectie_nacht_kwh",
    # Aardgas kent geen dag-/nachtregister.
    "afname": "afname_kwh",
    "injectie": "injectie_kwh",
}

ELEKTRICITEITSKOLOMMEN = (
    "afname_dag_kwh",
    "afname_nacht_kwh",
    "injectie_dag_kwh",
    "injectie_nacht_kwh",
)

STATUS_GEMETEN = "uitgelezen"
STATUS_GESCHAT = "geschat"


class FluviusDataError(ValueError):
    """Het Fluviusbestand kan niet betrouwbaar verwerkt worden."""


@dataclass(frozen=True)
class FluviusReeks:
    """Een ingelezen verbruikshistoriek, met de kwaliteit ervan erbij."""

    intervallen: pd.DataFrame
    bron: Path
    energie: str
    ean: str = ""
    metertype: str = ""
    resolutie: Optional[timedelta] = None
    geschatte_intervallen: int = 0
    ontbrekende_intervallen: int = 0
    waarschuwingen: tuple[str, ...] = field(default_factory=tuple)

    @property
    def start(self) -> Optional[pd.Timestamp]:
        return None if self.intervallen.empty else self.intervallen["tijdstip"].min()

    @property
    def eind(self) -> Optional[pd.Timestamp]:
        return None if self.intervallen.empty else self.intervallen["tijdstip"].max()

    def _som(self, kolom: str) -> Decimal:
        if kolom not in self.intervallen:
            return D("0")
        return D(str(self.intervallen[kolom].sum()))

    @property
    def afname_kwh(self) -> Decimal:
        if self.energie == "gas":
            return self._som("afname_kwh")
        return self._som("afname_dag_kwh") + self._som("afname_nacht_kwh")

    @property
    def injectie_kwh(self) -> Decimal:
        if self.energie == "gas":
            return self._som("injectie_kwh")
        return self._som("injectie_dag_kwh") + self._som("injectie_nacht_kwh")

    def tussen(self, van, tot) -> "FluviusReeks":
        """Dezelfde reeks, beperkt tot `[van, tot)` in UTC."""
        binnen = self.intervallen[
            (self.intervallen["tijdstip"] >= pd.Timestamp(van, tz="UTC"))
            & (self.intervallen["tijdstip"] < pd.Timestamp(tot, tz="UTC"))
        ]
        return FluviusReeks(
            intervallen=binnen.reset_index(drop=True),
            bron=self.bron,
            energie=self.energie,
            ean=self.ean,
            metertype=self.metertype,
            resolutie=self.resolutie,
            geschatte_intervallen=int(binnen.get("geschat", pd.Series(dtype=bool)).sum()),
            ontbrekende_intervallen=0,
            waarschuwingen=self.waarschuwingen,
        )

    def maandpieken_kw(self, jaar: int) -> tuple[Decimal, ...]:
        """De twaalf maandpieken in kW, uit de werkelijke kwartierdata.

        Het capaciteitstarief rekent met de hoogste gemiddelde afname over één
        kwartier per maand. Afname dag en nacht worden daarvoor opgeteld: de
        meter kent op elk moment maar één van beide, en de piek is de piek van
        het toegangspunt.

        Maanden zonder meting krijgen géén piek van nul — dat zou de laagste
        maand van het jaar verzinnen. De uitkomst is dan korter dan twaalf, en
        dat is informatie voor de oproeper.
        """
        if self.intervallen.empty or self.resolutie is None:
            return ()
        df = self.intervallen
        df = df[df["tijdstip"].dt.tz_convert(LOCAL_TZ).dt.year == jaar]
        if df.empty:
            return ()
        kolommen = [k for k in ("afname_dag_kwh", "afname_nacht_kwh", "afname_kwh") if k in df]
        totaal = df[kolommen].sum(axis=1)
        maand = df["tijdstip"].dt.tz_convert(LOCAL_TZ).dt.month
        per_uur = D(str(timedelta(hours=1) / self.resolutie))
        return tuple(
            D(str(piek)) * per_uur
            for _, piek in sorted(totaal.groupby(maand).max().items())
        )

    def voor_berekening(self) -> pd.DataFrame:
        """De vorm die `Calculator.supplier_cost()` verwacht.

        Dag en nacht worden hier wél samengeteld: een dynamisch product rekent
        per kwartier tegen de marktprijs en kent geen dag-/nachtonderscheid.
        """
        uit = pd.DataFrame({"tijdstip": self.intervallen["tijdstip"]})
        for doel, bronnen in (
            ("afname_kwh", ("afname_dag_kwh", "afname_nacht_kwh", "afname_kwh")),
            ("injectie_kwh", ("injectie_dag_kwh", "injectie_nacht_kwh", "injectie_kwh")),
        ):
            aanwezig = [k for k in bronnen if k in self.intervallen]
            uit[doel] = (
                self.intervallen[aanwezig].sum(axis=1) if aanwezig else 0.0
            )
        return uit


class FluviusIntervals:
    """Leest een verbruikshistoriek van Fluvius."""

    KOLOM_DATUM = "Van (datum)"
    KOLOM_TIJD = "Van (tijdstip)"

    @classmethod
    def read(cls, path: Path) -> FluviusReeks:
        bestand = Path(path)
        if not bestand.is_file():
            raise FluviusDataError(f"Meetbestand niet gevonden: {bestand}.")

        df = pd.read_csv(bestand, sep=";", dtype=str, encoding="utf-8-sig")
        df.columns = [clean_text(k) for k in df.columns]

        vereist = (cls.KOLOM_DATUM, cls.KOLOM_TIJD, "Register", "Volume")
        ontbreekt = [k for k in vereist if k not in df.columns]
        if ontbreekt:
            raise FluviusDataError(
                f"{bestand.name} mist de kolom(men) {', '.join(ontbreekt)}. "
                "Verwacht wordt een verbruikshistoriek van Fluvius."
            )

        waarschuwingen: list[str] = []

        # Aardgas staat er twee keer in: in m³ en in kWh. Optellen zou volume en
        # energie bij elkaar tellen.
        if "Eenheid" in df.columns:
            eenheden = {clean_text(e).casefold() for e in df["Eenheid"].dropna().unique()}
            if "kwh" in eenheden and len(eenheden) > 1:
                anderen = ", ".join(sorted(eenheden - {"kwh"}))
                waarschuwingen.append(
                    f"Regels in {anderen} overgeslagen; alleen kWh wordt gebruikt."
                )
            df = df[df["Eenheid"].map(lambda e: clean_text(e).casefold() == "kwh")]

        if df.empty:
            raise FluviusDataError(f"{bestand.name} bevat geen kWh-regels.")

        status = df.get("Validatiestatus", pd.Series("", index=df.index))
        status = status.map(lambda s: clean_text(s).casefold())
        volume = cls._volume(df["Volume"])

        # "Geen verbruik" met een leeg volume is géén gemeten nul maar een
        # ontbrekende meting. Ze op 0 zetten zou verbruik verzinnen dat er niet
        # gemeten is.
        ontbrekend = int(volume.isna().sum())
        if ontbrekend:
            statussen = sorted(set(status[volume.isna()]))
            waarschuwingen.append(
                f"{ontbrekend} interval(len) zonder meting (status: "
                f"{', '.join(statussen) or 'onbekend'}); niet als nul geteld."
            )
        df = df[volume.notna()].copy()
        df["_volume"] = volume[volume.notna()]
        df["_geschat"] = status[volume.notna()].eq(STATUS_GESCHAT)

        geschat = int(df["_geschat"].sum())
        if geschat:
            waarschuwingen.append(
                f"{geschat} interval(len) door Fluvius geschat in plaats van "
                "uitgelezen; het resultaat is in zoverre geen meting."
            )

        df["_kolom"] = df["Register"].map(
            lambda r: REGISTERKOLOMMEN.get(clean_text(r).casefold())
        )
        onbekend = sorted({
            clean_text(r) for r, k in zip(df["Register"], df["_kolom"]) if k is None
        })
        if onbekend:
            raise FluviusDataError(
                f"Onbekende registers in {bestand.name}: {', '.join(onbekend)}. "
                "Ze overslaan zou verbruik laten verdwijnen."
            )

        frames = [
            cls._register_naar_utc(deel, naam, waarschuwingen)
            for naam, deel in df.groupby("_kolom", sort=False)
        ]
        samen = pd.concat(frames, ignore_index=True)
        intervallen = (
            samen.pivot_table(
                index="tijdstip", columns="_kolom", values="_volume", aggfunc="sum"
            )
            .fillna(0.0)
            .reset_index()
        )
        intervallen.columns.name = None
        geschat_per_tijdstip = samen.groupby("tijdstip")["_geschat"].any()
        intervallen["geschat"] = intervallen["tijdstip"].map(geschat_per_tijdstip).fillna(False)
        intervallen = intervallen.sort_values("tijdstip").reset_index(drop=True)

        energie = "gas" if "afname_kwh" in intervallen.columns else "elektriciteit"
        for kolom in (ELEKTRICITEITSKOLOMMEN if energie == "elektriciteit" else ("afname_kwh",)):
            if kolom not in intervallen:
                intervallen[kolom] = 0.0

        resolutie = cls._resolutie(intervallen["tijdstip"])
        waarschuwingen.extend(cls._gaten(intervallen["tijdstip"], resolutie))

        return FluviusReeks(
            intervallen=intervallen,
            bron=bestand,
            energie=energie,
            ean=cls._eerste(df, "EAN-code"),
            metertype=cls._eerste(df, "Metertype"),
            resolutie=resolutie,
            geschatte_intervallen=geschat,
            ontbrekende_intervallen=ontbrekend,
            waarschuwingen=tuple(waarschuwingen),
        )

    # -- hulp --------------------------------------------------------------

    @staticmethod
    def _volume(kolom: pd.Series) -> pd.Series:
        """Belgische decimaalkomma naar float; leeg blijft leeg."""
        tekst = kolom.fillna("").map(lambda v: str(v).strip().replace(",", "."))
        return pd.to_numeric(tekst.where(tekst != "", other=None), errors="coerce")

    @staticmethod
    def _eerste(df: pd.DataFrame, kolom: str) -> str:
        if kolom not in df.columns or df.empty:
            return ""
        # De EAN staat in de export als Excel-formule: ="541448...".
        return clean_text(df[kolom].iloc[0]).strip('="')

    @classmethod
    def _register_naar_utc(
        cls, deel: pd.DataFrame, naam: str, waarschuwingen: list[str]
    ) -> pd.DataFrame:
        """Zet de lokale tijdstempels van één register om naar UTC.

        Per register, en niet in één keer over het hele bestand: op de laatste
        zondag van oktober komt elk lokaal tijdstip tussen 02:00 en 03:00 twee
        keer voor. Binnen één register staan die twee doorgangen na elkaar, en
        dáárop kan pandas het onderscheid afleiden. Door elkaar gehusseld met de
        andere registers lukt dat niet.
        """
        lokaal = pd.to_datetime(
            deel[cls.KOLOM_DATUM].str.strip() + " " + deel[cls.KOLOM_TIJD].str.strip(),
            dayfirst=True,
            errors="coerce",
        )
        ongeldig = int(lokaal.isna().sum())
        if ongeldig:
            waarschuwingen.append(
                f"{ongeldig} regel(s) in register {naam} met een onleesbaar tijdstip."
            )
        geldig = lokaal.notna()
        lokaal = lokaal[geldig].sort_values()

        # Welke doorgang is welke? Op de laatste zondag van oktober komt elk
        # lokaal tijdstip tussen 02:00 en 03:00 twee keer voor: eerst nog in
        # zomertijd (UTC+2), daarna in wintertijd (UTC+1). Het bestand staat
        # chronologisch, dus de éérste keer dat een tijdstip verschijnt is de
        # zomertijddoorgang.
        #
        # `ambiguous="infer"` van pandas kan dat ook, maar slechts voor één
        # overgang per aanroep — over een export van drie jaar zijn het er drie
        # of vier en gooit het een fout. Deze vorm werkt voor elk aantal.
        eerste_doorgang = ~lokaal.duplicated(keep="first")
        try:
            utc = lokaal.dt.tz_localize(
                LOCAL_TZ, ambiguous=eerste_doorgang.to_numpy(), nonexistent="raise"
            ).dt.tz_convert(UTC)
        except Exception as exc:
            # Een tijdstip dat lokaal niet bestaat (de overgeslagen zomertijduur
            # in maart) hoort er niet in te staan. Gebeurt het toch, dan is het
            # een fout in de export en schuiven we hem vooruit — met melding,
            # want stil verschuiven verplaatst verbruik naar een ander uur.
            waarschuwingen.append(
                f"Register {naam}: {exc}. De betrokken tijdstippen zijn "
                "vooruitgeschoven."
            )
            utc = lokaal.dt.tz_localize(
                LOCAL_TZ,
                ambiguous=eerste_doorgang.to_numpy(),
                nonexistent="shift_forward",
            ).dt.tz_convert(UTC)

        uit = deel.loc[lokaal.index].copy()
        uit["tijdstip"] = utc
        return uit[["tijdstip", "_kolom", "_volume", "_geschat"]]

    @staticmethod
    def _resolutie(tijdstippen: pd.Series) -> Optional[timedelta]:
        verschillen = tijdstippen.sort_values().diff().dropna()
        if verschillen.empty:
            return None
        mediaan = verschillen.median()
        return None if pd.isna(mediaan) else mediaan.to_pytimedelta()

    @staticmethod
    def _gaten(tijdstippen: pd.Series, resolutie: Optional[timedelta]) -> list[str]:
        """Meld onderbrekingen in de reeks.

        Een gat is niet hetzelfde als nulverbruik: er is dan geen meting, en een
        berekening die dat interval overslaat rekent stil met minder energie.
        """
        if resolutie is None or tijdstippen.empty:
            return []
        stap = pd.Timedelta(resolutie)
        verschillen = tijdstippen.sort_values().diff().dropna()
        gaten = verschillen[verschillen > stap]
        if gaten.empty:
            return []
        ontbrekend = int((gaten / stap - 1).sum())
        return [
            f"{len(gaten)} onderbreking(en) in de reeks, samen ongeveer "
            f"{ontbrekend} ontbrekende interval(len); grootste gat {gaten.max()}."
        ]


# Behouden onder de oude naam: `UsageProfile` was de vorige uitvoer van deze
# module. `FluviusReeks` draagt hetzelfde plus de kwaliteitsinformatie.
UsageProfile = FluviusReeks
