---
tags: [architectuur, audit, cli]
---

# De 4 Controlepoorten (Audit Pipeline)

## 1. Sanity Check (Volautomatisch)

Wat het doet: Zodra de Ingest Pipeline klaar is, vuur je de sanity checker af. Deze module controleert de CSV's op harde business logica.

Voorbeelden: "Is de elektriciteitsprijs > €0 en < €2 per kWh?", "Zijn er geen lege handelsnamen?", "Zijn alle RLP-waarden positief?"

Resultaat: Een groen of rood vinkje. Bij rood stopt het proces direct.

Commando: `energievergelijker audit sanity --version <id>`

## 2. Steekproeven / Spot Checks (Human-in-the-loop)

Wat het doet: Als de sanity check slaagt, genereert het systeem een rapport met bijvoorbeeld 5 willekeurige rijen
uit de dataset, inclusief exact de locatie in de originele Excel (SourceSheet, source_row).

Jouw rol: Jij opent de Excel, controleert deze 5 waarden visueel en valideert of de code de structuur correct heeft geïnterpreteerd.

Commando: `energievergelijker audit sample --version <id> [--count 5]`

## 3. Golden Master (Volautomatisch / Regressie)

Wat het doet: Zodra je (via stap 2) hebt vastgesteld dat versie A klopt, bombardeer je die tot "Golden Master"
(zie stap 4b). Als je een maand later versie B inlaadt, trekt deze module automatisch een vergelijking
(een zogenaamde diff) tussen de twee.

Resultaat: Een rapport dat zegt: "Let op, de databeheerkosten bij Fluvius Antwerpen zijn met 12% gestegen
ten opzichte van de Golden Master. Klopt dit?"

Commando: `energievergelijker audit golden --version <id>` — vergelijkt de gestagede CSV's cel voor cel met
de bron-XLSX (`VTestGoldenAuditor`/`TariffGoldenAuditor` in `audit/golden.py`).

## 4. The Approval Gate (De Stempel)

Wat het doet: Als jij als projectleider tevreden bent na de steekproeven en de Golden Master-vergelijking,
doorloop je twee aparte stappen — dit is bewust géén één commando:

**4a. Goedkeuren** — markeer de versie als betrouwbaar:
```
energievergelijker audit approve --version <id> [--notes "..."]
```

**4b. (optioneel) Tot Golden Master maken** — pas nodig als je deze versie als referentie voor toekomstige diffs wil gebruiken:
```
energievergelijker audit set-golden --version <id>
```

De status van een versie kun je op elk moment opvragen met `energievergelijker audit status --version <id>`.

Het mechanisme: `audit approve` schrijft een statusbestand (via `ApprovalManager`, in `manager.py`) dat de versie
van "quarantined" naar "approved" zet. `audit set-golden` wijzigt een apart pointerbestand (`golden_master.txt`
in de dataroot) dat aangeeft welke versie de huidige referentie is voor `audit golden`-diffs. De `DataRepository`
gebruikt de `approved`-status om te bepalen welke versies bruikbaar zijn; niet-goedgekeurde versies worden genegeerd.

## Mappenstructuur voor de Audit Module

```text
src/energie_vlaanderen/
├── audit/
│   ├── __init__.py
│   ├── sanity.py       (De grenswaarden en business logica)
│   ├── sampler.py      (De steekproef-generator)
│   ├── golden.py       (De vergelijker met de referentieversie)
│   └── manager.py      (Beheert de statussen: quarantaine -> approved, en de Golden Master-pointer)
```

De bijhorende CLI-commando's zitten in `src/energie_vlaanderen/cli/audit.py` (business-logica) en worden
geregistreerd in `src/energie_vlaanderen/cli/groups.py` (de `audit`-commandogroep).

---
terug naar [[MOC]]
