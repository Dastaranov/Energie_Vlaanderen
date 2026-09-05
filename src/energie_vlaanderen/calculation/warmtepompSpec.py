"""
Module voor de Warmtepomp-dataclass: een dynamisch thermisch model.
Bevat interne COP-correcties gebaseerd op temperatuurverschillen (bron vs. afgifte)
en bewaakt de fysieke grenzen via __setattr__ guards en ingebouwde geschiedenis.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List
import pandas as pd

# `WarmtepompSpec` woont sinds de masterdata-uitbreiding in `hardware.models`;
# her-geëxporteerd zodat bestaande imports blijven werken. Zie
# `hardware.repository.WarmtepompRepository` voor het laden uit
# `config/hardware/warmtepompen/*.toml`.
from energie_vlaanderen.hardware.models import WarmtepompSpec  # noqa: F401

@dataclass
class Warmtepomp:
    # Vaste fabrieksspecificaties
    merk: str
    model: str
    type_wp: str
    max_thermisch_vermogen_w: float
    nominaal_elektrisch_vermogen_w: float
    cop_nominaal: float
    t_bron_nominaal_c: float
    t_afgifte_nominaal_c: float

    # Dynamische toestandsvelden (standen van de 'teller')
    totaal_thermisch_geleverd_kwh: float = 0.0
    totaal_elektrisch_verbruikt_kwh: float = 0.0
    actuele_belasting_pct: float = 0.0
    actuele_cop: float = 0.0

    # Logboek - wordt out-of-the-box bijgehouden
    geschiedenis: List[Dict[str, Any]] = field(
        default_factory=list, init=False, repr=False, compare=False
    )

    # Constanten voor de grenscontroles
    _KLEM_VELDEN = {"actuele_belasting_pct"}
    _VASTE_VELDEN_ONDERGRENS_NUL = {
        "max_thermisch_vermogen_w", "nominaal_elektrisch_vermogen_w",
        "cop_nominaal", "totaal_thermisch_geleverd_kwh",
        "totaal_elektrisch_verbruikt_kwh"
    }

    def __post_init__(self) -> None:
        """Stelt de beginwaarden in en start het logboek."""
        self.actuele_cop = self.cop_nominaal
        self.geschiedenis.append(self._snapshot(actie="Aangemaakt (Nieuwstaat)"))

    @classmethod
    def from_masterdata(cls, spec: WarmtepompSpec) -> "Warmtepomp":
        """Bouwt een Warmtepomp-instantie vanuit de masterdata specificaties."""
        return cls(
            merk=spec.merk,
            model=spec.model,
            type_wp=spec.type_wp,
            max_thermisch_vermogen_w=spec.max_thermisch_vermogen_w,
            nominaal_elektrisch_vermogen_w=spec.nominaal_elektrisch_vermogen_w,
            cop_nominaal=spec.cop_nominaal,
            t_bron_nominaal_c=spec.t_bron_nominaal_c,
            t_afgifte_nominaal_c=spec.t_afgifte_nominaal_c,
        )

    def __setattr__(self, naam: str, waarde) -> None:
        """Beschermt het model tegen onmogelijke waarden en foutieve invoer."""
        geclipt = False
        if naam in self._KLEM_VELDEN:
            ondergrens = 0.0
            geklemde_waarde = min(100.0, max(ondergrens, float(waarde)))
            geclipt = geklemde_waarde != waarde
            waarde = geklemde_waarde
        elif naam in self._VASTE_VELDEN_ONDERGRENS_NUL and float(waarde) < 0:
            raise ValueError(f"{naam} is fysiek onmogelijk in de min; kreeg {waarde}.")

        geschiedenis_actief = hasattr(self, "geschiedenis")
        oude_waarde = getattr(self, naam) if geschiedenis_actief else None
        
        object.__setattr__(self, naam, waarde)

        # Triggert geen extra logregels voor interne dynamische velden om de DataFrame leesbaar te houden
        interne_velden = ["actuele_cop", "actuele_belasting_pct", "totaal_thermisch_geleverd_kwh", "totaal_elektrisch_verbruikt_kwh"]
        if geschiedenis_actief and oude_waarde != waarde and naam not in interne_velden:
            actie = f"{naam}: {oude_waarde} -> {waarde}"
            if geclipt:
                actie += " (begrensd op limiet)"
            self.geschiedenis.append(self._snapshot(actie=actie, veld=naam))

    def _snapshot(self, actie: str, **extra) -> Dict[str, Any]:
        """Creëert één uniform momentopname-record."""
        return {
            "stap": len(self.geschiedenis),
            "actie": actie,
            "actuele_cop": round(self.actuele_cop, 2),
            "actuele_belasting_pct": round(self.actuele_belasting_pct, 2),
            "totaal_thermisch_kwh": round(self.totaal_thermisch_geleverd_kwh, 4),
            "totaal_elektrisch_kwh": round(self.totaal_elektrisch_verbruikt_kwh, 4),
            **extra,
        }

    def geschiedenis_als_dataframe(self) -> pd.DataFrame:
        """Exporteert de gelogde data netjes naar een DataFrame voor analyses."""
        return pd.DataFrame(self.geschiedenis)

    def _bereken_actuele_cop(self, t_bron_c: float, t_afgifte_c: float) -> float:
        """
        Berekent een veilige inschatting van de actuele COP.
        Hoe groter de kloof die overbrugd moet worden, hoe lager het rendement.
        """
        delta_t_nominaal = self.t_afgifte_nominaal_c - self.t_bron_nominaal_c
        delta_t_actueel = t_afgifte_c - t_bron_c

        # Als er gekoeld in plaats van verwarmd wordt (of geen delta), blijft het efficiënt
        if delta_t_actueel <= 0:
            return self.cop_nominaal
        
        # Lineaire penalty: ca. 2% rendementsverlies voor elke graad afwijking
        verschil = delta_t_actueel - delta_t_nominaal
        correctie_factor = 1.0 - (verschil * 0.02)
        
        berekende_cop = self.cop_nominaal * correctie_factor
        
        # Natuurkundige fail-safe: een warmtepomp kan nooit een slechter rendement 
        # hebben dan een pure elektrische weerstand (COP = 1.0)
        return max(1.0, berekende_cop)

    def verwarm(self, gevraagd_thermisch_vermogen_w: float, t_bron_c: float, t_afgifte_c: float, duur_s: float) -> tuple[float, float]:
        """
        Simuleert de werking over een tijdsinterval en bepaalt het reële elektriciteitsverbruik.
        Retourneert: (opgewekte_thermische_energie_kwh, verbruikte_elektrische_energie_kwh)
        """
        if duur_s < 0:
            raise ValueError("duur_s mag niet negatief zijn.")
        if gevraagd_thermisch_vermogen_w <= 0:
            self.actuele_belasting_pct = 0.0
            return (0.0, 0.0)

        # 1. Begrens het gevraagde vermogen tot de max capaciteit van de machine
        geleverd_vermogen_w = min(gevraagd_thermisch_vermogen_w, self.max_thermisch_vermogen_w)
        self.actuele_belasting_pct = (geleverd_vermogen_w / self.max_thermisch_vermogen_w) * 100.0

        # 2. Update de effectieve efficiëntie gebaseerd op de opgegeven temperaturen
        self.actuele_cop = self._bereken_actuele_cop(t_bron_c, t_afgifte_c)

        # 3. Bereken energieomzetting
        thermisch_kwh = (geleverd_vermogen_w * duur_s) / 3600.0 / 1000.0
        elektrisch_kwh = thermisch_kwh / self.actuele_cop

        # 4. Tellerstanden bijwerken
        self.totaal_thermisch_geleverd_kwh += thermisch_kwh
        self.totaal_elektrisch_verbruikt_kwh += elektrisch_kwh
        
        # 5. Log de actie op een leesbare manier met context
        self.geschiedenis.append(
            self._snapshot(
                actie=f"Verwarmd: Bron {t_bron_c}°C -> Afgifte {t_afgifte_c}°C", 
                thermisch_geleverd=round(thermisch_kwh, 4),
                elektrisch_verbruikt=round(elektrisch_kwh, 4)
            )
        )

        return thermisch_kwh, elektrisch_kwh