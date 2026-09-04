"""Leest `gebruiker.toml` in als een volledig gebruikersdossier.

`gebruiker.toml` werd tot voor kort maar half gelezen: `hardware/installatie.py`
haalde er `[aansluiting.batterij]` en `[aansluiting.omvormer]` uit, de rest was
dode configuratie, en in `experiments/park/user_config.py` lag een volledige
parser die nooit gepromoveerd werd en niet meer importeerde. Beide zijn
verwijderd; dit is nu de enige lezer van het bestand, met het domeinmodel als
uitkomst.

De bestaande bestandsvorm blijft geldig. Alles wat erbij komt is optioneel:

    [gebruiker]      postcode, gemeente, segment, naam
    [aansluiting]    elektriciteit, gas, meter, zonnepanelen, omvormer_kva
                     + ean_elektriciteit, ean_gas, aansluitingsvermogen_kva,
                       aantal_fasen, registerschema, terugdraaiend, pv_kwp
    [aansluiting.batterij] / [aansluiting.omvormer]   merk, model
    [verbruik]       fluvius_csv, resolutie, ontbrekende_data
                     + jaar, afname_dag_kwh, afname_nacht_kwh,
                       afname_exclusief_nacht_kwh, injectie_dag_kwh,
                       injectie_nacht_kwh
    [huidig_contract.elektriciteit]   leverancier, product, type, startdatum
    [[contract.elektriciteit]]        idem + van/tot/tariefkaart_van

`[huidig_contract.*]` beschrijft één lopend contract zonder einddatum;
`[[contract.*]]` is de lijst met opeenvolgende contracten en is wat je nodig
hebt om over een jaar met een leverancierswissel te rekenen. Ze mogen naast
elkaar bestaan — `huidig_contract` wordt dan als laatste, nog lopende periode
toegevoegd wanneer de lijst hem niet al bevat.

Wat de gebruiker niet invult en de berekening wél nodig heeft, wordt ingevuld
met een `Aanname`: veld, waarde, bron en of dat cijfer geverifieerd is. Die
lijst reist mee tot in het eindbedrag, zodat een schatting nooit als meting
doorgaat.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Mapping, Optional

from energie_vlaanderen.gebruikers.models import (
    Aanname,
    Aansluitingspunt,
    AssetType,
    Contracttype,
    EnergieType,
    Gebruiker,
    GebruikersError,
    InstallatieAsset,
    Leveringscontract,
    Meter,
    Meterregime,
    OpgaveBron,
    Persoonsgegevens,
    Registerschema,
    Segment,
    Topologie,
    Verbruiksopgave,
)
from energie_vlaanderen.utility.constants import D

# De piek waarmee vtest.be zijn standaardwoning doorrekent, teruggerekend uit de
# capaciteitstarieven van alle acht netbeheerders op 2026-08-31. Zie de
# toelichting bij `Profile.geschatte_maandpiek_kw` in domain/models.py: de
# wettelijke ondergrens van 2,5 kW als schatting gebruiken maakte elke factuur
# ongeveer 86 EUR per jaar te laag.
STANDAARD_MAANDPIEK_BRON = (
    "vtest.be, teruggerekend uit de capaciteitstarieven van de 8 Vlaamse "
    "netbeheerders (2026-08-31)"
)


@dataclass(frozen=True)
class Dossier:
    """Alles wat één `gebruiker.toml` beschrijft, als domeinobjecten."""

    bron: Path
    gebruiker: Gebruiker
    persoonsgegevens: Optional[Persoonsgegevens]
    aansluitingspunten: tuple[Aansluitingspunt, ...]
    meters: tuple[Meter, ...]
    assets: tuple[InstallatieAsset, ...]
    contracten: tuple[Leveringscontract, ...]
    verbruiksopgaven: tuple[Verbruiksopgave, ...]
    aannames: tuple[Aanname, ...] = ()
    fluvius_csv: Optional[Path] = None

    def punt(self, energie_type: EnergieType) -> Optional[Aansluitingspunt]:
        for punt in self.aansluitingspunten:
            if punt.energie_type is energie_type:
                return punt
        return None

    def meter_van(self, punt: Aansluitingspunt) -> Optional[Meter]:
        for meter in self.meters:
            if meter.aansluitingspunt_id == punt.id:
                return meter
        return None

    def contracten_van(self, punt: Aansluitingspunt) -> tuple[Leveringscontract, ...]:
        return tuple(c for c in self.contracten if c.aansluitingspunt_id == punt.id)

    def opgaven_van(self, punt: Aansluitingspunt) -> tuple[Verbruiksopgave, ...]:
        return tuple(o for o in self.verbruiksopgaven if o.aansluitingspunt_id == punt.id)


# ---------------------------------------------------------------------------
# Kleine, strenge lezers
# ---------------------------------------------------------------------------


# Welke sleutels elke sectie kent. Een sleutel die hier niet in staat wordt
# geweigerd in plaats van genegeerd.
#
# Dat is niet overdreven strengheid. `afname_kwh` schrijven in plaats van
# `afname_dag_kwh` leverde een verbruiksopgave van 0 kWh op, en daarmee een
# berekening die netjes 21,40 EUR teruggaf in plaats van 291,56 — geen fout,
# geen waarschuwing, alleen een bedrag dat te laag was. Dezelfde foutklasse als
# elke andere stille nul in dit project: het valt pas op als iemand het cijfer
# wantrouwt.
#
# `resolutie` en `ontbrekende_data` staan hier omdat de documentatie en
# `gebruiker.voorbeeld.toml` ze noemen; ze worden vandaag door niets gelezen.
# Ze weigeren zou bestaande bestanden breken, ze weglaten zou ze onzichtbaar
# maken — vandaar dat ze toegestaan zijn met deze vermelding.
_SLEUTELS: dict[str, frozenset[str]] = {
    "gebruiker": frozenset({"postcode", "gemeente", "segment", "naam"}),
    "aansluiting": frozenset({
        "elektriciteit", "gas", "ean_elektriciteit", "ean_gas",
        "aansluitingsvermogen_kva", "aantal_fasen", "meter", "registerschema",
        "zonnepanelen", "terugdraaiend", "gemeten_maandpiek_kw", "omvormer_kva",
        "pv_kwp", "batterij", "omvormer",
    }),
    "aansluiting.batterij": frozenset({"merk", "model", "topologie"}),
    "aansluiting.omvormer": frozenset({"merk", "model"}),
    "verbruik": frozenset({
        "jaar", "periode_van", "periode_tot", "bron", "fluvius_csv",
        "resolutie", "ontbrekende_data",
        "afname_dag_kwh", "afname_nacht_kwh", "afname_exclusief_nacht_kwh",
        "injectie_dag_kwh", "injectie_nacht_kwh",
    }),
    "verbruiksopgave": frozenset({
        "energie", "periode_van", "periode_tot", "bron",
        "afname_dag_kwh", "afname_nacht_kwh", "afname_exclusief_nacht_kwh",
        "injectie_dag_kwh", "injectie_nacht_kwh",
    }),
    "contract": frozenset({
        "leverancier", "product", "type", "van", "startdatum", "tot",
        "vreg_id", "tariefkaart_van", "bron", "injectie_product",
    }),
}

# `[huidig_contract.*]` beschrijft hetzelfde als `[[contract.*]]`, alleen zonder
# einddatum. Dezelfde sleutels dus.
_SLEUTELS["huidig_contract"] = _SLEUTELS["contract"]


def _controleer_sleutels(data: Mapping[str, Any], sectie: str) -> None:
    """Weiger een sleutel die deze sectie niet kent.

    De sectienaam mag een achtervoegsel dragen (`contract.elektriciteit`,
    `huidig_contract.gas`); de sleutels zijn dezelfde.
    """
    import difflib

    basis = sectie.split(".")[0]
    toegestaan = _SLEUTELS.get(sectie) or _SLEUTELS.get(basis)
    if toegestaan is None or not isinstance(data, Mapping):
        return

    onbekend = sorted(set(data) - toegestaan)
    if not onbekend:
        return

    meldingen = []
    for sleutel in onbekend:
        # De fout is bijna altijd een typfout of een half onthouden veldnaam,
        # dus de dichtstbijzijnde bekende sleutel erbij scheelt zoekwerk.
        gelijkend = difflib.get_close_matches(sleutel, sorted(toegestaan), n=1, cutoff=0.6)
        meldingen.append(
            f"{sleutel!r}" + (f" (bedoelde je {gelijkend[0]!r}?)" if gelijkend else "")
        )

    raise GebruikersError(
        f"[{sectie}] kent de sleutel(s) {', '.join(meldingen)} niet. "
        "Een onbekende sleutel wordt geweigerd en niet genegeerd: stil "
        "overslaan levert een berekening op die klopt op een verkeerd getal. "
        f"Toegestaan: {', '.join(sorted(toegestaan))}."
    )


def _sectie(data: Mapping[str, Any], naam: str, *, verplicht: bool = True) -> Mapping[str, Any]:
    waarde = data.get(naam)
    if waarde is None:
        if verplicht:
            raise GebruikersError(f"Verplichte sectie [{naam}] ontbreekt.")
        return {}
    if not isinstance(waarde, Mapping):
        raise GebruikersError(f"[{naam}] moet een TOML-sectie zijn.")
    return waarde


def _tekst(data: Mapping[str, Any], sleutel: str, sectie: str, *, verplicht: bool = False) -> str:
    waarde = data.get(sleutel)
    if waarde is None or (isinstance(waarde, str) and not waarde.strip()):
        if verplicht:
            raise GebruikersError(f"[{sectie}].{sleutel} is verplicht.")
        return ""
    if not isinstance(waarde, str):
        raise GebruikersError(f"[{sectie}].{sleutel} moet tekst zijn.")
    return waarde.strip()


def _bool(data: Mapping[str, Any], sleutel: str, standaard: bool, sectie: str) -> bool:
    waarde = data.get(sleutel, standaard)
    if not isinstance(waarde, bool):
        raise GebruikersError(f"[{sectie}].{sleutel} moet true of false zijn.")
    return waarde


def _getal(data: Mapping[str, Any], sleutel: str, sectie: str) -> Optional[Decimal]:
    """Leest een getal als `Decimal` via zijn tekstvorm.

    Via `str()` en niet rechtstreeks uit de float: `Decimal(5.0)` levert
    5.0000000000000000000 op, `Decimal("5.0")` gewoon 5,0. Bij een
    kWh-hoeveelheid die in een geldberekening terechtkomt is dat het verschil
    tussen een exact en een benaderd bedrag.
    """
    waarde = data.get(sleutel)
    if waarde is None:
        return None
    if isinstance(waarde, bool) or not isinstance(waarde, (int, float, str)):
        raise GebruikersError(f"[{sectie}].{sleutel} moet een getal zijn.")
    try:
        return D(str(waarde).replace(",", "."))
    except InvalidOperation as exc:
        raise GebruikersError(f"[{sectie}].{sleutel} is geen geldig getal: {waarde!r}.") from exc


def _datum(data: Mapping[str, Any], sleutel: str, sectie: str, *, verplicht: bool = False) -> Optional[date]:
    waarde = data.get(sleutel)
    if waarde is None:
        if verplicht:
            raise GebruikersError(f"[{sectie}].{sleutel} is verplicht (JJJJ-MM-DD).")
        return None
    if isinstance(waarde, date):
        return waarde
    if isinstance(waarde, str):
        try:
            return date.fromisoformat(waarde.strip())
        except ValueError as exc:
            raise GebruikersError(f"[{sectie}].{sleutel} moet JJJJ-MM-DD zijn.") from exc
    raise GebruikersError(f"[{sectie}].{sleutel} moet een datum zijn.")


def _keuze(waarde: str, toegestaan: type, sectie: str, sleutel: str):
    try:
        return toegestaan(waarde.casefold())
    except ValueError as exc:
        opties = ", ".join(sorted(x.value for x in toegestaan))
        raise GebruikersError(
            f"[{sectie}].{sleutel} moet één van {opties} zijn, kreeg {waarde!r}."
        ) from exc


# ---------------------------------------------------------------------------
# Inlezen
# ---------------------------------------------------------------------------


def lees_dossier(
    pad: Path | str,
    *,
    project_root: Optional[Path] = None,
    netbeheerders=None,
) -> Dossier:
    """Leest `gebruiker.toml` en levert het volledige dossier op.

    `netbeheerders` is een optionele `NetbeheerderRegister`. Wordt die
    meegegeven, dan krijgt elk aansluitingspunt meteen zijn netbeheerdercode;
    zonder blijft die leeg en zoekt de berekening hem later zelf op.
    """
    bron = Path(pad).expanduser().resolve()
    if not bron.is_file():
        raise GebruikersError(f"Gebruikersprofiel niet gevonden: {bron}.")
    wortel = Path(project_root).resolve() if project_root else bron.parent

    try:
        with bron.open("rb") as fh:
            ruw = tomllib.load(fh)
    except tomllib.TOMLDecodeError as exc:
        raise GebruikersError(f"Ongeldige TOML in {bron.name}: {exc}") from exc

    aannames: list[Aanname] = []

    gebruiker_raw = _sectie(ruw, "gebruiker")
    aansluiting_raw = _sectie(ruw, "aansluiting")
    _controleer_sleutels(aansluiting_raw, "aansluiting")
    verbruik_raw = _sectie(ruw, "verbruik", verplicht=False)
    _controleer_sleutels(verbruik_raw, "verbruik")

    _controleer_sleutels(gebruiker_raw, "gebruiker")
    postcode = _tekst(gebruiker_raw, "postcode", "gebruiker", verplicht=True)
    gemeente = _tekst(gebruiker_raw, "gemeente", "gebruiker")
    segment = _segment(_tekst(gebruiker_raw, "segment", "gebruiker") or "Woning")

    gebruiker = Gebruiker(segment=segment)
    naam = _tekst(gebruiker_raw, "naam", "gebruiker")
    persoonsgegevens = (
        Persoonsgegevens(
            gebruiker_id=gebruiker.id,
            naam=naam,
            postcode=postcode,
            gemeente=gemeente,
        )
        if naam
        else None
    )

    # -- aansluitingspunten ------------------------------------------------
    heeft = {
        EnergieType.ELEKTRICITEIT: _bool(aansluiting_raw, "elektriciteit", True, "aansluiting"),
        EnergieType.GAS: _bool(aansluiting_raw, "gas", False, "aansluiting"),
    }
    if not any(heeft.values()):
        raise GebruikersError(
            "Minstens elektriciteit of gas moet actief zijn; zonder "
            "aansluitingspunt is er niets te berekenen."
        )

    punten: list[Aansluitingspunt] = []
    for energie_type, actief in heeft.items():
        if not actief:
            continue
        ean = _tekst(aansluiting_raw, f"ean_{energie_type.value}", "aansluiting") or None
        code = ""
        if netbeheerders is not None:
            code = netbeheerders.dnb_for(postcode, gemeente, energie_type.value)[1]
        punten.append(
            Aansluitingspunt(
                gebruiker_id=gebruiker.id,
                energie_type=energie_type,
                postcode=postcode,
                gemeente=gemeente,
                ean_code=ean,
                netbeheerder_code=code,
                aansluitingsvermogen_kva=_getal(
                    aansluiting_raw, "aansluitingsvermogen_kva", "aansluiting"
                ),
                aantal_fasen=aansluiting_raw.get("aantal_fasen"),
            )
        )
        if ean is None:
            aannames.append(
                Aanname(
                    veld=f"ean_{energie_type.value}",
                    waarde="onbekend",
                    bron="niet opgegeven in gebruiker.toml",
                    beinvloedt_bedrag=False,
                    motivering=(
                        "De EAN is niet nodig om te rekenen (de postcode stuurt "
                        "de tariefselectie), maar wel om later meetdata bij "
                        "Fluvius of de leverancier op te vragen."
                    ),
                )
            )

    # -- meters ------------------------------------------------------------
    regime_tekst = (_tekst(aansluiting_raw, "meter", "aansluiting") or "digitaal").casefold()
    # De bestaande bestandsvorm kent alleen "digitaal" en "analoog"; "analoog"
    # is in het domein "klassiek" (Ferraris).
    regime = Meterregime.KLASSIEK if regime_tekst == "analoog" else _keuze(
        regime_tekst, Meterregime, "aansluiting", "meter"
    )
    registerschema = _keuze(
        _tekst(aansluiting_raw, "registerschema", "aansluiting") or "enkelvoudig",
        Registerschema,
        "aansluiting",
        "registerschema",
    )
    zonnepanelen = _bool(aansluiting_raw, "zonnepanelen", False, "aansluiting")
    terugdraaiend = _bool(aansluiting_raw, "terugdraaiend", False, "aansluiting")
    if terugdraaiend and regime is not Meterregime.KLASSIEK:
        raise GebruikersError(
            "[aansluiting].terugdraaiend kan alleen bij een klassieke "
            "(analoge) meter. Een digitale meter registreert afname en "
            "injectie apart en valt niet onder het prosumententarief."
        )

    # Een gemeten maandpiek verslaat elke schatting: het capaciteitstarief is bij
    # een digitale meter de grootste post van de netkost, en de standaardwaarde
    # van 4,218 kW is de piek van vtest.be's standaardwoning, niet die van dit
    # gezin. Op een echte afrekening stond 7,409 kW — 76% hoger.
    gemeten_piek = _getal(aansluiting_raw, "gemeten_maandpiek_kw", "aansluiting")
    meters = [
        Meter(
            aansluitingspunt_id=punt.id,
            meterregime=regime,
            registerschema=registerschema,
            terugdraaiend=terugdraaiend,
            **({"geschatte_maandpiek_kw": gemeten_piek} if gemeten_piek else {}),
        )
        for punt in punten
        if punt.energie_type is EnergieType.ELEKTRICITEIT
    ]
    if gemeten_piek:
        aannames.append(
            Aanname(
                veld="geschatte_maandpiek_kw",
                waarde=str(gemeten_piek),
                bron="[aansluiting].gemeten_maandpiek_kw — opgegeven gemeten waarde",
                geverifieerd=True,
                beinvloedt_bedrag=True,
                motivering=(
                    "Een opgegeven gemeten maandpiek in plaats van de "
                    "standaardschatting van 4,218 kW."
                ),
            )
        )
    if not gemeten_piek and meters and regime in (Meterregime.DIGITAAL, Meterregime.AMR):
        aannames.append(
            Aanname(
                veld="geschatte_maandpiek_kw",
                waarde="4.218",
                bron=STANDAARD_MAANDPIEK_BRON,
                geverifieerd=True,
                motivering=(
                    "Er zijn geen gemeten maandpieken aangeleverd. De "
                    "wettelijke ondergrens van 2,5 kW is hier bewust níet als "
                    "schatting gebruikt: dat is een bodem, geen piek."
                ),
            )
        )

    # -- installaties ------------------------------------------------------
    assets: list[InstallatieAsset] = []
    omvormer_kva = _getal(aansluiting_raw, "omvormer_kva", "aansluiting")
    elek_punt = next(
        (p for p in punten if p.energie_type is EnergieType.ELEKTRICITEIT), None
    )
    if zonnepanelen and elek_punt is not None:
        kwp = _getal(aansluiting_raw, "pv_kwp", "aansluiting")
        if kwp is None:
            if omvormer_kva is None:
                raise GebruikersError(
                    "[aansluiting].zonnepanelen staat aan, maar er is geen "
                    "pv_kwp en geen omvormer_kva. Het SPP-profiel geeft "
                    "productie per kWp; zonder een van beide is de "
                    "PV-productie niet te schatten."
                )
            kwp = omvormer_kva
            aannames.append(
                Aanname(
                    veld="pv_kwp",
                    waarde=str(kwp),
                    bron="gelijkgesteld aan [aansluiting].omvormer_kva",
                    geverifieerd=False,
                    motivering=(
                        "Het paneelvermogen is niet opgegeven. Dit is een "
                        "plaatsvervanger gelijk aan het omvormervermogen, geen "
                        "gemeten kWp: panelen worden vaak ruimer gedimensioneerd "
                        "dan de omvormer, dus dit onderschat de productie "
                        "eerder dan ze te overschatten. Vul pv_kwp in voor een "
                        "bruikbare PV- of batterijsimulatie."
                    ),
                )
            )
        assets.append(
            InstallatieAsset(
                aansluitingspunt_id=elek_punt.id,
                type=AssetType.PV,
                kwp=kwp,
                omvormer_kva=omvormer_kva,
            )
        )

    batterij_raw = _sectie(aansluiting_raw, "batterij", verplicht=False)
    _controleer_sleutels(batterij_raw, "aansluiting.batterij")
    omvormer_raw = _sectie(aansluiting_raw, "omvormer", verplicht=False)
    _controleer_sleutels(omvormer_raw, "aansluiting.omvormer")
    merk = _tekst(batterij_raw, "merk", "aansluiting.batterij")
    model = _tekst(batterij_raw, "model", "aansluiting.batterij")
    if merk and model and elek_punt is not None:
        topologie_tekst = _tekst(batterij_raw, "topologie", "aansluiting.batterij")
        if topologie_tekst:
            topologie = _keuze(topologie_tekst, Topologie, "aansluiting.batterij", "topologie")
        else:
            # AC-gekoppeld is de voorzichtige aanname: elke kWh gaat dan door de
            # omvormer en draagt het conversieverlies. Een DC-gekoppelde
            # installatie stil aannemen zou het rendement — en dus de opbrengst
            # — te rooskleurig voorstellen.
            topologie = Topologie.AC_GEKOPPELD
            aannames.append(
                Aanname(
                    veld="batterij.topologie",
                    waarde=Topologie.AC_GEKOPPELD.value,
                    bron="voorzichtige standaardwaarde",
                    geverifieerd=False,
                    motivering=(
                        "De koppeling is niet opgegeven. AC-gekoppeld telt het "
                        "omvormerverlies mee en geeft dus de laagste opbrengst; "
                        "DC-gekoppeld of hybride aannemen zou het resultaat "
                        "gunstiger maken dan verantwoord is."
                    ),
                )
            )
        assets.append(
            InstallatieAsset(
                aansluitingspunt_id=elek_punt.id,
                type=AssetType.BATTERIJ,
                merk=merk,
                model=model,
                omvormer_merk=_tekst(omvormer_raw, "merk", "aansluiting.omvormer"),
                omvormer_model=_tekst(omvormer_raw, "model", "aansluiting.omvormer"),
                omvormer_kva=omvormer_kva,
                topologie=topologie,
            )
        )

    # -- contracten --------------------------------------------------------
    contracten = _lees_contracten(ruw, punten)

    # -- verbruik ----------------------------------------------------------
    opgaven = _lees_verbruiksopgaven(verbruik_raw, punten, ruw.get("verbruiksopgave"))

    fluvius = _tekst(verbruik_raw, "fluvius_csv", "verbruik")
    fluvius_pad = None
    if fluvius:
        kandidaat = Path(fluvius).expanduser()
        fluvius_pad = kandidaat if kandidaat.is_absolute() else (wortel / kandidaat)

    return Dossier(
        bron=bron,
        gebruiker=gebruiker,
        persoonsgegevens=persoonsgegevens,
        aansluitingspunten=tuple(punten),
        meters=tuple(meters),
        assets=tuple(assets),
        contracten=tuple(contracten),
        verbruiksopgaven=tuple(opgaven),
        aannames=tuple(aannames),
        fluvius_csv=fluvius_pad,
    )


def _segment(waarde: str) -> Segment:
    """`Segment` heeft hoofdlettergevoelige waarden ("Woning"), de TOML niet.

    De waarden van `Segment` zijn niet vrij te kiezen: ze moeten letterlijk
    overeenkomen met de segmentkolom die `DataRepository.products()` filtert.
    Daarom hier een eigen kaart in plaats van `_keuze()`.
    """
    kaart = {"woning": Segment.WONING, "onderneming": Segment.ONDERNEMING}
    gevonden = kaart.get(waarde.strip().casefold())
    if gevonden is None:
        raise GebruikersError(
            f"[gebruiker].segment moet Woning of Onderneming zijn, kreeg {waarde!r}."
        )
    return gevonden


def _lees_contracten(ruw: Mapping[str, Any], punten) -> list[Leveringscontract]:
    per_energie = {p.energie_type.value: p for p in punten}
    resultaat: list[Leveringscontract] = []

    lijsten = ruw.get("contract", {})
    if lijsten and not isinstance(lijsten, Mapping):
        raise GebruikersError("[contract] moet secties per energievorm bevatten.")
    for energie, rijen in (lijsten or {}).items():
        punt = per_energie.get(energie)
        if punt is None:
            raise GebruikersError(
                f"[[contract.{energie}]] beschrijft een contract voor {energie}, "
                f"maar [aansluiting].{energie} staat niet aan."
            )
        if isinstance(rijen, Mapping):
            rijen = [rijen]
        for rij in rijen:
            resultaat.append(_contract_uit(rij, punt, f"contract.{energie}", eind_verplicht=False))

    huidig = ruw.get("huidig_contract", {})
    if huidig and not isinstance(huidig, Mapping):
        raise GebruikersError("[huidig_contract] moet secties per energievorm bevatten.")
    for energie, rij in (huidig or {}).items():
        punt = per_energie.get(energie)
        if punt is None:
            continue
        contract = _contract_uit(
            rij, punt, f"huidig_contract.{energie}", eind_verplicht=False, start_sleutel="startdatum"
        )
        # Al beschreven in [[contract.*]]? Dan is dit dezelfde afspraak twee keer
        # genoteerd en zou toevoegen een overlappende periode maken.
        if any(
            c.aansluitingspunt_id == punt.id
            and c.leverancier == contract.leverancier
            and c.product == contract.product
            and c.geldig_van == contract.geldig_van
            for c in resultaat
        ):
            continue
        resultaat.append(contract)

    return sorted(resultaat, key=lambda c: (str(c.aansluitingspunt_id), c.geldig_van))


def _contract_uit(
    rij: Mapping[str, Any],
    punt,
    sectie: str,
    *,
    eind_verplicht: bool,
    start_sleutel: str = "van",
) -> Leveringscontract:
    if not isinstance(rij, Mapping):
        raise GebruikersError(f"[{sectie}] moet een TOML-sectie zijn.")
    _controleer_sleutels(rij, sectie)
    soort = _keuze(
        _tekst(rij, "type", sectie, verplicht=True), Contracttype, sectie, "type"
    )
    start = _datum(rij, start_sleutel, sectie) or _datum(rij, "startdatum", sectie) or _datum(rij, "van", sectie)
    if start is None:
        raise GebruikersError(
            f"[{sectie}] heeft een startdatum nodig ({start_sleutel} of startdatum). "
            "Zonder begin is de geldigheidsperiode niet te bepalen, en zonder "
            "periode is een historische kost niet te berekenen."
        )
    return Leveringscontract(
        aansluitingspunt_id=punt.id,
        leverancier=_tekst(rij, "leverancier", sectie, verplicht=True),
        product=_tekst(rij, "product", sectie),
        contracttype=soort,
        geldig_van=start,
        geldig_tot=_datum(rij, "tot", sectie, verplicht=eind_verplicht),
        vreg_id=_tekst(rij, "vreg_id", sectie) or None,
        tariefkaart_geldig_van=_datum(rij, "tariefkaart_van", sectie),
        bron=_tekst(rij, "bron", sectie),
    )


def _lees_verbruiksopgaven(
    verbruik_raw: Mapping[str, Any],
    punten,
    extra: Any = None,
) -> list[Verbruiksopgave]:
    """Een handmatig doorgegeven jaarverbruik, als er een staat.

    Bewust `OpgaveBron.MANUEEL` en dus exactheidsklasse `gereconstrueerd`: het
    is de beste beschikbare opgave, maar niet tegen een factuur of meting
    gelegd.
    """
    # `[[verbruiksopgave]]` naast of in plaats van `[verbruik]`: een afrekening
    # splitst het verbruik vaak per tariefkaartperiode, met de werkelijk
    # opgenomen meterstanden per stuk. Die aanleveren is beter dan één totaal
    # dat de berekening pro rata over de dagen moet verdelen — dat laatste
    # negeert seizoensverschillen, en juist die zijn groot.
    opgaven: list[Verbruiksopgave] = []
    if extra is not None:
        if isinstance(extra, Mapping):
            extra = [extra]
        if not isinstance(extra, list):
            raise GebruikersError("[[verbruiksopgave]] moet een lijst secties zijn.")
        for rij in extra:
            opgaven.append(_opgave_uit(rij, punten, "verbruiksopgave"))

    velden = (
        "afname_dag_kwh",
        "afname_nacht_kwh",
        "afname_exclusief_nacht_kwh",
        "injectie_dag_kwh",
        "injectie_nacht_kwh",
    )
    waarden = {veld: _getal(verbruik_raw, veld, "verbruik") for veld in velden}
    if all(waarde is None for waarde in waarden.values()):
        return opgaven

    # Een afrekening loopt zelden gelijk met het kalenderjaar: meterstanden
    # worden opgenomen wanneer het de netbeheerder uitkomt. Staat er een
    # expliciete periode, dan telt die; anders wordt `jaar` het kalenderjaar.
    # Het onderscheid is niet cosmetisch — de pro-rata verdeling over
    # deelperiodes deelt door het aantal dagen van de opgave.
    periode_van = _datum(verbruik_raw, "periode_van", "verbruik")
    periode_tot = _datum(verbruik_raw, "periode_tot", "verbruik")
    if (periode_van is None) != (periode_tot is None):
        raise GebruikersError(
            "[verbruik].periode_van en periode_tot horen samen: met maar één "
            "van beide is de meetperiode niet bepaald."
        )

    jaar = verbruik_raw.get("jaar")
    if periode_van is None and not isinstance(jaar, int):
        raise GebruikersError(
            "[verbruik] heeft een periode nodig: ofwel `jaar` voor een volledig "
            "kalenderjaar, ofwel `periode_van` en `periode_tot`. Zonder periode "
            "is niet te bepalen welke tarieven, heffingen en btw-tarieven erop "
            "van toepassing zijn."
        )

    bron_tekst = _tekst(verbruik_raw, "bron", "verbruik") or "manueel"
    try:
        bron = OpgaveBron(bron_tekst.casefold())
    except ValueError as exc:
        opties = ", ".join(sorted(b.value for b in OpgaveBron))
        raise GebruikersError(
            f"[verbruik].bron moet één van {opties} zijn, kreeg {bron_tekst!r}."
        ) from exc

    elek = next((p for p in punten if p.energie_type is EnergieType.ELEKTRICITEIT), None)
    if elek is None:
        raise GebruikersError(
            "[verbruik] beschrijft elektriciteitsverbruik, maar "
            "[aansluiting].elektriciteit staat niet aan."
        )

    return opgaven + [
        Verbruiksopgave(
            aansluitingspunt_id=elek.id,
            periode_van=periode_van or date(jaar, 1, 1),
            periode_tot=periode_tot or date(jaar + 1, 1, 1),
            bron=bron,
            **{veld: (waarde if waarde is not None else D("0")) for veld, waarde in waarden.items()},
        )
    ]


def _opgave_uit(rij: Mapping[str, Any], punten, sectie: str) -> Verbruiksopgave:
    """Eén `[[verbruiksopgave]]`-sectie."""
    if not isinstance(rij, Mapping):
        raise GebruikersError(f"[[{sectie}]] moet een TOML-sectie zijn.")

    _controleer_sleutels(rij, sectie)

    van = _datum(rij, "periode_van", sectie, verplicht=True)
    tot = _datum(rij, "periode_tot", sectie, verplicht=True)

    energie = _tekst(rij, "energie", sectie) or "elektriciteit"
    doel = next((p for p in punten if p.energie_type.value == energie), None)
    if doel is None:
        raise GebruikersError(
            f"[[{sectie}]] beschrijft {energie}, maar [aansluiting].{energie} "
            "staat niet aan."
        )

    bron_tekst = _tekst(rij, "bron", sectie) or "manueel"
    try:
        bron = OpgaveBron(bron_tekst.casefold())
    except ValueError as exc:
        opties = ", ".join(sorted(b.value for b in OpgaveBron))
        raise GebruikersError(
            f"[[{sectie}]].bron moet één van {opties} zijn, kreeg {bron_tekst!r}."
        ) from exc

    velden = (
        "afname_dag_kwh",
        "afname_nacht_kwh",
        "afname_exclusief_nacht_kwh",
        "injectie_dag_kwh",
        "injectie_nacht_kwh",
    )
    waarden = {veld: (_getal(rij, veld, sectie) or D("0")) for veld in velden}
    return Verbruiksopgave(
        aansluitingspunt_id=doel.id,
        periode_van=van,
        periode_tot=tot,
        bron=bron,
        **waarden,
    )
