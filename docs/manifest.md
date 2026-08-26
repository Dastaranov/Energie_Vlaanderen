# Manifest: Energie_Vlaanderen

> **Project:** Energie_Vlaanderen  
> **Auteur:** Gert Botte  
> **Licentie:** Apache License 2.0  
> **Manifestversie:** 3.0-concept  
> **Status:** uitbreiding en inhoudelijke validatie vereist  
> **Referentiedatum:** 25 augustus 2026

## 1. Doel en toepassingsgebied

Dit manifest vormt de functionele en gegevenskundige specificatie voor Energie_Vlaanderen.
Het platform verzamelt, normaliseert en valideert energiegegevens en gebruikt die voor:

1. energiecontractvergelijking en factuurcontrole;
2. historische en hypothetische kostensimulaties;
3. analyse van afname, injectie, piekvermogen en flexibiliteit;
4. scenario's met zonnepanelen, batterijen, warmtepompen en elektrische voertuigen;
5. laagspannings-, middenspannings- en hoogspanningsklanten;
6. particulieren, kmo's en hoogvermogen- of grootverbruiksklanten;
7. toekomstige forecasting, MPC en EMS-integratie.

Elektriciteit is de primaire scope. Aardgas blijft ondersteund waar betrouwbare tarief-, meet- en conversiedata beschikbaar zijn.

## 2. Segmenten en aansluitingsniveaus

### 2.1 Klantsegmenten

- `RESIDENTIAL`: particuliere aansluiting.
- `SME`: kmo-aansluiting op laag- of middenspanning.
- `LARGE_CONSUMER`: grootverbruiker met intervalmeting, contractueel vermogen of complexe tariefstructuur.
- `INDUSTRIAL`: industriële site, mogelijk rechtstreeks aangesloten op een hoger spanningsniveau of met meerdere toegangspunten.

Het klantsegment alleen bepaalt nooit het tarief. Tariefselectie steunt op de aansluiting,
netbeheerder, spanning, meetregime, contracttype, afname- en injectieregime en geldigheidsperiode.

### 2.2 Aansluitingsniveaus

Ondersteunde categorieën worden als configureerbare referentiedata opgeslagen:

- laagspanning;
- middenspanning;
- hoogspanning;
- rechtstreekse aansluiting op het transmissienet, indien binnen de gevalideerde scope.

Voor midden- en hoogspanning kunnen bijkomende componenten gelden, zoals contractueel vermogen,
gemeten maximumvermogen, actief en reactief vermogen, arbeidsfactor, kwartiervermogen, transformatorverliezen,
aansluitings- en systeemdiensten. Deze componenten worden niet afgeleid uit residentiële rekenregels.

## 3. Bronnenhiërarchie en provenance

### 3.1 Bronlagen

1. **Klant- en meetdata:** Fluvius of lokale P1/AMR/EMS-bronnen, uitsluitend met geldige toestemming.
2. **Belgische transmissie- en systeemdata:** Elia Open Data.
3. **Europese markt- en systeendata:** ENTSO-E Transparency Platform.
4. **Sectorreferentiedata:** Vlaamse Nutsregulator, CREG, Synergrid en waar bruikbaar Atrias.
5. **Productdata:** V-test, tariefkaarten en officiële leveranciersbronnen.

### 3.2 Minimale provenance

Elke afgeleide waarde bevat minstens:

- bronorganisatie en bronidentificatie;
- bron-URL of endpoint;
- ophaaltijdstip in UTC;
- publicatie- en geldigheidsperiode;
- bronartefact en SHA-256-checksum;
- parser-, schema- en engineversie;
- transformaties en eenheidsconversies;
- kwaliteitsstatus en eventuele waarschuwingen.

## 4. Externe energie-API's

### 4.1 ENTSO-E

ENTSO-E levert Europese markt- en systeemdata, waaronder day-aheadprijzen, belasting, productie en grensoverschrijdende stromen.
Het platform gebruikt deze data niet als universele vervanging voor leveranciersindexen.

Voor dynamische contracten gelden de volgende regels:

- biedzone en leveringsperiode zijn verplicht;
- bronprijzen worden met hun originele eenheid bewaard;
- `EUR/MWh` wordt centraal geconverteerd naar `EUR/kWh` of `ct/kWh`;
- tijdzone, UTC-offset, zomer- en wintertijd worden expliciet verwerkt;
- dubbele, ontbrekende en gewijzigde intervallen worden gerapporteerd;
- negatieve prijzen blijven behouden;
- marktprijzen worden pas aan verbruik gekoppeld nadat resolutie en intervalgrenzen overeenstemmen.

### 4.2 Elia Open Data

Elia-data kan worden gebruikt voor Belgische netbelasting, onbalans, hernieuwbare productie en prognoses.
Deze data ondersteunt forecasting, scenarioanalyse en toekomstige MPC-functionaliteit.
Een Elia-onbalansprijs is niet automatisch de afnameprijs van een eindklant en mag alleen worden gebruikt
wanneer een product- of optimalisatiemodel dat expliciet voorschrijft.

### 4.3 Fluvius en meterdata

Fluvius-meterdata kan, na formele toegang en geldig gebruikersmandaat, afname, injectie en piekwaarden leveren.
Het platform behandelt deze gegevens als persoonsgegevens of commercieel gevoelige gegevens.

Vereisten:

- doelbinding en expliciete toestemming;
- minimale gegevensophaling en retentie;
- scheiding tussen platform-, organisatie- en gebruikersautorisatie;
- encryptie tijdens transport en opslag;
- auditlog van mandaat, opvraging en verwijdering;
- export- en verwijdermogelijkheid voor de gebruiker;
- geen hergebruik voor sturing zonder afzonderlijke toestemming.

Wanneer geen Fluvius-koppeling beschikbaar is, kan lokale P1-, AMR- of EMS-data worden ingelezen mits
een gedocumenteerd schema en toestemming van de rechthebbende.

### 4.4 Synergrid en Atrias

RLP, SLP-EX en SPP worden gebruikt voor allocatie of benadering wanneer werkelijke intervaldata ontbreken.
Profielgewichten moeten per toepasselijke periode sommeren tot één. Elk resultaat op basis van profielen wordt als schatting gemarkeerd.

## 5. Data dictionary

### 5.1 `CustomerAccount`

- `customer_id: UUID`, verplicht, intern pseudoniem.
- `segment: CustomerSegment`, verplicht.
- `legal_entity_type: str | None`, optioneel.
- `country_code: str`, standaard `BE`.
- `consent_reference: str | None`, verplicht wanneer persoonsgegevens via een externe bron worden geraadpleegd.

### 5.2 `ConnectionPoint`

- `connection_id: UUID`, verplicht.
- `ean_code: str | None`, gevoelig en versleuteld indien opgeslagen.
- `postcode: str`, verplicht voor distributietariefselectie.
- `municipality: str`, verplicht voor distributietariefselectie.
- `grid_operator_code: str`, verplicht na resolutie.
- `voltage_level: VoltageLevel`, verplicht.
- `connection_capacity_kw: Decimal | None`.
- `contracted_capacity_kw: Decimal | None`.
- `transformer_owned_by_customer: bool | None`.
- `metering_regime: MeteringRegime`, bijvoorbeeld analoog, digitaal, AMR of telemetrie.
- `valid_from`, `valid_to`, verplicht voor historische berekeningen.

### 5.3 `ConsumptionProfile`

- `annual_import_kwh: Decimal`.
- `annual_export_kwh: Decimal`.
- `day_import_kwh`, `night_import_kwh`, `exclusive_night_kwh: Decimal | None`.
- `monthly_peaks_kw: tuple[Decimal, ...] | None`, exact twaalf bij een volledig jaar.
- `estimated_monthly_peak_kw: Decimal | None`.
- `profile_type: ACTUAL | RLP0N | SLP_EX | CUSTOM | FLAT`.
- `coverage_ratio: Decimal`, bereik nul tot één.
- `resolution: YEAR | MONTH | DAY | HOUR | PT15M`.

### 5.4 `IntervalMeasurement`

- `connection_id: UUID`.
- `interval_start_utc`, `interval_end_utc`.
- `local_timezone: str`.
- `import_kwh`, `export_kwh: Decimal`.
- `average_import_kw`, `average_export_kw: Decimal | None`.
- `active_power_kw`, `reactive_power_kvar: Decimal | None`.
- `voltage_v`, `current_a`, `power_factor: Decimal | None`.
- `quality_code: str`.
- `source_id`, `provenance_id`.

### 5.5 `Product`

- leverancier, productnaam en productversie;
- energievorm en producttype: vast, variabel, dynamisch of ToU;
- klantsegmenten en aansluitingsniveaus waarvoor het product geldig is;
- begin- en einddatum;
- vaste vergoeding;
- afname- en injectiecomponenten;
- groene-stroom- en WKK-componenten;
- gestructureerde indexatieformules;
- bron, eenheid, btw-status en geldigheidsperiode per component.

### 5.6 `GridTariff`

- netbeheerder en tariefjaar;
- klanttype, spanningsniveau en contracttype;
- tariefdetail en tarieftype;
- prijs, munteenheid en prijseenheid;
- eventueel volume-, vermogen-, piek-, vast, reactief- of maximumtarief;
- geldigheidsperiode en bronverwijzing.

### 5.7 `MarketSeries`

- bronplatform;
- dataset- of documentcode;
- marktgebied of biedzone;
- producttype, bijvoorbeeld day-ahead of onbalans;
- resolutie en tijdzone;
- eenheid;
- publicatie- en leveringsperiode;
- kwaliteitsstatus.

### 5.8 `CalculationResult`

- leverancierskost, nettarieven, heffingen, btw en injectievergoeding;
- afzonderlijke kostencomponenten met incl./excl. btw-status;
- totaalbedrag;
- meetdatadekking;
- exactheidsklasse: exact, gereconstrueerd, geschat of scenario;
- waarschuwingen en foutcodes;
- gebruikte bron-, snapshot-, profiel- en engineversies.

## 6. Energiekost en leveranciersformules

Vaste, variabele, dynamische en ToU-producten worden ondersteund. De generieke formule is:

```text
prijs_t = z + a*A_t + b*B_t + c*C_t + d*D_t
```

Elke indexparameter bevat naam, bron, frequentie, eenheid en geldigheid. Een vereenvoudigde formule `a*X_t + b` is een bijzonder geval.
Ontbrekende verplichte indexwaarden veroorzaken een fout. Een officieel aangeleverde berekende fallbackprijs mag
alleen met zichtbare waarschuwing worden gebruikt.

## 7. Nettarieven

### 7.1 Laagspanning

De berekening ondersteunt volumetrische nettarieven, vaste termen, capaciteitstarief, databeheer, toeslagen, maximumtarief
en waar toepasselijk prosumententarief. Voor digitale meters wordt de gefactureerde maandpiek volgens de geldige
tariefmethodologie berekend. Voor analoge meters worden uitsluitend de officiële analoge klantcategorie en tariefregels
gebruikt, zonder dubbele capaciteitsterm.

### 7.2 Midden- en hoogspanning

Midden- en hoogspanning krijgen een afzonderlijke tariefstrategie. Mogelijke componenten zijn:

- afname per kWh;
- gefactureerd, gemeten of contractueel vermogen;
- maand- of jaarmaximum;
- transformator- en aansluitingscomponenten;
- actief en reactief energiegebruik;
- overschrijding van contractueel vermogen;
- andere net- en systeemdiensten volgens de officiële tariefmethodologie.

De engine mag deze segmenten pas berekenen wanneer de toepasselijke tariefbestanden, formules en referentietests formeel gevalideerd zijn.

## 8. Heffingen en btw

Heffingen worden per geldige schijf, periode, klantcategorie en energievorm gemodelleerd.
Btw-percentages zijn versioned masterdata. Btw-vrije posten, zoals een bijdrage waarvoor de officiële regel vrijstelling bepaalt,
worden afzonderlijk verwerkt. Geen percentage wordt permanent in de financiële kerncode vastgelegd.

## 9. Meetprofielen en datakwaliteit

Voorkeursvolgorde:

1. gevalideerde werkelijke intervalmetingen;
2. gevalideerde maandmetingen;
3. officieel profiel zoals RLP0N of SLP-EX;
4. gedocumenteerd aangepast profiel;
5. vlak profiel uitsluitend voor demonstratie.

Ontbrekende intervallen, overlap, DST-afwijkingen, onmogelijke waarden en onvoldoende meetdekking worden zichtbaar gerapporteerd.

## 10. Referentie-algoritme

1. Valideer klant, aansluiting, segment en meetregime.
2. Selecteer product-, net-, heffings- en btw-versies op geldigheidsdatum.
3. Valideer en harmoniseer meetresolutie en tijdzone.
4. Bereken leverancierskost en injectievergoeding.
5. Bereken nettarieven volgens aansluitingsniveau.
6. Bereken heffingen en niet-btw-plichtige posten.
7. Pas btw per component toe.
8. Bouw resultaat, provenance, datadekking en waarschuwingen op.
9. Voer consistentiecontroles uit voor energie- en geldbalans.

## 11. Scenario-, MPC- en EMS-grens

De factuur- en tariefengine blijft deterministisch en gescheiden van forecasting en optimalisatie.
MPC gebruikt tariffen, marktdata, voorspellingen en technische assets, maar schrijft geen officiële factuurhistoriek over.

Een MPC-resultaat wordt altijd aangeduid als advies of scenario en bevat:

- horizon en resolutie;
- inputprognoses;
- technische beperkingen;
- objective function;
- solver en versie;
- onzekerheden;
- werkelijke versus voorspelde prestatie indien beschikbaar.

Automatische sturing vereist lokale veiligheidslogica, gebruikerslimieten, expliciete opt-in en fail-safe gedrag.

## 12. Fallback- en foutbeleid

- Ontbrekend verplicht tarief: berekening stoppen.
- Ontbrekende marktprijs: interval niet stilzwijgend verwijderen.
- Ontbrekende index: alleen officiële fallback met waarschuwing.
- Ontbrekende meetdata: dekking rapporteren en goedgekeurd profiel gebruiken.
- Ontbrekende maandpieken: alleen gedocumenteerde schatting toepassen.
- Niet-gevalideerd hoogspanningssegment: geen financieel resultaat publiceren.

## 13. Minimale testmatrix

De testmatrix omvat minstens:

- vast, variabel, dynamisch en ToU;
- enkelvoudig, dag/nacht en exclusief nacht;
- analoog, digitaal en AMR;
- afname, injectie en prosument;
- laag-, midden- en hoogspanning;
- particulier, kmo en grootverbruiker;
- negatieve prijzen en ontbrekende intervallen;
- reactieve energie en contractuele vermogenslimieten waar van toepassing;
- btw-vrije posten en progressieve heffingsschijven;
- historische product- en tariefwissels;
- Fluvius-, lokale meter-, Elia- en ENTSO-E-ingestie;
- MPC-scenario's met batterij, EV en warmtepomp.

## 14. Openstaande validaties

Voor productiegebruik moeten nog officieel worden bevestigd:

- actuele toegangs- en contractvoorwaarden van Fluvius;
- exacte Elia- en ENTSO-E-datasets per gebruiksdoel;
- tariefmethodologieën voor midden- en hoogspanning;
- behandeling van reactieve energie en vermogensoverschrijdingen;
- btw op injectievergoedingen en afzonderlijke kosten;
- maximumtarieven en analoge capaciteitstermen;
- gebruiksrechten op product-, profiel- en meterdata;
- representatieve validatieset voor grootverbruikers.
