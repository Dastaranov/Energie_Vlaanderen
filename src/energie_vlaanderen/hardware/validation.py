"""Structurele controle op de hardware-masterdata (batterijen/omvormers).

Zelfde regels als `heffingen/validation.py`: `geverifieerd = true` zonder
bronvermelding is een fout, `geverifieerd = false` is een waarschuwing (nooit
een fout — elk model start ongeverifieerd totdat iemand het tegen een
datasheet legt). Een dubbele `(merk, model)`-sleutel is al een harde
`HardwareError` bij het laden (zie `repository.py`), geen aparte bevinding.

Wat hier *niet* gebeurt is de inhoudelijke controle — of een cijfer ook
werkelijk klopt met de fabrikantdatasheet. Dat blijft mensenwerk: de
`bron`/`geverifieerd`-velden in elk TOML-bestand documenteren dat.
"""
from __future__ import annotations

from energie_vlaanderen.hardware.repository import BatterijRepository, OmvormerRepository
from energie_vlaanderen.heffingen.validation import Bevinding


def controleer_batterijen(repo: BatterijRepository) -> list[Bevinding]:
    bevindingen: list[Bevinding] = []

    for (merk, model), spec in sorted(repo.batterijen().items()):
        onderwerp = f"batterij/{merk}/{model}"

        if spec.max_capacity_kwh <= 0:
            bevindingen.append(
                Bevinding("fout", onderwerp, f"max_capacity_kwh is niet positief ({spec.max_capacity_kwh}).")
            )
        if not (0.0 < spec.minimum_capacity_pct < 100.0):
            bevindingen.append(
                Bevinding(
                    "fout", onderwerp,
                    f"minimum_capacity_pct moet tussen 0 en 100 liggen (exclusief), kreeg {spec.minimum_capacity_pct}.",
                )
            )
        if not (0.0 < spec.max_depth_of_discharge_pct <= 100.0):
            bevindingen.append(
                Bevinding(
                    "fout", onderwerp,
                    f"max_depth_of_discharge_pct moet tussen 0 en 100 liggen, kreeg {spec.max_depth_of_discharge_pct}.",
                )
            )
        for naam, pct in (
            ("round_trip_efficiency_pct", spec.round_trip_efficiency_pct),
            ("rte_ac_dc_pct", spec.rte_ac_dc_pct),
            ("rte_dc_ac_pct", spec.rte_dc_ac_pct),
            ("rte_storage_pct", spec.rte_storage_pct),
        ):
            if not (0.0 < pct <= 100.0):
                bevindingen.append(
                    Bevinding("fout", onderwerp, f"{naam} moet tussen 0 en 100 liggen, kreeg {pct}.")
                )
        if spec.max_cycle <= 0:
            bevindingen.append(
                Bevinding("fout", onderwerp, f"max_cycle is niet positief ({spec.max_cycle}).")
            )

        # "geverifieerd = true" zonder eigen bronvermelding is de vorm die een
        # ongecontroleerd cijfer geverifieerd laat lijken.
        if spec.geverifieerd and not spec.bron.strip():
            bevindingen.append(
                Bevinding("fout", onderwerp, "Staat op geverifieerd = true maar vermeldt geen bron.")
            )
        elif not spec.geverifieerd:
            bevindingen.append(
                Bevinding(
                    "waarschuwing", onderwerp,
                    "Nog niet tegen een bron gecontroleerd (geverifieerd = false).",
                )
            )

    return bevindingen


def controleer_omvormers(repo: OmvormerRepository) -> list[Bevinding]:
    bevindingen: list[Bevinding] = []

    for (merk, model), spec in sorted(repo.omvormers().items()):
        onderwerp = f"omvormer/{merk}/{model}"

        if spec.nominaal_ac_vermogen_w <= 0:
            bevindingen.append(
                Bevinding("fout", onderwerp, f"nominaal_ac_vermogen_w is niet positief ({spec.nominaal_ac_vermogen_w}).")
            )
        if spec.max_ac_vermogen_w <= 0:
            bevindingen.append(
                Bevinding("fout", onderwerp, f"max_ac_vermogen_w is niet positief ({spec.max_ac_vermogen_w}).")
            )
        if not (0.0 < spec.europees_rendement_pct <= 100.0):
            bevindingen.append(
                Bevinding(
                    "fout", onderwerp,
                    f"europees_rendement_pct moet tussen 0 en 100 liggen, kreeg {spec.europees_rendement_pct}.",
                )
            )

        if spec.geverifieerd and not spec.bron.strip():
            bevindingen.append(
                Bevinding("fout", onderwerp, "Staat op geverifieerd = true maar vermeldt geen bron.")
            )
        elif not spec.geverifieerd:
            bevindingen.append(
                Bevinding(
                    "waarschuwing", onderwerp,
                    "Nog niet tegen een bron gecontroleerd (geverifieerd = false).",
                )
            )

    return bevindingen


def controleer_alles(
    batterij_repo: BatterijRepository, omvormer_repo: OmvormerRepository
) -> list[Bevinding]:
    return [
        *controleer_batterijen(batterij_repo),
        *controleer_omvormers(omvormer_repo),
    ]
