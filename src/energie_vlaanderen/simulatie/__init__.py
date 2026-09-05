"""Mini-API voor simulaties: databank in, kostberekening uit.

Dit pakket is bewust dun. Het hergebruikt wat er al is —
`DbDataRepository`, `Calculator`, `HeffingenRepository`,
`NetbeheerderRegister` — en voegt er alleen het opzoekwerk aan toe dat een
script anders zelf zou moeten uitschrijven: een databankverbinding openen,
een contract met al zijn metadata opvragen, een lijst met contracten
filteren, en één contract voor één periode doorrekenen.

De regel uit CLAUDE.md geldt hier onverkort: de berekening komt uit de code
(`Calculator`), de data uit de databank. Dit pakket voegt geen nieuwe
rekenregel toe — het is verbindingslaag, geen rekenlaag.

Typisch gebruik:

    from energie_vlaanderen.simulatie import open_simulatie, SimulatieProfiel

    with open_simulatie(tariefjaar=2026) as sim:
        contracten = sim.lijst_contracten(energie_type="elektriciteit")
        contract = sim.haal_contract(contracten[0].vreg_id)

        profiel = SimulatieProfiel(
            postcode="9000", segment="Woning", meter="digitaal",
            afname_dag_kwh=D("2000"), afname_nacht_kwh=D("1000"),
        )
        kost = sim.bereken_contract(
            leverancier=contract.leverancier, product_naam=contract.product_naam,
            jaar=2026, maand=8, profiel=profiel,
        )
        print(kost.total)

Wie verder wil bouwen (een reeks contracten doorrekenen, een jaar knippen op
tariefjaarwissels, een dossier uit `gebruiker.toml` simuleren) vindt dat
bouwwerk in `energie_vlaanderen.gebruikers` — dit pakket is het fundament
eronder, niet de vervanging ervan.
"""
from __future__ import annotations

from energie_vlaanderen.simulatie.berekenen import SimulatieProfiel, bereken_kost
from energie_vlaanderen.simulatie.catalogus import ContractMetadata, Leverancier
from energie_vlaanderen.simulatie.context import SimulatieContext, open_simulatie

__all__ = [
    "ContractMetadata",
    "Leverancier",
    "SimulatieContext",
    "SimulatieProfiel",
    "bereken_kost",
    "open_simulatie",
]
