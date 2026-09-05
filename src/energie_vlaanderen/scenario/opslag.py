"""Een `ScenarioResultaat` wegschrijven als JSON of YAML.

Bewust **geen** `dataclasses.asdict()` op de fysieke assetobjecten
(`calculation.batterySpec.Battery` e.a.): die dragen een `geschiedenis`-log
(`field(init=False, ...)`) dat `asdict()` toch meeneemt, en dat hoort niet in
een schoon scenarioresultaat thuis. In plaats daarvan wordt het dict-veld voor
veld opgebouwd, naar het patroon dat `cli/gebruikers.py`'s
`run_gebruiker_bereken` al hanteert voor zijn `--json`-uitvoer: `Decimal` via
`money()` naar tekst, datums via `.isoformat()`, enums via `str()`.

De uitvoer is bewust een plat dict en geen `Berekening`/`Cost`-object: het doel
is dat de data later herbruikt kan worden (een webinterface, een los script),
niet dat ze terug een identieke Python-object wordt. `laad()` geeft dan ook een
dict terug, geen gereconstrueerd `ScenarioResultaat`.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from energie_vlaanderen.gebruikers.berekening import Berekening
from energie_vlaanderen.scenario.basis import ScenarioResultaat
from energie_vlaanderen.utility.normalizer import money


def _berekening_naar_dict(berekening: Berekening) -> dict[str, Any]:
    return {
        "van": berekening.van.isoformat(),
        "tot": berekening.tot.isoformat(),
        "exactheidsklasse": str(berekening.exactheidsklasse),
        "totalen": {k: str(money(v)) for k, v in berekening.totalen.items()},
        "regels": [
            {
                "van": regel.periode.van.isoformat(),
                "tot": regel.periode.tot.isoformat(),
                "dagen": regel.periode.dagen,
                "leverancier": regel.leverancier,
                "product": regel.product_naam,
                "redenen": list(regel.periode.redenen),
                "exactheidsklasse": str(regel.exactheidsklasse),
                "supplier_eur": str(money(regel.kost.supplier)),
                "grid_eur": str(money(regel.kost.grid)),
                "levies_eur": str(money(regel.kost.levies)),
                "injection_credit_eur": str(money(regel.kost.injection_credit)),
                "vat_eur": str(money(regel.kost.vat)),
                "totaal_eur": str(money(regel.kost.total)),
            }
            for regel in berekening.regels
        ],
        "aannames": [_aanname_naar_dict(a) for a in berekening.aannames],
        "warnings": list(berekening.warnings),
    }


def _aanname_naar_dict(aanname) -> dict[str, Any]:
    return {
        "veld": aanname.veld,
        "waarde": str(aanname.waarde) if aanname.waarde is not None else None,
        "bron": aanname.bron,
        "geverifieerd": aanname.geverifieerd,
    }


def naar_dict(resultaat: ScenarioResultaat) -> dict[str, Any]:
    """Het volledige scenarioresultaat als plat, JSON/YAML-vriendelijk dict."""
    return {
        "naam": resultaat.naam,
        "omschrijving": resultaat.omschrijving,
        "exactheidsklasse": str(resultaat.exactheidsklasse),
        "aangemaakt_op": resultaat.aangemaakt_op.isoformat(),
        "verschil_eur": {k: str(money(v)) for k, v in resultaat.verschil_eur.items()},
        "basislijn": {
            str(energie_type): _berekening_naar_dict(b)
            for energie_type, b in resultaat.basislijn.items()
        },
        "scenario": {
            str(energie_type): _berekening_naar_dict(b)
            for energie_type, b in resultaat.scenario.items()
        },
        "aannames": [_aanname_naar_dict(a) for a in resultaat.aannames],
        "warnings": list(resultaat.warnings),
    }


def sla_op(
    resultaat: ScenarioResultaat, pad: Path, *, formaat: Literal["json", "yaml"] = "json",
) -> Path:
    """Schrijft `resultaat` naar `pad`, in het gevraagde formaat.

    `pad`'s ouder-map wordt aangemaakt indien nodig — scenario's landen onder
    `data/simulaties/`, dat (zoals `data/referentie/`) niet vooraf hoeft te
    bestaan.
    """
    pad = Path(pad)
    pad.parent.mkdir(parents=True, exist_ok=True)
    inhoud = naar_dict(resultaat)

    if formaat == "json":
        pad.write_text(json.dumps(inhoud, ensure_ascii=False, indent=2), encoding="utf-8")
    elif formaat == "yaml":
        import yaml  # lokale import: enkel nodig wanneer YAML gevraagd wordt

        pad.write_text(
            yaml.safe_dump(inhoud, allow_unicode=True, sort_keys=False), encoding="utf-8",
        )
    else:
        raise ValueError(f"Onbekend formaat {formaat!r}; gebruik 'json' of 'yaml'.")
    return pad


def laad(pad: Path) -> dict[str, Any]:
    """Leest een eerder opgeslagen scenarioresultaat terug als plat dict.

    Geen objectreconstructie — zie de moduledocstring: het doel is hergebruik
    van de data, niet een identieke Python-round-trip.
    """
    pad = Path(pad)
    tekst = pad.read_text(encoding="utf-8")
    if pad.suffix.lower() in (".yaml", ".yml"):
        import yaml

        return yaml.safe_load(tekst)
    return json.loads(tekst)
