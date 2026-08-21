# EnergieVergelijker Vlaanderen

## Overzicht

EnergieVergelijker Vlaanderen is een Pythonproject voor het automatisch verzamelen, verwerken en vergelijken van energieproducten en gereguleerde nettarieven in Vlaanderen.

Het project heeft twee hoofddoelen:

1. officiële brongegevens automatisch en reproduceerbaar omzetten naar een lokale, gevalideerde dataset;
2. met die dataset de jaarlijkse energiekost voor een opgegeven verbruiksprofiel berekenen en producten vergelijken.

De toepassing is ontworpen rond betrouwbaarheid. Een nieuwe dataset wordt pas actief nadat bronbestanden, parsers, normalisatie en inhoudelijke controles volledig zijn geslaagd. De vorige geldige versie blijft beschikbaar voor rollback.

## Status

Het project is actief in ontwikkeling.

Reeds beschikbaar:

- modulaire packagearchitectuur;
- centrale configuratie;
- versiegebonden datamappen;
- CLI met subcommands;
- bronontdekking;
- veilige XLSX-downloads;
- raw-manifesten en SHA-256-validatie;
- raw-deduplicatie;
- V-testwerkboekparser;
- V-testnormalisatie;
- V-testvalidatie;
- V-testverwerkingspipeline;
- bestaande vergelijkingscalculator;
- uitgebreide unit- en integratietests.

Nog in ontwikkeling:

- koppeling van de volledige pipeline aan de CLI;
- energieprijscurvenparser;
- nettarievenparsers voor elektriciteit en gas;
- datasetbrede validatie;
- geautomatiseerde publicatie en rollback;
- volledig `update`-commando;
- periodieke operationele uitvoering.

## Officiële gegevensbronnen

De toepassing is bedoeld om de officiële publicaties van de Vlaamse Nutsregulator te gebruiken voor:

- V-testproductdata;
- energieprijscurves;
- distributienettarieven elektriciteit;
- distributienettarieven aardgas.

De exacte download-URL's worden niet als permanente bestandslinks hard gecodeerd. De toepassing ontdekt de actuele XLSX-links vanaf de configureerbare officiële bronpagina's.

ENTSO-E kan aanvullend worden gebruikt voor marktprijzen van dynamische elektriciteitsproducten. Fluvius-kwartierwaarden kunnen optioneel worden gebruikt om dynamische kosten op een werkelijk verbruiksprofiel te berekenen.

## Belangrijke ontwerpprincipes

### Officiële bestanden zijn de primaire bron

De gedownloade XLSX-bestanden worden onveranderd in de raw-laag bewaard. CSV-bestanden zijn afgeleide gegevens.

### Geen gedeeltelijke publicatie

Downloads en verwerkte output worden eerst naar tijdelijke of staginglocaties geschreven. Bij een fout wordt de nieuwe run niet actief.

### Reproduceerbaarheid

Elke raw-versie bevat een manifest met:

- bron-URL;
- oorspronkelijke bestandsnaam;
- lokale bestandsnaam;
- bestandsgrootte;
- SHA-256;
- downloadtijdstip;
- versie-id.

### Traceerbaarheid

Genormaliseerde V-testrijen behouden:

- bronwerkblad;
- bronrijnummer;
- oorspronkelijke componentomschrijving.

### Precisie

Geld- en prijswaarden worden intern met `Decimal` verwerkt. De exporter rondt formulecoëfficiënten en indexwaarden niet willekeurig af.

### Testbaarheid

Netwerkafhankelijke logica gebruikt injecteerbare sessies. Unit tests gebruiken fake responses en synthetische werkboeken. Integratietests kunnen een echte lokale dataset gebruiken.

## Architectuur

```text
Officiële bronpagina's
        ↓
VnrSourceScraper
        ↓
ArtifactDownloader
        ↓
data/raw/<version-id>
        ↓
RawStore.verify
        ↓
Bron-specifieke parsers
        ↓
Normalisatie
        ↓
Validatie
        ↓
data/staging/<version-id>
        ↓
Datasetbrede validatie
        ↓
data/versions/<version-id>
        ↓
current.txt
        ↓
DataRepository
        ↓
Calculator
        ↓
Vergelijkingsresultaat
```

## Projectstructuur

```text
energievergelijker_v3/
├── __init__.py
├── calculator.py
├── cli.py
├── config.py
├── constants.py
├── downloader.py
├── intervals.py
├── market.py
├── models.py
├── normalizer.py
├── parser.py
├── paths.py
├── raw_store.py
├── repository.py
├── sources.py
├── validation.py
├── vtest_normalizer.py
├── vtest_pipeline.py
├── vtest_validator.py
└── vtest_workbook.py

tests/
├── conftest.py
├── test_cli.py
├── test_config.py
├── test_downloader.py
├── test_energievergelijker.py
├── test_parser.py
├── test_paths.py
├── test_raw_store.py
├── test_sources.py
├── test_vtest_normalizer.py
├── test_vtest_pipeline.py
├── test_vtest_validator.py
└── test_vtest_workbook.py

data/
├── raw/
├── staging/
├── versions/
├── failed/
├── current/
└── current.txt
```

De exacte bestandslijst kan tijdens de verdere ontwikkeling uitbreiden.

## Installatie

### Vereisten

- Python 3.10 of nieuwer;
- pip;
- een virtuele omgeving wordt aanbevolen.

### Virtuele omgeving

```bash
python -m venv .venv
source .venv/bin/activate
```

Op Windows PowerShell:

```powershell
.venv\Scripts\Activate.ps1
```

### Project installeren

```bash
python -m pip install --upgrade pip
python -m pip install -e ".[test]"
```

## Configuratie

De standaardconfiguratie wordt geladen via:

```python
from energievergelijker_v3.config import Settings

settings = Settings.load()
```

Belangrijke omgevingsvariabelen:

```text
ENERGIEVERGELIJKER_DATA_DIR
ENERGIEVERGELIJKER_REQUEST_TIMEOUT
ENERGIEVERGELIJKER_MAX_DOWNLOAD_BYTES
ENERGIEVERGELIJKER_VTEST_PAGE_URL
ENERGIEVERGELIJKER_TARIFF_PAGE_URL
ENTSOE_API_KEY
```

Voorbeeld:

```bash
export ENERGIEVERGELIJKER_DATA_DIR="$PWD/data"
export ENERGIEVERGELIJKER_REQUEST_TIMEOUT="60"
```

API-sleutels horen niet in Git, broncode, logs of manifests.

## Datamappen

### Raw

```text
data/raw/<version-id>/
```

Bevat officiële, onveranderde downloads en `manifest.json`.

### Staging

```text
data/staging/<version-id>/
```

Bevat tijdelijke genormaliseerde output voordat de volledige dataset wordt gepubliceerd.

### Versions

```text
data/versions/<version-id>/
```

Bevat onveranderlijke, gevalideerde datasets.

### Current

```text
data/current.txt
```

Bevat de id van de actieve versie. Het aanpassen van deze kleine pointer kan atomair gebeuren.

### Failed

```text
data/failed/<version-id>/
```

Kan diagnostische gegevens van mislukte runs bewaren.

## Command-line interface

Algemene help:

```bash
python -m energievergelijker_v3.cli --help
```

### Paden tonen

```bash
python -m energievergelijker_v3.cli paths
```

Toont projectroot, dataroot, raw, staging, versions, failed en de actieve dataset.

### Bronnen ontdekken

```bash
python -m energievergelijker_v3.cli sources --year 2026
```

Als JSON:

```bash
python -m energievergelijker_v3.cli sources --year 2026 --json
```

Dit commando downloadt niets.

### Bronnen downloaden

```bash
python -m energievergelijker_v3.cli download --year 2026
```

De downloader maakt één raw-versie met vier XLSX-bestanden en een manifest. Een inhoudelijk identieke nieuwe batch wordt verwijderd als duplicaat.

### Raw-versies tonen

```bash
python -m energievergelijker_v3.cli raw-status
```

### Raw-versie verifiëren

```bash
python -m energievergelijker_v3.cli verify-raw --version <version-id>
```

Controleert manifest, bestanden, bestandsgrootte, SHA-256 en XLSX-structuur.

### V-testwerkboek verwerken

Het beoogde commando is:

```bash
python -m energievergelijker_v3.cli parse-vtest --version <version-id>
```

De definitieve CLI-koppeling naar de volledige V-testpipeline wordt tijdens de verdere ontwikkeling afgerond.

### Producten vergelijken

```bash
python -m energievergelijker_v3.cli compare   --postcode 9280   --gemeente Lebbeke   --year 2026   --month 8
```

Een expliciete datamap kan worden opgegeven:

```bash
python -m energievergelijker_v3.cli compare   --data "$PWD/data/current"   --postcode 9280   --gemeente Lebbeke
```

## Berekeningsmodel

De calculator verwerkt, afhankelijk van beschikbare data:

- vaste energieprijzen;
- variabele indexatieformules;
- dynamische marktprijzen;
- vaste leveranciersvergoeding;
- kosten voor groene stroom en WKK;
- distributienettarieven;
- capaciteitstarief;
- databeheer;
- afzonderlijk configureerbare heffingen;
- btw;
- injectievergoeding indien beschikbaar.

Intern worden geldbedragen in euro en energieprijzen in euro per kWh verwerkt. Broncomponenten kunnen andere eenheden gebruiken en moeten tijdens parsing en normalisatie expliciet worden geconverteerd.

## V-testverwerking

### Werkboekparser

`VTestWorkbookParser` zoekt producttabellen op inhoud. Niet-relevante werkbladen worden genegeerd. De parser levert:

```python
ParsedVTestWorkbook(
    fixed=...,
    variable_dynamic=...,
    sheets=...,
    warnings=...,
)
```

### Normalizer

`VTestDataNormalizer` zet ruwe productrijen om naar een stabiel schema met onder andere:

```text
year
month
segment
energy
direction
supplier
product
product_type
component
component_label
price
a, b, c, d, z
index_name_A ... index_name_D
index_value_A ... index_value_D
source_sheet
source_row
```

### Validator

`VTestDataValidator` controleert onder andere dubbele componenten, ontbrekende prijzen en onbruikbare formules.

### Pipeline

`VTestPipeline` voert parser, normalizer en validator na elkaar uit. Alleen bij afwezigheid van blokkerende fouten worden CSV's en een rapport geschreven.

## Tests uitvoeren

Alle tests:

```bash
python -m pytest -q
```

Alleen unit tests:

```bash
python -m pytest -q -m "not integration"
```

Integratietests met expliciete dataset:

```bash
ENERGIEVERGELIJKER_DATA_DIR="$PWD/data/current" python -m pytest -q -m integration
```

Gerichte modules:

```bash
python -m pytest -q tests/test_sources.py
python -m pytest -q tests/test_downloader.py
python -m pytest -q tests/test_raw_store.py
python -m pytest -q tests/test_vtest_workbook.py
python -m pytest -q tests/test_vtest_normalizer.py
python -m pytest -q tests/test_vtest_validator.py
python -m pytest -q tests/test_vtest_pipeline.py
```

Syntaxiscontrole van een module:

```bash
python -m py_compile energievergelijker_v3/vtest_pipeline.py
```

## Ontwikkelregels

1. Breid één laag tegelijk uit.
2. Voeg tests toe vóór CLI-integratie.
3. Gebruik geen netwerk in unit tests.
4. Bewaar raw-bronnen onveranderd.
5. Publiceer nooit gedeeltelijke output.
6. Rond Decimal-waarden niet impliciet af.
7. Bewaar bronmetadata.
8. Schrijf machineleesbare rapporten.
9. Gebruik atomische bestandsvervanging voor pointers en manifesten.
10. Houd de vorige geldige versie beschikbaar.

## Probleemoplossing

### Geen actieve dataset

Controleer:

```bash
python -m energievergelijker_v3.cli paths
```

Gebruik eventueel:

```bash
export ENERGIEVERGELIJKER_DATA_DIR="$PWD/data"
```

### Raw-versie ongeldig

```bash
python -m energievergelijker_v3.cli verify-raw --version <version-id>
```

Herstel geen checksums handmatig. Download de bron opnieuw of behoud de vorige geldige versie.

### Bron niet gevonden

```bash
python -m energievergelijker_v3.cli   --log-level DEBUG   sources   --year 2026
```

De scraper weigert bewust nul of meerdere niet-eenduidige kandidaten.

### Pipeline weigert export

Lees `pipeline_report.json` indien geschreven, of de CLI-foutmelding. Blokkerende normalisatie- of validatiefouten moeten eerst worden opgelost. De actieve dataset blijft ongewijzigd.

## Veiligheid en betrouwbaarheid

- alleen configureerbare toegelaten downloadhosts;
- HTTPS voor officiële downloads;
- redirectvalidatie;
- maximale bestandsgrootte;
- ZIP/XLSX-controle;
- SHA-256-verificatie;
- tijdelijke bestanden en atomische vervanging;
- geen overschrijving van bestaande versies;
- geen activering na een mislukte run;
- API-sleutels uitsluitend via veilige configuratie.

## Roadmap

Zie `ROADMAP.md` voor de geplande fasen. Zie `PROJECT_STATUS.md` voor een samenvatting van de reeds gebouwde onderdelen.

## Licentie en gebruik

Voeg vóór publieke distributie een passende licentie toe en documenteer de toepasselijke gebruiksvoorwaarden van elke gegevensbron. De berekende vergelijking is afhankelijk van bronkwaliteit, profielinvoer, belastingregels, tariefperioden en geïmplementeerde formules. Resultaten moeten daarom transparant bronverwijzingen en waarschuwingen tonen.
