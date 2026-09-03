"""Wie is de netbeheerder op dit adres?

`Calculator.grid_cost()` roept `repo.dnb_for(postcode, gemeente)` aan om te weten
welke tariefrijen gelden. Die methode bestond niet: alleen een fake in
`tests/test_calculator_heffingen.py` hield de berekening draaiend, waardoor de
nettarieven nog nooit tegen echte data gedraaid zijn. Deze module vult dat gat.

Bron is `data/current/DnbPerGemeente.csv`, hetzelfde bestand dat
`infrastructure/db/importer.py::import_gemeente` en
`ingest/vtest/refine_matrix.py::representatieve_postcodes` al gebruiken.

Twee dingen die de vorm bepalen:

- **Elektriciteit en gas kunnen een verschillende netbeheerder hebben.** Het
  bestand heeft daar twee aparte kolommen voor, en op één postcode lopen ze
  werkelijk uiteen.
- **De postcode alleen volstaat niet altijd.** Postcode 2387 dekt zowel
  Zondereigen (gas: Fluvius Kempen) als Baarle-Hertog (gas: Enexis Netbeheer,
  een Belgische enclave in Nederland). Zonder gemeentenaam is daar geen
  eenduidig antwoord, en een gok zou stil het verkeerde tarief opleveren.
  Op augustus 2026 is dat de enige postcode met zo'n conflict (519 postcodes,
  1 conflict op gas, 0 op elektriciteit) — maar de regel geldt algemeen.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import pandas as pd

from energie_vlaanderen.utility.constants import DNB_CODES, DNB_ZONDER_TARIEVEN
from energie_vlaanderen.utility.normalizer import clean_text

LOG = logging.getLogger(__name__)

KOLOM_PER_ENERGIE = {
    "elektriciteit": "DNB Elektriciteit",
    "gas": "DNB Gas",
}


class NetbeheerderError(RuntimeError):
    """De netbeheerder voor dit adres is niet eenduidig te bepalen."""


def dnb_code(naam: str) -> str:
    """Vertaal een volledige netbeheerdernaam naar zijn afkorting.

    Een onbekende naam levert de naam zelf terug, met een waarschuwing: stil
    een bestaande code kiezen zou tarieven van de verkeerde netbeheerder
    toepassen.
    """
    code = DNB_CODES.get(naam)
    if code is None:
        LOG.warning(
            "Netbeheerder %r staat niet in DNB_CODES; volledige naam wordt als code gebruikt.",
            naam,
        )
        return naam
    return code


@dataclass(frozen=True)
class NetbeheerderRegister:
    """Postcode (+ gemeente) → netbeheerder, per energiedrager."""

    bron: Path
    # {(postcode, energie_type): {gemeente_sleutel: (gemeente_zoals_geschreven, dnb_naam)}}
    _per_postcode: dict[tuple[str, str], dict[str, tuple[str, str]]]

    @classmethod
    def load(cls, csv_path: Path) -> "NetbeheerderRegister":
        pad = Path(csv_path)
        if not pad.is_file():
            raise NetbeheerderError(
                f"DnbPerGemeente.csv niet gevonden op {pad}. Zonder dit bestand "
                "is de netbeheerder — en dus het nettarief — niet te bepalen."
            )
        df = pd.read_csv(pad, sep=";", dtype=str, encoding="utf-8-sig")
        ontbrekend = [k for k in ("Postcode", "Gemeente", *KOLOM_PER_ENERGIE.values()) if k not in df.columns]
        if ontbrekend:
            raise NetbeheerderError(
                f"{pad.name} mist de kolom(men) {', '.join(ontbrekend)}."
            )

        index: dict[tuple[str, str], dict[str, tuple[str, str]]] = {}
        for _, rij in df.iterrows():
            postcode = clean_text(rij["Postcode"])
            gemeente = clean_text(rij["Gemeente"])
            if not postcode:
                continue
            for energie_type, kolom in KOLOM_PER_ENERGIE.items():
                naam = clean_text(rij[kolom])
                if not naam:
                    # Geen gasnet op deze postcode. Dat is een geldig gegeven,
                    # geen ontbrekende waarde — het wordt een duidelijke fout
                    # zodra er wél een gasberekening gevraagd wordt.
                    continue
                index.setdefault((postcode, energie_type), {})[gemeente.casefold()] = (
                    gemeente,
                    naam,
                )

        return cls(bron=pad, _per_postcode=index)

    @classmethod
    def uit_rijen(
        cls,
        rijen: Iterable[tuple[str, str, str | None, str | None]],
        *,
        herkomst: str = "databank",
    ) -> "NetbeheerderRegister":
        """Bouw het register uit rijen `(postcode, gemeente, dnb_elek, dnb_gas)`.

        Bestaat zodat de databank dezelfde opzoeking krijgt als het CSV, en niet
        een tweede implementatie ernaast. De regel die postcode 2387
        (Zondereigen/Baarle-Hertog) niet laat raden, hoort op één plek te staan.
        """
        index: dict[tuple[str, str], dict[str, tuple[str, str]]] = {}
        for postcode_ruw, gemeente_ruw, dnb_elek, dnb_gas in rijen:
            postcode = clean_text(postcode_ruw)
            gemeente = clean_text(gemeente_ruw)
            if not postcode:
                continue
            for energie_type, naam_ruw in (("elektriciteit", dnb_elek), ("gas", dnb_gas)):
                naam = clean_text(naam_ruw or "")
                if not naam:
                    continue
                index.setdefault((postcode, energie_type), {})[gemeente.casefold()] = (
                    gemeente,
                    naam,
                )
        return cls(bron=Path(herkomst), _per_postcode=index)

    def dnb_for(
        self,
        postcode: str,
        gemeente: str = "",
        energie_type: str = "elektriciteit",
    ) -> tuple[str, str]:
        """De netbeheerder op dit adres, als `(naam, code)`.

        `gemeente` is alleen nodig wanneer één postcode meerdere netbeheerders
        kent; in dat geval is ze verplicht en levert een ontbrekende of
        onbekende gemeente een harde fout in plaats van een keuze.
        """
        energie_type = (energie_type or "elektriciteit").casefold()
        if energie_type not in KOLOM_PER_ENERGIE:
            raise NetbeheerderError(
                f"Onbekende energievorm '{energie_type}'; "
                f"verwacht {' of '.join(KOLOM_PER_ENERGIE)}."
            )

        sleutel = (clean_text(postcode), energie_type)
        per_gemeente = self._per_postcode.get(sleutel)
        if not per_gemeente:
            andere = "elektriciteit" if energie_type == "gas" else "gas"
            extra = ""
            if (sleutel[0], andere) in self._per_postcode:
                extra = (
                    f" Er is op deze postcode wel een netbeheerder voor {andere}; "
                    f"vermoedelijk is er geen {energie_type}net."
                )
            raise NetbeheerderError(
                f"Geen netbeheerder voor {energie_type} op postcode "
                f"{clean_text(postcode)!r} in {self.bron.name}.{extra}"
            )

        namen = {naam for _, naam in per_gemeente.values()}
        if len(namen) == 1:
            naam = next(iter(namen))
        else:
            gekozen = per_gemeente.get(clean_text(gemeente).casefold())
            if gekozen is None:
                opties = ", ".join(
                    f"{getoond or '(geen naam)'} → {dnb}"
                    for _, (getoond, dnb) in sorted(per_gemeente.items())
                )
                raise NetbeheerderError(
                    f"Postcode {clean_text(postcode)} heeft meerdere "
                    f"netbeheerders voor {energie_type} en de gemeente "
                    f"{clean_text(gemeente)!r} wijst er geen aan. Kies uit: {opties}."
                )
            naam = gekozen[1]

        return naam, dnb_code(naam)

    def heeft_tarieven(self, code: str) -> bool:
        return code not in DNB_ZONDER_TARIEVEN

    def dnb_met_tarieven(
        self,
        postcode: str,
        gemeente: str = "",
        energie_type: str = "elektriciteit",
    ) -> tuple[str, str]:
        """Als `dnb_for`, maar weigert een netbeheerder zonder tariefdata.

        Enexis (Baarle-Hertog, postcode 2387) staat onder toezicht van de
        Nederlandse ACM en publiceert zijn tarieven in een werkboek dat deze
        pipeline niet inleest. Een gasberekening daar hoort te stoppen, niet
        stilzwijgend een Fluvius-tarief te gebruiken.
        """
        naam, code = self.dnb_for(postcode, gemeente, energie_type)
        if not self.heeft_tarieven(code):
            raise NetbeheerderError(
                f"Netbeheerder {naam} ({code}) op postcode {clean_text(postcode)} "
                f"heeft geen {energie_type}tarieven in deze dataset. Een "
                "berekening hier stopt in plaats van een tarief van een andere "
                "netbeheerder te gebruiken."
            )
        return naam, code


def standaard_gemeente_csv(data_root: Path) -> Path:
    """Het pad dat de rest van dit project ook gebruikt voor dit bestand."""
    return Path(data_root) / "current" / "DnbPerGemeente.csv"
