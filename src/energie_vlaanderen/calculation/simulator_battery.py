from energie_vlaanderen.calculation.batterySpec import Battery
from energie_vlaanderen.gebruikers.models import AssetType, GebruikersError
from energie_vlaanderen.gebruikers.toml_io import lees_dossier
from energie_vlaanderen.hardware.repository import BatterijRepository, HardwareError
from energie_vlaanderen.settings import Settings


def start_simulator():
    print("--- Batterij Simulator Gestart ---")

    # 1. Batterij bouwen uit masterdata, niet uit hardcoded kwargs.
    #
    # Welk model dat is, staat in gebruiker.toml (`[aansluiting.batterij]`),
    # niet in dit script — zo hangt de gekozen batterij niet vast aan de
    # broncode, en levert een tweede simulatie (ander model) geen Python-
    # wijziging meer op, enkel een andere regel in gebruiker.toml.
    settings = Settings.load()
    try:
        dossier = lees_dossier(
            settings.project_root / "gebruiker.toml",
            project_root=settings.project_root,
        )
    except GebruikersError as exc:
        print(f"Kon gebruikersprofiel niet lezen: {exc}")
        return

    batterijen = [a for a in dossier.assets if a.type is AssetType.BATTERIJ]
    if not batterijen:
        print(
            "gebruiker.toml heeft geen batterij gekozen "
            "([aansluiting.batterij] merk/model) — simulatie overgeslagen."
        )
        return
    asset = batterijen[0]

    try:
        repo = BatterijRepository.load(
            settings.project_root / "config" / "hardware" / "batterijen"
        )
        spec = repo.batterij(asset.merk, asset.model)
    except HardwareError as exc:
        print(f"Kon batterijmasterdata niet laden: {exc}")
        return

    mijn_batterij = Battery.from_masterdata(spec)

    print(f"\nBatterij geïnitialiseerd: {mijn_batterij.merknaam} {mijn_batterij.productnaam}"
          f" met een capaciteit van {mijn_batterij.max_capacity} kWh en een maximale levensduur van {mijn_batterij.max_cycle} cycli.")

    # =====================================================================
    # SIMULATIE DEEL 1: Jarenlange slijtage (Levensduur zonder compromissen)
    # =====================================================================
    print("\n--- Deel 1: Levensduur Simulatie (eerste en laatste cycli) ---")

    # Simuleer 6000 cycli en sla het op in een DataFrame
    levensduur_df = mijn_batterij.simuleer_bruikbare_capaciteit(aantal_cycli_te_simuleren=6000)

    # Print de eerste 2 en de laatste 2 resultaten om te zien hoe de capaciteit daalt
    print(levensduur_df.head(5))
    print("...")
    print(levensduur_df.tail(5))


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
