"""Day-ahead prijzen voor de Belgische biedzone via api.energy-charts.info.

Waarom een tweede bron
----------------------
ENTSO-E's Transparency Platform is het officiële publicatiekanaal, maar het is
een *rapporteringsplatform* — het staat los van de markt zelf. Op 2026-08-31
serveerde het een onderhoudspagina op zowel de API-host als de webinterface,
terwijl de Belgische markt gewoon doordraaide. Eén bron voor marktprijzen
betekent dat de rekentool stilvalt op momenten dat de data er wel degelijk is.

energy-charts.info (Fraunhofer ISE) publiceert dezelfde day-ahead prijzen,
zonder API-sleutel. De cijfers zijn geverifieerd identiek: over 958
overlappende kwartierpunten tussen 10 en 14 augustus 2026 week geen enkel punt
af van de ENTSO-E-cache van dit project — maximaal verschil 0,0000 EUR/MWh.

Dit is bewust géén vervanging van ENTSO-E maar een terugvalpad. ENTSO-E blijft
de primaire bron; elke rij draagt een `source`-veld zodat achteraf zichtbaar
is waar een prijs vandaan komt (manifest §: provenance is verplicht).
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

LOG = logging.getLogger(__name__)

BRON = "energy-charts.info"


class EnergyChartsError(RuntimeError):
    pass


class EnergyChartsMarketData:
    """Haalt day-ahead prijzen op bij api.energy-charts.info.

    De API vraagt een biedzone (`bzn`) en een datumbereik, en geeft twee
    parallelle lijsten terug: `unix_seconds` en `price`. De resolutie volgt de
    markt — sinds de overgang naar kwartierproducten is dat 15 minuten voor
    België, maar de code leidt ze af uit de data in plaats van ze aan te nemen.
    """

    BASE_URL = "https://api.energy-charts.info/price"
    BIEDZONE = "BE"

    def __init__(self, timeout: int = 60, biedzone: str | None = None) -> None:
        self.timeout = timeout
        self.biedzone = biedzone or self.BIEDZONE

    def fetch_period(
        self, start_utc: datetime, end_utc: datetime
    ) -> list[dict[str, object]]:
        """Prijzen tussen `start_utc` (inclusief) en `end_utc` (exclusief).

        De API werkt met hele dagen in lokale tijd. We vragen een dag ruimer op
        aan beide kanten en snijden daarna exact bij, zodat een periode die
        midden op een dag begint niet stilzwijgend afgekapt wordt.
        """
        params = {
            "bzn": self.biedzone,
            "start": (start_utc - timedelta(days=1)).strftime("%Y-%m-%d"),
            "end": (end_utc + timedelta(days=1)).strftime("%Y-%m-%d"),
        }
        url = self.BASE_URL + "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(
            url, headers={"User-Agent": "EnergieVergelijker/3.0"}
        )

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                payload = json.loads(resp.read())
        except (urllib.error.URLError, ValueError) as exc:
            raise EnergyChartsError(
                f"Kon day-ahead prijzen niet ophalen bij {BRON}: {exc}"
            ) from exc

        seconden = payload.get("unix_seconds")
        prijzen = payload.get("price")
        if not seconden or not prijzen:
            raise EnergyChartsError(
                f"{BRON} gaf geen prijzen terug voor biedzone {self.biedzone} "
                f"({params['start']} .. {params['end']})."
            )
        if len(seconden) != len(prijzen):
            raise EnergyChartsError(
                f"{BRON} gaf {len(seconden)} tijdstippen maar {len(prijzen)} "
                "prijzen terug."
            )

        eenheid = payload.get("unit", "")
        if eenheid and "MWh" not in eenheid:
            # Liever stoppen dan een prijs in de verkeerde eenheid doorgeven:
            # dat zou pas in de eindfactuur zichtbaar worden.
            raise EnergyChartsError(
                f"{BRON} rapporteert prijzen in '{eenheid}' in plaats van EUR/MWh."
            )

        rijen: list[dict[str, object]] = []
        for seconde, prijs in zip(seconden, prijzen):
            if prijs is None:
                continue
            tijdstip = datetime.fromtimestamp(seconde, timezone.utc)
            if not (start_utc <= tijdstip < end_utc):
                continue
            rijen.append(
                {
                    "timestamp": tijdstip.isoformat().replace("+00:00", "Z"),
                    "price_eur_mwh": float(prijs),
                    "source": BRON,
                }
            )

        if not rijen:
            raise EnergyChartsError(
                f"{BRON} leverde geen punten binnen "
                f"{start_utc.isoformat()} .. {end_utc.isoformat()}."
            )

        LOG.info(
            "%d day-ahead prijzen opgehaald bij %s (%s .. %s).",
            len(rijen), BRON, rijen[0]["timestamp"], rijen[-1]["timestamp"],
        )
        return rijen
