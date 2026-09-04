from dataclasses import dataclass, field
from typing import Any, Dict, List, Union

import numpy as np
import pandas as pd

from energie_vlaanderen.hardware.models import BatterijSpec

"""
Module voor het definiëren van de Battery-dataclass en gerelateerde berekeningen.
"""

@dataclass
class Battery:

    # Algemene informatie - synergid
    # Informatie uit de C10/26 lijst van gehomologeerde decentrale productie-eenheden (DPE)
    synergrid_id: str                       # Synergrid ID van de DPE, uniek per DPE
    merknaam: str                           # Naam van de fabrikant
    productnaam: str                        # Naam van het product
    power_control_system: str               # Type van het vermogensregelingssysteem
    P_active_power: float                   # Actief vermogen van de batterij
    Smax_apparent_power: float              # Maximale schijnbare vermogen van de batterij
    num_phase: int                          # Aantal fasen van de batterij (bijv. 1, 3)

    # Technische informatie
    # Nodig voor het uitvoeren van berekeningen en simulaties van de batterij
    max_charge_w: float                     # Maximale laadvermogen van de batterij (kW)
    max_discharge_w: float                  # Maximale ontlaadvermogen van de batterij (kW)
    
    max_capacity: float                     # Capaciteit van de batterij (kWh)
    minimum_capacity: float                 # Minimale capaciteit van de batterij, uitgedrukt in percentage van de totale capaciteit (%)

    standby_power_w: float                  # Vermogen dat de batterij verbruikt in standby-modus (kW)

    """
    Round-trip efficiency (RTE) is een maat voor het energieverlies dat optreedt tijdens het opladen en ontladen van een batterij.
    RTE = (Energie teruggewonnen / Energie opgeslagen) * 100%
    Een hogere RTE betekent dat de batterij efficiënter is, terwijl een lagere RTE aangeeft dat er meer energie verloren gaat tijdens het proces.
    RTE kan variëren afhankelijk van het type batterij, de laad- en ontlaadsnelheid, de temperatuur en andere operationele omstandigheden.
    """
    round_trip_efficiency: float            # Round-trip efficiency van de batterij (%)
    rte_ac_dc: float                        # Round-trip efficiency van de batterij voor AC-DC conversie (%)
    rte_dc_ac: float                        # Round-trip efficiency van de batterij voor DC-AC conversie (%)
    rte_storage: float                      # Round-trip efficiency van de batterij voor opslag (%)

    ramp_up_time: float                     # Tijd die nodig is om van 0% naar 100% vermogen te gaan (s)

    """
    Eén cyclus staat gelijk aan het verbruiken van 100% van de nominale capaciteit. Dit hoeft niet in één opeenvolgende actie te gebeuren; het is cumulatief.
    Volledige cyclus (100% Depth of Discharge): Een batterij ontladen van 100% naar 0% en weer opladen naar 100% = 1 cyclus.

    Gedeeltelijke cyclus (Partial cycle):

        Dag 1: Batterij ontladen van 100% naar 50% en weer opladen (+0,5 cyclus).
        Dag 2: Batterij ontladen van 100% naar 50% en weer opladen (+0,5 cyclus).

    Totaal: 2 dagen van 50% ontlading = 1 volledige cyclus.
    """
    max_cycle: int                          # Maximale aantal laad-/ontlaadcycli van de batterij
    max_depth_of_discharge: float           # Maximaal toegelaten diepte van ontlading van de batterij opgelegd door de fabrikant (%)
    state_of_charge: float                  # Huidige staat van lading van de batterij (0% = leeg, 100% = vol)(%)
    state_of_health: float                  # Huidige staat van gezondheid van de batterij tov de nieuwwaarde(%)
    c_rate: float                           # C-rate van de batterij (1C = volledig opladen of ontladen in 1 uur)
    eol_criteria: float                     # End-of-life criteria van de batterij (%) - meestal 80% van de oorspronkelijke capaciteit

    # Geschiedenis - géén constructorargument, wordt automatisch bijgehouden
    # zolang het object in het geheugen leeft (zie __setattr__ hieronder).
    geschiedenis: List[Dict[str, Any]] = field(
        default_factory=list, init=False, repr=False, compare=False
    )

    # Dynamische toestandsvelden: een tijdelijke over-/onderschrijding tijdens
    # een berekening wordt stil teruggebracht binnen de fysieke grens (zoals
    # een BMS dat ook zou doen) in plaats van een fout te geven.
    _KLEM_VELDEN = {"state_of_charge", "state_of_health"}

    # Vaste nameplate-specificaties: een ongeldige waarde hier is een fout in
    # de configuratie, geen simulatie-overshoot, en wordt geweigerd.
    _VASTE_VELDEN_ONDERGRENS_NUL = {"max_capacity", "max_charge_w", "max_discharge_w", "standby_power_w"}
    # `max_cycle` staat in de noemer van het cyclusverlies: het verlies per
    # cyclus is het bereik tot de EOL-drempel gedeeld door het aantal cycli.
    # Bij nul brak dat af met een ZeroDivisionError — dezelfde fout als in
    # `omvormerSpec`, en om dezelfde reden hier bij de bron geweigerd: een
    # batterij die nul cycli meegaat, is geen batterij.
    _VASTE_VELDEN_STRIKT_POSITIEF = {"max_cycle"}
    _VASTE_VELDEN_PERCENTAGE = {"minimum_capacity", "max_depth_of_discharge"}

    def __post_init__(self) -> None:
        """Legt de nieuwstaat vast als eerste regel van de geschiedenis."""
        self.geschiedenis.append(self._snapshot(actie="Aangemaakt"))

    @classmethod
    def from_masterdata(
        cls,
        spec: BatterijSpec,
        *,
        state_of_charge: float = 100.0,
        state_of_health: float = 100.0,
    ) -> "Battery":
        """Bouwt een `Battery` uit een geladen `BatterijSpec` (zie
        `hardware.repository.BatterijRepository`) in plaats van de
        nameplate-kwargs rechtstreeks in Python te hardcoden.

        `state_of_charge`/`state_of_health` horen niet in een nameplate-spec
        thuis — dat is de runtime-toestand van één concreet exemplaar, geen
        vaste fabrieksspecificatie — en blijven daarom expliciete
        keyword-argumenten met een nieuwstaat-default (100%/100%).
        """
        return cls(
            synergrid_id=spec.synergrid_id,
            merknaam=spec.merk,
            productnaam=spec.model,
            power_control_system=spec.power_control_system,
            P_active_power=spec.p_active_power_w,
            Smax_apparent_power=spec.smax_apparent_power_w,
            num_phase=spec.num_phase,
            max_charge_w=spec.max_charge_w,
            max_discharge_w=spec.max_discharge_w,
            max_capacity=spec.max_capacity_kwh,
            minimum_capacity=spec.minimum_capacity_pct,
            standby_power_w=spec.standby_power_w,
            round_trip_efficiency=spec.round_trip_efficiency_pct,
            rte_ac_dc=spec.rte_ac_dc_pct,
            rte_dc_ac=spec.rte_dc_ac_pct,
            rte_storage=spec.rte_storage_pct,
            ramp_up_time=spec.ramp_up_time_s,
            max_cycle=spec.max_cycle,
            max_depth_of_discharge=spec.max_depth_of_discharge_pct,
            state_of_charge=state_of_charge,
            state_of_health=state_of_health,
            c_rate=spec.c_rate,
            eol_criteria=spec.eol_criteria_pct,
        )

    def __setattr__(self, naam: str, waarde) -> None:
        """
        Bewaakt bij élke toewijzing - ook tijdens de constructie, en ook van
        buitenaf, bv. in een externe simulatielus die `batterij.state_of_charge
        = ...` zet - dat de technische capaciteiten van de batterij nooit
        overschreden worden, en logt de wijziging in `self.geschiedenis`. Zo
        hoeft een simulatie zelf niets bij te houden of te bewaken: het object
        onthoudt en beschermt zijn eigen toestand.
        """
        geclipt = False

        if naam in self._KLEM_VELDEN:
            if naam == "state_of_charge":
                # minimum_capacity staat al vast op dit punt: het veld komt
                # eerder in de declaratievolgorde en is dus altijd al gezet
                # tegen de tijd dat state_of_charge (voor het eerst) gezet wordt.
                ondergrens = max(0.0, getattr(self, "minimum_capacity", 0.0))
            else:
                ondergrens = 0.0
            geklemde_waarde = min(100.0, max(ondergrens, waarde))
            geclipt = geklemde_waarde != waarde
            waarde = geklemde_waarde
        elif naam in self._VASTE_VELDEN_STRIKT_POSITIEF and float(waarde) <= 0:
            raise ValueError(
                f"{naam} moet groter dan nul zijn, kreeg {waarde}. Het "
                "cyclusverlies wordt door dit getal gedeeld."
            )
        elif naam in self._VASTE_VELDEN_ONDERGRENS_NUL and waarde < 0:
            raise ValueError(f"{naam} is een nameplate-specificatie en kan niet negatief zijn, kreeg {waarde}.")
        elif naam in self._VASTE_VELDEN_PERCENTAGE and not (0.0 <= waarde <= 100.0):
            raise ValueError(f"{naam} moet een percentage tussen 0 en 100 zijn, kreeg {waarde}.")

        # Tijdens __init__ bestaat 'geschiedenis' nog niet (wordt als laatste
        # veld gezet) - die vroege toewijzingen zijn geen wijzigingen, gewoon
        # de initiële constructie, dus niet loggen (wel al bewaakt hierboven).
        geschiedenis_actief = naam != "geschiedenis" and hasattr(self, "geschiedenis")
        oude_waarde = getattr(self, naam) if geschiedenis_actief else None

        object.__setattr__(self, naam, waarde)

        if geschiedenis_actief and oude_waarde != waarde:
            actie = f"{naam}: {oude_waarde} → {waarde}"
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
            "state_of_charge": self.state_of_charge,
            "state_of_health": self.state_of_health,
            "max_capacity": self.max_capacity,
            **extra,
        }

    def geschiedenis_als_dataframe(self) -> pd.DataFrame:
        """Geeft de bijgehouden geschiedenis terug als Pandas DataFrame."""
        return pd.DataFrame(self.geschiedenis)

    def wis_geschiedenis(self) -> None:
        """Leegt de geschiedenis (bv. na het opstarten van een nieuwe simulatierun)."""
        self.geschiedenis.clear()
        self.geschiedenis.append(self._snapshot(actie="Geschiedenis gewist"))

    def _actuele_max_capaciteit(self) -> float:
        """Werkelijk beschikbare capaciteit (kWh), gedegradeerd door de huidige SoH."""
        return self.max_capacity * (self.state_of_health / 100.0)

    def laad(self, vermogen_w: float, duur_s: float) -> float:
        """
        Laadt de batterij met een extern aangeboden AC-vermogen gedurende een
        tijdsduur. Het vermogen wordt begrensd door max_charge_w, de
        opgeslagen energie door de actuele (SoH-gedegradeerde) capaciteit -
        de batterij kan dus nooit meer opnemen of opslaan dan hij fysiek
        aankan, ongeacht wat er gevraagd wordt.

        :param vermogen_w: Aangeboden laadvermogen (W). Negatief wordt als 0 behandeld.
        :param duur_s: Duur van het laadinterval (s).
        :return: Werkelijk benutte laadenergie aan de AC-zijde (kWh), na begrenzing.
        """
        if duur_s < 0:
            raise ValueError("duur_s mag niet negatief zijn.")
        if vermogen_w <= 0:
            return 0.0

        # 1. Vermogen begrenzen door de fabrieksspecificatie
        effectief_vermogen_w = min(vermogen_w, self.max_charge_w)
        aangeboden_energie_kwh = effectief_vermogen_w * duur_s / 3600.0 / 1000.0

        # 2. Fysieke ruimte die nog beschikbaar is (rekening houdend met SoH)
        actuele_max_capaciteit = self._actuele_max_capaciteit()
        huidige_energie_kwh = actuele_max_capaciteit * (self.state_of_charge / 100.0)
        beschikbare_ruimte_kwh = max(0.0, actuele_max_capaciteit - huidige_energie_kwh)

        # 3. AC->DC conversieverlies: er moet meer AC-energie in dan er DC bijkomt
        factor_ac_dc = self.rte_ac_dc / 100.0 if self.rte_ac_dc > 0 else 1.0
        dc_energie_kwh = aangeboden_energie_kwh * factor_ac_dc

        # 4. Nooit meer opslaan dan er fysiek ruimte is
        werkelijk_opgeslagen_kwh = min(dc_energie_kwh, beschikbare_ruimte_kwh)

        if actuele_max_capaciteit > 0:
            self.state_of_charge += (werkelijk_opgeslagen_kwh / actuele_max_capaciteit) * 100.0

        # AC-energie die hiervoor daadwerkelijk werd afgenomen (voor het conversieverlies)
        return werkelijk_opgeslagen_kwh / factor_ac_dc

    def ontlaad(self, vermogen_w: float, duur_s: float) -> float:
        """
        Ontlaadt de batterij met een extern gevraagd AC-vermogen gedurende
        een tijdsduur. Het vermogen wordt begrensd door max_discharge_w, de
        onttrokken energie door wat er boven minimum_capacity nog
        beschikbaar is - de batterij levert dus nooit meer af dan hij fysiek
        en volgens zijn minimumgrens kan geven.

        :param vermogen_w: Gevraagd ontlaadvermogen (W). Negatief wordt als 0 behandeld.
        :param duur_s: Duur van het ontlaadinterval (s).
        :return: Werkelijk geleverde energie aan de AC-zijde (kWh), na begrenzing.
        """
        if duur_s < 0:
            raise ValueError("duur_s mag niet negatief zijn.")
        if vermogen_w <= 0:
            return 0.0

        # 1. Vermogen begrenzen door de fabrieksspecificatie
        effectief_vermogen_w = min(vermogen_w, self.max_discharge_w)
        gevraagde_ac_energie_kwh = effectief_vermogen_w * duur_s / 3600.0 / 1000.0

        # 2. DC->AC conversieverlies: er moet meer DC-energie uit dan er AC uitkomt
        factor_dc_ac = self.rte_dc_ac / 100.0 if self.rte_dc_ac > 0 else 1.0
        benodigde_dc_energie_kwh = gevraagde_ac_energie_kwh / factor_dc_ac

        # 3. Wat er nog beschikbaar is boven de minimumgrens
        actuele_max_capaciteit = self._actuele_max_capaciteit()
        huidige_energie_kwh = actuele_max_capaciteit * (self.state_of_charge / 100.0)
        ondergrens_kwh = actuele_max_capaciteit * (self.minimum_capacity / 100.0)
        beschikbare_energie_kwh = max(0.0, huidige_energie_kwh - ondergrens_kwh)

        # 4. Nooit meer onttrekken dan er fysiek/volgens de minimumgrens beschikbaar is
        werkelijk_onttrokken_dc_kwh = min(benodigde_dc_energie_kwh, beschikbare_energie_kwh)

        if actuele_max_capaciteit > 0:
            self.state_of_charge -= (werkelijk_onttrokken_dc_kwh / actuele_max_capaciteit) * 100.0

        return werkelijk_onttrokken_dc_kwh * factor_dc_ac

    def verbruik_standby(self, duur_s: float) -> float:
        """
        Trekt het eigen standby-verbruik van de batterij (bv.
        besturingselektronica) af over een tijdsduur, begrensd zodat de SoC
        niet onder minimum_capacity zakt.

        :param duur_s: Duur van het interval (s).
        :return: Werkelijk onttrokken standby-energie (kWh).
        """
        if duur_s < 0:
            raise ValueError("duur_s mag niet negatief zijn.")
        if self.standby_power_w <= 0:
            return 0.0

        gevraagde_energie_kwh = self.standby_power_w * duur_s / 3600.0 / 1000.0

        actuele_max_capaciteit = self._actuele_max_capaciteit()
        huidige_energie_kwh = actuele_max_capaciteit * (self.state_of_charge / 100.0)
        ondergrens_kwh = actuele_max_capaciteit * (self.minimum_capacity / 100.0)
        beschikbare_energie_kwh = max(0.0, huidige_energie_kwh - ondergrens_kwh)

        werkelijk_onttrokken_kwh = min(gevraagde_energie_kwh, beschikbare_energie_kwh)

        if actuele_max_capaciteit > 0:
            self.state_of_charge -= (werkelijk_onttrokken_kwh / actuele_max_capaciteit) * 100.0

        return werkelijk_onttrokken_kwh

    @staticmethod
    def bereken_soh_capaciteit(c_actueel: float, c_nominaal: float) -> float:
        """
        Berekent de State of Health op basis van capaciteit (SoHc).

        :param c_actueel: De huidige maximale capaciteit (in Ah of kWh).
        :param c_nominaal: De nominale fabriekscapaciteit (in Ah of kWh).
        :return: SoH percentage (0.0 tot 100.0%).
        """
        if c_nominaal <= 0:
            raise ValueError("Nominale capaciteit moet groter zijn dan 0.")

        soh = (c_actueel / c_nominaal) * 100.0
        return round(soh, 2)

    @staticmethod
    def bereken_capaciteit_coulomb_counting_vectorized(
        data_of_tijd: Union[pd.DataFrame, np.ndarray],
        stroom: Union[np.ndarray, str, None] = None,
        tijd_kolom: str = "tijd",
        stroom_kolom: str = "stroom"
    ) -> float:
        """
        Berekent de capaciteit (Ah) uit een tijdreeks met behulp van vectorintegratie (trapeziumregel).
        Ondersteunt zowel Pandas DataFrames als NumPy arrays.

        :param data_of_tijd: Een pd.DataFrame OF een 1D/2D np.ndarray / Series met tijdstippen (in seconden).
        :param stroom: Indien 'data_of_tijd' een array is: een 1D np.ndarray met stromen (in Ampère).
                    Indien 'data_of_tijd' een DataFrame is: kan dit None blijven.
        :param tijd_kolom: Kolomnaam voor tijd in het DataFrame (standaard 'tijd').
        :param stroom_kolom: Kolomnaam voor stroom in het DataFrame (standaard 'stroom').
        :return: Berekende capaciteit in Ampère-uur (Ah).
        """
        # 1. Verwerking als het invoer-type een Pandas DataFrame is
        if isinstance(data_of_tijd, pd.DataFrame):
            if tijd_kolom not in data_of_tijd.columns or stroom_kolom not in data_of_tijd.columns:
                raise KeyError(f"Kolommen '{tijd_kolom}' en/of '{stroom_kolom}' niet gevonden in DataFrame.")
            
            tijd_array = data_of_tijd[tijd_kolom].to_numpy()
            stroom_array = data_of_tijd[stroom_kolom].to_numpy()

        # 2. Verwerking als de invoer NumPy arrays zijn
        elif isinstance(data_of_tijd, np.ndarray):
            tijd_array = data_of_tijd
            if not isinstance(stroom, np.ndarray):
                raise TypeError("Als 'data_of_tijd' een NumPy array is, moet 'stroom' ook een NumPy array zijn.")
            stroom_array = stroom

        # 3. Verwerking van Pandas Series (los ingestuurd)
        elif isinstance(data_of_tijd, pd.Series) and isinstance(stroom, pd.Series):
            tijd_array = data_of_tijd.to_numpy()
            stroom_array = stroom.to_numpy()

        else:
            raise TypeError("Ongeldige invoer types. Verwacht Pandas DataFrame, Series of NumPy arrays.")

        if len(tijd_array) != len(stroom_array) or len(tijd_array) < 2:
            raise ValueError("Tijd- en stroomreeksen moeten dezelfde lengte hebben en ten minste 2 punten bevatten.")

        # 4. Numerieke integratie via de gevectoriseerde trapeziumregel
        # Gebruik np.trapezoid (NumPy >= 2.0) met fallback naar np.trapz (NumPy < 2.0).
        # We vermijden direct attribuuttoegang op np.trapz om type-checkers/IDE's te laten slagen.
        trapz_func = np.trapezoid if hasattr(np, "trapezoid") else np.__dict__.get("trapz")
        if trapz_func is None:
            raise AttributeError("NumPy ondersteunt geen trapezium-integratie (np.trapezoid/np.trapz).")

        # Int(I dt) geeft Ampère-seconden
        totale_ampere_seconden = trapz_func(y=stroom_array, x=tijd_array)

        # Omzetten naar Ampère-uur (1 uur = 3600 seconden)
        capaciteit_ah = abs(totale_ampere_seconden) / 3600.0
        return float(capaciteit_ah)

    @staticmethod
    def bereken_interne_weerstand(v_oc: float, v_last: float, stroom: float) -> float:
        """
        Berekent de interne Ohmse weerstand van een cel op basis van de spanningsval.
        
        :param v_oc: Open-circuit spanning in rust (Volt).
        :param v_last: Klemspanning onder belasting (Volt).
        :param stroom: Ontlaadstroom (Ampère).
        :return: Interne weerstand in Ohm (Ω).
        """
        if stroom == 0:
            raise ZeroDivisionError("Stroom mag niet 0 zijn bij een weerstandsmeting.")
        
        delta_v = abs(v_oc - v_last)
        r_actueel = delta_v / abs(stroom)
        return r_actueel

    @staticmethod
    def bereken_soh_weerstand(r_actueel: float, r_nieuw: float, r_eol: float) -> float:
        """
        Berekent de State of Health op basis van interne weerstand (SoHr).
        
        :param r_actueel: Huidige gemeten interne weerstand (Ohm).
        :param r_nieuw: Interne weerstand in nieuwstaat (Ohm).
        :param r_eol: Maximale weerstand bij End-of-Life (Ohm).
        :return: SoH percentage (0.0 tot 100.0%).
        """
        if r_eol <= r_nieuw:
            raise ValueError("R_eol moet groter zijn dan R_nieuw.")
        
        soh = ((r_eol - r_actueel) / (r_eol - r_nieuw)) * 100.0
        
        # Begrenzen tussen 0% en 100%
        return round(max(0.0, min(100.0, soh)), 2)

    @staticmethod
    def bereken_soh_via_delta_soc(
        geintegreerde_stroom_ah: float, 
        soc_start: float, 
        soc_eind: float
    ) -> float:
        """
        Schattingsmodel voor het BMS bij partiële ontladingen op basis van delta SoC.
        
        :param geintegreerde_stroom_ah: Totaal verplaatste lading gedurende het interval (Ah).
        :param soc_start: State of Charge aan het begin (schaal 0.0 tot 1.0 of 0 tot 100%).
        :param soc_eind: State of Charge aan het einde (schaal 0.0 tot 1.0 of 0 tot 100%).
        :return: Geschatte actuele capaciteit C_actueel (Ah).
        """
        # Normaliseren naar een schaal van 0.0 tot 1.0 indien opgegeven als percentage
        if soc_start > 1.0:
            soc_start /= 100.0
        if soc_eind > 1.0:
            soc_eind /= 100.0
            
        delta_soc = abs(soc_start - soc_eind)
        
        if delta_soc == 0:
            raise ValueError("Delta SoC kan niet 0 zijn voor een capaciteitsberekening.")
            
        c_actueel_geschat = abs(geintegreerde_stroom_ah) / delta_soc
        return c_actueel_geschat

    def simuleer_levensduur(self, aantal_cycli_te_simuleren: int) -> pd.DataFrame:
        """
        Simuleert de slijtage van de batterij over een opgegeven aantal cycli.
        Geeft een tabel (DataFrame) terug met het verloop.

        :param aantal_cycli_te_simuleren: Het aantal cycli dat gesimuleerd moet worden.
        :return: Pandas DataFrame met de geschiedenis van SoC, SoH en maximale capaciteit per cyclus.
        """
        geschiedenis = []
        
        # Bereken hoeveel de batterij slijt per 1 volledige cyclus
        # Bijv: (100% - 80%) / 6000 cycli = 0.0033% verlies per cyclus
        verlies_per_cyclus = (100.0 - self.eol_criteria) / self.max_cycle
        
        # Begintoestand opslaan in de lijst
        geschiedenis.append({
            "Cyclus": 0,
            "Actie": "Start (Nieuwstaat)",
            "SoC (%)": self.state_of_charge,
            "SoH (%)": round(self.state_of_health, 4),
            "Max Capaciteit (kWh)": round(self.max_capacity, 4)
        })

        # Laat de tijd lopen voor het gevraagde aantal cycli
        for cyclus_nummer in range(1, aantal_cycli_te_simuleren + 1):
            
            # De batterij verliest een fractie van zijn gezondheid
            self.state_of_health -= verlies_per_cyclus
            
            # De nieuwe werkelijke capaciteit = fabriekscapaciteit * gezondheidspercentage
            actuele_max_capaciteit = self.max_capacity * (self.state_of_health / 100.0)
            
            # Zorg dat SoH niet onder 0 zakt in extreme simulaties
            if self.state_of_health <= 0:
                self.state_of_health = 0.0
                actuele_max_capaciteit = 0.0

            # Resultaat van deze cyclus opslaan
            geschiedenis.append({
                "Cyclus": cyclus_nummer,
                "Actie": "1 volledige cyclus voltooid",
                "SoC (%)": 100.0, # We gaan ervan uit dat de cyclus eindigt op volgeladen
                "SoH (%)": round(self.state_of_health, 4),
                "Max Capaciteit (kWh)": round(actuele_max_capaciteit, 4)
            })
            
        # Geef de volledige geschiedenis terug als een Pandas tabel
        return pd.DataFrame(geschiedenis)

    def simuleer_levensduur_met_verlies(self, aantal_cycli_te_simuleren: int) -> pd.DataFrame:
        """
        Simuleert de slijtage én het energieverlies (RTE) over een opgegeven aantal cycli.

        :param aantal_cycli_te_simuleren: Het aantal cycli dat gesimuleerd moet worden.
        :return: Pandas DataFrame met de geschiedenis van SoC, SoH, maximale capaciteit, 
        nergieverlies per cyclus en cumulatief verlies.
        """
        geschiedenis = []
        
        # Slijtage per cyclus berekenen
        verlies_per_cyclus_soh = (100.0 - self.eol_criteria) / self.max_cycle
        
        # We maken een teller aan voor het totale energieverlies
        cumulatief_verlies_kwh = 0.0
        actuele_max_capaciteit = self.max_capacity

        # Startwaarden opslaan (Cyclus 0)
        geschiedenis.append({
            "Cyclus": 0,
            "SoH (%)": round(self.state_of_health, 4),
            "Max Capaciteit (kWh)": round(actuele_max_capaciteit, 4),
            "Verlies per cyclus (kWh)": 0.0,
            "Cumulatief Verlies (kWh)": 0.0
        })

        # Laat de tijd lopen voor het gevraagde aantal cycli
        for cyclus_nummer in range(1, aantal_cycli_te_simuleren + 1):
            
            # 1. Batterij degradeert
            self.state_of_health -= verlies_per_cyclus_soh
            
            # Voorkom dat SoH onder 0 zakt
            if self.state_of_health < 0:
                self.state_of_health = 0.0
                
            actuele_max_capaciteit = self.max_capacity * (self.state_of_health / 100.0)
            
            # 2. Energieverlies (RTE) berekenen
            # Eén cyclus is de actuele capaciteit volledig laden en ontladen.
            # Verlies = Capaciteit * (100% - RTE%)
            rendement_factor = self.round_trip_efficiency / 100.0
            verlies_deze_cyclus = actuele_max_capaciteit * (1.0 - rendement_factor)
            
            # Tel dit verlies op bij het totaal
            cumulatief_verlies_kwh += verlies_deze_cyclus

            # 3. Resultaten van deze cyclus opslaan
            geschiedenis.append({
                "Cyclus": cyclus_nummer,
                "SoH (%)": round(self.state_of_health, 4),
                "Max Capaciteit (kWh)": round(actuele_max_capaciteit, 4),
                "Verlies per cyclus (kWh)": round(verlies_deze_cyclus, 4),
                "Cumulatief Verlies (kWh)": round(cumulatief_verlies_kwh, 4)
            })
            
        return pd.DataFrame(geschiedenis)
    
    def simuleer_bruikbare_capaciteit(self, aantal_cycli_te_simuleren: int) -> pd.DataFrame:
        """
        Simuleert de levensduur, berekent de exacte bruikbare AC-capaciteit
        en het absolute energieverlies per cyclus.

        :param aantal_cycli_te_simuleren: Het aantal cycli dat gesimuleerd moet worden.
        :return: Pandas DataFrame met de geschiedenis van SoH, fysieke capaciteit, 
            bruikbare DC-capaciteit, bruikbare AC-capaciteit, benodigde AC-laadenergie
        """
        geschiedenis = []
        
        # Slijtage per cyclus berekenen op basis van de fabrieksspecificaties
        verlies_per_cyclus_soh = (100.0 - self.eol_criteria) / self.max_cycle
        
        # Zet efficiënties om naar wiskundige factoren (bijv. 98% -> 0.98)
        factor_ac_dc = self.rte_ac_dc / 100.0
        factor_dc_ac = self.rte_dc_ac / 100.0
        factor_opslag = self.rte_storage / 100.0
        factor_dod = self.max_depth_of_discharge / 100.0

        cumulatief_verlies_kwh = 0.0

        for cyclus_nummer in range(0, aantal_cycli_te_simuleren + 1):
            
            # Cyclus 0 is de fabrieksstaat (geen degradatie toepassen)
            if cyclus_nummer > 0:
                self.state_of_health -= verlies_per_cyclus_soh
                if self.state_of_health < 0:
                    self.state_of_health = 0.0

            # 1. Fysiek beschikbare capaciteit in de cellen (DC)
            actuele_fysieke_capaciteit = self.max_capacity * (self.state_of_health / 100.0)
            
            # 2. Toegestane capaciteit door het BMS (DoD limiet)
            bruikbare_dc_capaciteit = actuele_fysieke_capaciteit * factor_dod
            
            # 3. Werkelijk geleverde AC-capaciteit aan de woning
            # DC stroom verliest energie in opslag (chemisch) én tijdens het omvormen naar AC
            bruikbare_ac_capaciteit = bruikbare_dc_capaciteit * factor_opslag * factor_dc_ac
            
            # 4. Werkelijk benodigde AC-energie om de batterij te vullen
            # Om de bruikbare DC-capaciteit te vullen, moet er (vanwege AC->DC verlies) extra stroom in
            benodigde_ac_laad_energie = bruikbare_dc_capaciteit / factor_ac_dc
            
            # 5. Absoluut verlies in kWh voor deze specifieke cyclus (Laden in - Ontladen uit)
            verlies_deze_cyclus = benodigde_ac_laad_energie - bruikbare_ac_capaciteit
            
            # Bij cyclus 0 berekenen we wel de startwaarden, maar is er nog geen slijtage-cyclus voltooid
            if cyclus_nummer > 0:
                cumulatief_verlies_kwh += verlies_deze_cyclus

            geschiedenis.append({
                "Cyclus": cyclus_nummer,
                "SoH (%)": round(self.state_of_health, 4),
                "Fysieke Cel (kWh)": round(actuele_fysieke_capaciteit, 4),
                "BMS Bruikbaar DC (kWh)": round(bruikbare_dc_capaciteit, 4),
                "Echte AC Oogst Woning (kWh)": round(bruikbare_ac_capaciteit, 4),
                "AC Laadkost Paneel/Net (kWh)": round(benodigde_ac_laad_energie, 4),
                "Verlies per Cyclus (kWh)": round(verlies_deze_cyclus, 4),
                "Cumulatief Verlies (kWh)": round(cumulatief_verlies_kwh, 4)
            })
            
        return pd.DataFrame(geschiedenis)