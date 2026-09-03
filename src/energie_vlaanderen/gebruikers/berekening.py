"""Rekent een gebruikersdossier door over een periode, stuk voor stuk.

Dit is de laag tussen de gebruikersbasis en `Calculator`. Ze doet drie dingen
die de rekenengine zelf niet kan:

1. **Knippen.** `periodes.snijd()` deelt het venster op bij elke contractwissel,
   elke bevroren tariefkaart, elk heffingenregime en elke jaarwissel.
2. **Per stuk een `Profile` bouwen.** De rekenengine kent alleen jaartotalen;
   deze module verdeelt het verbruik over de deelperiodes en zegt erbij hoe.
3. **De drie tijdassen uit elkaar houden.** De *prijs* van een vast contract
   komt uit de tariefkaart van bij de ondertekening; de *heffingen* komen uit
   het regime dat in de deelperiode geldt. Dat zijn twee verschillende datums,
   en ze door elkaar halen is precies wat een historische berekening verkeerd
   maakt.

Manifest §10 zet de volgorde: valideer klant en aansluiting, selecteer de
versies op geldigheidsdatum, reken, en bouw provenance en waarschuwingen op.
Manifest §12 zet de ondergrens: een ontbrekend verplicht tarief stopt de
berekening, het wordt nooit een nul.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal
from typing import Optional, Sequence

import pandas as pd

from energie_vlaanderen.calculation.calculator import Calculator
from energie_vlaanderen.data.repository import DataRepository
from energie_vlaanderen.domain.models import Cost, Product, Profile
from energie_vlaanderen.gebruikers.models import (
    Aanname,
    Aansluitingspunt,
    Contracttype,
    EnergieType,
    Exactheidsklasse,
    GebruikersError,
    Leveringscontract,
    Meter,
    Meterregime,
    Verbruiksopgave,
)
from energie_vlaanderen.gebruikers.periodes import Deelperiode, heffingengrenzen, snijd
from energie_vlaanderen.utility.constants import D
from energie_vlaanderen.utility.normalizer import leverancier_sleutel


class BerekeningError(GebruikersError):
    """De kost is voor deze periode niet te berekenen."""


@dataclass(frozen=True)
class PeriodeResultaat:
    periode: Deelperiode
    kost: Cost
    product: Product
    exactheidsklasse: Exactheidsklasse
    aannames: tuple[Aanname, ...] = ()

    @property
    def leverancier(self) -> str:
        return self.periode.contract.leverancier if self.periode.contract else ""

    @property
    def product_naam(self) -> str:
        return self.periode.contract.product if self.periode.contract else ""


@dataclass(frozen=True)
class Berekening:
    """Het volledige resultaat: totalen, de stukken, en waarop ze steunen."""

    van: date
    tot: date
    regels: tuple[PeriodeResultaat, ...]
    exactheidsklasse: Exactheidsklasse
    aannames: tuple[Aanname, ...] = ()
    warnings: tuple[str, ...] = ()

    @property
    def totalen(self) -> dict[str, Decimal]:
        velden = ("supplier", "grid", "levies", "injection_credit", "vat")
        totaal = {veld: sum((getattr(r.kost, veld) for r in self.regels), D("0")) for veld in velden}
        totaal["totaal"] = sum((r.kost.total for r in self.regels), D("0"))
        return totaal


def dagaandeel(opgave: Verbruiksopgave, periode: Deelperiode) -> tuple[Decimal, Aanname]:
    """Welk deel van de verbruiksopgave in deze deelperiode valt, in dagen.

    Pro rata temporis. Dat is een aanname en geen meting: januari en juli
    verbruiken niet evenveel, en wie een leverancierswissel in de zomer zo
    verdeelt legt te veel winterverbruik bij de zomerleverancier. Voor een
    exacte verdeling zijn kwartiermetingen of een Synergrid-profiel nodig; de
    aanname die deze functie teruggeeft zegt dat ook.
    """
    dagen_opgave = (opgave.periode_tot - opgave.periode_van).days
    if dagen_opgave <= 0:
        raise BerekeningError("De verbruiksopgave beslaat geen dagen.")

    overlap_van = max(opgave.periode_van, periode.van)
    overlap_tot = min(opgave.periode_tot, periode.tot)
    dagen = max((overlap_tot - overlap_van).days, 0)

    aanname = Aanname(
        veld="verdeling_over_deelperiode",
        waarde=f"{dagen}/{dagen_opgave} dagen",
        bron="pro rata temporis op dagbasis",
        geverifieerd=False,
        motivering=(
            f"De jaarkost onder het regime van {periode.van}..{periode.tot} is "
            f"naar rato van {dagen} op {dagen_opgave} dagen toegewezen. "
            "Seizoenseffecten zitten hier niet in; met kwartiermetingen of een "
            "Synergrid-profiel wordt dit exacter."
        ),
    )
    return D(dagen) / D(dagen_opgave), aanname


def bouw_profile(
    punt: Aansluitingspunt,
    meter: Optional[Meter],
    verbruik: dict[str, Decimal],
    *,
    segment: str = "Woning",
    omvormer_kva: Decimal = D("0"),
    maandpieken: Sequence[Decimal] = (),
) -> Profile:
    """Zet aansluitingspunt + meter + verbruik om in het rekencontract.

    `segment` moet letterlijk overeenkomen met de segmentwaarde in de
    productdata ("Woning"/"Onderneming"): `Calculator._levies()` kiest er de
    accijns- en energiefondscategorie mee. Stond dit vast op "Woning", dan
    kreeg een onderneming residentiële heffingen — 140,58 in plaats van 169,25
    EUR op 3 MWh, zonder foutmelding.

    `Profile.meter` kent alleen "digitaal" en "analoog"; het domein maakt meer
    onderscheid. AMR gedraagt zich voor het capaciteitstarief als digitaal (er
    is een gemeten kwartierpiek), klassiek als analoog.

    Het prosumententarief hangt aan `omvormer_kva`: `grid_cost()` kiest
    `ELEK_LS_ANA_PRO` zodra dat groter dan nul is bij een analoge meter. Bij een
    digitale meter is er geen prosumententarief, dus dan wordt het vermogen niet
    doorgegeven — anders zou het bij een latere wijziging van `grid_cost()`
    alsnog een tarief kunnen aanzetten dat hier niet geldt.
    """
    regime = meter.meterregime if meter else Meterregime.DIGITAAL
    digitaal = regime in (Meterregime.DIGITAAL, Meterregime.AMR)
    terugdraaiend = bool(meter and meter.terugdraaiend)

    return Profile(
        postcode=punt.postcode,
        gemeente=punt.gemeente,
        segment=segment,
        meter="digitaal" if digitaal else "analoog",
        afname_dag_kwh=verbruik.get("afname_dag_kwh", D("0")),
        # Het exclusief-nachtregister deelt in `grid_cost()` het nachttarief:
        # daar wordt het ODV-tarief "exclusief nacht" op de nachtvolumes
        # toegepast. Apart houden vergt een derde volumeslot in `Profile`, wat
        # buiten deze stap valt.
        afname_nacht_kwh=(
            verbruik.get("afname_nacht_kwh", D("0"))
            + verbruik.get("afname_exclusief_nacht_kwh", D("0"))
        ),
        injectie_dag_kwh=verbruik.get("injectie_dag_kwh", D("0")),
        injectie_nacht_kwh=verbruik.get("injectie_nacht_kwh", D("0")),
        omvormer_kva=omvormer_kva if (terugdraaiend and not digitaal) else D("0"),
        maandpieken_kw=tuple(maandpieken),
        geschatte_maandpiek_kw=meter.geschatte_maandpiek_kw if meter else D("4.218"),
        minimum_maandpiek_kw=meter.minimum_maandpiek_kw if meter else D("2.5"),
    )


class Kostberekening:
    """Rekent één aansluitingspunt door over een venster."""

    def __init__(
        self,
        data_repo: DataRepository,
        heffingen,
        *,
        segment: str = "Woning",
    ) -> None:
        self.data_repo = data_repo
        self.heffingen = heffingen
        self.segment = segment
        self.calculator = Calculator(data_repo, heffingen=heffingen)

    def zoek_product(
        self,
        contract: Leveringscontract,
        periode: Deelperiode,
        richting: str = "Afname",
    ) -> Product:
        """Het product waarmee deze deelperiode gerekend wordt.

        Hier komen de eerste twee tijdassen samen. Een vast contract haalt zijn
        prijs uit de snapshot van de maand waarin de tariefkaart bevroor; een
        variabel of dynamisch contract uit de snapshot van de deelperiode zelf.
        Het teruggegeven `Product` draagt daarna wél het jaar en de maand van de
        deelperiode, want `Calculator._levies()` gebruikt die als peildatum voor
        de accijnzen — en die volgen het contract niet.
        """
        peil = contract.peil_tariefkaart() if contract.prijs_bevriest else periode.van
        kandidaten = self.data_repo.products(
            peil.year, peil.month, self.segment, energy="Elektriciteit", direction=richting
        )
        if not kandidaten:
            raise BerekeningError(
                f"Geen productdata voor {peil.year}-{peil.month:02d} "
                f"({self.segment}, elektriciteit, {richting.casefold()}). De "
                "V-test-export in deze dataversie dekt die maand niet; de "
                "berekening stopt in plaats van een tarief van een andere maand "
                "te gebruiken."
            )

        gezocht_lev = leverancier_sleutel(contract.leverancier)
        productnaam = (
            contract.injectie_product
            if richting == "Injectie" and contract.injectie_product
            else contract.product
        )
        gezocht_prod = productnaam.casefold().strip()
        treffers = [
            p
            for p in kandidaten
            if leverancier_sleutel(p.supplier) == gezocht_lev
            and (not gezocht_prod or p.name.casefold().strip() == gezocht_prod)
        ]
        # Dezelfde productnaam kan in twee smaken bestaan: "Bolt Variabel" staat
        # in augustus 2026 zowel als `variabel` (maandelijkse indexformule) als
        # `dynamisch` (kwartierprijs) in de export. Het contract weet welke van
        # de twee de klant heeft, dus dat weegt mee. Voor ToU wordt niet
        # gefilterd: die producten dragen in de brondata gewoon `vast` of
        # `variabel` als type, met ToU-componenten erin.
        if len(treffers) > 1 and contract.contracttype is not Contracttype.TOU:
            op_type = [
                p for p in treffers if p.kind.startswith(str(contract.contracttype))
            ]
            if op_type:
                treffers = op_type
        if not treffers:
            van_leverancier = sorted(
                {p.name for p in kandidaten if leverancier_sleutel(p.supplier) == gezocht_lev}
            )
            hint = (
                f" Producten van {contract.leverancier} in die maand: "
                + ", ".join(van_leverancier)
                if van_leverancier
                else f" {contract.leverancier} komt in die maand niet voor."
            )
            raise BerekeningError(
                f"Product '{productnaam}' van {contract.leverancier} niet "
                f"gevonden voor {peil.year}-{peil.month:02d} "
                f"({richting.casefold()}).{hint}"
            )
        if len(treffers) > 1:
            soorten = ", ".join(sorted({p.kind for p in treffers}))
            raise BerekeningError(
                f"'{productnaam}' van {contract.leverancier} komt "
                f"{len(treffers)} keer voor in {peil.year}-{peil.month:02d} "
                f"({richting.casefold()}), als: {soorten}. Het contracttype "
                f"'{contract.contracttype}' wijst er geen aan. Stil de eerste "
                "kiezen zou een willekeurige prijs opleveren."
            )

        product = treffers[0]
        # Prijs van de bevroren kaart, heffingen van de deelperiode.
        return replace(product, year=periode.van.year, month=periode.van.month)

    def bereken(
        self,
        punt: Aansluitingspunt,
        meter: Optional[Meter],
        contracten: Sequence[Leveringscontract],
        opgaven: Sequence[Verbruiksopgave],
        van: date,
        tot: date,
        *,
        omvormer_kva: Decimal = D("0"),
        extra_aannames: Sequence[Aanname] = (),
        markt: Optional[pd.DataFrame] = None,
        metingen: Optional[pd.DataFrame] = None,
    ) -> Berekening:
        """Reken `[van, tot)` door, deelperiode per deelperiode.

        `metingen` is de kwartierreeks van dit aansluitingspunt (kolommen
        `tijdstip`, `afname_kwh`, `injectie_kwh`). Is die er, dan worden de
        volumes per deelperiode daaruit gehaald in plaats van pro rata verdeeld,
        en kan een dynamisch product exact gerekend worden. `markt` is de
        day-ahead-reeks (`timestamp`, `price_eur_mwh`) die daarvoor nodig is.
        """
        if punt.energie_type is not EnergieType.ELEKTRICITEIT:
            raise BerekeningError(
                f"Kostberekening voor {punt.energie_type} wordt nog niet "
                "ondersteund: `grid_cost()` dekt enkel elektriciteit-"
                "laagspanning."
            )
        if not opgaven:
            raise BerekeningError(
                "Er is geen verbruiksopgave voor dit aansluitingspunt. "
                "Postcode en een jaarverbruik zijn het minimum om te rekenen."
            )

        periodes = snijd(van, tot, contracten, heffingengrenzen(self.heffingen))
        regels: list[PeriodeResultaat] = []
        aannames: list[Aanname] = list(extra_aannames)
        warnings: list[str] = []

        for periode in periodes:
            if periode.contract is None:
                raise BerekeningError(
                    f"Geen leveringscontract voor {periode.van}..{periode.tot}. "
                    "Een gat in de contracthistoriek levert geen nul op maar "
                    "een onbekende kost; vul het contract aan of verklein het "
                    "venster."
                )
            opgave = self._opgave_voor(opgaven, periode)
            aandeel, verdeel_aanname = dagaandeel(opgave, periode)
            resultaat = self._reken_periode(
                punt, meter, periode, opgave, aandeel,
                omvormer_kva=omvormer_kva, markt=markt, metingen=metingen,
            )
            regel_aannames = (
                (verdeel_aanname,) if metingen is None else ()
            ) + resultaat.aannames
            aannames.extend(regel_aannames)
            warnings.extend(resultaat.kost.warnings)
            regels.append(replace(resultaat, aannames=regel_aannames))

        klasse = Exactheidsklasse.zwakste(
            [r.exactheidsklasse for r in regels]
            # Een niet-geverifieerde aanname die het bedrag raakt trekt het
            # resultaat naar "geschat". Administratieve aannames (een onbekende
            # EAN bijvoorbeeld) tellen niet mee: die raken geen euro, en ze wél
            # laten meetellen zou bijna elk resultaat "geschat" maken en die
            # klasse betekenisloos.
            + [
                Exactheidsklasse.GESCHAT
                for a in aannames
                if not a.geverifieerd and a.beinvloedt_bedrag
            ]
        )

        return Berekening(
            van=van,
            tot=tot,
            regels=tuple(regels),
            exactheidsklasse=klasse,
            aannames=tuple(aannames),
            warnings=tuple(dict.fromkeys(warnings)),
        )

    # ------------------------------------------------------------------
    # Eén deelperiode
    # ------------------------------------------------------------------

    def _reken_periode(
        self,
        punt: Aansluitingspunt,
        meter: Optional[Meter],
        periode: Deelperiode,
        opgave: Verbruiksopgave,
        aandeel: Decimal,
        *,
        omvormer_kva: Decimal,
        markt: Optional[pd.DataFrame],
        metingen: Optional[pd.DataFrame],
    ) -> PeriodeResultaat:
        """De kost van één deelperiode, component per component.

        De componenten van een energiefactuur schalen niet allemaal hetzelfde,
        en dat is de reden dat deze methode ze uit elkaar houdt:

        - **Nettarieven en heffingen zijn jaargrootheden.** Het capaciteitstarief
          heeft een jaarlijkse ondergrens én een maximumtarief over het
          jaarverbruik, databeheer is EUR/jaar, de accijnsschijven zijn
          progressief over het *jaar*verbruik en het energiefonds is een vast
          bedrag per maand. Ze worden dus op het volledige jaarprofiel berekend
          en naar dagen geschaald.
        - **De vaste vergoeding van de leverancier** is eveneens EUR/jaar en
          wordt apart geschaald.
        - **De energiecomponent volgt de volumes.** Bij een vast of variabel
          product schaalt die lineair mee, maar bij een *dynamisch* product niet:
          daar hangt de kost af van wélke kwartieren in de periode vallen. Een
          jaarbedrag naar dagen schalen zou dure winteruren over de zomer
          uitsmeren. Met gemeten kwartierdata wordt die component daarom
          rechtstreeks op de periode gerekend.
        """
        contract = periode.contract
        product = self.zoek_product(contract, periode, "Afname")

        jaarverbruik = {
            "afname_dag_kwh": opgave.afname_dag_kwh,
            "afname_nacht_kwh": opgave.afname_nacht_kwh,
            "afname_exclusief_nacht_kwh": opgave.afname_exclusief_nacht_kwh,
            "injectie_dag_kwh": opgave.injectie_dag_kwh,
            "injectie_nacht_kwh": opgave.injectie_nacht_kwh,
        }
        jaarprofiel = bouw_profile(
            punt, meter, jaarverbruik, segment=self.segment, omvormer_kva=omvormer_kva
        )

        # -- jaargrootheden, naar dagen geschaald --------------------------
        self._controleer_tariefjaar(periode)
        grid = self.calculator.grid_cost(jaarprofiel) * aandeel
        levies = self.calculator.levies(jaarprofiel, product.year, product.month) * aandeel

        # -- volumes van deze deelperiode ----------------------------------
        periode_intervals = _snijd_metingen(metingen, periode)
        periodeverbruik, volume_aannames = self._periodevolumes(
            opgave, aandeel, periode_intervals
        )
        periodeprofiel = bouw_profile(
            punt, meter, periodeverbruik, segment=self.segment, omvormer_kva=omvormer_kva
        )

        supplier, warnings = self._leverancierskost(
            product, periodeprofiel, aandeel, markt, _afname(periode_intervals)
        )

        # -- injectie -------------------------------------------------------
        credit = D("0")
        aannames = list(volume_aannames)
        injectie_kwh = periodeprofiel.injectie_kwh
        if injectie_kwh > 0:
            if meter is not None and meter.terugdraaiend:
                raise BerekeningError(
                    "Een terugdraaiende meter registreert geen injectie: de "
                    "meter draait terug en daarvoor wordt het prosumententarief "
                    "aangerekend. Injectievolumes én een prosumententarief "
                    "tegelijk zouden hetzelfde voordeel twee keer tellen."
                )
            injectieprofiel = replace(
                periodeprofiel,
                afname_dag_kwh=periodeprofiel.injectie_dag_kwh,
                afname_nacht_kwh=periodeprofiel.injectie_nacht_kwh,
            )
            try:
                inject_product = self.zoek_product(contract, periode, "Injectie")
            except BerekeningError as exc:
                # Geen injectieproduct is geen injectievergoeding van nul: het is
                # een onbekend bedrag. De kost wordt doorgerekend zonder krediet,
                # maar het resultaat zegt dat het te hoog staat.
                warnings.append(
                    f"Injectie niet verrekend voor {periode.van}..{periode.tot}: {exc}"
                )
                aannames.append(
                    Aanname(
                        veld="injectievergoeding",
                        waarde="0",
                        bron="geen injectieproduct gevonden",
                        geverifieerd=False,
                        motivering=(
                            f"{injectie_kwh} kWh injectie blijft onvergoed in dit "
                            "bedrag. De werkelijke kost ligt lager; vul een "
                            "injectieproduct in bij het contract."
                        ),
                    )
                )
            else:
                credit, inj_warnings = self._leverancierskost(
                    inject_product,
                    injectieprofiel,
                    aandeel,
                    markt,
                    _injectie(periode_intervals),
                    sta_vlak_profiel=False,
                )
                warnings.extend(inj_warnings)

        belastbaar = supplier + grid + levies - credit
        btw = max(belastbaar, D("0")) * self.calculator.vat

        return PeriodeResultaat(
            periode=periode,
            kost=Cost(supplier, grid, levies, credit, btw, warnings),
            product=product,
            exactheidsklasse=(
                opgave.exactheidsklasse
                if periode_intervals is None
                else Exactheidsklasse.EXACT
            ),
            aannames=tuple(aannames),
        )

    def _controleer_tariefjaar(self, periode: Deelperiode) -> None:
        """Weiger nettarieven van een ander jaar dan de deelperiode.

        De distributienettarieven worden per kalenderjaar goedgekeurd en de
        tariefrijen dragen zelf geen datum: aan de data is niet te zien of ze
        bij 2025 of bij 2026 horen. Een berekening over 2025 met het werkboek
        van 2026 levert daarom een plausibel ogend en verkeerd bedrag op, zonder
        enige melding. `periodes.tariefjaargrenzen()` knipt al op elke
        jaarwissel, dus elke deelperiode ligt binnen één kalenderjaar.

        Meerdere tariefjaren tegelijk laden is de volgende stap; tot dan is dit
        het verschil tussen een fout en een verkeerd getal.
        """
        geladen = getattr(self.data_repo, "tariefjaar", None)
        if geladen is None:
            # Oudere dataversies dragen het veld niet. Daar valt niets te
            # toetsen; de waarschuwing daarover staat in `cli/db.py`.
            return
        if periode.van.year != geladen:
            raise BerekeningError(
                f"De geladen nettarieven gelden voor {geladen}, maar deze "
                f"deelperiode loopt van {periode.van} tot {periode.tot}. "
                "Kies de dataversie met het werkboek van "
                f"{periode.van.year}; tarieven van een ander jaar geven een "
                "verkeerd bedrag zonder dat het aan het resultaat te zien is."
            )

    def _leverancierskost(
        self,
        product: Product,
        profiel: Profile,
        aandeel: Decimal,
        markt: Optional[pd.DataFrame],
        intervals: Optional[pd.DataFrame],
        *,
        sta_vlak_profiel: bool = True,
    ) -> tuple[Decimal, list[str]]:
        """Energiecomponent van deze periode plus het pro-rata deel van de vaste vergoeding.

        `supplier_cost()` telt de vaste vergoeding altijd voluit mee — dat is
        juist voor een jaarberekening en verkeerd voor een deelperiode. Ze wordt
        er hier afgetrokken en naar dagen geschaald teruggezet; anders betaalt
        een gebruiker met vier contractperiodes vier keer de jaarlijkse
        abonnementskost.
        """
        try:
            kost, warnings = self.calculator.supplier_cost(
                product, profiel, markt, intervals, sta_vlak_profiel=sta_vlak_profiel
            )
        except ValueError as exc:
            raise BerekeningError(str(exc)) from exc
        vaste_vergoeding = product.components.get("fixed_fee", D("0"))
        return kost - vaste_vergoeding + vaste_vergoeding * aandeel, list(warnings)

    def _periodevolumes(
        self,
        opgave: Verbruiksopgave,
        aandeel: Decimal,
        intervals: Optional[pd.DataFrame],
    ) -> tuple[dict[str, Decimal], tuple[Aanname, ...]]:
        """De volumes van deze deelperiode: gemeten als het kan, anders pro rata."""
        if intervals is None or intervals.empty:
            return {
                veld: getattr(opgave, veld) * aandeel
                for veld in (
                    "afname_dag_kwh",
                    "afname_nacht_kwh",
                    "afname_exclusief_nacht_kwh",
                    "injectie_dag_kwh",
                    "injectie_nacht_kwh",
                )
            }, ()

        # Gemeten kwartierdata kent geen dag/nacht-onderscheid: de Fluvius-export
        # geeft één afname- en één injectieregister. Alles komt daarom in het
        # dagslot; wie een tweevoudige meter heeft en het onderscheid nodig heeft,
        # levert dat via een verbruiksopgave aan.
        return {
            "afname_dag_kwh": D(str(intervals["afname_kwh"].sum())),
            "afname_nacht_kwh": D("0"),
            "afname_exclusief_nacht_kwh": D("0"),
            "injectie_dag_kwh": D(str(intervals["injectie_kwh"].sum())),
            "injectie_nacht_kwh": D("0"),
        }, ()

    @staticmethod
    def _opgave_voor(
        opgaven: Sequence[Verbruiksopgave], periode: Deelperiode
    ) -> Verbruiksopgave:
        overlappend = [
            o
            for o in opgaven
            if o.periode_van < periode.tot and periode.van < o.periode_tot
        ]
        if not overlappend:
            raise BerekeningError(
                f"Geen verbruiksopgave die {periode.van}..{periode.tot} dekt."
            )
        if len(overlappend) > 1:
            # Twee opgaven over dezelfde dagen zouden dubbel geteld worden of,
            # erger, willekeurig gekozen. Beide zijn stille fouten.
            beschrijving = ", ".join(
                f"{o.periode_van}..{o.periode_tot} ({o.bron})" for o in overlappend
            )
            raise BerekeningError(
                f"Meerdere verbruiksopgaven overlappen {periode.van}.."
                f"{periode.tot}: {beschrijving}."
            )
        return overlappend[0]


def _snijd_metingen(
    metingen: Optional[pd.DataFrame], periode: Deelperiode
) -> Optional[pd.DataFrame]:
    """De kwartierreeks binnen `[periode.van, periode.tot)`, of niets.

    Half-open, net als de periode zelf: het eerste kwartier van de wisseldag
    hoort bij de nieuwe periode, niet bij beide.
    """
    if metingen is None or metingen.empty:
        return None
    tijdstip = pd.to_datetime(metingen["tijdstip"], utc=True)
    grens_van = pd.Timestamp(periode.van, tz="UTC")
    grens_tot = pd.Timestamp(periode.tot, tz="UTC")
    binnen = metingen[(tijdstip >= grens_van) & (tijdstip < grens_tot)]
    return binnen if not binnen.empty else None


def _afname(intervals: Optional[pd.DataFrame]) -> Optional[pd.DataFrame]:
    """De reeks in de vorm die `supplier_cost()` verwacht: timestamp + afname_kwh."""
    if intervals is None or intervals.empty:
        return None
    uit = intervals[["tijdstip", "afname_kwh"]].copy()
    return uit.rename(columns={"tijdstip": "timestamp"})


def _injectie(intervals: Optional[pd.DataFrame]) -> Optional[pd.DataFrame]:
    """Idem, maar met de injectievolumes in het `afname_kwh`-slot.

    Dezelfde truc als bij het injectieprofiel: de componentlogica is identiek,
    alleen de volumes verschillen. Hier stond eerder de afnamereeks, waardoor een
    dynamisch injectieproduct het verbruik tegen de injectieprijs waardeerde.
    """
    if intervals is None or intervals.empty:
        return None
    uit = intervals[["tijdstip", "injectie_kwh"]].copy()
    return uit.rename(columns={"tijdstip": "timestamp", "injectie_kwh": "afname_kwh"})
