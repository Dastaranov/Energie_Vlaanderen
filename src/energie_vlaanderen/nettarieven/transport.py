"""Vervoerstarieven die de netbeheerder doorrekent maar niet vaststelt.

Voor aardgas is dat het tarief van Fluxys. Het staat in geen enkel
VREG-werkboek — die dekken alleen de distributie — en ontbrak daardoor
volledig, wat elke gasfactuur ongeveer 25 EUR per jaar te laag maakte.

Deze module volgt bewust de vorm van `heffingen/repository.py`: TOML-bestanden
met een tijdsas per tarief, een `geverifieerd`-vlag, en een harde fout bij
ontbrekende data in plaats van een stille 0. Een gasfactuur zonder
vervoerstarief is per definitie te laag; dat mag niet onopgemerkt gebeuren.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Optional

from energie_vlaanderen.utility.constants import D

BESTANDSPATROON = "transport_*.toml"


class TransportTariefError(RuntimeError):
    """Verplichte vervoerstariefdata ontbreekt of is niet eenduidig."""


@dataclass(frozen=True)
class TransportTarief:
    """Eén vervoerstarief voor één klantcategorie vanaf één datum.

    `eur_per_kwh` staat exclusief btw, net als de rest van de masterdata.
    """

    energievorm: str
    klantcategorie: str
    eur_per_kwh: Decimal
    geldig_vanaf: date
    geverifieerd: bool
    bron: str


def _datum(waarde: object, pad: Path) -> date:
    """TOML geeft een kale datum al als `date`; een string mag ook."""
    if isinstance(waarde, datetime):
        return waarde.date()
    if isinstance(waarde, date):
        return waarde
    try:
        return date.fromisoformat(str(waarde))
    except ValueError as exc:
        raise TransportTariefError(
            f"Ongeldige geldig_vanaf {waarde!r} in {pad.name}."
        ) from exc


class TransportTariefRepository:
    def __init__(self, tarieven: tuple[TransportTarief, ...]) -> None:
        self._tarieven = tarieven

    def tarieven(self) -> tuple[TransportTarief, ...]:
        """Publieke accessor (voor de databankimport en de validatie)."""
        return self._tarieven

    @classmethod
    def load(cls, config_dir: Path) -> "TransportTariefRepository":
        """Lees alle `transport_*.toml` uit `config_dir`.

        De energievorm staat in het bestand zelf, dus een nieuwe energievorm
        toevoegen vraagt geen codewijziging.
        """
        tarieven: list[TransportTarief] = []
        bestanden = sorted(config_dir.glob(BESTANDSPATROON))
        if not bestanden:
            raise TransportTariefError(
                f"Geen vervoerstariefbestanden gevonden in {config_dir} "
                f"(patroon {BESTANDSPATROON})."
            )

        for pad in bestanden:
            with pad.open("rb") as fh:
                ruw = tomllib.load(fh)
            energievorm = ruw["energievorm"]
            bestandsbron = ruw.get("bron", "")
            for rij in ruw["tarief"]:
                tarieven.append(
                    TransportTarief(
                        energievorm=energievorm,
                        klantcategorie=rij["klantcategorie"],
                        eur_per_kwh=D(str(rij["eur_per_kwh"])),
                        geldig_vanaf=_datum(rij["geldig_vanaf"], pad),
                        geverifieerd=bool(rij.get("geverifieerd", False)),
                        bron=rij.get("bron") or bestandsbron,
                    )
                )

        return cls(tuple(tarieven))

    def tarief(
        self, energievorm: str, klantcategorie: str, op_datum: date
    ) -> TransportTarief:
        """Het tarief dat op `op_datum` van kracht is.

        Net als bij de accijnzen: het regime met de meest recente
        ingangsdatum die niet in de toekomst ligt. Voor datums vóór het
        oudste regime volgt een fout — met een ouder tarief doorrekenen zou
        een verkeerd bedrag opleveren zonder dat iemand het merkt.
        """
        kandidaten = [
            t for t in self._tarieven
            if t.energievorm == energievorm and t.klantcategorie == klantcategorie
        ]
        if not kandidaten:
            beschikbaar = sorted(
                {
                    f"{t.energievorm}/{t.klantcategorie}"
                    for t in self._tarieven
                }
            )
            raise TransportTariefError(
                f"Geen vervoerstarief voor {energievorm}/{klantcategorie}. "
                f"Beschikbaar: {', '.join(beschikbaar)}."
            )

        van_kracht = [t for t in kandidaten if t.geldig_vanaf <= op_datum]
        if not van_kracht:
            vroegste = min(t.geldig_vanaf for t in kandidaten)
            raise TransportTariefError(
                f"Geen vervoerstarief voor {energievorm}/{klantcategorie} op "
                f"{op_datum.isoformat()}: de masterdata begint pas op "
                f"{vroegste.isoformat()}. Vul config/nettarieven/ aan in "
                "plaats van met een ouder tarief te rekenen."
            )

        return max(van_kracht, key=lambda t: t.geldig_vanaf)

    def eur_per_kwh(
        self, energievorm: str, klantcategorie: str, op_datum: date
    ) -> Decimal:
        return self.tarief(energievorm, klantcategorie, op_datum).eur_per_kwh

    def kost_per_jaar(
        self,
        energievorm: str,
        klantcategorie: str,
        jaarverbruik_kwh: Decimal,
        op_datum: date,
    ) -> Decimal:
        """Vervoerskost voor een jaarverbruik, exclusief btw.

        Het tarief is vlak: over vijf gemeten verbruikspunten van 4.000 tot
        35.000 kWh is er geen knik, ook niet op de 12 MWh-grens waar de
        accijns wél knikt.
        """
        return jaarverbruik_kwh * self.eur_per_kwh(
            energievorm, klantcategorie, op_datum
        )
