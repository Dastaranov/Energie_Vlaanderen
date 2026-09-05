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

from energie_vlaanderen.hardware.repository import (
    BatterijRepository,
    ElektrischeWagenRepository,
    OmvormerRepository,
    WarmtepompRepository,
    ZonnepaneelRepository,
)
from energie_vlaanderen.heffingen.validation import Bevinding


def _geverifieerd_bevinding(onderwerp: str, spec) -> list[Bevinding]:
    """De `geverifieerd`/`bron`-toets die voor elk hardwaretype hetzelfde is.

    "geverifieerd = true" zonder eigen bronvermelding is de vorm die een
    ongecontroleerd cijfer geverifieerd laat lijken, dus dat is een fout.
    "geverifieerd = false" is geen fout maar een waarschuwing: elk model
    start ongeverifieerd totdat iemand het tegen een datasheet legt.
    """
    if spec.geverifieerd and not spec.bron.strip():
        return [Bevinding("fout", onderwerp, "Staat op geverifieerd = true maar vermeldt geen bron.")]
    if not spec.geverifieerd:
        return [Bevinding(
            "waarschuwing", onderwerp,
            "Nog niet tegen een bron gecontroleerd (geverifieerd = false).",
        )]
    return []


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

        bevindingen.extend(_geverifieerd_bevinding(onderwerp, spec))

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

        bevindingen.extend(_geverifieerd_bevinding(onderwerp, spec))

    return bevindingen


def controleer_zonnepanelen(repo: ZonnepaneelRepository) -> list[Bevinding]:
    bevindingen: list[Bevinding] = []

    for (merk, model), spec in sorted(repo.zonnepanelen().items()):
        onderwerp = f"zonnepaneel/{merk}/{model}"

        if spec.piekvermogen_wp <= 0:
            bevindingen.append(
                Bevinding("fout", onderwerp, f"piekvermogen_wp is niet positief ({spec.piekvermogen_wp}).")
            )
        if spec.oppervlakte_m2 <= 0:
            bevindingen.append(
                Bevinding("fout", onderwerp, f"oppervlakte_m2 is niet positief ({spec.oppervlakte_m2}).")
            )
        if not (0.0 <= spec.degradatie_eerste_jaar_pct < 100.0):
            bevindingen.append(
                Bevinding(
                    "fout", onderwerp,
                    f"degradatie_eerste_jaar_pct moet tussen 0 en 100 liggen, kreeg {spec.degradatie_eerste_jaar_pct}.",
                )
            )

        bevindingen.extend(_geverifieerd_bevinding(onderwerp, spec))

    return bevindingen


def controleer_elektrische_wagens(repo: ElektrischeWagenRepository) -> list[Bevinding]:
    bevindingen: list[Bevinding] = []

    for (merk, model), spec in sorted(repo.elektrische_wagens().items()):
        onderwerp = f"elektrische_wagen/{merk}/{model}"

        if spec.batterij_capaciteit_kwh <= 0:
            bevindingen.append(
                Bevinding("fout", onderwerp, f"batterij_capaciteit_kwh is niet positief ({spec.batterij_capaciteit_kwh}).")
            )
        if spec.verbruik_per_100km_kwh <= 0:
            bevindingen.append(
                Bevinding("fout", onderwerp, f"verbruik_per_100km_kwh is niet positief ({spec.verbruik_per_100km_kwh}).")
            )
        if spec.max_laadvermogen_ac_w <= 0 or spec.max_laadvermogen_dc_w <= 0:
            bevindingen.append(
                Bevinding("fout", onderwerp, "max_laadvermogen_ac_w/dc_w moet positief zijn.")
            )
        if spec.onderhoudsinterval_km <= 0:
            bevindingen.append(
                Bevinding("fout", onderwerp, f"onderhoudsinterval_km is niet positief ({spec.onderhoudsinterval_km}).")
            )

        bevindingen.extend(_geverifieerd_bevinding(onderwerp, spec))

    return bevindingen


def controleer_warmtepompen(repo: WarmtepompRepository) -> list[Bevinding]:
    bevindingen: list[Bevinding] = []

    for (merk, model), spec in sorted(repo.warmtepompen().items()):
        onderwerp = f"warmtepomp/{merk}/{model}"

        if spec.max_thermisch_vermogen_w <= 0:
            bevindingen.append(
                Bevinding("fout", onderwerp, f"max_thermisch_vermogen_w is niet positief ({spec.max_thermisch_vermogen_w}).")
            )
        if spec.nominaal_elektrisch_vermogen_w <= 0:
            bevindingen.append(
                Bevinding("fout", onderwerp, f"nominaal_elektrisch_vermogen_w is niet positief ({spec.nominaal_elektrisch_vermogen_w}).")
            )
        # Een COP onder 1,0 zou een warmtepomp een slechter rendement geven dan
        # een pure elektrische weerstand — zie de fail-safe in
        # `Warmtepomp._bereken_actuele_cop()`, die dezelfde ondergrens hanteert.
        if spec.cop_nominaal < 1.0:
            bevindingen.append(
                Bevinding("fout", onderwerp, f"cop_nominaal onder 1,0 is fysisch onmogelijk ({spec.cop_nominaal}).")
            )
        if spec.t_afgifte_nominaal_c <= spec.t_bron_nominaal_c:
            bevindingen.append(
                Bevinding(
                    "fout", onderwerp,
                    "t_afgifte_nominaal_c moet hoger liggen dan t_bron_nominaal_c "
                    f"(kreeg bron={spec.t_bron_nominaal_c}, afgifte={spec.t_afgifte_nominaal_c}).",
                )
            )

        bevindingen.extend(_geverifieerd_bevinding(onderwerp, spec))

    return bevindingen


def controleer_alles(
    batterij_repo: BatterijRepository,
    omvormer_repo: OmvormerRepository,
    *,
    zonnepaneel_repo: ZonnepaneelRepository | None = None,
    elektrische_wagen_repo: ElektrischeWagenRepository | None = None,
    warmtepomp_repo: WarmtepompRepository | None = None,
) -> list[Bevinding]:
    """Verzamelt de bevindingen van alle hardwaretypes.

    De drie nieuwe repository's zijn optioneel (`None` = overgeslagen): een
    oproeper die alleen batterijen/omvormers laadt (zoals
    `gebruiker controleer --hardware` vandaag doet) hoeft niet meteen ook
    zonnepanelen/EV's/warmtepompen te laden om deze functie te kunnen
    aanroepen.
    """
    bevindingen = [
        *controleer_batterijen(batterij_repo),
        *controleer_omvormers(omvormer_repo),
    ]
    if zonnepaneel_repo is not None:
        bevindingen.extend(controleer_zonnepanelen(zonnepaneel_repo))
    if elektrische_wagen_repo is not None:
        bevindingen.extend(controleer_elektrische_wagens(elektrische_wagen_repo))
    if warmtepomp_repo is not None:
        bevindingen.extend(controleer_warmtepompen(warmtepomp_repo))
    return bevindingen
