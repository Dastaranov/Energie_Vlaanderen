---
tags: [prijsmodel, laagspanning, specificatie]
---

# Opbouw van de energieprijs in Vlaanderen

> **Doelgroep:** particulieren en kmo's
> **Project:** Energie Vlaanderen
> **Auteur:** Gert Botte
> **Licentie:** Apache License 2.0
> **Status:** approved
> **Laatste inhoudelijke referentiedatum:** 26 januari 2026

## 1. Doel en toepassingsgebied

Dit document beschrijft de opbouw van de elektriciteits- en aardgasprijs in Vlaanderen en
vormt de functionele basis voor de berekeningen in de Energievergelijker.

De totale energieprijs bestaat uit de volgende hoofdcomponenten:

1. energiekost;
2. nettarieven;
3. heffingen;
4. btw;
5. eventuele afzonderlijke kosten, zoals administratiekosten voor energiedelen.

De berekeningsregels in dit document richten zich hoofdzakelijk op elektriciteit. Waar relevant wordt ook aardgas vermeld.

## 2. Bronnen

- [Vlaamse Nutsregulator: waaruit bestaat de energieprijs?](https://www.vlaamsenutsregulator.be/elektriciteit-en-aardgas/energieprijzen-en-facturen/waaruit-bestaat-de-energieprijs-voor-elektriciteit-en-aardgas)
- [Vlaamse Nutsregulator: distributienettarieven](https://www.vlaamsenutsregulator.be/elektriciteit-en-aardgas/nettarieven/hoeveel-bedragen-de-distributienettarieven)
- [Vlaamse Nutsregulator: wat zijn nettarieven?](https://www.vlaamsenutsregulator.be/elektriciteit-en-aardgas/nettarieven/wat-zijn-nettarieven)
- [Vlaamse Nutsregulator: capaciteitstarief](https://www.vlaamsenutsregulator.be/elektriciteit-en-aardgas/nettarieven/capaciteitstarief)
- [Vlaamse Nutsregulator: prosumententarief](https://www.vlaamsenutsregulator.be/elektriciteit-en-aardgas/nettarieven/prosumententarief)
- [V-test](https://www.vtest.be/)
- [CREG: tarieven voor het transmissienet](https://www.creg.be/nl/professionals/toegang-tot-het-net/elektriciteit-transmissie/tarieven-transmissienet)

> [!NOTE]
> Controleer tarieven, heffingen en btw-percentages altijd tegen de officiële bronnen en de tariefbestanden voor het toepasselijke kalenderjaar.

## 3. Energiekost

### 3.1 Vaste vergoeding

Energieleveranciers kunnen een vaste vergoeding aanrekenen voor administratieve kosten, zoals klantendienst, facturatie en contractbeheer.
Deze kost wordt ook de **jaarlijkse vergoeding** genoemd.

In de berekeningen wordt deze component aangeduid als:

- `j`: vaste vergoeding in euro per jaar.

### 3.2 Energiecomponent

De energiecomponent is de prijs voor de werkelijk afgenomen energie.
Ze wordt doorgaans uitgedrukt in eurocent per kilowattuur (`ct/kWh`) of euro per kilowattuur (`EUR/kWh`).

De energiecomponent kan verschillende vormen aannemen:

- **Vast tarief:** een vooraf vastgelegde prijs per kWh gedurende de contractueel bepaalde periode.
- **Variabel tarief:** een prijs die periodiek wijzigt volgens een contractuele indexatieformule.
- **Dynamisch tarief:** een prijs die de marktprijs per uur of kwartier volgt.
- **Tijdsgebonden tarief, Time-of-Use of ToU:** verschillende prijzen voor vooraf vastgelegde tijdzones.

De uiteindelijke energiekost hangt af van zowel het tarief als het afnameprofiel.

### 3.3 Variabele energiecomponent

Voor een variabel contract gebruikt de leverancier een indexatieformule. Een algemene vorm is:

```text
p_t = a * X_t + b
```

Waarbij:

- `p_t`: energieprijs in periode `t`;
- `X_t`: indexatieparameter in periode `t`;
- `a`: vermenigvuldigingscoefficient van de leverancier;
- `b`: vaste term of marge van de leverancier;
- `t`: maand of kwartaal, afhankelijk van het contract.

Een indexatieparameter kan gebaseerd zijn op:

- een **forwardmarkt**, met prijzen voor een toekomstige periode;
- een **spotmarkt**, met prijzen voor de volgende dag of een korte leveringsperiode.

> [!IMPORTANT]
> De formule-eenheid moet expliciet worden gecontroleerd. Het resultaat kan volgens de tariefkaart in `ct/kWh` of `EUR/kWh` zijn uitgedrukt.
> [!NOTE]
> Voor een exacte jaarberekening is verbruik per indexatieperiode nodig.
> Als alleen jaarverbruik beschikbaar is, moet dit met een gedocumenteerd verbruiksprofiel over de periodes worden verdeeld.

Een overzicht van indexatieparameters en bijbehorende beurzen kan in het project worden bijgehouden in:

```text
/Energiekost/indexatieparameter.csv
```

> [!NOTE]
> Dit pad is conceptueel/illustratief. De werkelijke, geïmplementeerde datalay-out
> is versiegebonden (`data/raw/<versie>/`, `data/staging/<versie>/`,
> `data/versions/<versie>/`, zie `CLAUDE.md` § Data versioning) en wijkt af van
> de voorbeeldpaden in dit document.

### 3.4 Dynamische energiecomponent

Bij een dynamisch contract volgt de energieprijs de marktprijs per uur of kwartier. De totale kost hangt af van:

- de marktprijs per interval;
- het verbruik per overeenkomstig interval;
- de marge of formule van de leverancier;
- de correcte tijdzone en overgang tussen zomer- en wintertijd.

Zonder intervalverbruik is geen exacte dynamische berekening mogelijk.
Een vlak of standaard lastprofiel levert alleen een benadering op en moet als zodanig worden gemarkeerd.

### 3.4.1 ENTSO-E en marktdata

ENTSO-E (European Network of Transmission System Operators for Electricity)
publiceert via haar Transparency Platform marktgegevens voor de Europese
elektriciteitsmarkt.

Voor dynamische elektriciteitscontracten kunnen uurprijzen afkomstig zijn van:

- EPEX SPOT Belgium;
- andere day-aheadmarkten;
- gegevens gepubliceerd via ENTSO-E.

Belangrijke principes:

- Marktprijzen worden doorgaans aangeleverd in EUR/MWh.
- Voor facturatie moeten deze worden omgerekend naar EUR/kWh of ct/kWh.
- Dagprijzen gelden voor een specifiek leveringsuur.
- Tijdzones moeten expliciet verwerkt worden.
- Overgangen tussen zomer- en wintertijd mogen geen dubbele of ontbrekende
  uren veroorzaken.

Omrekening:

1 EUR/MWh = 0,001 EUR/kWh
1 EUR/MWh = 0,1 ct/kWh

Negatieve marktprijzen zijn toegestaan en moeten ondersteund worden.

Indien leverancierstarieven een formule gebruiken:

prijs_h = a × marktprijs_h + z

dan moet eerst de marktprijs correct worden omgerekend naar de eenheid die
door de formule verwacht wordt.

### 3.5 Kosten voor groene stroom en warmtekrachtkoppeling

Leveranciers kunnen afzonderlijke kosten aanrekenen voor:

- groene stroom;
- warmtekrachtkoppeling, afgekort als WKK.

Deze kosten staan doorgaans op de tariefkaart of factuur en worden meestal per kWh aangerekend.

In de formules worden deze componenten aangeduid als:

- `G`: kost voor groene stroom per kWh;
- `W`: kost voor WKK per kWh.

### 3.6 Kosten voor energiedelen

Voor energiedelen kan een afzonderlijke administratieve kost worden aangerekend.
In de aangeleverde berekeningsregels wordt hiervoor een btw-tarief van 21% gebruikt.

In de formules wordt deze component aangeduid als:

- `ED`: administratiekost voor energiedelen, exclusief btw.

## 4. Nettarieven

Nettarieven dekken de kosten voor het transport en de distributie van energie.
De energieleverancier rekent deze kosten aan op de factuur en stort ze door aan de betrokken netbeheerder.

### 4.1 Distributienettarieven

Distributienettarieven dekken onder meer de aanleg, het beheer en het onderhoud van het distributienet.
De Vlaamse Nutsregulator keurt de distributienettarieven goed.

Projectlocatie voor de tariefbestanden:

```text
/TarievenDNB/Vlaanderen/<jaar>/elektriciteit/
```

Voorbeeld:

```text
/TarievenDNB/Vlaanderen/2026/elektriciteit/Distributienettarieven elektriciteit 2026.xls
```

> [!NOTE]
> Volgens de gebruikte tarieflijst zijn transmissienetkosten opgenomen in de distributienettarieven onder de tarieven voor netgebruik.
> Controleer dit per tariefbestand en jaar.

### 4.2 Transmissietarieven voor elektriciteit

Transmissietarieven dekken de kosten van het hoogspanningsnet.
Elia beheert het Belgische transmissienet en de CREG keurt de transmissietarieven goed.
Voor afnemers op het distributienet worden deze kosten via de distributienettarieven doorgerekend.

### 4.3 Transporttarieven voor aardgas

Transporttarieven dekken het vervoer van aardgas tot bij de distributienetbeheerder.
Fluxys beheert het transportnet en de CREG keurt de transporttarieven goed.

### 4.4 Capaciteitstarief

Het capaciteitstarief is een onderdeel van de nettarieven voor elektriciteit.
Een gedeelte van de nettarieven wordt berekend op basis van het gelijktijdig afgenomen vermogen.

#### Digitale meter

Voor een digitale meter wordt de maandpiek bepaald op basis van de hoogste gemiddelde afname gedurende
een kwartier in de betreffende maand. De maandpiek wordt uitgedrukt in kilowatt (`kW`).

Voor maand `m`:

```text
gefactureerde_piek_m = max(2,5 kW; gemeten_piek_m)
```

De jaarlijkse capaciteitskost is:

```text
C_totaal = som over m=1..12 van [gefactureerde_piek_m * (C / 12)]
```

Waarbij:

- `C`: capaciteitstarief in `EUR/kW/jaar`.

#### Analoge meter

Bij een analoge meter is geen gemeten maandpiek beschikbaar. De toepasselijke nettarieven worden daarom rechtstreeks
uit de klantcategorie voor een analoge meter gehaald. Als de tariefmethodologie een vaste referentiepiek van 2,5 kW gebruikt, geldt:

```text
C_totaal = 2,5 * C
```

> [!IMPORTANT]
> Vermijd dubbele aanrekening. Als de officiële tarieflijst voor een analoge meter al een aangepaste vaste term of
> een aangepast afnametarief bevat, mag niet zonder bijkomende controle nogmaals `2,5 * C` worden toegevoegd.

### 4.5 Prosumententarief

Het prosumententarief kan van toepassing zijn op eigenaars van zonnepanelen met een klassieke terugdraaiende elektriciteitsmeter.

- **Klassieke terugdraaiende meter:** prosumententarief kan van toepassing zijn.
- **Digitale meter:** geen prosumententarief volgens deze berekeningslogica.

De berekening kan afhangen van het omvormervermogen en het toepasselijke tarief van de distributienetbeheerder.

## 5. Heffingen

De federale en Vlaamse overheden heffen belastingen en bijdragen op energie. Mogelijke componenten zijn:

- energiebijdrage;
- bijzondere of federale accijns;
- bijdrage aan het Energiefonds.

Accijnzen kunnen afhangen van verbruiksschijven, bijvoorbeeld:

- van 0 tot en met 3.000 kWh;
- meer dan 3.000 tot en met 20.000 kWh;
- meer dan 20.000 tot en met 50.000 kWh;
- meer dan 50.000 tot en met 1.000.000 kWh.

In de formules worden de componenten aangeduid als:

- `Eb`: energiebijdrage per kWh;
- `Ab`: bijzondere accijns per kWh;
- `Fb`: bijdrage aan het Energiefonds per aangerekende periode.

> [!IMPORTANT]
> Heffingen met verbruiksschijven moeten progressief per schijf worden berekend.
> Eén vlak tarief op het volledige jaarverbruik is alleen correct wanneer de officiële regeling dat expliciet bepaalt.

## 6. Btw

Op de inhoudelijke referentiedatum van dit document, 26 januari 2026, wordt in de berekeningsregels uitgegaan van:

- elektriciteit: 6%;
- aardgas: 6%;
- administratiekost voor energiedelen: 21%;
- bijdrage aan het Energiefonds: vrijgesteld van btw.

Definieer de btw-factoren als configureerbare waarden:

```text
btw_energie = 1,06
btw_energiedelen = 1,21
```

> [!IMPORTANT]
> Btw-tarieven mogen niet permanent in de broncode worden vastgelegd.
> Bewaar ze bij voorkeur in versiegebonden configuratie of masterdata met een geldigheidsperiode.

## 7. Algemene symbolen en eenheden

Gebruik in implementatie en documentatie consistente eenheden:

- energie: `kWh`;
- vermogen: `kW`;
- marktprijs: `EUR/MWh`;
- consumentenprijs: `ct/kWh` of `EUR/kWh`;
- vaste vergoeding: `EUR/jaar`;
- capaciteitstarief: `EUR/kW/jaar`.

Aanbevolen symbolen:

- `kWh_afname_t`: afname in periode `t`;
- `kWh_afname_totaal`: totale afname;
- `kWh_injectie_t`: injectie in periode `t`;
- `G`: kost voor groene stroom;
- `W`: WKK-kost;
- `j`: vaste jaarlijkse vergoeding;
- `C`: capaciteitstarief;
- `A`: volumetrisch nettarief;
- `ED`: administratiekost voor energiedelen.

> [!CAUTION]
> Voer alle financiële berekeningen uit met `Decimal`.
> Zet bronwaarden eerst via hun tekstrepresentatie om en rond alleen af op duidelijk bepaalde facturatiemomenten.

## 8. Berekeningen voor een vast tarief

### 8.1 Energiekost

Voor een enkelvoudige prijs:

```text
TE_excl = prijs_vast * kWh_afname_totaal
          + G * kWh_afname_totaal
          + W * kWh_afname_totaal
          + j

TE = TE_excl * 1,06
```

Voor een dag- en nachtprijs:

```text
TE_excl = prijs_dag * kWh_afname_dag
          + prijs_nacht * kWh_afname_nacht
          + G * kWh_afname_totaal
          + W * kWh_afname_totaal
          + j

TE = TE_excl * 1,06
```

## 9. Berekeningen voor een variabel tarief

### 9.1 Digitale meter, enkelvoudig of dagtarief

Prijs per periode:

```text
p_t = a * X_t + b
```

Energiekost:

```text
TE_excl = som over t van [p_t * kWh_afname_t]
          + G * kWh_afname_totaal
          + W * kWh_afname_totaal
          + j

TE = TE_excl * 1,06
```

Nettarief:

```text
C_m = max(2,5; piek_m) * (C / 12)
C_totaal = som over m=1..12 van C_m

TN_excl = A * kWh_afname_totaal + C_totaal
TN = TN_excl * 1,06
```

Heffingen:

```text
TH_btw_plichtig = Eb * kWh_afname_totaal
                  + Ab * kWh_afname_totaal

TH = TH_btw_plichtig * 1,06 + Fb
```

Totaal:

```text
T = TE + TN + TH + ED * 1,21
```

Injectie met een vast injectietarief:

```text
T_inj = T - injectieprijs * kWh_injectie_totaal * 1,06
```

Injectie met een variabel injectietarief:

```text
T_inj = T - som over t van [injectieprijs_t * kWh_injectie_t * 1,06]
```

> [!NOTE]
> Controleer per product of de injectievergoeding inclusief of exclusief btw wordt aangeleverd en of btw volgens de toepasselijke regels
> op deze vergoeding moet worden verwerkt.

### 9.2 Digitale meter, dag- en nachttarief

```text
prijs_dag_t = a_dag * X_t + b_dag
prijs_nacht_t = a_nacht * X_t + b_nacht
```

```text
TE_excl = som over t van [prijs_dag_t * kWh_afname_dag_t]
          + som over t van [prijs_nacht_t * kWh_afname_nacht_t]
          + G * kWh_afname_totaal
          + W * kWh_afname_totaal
          + j

TE = TE_excl * 1,06
```

De formules voor nettarieven, heffingen en totaal blijven gelijk. Hierbij geldt:

```text
kWh_afname_totaal = kWh_afname_dag + kWh_afname_nacht
```

## 10. Berekeningen voor een dynamisch tarief

### 10.1 Digitale meter

Voor interval `h`:

```text
prijs_h = a * P_h + z
```

Waarbij:

- `P_h`: marktprijs in `EUR/MWh`;
- `a`: coefficient op de marktprijs;
- `z`: vaste term of opslag volgens de productformule;
- `prijs_h`: resulterende consumentenprijs, volgens de eenheid in de tariefkaart.

Energiekost:

```text
TE_excl = som over h van [prijs_h * kWh_afname_h]
          + G * kWh_afname_totaal
          + W * kWh_afname_totaal
          + j

TE = TE_excl * 1,06
```

Nettarieven, heffingen en totaal worden op dezelfde manier berekend als bij een digitale meter met een variabel product.

Dynamische injectievergoeding:

```text
T_inj = T - som over h van [injectieprijs_h * kWh_injectie_h * 1,06]
```

### 10.2 Analoge meter, benadering

Een analoge meter levert normaal geen uur- of kwartierverbruik. Een dynamische berekening is daarom alleen mogelijk via een benaderd lastprofiel.

Definieer gewichten `w_h` waarvoor geldt:

```text
som over h van w_h = 1
```

Het geschatte intervalverbruik is:

```text
kWh_afname_h = kWh_afname_jaar * w_h
```

De geschatte energiekost is:

```text
TE_excl = som over h van [prijs_h * kWh_afname_h]
          + G * kWh_afname_jaar
          + W * kWh_afname_jaar
          + j

TE = TE_excl * 1,06
```

> [!WARNING]
> Markeer het resultaat expliciet als een schatting. Een vlak profiel is eenvoudig maar niet representatief
> voor de typische verdeling van huishoudelijk of zakelijk verbruik.

## 11. Analoge meter

### 11.1 Vast tarief

Wanneer de nettariefmethodologie een capaciteitsterm van 2,5 kW voorschrijft:

```text
C_totaal = 2,5 * C
TN_excl = A_analoog * kWh_afname_totaal + C_totaal
TN = TN_excl * 1,06
```

De energiekost, heffingen en eventuele injectievergoeding worden berekend volgens dezelfde principes als bij het overeenkomstige vaste product.

### 11.2 Variabel tarief

```text
p_t = a * X_t + b
```

```text
TE_excl = som over t van [p_t * kWh_afname_t]
          + G * kWh_afname_totaal
          + W * kWh_afname_totaal
          + j

TE = TE_excl * 1,06
```

Wanneer de capaciteitsterm afzonderlijk van toepassing is:

```text
C_totaal = 2,5 * C
TN_excl = A_analoog * kWh_afname_totaal + C_totaal
TN = TN_excl * 1,06
```

Voor dag- en nachtverbruik wordt de energiecomponent afzonderlijk per register berekend.

## Verbruiksprofielen

Verbruiksprofielen worden gebruikt wanneer geen werkelijk
maand-, uur- of kwartierverbruik beschikbaar is.

Voorbeelden:

- klassieke elektriciteitsmeter;
- klassieke gasmeter;
- ontbrekende meetgegevens;
- defecte digitale meter.

Ondersteunde profielen:

- RLP0N (Real Load Profile Normalized);
- SLP-EX (Synthetisch Lastprofiel Exclusief Nacht);
- SPP (Synthetisch Productieprofiel voor PV).

Toepassing:

Digitale meter:

- gebruik werkelijke meetgegevens.

Klassieke meter:

- gebruik een gevalideerd verbruiksprofiel om het jaarverbruik over
  maanden, uren of kwartieren te verdelen.

Voor ieder profiel geldt:

SUM(gewicht_t) = 1

kWh_t = kWh_jaar × gewicht_t

## Indexatieparameters

Een variabel energiecontract gebruikt één of meerdere
indexatieparameters.

Elke parameter moet vastleggen:

- naam;
- energievorm;
- bronmarkt;
- publicatiefrequentie;
- eenheid.

Voorbeelden elektriciteit:

- EPEX DAM BE
- BELPEX Hourly
- BELPEX Day-Ahead
- Nord Pool Day-Ahead
- APX DAM

Voorbeelden aardgas:

- TTF101
- TTF103
- TTF Day-Ahead
- ZTP101
- ZTP Spot
- ZTP DAM

De indexatieparameter bepaalt enkel de energiecomponent.
Nettarieven, heffingen en btw worden onafhankelijk berekend.

## Generieke leveranciersformule

Om verschillende leveranciersproducten uniform te verwerken gebruikt
de Energievergelijker een generieke formule.

Prijs =

```text
z
+ a × A
+ b × B
+ c × C
+ d × D
```

waarbij:

z = vaste component
A-D = indexatieparameters
a-d = coëfficiënten

Niet gebruikte parameters mogen leeg zijn.

Vereenvoudigde leveranciersformules zoals:

Prijs = a × X + b

zijn een specifiek geval van bovenstaande formule.

## Datakwaliteit en fallbackregels

Ontbrekende marktprijs:

- waarschuwing genereren.

Ontbrekende indexatieparameter:

- gebruik berekende prijs van leverancier indien beschikbaar.

Ontbrekend verplicht nettarief:

- berekening stoppen.

Ontbrekend intervalverbruik:

- gebruik gevalideerd verbruiksprofiel.

Ontbrekende maandpieken:

- gebruik geschatte maandpiek.

## A. Aanbevolen testgevallen

Minimaal te voorzien:

- vast enkelvoudig tarief;
- vast dag- en nachttarief;
- variabel tarief met geldige indexwaarden;
- variabel tarief met fallbackprijs;
- dynamisch tarief met kwartierverbruik en kwartierprijzen;
- dynamisch tarief met kwartierverbruik en uurprijzen;
- dynamisch tarief zonder intervalverbruik;
- digitale meter met twaalf maandpieken;
- analoge meter zonder zonnepanelen;
- analoge terugdraaiende meter met omvormervermogen;
- ontbrekend verplicht tarief;
- ontbrekende of niet-overlappende marktprijzen;
- dubbele prijstimestamps;
- negatieve dynamische marktprijzen;
- verbruik rond grenzen van heffingsschijven;
- afzonderlijke verwerking van btw-vrijgestelde componenten.

## B. Openstaande inhoudelijke controles

De volgende punten moeten tegen officiële tariefdocumentatie en productdata
worden gevalideerd voordat de resultaten als factuurnauwkeurig worden beschouwd:

- de exacte eenheid van iedere leveranciersformule;
- de omzetting van `EUR/MWh` naar `ct/kWh` per formule;
- de tariefmethodologie voor analoge meters;
- de toepassing van minimum- en maximumtarieven;
- de progressieve verwerking van accijnsschijven;
- de btw-behandeling van injectievergoedingen;
- de btw-behandeling van alle vaste en afzonderlijke kosten;
- de behandeling van ontbrekende marktprijsintervallen;
- de selectie van een representatief standaardlastprofiel.

---
terug naar [MOC](MOC.md)
