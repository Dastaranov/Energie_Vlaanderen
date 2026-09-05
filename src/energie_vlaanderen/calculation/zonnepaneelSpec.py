"""
Module voor de uitgebreide Zonnepaneel-dataclass.
Inclusief degradatie over tijd, spanning/stroom karakteristieken (Voc, Vmpp) 
en boma-proof grenscontroles voor betrouwbare simulaties.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List
import pandas as pd

# `ZonnepaneelSpec` woont sinds de masterdata-uitbreiding in
# `hardware.models` (samen met `BatterijSpec`/`OmvormerSpec`) en wordt hier
# enkel her-geëxporteerd, zodat bestaande imports
# (`from energie_vlaanderen.calculation.zonnepaneelSpec import ZonnepaneelSpec`)
# blijven werken. Zie `hardware.repository.ZonnepaneelRepository` voor hoe een
# spec nu uit `config/hardware/zonnepanelen/*.toml` geladen wordt.
from energie_vlaanderen.hardware.models import ZonnepaneelSpec  # noqa: F401

@dataclass
class Zonnepaneel:
    # Vaste datasheet specificaties (STC - Standard Test Conditions)
    merk: str
    model: str
    piekvermogen_wp: float
    v_oc_volt: float
    i_sc_ampere: float
    v_mpp_volt: float
    i_mpp_ampere: float
    temperatuur_coeff_pmax_pct_c: float
    temperatuur_coeff_voc_pct_c: float
    degradatie_eerste_jaar_pct: float
    degradatie_per_jaar_pct: float
    oppervlakte_m2: float
    
    # Dynamische toestandsvelden
    leeftijd_jaren: float = 0.0
    actueel_vermogen_w: float = 0.0
    actuele_spanning_v: float = 0.0
    
    # Automatisch logboek
    geschiedenis: List[Dict[str, Any]] = field(
        default_factory=list, init=False, repr=False, compare=False
    )

    # Boma-proof grenzen
    _KLEM_VELDEN = {"actueel_vermogen_w", "actuele_spanning_v"}
    _VASTE_VELDEN_ONDERGRENS_NUL = {
        "piekvermogen_wp", "v_oc_volt", "i_sc_ampere", 
        "v_mpp_volt", "i_mpp_ampere", "leeftijd_jaren"
    }

    def __post_init__(self) -> None:
        """Zet de beginstand en start het logboek."""
        self.actuele_spanning_v = self.v_oc_volt
        self.geschiedenis.append(self._snapshot(actie="Paneel Aangemaakt (Nieuwstaat)"))

    @classmethod
    def from_masterdata(cls, spec: ZonnepaneelSpec, start_leeftijd_jaren: float = 0.0) -> "Zonnepaneel":
        """Bouwt een Zonnepaneel vanuit de masterdata specificaties."""
        return cls(
            merk=spec.merk,
            model=spec.model,
            piekvermogen_wp=spec.piekvermogen_wp,
            v_oc_volt=spec.v_oc_volt,
            i_sc_ampere=spec.i_sc_ampere,
            v_mpp_volt=spec.v_mpp_volt,
            i_mpp_ampere=spec.i_mpp_ampere,
            temperatuur_coeff_pmax_pct_c=spec.temperatuur_coeff_pmax_pct_c,
            temperatuur_coeff_voc_pct_c=spec.temperatuur_coeff_voc_pct_c,
            degradatie_eerste_jaar_pct=spec.degradatie_eerste_jaar_pct,
            degradatie_per_jaar_pct=spec.degradatie_per_jaar_pct,
            oppervlakte_m2=spec.oppervlakte_m2,
            leeftijd_jaren=start_leeftijd_jaren
        )

    def __setattr__(self, naam: str, waarde) -> None:
        """Beschermt het model tegen onmogelijke waarden en foutieve invoer."""
        geclipt = False
        if naam in self._KLEM_VELDEN:
            # We laten cloud-edge effecten toe (tot 150% van Pmax) maar geen negatieve energie
            maximale_waarde = self.piekvermogen_wp * 1.5 if naam == "actueel_vermogen_w" else self.v_oc_volt * 1.5
            geklemde_waarde = min(maximale_waarde, max(0.0, float(waarde))) 
            geclipt = geklemde_waarde != waarde
            waarde = geklemde_waarde
        elif naam in self._VASTE_VELDEN_ONDERGRENS_NUL and float(waarde) < 0:
            raise ValueError(f"{naam} is fysiek onmogelijk in de min; kreeg {waarde}.")

        geschiedenis_actief = hasattr(self, "geschiedenis")
        oude_waarde = getattr(self, naam) if geschiedenis_actief else None
        
        object.__setattr__(self, naam, waarde)

        interne_velden = ["actueel_vermogen_w", "actuele_spanning_v"]
        if geschiedenis_actief and oude_waarde != waarde and naam not in interne_velden:
            actie = f"{naam}: {oude_waarde} -> {waarde}"
            if geclipt:
                actie += " (begrensd op fysieke limiet)"
            self.geschiedenis.append(self._snapshot(actie=actie, veld=naam))

    def _snapshot(self, actie: str, **extra) -> Dict[str, Any]:
        """Creëert één uniform momentopname-record."""
        return {
            "stap": len(self.geschiedenis),
            "actie": actie,
            "Leeftijd (jaren)": round(self.leeftijd_jaren, 1),
            "Spanning (V)": round(self.actuele_spanning_v, 2),
            "Vermogen (W)": round(self.actueel_vermogen_w, 2),
            **extra,
        }

    def geschiedenis_als_dataframe(self) -> pd.DataFrame:
        """Exporteert de gelogde data naar een DataFrame."""
        return pd.DataFrame(self.geschiedenis)

    def _bereken_degradatie_factor(self) -> float:
        """Berekent hoeveel rendement het paneel nog over heeft (SOH)."""
        if self.leeftijd_jaren <= 0:
            return 1.0
        
        verlies = self.degradatie_eerste_jaar_pct
        if self.leeftijd_jaren > 1.0:
            verlies += (self.leeftijd_jaren - 1.0) * self.degradatie_per_jaar_pct
            
        actuele_soh = max(0.0, 100.0 - verlies) / 100.0
        return actuele_soh

    def verouder(self, extra_jaren: float) -> None:
        """Voegt levensjaren toe aan het paneel (beïnvloedt rendement)."""
        if extra_jaren < 0:
            raise ValueError("Een zonnepaneel kan niet jonger worden.")
        self.leeftijd_jaren += extra_jaren
        gezondheid_pct = self._bereken_degradatie_factor() * 100.0
        self.geschiedenis.append(
            self._snapshot(actie=f"Verouderd met {extra_jaren} jaar. Actuele SoH: {gezondheid_pct:.1f}%")
        )

    def genereer_dc_vermogen(self, instraling_w_m2: float, t_cel_c: float) -> float:
        """
        Berekent het actuele DC-vermogen (Watt) en de werkspanning (Volt).
        Houdt rekening met instraling, temperatuur en degradatie door ouderdom.
        """
        if instraling_w_m2 <= 0:
            self.actueel_vermogen_w = 0.0
            self.actuele_spanning_v = self.v_oc_volt # Keert terug naar nullastspanning
            return 0.0

        delta_t = t_cel_c - 25.0

        # 1. Spanning berekenen (Stijgt bij kou, daalt bij hitte)
        # Gebruikt voor inverter overvoltage berekeningen
        correctie_voc = 1.0 + ((self.temperatuur_coeff_voc_pct_c / 100.0) * delta_t)
        self.actuele_spanning_v = self.v_mpp_volt * correctie_voc

        # 2. Vermogen berekenen (Daalt bij hitte)
        correctie_pmax = 1.0 + ((self.temperatuur_coeff_pmax_pct_c / 100.0) * delta_t)
        
        # 3. Degradatie door ouderdom toepassen
        gezondheid_factor = self._bereken_degradatie_factor()

        # Bruto vermogen berekenen
        self.actueel_vermogen_w = self.piekvermogen_wp * (instraling_w_m2 / 1000.0) * correctie_pmax * gezondheid_factor
        
        return self.actueel_vermogen_w