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
class ZonnepaneelSpec:
    """Nameplate-specificatie van één zonnepaneelmodel.

    Verhuisd hierheen uit `calculation.zonnepaneelSpec` (dat het nu
    her-exporteert) om zonnepanelen dezelfde masterdata-discipline te geven
    als batterijen: een TOML-bestand per model onder
    `config/hardware/zonnepanelen/`, geladen via `ZonnepaneelRepository`, in
    plaats van een spec-dataclass zonder bron die enkel als Python-object kon
    bestaan.

    Anders dan `BatterijSpec`/`OmvormerSpec` dragen de provenance-velden hier
    een standaardwaarde: deze klasse bestond al (met deze exacte velden) vóór
    de masterdata-laag erbij kwam, en bestaande constructie-aanroepen zonder
    provenance (zie `tests/test_zonnepaneel.py`) moeten blijven werken.
    """

    merk: str
    model: str
    piekvermogen_wp: float
    v_oc_volt: float  # Open-circuit spanning (max voltage, onbelast)
    i_sc_ampere: float  # Kortsluitstroom
    v_mpp_volt: float  # Spanning op maximaal vermogen (belast)
    i_mpp_ampere: float  # Stroom op maximaal vermogen (belast)
    temperatuur_coeff_pmax_pct_c: float  # Verlies in Wp per graad boven 25°C
    temperatuur_coeff_voc_pct_c: float   # Stijging/daling in spanning per graad
    degradatie_eerste_jaar_pct: float = 2.0  # Standaard initiële degradatie
    degradatie_per_jaar_pct: float = 0.5     # Standaard lineaire degradatie
    oppervlakte_m2: float = 1.95

    geverifieerd: bool = False
    bron: str = ""
    datasheet_versie: str = ""
    datasheet_datum: str = ""
    opgehaald_op: str = ""


@dataclass(frozen=True)
class ElektrischeWagenSpec:
    """Nameplate-specificatie van één EV-model.

    Zie `ZonnepaneelSpec` hierboven voor de reden waarom de provenance-velden
    hier, anders dan bij `BatterijSpec`, een standaardwaarde dragen.
    """

    merk: str
    model: str
    batterij_capaciteit_kwh: float
    verbruik_per_100km_kwh: float
    max_laadvermogen_ac_w: float
    max_laadvermogen_dc_w: float
    onderhoudsinterval_km: float

    geverifieerd: bool = False
    bron: str = ""
    datasheet_versie: str = ""
    datasheet_datum: str = ""
    opgehaald_op: str = ""


@dataclass(frozen=True)
class WarmtepompSpec:
    """Nameplate-specificatie van één warmtepompmodel.

    `t_bron_nominaal_c`/`t_afgifte_nominaal_c` leggen vast bij welke
    testcondities `cop_nominaal` gemeten is (vaak A7/W35 voor lucht-water,
    volgens EN14511) — zonder die twee is een COP-getal op zich niet te
    interpreteren. Zie `ZonnepaneelSpec` hierboven voor de reden waarom de
    provenance-velden hier een standaardwaarde dragen.
    """

    merk: str
    model: str
    type_wp: str  # bv. "lucht-water", "geothermisch"
    max_thermisch_vermogen_w: float
    nominaal_elektrisch_vermogen_w: float
    cop_nominaal: float
    t_bron_nominaal_c: float = 7.0
    t_afgifte_nominaal_c: float = 35.0

    geverifieerd: bool = False
    bron: str = ""
    datasheet_versie: str = ""
    datasheet_datum: str = ""
    opgehaald_op: str = ""


@dataclass(frozen=True)
class OmvormerSpec:
    """Nameplate-specificatie van één omvormermodel.

    Bewust minimaal: enkel wat `calculation.omvormerSpec.Omvormer` in de eerste
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
