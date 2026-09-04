"""Module voor de Omvormer-dataclass: een eenvoudig AC/DC-conversiemodel.

Eerste iteratie, bewust minimaal — zie `docs/research/technische_data_batterijen_en_omvormers.md`
en het implementatieplan: nameplate-identiteit plus één vast Europees
rendement, geen belastingscurve, geen MPPT-modellering.

Deze klasse staat los van `Battery.rte_ac_dc`/`rte_dc_ac`: een `Battery` die
zelf al een geïntegreerd vermogensregelingssysteem heeft (zoals de Marstek
Venus E-reeks — vandaar `power_control_system = "Hybride"` op dat model)
rekent zijn eigen AC/DC-conversieverlies al zelf uit. `Omvormer` is bedoeld
voor een *apart* omvormerproduct (bv. een klassieke PV-stringomvormer, of een
hybride omvormer die niet in dezelfde behuizing als de batterij zit).

Gebruik je `Omvormer.dc_naar_ac`/`ac_naar_dc` én `Battery.laad`/`ontlaad` in
dezelfde simulatielus, dan tel je het conversieverlies dubbel — dat is een
bewust ongeadresseerde beperking van deze eerste iteratie, geen verborgen
bug. Een vervolgstap moet expliciet kiezen welke van de twee het verlies
draagt (bv. door op een `Battery` met een eigen `power_control_system`
`rte_ac_dc = rte_dc_ac = 100.0` te zetten wanneer een aparte `Omvormer` de
conversie voor zijn rekening neemt).
"""
from __future__ import annotations

from dataclasses import dataclass

from energie_vlaanderen.hardware.models import OmvormerSpec


@dataclass
class Omvormer:
    merk: str
    model: str
    product_type: str  # "pv" | "batterij" | "hybride"
    nominaal_ac_vermogen_w: float
    max_ac_vermogen_w: float
    max_dc_vermogen_w: float
    num_phase: int
    europees_rendement_pct: float

    @classmethod
    def from_masterdata(cls, spec: OmvormerSpec) -> "Omvormer":
        """Bouwt een `Omvormer` uit een geladen `OmvormerSpec` (zie
        `hardware.repository.OmvormerRepository`)."""
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

    def dc_naar_ac(self, vermogen_w: float, duur_s: float) -> float:
        """Converteert een aangeboden DC-vermogen (bv. van zonnepanelen of
        een batterij) naar geleverde AC-energie (kWh), begrensd door
        `max_ac_vermogen_w` en verminderd met het Europees rendement.

        :param vermogen_w: Aangeboden DC-vermogen (W). Negatief wordt als 0 behandeld.
        :param duur_s: Duur van het interval (s).
        :return: Geleverde AC-energie (kWh), na begrenzing en rendementsverlies.
        """
        if duur_s < 0:
            raise ValueError("duur_s mag niet negatief zijn.")
        if vermogen_w <= 0:
            return 0.0

        effectief_vermogen_w = min(vermogen_w, self.max_dc_vermogen_w)
        dc_energie_kwh = effectief_vermogen_w * duur_s / 3600.0 / 1000.0
        rendement = self.europees_rendement_pct / 100.0
        ac_energie_kwh = dc_energie_kwh * rendement

        max_ac_energie_kwh = self.max_ac_vermogen_w * duur_s / 3600.0 / 1000.0
        return min(ac_energie_kwh, max_ac_energie_kwh)

    def ac_naar_dc(self, vermogen_w: float, duur_s: float) -> float:
        """Converteert een gevraagd AC-vermogen (bv. om een batterij te laden
        vanaf het net) naar de benodigde DC-energie (kWh), begrensd door
        `max_ac_vermogen_w` en verhoogd met het rendementsverlies.

        :param vermogen_w: Gevraagd AC-vermogen (W). Negatief wordt als 0 behandeld.
        :param duur_s: Duur van het interval (s).
        :return: Geleverde DC-energie (kWh), na begrenzing en rendementsverlies.
        """
        if duur_s < 0:
            raise ValueError("duur_s mag niet negatief zijn.")
        if vermogen_w <= 0:
            return 0.0

        effectief_vermogen_w = min(vermogen_w, self.max_ac_vermogen_w)
        ac_energie_kwh = effectief_vermogen_w * duur_s / 3600.0 / 1000.0
        rendement = self.europees_rendement_pct / 100.0
        dc_energie_kwh = ac_energie_kwh * rendement

        max_dc_energie_kwh = self.max_dc_vermogen_w * duur_s / 3600.0 / 1000.0
        return min(dc_energie_kwh, max_dc_energie_kwh)
