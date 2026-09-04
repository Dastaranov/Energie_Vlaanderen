"""
Module voor de vernieuwde Omvormer-dataclass: een veilig en zelf-loggend AC/DC-conversiemodel.
Net als de Battery-klasse beschermt deze Omvormer zijn eigen grenzen via __setattr__ en 
houdt het alle acties bij in een Pandas-compatibel logboek.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List
import pandas as pd

from energie_vlaanderen.hardware.models import OmvormerSpec

@dataclass
class Omvormer:
    # Vaste nameplate-specificaties
    merk: str
    model: str
    product_type: str  # "pv" | "batterij" | "hybride"
    nominaal_ac_vermogen_w: float
    max_ac_vermogen_w: float
    max_dc_vermogen_w: float
    num_phase: int
    europees_rendement_pct: float

    # Dynamische toestandsvelden (om de simulatie te kunnen volgen)
    totaal_geleverde_ac_energie_kwh: float = 0.0
    totaal_geleverde_dc_energie_kwh: float = 0.0
    actuele_belasting_pct: float = 0.0

    # Geschiedenis - wordt automatisch bijgehouden zolang het object leeft
    geschiedenis: List[Dict[str, Any]] = field(
        default_factory=list, init=False, repr=False, compare=False
    )

    # Veld-bewaking, vergelijkbaar met het BMS van de batterij
    _KLEM_VELDEN = {"actuele_belasting_pct"}
    _VASTE_VELDEN_ONDERGRENS_NUL = {
        "nominaal_ac_vermogen_w", "max_ac_vermogen_w",
        "max_dc_vermogen_w", "totaal_geleverde_ac_energie_kwh",
        "totaal_geleverde_dc_energie_kwh"
    }
    _VASTE_VELDEN_PERCENTAGE = {"europees_rendement_pct"}
    # Velden waar de fysica door deelt: de belasting is een percentage van het
    # maximum, en zonder maximum bestaat dat percentage niet. Nul werd hier
    # aanvaard omdat het niet negatief is, waarna `dc_naar_ac` afbrak met een
    # ZeroDivisionError — een onbegrijpelijke fout op een invoerprobleem.
    # Weigeren bij het aanmaken is duidelijker dan bij elke deling opnieuw
    # bewaken: een omvormer van nul watt bestaat niet.
    _VASTE_VELDEN_STRIKT_POSITIEF = {
        "nominaal_ac_vermogen_w", "max_ac_vermogen_w", "max_dc_vermogen_w",
    }

    def __post_init__(self) -> None:
        """Legt de nieuwstaat vast als eerste regel van de geschiedenis."""
        self.geschiedenis.append(self._snapshot(actie="Aangemaakt"))

    @classmethod
    def from_masterdata(cls, spec: OmvormerSpec) -> "Omvormer":
        """Bouwt een Omvormer uit een geladen OmvormerSpec."""
        return cls(
            merk=spec.merk,
            model=spec.model,
            product_type=spec.product_type,
            nominaal_ac_vermogen_w=spec.nominaal_ac_vermogen_w,
            max_ac_vermogen_w=spec.max_ac_vermogen_w,
            max_dc_vermogen_w=spec.max_dc_vermogen_w,
            num_phase=spec.num_phase,
            europees_rendement_pct=spec.europees_rendement_pct,
        )

    def __setattr__(self, naam: str, waarde) -> None:
        """
        Bewaakt bij elke toewijzing dat de technische limieten gerespecteerd worden,
        en logt de wijziging in `self.geschiedenis`.
        """
        geclipt = False
        if naam in self._KLEM_VELDEN:
            ondergrens = 0.0
            geklemde_waarde = min(100.0, max(ondergrens, float(waarde)))
            geclipt = geklemde_waarde != waarde
            waarde = geklemde_waarde
        elif naam in self._VASTE_VELDEN_STRIKT_POSITIEF and float(waarde) <= 0:
            raise ValueError(
                f"{naam} moet groter dan nul zijn, kreeg {waarde}. Een omvormer "
                "zonder vermogen bestaat niet, en de belasting is een percentage "
                "van dit maximum."
            )
        elif naam in self._VASTE_VELDEN_ONDERGRENS_NUL and waarde < 0:
            raise ValueError(f"{naam} is een nameplate-specificatie en kan niet negatief zijn, kreeg {waarde}.")
        elif naam in self._VASTE_VELDEN_PERCENTAGE and not (0.0 <= waarde <= 100.0):
            raise ValueError(f"{naam} moet een percentage tussen 0 en 100 zijn, kreeg {waarde}.")

        geschiedenis_actief = naam != "geschiedenis" and hasattr(self, "geschiedenis")
        oude_waarde = getattr(self, naam) if geschiedenis_actief else None
        object.__setattr__(self, naam, waarde)

        if geschiedenis_actief and oude_waarde != waarde:
            actie = f"{naam}: {oude_waarde} -> {waarde}"
            if geclipt:
                actie += " (begrensd op technische limiet)"
            self.geschiedenis.append(
                self._snapshot(actie=actie, veld=naam, van=oude_waarde, naar=waarde)
            )

    def _snapshot(self, actie: str, **extra) -> Dict[str, Any]:
        """Bouwt één regel van de geschiedenis: de kerntoestand plus context."""
        return {
            "stap": len(self.geschiedenis),
            "actie": actie,
            "actuele_belasting_pct": round(self.actuele_belasting_pct, 2),
            "totaal_ac_kwh": round(self.totaal_geleverde_ac_energie_kwh, 4),
            "totaal_dc_kwh": round(self.totaal_geleverde_dc_energie_kwh, 4),
            **extra,
        }

    def geschiedenis_als_dataframe(self) -> pd.DataFrame:
        """Geeft de bijgehouden geschiedenis terug als Pandas DataFrame."""
        return pd.DataFrame(self.geschiedenis)

    def wis_geschiedenis(self) -> None:
        """Leegt de geschiedenis (bv. na het opstarten van een nieuwe simulatierun)."""
        self.geschiedenis.clear()
        self.geschiedenis.append(self._snapshot(actie="Geschiedenis gewist"))

    def dc_naar_ac(self, vermogen_w: float, duur_s: float) -> float:
        """
        Converteert een aangeboden DC-vermogen naar geleverde AC-energie (kWh).
        Begrensd door max_dc_vermogen_w en verminderd met het Europees rendement.
        """
        if duur_s < 0:
            raise ValueError("duur_s mag niet negatief zijn.")
        if vermogen_w <= 0:
            self.actuele_belasting_pct = 0.0
            return 0.0

        # Begrenzen op wat de omvormer fysiek aankan
        effectief_vermogen_w = min(vermogen_w, self.max_dc_vermogen_w)
        self.actuele_belasting_pct = (effectief_vermogen_w / self.max_dc_vermogen_w) * 100.0

        dc_energie_kwh = effectief_vermogen_w * duur_s / 3600.0 / 1000.0
        rendement = self.europees_rendement_pct / 100.0
        ac_energie_kwh = dc_energie_kwh * rendement
        max_ac_energie_kwh = self.max_ac_vermogen_w * duur_s / 3600.0 / 1000.0

        geleverd_kwh = min(ac_energie_kwh, max_ac_energie_kwh)
        
        # Omdat de eigenschap wijzigt, triggert dit automatisch een log in de geschiedenis
        self.totaal_geleverde_ac_energie_kwh += geleverd_kwh
        return geleverd_kwh

    def ac_naar_dc(self, vermogen_w: float, duur_s: float) -> float:
        """
        Converteert een gevraagd AC-vermogen naar geleverde DC-energie (kWh).
        Begrensd door max_ac_vermogen_w en verminderd met het Europees rendement.
        """
        if duur_s < 0:
            raise ValueError("duur_s mag niet negatief zijn.")
        if vermogen_w <= 0:
            self.actuele_belasting_pct = 0.0
            return 0.0

        effectief_vermogen_w = min(vermogen_w, self.max_ac_vermogen_w)
        self.actuele_belasting_pct = (effectief_vermogen_w / self.max_ac_vermogen_w) * 100.0

        ac_energie_kwh = effectief_vermogen_w * duur_s / 3600.0 / 1000.0
        rendement = self.europees_rendement_pct / 100.0
        dc_energie_kwh = ac_energie_kwh * rendement
        max_dc_energie_kwh = self.max_dc_vermogen_w * duur_s / 3600.0 / 1000.0

        geleverd_kwh = min(dc_energie_kwh, max_dc_energie_kwh)
        
        # Omdat de eigenschap wijzigt, triggert dit automatisch een log in de geschiedenis
        self.totaal_geleverde_dc_energie_kwh += geleverd_kwh
        return geleverd_kwh