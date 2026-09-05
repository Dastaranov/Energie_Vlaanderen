"""Domeinmodel voor de gebruikersbasis.

Implementeert `docs/manifest.md` §5.1-5.4 (`CustomerAccount`, `ConnectionPoint`,
`ConsumptionProfile`, `IntervalMeasurement`) en §5.8 (exactheidsklasse).

Drie ontwerpregels die de vorm van dit bestand bepalen:

1. **Een EAN hoort bij een aansluitingspunt, niet bij een gebruiker.** Eén EAN18
   identificeert één toegangspunt voor één energiedrager; elektriciteit en gas
   hebben elk hun eigen EAN. Injectie is *geen* aparte EAN maar een aparte
   registerlezing op dezelfde meter. Daarom is er geen veld "heeft gas": het
   bestaan van een gasaansluitingspunt ís dat antwoord, en een boolean ernaast
   zou de lijst kunnen tegenspreken.

2. **Vermogensbegrippen worden niet samengevoegd.** Het aansluitingsvermogen
   (fysiek, kVA), de AC-limiet van de omvormer en de maandpiek (een tariefconstruct)
   zijn drie verschillende getallen. Dit project heeft het samenvallen van
   piekbegrippen al één keer betaald — zie de toelichting bij
   `geschatte_maandpiek_kw` in `domain/models.py`.

3. **Een geschat getal draagt zijn herkomst mee.** `Aanname` en `Exactheidsklasse`
   zijn geen rapportageversiering: ze reizen mee tot in het eindbedrag, zodat een
   schatting nooit stilzwijgend als meting behandeld wordt.

Geldigheidsperiodes zijn **half-open**: `[geldig_van, geldig_tot)`. `geldig_tot`
gelijk aan `None` betekent "nog lopend". Half-open omdat contracten en
tariefregimes op dezelfde dag opvolgen — een inclusieve einddatum zou die dag aan
twee periodes toewijzen en het bedrag dubbel tellen.

`Decimal` voor geld en voor kWh die rechtstreeks in een geldberekening gaan;
`float` voor technische nameplate-waarden (zie `hardware/models.py` voor dezelfde
afweging).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Iterable, Optional
from uuid import UUID, uuid4

from energie_vlaanderen.utility.constants import D


class GebruikersError(ValueError):
    """Een gebruikersgegeven ontbreekt of is intern tegenstrijdig."""


# ---------------------------------------------------------------------------
# Gesloten waardelijsten
# ---------------------------------------------------------------------------


class Exactheidsklasse(StrEnum):
    """Manifest §5.8: hoe hard is dit resultaat?

    De volgorde is bewust een rangorde. Een berekening die één geschatte invoer
    gebruikt is `GESCHAT`, ook als elke tariefopzoeking exact was — de zwakste
    schakel bepaalt de klasse. `zwakste()` legt dat vast zodat elke oproeper
    dezelfde regel gebruikt in plaats van er zelf een te verzinnen.
    """

    EXACT = "exact"
    GERECONSTRUEERD = "gereconstrueerd"
    GESCHAT = "geschat"
    SCENARIO = "scenario"

    @property
    def rangorde(self) -> int:
        return _RANGORDE[self]

    @classmethod
    def zwakste(cls, klassen: Iterable["Exactheidsklasse"]) -> "Exactheidsklasse":
        gevonden = list(klassen)
        if not gevonden:
            raise GebruikersError(
                "Exactheidsklasse.zwakste() kreeg geen enkele klasse; een "
                "resultaat zonder klasse mag niet stil als exact doorgaan."
            )
        return max(gevonden, key=lambda k: k.rangorde)


_RANGORDE = {
    Exactheidsklasse.EXACT: 0,
    Exactheidsklasse.GERECONSTRUEERD: 1,
    Exactheidsklasse.GESCHAT: 2,
    Exactheidsklasse.SCENARIO: 3,
}


class EnergieType(StrEnum):
    ELEKTRICITEIT = "elektriciteit"
    GAS = "gas"


class Segment(StrEnum):
    """Sluit aan op de segmentwaarden die `DataRepository.products()` filtert."""

    WONING = "Woning"
    ONDERNEMING = "Onderneming"


class Spanningsniveau(StrEnum):
    LAAG = "laag"
    MIDDEN = "midden"
    HOOG = "hoog"


class Meterregime(StrEnum):
    """Manifest §5.2 `metering_regime`.

    `KLASSIEK` is de Ferrarismeter. Die kent geen gemeten maandpiek, en dus ook
    geen capaciteitstarief op basis van meting — `grid_cost()` valt daar terug
    op de analoge klantcategorie.
    """

    DIGITAAL = "digitaal"
    KLASSIEK = "klassiek"
    AMR = "amr"


class Registerschema(StrEnum):
    """Welke registers de meter uitleest.

    Niet hetzelfde als het meterregime: een digitale meter kan enkelvoudig of
    tweevoudig geregistreerd zijn, en 'exclusief nacht' is een derde, apart
    register met een eigen nettarief (`ODV kWh-tarief exclusief nacht`).
    """

    ENKELVOUDIG = "enkelvoudig"
    TWEEVOUDIG = "tweevoudig"
    EXCLUSIEF_NACHT = "exclusief_nacht"


class Contracttype(StrEnum):
    VAST = "vast"
    VARIABEL = "variabel"
    DYNAMISCH = "dynamisch"
    TOU = "tou"


class AssetType(StrEnum):
    PV = "pv"
    BATTERIJ = "batterij"
    EV = "ev"
    WARMTEPOMP = "warmtepomp"
    # Eén type voor elk gasverwarmingstoestel (kachel, ketel, ...) — het
    # *doel* (InstallatieAsset.doel: "ruimteverwarming"/"warm_water"/"beide")
    # onderscheidt de variant, net zoals `WarmtepompSpec.type_wp` dat al doet
    # voor warmtepomptypes. Een aparte enumwaarde per toestelsoort zou bij elk
    # nieuw toestel een migratie vergen.
    GASTOESTEL = "gastoestel"


class Topologie(StrEnum):
    """Hoe een batterij aan de installatie hangt.

    Bepalend voor de simulatie: bij `DC_GEKOPPELD` kan PV de batterij laden
    zonder de meter te passeren en zonder DC->AC->DC-verlies; bij
    `AC_GEKOPPELD` gaat elke kWh door de omvormer heen. `HYBRIDE` is één
    toestel dat beide kanten intern regelt — daar mag het AC/DC-verlies niet
    nog eens apart aangerekend worden.
    """

    AC_GEKOPPELD = "ac_gekoppeld"
    DC_GEKOPPELD = "dc_gekoppeld"
    HYBRIDE = "hybride"


class OpgaveBron(StrEnum):
    """Waar een verbruikscijfer vandaan komt — bepaalt mee de exactheidsklasse."""

    METING = "meting"
    FACTUUR = "factuur"
    MANUEEL = "manueel"
    SCHATTING = "schatting"


_BRON_KLASSE = {
    OpgaveBron.METING: Exactheidsklasse.EXACT,
    OpgaveBron.FACTUUR: Exactheidsklasse.EXACT,
    # Een handmatig doorgegeven jaarverbruik is niet nagerekend tegen een
    # factuur of meting: het is de beste beschikbare opgave, geen bewijs.
    OpgaveBron.MANUEEL: Exactheidsklasse.GERECONSTRUEERD,
    OpgaveBron.SCHATTING: Exactheidsklasse.GESCHAT,
}


# ---------------------------------------------------------------------------
# Herkomst van geschatte waarden
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Aanname:
    """Eén ingevuld gegeven dat niet van de gebruiker kwam.

    Zelfde vorm als de provenance in `config/heffingen/*.toml` en
    `config/hardware/*.toml`: `bron` zegt waaruit de waarde komt en
    `geverifieerd` of dat cijfer tegen die bron gelegd is. Een aanname zonder
    bron is een fout, geen waarschuwing — dan is het een gok die zich als
    gegeven voordoet.
    """

    veld: str
    waarde: str
    bron: str
    geverifieerd: bool = False
    motivering: str = ""
    # Verlaagt deze aanname de exactheidsklasse van een bedrag? Een onbekende
    # EAN is administratief en raakt geen enkele euro; een geraden
    # paneelvermogen of een pro-rata-verdeling wel. Zonder dit onderscheid zou
    # bijna elk resultaat "geschat" heten en zegt die klasse niets meer.
    beinvloedt_bedrag: bool = True

    def __post_init__(self) -> None:
        if not self.veld.strip():
            raise GebruikersError("Een aanname moet zeggen welk veld ze invult.")
        if not self.bron.strip():
            raise GebruikersError(
                f"Aanname voor '{self.veld}' heeft geen bron. Een ingevulde "
                "waarde zonder herkomst hoort niet in een berekening."
            )


# ---------------------------------------------------------------------------
# EAN
# ---------------------------------------------------------------------------


def ean_controlecijfer(zeventien_cijfers: str) -> int:
    """GS1 mod-10 controlecijfer over de eerste 17 cijfers van een EAN18.

    Bron: GS1 General Specifications, standaard mod-10-berekening. Geteld vanaf
    rechts krijgt het cijfer naast het controlecijfer gewicht 3, het volgende 1,
    en zo verder afwisselend.
    """
    if len(zeventien_cijfers) != 17 or not zeventien_cijfers.isdigit():
        raise GebruikersError("Het controlecijfer verwacht exact 17 cijfers.")
    som = 0
    for positie, teken in enumerate(reversed(zeventien_cijfers)):
        gewicht = 3 if positie % 2 == 0 else 1
        som += int(teken) * gewicht
    return (10 - som % 10) % 10


def normaliseer_ean(waarde: Optional[str]) -> Optional[str]:
    """Maak een EAN18 schoon en toets het controlecijfer.

    `None` of leeg blijft `None`: een onbekende EAN is een geldige toestand —
    veel gebruikers kennen hun EAN niet uit het hoofd, en de berekening heeft
    hem niet nodig (postcode volstaat voor tariefselectie). Wat er wél staat
    moet kloppen, anders koppelt een latere Fluvius- of leveranciersopvraging
    aan het verkeerde toegangspunt.
    """
    if waarde is None:
        return None
    schoon = "".join(teken for teken in str(waarde) if teken.isdigit())
    if not schoon:
        return None
    if len(schoon) != 18:
        raise GebruikersError(
            f"Een EAN bestaat uit 18 cijfers, deze heeft er {len(schoon)}."
        )
    verwacht = ean_controlecijfer(schoon[:17])
    if int(schoon[17]) != verwacht:
        raise GebruikersError(
            "EAN-controlecijfer klopt niet: verwacht "
            f"{verwacht}, gevonden {schoon[17]}."
        )
    return schoon


# ---------------------------------------------------------------------------
# Entiteiten
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Gebruiker:
    """Manifest §5.1 `CustomerAccount` — pseudonieme identiteit.

    Draagt bewust geen naam of adres: die staan in `Persoonsgegevens`. De
    scheiding bestaat omdat login en API het doel zijn (ROADMAP Fase 11) en
    het achteraf uit elkaar halen van persoonsgegevens veel duurder is dan het
    nu al gescheiden houden.
    """

    id: UUID = field(default_factory=uuid4)
    segment: Segment = Segment.WONING
    land: str = "BE"
    toestemming_referentie: Optional[str] = None


@dataclass(frozen=True)
class Persoonsgegevens:
    """Naam en adres, apart van de rekenkundige gegevens.

    Het adres staat hier omdat het bij de persoon hoort; de postcode die de
    tariefselectie stuurt staat op het aansluitingspunt, want een gebruiker kan
    aansluitingspunten op meerdere adressen hebben.
    """

    gebruiker_id: UUID
    naam: str = ""
    email: str = ""
    straat: str = ""
    huisnummer: str = ""
    postcode: str = ""
    gemeente: str = ""


@dataclass(frozen=True)
class Aansluitingspunt:
    """Manifest §5.2 `ConnectionPoint` — één EAN, één energiedrager."""

    gebruiker_id: UUID
    energie_type: EnergieType
    postcode: str
    gemeente: str = ""
    ean_code: Optional[str] = None
    netbeheerder_code: str = ""
    spanningsniveau: Spanningsniveau = Spanningsniveau.LAAG
    aansluitingsvermogen_kva: Optional[Decimal] = None
    aantal_fasen: Optional[int] = None
    # Gebouwkenmerken, vrije tekst en geen vaste lijst — net als `type_wp` op
    # een warmtepomp: een derde/vierde variant (bv. "gesloten") mag niet op
    # een codewijziging wachten. Bedoeld als invoer voor een toekomstig
    # gebouw-warmtevraagmodel (zie CLAUDE.md "Uitbreiding dossiermodel");
    # vandaag enkel meegenomen en niet door een berekening gelezen.
    bebouwingstype: str = ""
    bewoonbare_oppervlakte_m2: Optional[Decimal] = None
    geldig_van: Optional[date] = None
    geldig_tot: Optional[date] = None
    id: UUID = field(default_factory=uuid4)

    def __post_init__(self) -> None:
        postcode = str(self.postcode).strip()
        if not (len(postcode) == 4 and postcode.isdigit()):
            raise GebruikersError(
                f"Postcode moet uit vier cijfers bestaan, kreeg '{self.postcode}'."
            )
        object.__setattr__(self, "postcode", postcode)
        object.__setattr__(self, "ean_code", normaliseer_ean(self.ean_code))
        if self.aantal_fasen is not None and self.aantal_fasen not in (1, 3):
            raise GebruikersError(
                "Een laagspanningsaansluiting is 1-fasig (230 V) of 3-fasig "
                f"(400 V); {self.aantal_fasen} fasen bestaat niet."
            )
        if (
            self.aansluitingsvermogen_kva is not None
            and self.aansluitingsvermogen_kva <= 0
        ):
            raise GebruikersError("Aansluitingsvermogen moet groter dan nul zijn.")
        if self.bewoonbare_oppervlakte_m2 is not None and self.bewoonbare_oppervlakte_m2 <= 0:
            raise GebruikersError("Bewoonbare oppervlakte moet groter dan nul zijn.")
        _controleer_periode(self.geldig_van, self.geldig_tot, "aansluitingspunt")


@dataclass(frozen=True)
class Meter:
    """Meetregime en registerschema — samen bepalen ze de nettariefkeuze.

    `terugdraaiend` staat apart van `meterregime`: alleen een klassieke,
    terugdraaiende meter mét PV valt onder het prosumententarief. Een digitale
    meter met PV valt daar níet onder (`price_model_low_voltage.md` §4.5), en
    dat verschil loopt in de honderden euro's per jaar.

    De twee maandpiekvelden horen hier en niet bij het verbruik: de ondergrens
    van 2,5 kW hangt aan het meetregime, niet aan hoeveel er verbruikt is.
    """

    aansluitingspunt_id: UUID
    meterregime: Meterregime = Meterregime.DIGITAAL
    registerschema: Registerschema = Registerschema.ENKELVOUDIG
    terugdraaiend: bool = False
    geschatte_maandpiek_kw: Decimal = D("4.218")
    minimum_maandpiek_kw: Decimal = D("2.5")
    geldig_van: Optional[date] = None
    geldig_tot: Optional[date] = None
    id: UUID = field(default_factory=uuid4)

    def __post_init__(self) -> None:
        if self.terugdraaiend and self.meterregime is not Meterregime.KLASSIEK:
            raise GebruikersError(
                "Alleen een klassieke (Ferraris) meter kan terugdraaien. Een "
                "digitale meter registreert afname en injectie apart en valt "
                "niet onder het prosumententarief."
            )
        _controleer_periode(self.geldig_van, self.geldig_tot, "meter")

    @property
    def heeft_gemeten_maandpiek(self) -> bool:
        """Alleen digitale en AMR-meters leveren een gemeten kwartierpiek."""
        return self.meterregime in (Meterregime.DIGITAAL, Meterregime.AMR)


@dataclass(frozen=True)
class InstallatieAsset:
    """PV, batterij, EV, warmtepomp of gastoestel achter één aansluitingspunt.

    `merk`/`model` sluiten aan op de sleutel `(merk, model)` van
    `hardware.BatterijRepository` en `hardware.OmvormerRepository`, zodat een
    asset naar een nameplate-specificatie met bronvermelding wijst in plaats van
    naar losse getallen.

    **Meerdere PV-assets op hetzelfde aansluitingspunt is het model voor
    oriëntatie**, niet een geneste sub-structuur: een installatie met
    oost/zuid/west-strings is drie `InstallatieAsset(type=PV, ...)`-rijen, elk
    met zijn eigen `kwp`/`omvormer_kva`/`richting`. Eén asset zonder
    `richting` (het eenvoudige, éénrichting-geval) blijft het bestaande
    gedrag — `productie_uit_kwp()`/`productiereeks()` sommeren vandaag nog
    gewoon over alle PV-assets op het punt, ongeacht `richting`; een
    oriëntatie-afhankelijk productiemodel is een latere stap (zie CLAUDE.md
    "Uitbreiding dossiermodel").
    """

    aansluitingspunt_id: UUID
    type: AssetType
    merk: str = ""
    model: str = ""
    kwp: Optional[Decimal] = None
    omvormer_merk: str = ""
    omvormer_model: str = ""
    omvormer_kva: Optional[Decimal] = None
    topologie: Optional[Topologie] = None
    # Oriëntatie van een PV-string ("oost"/"zuid"/"west", of een gradengetal
    # als tekst) — vrije tekst, geen vaste lijst, om dezelfde reden als
    # `Aansluitingspunt.bebouwingstype`. Leeg voor elk ander asset-type.
    richting: str = ""
    # Generiek nominaal vermogen: voor een `GASTOESTEL` het thermisch
    # vermogen. Een warmtepomp haalt haar vermogens uit `hardware.WarmtepompSpec`
    # (via `merk`/`model`), dus dit veld is daar niet de bron van waarheid.
    vermogen_kw: Optional[Decimal] = None
    # Waartoe het toestel dient: "ruimteverwarming"/"warm_water"/"beide" voor
    # een `GASTOESTEL`. Vrije tekst om dezelfde reden als `type_wp` op een
    # warmtepomp: een derde doel (bv. koken) mag niet op een migratie wachten.
    doel: str = ""
    geldig_van: Optional[date] = None
    geldig_tot: Optional[date] = None
    id: UUID = field(default_factory=uuid4)

    def __post_init__(self) -> None:
        if self.type is AssetType.PV and self.kwp is None:
            raise GebruikersError(
                "Een PV-installatie zonder kWp is niet te simuleren: het "
                "SPP-profiel geeft productie *per kWp*, geen verdeling."
            )
        if self.type is AssetType.BATTERIJ and self.topologie is None:
            raise GebruikersError(
                "Een batterij zonder topologie is niet te simuleren: AC- en "
                "DC-gekoppeld verschillen in welke kWh de meter passeert."
            )
        if self.vermogen_kw is not None and self.vermogen_kw <= 0:
            raise GebruikersError("vermogen_kw moet groter dan nul zijn.")
        _controleer_periode(self.geldig_van, self.geldig_tot, "installatie")


@dataclass(frozen=True)
class Leveringscontract:
    """Het contract van de klant met zijn leverancier.

    Niet te verwarren met `Contracttype`/`contract_richting` elders in deze
    codebase: dáár betekent "Contracttype" de waarde "Afname" of "Injectie".

    `tariefkaart_geldig_van` is de kern van een correcte historische kost. Een
    *vast* contract volgt de actuele tariefkaart niet — de prijs bevriest bij
    ondertekening. Zonder dit veld zou een terugblik het contract aan de
    tariefrij van vandaag koppelen en een verkeerd bedrag geven.
    """

    aansluitingspunt_id: UUID
    leverancier: str
    product: str
    contracttype: Contracttype
    geldig_van: date
    geldig_tot: Optional[date] = None
    vreg_id: Optional[str] = None
    tariefkaart_geldig_van: Optional[date] = None
    # Meestal leeg: injectie hoort bij hetzelfde product, met een eigen regel in
    # de tariefkaart — "Bolt Variabel" bestaat in de V-test-export in beide
    # richtingen. Vul dit alleen wanneer de leverancier voor teruglevering een
    # ander product hanteert dan voor afname.
    injectie_product: str = ""
    bron: str = ""
    id: UUID = field(default_factory=uuid4)

    def __post_init__(self) -> None:
        if not self.leverancier.strip():
            raise GebruikersError("Een leveringscontract heeft een leverancier nodig.")
        _controleer_periode(self.geldig_van, self.geldig_tot, "leveringscontract")

    @property
    def prijs_bevriest(self) -> bool:
        """Vast en ToU liggen vast bij ondertekening; variabel en dynamisch niet."""
        return self.contracttype in (Contracttype.VAST, Contracttype.TOU)

    def peil_tariefkaart(self) -> date:
        """De datum waarop de tariefkaart van dit contract opgezocht wordt.

        Voor een vast contract is dat de bevroren kaart (of, als die niet
        genoteerd is, de startdatum van het contract). Voor een variabel of
        dynamisch contract bestaat er geen bevroren kaart: dat wordt per
        deelperiode opgezocht en deze waarde is dan alleen het startpunt.
        """
        return self.tariefkaart_geldig_van or self.geldig_van


@dataclass(frozen=True)
class Verbruiksopgave:
    """Manifest §5.3 `ConsumptionProfile` voor één periode.

    Draagt zijn eigen `bron`, en daaruit volgt de exactheidsklasse. Een
    handmatig doorgegeven jaarverbruik is `GERECONSTRUEERD`, niet `EXACT`: het
    is de beste beschikbare opgave, maar niet tegen een factuur gelegd.
    """

    aansluitingspunt_id: UUID
    periode_van: date
    periode_tot: date
    afname_dag_kwh: Decimal = D("0")
    afname_nacht_kwh: Decimal = D("0")
    afname_exclusief_nacht_kwh: Decimal = D("0")
    injectie_dag_kwh: Decimal = D("0")
    injectie_nacht_kwh: Decimal = D("0")
    bron: OpgaveBron = OpgaveBron.MANUEEL
    dekkingsgraad: Decimal = D("1")
    aannames: tuple[Aanname, ...] = ()
    id: UUID = field(default_factory=uuid4)

    def __post_init__(self) -> None:
        if self.periode_tot <= self.periode_van:
            raise GebruikersError(
                "Een verbruiksperiode is half-open [van, tot) en moet minstens "
                f"één dag beslaan; kreeg {self.periode_van} tot {self.periode_tot}."
            )
        for naam in (
            "afname_dag_kwh",
            "afname_nacht_kwh",
            "afname_exclusief_nacht_kwh",
            "injectie_dag_kwh",
            "injectie_nacht_kwh",
        ):
            if getattr(self, naam) < 0:
                raise GebruikersError(f"{naam} kan niet negatief zijn.")
        if not (D("0") <= self.dekkingsgraad <= D("1")):
            raise GebruikersError("Dekkingsgraad ligt tussen 0 en 1.")

    @property
    def afname_kwh(self) -> Decimal:
        return (
            self.afname_dag_kwh
            + self.afname_nacht_kwh
            + self.afname_exclusief_nacht_kwh
        )

    @property
    def injectie_kwh(self) -> Decimal:
        return self.injectie_dag_kwh + self.injectie_nacht_kwh

    @property
    def exactheidsklasse(self) -> Exactheidsklasse:
        """De klasse van deze opgave, verlaagd bij onvolledige dekking.

        Manifest §9: onvoldoende meetdekking wordt zichtbaar gerapporteerd. Een
        meting die maar de helft van de periode dekt is geen exacte meting van
        die periode — ze is een reconstructie.
        """
        klasse = _BRON_KLASSE[self.bron]
        if self.dekkingsgraad < D("1") and klasse is Exactheidsklasse.EXACT:
            return Exactheidsklasse.GERECONSTRUEERD
        return klasse


@dataclass(frozen=True)
class Toestemming:
    """ROADMAP §9: doelgebonden toestemming voor persoons- en meterdata."""

    gebruiker_id: UUID
    doel: str
    verleend_op: date
    ingetrokken_op: Optional[date] = None
    bron: str = ""
    id: UUID = field(default_factory=uuid4)

    def geldig_op(self, peildatum: date) -> bool:
        if peildatum < self.verleend_op:
            return False
        return self.ingetrokken_op is None or peildatum < self.ingetrokken_op


# ---------------------------------------------------------------------------
# Hulp
# ---------------------------------------------------------------------------


def _controleer_periode(
    van: Optional[date], tot: Optional[date], onderwerp: str
) -> None:
    if van is not None and tot is not None and tot <= van:
        raise GebruikersError(
            f"De geldigheidsperiode van {onderwerp} is half-open [van, tot) en "
            f"moet vooruit lopen; kreeg {van} tot {tot}."
        )
