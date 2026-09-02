import pandas as pd
from energie_vlaanderen.calculation.battery import Battery


def start_simulator():
    print("--- Batterij Simulator Gestart ---")
    
    # 1. Maak de batterij aan met realistische gegevens
    # We gebruiken als voorbeeld de Marstek Venus specificaties
    mijn_batterij = Battery(
        synergrid_id="SG-123456",
        merknaam="Marstek",
        productnaam="Venus 5.12",
        power_control_system="Hybride",
        P_active_power=5.0,
        Smax_apparent_power=5.0,
        num_phase=1,
        
        # Technische info
        max_charge_w=2500.0,       # 2.5 kW maximaal laadvermogen
        max_discharge_w=2500.0,    # 2.5 kW maximaal ontlaadvermogen
        max_capacity=5.12,         # 5.12 kWh nominale capaciteit
        minimum_capacity=10.0,     # BMS buffer van 10%
        standby_power_w=15.0,      # 15 Watt sluimerverbruik
        
        # Rendement (RTE)
        round_trip_efficiency=95.0,
        rte_ac_dc=98.0,
        rte_dc_ac=98.0,
        rte_storage=99.0,
        
        ramp_up_time=0.5,
        
        # Levensduur & Status
        max_cycle=6000,
        max_depth_of_discharge=90.0,
        state_of_charge=100.0,     # We starten met een volle batterij
        state_of_health=100.0,
        c_rate=0.5,
        eol_criteria=80.0
    )

    print(f"\nBatterij geïnitialiseerd: {mijn_batterij.merknaam} {mijn_batterij.productnaam}"
          f" met een capaciteit van {mijn_batterij.max_capacity} kWh en een maximale levensduur van {mijn_batterij.max_cycle} cycli.")  

    # =====================================================================
    # SIMULATIE DEEL 1: Jarenlange slijtage (Levensduur zonder compromissen)
    # =====================================================================
    print("\n--- Deel 1: Levensduur Simulatie (eerste en laatste cycli) ---")
    
    # Simuleer 6000 cycli en sla het op in een DataFrame
    levensduur_df = mijn_batterij.simuleer_bruikbare_capaciteit(aantal_cycli_te_simuleren=6000)
    
    # Print de eerste 2 en de laatste 2 resultaten om te zien hoe de capaciteit daalt
    print(levensduur_df.head(2))
    print("...")
    print(levensduur_df.tail(2))


    # =====================================================================
    # SIMULATIE DEEL 2: Een dag uit het leven van de batterij (Real-time)
    # =====================================================================
    print("\n--- Deel 2: Real-time Dagelijkse Cyclus ---")
    
    # Eerst wissen we de geschiedenis, zodat we een schone lei hebben voor deze testrun
    mijn_batterij.wis_geschiedenis()
    
    # We starten de ochtend met een batterij die leeg is tot aan de veilige BMS grens (10%)
    mijn_batterij.state_of_charge = 10.0 

    # Gebeurtenis 1: Zonnepanelen geven veel stroom (Laden)
    # We laden met 2000 Watt gedurende 2 uur (7200 seconden)
    opgenomen_ac = mijn_batterij.laad(vermogen_w=2000.0, duur_s=7200.0)
    print(f"Ochtend: Geladen. Vroeg {opgenomen_ac:.2f} kWh van zonnepanelen/net.")

    # Gebeurtenis 2: Batterij doet niets, staat stand-by gedurende 4 uur (14400 seconden)
    verlies_standby = mijn_batterij.verbruik_standby(duur_s=14400.0)
    print(f"Middag: Stand-by. Kostte {verlies_standby:.3f} kWh.")

    # Gebeurtenis 3: De avond valt, we gaan koken en tv kijken (Ontladen)
    # We vragen 1500 Watt gedurende 3 uur (10800 seconden)
    geleverde_ac = mijn_batterij.ontlaad(vermogen_w=1500.0, duur_s=10800.0)
    print(f"Avond: Ontladen. Leverde {geleverde_ac:.2f} kWh aan de woning.")

    # =====================================================================
    # RESULTAAT: De automatische geschiedenis bekijken
    # =====================================================================
    print("\n--- Logboek van de dynamische gebeurtenissen ---")
    
    # Haal de geschiedenis op via de ingebouwde Pandas functie
    logboek_df = mijn_batterij.geschiedenis_als_dataframe()
    
    # Toon alle geregistreerde wijzigingen in de status van de batterij
    print(logboek_df[['stap', 'actie', 'state_of_charge']])

# Start het programma
if __name__ == "__main__":
    start_simulator()