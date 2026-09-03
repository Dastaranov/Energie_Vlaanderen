"""Leest de tarieftabel van de Vlaamse bijdrage energiefonds.

`config/heffingen/bijdrage_energiefonds.toml` is handgeschreven en werd tot nu
toe met de hand tegen vlaanderen.be gelegd. Dat is precies het soort controle
dat vergeten wordt: de tabel wijzigt één keer per jaar, en `docs/jaarwissel
2026-2027.md` waarschuwt dat het energiefonds bij een ontbrekend jaar hard
faalt — een berekening over 2027 stopt dus zodra dat jaar niet aangevuld is.

De pagina publiceert één HTML-tabel met de categorieën als rijen en de jaren als
kolommen. Twee eigenaardigheden bepalen de vorm van de parser:

- **De laagspanningsrijen delen één cel.** "Afnemers op laagspanning" staat in
  een cel met `rowspan=3`, waarna de drie subcategorieën (residentieel,
  niet-residentieel, beschermd) elk hun eigen rij hebben zonder die eerste
  kolom. Midden- en hoogspanning hebben geen subcategorie en zetten daar een
  lege cel.
- **Bedragen staan in Belgische notatie**: "1.120,66" is duizend-honderd-twintig
  komma zesenzestig, niet 1,12066. `dec()` uit `utility/normalizer.py` kent dat
  onderscheid al.

Deze module haalt de tabel op en zet ze om; vergelijken met de masterdata doet
`scripts/check_energiefonds.py`.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Optional

from energie_vlaanderen.utility.normalizer import clean_text, dec

LOG = logging.getLogger(__name__)

TARIEF_PAGINA = (
    "https://www.vlaanderen.be/belastingen-en-begroting/vlaamse-belastingen/"
    "energieheffingen/bijdrage-energiefonds-heffing-op-afnamepunten-van-"
    "elektriciteit/tarief-van-de-bijdrage-energiefonds"
)

# Rijlabel op de pagina -> (spanningsniveau, klantcategorie) zoals
# `config/heffingen/bijdrage_energiefonds.toml` ze schrijft. Midden- en
# hoogspanning kennen geen klantcategorie en dragen daar een lege string.
#
# De volgorde telt: "niet-residentiële afnemer" bevat "residentiële afnemer" als
# deelstring, dus de specifiekere moet eerst getoetst worden. Andersom kreeg de
# residentiële categorie de bedragen van de niet-residentiële — 10,07 in plaats
# van 0,00 EUR per maand.
RIJLABELS: tuple[tuple[str, tuple[str, str]], ...] = (
    ("niet-residentiële afnemer", ("laag", "niet_residentieel")),
    ("residentiële afnemer", ("laag", "residentieel")),
    ("beschermde klanten", ("laag", "beschermd")),
    ("afnemer op middenspanning", ("midden", "")),
    ("afnemer op hoogspanning", ("hoog", "")),
)

_JAAR = re.compile(r"\b(20\d{2})\b")


def _tekst(cel) -> str:
    """De tekst van een cel, met de regeleindes als spatie.

    De pagina breekt labels af met `<br>`: "Residentiële<br>afnemer".
    `get_text()` zonder scheidingsteken plakt die aan elkaar tot
    "Residentiëleafnemer", waardoor geen enkel rijlabel meer herkend wordt.
    """
    return clean_text(cel.get_text(" "))


class EnergiefondsError(RuntimeError):
    """De tarieftabel is niet op te halen of niet te lezen."""


@dataclass(frozen=True)
class EnergiefondsRij:
    jaar: int
    spanningsniveau: str
    klantcategorie: str
    eur_per_maand: Decimal

    @property
    def sleutel(self) -> tuple[int, str, str]:
        return (self.jaar, self.spanningsniveau, self.klantcategorie)


def parse_tabel(html: str) -> tuple[EnergiefondsRij, ...]:
    """Zet de HTML-tarieftabel om in losse rijen.

    Faalt hard wanneer er geen jaarkolommen of geen herkenbare categorieën in
    zitten: een lege uitkomst zou als "niets gewijzigd" gelezen worden, en dat
    is precies de stilte die deze controle moet doorbreken.
    """
    try:
        from bs4 import BeautifulSoup
    except ImportError as exc:  # pragma: no cover - afhankelijkheid
        raise EnergiefondsError(
            "beautifulsoup4 is niet geïnstalleerd. Voer "
            "'pip install -e \".[scrape]\"' uit."
        ) from exc

    soup = BeautifulSoup(html, "html.parser")
    tabel = soup.find("table")
    if tabel is None:
        raise EnergiefondsError("Geen tabel gevonden in de pagina.")

    rijen = tabel.find_all("tr")
    if not rijen:
        raise EnergiefondsError("De tabel bevat geen rijen.")

    # De kop draagt de jaartallen, elk in een eigen cel ("Tarief in euro per
    # maand (2026)"). De positie van die cel bepaalt welke kolom bij welk jaar
    # hoort; we tellen vanaf rechts, want links staan de categoriecellen en
    # hun aantal verschilt per rij.
    jaren: list[int] = []
    for cel in rijen[0].find_all(["td", "th"]):
        gevonden = _JAAR.findall(_tekst(cel))
        if len(gevonden) == 1:
            jaren.append(int(gevonden[0]))
    if not jaren:
        raise EnergiefondsError(
            "Geen jaartallen in de kop van de tabel; de opmaak is gewijzigd."
        )

    uit: list[EnergiefondsRij] = []
    for rij in rijen[1:]:
        cellen = rij.find_all(["td", "th"])
        if len(cellen) < len(jaren):
            continue
        # De bedragen staan achteraan: de laatste `len(jaren)` cellen. De cellen
        # ervóór zijn categorielabels, en hoeveel dat er zijn verschilt doordat
        # "Afnemers op laagspanning" met rowspan drie rijen overspant.
        labels = cellen[: len(cellen) - len(jaren)]
        bedragen = cellen[len(cellen) - len(jaren) :]

        gevonden = _herken_rij(labels)
        if gevonden is None:
            continue
        spanningsniveau, klantcategorie = gevonden

        for jaar, cel in zip(jaren, bedragen):
            waarde = dec(_tekst(cel))
            if waarde is None:
                continue
            uit.append(
                EnergiefondsRij(
                    jaar=jaar,
                    spanningsniveau=spanningsniveau,
                    klantcategorie=klantcategorie,
                    eur_per_maand=waarde,
                )
            )

    if not uit:
        raise EnergiefondsError(
            "Geen enkele categorie herkend in de tabel; de rijlabels zijn "
            "gewijzigd. Verwacht werd: "
            + ", ".join(label for label, _ in RIJLABELS)
        )
    return tuple(uit)


def _herken_rij(labels) -> Optional[tuple[str, str]]:
    """Welke categorie beschrijft deze rij?

    De laatste label-cel is de meest specifieke: bij laagspanning staat daar de
    subcategorie, bij midden- en hoogspanning het niveau zelf.
    """
    teksten = [_tekst(cel).casefold() for cel in labels]
    for tekst in reversed(teksten):
        if not tekst:
            continue
        for label, doel in RIJLABELS:
            if label in tekst:
                return doel
    return None


class EnergiefondsScraper:
    """Haalt de tarieftabel op bij vlaanderen.be."""

    def __init__(self, settings=None, url: str = TARIEF_PAGINA) -> None:
        self.settings = settings
        self.url = url

    def haal_html(self) -> str:
        import requests

        timeout = getattr(self.settings, "request_timeout_seconds", 60.0)
        agent = getattr(self.settings, "user_agent", "EnergieVergelijker/3.0")
        try:
            antwoord = requests.get(
                self.url, timeout=timeout, headers={"User-Agent": agent}
            )
            antwoord.raise_for_status()
        except Exception as exc:
            raise EnergiefondsError(
                f"Tarieftabel niet op te halen van {self.url}: {exc}"
            ) from exc
        return antwoord.text

    def tarieven(self) -> tuple[EnergiefondsRij, ...]:
        return parse_tabel(self.haal_html())


def lees_bestand(pad: Path) -> tuple[EnergiefondsRij, ...]:
    """Lees een opgeslagen kopie van de pagina — handig zonder netwerk."""
    bestand = Path(pad)
    if not bestand.is_file():
        raise EnergiefondsError(f"Bestand niet gevonden: {bestand}.")
    return parse_tabel(bestand.read_text(encoding="utf-8"))
