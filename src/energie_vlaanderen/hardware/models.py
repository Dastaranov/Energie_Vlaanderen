"""Nameplate-modellen voor batterijen en omvormers.

Dit zijn technische specificaties (vermogens, capaciteiten, rendementen),
geen geldbedragen — `float`, niet `Decimal` (de Manifest 3.0-regel over
`Decimal` geldt voor financiële waarden, niet voor watt en kWh).

Anders dan bij `heffingen`/`nettarieven` dragen deze specs geen `geldig_vanaf`:
een productmodel verandert niet op een datum zoals een tarief dat doet — een
wijziging is een nieuw modelnummer, dus een nieuw bestand, geen nieuwe rij in
hetzelfde bestand. Wat wél overgenomen wordt, is provenance: `datasheet_versie`,
`datasheet_datum` (publicatiedatum van het brondocument) en `opgehaald_op`
(wanneer het cijfer overgenomen werd) — zuiver informatief, de repository kiest
er nooit een regime mee.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BatterijSpec:
    """Nameplate-specificatie van één batterijmodel.

    Veldnamen dragen de eenheid als suffix (`_w`, `_kwh`, `_pct`, `_s`) zodat
    de TOML zelf al zegt in welke eenheid een getal staat — een verwarring
    tussen kW en W is anders makkelijk gemaakt.
    """

    merk: str
    model: str
    synergrid_id: str  # "" = niet gekend / niet C10/26-gehomologeerd
    power_control_system: str
    p_active_power_w: float
    smax_apparent_power_w: float
    num_phase: int

    max_charge_w: float
    max_discharge_w: float
    max_capacity_kwh: float
    minimum_capacity_pct: float
    standby_power_w: float

    round_trip_efficiency_pct: float
    rte_ac_dc_pct: float
    rte_dc_ac_pct: float
    rte_storage_pct: float
    ramp_up_time_s: float

    max_cycle: int
    max_depth_of_discharge_pct: float
    c_rate: float
    eol_criteria_pct: float

    geverifieerd: bool
    bron: str
    datasheet_versie: str
    datasheet_datum: str
    opgehaald_op: str


@dataclass(frozen=True)
class OmvormerSpec:
    """Nameplate-specificatie van één omvormermodel.

    Bewust minimaal: enkel wat `calculation.omvormer.Omvormer` in de eerste
    iteratie gebruikt (nameplate-identiteit + één vast Europees rendement,
    geen belastingscurve). Zie `docs/research/technische_data_batterijen_en_omvormers.md`
    voor het bredere veldenoverzicht dat hier bewust niet is overgenomen.
    """

    merk: str
    model: str
    product_type: str  # "pv" | "batterij" | "hybride"
    nominaal_ac_vermogen_w: float
    max_ac_vermogen_w: float
    max_dc_vermogen_w: float
    num_phase: int
    europees_rendement_pct: float

    geverifieerd: bool
    bron: str
    datasheet_versie: str
    datasheet_datum: str
    opgehaald_op: str
