"""De Synergrid C10/26-lijst als controle op de hardware-masterdata.

C10/26 is de Belgische lijst van productie-eenheden — omvormers, batterijen,
WKK's — die voldoen aan de aansluitingsvoorschriften C10/11 en dus op een
distributienet aangesloten mogen worden. Staat een toestel er niet in, dan mag
de netbeheerder de aansluiting weigeren. Voor een gebruiker die straks in een
interface een batterij of omvormer kiest, is dat de eerste vraag die telt: mag
dit ding hier überhaupt hangen?

De lijst is bovendien een *onafhankelijke bron* voor cijfers die nu uit
fabrikantsdatasheets komen. `BatterijSpec` draagt niet toevallig
`synergrid_id`, `power_control_system`, `p_active_power_w`,
`smax_apparent_power_w` en `num_phase`: dat zijn precies de kolommen van deze
lijst. Waar de masterdata `geverifieerd = false` draagt, kan ze hier tegen
gelegd worden.

Wat de lijst *niet* zegt: capaciteit in kWh, rendementen, cyclusleven. Die
blijven uit de datasheet komen.

Twee dingen om in het achterhoofd te houden bij het lezen:

- **Merken staan er in wisselende schrijfwijze in.** "Growatt" en "Growatt "
  zijn aparte waarden, en MARSTEK staat in hoofdletters. Vergelijken gebeurt
  daarom genormaliseerd.
- **Eén model heeft vaak meerdere vermeldingen**, per vermogensvariant en per
  firmwareversie. `MST-BIE5-0800` en `MST-BIE5-2500` zijn allebei "Venus-E
  energy cube", met 800 respectievelijk 2500 W.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

import pandas as pd

from energie_vlaanderen.heffingen.validation import Bevinding

# De kop staat op Excel-rij 10 (0-indexed 9): daarboven staan titel, een
# kolomnummering en een meerregelige toelichting.
KOP_RIJ = 9

BLAD_GELDIG = "C10-26 power-generating units"
BLAD_VERVALLEN = "C10-26 expired homologations"

# Kolomposities in beide bladen. Namen zijn meerregelig en wisselen per uitgave;
# de volgorde is stabiel, dus die is hier de sleutel.
KOL_SYNERGRID_ID = 1
KOL_MERK = 2
KOL_SERIE = 3
KOL_MODEL = 4
KOL_FIRMWARE = 5
KOL_PCS_KLEIN = 6
KOL_PCS_GROOT = 7
KOL_PAC = 8
KOL_SMAX = 9
KOL_FASEN = 10

# De werkbladen melden Excel's maximum van 1.048.576 rijen omdat er opmaak tot
# onderaan staat; zonder bovengrens leest pandas een miljoen lege rijen en duurt
# het inlezen minuten. De geldige lijst telde op 2026-08-26 8.168 eenheden, dus
# 50.000 is ruim en toch begrensd. Wordt die grens gehaald, dan volgt een
# waarschuwing — stil afkappen zou toestellen onzichtbaar maken.
MAX_RIJEN = 50_000

OMGEVINGSVARIABELE = "ENERGIEVERGELIJKER_C1026_PAD"
STANDAARDPAD = Path("data/datasheets/synergrid C10-26")


class HomologatieError(RuntimeError):
    """De C10/26-lijst is niet leesbaar of niet gevonden."""


def _sleutel(waarde: object) -> str:
    """Normaliseer merk- en modelnamen voor vergelijking.

    Kleine letters, en alles wat geen letter of cijfer is eruit. Zo vallen
    "Venus E", "Venus-E" en "VENUS_E" samen, en ook "Growatt " met de spatie
    die in de bronlijst staat.
    """
    return re.sub(r"[^a-z0-9]+", "", str(waarde or "").casefold())


@dataclass(frozen=True)
class C1026Vermelding:
    """Eén regel uit de lijst."""

    synergrid_id: str
    merk: str
    serie: str
    model: str
    firmware: str
    power_control_system: str
    p_active_power_w: Optional[float]
    smax_apparent_power_w: Optional[float]
    num_phase: Optional[int]
    vervallen: bool = False

    @property
    def omschrijving(self) -> str:
        delen = [self.merk, self.serie, self.model]
        return " ".join(d for d in delen if d)


class C1026Lijst:
    """De volledige lijst, doorzoekbaar op merk en model."""

    def __init__(self, vermeldingen: tuple[C1026Vermelding, ...], bron: Path) -> None:
        self.vermeldingen = vermeldingen
        self.bron = bron

    # -- laden -------------------------------------------------------------

    @classmethod
    def load(cls, pad: Path | str) -> "C1026Lijst":
        bestand = Path(pad)
        if bestand.is_dir():
            kandidaten = sorted(bestand.glob("*.xlsx"))
            if not kandidaten:
                raise HomologatieError(f"Geen .xlsx gevonden in {bestand}.")
            bestand = kandidaten[-1]
        if not bestand.is_file():
            raise HomologatieError(f"C10/26-lijst niet gevonden: {bestand}.")

        vermeldingen: list[C1026Vermelding] = []
        for blad, vervallen in ((BLAD_GELDIG, False), (BLAD_VERVALLEN, True)):
            try:
                frame = pd.read_excel(
                    bestand, sheet_name=blad, header=KOP_RIJ, dtype=object,
                    engine="openpyxl", nrows=MAX_RIJEN,
                ).dropna(how="all")
            except ValueError:
                # Het blad met vervallen homologaties ontbreekt in sommige
                # uitgaven; dat is geen fout.
                if vervallen:
                    continue
                raise HomologatieError(
                    f"Werkblad {blad!r} ontbreekt in {bestand.name}."
                ) from None
            gelezen = cls._lees_blad(frame, vervallen)
            if len(frame) >= MAX_RIJEN:
                raise HomologatieError(
                    f"Werkblad {blad!r} bereikte de leeslimiet van {MAX_RIJEN} "
                    "rijen; er kunnen eenheden ontbreken. Verhoog MAX_RIJEN."
                )
            vermeldingen.extend(gelezen)

        if not vermeldingen:
            raise HomologatieError(f"{bestand.name} bevat geen bruikbare regels.")
        return cls(tuple(vermeldingen), bestand)

    @classmethod
    def standaard(cls, project_root: Path) -> "C1026Lijst":
        """Laad de lijst van het gebruikelijke pad, of van `ENERGIEVERGELIJKER_C1026_PAD`."""
        gekozen = os.environ.get(OMGEVINGSVARIABELE)
        return cls.load(Path(gekozen) if gekozen else project_root / STANDAARDPAD)

    @staticmethod
    def _lees_blad(frame: pd.DataFrame, vervallen: bool) -> list[C1026Vermelding]:
        uit: list[C1026Vermelding] = []
        kolommen = list(frame.columns)
        if len(kolommen) <= KOL_FASEN:
            return uit

        def tekst(rij, index: int) -> str:
            waarde = rij.iloc[index]
            return "" if pd.isna(waarde) else str(waarde).replace("\n", " ").strip()

        def getal(rij, index: int) -> Optional[float]:
            waarde = rij.iloc[index]
            if pd.isna(waarde):
                return None
            try:
                return float(str(waarde).replace(",", "."))
            except ValueError:
                return None

        for _, rij in frame.iterrows():
            merk = tekst(rij, KOL_MERK)
            model = tekst(rij, KOL_MODEL)
            serie = tekst(rij, KOL_SERIE)
            if not merk or not (model or serie):
                continue
            fasen_tekst = tekst(rij, KOL_FASEN).casefold()
            fasen = 3 if "3" in fasen_tekst else (1 if "1" in fasen_tekst else None)
            uit.append(
                C1026Vermelding(
                    synergrid_id=tekst(rij, KOL_SYNERGRID_ID),
                    merk=merk,
                    serie=serie,
                    model=model,
                    firmware=tekst(rij, KOL_FIRMWARE),
                    power_control_system=(
                        tekst(rij, KOL_PCS_KLEIN) or tekst(rij, KOL_PCS_GROOT)
                    ),
                    p_active_power_w=getal(rij, KOL_PAC),
                    smax_apparent_power_w=getal(rij, KOL_SMAX),
                    num_phase=fasen,
                    vervallen=vervallen,
                )
            )
        return uit

    # -- zoeken ------------------------------------------------------------

    def merken(self) -> tuple[str, ...]:
        return tuple(sorted({v.merk.strip() for v in self.vermeldingen if v.merk.strip()}))

    def zoek(self, merk: str, model: str = "") -> tuple[C1026Vermelding, ...]:
        """Alle vermeldingen van dit merk waarvan serie of model overeenkomt.

        Zowel de serie ("Venus-E energy cube") als de modelreferentie
        ("MST-BIE5-2500") wordt vergeleken, en er wordt op deelstring gematcht:
        de masterdata noemt het model "Venus E", de lijst "Venus-E energy cube".
        """
        merk_sleutel = _sleutel(merk)
        van_merk = [v for v in self.vermeldingen if _sleutel(v.merk) == merk_sleutel]
        if not model:
            return tuple(van_merk)

        model_sleutel = _sleutel(model)
        treffers = [
            v
            for v in van_merk
            if model_sleutel and (
                model_sleutel in _sleutel(v.serie)
                or model_sleutel in _sleutel(v.model)
                or _sleutel(v.model) == model_sleutel
            )
        ]
        return tuple(treffers)


# ---------------------------------------------------------------------------
# Controle op de masterdata
# ---------------------------------------------------------------------------


def controleer_spec(spec, lijst: C1026Lijst, soort: str) -> list[Bevinding]:
    """Leg één nameplate-spec naast de C10/26-lijst.

    Wat hier een **fout** is: het toestel komt niet in de lijst voor, of alleen
    bij de vervallen homologaties. Dan mag het niet op een Belgisch
    distributienet, en een simulatie ermee beschrijft een installatie die de
    netbeheerder kan weigeren.

    Wat een **waarschuwing** is: het toestel staat er wel in, maar een cijfer
    wijkt af. De lijst is dan de sterkere bron — ze is door Synergrid
    gecontroleerd, de datasheet niet.
    """
    onderwerp = f"c10-26/{soort}"
    treffers = lijst.zoek(spec.merk, spec.model)
    if not treffers:
        van_merk = lijst.zoek(spec.merk)
        hint = (
            " Van dit merk staan wél in de lijst: "
            + ", ".join(sorted({v.omschrijving for v in van_merk})[:6])
            if van_merk
            else f" Het merk {spec.merk!r} komt helemaal niet in de lijst voor."
        )
        return [
            Bevinding(
                "fout",
                onderwerp,
                f"{spec.merk} {spec.model} staat niet in de C10/26-lijst en is "
                f"dus niet gehomologeerd voor een Belgisch distributienet.{hint}",
            )
        ]

    geldig = [v for v in treffers if not v.vervallen]
    if not geldig:
        return [
            Bevinding(
                "fout",
                onderwerp,
                f"{spec.merk} {spec.model} staat alleen bij de vervallen "
                "homologaties. De aansluiting kan geweigerd worden.",
            )
        ]

    bevindingen: list[Bevinding] = []

    # Het vermogen kiest de variant: één serie heeft vaak meerdere uitvoeringen
    # (MST-BIE5-0800 en MST-BIE5-2500 zijn allebei "Venus-E").
    gevraagd = getattr(spec, "p_active_power_w", None) or getattr(
        spec, "nominaal_ac_vermogen_w", None
    )
    fasen = getattr(spec, "num_phase", None)
    variant = _kies_variant(geldig, gevraagd, fasen)

    # 1% speling op het vermogen: de lijst noteert de gemeten waarde, de
    # datasheet de nominale. Growatt's 1-fasige SPH 5000 staat er met 4.999 W in
    # terwijl de datasheet 5.000 W noemt — exact vergelijken koppelt hem dan aan
    # de verkeerde (3-fasige) variant.
    if gevraagd and variant.p_active_power_w:
        afwijking = abs(variant.p_active_power_w - gevraagd) / gevraagd
        if afwijking > 0.01:
            vermogens = sorted({v.p_active_power_w for v in geldig if v.p_active_power_w})
            bevindingen.append(
                Bevinding(
                    "waarschuwing",
                    onderwerp,
                    f"{spec.merk} {spec.model}: de masterdata noemt "
                    f"{gevraagd:.0f} W, maar de lijst kent alleen de varianten "
                    f"{', '.join(f'{v:.0f} W' for v in vermogens)}.",
                )
            )

    if not getattr(spec, "synergrid_id", ""):
        bevindingen.append(
            Bevinding(
                "info",
                onderwerp,
                f"{spec.merk} {spec.model} is gehomologeerd als "
                f"{variant.synergrid_id} ({variant.omschrijving}); vul dat in "
                "als synergrid_id.",
            )
        )
    elif _sleutel(spec.synergrid_id) != _sleutel(variant.synergrid_id):
        bevindingen.append(
            Bevinding(
                "waarschuwing",
                onderwerp,
                f"{spec.merk} {spec.model} draagt synergrid_id "
                f"{spec.synergrid_id!r}, de lijst zegt {variant.synergrid_id!r}.",
            )
        )

    smax = getattr(spec, "smax_apparent_power_w", None)
    if smax and variant.smax_apparent_power_w and abs(smax - variant.smax_apparent_power_w) >= 1:
        bevindingen.append(
            Bevinding(
                "waarschuwing",
                onderwerp,
                f"{spec.merk} {spec.model}: smax_apparent_power_w is "
                f"{smax:.0f} VA in de masterdata en {variant.smax_apparent_power_w:.0f} VA "
                "in de C10/26-lijst. De lijst is door Synergrid gecontroleerd.",
            )
        )

    fasen = getattr(spec, "num_phase", None)
    if fasen and variant.num_phase and fasen != variant.num_phase:
        bevindingen.append(
            Bevinding(
                "waarschuwing",
                onderwerp,
                f"{spec.merk} {spec.model}: {fasen}-fasig in de masterdata, "
                f"{variant.num_phase}-fasig in de C10/26-lijst.",
            )
        )

    if not bevindingen:
        bevindingen.append(
            Bevinding(
                "info",
                onderwerp,
                f"{spec.merk} {spec.model} komt overeen met {variant.synergrid_id} "
                f"({variant.omschrijving}, {variant.p_active_power_w:.0f} W).",
            )
        )
    return bevindingen


def _kies_variant(
    kandidaten: list[C1026Vermelding],
    vermogen: Optional[float],
    fasen: Optional[int],
) -> C1026Vermelding:
    """De vermelding die het best bij deze spec past.

    Eén productserie heeft vaak meerdere vermeldingen: per vermogensvariant, per
    aantal fasen en per firmwareversie. Growatt's SPH-serie staat er zowel
    1-fasig (SPH 5000, 4.999 W) als 3-fasig (SPH 5000TL3 BH, 5.000 W) in. De
    eerste de beste nemen koppelt de masterdata dan aan het verkeerde toestel en
    levert een waarschuwing op die nergens op slaat.

    Het aantal fasen weegt zwaarder dan het vermogen: dat is een harde
    eigenschap van de aansluiting, terwijl vermogens dicht bij elkaar liggen.
    """

    def score(vermelding: C1026Vermelding) -> tuple[int, float]:
        fase_mis = 0 if (fasen is None or vermelding.num_phase in (None, fasen)) else 1
        if vermogen and vermelding.p_active_power_w:
            afstand = abs(vermelding.p_active_power_w - vermogen) / vermogen
        else:
            afstand = 1.0
        return (fase_mis, afstand)

    return min(kandidaten, key=score)


def controleer_hardware(
    lijst: C1026Lijst,
    batterijen: Iterable = (),
    omvormers: Iterable = (),
) -> list[Bevinding]:
    """Leg alle bekende batterijen en omvormers naast de lijst."""
    bevindingen: list[Bevinding] = []
    for spec in batterijen:
        bevindingen.extend(controleer_spec(spec, lijst, "batterij"))
    for spec in omvormers:
        bevindingen.extend(controleer_spec(spec, lijst, "omvormer"))
    return bevindingen
