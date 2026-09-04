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
from datetime import date, timedelta
from decimal import Decimal
from typing import Optional, Sequence

import pandas as pd

from energie_vlaanderen.calculation.calculator import Calculator
from energie_vlaanderen.data.bron import TariefBron
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

    # Kruist de opgave een tariefjaargrens, dan kost deze aanname geld: de
    # nettarieven verschillen tussen de jaren, dus het maakt uit hoeveel kWh
    # vóór en na 1 januari verbruikt is. Een leverancier splitst daar op de
    # werkelijke meterstand; wij op de dagen.
    #
    # Op een echte afrekening scheelde dat 0,73 EUR: over 28/10-30/04 viel 40,2%
    # van het verbruik in de 35,1% van de dagen die nog in 2025 lagen — een
    # winter verbruikt nu eenmaal niet zoals een lente.
    kruist_jaargrens = opgave.periode_van.year != (opgave.periode_tot - timedelta(days=1)).year
    if kruist_jaargrens:
        motivering = (
            f"De kost onder het regime van {periode.van}..{periode.tot} is naar "
            f"rato van {dagen} op {dagen_opgave} dagen toegewezen. Deze opgave "
            f"loopt over de jaarwissel, en de nettarieven verschillen per "
            "kalenderjaar — hoeveel kWh vóór en na 1 januari verbruikt is, maakt "
            "dus uit voor het bedrag. Een meterstand op 31 december sluit dit: "
            "geef dan twee `[[verbruiksopgave]]`-secties op in plaats van één."
        )
    else:
        motivering = (
            f"De kost onder het regime van {periode.van}..{periode.tot} is naar "
            f"rato van {dagen} op {dagen_opgave} dagen toegewezen. "
            "Seizoenseffecten zitten hier niet in; met kwartiermetingen of een "
            "Synergrid-profiel wordt dit exacter."
        )

    aanname = Aanname(
        veld=(
            "verdeling_over_de_jaarwissel" if kruist_jaargrens
            else "verdeling_over_deelperiode"
        ),
        waarde=f"{dagen}/{dagen_opgave} dagen",
        bron="pro rata temporis op dagbasis",
        geverifieerd=False,
        motivering=motivering,
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
        afname_nacht_kwh=verbruik.get("afname_nacht_kwh", D("0")),
        # Apart, niet bij het nachtvolume geteld: het exclusief-nachtregister
        # heeft een eigen, lager ODV-tarief dat niet voor gewone daluren geldt.
        afname_exclusief_nacht_kwh=verbruik.get("afname_exclusief_nacht_kwh", D("0")),
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
        data_repo: TariefBron,
        heffingen,
        *,
        segment: str = "Woning",
        nettarieven_per_jaar: Optional[dict[int, TariefBron]] = None,
        transport=None,
        gasverdeler=None,
    ) -> None:
        """`nettarieven_per_jaar` koppelt een tariefjaar aan zijn dataversie.

        De distributienettarieven worden per kalenderjaar goedgekeurd en de
        tariefrijen dragen zelf geen datum. Een afrekening loopt zelden gelijk
        met het kalenderjaar — een verbruiksperiode van juni tot april kruist de
        jaarwissel — dus één dataversie volstaat dan niet.

        `periodes.tariefjaargrenzen()` knipt al op elke 1 januari, zodat elke
        deelperiode binnen één kalenderjaar valt en er dus altijd precies één
        tariefjaar bij hoort. Zonder deze kaart blijft `data_repo` de enige
        bron, en toetst `_controleer_tariefjaar()` of dat jaar klopt.
        """
        self.data_repo = data_repo
        self.heffingen = heffingen
        self.segment = segment
        # Het vervoerstarief van Fluxys staat in geen VREG-werkboek en dus ook
        # niet in `data_repo`; het komt uit config/nettarieven/. Zonder deze
        # repository weigert een gasberekening -- 25 EUR per jaar stil laten
        # vallen is precies wat dit project niet doet.
        self.transport = transport
        # De verdeler van een gasjaarverbruik over de tariefperiodes. Bij gas
        # is naar dagen verdelen geen benadering maar een systematische fout
        # (zie `schatting.gasaandeel_uit_rlp0`). Als callable meegegeven zodat
        # deze klasse geen databankverbinding hoeft te kennen.
        self.gasverdeler = gasverdeler
        self.nettarieven_per_jaar = dict(nettarieven_per_jaar or {})
        self.calculator = Calculator(data_repo, heffingen=heffingen)
        self._calculators: dict[int, Calculator] = {
            jaar: Calculator(repo, heffingen=heffingen)
            for jaar, repo in self.nettarieven_per_jaar.items()
        }
        # Eén melding per opgave, niet één per deelperiode. Als instantieveld en
        # niet als klasseattribuut: dat laatste zou gedeeld worden tussen
        # berekeningen en de tweede stil laten zwijgen.
        self._gemelde_opgaven: set[tuple] = set()

    def _calculator_voor(self, periode: Deelperiode) -> Calculator:
        """De rekenengine met de nettarieven van het jaar van deze deelperiode."""
        if not self._calculators:
            return self.calculator
        gekozen = self._calculators.get(periode.van.year)
        if gekozen is None:
            beschikbaar = ", ".join(str(j) for j in sorted(self._calculators))
            raise BerekeningError(
                f"Geen nettarieven geladen voor {periode.van.year} "
                f"({periode.van}..{periode.tot}). Beschikbaar: {beschikbaar}."
            )
        return gekozen

    def zoek_product(
        self,
        contract: Leveringscontract,
        periode: Deelperiode,
        richting: str = "Afname",
        energie: str = "Elektriciteit",
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
        # De energievorm hoort in de opzoeking. Stond die vast op
        # "Elektriciteit", dan kreeg een gascontract van dezelfde leverancier
        # met dezelfde productnaam ("ENGIE Easy" bestaat in beide) gewoon de
        # elektriciteitsprijs: 0,172 in plaats van 0,050 EUR/kWh, oftewel drie
        # keer te veel, zonder foutmelding.
        kandidaten = self.data_repo.products(
            peil.year, peil.month, self.segment, energy=energie, direction=richting
        )
        if not kandidaten:
            raise BerekeningError(
                f"Geen productdata voor {peil.year}-{peil.month:02d} "
                f"({self.segment}, {energie.casefold()}, {richting.casefold()}). De "
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
        if punt.energie_type is EnergieType.GAS:
            if self.transport is None:
                raise BerekeningError(
                    "Een gasberekening vereist het vervoerstarief "
                    "(`TransportTariefRepository.load(config/nettarieven)`). "
                    "Het staat in geen VREG-werkboek en zou anders stil "
                    "wegvallen — ongeveer 25 EUR per jaar."
                )
        elif punt.energie_type is not EnergieType.ELEKTRICITEIT:
            raise BerekeningError(
                f"Kostberekening voor {punt.energie_type} wordt niet "
                "ondersteund: enkel elektriciteit-laagspanning en aardgas."
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
            warnings.extend(self._toets_opgave_tegen_meting(opgave, metingen))
            if punt.energie_type is EnergieType.GAS and self.gasverdeler:
                # Het VREG-werkboek schrijft voor dat de gemeten kWh met het
                # reëel lastprofiel RLP0 over de tariefperiodes verdeeld worden,
                # niet naar dagen. Gas is winterzwaar; naar dagen verdelen legt
                # te weinig volume in het duurdere tariefjaar.
                aandeel, verdeel_aanname = self._gasaandeel(opgave, periode)
            else:
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

    def _gasaandeel(
        self, opgave: Verbruiksopgave, periode: Deelperiode
    ) -> tuple[Decimal, Aanname]:
        """Welk deel van het opgavevolume in deze deelperiode valt, via RLP0.

        Dezelfde vorm als `dagaandeel()`, maar met het gasprofiel in plaats van
        de kalender: het aandeel van de deelperiode gedeeld door dat van de
        volledige opgave, zodat de deelperiodes over de opgave heen tot 1
        sommeren. Dat invariant is wat `tests/test_gebruikers_berekening.py`
        bewaakt: knippen mag het totaal niet veranderen.
        """
        deel, aanname = self.gasverdeler(periode.van, periode.tot)
        geheel, _ = self.gasverdeler(opgave.periode_van, opgave.periode_tot)
        if geheel <= 0:
            raise BerekeningError(
                f"Het RLP0-gasprofiel geeft nul gewicht aan de opgaveperiode "
                f"{opgave.periode_van}..{opgave.periode_tot}; verdelen is dan "
                "niet mogelijk."
            )
        return deel / geheel, aanname

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
        gas = punt.energie_type is EnergieType.GAS
        energie = "Gas" if gas else "Elektriciteit"
        product = self.zoek_product(contract, periode, "Afname", energie)

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

        rekenaar = self._calculator_voor(periode)
        if not self._calculators:
            self._controleer_tariefjaar(periode)

        # Twee breuken, en ze zijn niet hetzelfde zodra de meetperiode geen
        # volledig jaar beslaat:
        #
        #   `aandeel`  = dagen van deze deelperiode / dagen van de opgave.
        #                Hoeveel van het *verbruik* hier valt.
        #   `tijddeel` = dagen van deze deelperiode / 365.
        #                Hoeveel van een *jaar* deze periode is.
        #
        # Een eindafrekening over 310 gemeten dagen rekent het capaciteitstarief
        # en het databeheer naar rato van 310/365 aan, niet voluit. Wie daar
        # `aandeel` gebruikt — dat over de deelperiodes tot 1 sommeert — betaalt
        # een vol jaar aan vaste posten voor tien maanden verbruik: 365/310 =
        # 1,177 keer te veel.
        tijddeel = D(periode.dagen) / D("365")

        # -- volumes van deze deelperiode ----------------------------------
        periode_intervals = _snijd_metingen(metingen, periode)
        periodeverbruik, volume_aannames = self._periodevolumes(
            opgave, aandeel, periode_intervals
        )
        periodeprofiel = bouw_profile(
            punt, meter, periodeverbruik, segment=self.segment, omvormer_kva=omvormer_kva
        )

        # Netkost op de volumes van deze periode, met de vaste jaarposten naar
        # rato van de dagen.
        if gas:
            # De tariefgroep (T1..T4) volgt het *jaar*verbruik, de vaste term en
            # het databeheer de dagen, en de volumetrische termen het volume van
            # deze periode. Drie grootheden, drie schalen.
            grid = rekenaar.gas_grid_cost(
                periodeprofiel,
                jaarprofiel.afname_kwh,
                periodeprofiel.afname_kwh,
                dagen=periode.dagen,
            )
            # Het vervoerstarief van Fluxys, dat de netbeheerder doorrekent maar
            # niet vaststelt. Staat in geen werkboek en dus niet in `grid_cost`.
            vervoer = self.transport.tarief(
                "aardgas",
                "niet_zakelijk" if self.segment == "Woning" else "zakelijk_laagspanning",
                periode.van,
            )
            grid += vervoer.eur_per_kwh * periodeprofiel.afname_kwh
        else:
            grid = rekenaar.grid_cost(periodeprofiel, dagen=periode.dagen)

        # Heffingen: de accijnsschijven zijn progressief over het jaarverbruik,
        # dus die worden op het volledige opgavevolume berekend en daarna naar
        # het volumeaandeel geschaald. Het energiefonds is een maandbedrag en
        # volgt de kalender — en bestaat enkel voor elektriciteit.
        verbruiksheffing, energiefonds = rekenaar.levies_gesplitst(
            jaarprofiel, product.year, product.month,
            "aardgas" if gas else "elektriciteit",
        )
        levies = verbruiksheffing * aandeel + energiefonds * tijddeel

        supplier, warnings = self._leverancierskost(
            product, periodeprofiel, tijddeel, markt, _afname(periode_intervals)
        )

        # -- injectie -------------------------------------------------------
        credit = D("0")
        aannames = list(volume_aannames)
        injectie_kwh = periodeprofiel.injectie_kwh
        if gas and injectie_kwh > 0:
            raise BerekeningError(
                "Er staat injectie op een aardgasaansluiting. Gas kent geen "
                "teruglevering; dit is bijna zeker een verwisseld "
                "aansluitingspunt in het dossier."
            )
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
                    tijddeel,
                    markt,
                    _injectie(periode_intervals),
                    sta_vlak_profiel=False,
                )
                warnings.extend(inj_warnings)

        belastbaar = supplier + grid + levies - credit
        btw = max(belastbaar, D("0")) * rekenaar.vat

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

    def _toets_opgave_tegen_meting(
        self, opgave: Verbruiksopgave, metingen: Optional[pd.DataFrame]
    ) -> list[str]:
        """Melden wanneer de aangegeven volumes en de meetreeks uiteenlopen.

        Beide worden gebruikt: de opgave bepaalt het volume waarover de
        progressieve accijnsschijven lopen, de meetreeks bepaalt hoe dat volume
        over de deelperiodes verdeeld is. Als ze het oneens zijn, is stil
        doorrekenen het slechtste antwoord — dan staat er een bedrag dat op twee
        verschillende verbruiken tegelijk steunt.

        Een procent speling: een factuur drukt kWh in hele eenheden af, en vier
        afgeronde registers geven makkelijk een kWh verschil op de som.
        """
        if metingen is None or metingen.empty:
            return []
        sleutel = (opgave.periode_van, opgave.periode_tot)
        if sleutel in self._gemelde_opgaven:
            return []
        self._gemelde_opgaven.add(sleutel)

        binnen = _snijd_metingen(
            metingen, Deelperiode(opgave.periode_van, opgave.periode_tot, None)
        )
        if binnen is None or binnen.empty:
            return [
                f"Geen meetgegevens voor {opgave.periode_van}..{opgave.periode_tot}, "
                "terwijl er wel een verbruiksopgave is."
            ]
        gemeten = _reeks(binnen, ("afname_dag_kwh", "afname_nacht_kwh", "afname_kwh"))
        gemeten_kwh = D(str(gemeten["afname_kwh"].sum()))
        aangegeven = opgave.afname_kwh
        if aangegeven <= 0:
            return []
        afwijking = abs(gemeten_kwh - aangegeven) / aangegeven
        if afwijking > D("0.01"):
            return [
                f"Opgave {opgave.periode_van}..{opgave.periode_tot} noemt "
                f"{aangegeven:.1f} kWh afname, de meetreeks {gemeten_kwh:.1f} kWh "
                f"({afwijking:.1%} verschil). De heffingen rekenen met de opgave, "
                "de verdeling over de periodes met de meting."
            ]
        return []

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
        tijddeel: Decimal,
        markt: Optional[pd.DataFrame],
        intervals: Optional[pd.DataFrame],
        *,
        sta_vlak_profiel: bool = True,
    ) -> tuple[Decimal, list[str]]:
        """Energiecomponent van deze periode plus het pro-rata deel van de vaste vergoeding.

        `supplier_cost()` telt de vaste vergoeding altijd voluit mee — dat is
        juist voor een jaarberekening en verkeerd voor een deelperiode. Ze wordt
        er hier afgetrokken en naar `tijddeel` (dagen/365) teruggezet; anders
        betaalt een gebruiker met vier contractperiodes vier keer de jaarlijkse
        abonnementskost.

        Een echte eindafrekening bevestigt de breuk: 22,29 EUR over 125 dagen en
        32,99 EUR over 185 dagen komen allebei op 65,09 EUR per jaar uit.
        """
        try:
            kost, warnings = self.calculator.supplier_cost(
                product, profiel, markt, intervals, sta_vlak_profiel=sta_vlak_profiel
            )
        except ValueError as exc:
            raise BerekeningError(str(exc)) from exc
        vaste_vergoeding = product.components.get("fixed_fee", D("0"))
        return kost - vaste_vergoeding + vaste_vergoeding * tijddeel, list(warnings)

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

        # De Fluvius-export kent vier registers — Afname Dag, Afname Nacht,
        # Injectie Dag, Injectie Nacht — en `FluviusIntervals` houdt die apart.
        # Dat onderscheid is nodig: het nettarief en de meeste
        # leveranciersproducten rekenen een ander tarief voor dag en nacht.
        # Levert de reeks alleen een totaal (een oudere of eenvoudiger export),
        # dan valt alles in het dagslot.
        def som(*namen: str) -> Decimal:
            aanwezig = [n for n in namen if n in intervals]
            if not aanwezig:
                return D("0")
            return D(str(intervals[aanwezig].sum(axis=1).sum()))

        return {
            "afname_dag_kwh": som("afname_dag_kwh") or som("afname_kwh"),
            "afname_nacht_kwh": som("afname_nacht_kwh"),
            "afname_exclusief_nacht_kwh": som("afname_exclusief_nacht_kwh"),
            "injectie_dag_kwh": som("injectie_dag_kwh") or som("injectie_kwh"),
            "injectie_nacht_kwh": som("injectie_nacht_kwh"),
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
    """De reeks in de vorm die `supplier_cost()` verwacht: timestamp + afname_kwh.

    Dag en nacht worden hier samengeteld: een dynamisch product rekent per
    kwartier tegen de marktprijs en kent dat onderscheid niet.
    """
    return _reeks(intervals, ("afname_dag_kwh", "afname_nacht_kwh", "afname_kwh"))


def _injectie(intervals: Optional[pd.DataFrame]) -> Optional[pd.DataFrame]:
    """Idem, maar met de injectievolumes in het `afname_kwh`-slot.

    Dezelfde truc als bij het injectieprofiel: de componentlogica is identiek,
    alleen de volumes verschillen. Hier stond eerder de afnamereeks, waardoor een
    dynamisch injectieproduct het verbruik tegen de injectieprijs waardeerde.
    """
    return _reeks(intervals, ("injectie_dag_kwh", "injectie_nacht_kwh", "injectie_kwh"))


def _reeks(
    intervals: Optional[pd.DataFrame], kolommen: tuple[str, ...]
) -> Optional[pd.DataFrame]:
    """Tel de genoemde kolommen op tot één `afname_kwh`-reeks."""
    if intervals is None or intervals.empty:
        return None
    aanwezig = [k for k in kolommen if k in intervals]
    if not aanwezig:
        return None
    return pd.DataFrame({
        "timestamp": intervals["tijdstip"],
        "afname_kwh": intervals[aanwezig].sum(axis=1),
    })
