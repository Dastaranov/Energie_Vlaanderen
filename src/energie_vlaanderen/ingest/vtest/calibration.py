"""Kalibratie van heffingen en nettarieven tegen vtest.be zelf.

Waarom dit bestaat
------------------
`config/heffingen/*.toml` is handmatig onderhouden masterdata. De enige manier
om te weten of die cijfers nog kloppen, is ze vergelijken met een bron die de
officiële berekening *uitvoert*. vtest.be is die bron: elke resultatenrij bevat
een `data-productinvoicestring` met VREG's eigen kostenopbouw, inclusief de
groep "Heffingen" (Bijzondere accijns, Bijdrage op de energie, Bijdrage
Energiefonds) en de groep "Nettarieven".

Die bedragen zijn een zuivere functie van het ingevulde jaarverbruik. Door
hetzelfde profiel bij verschillende verbruiken op te vragen en de bedragen
tegen het verbruik uit te zetten, valt de onderliggende tariefstructuur exact
terug te rekenen: elk lineair stuk is één verbruiksschijf, de helling is het
tarief in EUR/MWh en een knik markeert een schijfgrens.

Dat is geen schatting maar een reconstructie — bij een perfect passende
stuksgewijs-lineaire fit is de residu nul tot op de afrondingscent van
vtest.be.

Gebruik
-------
    energievergelijker staging calibrate --version <id> [--postcode 9120]

Het resultaat (`calibration_report.json` in de staging-map) bevat per
heffingscomponent de teruggerekende schijven, en per nettariefcomponent de
helling in EUR/kWh en de vaste term — klaar om tegen `config/heffingen/` en
`tariffs_*.csv` te leggen.
"""

from __future__ import annotations

import json
import logging
import time
from collections import Counter
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from .html_downloader import VTestHtmlDownloader
from .product_parser import VTestProductParser

LOG = logging.getLogger(__name__)

# Verbruikspunten (kWh/jaar). Dicht rond de vermoede schijfgrenzen
# (elektriciteit 3 MWh "basisverbruik" en 20 MWh; gas 12 MWh), plus punten
# ruim daarbuiten zodat elke schijf minstens twee metingen krijgt en de
# helling dus bepaald is.
ELEKTRICITEIT_PUNTEN = (1_000, 2_900, 3_100, 6_000, 19_500, 20_500, 25_000)
GAS_PUNTEN = (4_000, 11_900, 12_100, 20_000, 35_000)

# vtest.be rondt elk componentbedrag af op eurocent. Twee metingen die
# hetzelfde tarief delen, mogen dus tot een halve cent per meting afwijken.
AFRONDING = Decimal("0.01")
# Speelruimte bij het toetsen of een meting nog op dezelfde rechte ligt: de
# afronding van vtest.be aan beide uiteinden plus die van het punt zelf.
TOLERANTIE = Decimal("0.02")
# Aandeel van de contracten dat hetzelfde bedrag moet dragen voordat we een
# component als verbruiksafhankelijk (en niet leveranciersafhankelijk)
# beschouwen. Het sociaal tarief is doorgaans één contract op enkele
# tientallen, dus een ruime meerderheid volstaat.
DOMINANT_DREMPEL = Decimal("0.6")


class CalibrationError(RuntimeError):
    pass


@dataclass
class Meting:
    """Eén scrape: het ingevulde verbruik en de bedragen die vtest.be teruggaf."""

    kwh: int
    postcode: str
    energy: str
    segment: str
    producten: int
    # component_naam -> het bedrag excl. btw dat de meeste contracten dragen.
    # Heffingen zijn wettelijk en dus voor elk contract gelijk; toch is het
    # bedrag zelden uniek, want het sociaal tarief kent eigen, lagere
    # accijnzen. Daarom nemen we de dominante waarde en niet de unieke.
    componenten: dict[str, str] = field(default_factory=dict)
    # component_naam -> aandeel van de contracten met die dominante waarde.
    # Ligt dit laag, dan hangt de component van de leverancier af en is het
    # geen zuivere functie van het verbruik.
    dominant_aandeel: dict[str, str] = field(default_factory=dict)
    # component_naam -> aantal verschillende bedragen dat we zagen.
    spreiding: dict[str, int] = field(default_factory=dict)


@dataclass
class Schijf:
    van_kwh: int
    tot_kwh: int | None
    eur_per_mwh: str


@dataclass
class ComponentFit:
    component: str
    groep: str
    # Vaste term (EUR/jaar) als de component niet met het verbruik meeschaalt.
    vaste_term_eur: str | None
    schijven: list[Schijf]
    max_residu_eur: str
    sluitend: bool
    metingen: list[dict[str, str]]


def _d(value: str | int | float) -> Decimal:
    return Decimal(str(value))


class VTestCalibrator:
    """Rekent heffingen- en nettariefstructuren terug uit vtest.be."""

    def __init__(
        self,
        downloader: VTestHtmlDownloader | None = None,
        parser: VTestProductParser | None = None,
        pauze_seconden: float = 5.0,
    ) -> None:
        self.downloader = downloader or VTestHtmlDownloader()
        self.parser = parser or VTestProductParser()
        # Hoffelijkheidspauze tussen scrapes — dezelfde afspraak als
        # refine_matrix: vtest.be is een publieke dienst, geen API.
        self.pauze_seconden = pauze_seconden

    # -- scrapen ---------------------------------------------------------

    def meet(
        self,
        kwh: int,
        postcode: str,
        energy: str,
        segment: str = "woning",
        browser: str = "chrome",
        headless: bool = True,
    ) -> Meting:
        """Vraag vtest.be één keer op met `kwh` jaarverbruik en vat de
        kostencomponenten samen.

        `segment` maakt uit: de accijnshervorming van 2023 gold enkel voor
        residentiële afnemers, dus "woning" en "onderneming" dragen
        wezenlijk andere tarieven (46,00 tegenover 14,21 EUR/MWh).
        """
        html = self.downloader.download(
            postcode=postcode,
            segment=segment,
            energy=energy,
            kwh_elektriciteit=kwh if energy == "elektriciteit" else 0,
            kwh_gas=kwh if energy == "gas" else 0,
            headless=headless,
            browser=browser,
            force_eigen_verbruik=True,
        )
        producten = self.parser.parse(html)
        if not producten:
            raise CalibrationError(
                f"Geen producten gevonden voor {energy} @ {kwh} kWh, postcode {postcode}."
            )

        # Per component tellen hoe vaak elk bedrag voorkomt.
        gezien: dict[tuple[str, str], Counter[str]] = {}
        for product in producten:
            if not product.invoice_raw:
                continue
            for groep in product.invoice_raw.get("groupResults") or []:
                groep_naam = groep.get("name", "")
                for comp in groep.get("componentResults") or []:
                    sleutel = (groep_naam, comp.get("name", ""))
                    bedrag = (comp.get("price") or {}).get("totalExVAT")
                    if bedrag is None:
                        continue
                    gezien.setdefault(sleutel, Counter())[str(_d(bedrag))] += 1

        componenten: dict[str, str] = {}
        dominant_aandeel: dict[str, str] = {}
        spreiding: dict[str, int] = {}
        for (groep_naam, comp_naam), teller in gezien.items():
            label = f"{groep_naam}|{comp_naam}"
            spreiding[label] = len(teller)
            waarde, aantal = teller.most_common(1)[0]
            componenten[label] = waarde
            dominant_aandeel[label] = str(
                (_d(aantal) / _d(sum(teller.values()))).quantize(Decimal("0.0001"))
            )

        return Meting(
            kwh=kwh,
            postcode=postcode,
            energy=energy,
            segment=segment,
            producten=len(producten),
            componenten=componenten,
            dominant_aandeel=dominant_aandeel,
            spreiding=spreiding,
        )

    def meet_reeks(
        self,
        punten: tuple[int, ...],
        postcode: str,
        energy: str,
        segment: str = "woning",
        browser: str = "chrome",
        headless: bool = True,
    ) -> list[Meting]:
        metingen: list[Meting] = []
        for index, kwh in enumerate(punten):
            if index:
                time.sleep(self.pauze_seconden)
            LOG.info(
                "Kalibratie %s/%s @ %s kWh (postcode %s) ...",
                segment, energy, kwh, postcode,
            )
            metingen.append(
                self.meet(
                    kwh, postcode, energy, segment=segment,
                    browser=browser, headless=headless,
                )
            )
        return metingen

    # -- terugrekenen ----------------------------------------------------

    @staticmethod
    def fit(metingen: list[Meting]) -> list[ComponentFit]:
        """Reconstrueer per component de stuksgewijs-lineaire tariefstructuur.

        Werkwijze: sorteer de metingen op verbruik en lees ze als een
        cumulatieve kostenfunctie. Tussen twee opeenvolgende metingen is het
        marginale tarief (bedrag_2 - bedrag_1) / (kwh_2 - kwh_1). Opeenvolgende
        intervallen met hetzelfde marginale tarief horen bij dezelfde schijf en
        worden samengevoegd; een verandering markeert een schijfgrens.

        De schijfgrens ligt ergens tússen de twee metingen die hem insluiten —
        de exacte grens is daarmee niet bepaald, wel begrensd. We rapporteren
        de bovengrens van de laatste meting die nog in de vorige schijf viel;
        `ELEKTRICITEIT_PUNTEN`/`GAS_PUNTEN` zijn zo gekozen dat die punten dicht
        genoeg bij de verwachte grenzen liggen om bruikbaar te zijn.
        """
        if len(metingen) < 2:
            raise CalibrationError(
                "Minstens twee metingen nodig om een tariefstructuur terug te rekenen."
            )

        gesorteerd = sorted(metingen, key=lambda m: m.kwh)

        def stabiel(meting: Meting) -> set[str]:
            """Componenten waarvan het dominante bedrag breed genoeg gedragen
            wordt om als functie van het verbruik te gelden."""
            return {
                label
                for label in meting.componenten
                if _d(meting.dominant_aandeel.get(label, "0")) >= DOMINANT_DREMPEL
            }

        gemeenschappelijk = stabiel(gesorteerd[0])
        for meting in gesorteerd[1:]:
            gemeenschappelijk &= stabiel(meting)

        fits: list[ComponentFit] = []
        for label in sorted(gemeenschappelijk):
            groep, _, component = label.partition("|")
            punten = [(m.kwh, _d(m.componenten[label])) for m in gesorteerd]

            # Vaste term? Dan is elk bedrag gelijk.
            bedragen = {bedrag for _, bedrag in punten}
            if len(bedragen) == 1:
                fits.append(
                    ComponentFit(
                        component=component,
                        groep=groep,
                        vaste_term_eur=str(punten[0][1]),
                        schijven=[],
                        max_residu_eur="0",
                        sluitend=True,
                        metingen=[
                            {"kwh": str(kwh), "eur": str(bedrag)} for kwh, bedrag in punten
                        ],
                    )
                )
                continue

            # Gulzige segmentatie: rek één rechte zo ver mogelijk uit. Een punt
            # hoort nog bij de lopende schijf als de rechte door het beginpunt
            # en dat punt óók alle tussenliggende metingen verklaart binnen de
            # afronding van vtest.be. Zo niet, dan zit er een knik tussen — een
            # schijfgrens — en begint een nieuwe schijf.
            #
            # Dit toetst op bedragen (EUR), niet op hellingen: een helling over
            # een breed interval draagt veel minder afrondingsruis dan één over
            # een smal interval, en een vaste tolerantie op hellingen zou die
            # twee onterecht gelijk behandelen.
            schijven: list[Schijf] = []
            start = 0
            while start < len(punten) - 1:
                eind = start + 1
                beste_eind = eind
                while eind < len(punten):
                    kwh_0, eur_0 = punten[start]
                    kwh_n, eur_n = punten[eind]
                    helling = (eur_n - eur_0) / _d(kwh_n - kwh_0)
                    if all(
                        abs((eur_0 + _d(kwh - kwh_0) * helling) - eur) <= TOLERANTIE
                        for kwh, eur in punten[start + 1 : eind]
                    ):
                        beste_eind = eind
                        eind += 1
                    else:
                        break
                kwh_0, eur_0 = punten[start]
                kwh_n, eur_n = punten[beste_eind]
                tarief = (eur_n - eur_0) / _d(kwh_n - kwh_0) * _d(1000)
                laatste_schijf = beste_eind == len(punten) - 1
                schijven.append(
                    Schijf(
                        van_kwh=kwh_0,
                        tot_kwh=None if laatste_schijf else kwh_n,
                        eur_per_mwh=str(tarief.quantize(Decimal("0.000001"))),
                    )
                )
                start = beste_eind

            # Residu: voorspel elk gemeten bedrag terug uit de schijven.
            # Een sluitende fit betekent dat de gereconstrueerde structuur de
            # waarnemingen tot op de afrondingscent verklaart.
            max_residu = Decimal(0)
            basis_kwh, basis_eur = punten[0]
            for kwh, gemeten in punten:
                voorspeld = basis_eur
                resterend = kwh - basis_kwh
                positie = basis_kwh
                for schijf in schijven:
                    if resterend <= 0:
                        break
                    bovengrens = schijf.tot_kwh if schijf.tot_kwh is not None else kwh
                    stuk = min(resterend, max(0, bovengrens - positie))
                    voorspeld += _d(stuk) * _d(schijf.eur_per_mwh) / _d(1000)
                    resterend -= stuk
                    positie += stuk
                max_residu = max(max_residu, abs(voorspeld - gemeten))

            fits.append(
                ComponentFit(
                    component=component,
                    groep=groep,
                    vaste_term_eur=None,
                    schijven=schijven,
                    max_residu_eur=str(max_residu.quantize(Decimal("0.0001"))),
                    sluitend=max_residu <= AFRONDING,
                    metingen=[
                        {"kwh": str(kwh), "eur": str(bedrag)} for kwh, bedrag in punten
                    ],
                )
            )

        return fits

    # -- volledige run ---------------------------------------------------

    def run(
        self,
        staging_dir: Path,
        postcode: str = "9120",
        segment: str = "woning",
        browser: str = "chrome",
        headless: bool = True,
        elektriciteit_punten: tuple[int, ...] = ELEKTRICITEIT_PUNTEN,
        gas_punten: tuple[int, ...] = GAS_PUNTEN,
    ) -> Path:
        staging_dir.mkdir(parents=True, exist_ok=True)
        rapport: dict[str, object] = {
            "schema_version": 2,
            "postcode": postcode,
            "segment": segment,
            "uitgevoerd_op": datetime.now(timezone.utc).isoformat(),
            "bron": "https://www.vtest.be/ (data-productinvoicestring)",
        }

        for energy, punten in (
            ("elektriciteit", elektriciteit_punten),
            ("gas", gas_punten),
        ):
            metingen = self.meet_reeks(
                punten, postcode, energy, segment=segment,
                browser=browser, headless=headless,
            )
            fits = self.fit(metingen)
            rapport[energy] = {
                "verbruikspunten_kwh": list(punten),
                "metingen": [asdict(m) for m in metingen],
                "componenten": [asdict(f) for f in fits],
            }
            LOG.info(
                "%s: %d componenten teruggerekend, %d sluitend.",
                energy,
                len(fits),
                sum(1 for f in fits if f.sluitend),
            )

        # Eén rapport per segment: de tarieven verschillen wezenlijk en
        # mogen elkaar niet overschrijven.
        achtervoegsel = "" if segment == "woning" else f"_{segment}"
        pad = staging_dir / f"calibration_report{achtervoegsel}.json"
        pad.write_text(
            json.dumps(rapport, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        LOG.info("Kalibratierapport geschreven naar %s", pad)
        return pad
