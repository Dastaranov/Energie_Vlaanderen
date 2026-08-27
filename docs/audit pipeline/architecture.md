De 4 Controlepoorten (Audit Pipeline)
1. Sanity Check (Volautomatisch)

Wat het doet: Zodra de Ingest Pipeline klaar is, vuur je de sanity checker af. Deze module controleert de CSV's op harde business logica.

Voorbeelden: "Is de elektriciteitsprijs > €0 en < €2 per kWh?", "Zijn er geen lege handelsnamen?", "Zijn alle RLP-waarden positief?"

Resultaat: Een groen of rood vinkje. Bij rood stopt het proces direct.

2. Steekproeven / Spot Checks (Human-in-the-loop)

Wat het doet: Als de sanity check slaagt, genereert het systeem een rapport met bijvoorbeeld 5 willekeurige rijen uit de dataset, inclusief exact de locatie in de originele Excel (SourceSheet, source_row).

Jouw rol: Jij opent de Excel, controleert deze 5 waarden visueel en valideert of de code de structuur correct heeft geïnterpreteerd.

3. Golden Master (Volautomatisch / Regressie)

Wat het doet: Zodra je (via stap 2) hebt vastgesteld dat versie A klopt, bombardeer je die tot "Golden Master". Als je een maand later versie B inlaadt, trekt deze module automatisch een vergelijking (een zogenaamde diff) tussen de twee.

Resultaat: Een rapport dat zegt: "Let op, de databeheerkosten bij Fluvius Antwerpen zijn met 12% gestegen ten opzichte van de Golden Master. Klopt dit?"

4. The Approval Gate (De Stempel)

Wat het doet: Als jij als projectleider tevreden bent na de steekproeven en de Golden Master-vergelijking, voer je een commando uit (bijv. python -m energie_vlaanderen.cli approve --version <id>).

Het mechanisme: Dit schrijft een klein bestandje (bijv. approved.json of een tag) in de map van die versie. De DataRepository wordt zo geprogrammeerd dat hij uitsluitend mappen inlaadt die deze stempel dragen. Al het andere negeert hij.

Mappenstructuur voor de Audit Module

```text
src/energie_vlaanderen/
├── audit/
│   ├── __init__.py
│   ├── sanity.py       (De grenswaarden en business logica)
│   ├── sampler.py      (De steekproef-generator)
│   ├── golden.py       (De vergelijker met de referentieversie)
│   └── manager.py      (Beheert de statussen: quarantaine -> approved)
```