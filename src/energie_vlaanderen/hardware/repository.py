"""Leest handmatig onderhouden batterij-/omvormermasterdata uit
`config/hardware/batterijen/` en `config/hardware/omvormers/`.

Zelfde patroon als `heffingen/repository.py` en `nettarieven/transport.py`:
één bestand per model, een `bron`-veld, een `geverifieerd`-vlag, en een harde
fout in plaats van een stille 0/lege string bij ontbrekende of dubbelzinnige
data. `merk`/`model` staan in het bestand zelf, niet in de bestandsnaam — een
hernoemd of verkeerd gespeld bestand levert dus nooit stilzwijgend een
verkeerde sleutel op.
"""
from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Callable, TypeVar

from energie_vlaanderen.hardware.models import BatterijSpec, OmvormerSpec

BATTERIJEN_PATROON = "*.toml"
OMVORMERS_PATROON = "*.toml"

T = TypeVar("T")


class HardwareError(RuntimeError):
    """Verplichte hardware-masterdata ontbreekt of is niet eenduidig."""


def _bouw_batterijspec(sectie: dict, bestandsbron: str) -> BatterijSpec:
    return BatterijSpec(
        merk=sectie["merk"],
        model=sectie["model"],
        synergrid_id=sectie.get("synergrid_id", ""),
        power_control_system=sectie["power_control_system"],
        p_active_power_w=float(sectie["p_active_power_w"]),
        smax_apparent_power_w=float(sectie["smax_apparent_power_w"]),
        num_phase=int(sectie["num_phase"]),
        max_charge_w=float(sectie["max_charge_w"]),
        max_discharge_w=float(sectie["max_discharge_w"]),
        max_capacity_kwh=float(sectie["max_capacity_kwh"]),
        minimum_capacity_pct=float(sectie["minimum_capacity_pct"]),
        standby_power_w=float(sectie["standby_power_w"]),
        round_trip_efficiency_pct=float(sectie["round_trip_efficiency_pct"]),
        rte_ac_dc_pct=float(sectie["rte_ac_dc_pct"]),
        rte_dc_ac_pct=float(sectie["rte_dc_ac_pct"]),
        rte_storage_pct=float(sectie["rte_storage_pct"]),
        ramp_up_time_s=float(sectie["ramp_up_time_s"]),
        max_cycle=int(sectie["max_cycle"]),
        max_depth_of_discharge_pct=float(sectie["max_depth_of_discharge_pct"]),
        c_rate=float(sectie["c_rate"]),
        eol_criteria_pct=float(sectie["eol_criteria_pct"]),
        geverifieerd=bool(sectie.get("geverifieerd", False)),
        bron=sectie.get("bron") or bestandsbron,
        datasheet_versie=sectie.get("datasheet_versie", ""),
        datasheet_datum=sectie.get("datasheet_datum", ""),
        opgehaald_op=sectie.get("opgehaald_op", ""),
    )


def _bouw_omvormerspec(sectie: dict, bestandsbron: str) -> OmvormerSpec:
    return OmvormerSpec(
        merk=sectie["merk"],
        model=sectie["model"],
        product_type=sectie["product_type"],
        nominaal_ac_vermogen_w=float(sectie["nominaal_ac_vermogen_w"]),
        max_ac_vermogen_w=float(sectie["max_ac_vermogen_w"]),
        max_dc_vermogen_w=float(sectie["max_dc_vermogen_w"]),
        num_phase=int(sectie["num_phase"]),
        europees_rendement_pct=float(sectie["europees_rendement_pct"]),
        geverifieerd=bool(sectie.get("geverifieerd", False)),
        bron=sectie.get("bron") or bestandsbron,
        datasheet_versie=sectie.get("datasheet_versie", ""),
        datasheet_datum=sectie.get("datasheet_datum", ""),
        opgehaald_op=sectie.get("opgehaald_op", ""),
    )


def _laad_specs(
    config_dir: Path,
    patroon: str,
    tomlsectie: str,
    bouwer: Callable[[dict, str], T],
    omschrijving: str,
) -> dict[tuple[str, str], T]:
    """Leest elk `*.toml`-bestand in `config_dir`, bouwt er via `bouwer` één
    spec uit, en sleutelt op `(merk, model)` uit de inhoud van het bestand.

    Een ontbrekend verplicht veld (`KeyError` uit `bouwer`) wordt herverpakt
    met de bestandsnaam erbij, zodat de foutmelding zegt wélk bestand
    onvolledig is — niet enkel welk veld.
    """
    specs: dict[tuple[str, str], T] = {}
    bestanden = sorted(config_dir.glob(patroon)) if config_dir.is_dir() else []
    if not bestanden:
        raise HardwareError(
            f"Geen {omschrijving}bestanden gevonden in {config_dir} "
            f"(patroon {patroon})."
        )

    for pad in bestanden:
        with pad.open("rb") as fh:
            ruw = tomllib.load(fh)
        bestandsbron = ruw.get("bron", "")
        try:
            sectie = ruw[tomlsectie]
        except KeyError as exc:
            raise HardwareError(
                f"{pad.name} mist de sectie [{tomlsectie}]."
            ) from exc
        try:
            spec = bouwer(sectie, bestandsbron)
        except KeyError as exc:
            raise HardwareError(
                f"{pad.name}: ontbrekend verplicht veld {exc} in [{tomlsectie}]."
            ) from exc

        sleutel = (spec.merk, spec.model)
        if sleutel in specs:
            raise HardwareError(
                f"Twee {omschrijving}bestanden claimen merk/model "
                f"'{spec.merk}'/'{spec.model}' (laatste: {pad.name})."
            )
        specs[sleutel] = spec

    return specs


class BatterijRepository:
    def __init__(self, specs: dict[tuple[str, str], BatterijSpec]) -> None:
        self._specs = specs

    def batterijen(self) -> dict[tuple[str, str], BatterijSpec]:
        """Publieke accessor (voor validatie en toekomstige DB-import)."""
        return self._specs

    @classmethod
    def load(cls, config_dir: Path) -> "BatterijRepository":
        specs = _laad_specs(
            config_dir, BATTERIJEN_PATROON, "batterij", _bouw_batterijspec, "batterij"
        )
        return cls(specs)

    def batterij(self, merk: str, model: str) -> BatterijSpec:
        spec = self._specs.get((merk, model))
        if spec is None:
            beschikbaar = sorted(f"{m}/{mo}" for m, mo in self._specs)
            raise HardwareError(
                f"Geen batterijmasterdata voor '{merk}'/'{model}'. "
                f"Beschikbaar: {', '.join(beschikbaar) or '(geen)'}."
            )
        return spec


class OmvormerRepository:
    def __init__(self, specs: dict[tuple[str, str], OmvormerSpec]) -> None:
        self._specs = specs

    def omvormers(self) -> dict[tuple[str, str], OmvormerSpec]:
        """Publieke accessor (voor validatie en toekomstige DB-import)."""
        return self._specs

    @classmethod
    def load(cls, config_dir: Path) -> "OmvormerRepository":
        specs = _laad_specs(
            config_dir, OMVORMERS_PATROON, "omvormer", _bouw_omvormerspec, "omvormer"
        )
        return cls(specs)

    def omvormer(self, merk: str, model: str) -> OmvormerSpec:
        spec = self._specs.get((merk, model))
        if spec is None:
            beschikbaar = sorted(f"{m}/{mo}" for m, mo in self._specs)
            raise HardwareError(
                f"Geen omvormermasterdata voor '{merk}'/'{model}'. "
                f"Beschikbaar: {', '.join(beschikbaar) or '(geen)'}."
            )
        return spec
