# ROADMAP: Energie_Vlaanderen

> **Eigenaar:** Gert Botte  
> **Licentie:** Apache License 2.0  
> **Roadmapversie:** 0.2-concept  
> **Datum:** 25 augustus 2026

## 1. Geactualiseerde visie

Energie_Vlaanderen evolueert van een energievergelijker naar een controleerbaar energie-data-, reken- en optimalisatieplatform voor particulieren,
kmo's en hoogvermogenklanten. Het platform combineert officiële tarieven, productdata, marktdata, meterdata en technische scenario's
zonder hun verschillende bewijsniveaus door elkaar te halen.

De kernproducten worden:

1. contractvergelijking en factuurcontrole;
2. historische kostenreconstructie;
3. verbruiks-, injectie- en piekanalyse;
4. scenario-engine voor assets en flexibiliteit;
5. data-API, Pythonbibliotheek, REST-API en MCP-server;
6. toekomstige EMS- en MPC-optimalisatie;
7. ondersteuning voor laag-, midden- en hoogspanning.

## 2. Strategische databronnen

- Vlaamse Nutsregulator en CREG voor tarief- en regelgevingsdata.
- V-test en leveranciersbronnen voor contract- en productdata.
- ENTSO-E voor Europese day-ahead- en systeemdata.
- Elia Open Data voor Belgische net-, onbalans- en prognosedata.
- Fluvius of lokale meterinterfaces voor gemandateerde klantmetingen.
- Synergrid en waar bruikbaar Atrias voor sectorprofielen en referentiedata.

Iedere bron krijgt een bronfiche met doel, toegang, licentie, vertrouwelijkheid, updatefrequentie, schema, retentie en fallback.

## 3. Architectuurdoel

```text
Officiële bronnen, marktdata en gemandateerde meterdata
                         |
                         v
       Source registry, consent en immutable archive
                         |
                         v
        Parsers, API-connectors en datakwaliteit
                         |
                         v
         Canonical energy and metering model
                         |
               +---------+---------+
               |                   |
               v                   v
        Tarief-/factuurengine   Time-series platform
               |                   |
               +---------+---------+
                         v
                  Scenario-engine
                         |
               +---------+---------+
               |                   |
               v                   v
        REST/Python/MCP       Forecasting en MPC
                                   |
                                   v
                           Veilige lokale actuatie
```

## 4. Niet-onderhandelbare principes

- Correctheid en reproduceerbaarheid gaan voor functiesnelheid.
- Geen resultaat zonder provenance.
- Geen stille aannames, nulwaarden of intervalverliezen.
- Eenheden, tijdzone, resolutie en geldigheid zijn onderdeel van het datatype.
- Financiële kernberekeningen gebruiken `Decimal`.
- Persoons- en meterdata worden doelgebonden, minimaal en versleuteld verwerkt.
- Factuurberekening, forecasting en actieve sturing blijven afzonderlijke domeinen.
- Midden- en hoogspanning worden niet benaderd met residentiële formules.
- Elke fase heeft harde exitcriteria en een Architecture Decision Record.

## 5. Fase 0: governance en scopeherijking

### Deliverables

- ROADMAP 0.2 en Manifest 3.0 laten reviewen.
- `DATA_GOVERNANCE.md`, `VALIDATION_POLICY.md`, `SECURITY.md` en `PRIVACY.md`.
- API- en databronregister voor VNR, CREG, V-test, ENTSO-E, Elia, Fluvius, Synergrid en Atrias.
- Consent- en retentiemodel voor meterdata.
- Segmentdefinities voor residentieel, kmo, grootverbruiker en industrieel.
- Spanningsniveaus en toepassingsgrenzen vastleggen.
- Assumption register en lijst met bekende beperkingen.

### Exitcriteria

- Juridische en technische status van iedere databron is vastgelegd.
- Minstens één lage-spannings- en één hoogvermogen-use-case zijn volledig beschreven.
- Geen persoonlijke meterdata wordt opgehaald vóór security- en privacyreview.

## 6. Fase 1: canonical domain model en data dictionary

### Nieuwe kernentiteiten

Naast bestaande bron-, product- en tariefentiteiten:

- `customers` en pseudonieme gebruikersidentiteiten;
- `connection_points` en EAN-referenties;
- `connection_contracts`;
- `voltage_levels` en `customer_segments`;
- `meters`, `meter_channels` en `measurement_series`;
- `interval_measurements` en `data_quality_flags`;
- `consents`, `mandates` en `access_grants`;
- `market_series` en `market_values`;
- `grid_power_components` en `reactive_energy_components`;
- `forecast_runs`, `optimization_runs` en `control_plans`.

### Exitcriteria

- Laag-, midden- en hoogspanningsaansluitingen zijn zonder informatieverlies modelleerbaar.
- Intervaldata ondersteunt afname, injectie, actief en reactief vermogen.
- EAN en persoonsgegevens zijn afzonderlijk beveiligd.
- Tijdreekspartitionering en retentie zijn getest.

## 7. Fase 2: bronarchief en connectorframework

Bouw één generiek framework voor downloads, REST-API's en gemandateerde data.

### Connectorvolgorde

1. bestaande VNR/DNB-bronnen;
2. ENTSO-E proof of concept;
3. Elia Open Data proof of concept;
4. Synergrid-profielen;
5. Fluvius technische en contractuele proof of concept;
6. leveranciersconnectoren.

### Exitcriteria

- Iedere ingestie is idempotent, versioned en observeerbaar.
- API-tokens en certificaten staan nooit in broncode of logs.
- Rate limiting, retry, quarantaining en schemawijzigingen zijn getest.

## 8. Fase 3: parsers en marktdata

### Werkpakketten

- V-test- en DNB-parsers productierijp maken.
- ENTSO-E day-aheadprijzen voor de Belgische biedzone ophalen.
- Elia-datasets modelleren zonder ze als leveranciersprijs te behandelen.
- RLP0N, SLP-EX en SPP importeren.
- Centrale eenheids- en tijdzoneconversies bouwen.

### Exitcriteria

- DST-dagen van 23 en 25 uur zijn getest.
- Negatieve prijzen blijven behouden.
- Ontbrekende en dubbele intervallen zijn zichtbaar.
- Dezelfde bron en versie levert deterministische output.

## 9. Fase 4: gemandateerde meterdata

### Doel

Werkelijke meetprofielen veilig importeren via Fluvius, P1, AMR of EMS.

### Werkpakketten

- Fluvius-partnerschap en toegangsvoorwaarden formeel onderzoeken.
- Mandaat- en onboardingflow ontwerpen.
- Connector abstraheren zodat lokale P1/AMR-data hetzelfde canonical schema gebruikt.
- Dekking, kwaliteit, correcties en ontbrekende intervallen modelleren.
- Data-export en verwijdering door gebruiker implementeren.

### Exitcriteria

- Consent, autorisatie en audittrail zijn end-to-end getest.
- Ruwe meetdata is versleuteld en niet zichtbaar in standaardlogs.
- Een gebruiker kan zijn data exporteren en verwijderen.
- Een ingetrokken mandaat stopt toekomstige opvragingen.

## 10. Fase 5: rekenengine laagspanning

Behouden uit de oorspronkelijke roadmap, met verplichte conformiteit aan Manifest 3.0.

### Scope

- vast, variabel, dynamisch en ToU;
- digitale, analoge en prosumentprofielen;
- distributietarieven, capaciteitstarief, heffingen en btw;
- aardgas waar officieel gevalideerd;
- volledige uitsplitsing, provenance en warnings.

### Exitcriteria

- ten minste tien onafhankelijke referentiefacturen;
- 100% branch coverage voor kritieke financiële regels;
- geen floats in de financiële kern;
- geen niet-verklaarde afwijkingen boven de toleranties.

## 11. Fase 6: rekenengine midden- en hoogspanning

### Doel

Een afzonderlijke tariefengine bouwen voor hoogvermogenklanten.

### Onderzoek

- klantcategorieën en spanningsniveaus;
- contractueel en gemeten vermogen;
- kwartiermaxima en vermogensoverschrijdingen;
- actief en reactief energiegebruik;
- transformator- en aansluitingscomponenten;
- transmissie- en systeemcomponenten;
- AMR-meetkanalen en tariefgeldigheid.

### Exitcriteria

- officiële tariefmethodologie en tariefbestanden zijn gemodelleerd;
- minstens vijf onafhankelijke grootverbruikerscases zijn gevalideerd;
- residentiële formules worden aantoonbaar niet hergebruikt waar ze niet gelden;
- reactieve energie en vermogenscomponenten hebben aparte tests;
- publicatie blijft geblokkeerd voor niet-gevalideerde segmenten.

## 12. Fase 7: leveranciersdata en contractvergelijking

- leveranciersdetails, tariefkaarten en productversies;
- conflictbeleid tussen V-test en leverancier;
- segmentgeschiktheid per product;
- zakelijke en geïndexeerde producten afzonderlijk modelleren;
- geen automatische leverancierwissel in deze fase.

## 13. Fase 8: historische reconstructie en factuurcontrole

- werkelijke of geprofileerde meetdata koppelen aan historische tarieven;
- contractwissels en tariefperioden ondersteunen;
- exacte, gereconstrueerde en geschatte resultaten onderscheiden;
- meetdekking, bronversies en afwijkingsanalyse rapporteren.

## 14. Fase 9: scenario-engine

### Assets

- PV, batterij, EV, laadpaal, warmtepomp, boiler;
- industriële flexibiliteit en stuurbare lasten;
- meerdere aansluitingen of sites pas na bewezen enkel-sitewerking.

### Uitgangspunten

- fysieke en financiële modellen blijven gescheiden;
- scenario's bewaren energie- en vermogensbalans;
- geen perfecte voorkennis behalve als theoretische bovengrens;
- investeringsaannames en onzekerheid zijn zichtbaar.

## 15. Fase 10: forecasting

- belasting- en PV-prognoses;
- ENTSO-E- en Elia-exogene variabelen;
- voorspelfouten en backtesting;
- aparte modellen per klantsegment en resolutie;
- geen optimalisatie zonder gekwantificeerde forecastkwaliteit.

## 16. Fase 11: REST-, Python- en MCP-API

De publieke API biedt goedgekeurde data en reproduceerbare berekeningen.
Persoonlijke meetdata krijgt afzonderlijke authenticatie, autorisatie en tenantisolatie.

MCP blijft standaard read-only. Iedere tool meldt engineversie, bronversies, exactheidsklasse en waarschuwingen.

## 17. Fase 12: MPC en EMS

### Proof of concept

- rolling horizon op kwartierbasis;
- batterij, EV of warmtepomp als eerste stuurbare asset;
- dynamische prijs als eerste objective;
- capaciteitspiek en zelfconsumptie als bijkomende objectives;
- Elia-onbalans alleen in experimentele of contractueel passende use-cases.

### Veiligheidsvoorwaarden

- shadow mode vóór actieve sturing;
- lokale override en fail-safe strategie;
- technische grenzen kunnen niet door cloudsoftware worden overschreden;
- expliciete opt-in per apparaat en doel;
- geen besparingsgarantie;
- werkelijke prestatie wordt tegen voorspelling gemeten.

## 18. Fase 13: Home Assistant en edge-integratie

Begin read-only. Voeg pas later advies en daarna optionele sturing toe.
Ondersteun waar passend MQTT, Modbus, SunSpec, OCPP en lokale EMS-koppelingen, zonder afhankelijk te worden van één hardwareleverancier.

## 19. Direct volgend werkpakket

1. Review en aanvaarding van Manifest 3.0 en Roadmap 0.2.
2. Data dictionary omzetten naar formele JSON Schema/Pydantic-modellen.
3. `ConnectionPoint`, `IntervalMeasurement`, `MarketSeries` en `CalculationResult` als eerste modellen implementeren.
4. Bronregister voor ENTSO-E, Elia, Fluvius, Synergrid en Atrias maken.
5. Technische spike voor ENTSO-E en Elia uitvoeren.
6. Fluvius-toegang en partnerschapsvoorwaarden formeel verifiëren.
7. Een hoogvermogen-referentiecase selecteren en alle benodigde tariefvelden inventariseren.
8. PostgreSQL- en tijdreeksstrategie kiezen.
9. Eén laagspanningsberekening en één hoogvermogenberekening volledig traceerbaar uitschrijven.
10. Pas daarna de huidige `Calculator` opsplitsen in segment- en componentstrategieën.

## 20. Nieuwe bewuste non-goals voor de eerste releases

- geen automatische sturing zonder shadow-modevalidatie;
- geen publicatie van hoogspanningsresultaten zonder officiële referentiecases;
- geen onbalansarbitrage voorstellen aan eindklanten zonder passend contract- en marktmodel;
- geen opslag van meterdata zonder geldige toestemming en verwijderproces;
- geen generieke 'AI-optimalisatie' zonder reproduceerbaar mathematisch model;
- geen multi-site portfolio-optimalisatie vóór de enkel-site-engine stabiel is.

## 21. Succescriteria

Het platform is succesvol wanneer het voor ieder resultaat toont:

- welke klant-, aansluitings- en meetcontext gebruikt werd;
- welke bron- en tariefversies gelden;
- of het resultaat exact, gereconstrueerd, geschat of gesimuleerd is;
- welke aannames, datagaten en onzekerheden bestaan;
- welke formule- en engineversie rekende;
- hoe een onafhankelijke reviewer het resultaat kan reproduceren;
- welke privacytoestemming de verwerking van meterdata rechtvaardigt.
