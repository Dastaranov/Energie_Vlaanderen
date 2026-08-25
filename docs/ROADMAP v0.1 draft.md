# Roadmap: EnergieVergelijker Vlaanderen

## Uitgangspunt

De roadmap bouwt verder op de bestaande raw-laag en V-testpipeline. Elke fase moet eindigen met unit tests, integratietests en een duidelijke CLI-controle. Een latere fase mag de laatst geldige actieve dataset niet beschadigen.

## Fase 7B.3: V-testpipeline koppelen aan de CLI

### Doel

Het bestaande `parse-vtest`-commando moet `VTestPipeline.process()` gebruiken.

### Te bouwen

- oude losse parse- en exportlogica uit de CLI verwijderen;
- raw-versie eerst verifiëren;
- `vtest.xlsx` uit het raw-manifest ophalen;
- pipeline naar `data/staging/<version-id>/vtest` laten schrijven;
- fouten en waarschuwingen in tekst en JSON tonen;
- correcte exitcode bij validatiefouten.

### Klaar wanneer

```bash
python -m energievergelijker_v3.cli parse-vtest --version <id>
```

maakt:

```text
data/staging/<id>/vtest/master_vast.csv
data/staging/<id>/vtest/master_var_dyn.csv
data/staging/<id>/vtest/pipeline_report.json
```

## Fase 7C: testen tegen het echte V-testwerkboek

### Doel

Bevestigen dat de parser, normalizer en validator aansluiten op de actuele officiële werkboekstructuur.

### Te bouwen

- inspectiecommando voor werkbladen en headers;
- tolerant aliasbeheer voor gewijzigde kolomnamen;
- rapportering van onbekende prijsonderdelen;
- rapportering van niet-geclassificeerde rijen;
- vergelijking van aantallen met de vorige genormaliseerde versie;
- snapshottests van echte kolomnamen zonder het volledige bronbestand in Git op te nemen.

## Fase 8: energieprijscurves

### Doel

Het officiële bestand met energieprijscurves omzetten naar een genormaliseerde dataset.

### Te bouwen

- `energy_curves_workbook.py`;
- header- en sheetdetectie;
- model voor curve, markt, periode, publicatiemaand en waarde;
- decimaal- en datumnormalisatie;
- validatie van duplicaten en ontbrekende perioden;
- stagingexport;
- pipeline- en CLI-integratie.

### Uitvoer

Bijvoorbeeld:

```text
energy_curves.csv
energy_curves_report.json
```

## Fase 9: distributienettarieven elektriciteit

### Doel

Het officiële elektriciteitswerkboek omzetten naar `DNB_ELEK_<jaar>.csv`.

### Te bouwen

- herkenning van overzichts- en DNB-tabbladen;
- mapping van Fluviusnaam naar DNB-code;
- klanttype- en spanningsniveauclassificatie;
- onderscheid afname en injectie;
- canonicalisatie van tariefonderdeel, detail en eenheid;
- behoud van volledige precisie;
- controles op de acht Fluvius-netgebieden;
- vergelijking met werkboekoverzichten.

## Fase 10: distributienettarieven aardgas

### Doel

Het officiële aardgaswerkboek omzetten naar `DNB_GAS_<jaar>.csv`.

### Te bouwen

- tariefcategorieën T1 tot en met T6, LD en MD;
- onderscheid afname en injectie;
- vaste, proportionele en capaciteitscomponenten;
- databeheer, openbare dienstverplichtingen, pensioenen en heffingen;
- eenheidsnormalisatie;
- validatie per DNB en klanttype.

## Fase 11: gemeentelijke DNB-koppeling

### Doel

`DnbPerGemeente.csv` eveneens uit een onderhoudbare bron of gecontroleerde referentiedataset opbouwen.

### Te bouwen

- bronkeuze expliciet vastleggen;
- postcode-gemeentecombinaties valideren;
- ambiguïteiten behouden en rapporteren;
- elektriciteits- en gas-DNB apart modelleren;
- regressietest voor 9280 Lebbeke.

## Fase 12: datasetbrede validatie

### Doel

Alle stagingresultaten als één consistente toekomstige productiedataset beoordelen.

### Te bouwen

- verplicht bestandenoverzicht;
- controles op schema en rijenaantallen;
- referentiële consistentie tussen producten, DNB's en gemeenten;
- controle van jaren en maanden;
- controle van productcomponenten en indexformules;
- vergelijking met vorige actieve versie;
- machineleesbaar validatierapport;
- blokkering bij errors, toelating bij expliciet beoordeelde warnings.

## Fase 13: versiepublicatie

### Doel

Een geldige stagingrun onveranderlijk publiceren.

### Te bouwen

- kopie of verplaatsing naar `data/versions/<version-id>`;
- versie-manifest met bronchecksums en outputchecksums;
- bevestiging dat staging en gepubliceerde output identiek zijn;
- atomaire update van `current.txt`;
- behoud van vorige versie;
- verbod op overschrijven van bestaande versies.

## Fase 14: rollback

### Doel

Snel terugkeren naar een eerdere geldige dataversie.

### CLI

```bash
energievergelijker versions
energievergelijker rollback --version <id>
```

### Te bouwen

- alleen geldige gepubliceerde versies tonen;
- doelversie opnieuw verifiëren;
- `current.txt` atomair aanpassen;
- auditregel schrijven;
- actieve dataset na rollback openen met `DataRepository`.

## Fase 15: overkoepelend updatecommando

### Doel

Eén commando voert de volledige keten uit.

```bash
energievergelijker update --year 2026
```

### Keten

```text
sources
  ↓
download
  ↓
verify raw
  ↓
parse V-test
  ↓
parse curves
  ↓
parse elektriciteit
  ↓
parse gas
  ↓
validate staging
  ↓
publish version
  ↓
activate current
```

### Varianten

```bash
energievergelijker update --year 2026 --dry-run
energievergelijker update --year 2026 --no-activate
energievergelijker update --year 2026 --json
```

## Fase 16: repository en calculator migreren

### Doel

`DataRepository` laten werken met de nieuwe gepubliceerde schema's zonder oude handmatige masterbestanden.

### Te bouwen

- schema-adapter voor genormaliseerde V-testcomponenten;
- productsamenstelling uit componentregels;
- indexformules correct reconstrueren;
- vaste, variabele en dynamische berekening regressietesten;
- elektriciteit en later gas in dezelfde repositoryarchitectuur;
- duidelijke fout bij niet-berekenbare producten.

## Fase 17: operationele automatisering

### Doel

De updater periodiek en controleerbaar uitvoeren.

### Mogelijkheden

- systemd timer op een Linuxhost;
- GitHub Actions-workflow;
- container of cronjob;
- handmatige `workflow_dispatch` voor herstelruns.

### Vereisten

- dagelijkse controle, verwerking alleen bij gewijzigde inhoud;
- timeout en retrybeleid;
- geen activering na een gedeeltelijke fout;
- logs en JSON-runrapport;
- bewaarbeleid voor raw-, staging- en versiegegevens;
- notificatie bij blokkering.

## Fase 18: kwaliteitsverbeteringen

- typecontrole met mypy of pyright;
- linting en formatting;
- testcoverage;
- securitycontrole van dependencies;
- schema-versies en migraties;
- documentatie van bronwijzigingen;
- compacte fixturebestanden;
- performancecontrole op grote werkboeken;
- logging zonder gevoelige API-sleutels.

## Fase 19: gebruikersfuncties

- vergelijkingsprofielen opslaan;
- elektriciteit en gas gecombineerd vergelijken;
- injectievergoeding meenemen;
- kwartierwaarden gebruiken voor dynamische producten;
- rapport in CSV, JSON en eventueel een gebruikersinterface;
- duidelijke bronvermelding en waarschuwingen per resultaat.

## Definitie van een volledig automatische updater

De updater is volledig wanneer een lege installatiedatamap met één commando kan worden opgebouwd, gevalideerd en geactiveerd, terwijl een fout nooit de vorige geldige productieversie beschadigt.
