"""
Module voor de ElektrischeWagen-dataclass: een dynamisch model voor een EV.
Bevat grenscontroles voor kilometerstanden, slim laden (AC/DC) en een 
automatisch waarschuwingssysteem voor onderhoud, netjes gelogd in de geschiedenis.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List
import pandas as pd

# `ElektrischeWagenSpec` woont sinds de masterdata-uitbreiding in
# `hardware.models`; her-geëxporteerd zodat bestaande imports blijven werken.
# Zie `hardware.repository.ElektrischeWagenRepository` voor het laden uit
# `config/hardware/elektrische_wagens/*.toml`.
from energie_vlaanderen.hardware.models import ElektrischeWagenSpec  # noqa: F401

@dataclass
class ElektrischeWagen:
    # Vaste fabrieksspecificaties
    merk: str
    model: str
    batterij_capaciteit_kwh: float
    verbruik_per_100km_kwh: float
    max_laadvermogen_ac_w: float
    max_laadvermogen_dc_w: float
    onderhoudsinterval_km: float

    # Dynamische toestandsvelden (tellerstanden)
    state_of_charge_pct: float = 100.0
    kilometerstand_km: float = 0.0
    laatste_onderhoud_km: float = 0.0
    onderhoud_nodig: bool = False

    # Logboek - wordt volautomatisch bijgehouden
    geschiedenis: List[Dict[str, Any]] = field(
        default_factory=list, init=False, repr=False, compare=False
    )

    # Constanten voor grenscontroles (Boma-proof guards)
    _KLEM_VELDEN = {"state_of_charge_pct"}
    _VASTE_VELDEN_ONDERGRENS_NUL = {
        "batterij_capaciteit_kwh", "verbruik_per_100km_kwh",
        "max_laadvermogen_ac_w", "max_laadvermogen_dc_w",
        "onderhoudsinterval_km", "kilometerstand_km",
        "laatste_onderhoud_km"
    }

    def __post_init__(self) -> None:
        """Stelt de beginwaarden in en start het logboek."""
        self.geschiedenis.append(self._snapshot(actie="Aangemaakt (Nieuw uit de garage)"))

    @classmethod
    def from_masterdata(cls, spec: ElektrischeWagenSpec, huidige_km_stand: float = 0.0) -> "ElektrischeWagen":
        """Bouwt een wagen vanuit de masterdata specificaties."""
        return cls(
            merk=spec.merk,
            model=spec.model,
            batterij_capaciteit_kwh=spec.batterij_capaciteit_kwh,
            verbruik_per_100km_kwh=spec.verbruik_per_100km_kwh,
            max_laadvermogen_ac_w=spec.max_laadvermogen_ac_w,
            max_laadvermogen_dc_w=spec.max_laadvermogen_dc_w,
            onderhoudsinterval_km=spec.onderhoudsinterval_km,
            kilometerstand_km=huidige_km_stand,
            laatste_onderhoud_km=huidige_km_stand
        )

    def __setattr__(self, naam: str, waarde) -> None:
        """Bewaakt de fysieke grenzen en logt externe wijzigingen."""
        geclipt = False
        if naam in self._KLEM_VELDEN:
            geklemde_waarde = min(100.0, max(0.0, float(waarde)))
            geclipt = geklemde_waarde != waarde
            waarde = geklemde_waarde
        elif naam in self._VASTE_VELDEN_ONDERGRENS_NUL and float(waarde) < 0:
            raise ValueError(f"{naam} kan onmogelijk negatief zijn; kreeg {waarde}.")

        geschiedenis_actief = hasattr(self, "geschiedenis")
        oude_waarde = getattr(self, naam) if geschiedenis_actief else None
        
        # Guard: Voorkom het terugdraaien van de kilometerteller
        if naam == "kilometerstand_km" and oude_waarde is not None and waarde < oude_waarde:
            raise ValueError("Fraude-beveiliging: Kilometerteller terugdraaien is niet toegestaan!")

        object.__setattr__(self, naam, waarde)

        # Triggert geen logregel bij interne velden, die nemen we mee in de 'rijd' en 'laad' acties
        interne_velden = ["onderhoud_nodig", "kilometerstand_km"] 
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
            "SoC (%)": round(self.state_of_charge_pct, 2),
            "Kilometerstand": round(self.kilometerstand_km, 1),
            "Onderhoud Nodig": self.onderhoud_nodig,
            **extra,
        }

    def geschiedenis_als_dataframe(self) -> pd.DataFrame:
        """Exporteert de geschiedenis naar Pandas."""
        return pd.DataFrame(self.geschiedenis)

    def laad(self, vermogen_w: float, duur_s: float, is_dc_snelladen: bool = False) -> float:
        """
        Laadt de batterij op en houdt rekening met de maximale ladercapaciteit (AC of DC).
        Retourneert de werkelijk opgeslagen kWh.
        """
        if duur_s < 0:
            raise ValueError("duur_s mag niet negatief zijn.")
        if vermogen_w <= 0:
            return 0.0

        max_w = self.max_laadvermogen_dc_w if is_dc_snelladen else self.max_laadvermogen_ac_w
        effectief_vermogen_w = min(vermogen_w, max_w)
        
        aangeboden_energie_kwh = (effectief_vermogen_w * duur_s) / 3600.0 / 1000.0
        huidige_energie_kwh = self.batterij_capaciteit_kwh * (self.state_of_charge_pct / 100.0)
        beschikbare_ruimte_kwh = max(0.0, self.batterij_capaciteit_kwh - huidige_energie_kwh)

        werkelijk_opgeslagen_kwh = min(aangeboden_energie_kwh, beschikbare_ruimte_kwh)
        
        if self.batterij_capaciteit_kwh > 0:
            self.state_of_charge_pct += (werkelijk_opgeslagen_kwh / self.batterij_capaciteit_kwh) * 100.0

        self.geschiedenis.append(
            self._snapshot(actie=f"Geladen ({'DC' if is_dc_snelladen else 'AC'}) met {werkelijk_opgeslagen_kwh:.2f} kWh")
        )
        return werkelijk_opgeslagen_kwh

    def _controleer_onderhoud(self) -> None:
        """Checkt achter de schermen of de auto binnenkort naar de garage moet."""
        gereden_sinds_onderhoud = self.kilometerstand_km - self.laatste_onderhoud_km
        if gereden_sinds_onderhoud >= self.onderhoudsinterval_km:
            if not self.onderhoud_nodig:
                self.onderhoud_nodig = True
                self.geschiedenis.append(self._snapshot(actie="WAARSCHUWING: Onderhoudsinterval bereikt!"))

    def voer_onderhoud_uit(self) -> None:
        """Reset de servicestatus als de wagen uit de garage komt."""
        self.laatste_onderhoud_km = self.kilometerstand_km
        self.onderhoud_nodig = False
        self.geschiedenis.append(self._snapshot(actie="Onderhoud uitgevoerd in garage. Teller gereset."))

    def rijd(self, gevraagde_afstand_km: float) -> float:
        """
        Simuleert een rit. Berekent het verbruik en past de batterij en kilometerteller aan.
        Retourneert de effectief gereden kilometers (als de batterij leeg is, haal je de eindstreep niet).
        """
        if gevraagde_afstand_km <= 0:
            return 0.0

        huidige_energie_kwh = self.batterij_capaciteit_kwh * (self.state_of_charge_pct / 100.0)
        verbruik_per_km_kwh = self.verbruik_per_100km_kwh / 100.0
        
        max_haalbare_afstand_km = huidige_energie_kwh / verbruik_per_km_kwh if verbruik_per_km_kwh > 0 else 0.0
        werkelijk_gereden_km = min(gevraagde_afstand_km, max_haalbare_afstand_km)
        verbruikte_energie_kwh = werkelijk_gereden_km * verbruik_per_km_kwh

        # SoC updaten via het object om interne logging te triggeren indien nodig
        if self.batterij_capaciteit_kwh > 0:
            self.state_of_charge_pct -= (verbruikte_energie_kwh / self.batterij_capaciteit_kwh) * 100.0

        # Kilometerteller updaten via de master setter (zonder dat _setattr er een lege log van maakt)
        nieuwe_km = self.kilometerstand_km + werkelijk_gereden_km
        object.__setattr__(self, "kilometerstand_km", nieuwe_km)

        status_bericht = f"Rit van {werkelijk_gereden_km:.1f} km voltooid."
        if werkelijk_gereden_km < gevraagde_afstand_km:
            status_bericht = f"STRANDING: Kon maar {werkelijk_gereden_km:.1f} km van de {gevraagde_afstand_km} km rijden. Batterij leeg!"

        self.geschiedenis.append(
            self._snapshot(actie=status_bericht, verbruikt_kwh=round(verbruikte_energie_kwh, 2))
        )

        self._controleer_onderhoud()

        return werkelijk_gereden_km