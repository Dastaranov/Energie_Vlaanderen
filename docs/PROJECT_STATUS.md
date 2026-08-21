# Stand van zaken: EnergieVergelijker Vlaanderen

## 1. Doel van het project

EnergieVergelijker Vlaanderen wordt een modulair Pythonprogramma dat officiële energiegegevens automatisch ontdekt, downloadt, valideert, parseert, normaliseert en inzet voor prijsvergelijkingen van Vlaamse energieproducten.

De toepassing moet uiteindelijk zonder handmatig vervangen van bronbestanden kunnen werken. De officiële Excelbestanden vormen de primaire bron. De gegenereerde CSV-bestanden en lokale dataversies zijn afgeleide, gecontroleerde gegevens.

## 2. Wat al gebouwd is

### 2.1 Projectstructuur

De oorspronkelijke monolithische toepassing is opgesplitst in modules met afzonderlijke verantwoordelijkheden.

Belangrijke bestaande modules:

- `config.py`: centrale configuratie via `Settings`.
- `paths.py`: beheer van `raw`, `staging`, `versions`, `failed` en de actieve dataset.
- `models.py`: domeinmodellen zoals `Profile`, `Product` en `Cost`.
- `normalizer.py`: algemene tekst-, null-, decimaal- en geldnormalisatie.
- `parser.py`: robuuste CSV-parser.
- `repository.py`: laden van genormaliseerde datasets en opbouwen van producten.
- `calculator.py`: berekening van leverancierskost, netkost, heffingen, btw en totaal.
- `market.py`: ENTSO-E-marktdata en lokale cache.
- `intervals.py`: verwerking van Fluvius-kwartierwaarden.
- `sources.py`: ontdekking van officiële bronbestanden.
- `downloader.py`: veilige download van officiële XLSX-bestanden.
- `raw_store.py`: manifestvalidatie, checksumcontrole en deduplicatie van raw-versies.
- `vtest_workbook.py`: structurele parsing van het V-testwerkboek.
- `vtest_normalizer.py`: inhoudelijke normalisatie van V-testproductrijen.
- `vtest_validator.py`: validatie van genormaliseerde productcomponenten.
- `vtest_pipeline.py`: keten van parsing, normalisatie, validatie en stagingexport.
- `cli.py`: command-line interface met subcommands.

### 2.2 Centrale configuratie

`Settings` bepaalt onder andere:

- projectroot;
- dataroot;
- officiële bronpagina's;
- toegelaten downloadhosts;
- requesttimeout;
- maximale downloadgrootte;
- downloadchunkgrootte;
- user-agent.

Instellingen kunnen via omgevingsvariabelen worden overschreven zonder broncode te wijzigen.

### 2.3 Datamappen en versies

De datapaden zijn gecentraliseerd:

```text
data/
├── raw/
├── staging/
├── versions/
├── failed/
├── current/
└── current.txt
```

- `raw`: onveranderde officiële downloads met manifest.
- `staging`: tijdelijk verwerkte output die nog niet gepubliceerd is.
- `versions`: gevalideerde publiceerbare datasets.
- `failed`: mislukte runs of diagnostische output.
- `current.txt`: atomaire verwijzing naar de actieve versie.
- `current`: tijdelijke compatibiliteit met de bestaande datasetindeling.

### 2.4 CLI met subcommands

De oude platte argumentparser is omgebouwd naar subcommands.

Reeds opgebouwde of voorbereide commando's:

```text
paths
sources
download
raw-status
verify-raw
parse-vtest
compare
```

De CLI gebruikt gedeelde configuratie en geeft gecontroleerde exitcodes terug.

### 2.5 Bronontdekking

`VnrSourceScraper` ontdekt vier officiële XLSX-bronnen:

1. V-testproductdata;
2. energieprijscurves;
3. distributienettarieven elektriciteit;
4. distributienettarieven aardgas.

De scraper:

- volgt alleen toegelaten hosts;
- verwerkt relatieve en absolute links;
- selecteert alleen XLSX-bestanden;
- weigert ontbrekende of niet-eenduidige matches;
- biedt gewone en JSON-uitvoer via de CLI;
- is unit-testbaar met lokale HTML-fixtures en een fake sessie.

### 2.6 Veilige downloader

`ArtifactDownloader`:

- downloadt met streaming;
- respecteert timeout en maximale bestandsgrootte;
- controleert de finale redirect-URL;
- schrijft eerst naar een tijdelijk bestand;
- controleert ZIP/XLSX-signatuur;
- controleert verplichte XLSX-onderdelen;
- test de ZIP-container;
- berekent SHA-256;
- gebruikt vaste lokale bestandsnamen;
- schrijft een atomair `manifest.json`;
- verwijdert een onvolledige batch bij een fout.

Vaste lokale bestandsnamen:

```text
vtest.xlsx
energy_curves.xlsx
electricity_tariffs.xlsx
gas_tariffs.xlsx
manifest.json
```

### 2.7 Raw-opslag en deduplicatie

`RawStore`:

- opent en valideert manifesten;
- verifieert versie-id's;
- controleert bestandsgrootte en SHA-256;
- valideert elk XLSX-bestand opnieuw;
- rapporteert ontbrekende en onverwachte bestanden;
- vergelijkt contentfingerprints;
- verwijdert een nieuwe raw-versie wanneer ze inhoudelijk identiek is aan een eerdere geldige versie.

### 2.8 V-testwerkboekparser

`VTestWorkbookParser`:

- opent het officiële werkboek met `openpyxl` via pandas;
- inspecteert alle werkbladen;
- zoekt de header in de eerste configureerbare rijen;
- vereist de kernkolommen voor productdata;
- negeert niet-productbladen;
- splitst vaste producten van variabele en dynamische producten;
- gebruikt producttypekolommen en, indien nodig, de werkbladnaam;
- normaliseert lege waarden;
- bewaart `source_sheet` en `source_row`;
- retourneert een `ParsedVTestWorkbook` met twee DataFrames.

### 2.9 V-testnormalisatie

De bestaande `vtest_normalizer.py` bevat:

- `VTestDataNormalizer`;
- `NormalizedVTestData`;
- `RowIssue`;
- omzetting van jaar en maand;
- canonicalisatie van segment, energietype en richting;
- canonicalisatie van `vast`, `variabel` en `dynamisch`;
- mapping van prijsonderdelen naar componentcodes;
- omzetting van Belgische decimalen naar `Decimal`;
- verwerking van coëfficiënten `a`, `b`, `c`, `d` en `z`;
- uitlezen van indexnamen en indexwaarden A tot en met D;
- waarschuwingen voor niet-nulcoëfficiënten zonder indexwaarde;
- behoud van bronmetadata;
- uitsluiting van rijen met blokkerende normalisatiefouten.

### 2.10 V-testvalidatie

`VTestDataValidator` controleert:

- verplichte genormaliseerde kolommen;
- dubbele productcomponenten;
- producttypes in de juiste tabel;
- vaste componenten zonder prijs;
- variabele componenten zonder prijs of formule;
- dynamische componenten zonder prijs of formule;
- niet-nulcoëfficiënten zonder indexwaarde.

De validator levert een rapport met errors, warnings en een `valid`-eigenschap.

### 2.11 V-testpipeline

`VTestPipeline` verbindt:

```text
VTestWorkbookParser
        ↓
VTestDataNormalizer
        ↓
VTestDataValidator
        ↓
CSV-export + pipeline_report.json
```

De pipeline:

- exporteert alleen wanneer geen blokkerende fouten bestaan;
- schrijft vaste en variabele/dynamische data afzonderlijk;
- bewaart decimalen zonder ongewenste afronding;
- schrijft een gedetailleerd verwerkingsrapport;
- weigert bestaande stagingdoelen te overschrijven;
- ruimt gedeeltelijke output op bij fouten.

### 2.12 Teststrategie

De tests zijn gescheiden in:

- unit tests zonder productiegegevens;
- integratietests met `ENERGIEVERGELIJKER_DATA_DIR`;
- fake HTTP-sessies voor bronontdekking en downloads;
- synthetische XLSX-bestanden;
- validatie van foutscenario's;
- CLI-parsertests.

Belangrijke testprincipes:

- geen internet nodig voor unit tests;
- geen afhankelijkheid van de actieve werkdirectory;
- expliciete testdatafixture;
- tijdelijke mappen via `tmp_path`;
- geen gedeeltelijke output bij een fout.

## 3. Huidige grens van het systeem

De infrastructuur voor V-testproductdata is grotendeels opgebouwd, maar de volledige automatische updater is nog niet klaar. De volgende onderdelen moeten nog worden gekoppeld of ontwikkeld:

- pipeline aansluiten op `parse-vtest`;
- echte V-testbron volledig door de pipeline laten lopen;
- parser voor energieprijscurves;
- parser voor elektriciteitsnettarieven;
- parser voor gastarieven;
- datasetbrede validatie;
- publicatie naar `versions`;
- activering via `current.txt`;
- rollback;
- één overkoepelend `update`-commando;
- geplande uitvoering en rapportering.
