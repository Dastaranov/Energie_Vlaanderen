# Bronnen voor technische data van batterijen en omvormers

## Kernconclusie

Er bestaat momenteel geen centrale, volledig open databank of API die voor commerciële batterijen en omvormers
alle technische productkenmerken gestandaardiseerd aanbiedt.

Als met **technische data** onder meer het volgende wordt bedoeld:

- batterijchemie;
- celconfiguratie;
- nominale en bruikbare capaciteit;
- nominale spanning en spanningsvenster;
- interne weerstand;
- laad- en ontlaadcurves;
- C-rates;
- cycluslevensduur;
- rendement als functie van belasting;
- temperatuurgrenzen en temperatuurcorrecties;
- BMS- en communicatieprotocollen;
- MPPT-bereiken;
- DC- en AC-limieten;
- CAN-bus-, Modbus- of registerinformatie;

zijn vooral **fabrikantdatasheets, installatiehandleidingen, certificatiedocumenten en testrapporten** nodig.

## Beoordeling van de eerder genoemde bronnen

### EPREL

EPREL is in hoofdzaak een Europese databank voor energie-etikettering, productregistratie en conformiteitsinformatie.
De databank is niet opgezet als volledige engineeringdatabase voor batterij- of omvormermodellen.

**Bruikbaar voor:**

- productidentificatie;
- fabrikant en model;
- gereglementeerde productkenmerken;
- energie- en conformiteitsinformatie binnen de opgenomen productgroepen.

**Niet voldoende voor:**

- gedetailleerde batterijmodellen;
- laad- en ontlaadcurves;
- BMS-protocollen;
- volledige omvormerrendementscurves;
- uitgebreide DC-, MPPT- en regelparameters.

- [EPREL publieke databank](https://eprel.ec.europa.eu/)
- [EPREL publieke API-key aanvragen](https://eprel.ec.europa.eu/screen/requestpublicapikey)

### Victron Energy VRM API

De VRM API is gericht op operationele installatie- en meetdata van Victron-systemen.
Ze kan onder meer gemeten batterij-, PV-, net- en omvormerwaarden ontsluiten, afhankelijk van de installatie en beschikbare apparatuur.

**Bruikbaar voor:**

- operationele meetwaarden;
- monitoring van installaties;
- tijdreeksen en rapportering;
- integratie met een energiemanagementsysteem.

**Niet voldoende voor:**

- een algemene marktbrede productcatalogus;
- technische eigenschappen van batterijen en omvormers van alle fabrikanten;
- volledige engineeringparameters per commercieel product.

- [Victron VRM API-documentatie](https://vrm-api-docs.victronenergy.com/)
- [Victron-documentatie](https://docs.victronenergy.com/)

### Fraunhofer BetterBat

BetterBat is relevant voor technische gegevens van lithium-ioncellen.
Het zwaartepunt ligt op celgegevens en vergelijking van cellen, niet op een volledige catalogus van commerciële thuisbatterijen,
batterijpacks en omvormers.

**Bruikbaar voor:**

- celcapaciteit;
- nominale spanning;
- afmetingen en gewicht;
- energie- en vermogensdichtheid;
- laad- en ontlaadwaarden;
- cyclusinformatie, voor zover opgenomen.

**Niet voldoende voor:**

- volledige packconfiguraties;
- BMS-instellingen en communicatie;
- commerciële systeemspecificaties;
- omvormerdata.

- [Fraunhofer BetterBat-overzicht](https://www.isi.fraunhofer.de/en/blog/themen/batterie-update/lithium-ionen-batterien-open-source-datenbank-veroeffentlicht.html)

### PVsyst

PVsyst beschikt over componentdata voor simulaties, onder andere voor PV-modules, omvormers en batterijen.
Het is vooral een simulatieomgeving en geen volledig open, algemene REST-API voor het systematisch verzamelen van alle technische marktdata.

**Bruikbaar voor:**

- simulatieparameters;
- componentselectie binnen PVsyst;
- systeemprestatieberekeningen.

**Beperking:**

- geen ideale primaire open bron voor het opbouwen van een onafhankelijke, marktbrede technische productdatabase.

- [PVsyst](https://www.pvsyst.com/)

### Synergrid C10/26

De Synergrid C10/26-lijst is belangrijk voor Belgische netconformiteit en homologatie.
Ze helpt bepalen of een omvormer of ander toestel voor decentrale productie aan de relevante Belgische voorschriften voldoet.

**Bruikbaar voor:**

- merk- en modelidentificatie;
- homologatiestatus;
- Belgische netconformiteit;
- koppeling van een technisch productrecord aan een goedkeuringsrecord.

**Niet voldoende voor:**

- volledige technische modellering;
- batterijcelgegevens;
- laad- en ontlaadcurves;
- volledige rendementscurves en communicatieprotocollen.

- [Synergrid homologatie van decentrale productie-eenheden](https://www.synergrid.be/nl/homologatie/elektriciteit/decentrale-productie-eenheden)

## Bruikbare bronnen voor omvormers

### CEC Inverter Database

De inverterdatabase van de California Energy Commission is relevant voor gestandaardiseerde prestaties en identificatie van omvormers.

Mogelijke gegevens, afhankelijk van het record en de beschikbare export:

- fabrikant en model;
- nominaal AC-vermogen;
- DC-invoerwaarden;
- efficiëntieparameters;
- test- en certificatiewaarden.

- [California Energy Commission](https://www.energy.ca.gov/)

### Sandia Inverter Database

De Sandia-database wordt gebruikt voor omvormermodellen en simulaties. Ze kan nuttig zijn voor prestatiemodellering,
maar de dekking en actualiteit moeten per model worden gecontroleerd.

- [Sandia National Laboratories](https://www.sandia.gov/)

### pvlib

pvlib is een open source softwarebibliotheek voor het modelleren van PV-systemen.
Ze kan worden gebruikt met component- en modelgegevens uit onder meer CEC- en Sandia-bronnen.

**Rol van pvlib:**

- data inlezen en verwerken;
- omvormerprestaties modelleren;
- datasets normaliseren voor analyse;
- geen volledige universele fabrikantendatabase op zichzelf.

- [pvlib-documentatie](https://pvlib-python.readthedocs.io/)

### Fabrikantdocumentatie

Voor commerciële omvormers blijft dit meestal de primaire bron:

- productdatasheets;
- installatiehandleidingen;
- servicehandleidingen;
- Modbus-registerlijsten;
- SunSpec-documentatie;
- certificaten en testrapporten;
- firmware- en communicatiehandleidingen.

Voorbeelden van relevante parameters:

- maximaal en nominaal DC-vermogen;
- MPPT-spanningsbereik;
- startspanning;
- maximaal aantal MPPT's en strings;
- maximale ingangsstroom en kortsluitstroom;
- nominaal en maximaal AC-vermogen;
- rendement en deellastrendement;
- blindvermogenregeling;
- bescherming en IP-klasse;
- communicatieprotocollen;
- compatibele batterijen.

## Bruikbare bronnen voor batterijen

### Battery Archive

Battery Archive is gericht op batterij-experimenten en cyclustestdata.
Deze bron is vooral bruikbaar voor onderzoek, degradatiemodellen en vergelijking van celgedrag.

- [Battery Archive](https://www.batteryarchive.org/)

### Onderzoeksdatasets van NASA, NREL en universiteiten

Onderzoeksdatasets kunnen cycli, capaciteit, temperatuur, laadprofielen en degradatiegegevens bevatten.
Ze zijn doorgaans nuttiger voor modellering dan voor het samenstellen van een actuele commerciële productcatalogus.

- [NREL Data Catalog](https://data.nrel.gov/)
- [NASA Prognostics Data Repository](https://www.nasa.gov/intelligent-systems-division/discovery-and-systems-health/pcoe/pcoe-data-set-repository/)

### Fabrikantdocumentatie

Voor commerciële batterijproducten is de fabrikant doorgaans de primaire bron voor:

- nominale en bruikbare capaciteit;
- nominale spanning;
- spanningsvenster;
- maximaal continu en piekvermogen;
- laad- en ontlaadlimieten;
- DoD;
- rendement;
- garantievoorwaarden en cycli;
- werktemperatuur;
- afmetingen en gewicht;
- IP-klasse;
- uitbreidbaarheid;
- compatibele omvormers;
- communicatie-interface.

Niet alle fabrikanten publiceren celchemie, celconfiguratie, interne weerstand, gedetailleerde degradatiecurves of volledige BMS-registers.

## Praktische architectuur voor een eigen databank

### 1. Omvormers

Gebruik als basis:

1. CEC Inverter Database;
2. Sandia-modeldata;
3. pvlib voor verwerking en modellering;
4. fabrikantdatasheets en handleidingen;
5. Synergrid C10/26 voor Belgische homologatiestatus.

### 2. Batterijen

Gebruik als basis:

1. fabrikantdatasheets en installatiehandleidingen;
2. BetterBat voor celvergelijking;
3. Battery Archive en onderzoeksdatasets voor cycli en degradatie;
4. BMS-, CAN-, Modbus- en integratiedocumentatie waar openbaar beschikbaar;
5. Synergrid-informatie waar relevant voor de gekoppelde omvormer of opslageenheid.

## Aanbevolen datamodel

### Omvormer

```yaml
manufacturer: string
model: string
product_type: pv | battery | hybrid
rated_ac_power_kw: number
max_ac_power_kw: number
max_dc_power_kw: number
mppt_voltage_min_v: number
mppt_voltage_max_v: number
start_voltage_v: number
max_input_voltage_v: number
max_input_current_a: number
max_short_circuit_current_a: number
mppt_count: integer
phase_count: integer
efficiency_max_percent: number
efficiency_european_percent: number
ip_rating: string
communication_protocols: array
battery_compatibility: array
synergrid_c10_26_status: string
source_documents: array
source_checked_date: date
```

### Batterij

```yaml
manufacturer: string
model: string
chemistry: string
nominal_capacity_kwh: number
usable_capacity_kwh: number
nominal_voltage_v: number
voltage_min_v: number
voltage_max_v: number
continuous_charge_power_kw: number
continuous_discharge_power_kw: number
peak_discharge_power_kw: number
max_charge_current_a: number
max_discharge_current_a: number
depth_of_discharge_percent: number
round_trip_efficiency_percent: number
cycle_life: number
cycle_life_conditions: string
operating_temperature_min_c: number
operating_temperature_max_c: number
ip_rating: string
weight_kg: number
scalable_min_modules: integer
scalable_max_modules: integer
compatible_inverters: array
communication_protocols: array
warranty: string
source_documents: array
source_checked_date: date
```

## Belangrijkste beperking

Voor een betrouwbare technische databank moet bij elk veld de herkomst worden bijgehouden.
Een waarde zonder bron, testconditie of documentversie kan misleidend zijn.

Minimaal aanbevolen bronmetadata:

```yaml
source_url: string
source_type: datasheet | manual | certificate | test_report | database
publisher: string
document_title: string
document_version: string
publication_date: date
retrieval_date: date
page_or_section: string
value_as_published: string
normalized_value: string
confidence: high | medium | low
```

## Eindadvies

Gebruik EPREL, Victron VRM, PVsyst en Synergrid niet als vervanging voor fabrikantdocumentatie. Ze kunnen wel aanvullende rollen vervullen:

- **EPREL:** identificatie en gereglementeerde productinformatie;
- **Victron VRM:** operationele meetdata;
- **PVsyst:** simulatieparameters;
- **Synergrid C10/26:** Belgische homologatie;
- **CEC, Sandia en pvlib:** omvormerdata en modellering;
- **BetterBat en Battery Archive:** celdata, cyclustesten en degradatieonderzoek;
- **fabrikantdocumentatie:** primaire bron voor commerciële productkenmerken.

De meest realistische aanpak is daarom een eigen genormaliseerde databank die gegevens uit meerdere
bronnen combineert en elk technisch veld aan een controleerbare bron koppelt.
