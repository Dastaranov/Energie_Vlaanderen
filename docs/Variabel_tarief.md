# Hoe een variabel elektriciteitstarief berekend wordt
 
> Doel: begrijpen waar de cijfers op een elektriciteitsfactuur vandaan komen en hoe een variabel tarief in elkaar zit.

\---

## 1\. Basisidee: mijn elektriciteitsfactuur bestaat uit meerdere blokken

Een elektriciteitsfactuur is niet gewoon:

```text
prijs per kWh × verbruik
```

De totale factuur bestaat in grote lijnen uit vier onderdelen:

```text
Totale elektriciteitsfactuur
= energiekost leverancier
+ distributie- en transmissienettarieven
+ heffingen / bijdragen
+ btw
```

Bij een **variabel tarief** verandert vooral de **energiekost per kWh**. Dat is het deel dat gekoppeld is aan de marktprijs van elektriciteit.

De andere delen — nettarieven, capaciteitstarief, heffingen en btw — kunnen ook wijzigen, maar die worden niet rechtstreeks bepaald door mijn variabele energie-index.

\---

## 2\. Wat betekent “variabel tarief” eigenlijk?

Bij een variabel elektriciteitscontract ligt de prijs per kWh niet voor de hele contractduur vast. De prijs wordt op vaste momenten opnieuw berekend volgens een formule op de tariefkaart.

Dat gebeurt meestal:

* **maandelijks**, of
* **driemaandelijks**.

De formule ziet er vaak ongeveer zo uit:

```text
Energieprijs in c€/kWh = X × index + Y
```

Soms wordt dit op de tariefkaart weergegeven als:

```text
((INDEX × X) + Y) × btw
```

Waarbij:

* **INDEX** = marktparameter, bijvoorbeeld Belpex, EPEX DAM of Endex.
* **X** = vermenigvuldigingsfactor uit mijn contract.
* **Y** = vaste opslag uit mijn contract, meestal in c€/kWh.
* **btw** = belasting op de eindprijs.

Belangrijk: **X en Y zijn niet universeel**. Die verschillen per leverancier en per product. Ik moet dus altijd naar mijn eigen tariefkaart kijken.

\---

## 3\. Waar komt de index vandaan?

De index komt uit de groothandelsmarkt voor elektriciteit. Leveranciers kopen elektriciteit op markten waar prijzen voortdurend veranderen.

Er zijn twee grote soorten markten die vaak gebruikt worden in variabele contracten.

### 3.1 Spotmarkt / day-aheadmarkt

De spotmarkt is de kortetermijnmarkt. Elektriciteit wordt daar vandaag verhandeld voor levering morgen.

Typische indexnamen:

```text
Belpex
EPEX DAM
EPEX Day Ahead Market
```

Bij een maandelijkse spotindex wordt meestal een gemiddelde genomen van de marktprijzen binnen die maand.

Voorbeeld:

```text
Januari: gemiddelde EPEX DAM = 90 €/MWh
Februari: gemiddelde EPEX DAM = 85 €/MWh
Maart: gemiddelde EPEX DAM = 92 €/MWh
```

Als mijn contract maandelijks geïndexeerd is, krijg ik dus voor elke maand een andere energieprijs.

### 3.2 Forwardmarkt / termijnmarkt

De forwardmarkt is een markt voor toekomstige levering. Leveranciers kunnen daar elektriciteit aankopen voor een volgende maand, kwartaal of jaar.

Typische indexnamen:

```text
Endex 101
Endex 103
Endex 303
```

Een forwardprijs reageert meestal anders dan een spotprijs. Spotprijzen volgen heel kort op de actuele markt. Forwardprijzen bevatten verwachtingen over de toekomst.

\---

## 4\. Maandelijkse of driemaandelijkse indexatie

Bij een variabel contract moet ik altijd controleren hoe vaak de prijs aangepast wordt.

### Maandelijks geïndexeerd

De prijs verandert elke maand.

```text
Verbruik januari × prijs januari
+ verbruik februari × prijs februari
+ verbruik maart × prijs maart
+ ...
```

### Driemaandelijks geïndexeerd

De prijs verandert per kwartaal.

```text
Q1: januari + februari + maart aan kwartaalprijs
Q2: april + mei + juni aan kwartaalprijs
Q3: juli + augustus + september aan kwartaalprijs
Q4: oktober + november + december aan kwartaalprijs
```

Een maandcontract volgt de markt sneller. Dat kan positief zijn bij dalende prijzen, maar negatief bij stijgende prijzen.

Een kwartaalcontract reageert trager. Dat kan schommelingen wat afvlakken, maar de prijs kan ook langer hoog blijven.

\---

## 5\. Omrekening van €/MWh naar c€/kWh

Marktprijzen worden meestal gepubliceerd in:

```text
€/MWh
```

Mijn factuur rekent meestal in:

```text
c€/kWh
```

De omzetting is:

```text
1 MWh = 1.000 kWh
1 €/MWh = 0,001 €/kWh
1 €/MWh = 0,1 c€/kWh
```

Voorbeeld:

```text
80 €/MWh = 8 c€/kWh
```

Maar mijn contractuele energieprijs is meestal niet gewoon die marktprijs. De leverancier past de formule toe:

```text
Energieprijs = X × index + Y
```

Daarin zitten onder andere leverancierkosten, risico-opslag, balanceringskosten en marge verwerkt.

\---

## 6\. Voorbeeldberekening van de energiekost

Stel fictief:

```text
Index = 80 €/MWh
Formule = 0,100 × index + 2,50
Verbruik = 3.500 kWh/jaar
Vaste vergoeding leverancier = €60/jaar
```

Dan wordt de energieprijs:

```text
Energieprijs = 0,100 × 80 + 2,50
             = 8,00 + 2,50
             = 10,50 c€/kWh excl. btw
```

De jaarlijkse energiekost wordt dan:

```text
3.500 kWh × 10,50 c€/kWh = €367,50
+ vaste vergoeding        = €60,00
= €427,50 excl. btw
```

Dit is enkel de **energiekost**. Daarbovenop komen nog nettarieven, heffingen en btw.

\---

## 7\. Hoe wordt mijn verbruik verdeeld over maanden?

Dit is belangrijk bij een variabel contract, omdat de prijs per maand of kwartaal kan verschillen.

### 7.1 Met digitale meter

Met een digitale meter kan het werkelijke maandverbruik gebruikt worden.

Dan wordt de berekening veel juister:

```text
Verbruik januari × prijs januari
+ verbruik februari × prijs februari
+ verbruik maart × prijs maart
+ ...
```

Als ik in een dure maand veel verbruik, betaal ik meer. Als ik in een goedkope maand veel verbruik, betaal ik minder.

### 7.2 Met klassieke meter

Bij een klassieke meter wordt mijn meterstand meestal maar één keer per jaar opgenomen.

Dan weet de leverancier wel mijn jaarverbruik, maar niet exact hoeveel ik in elke maand heb verbruikt.

Daarom gebruikt men **gebruiksprofielen** of **lastprofielen**. Die verdelen mijn jaarverbruik statistisch over het jaar.

Voorbeelden:

* meer verbruik in de winter,
* minder verbruik in de zomer,
* verschillen tussen weekdagen, weekends en feestdagen.

Daardoor kan een deel van mijn verbruik toegewezen worden aan duurdere of goedkopere maanden, ook al is dat niet exact mijn echte verbruik.

\---

## 8\. Nettarieven

Naast de energiekost betaal ik ook nettarieven.

Die dienen voor:

* aanleg van het elektriciteitsnet,
* onderhoud van het net,
* beheer van het distributienet,
* vervoer van elektriciteit via hoogspannings- en distributienetten.

Er zijn twee grote soorten:

```text
Distributienettarieven
+ transmissienettarieven
```

### 8.1 Distributienettarieven

Distributienettarieven hebben te maken met het lokale net dat elektriciteit tot bij woningen en bedrijven brengt.

In Vlaanderen worden deze tarieven gereguleerd. Ze verschillen per netgebied.

### 8.2 Transmissienettarieven

Transmissienettarieven hebben te maken met het hoogspanningsnet. In België is Elia de beheerder van het transmissienet.

Die kosten worden doorgerekend via de elektriciteitsfactuur.

\---

## 9\. Capaciteitstarief

Sinds 2023 wordt in Vlaanderen een deel van de nettarieven aangerekend op basis van hoeveel elektriciteit ik tegelijk gebruik.

Dat heet het **capaciteitstarief**.

Het gaat dus niet alleen over:

```text
Hoeveel kWh verbruik ik?
```

maar ook over:

```text
Hoe hoog is mijn piekvermogen in kW?
```

### 9.1 Kwartierpiek

Een digitale meter meet mijn verbruik per kwartier.

De kwartierpiek is het gemiddelde vermogen tijdens een kwartier.

Voorbeeld:

```text
In 15 minuten verbruik ik 1 kWh.
```

Omdat 15 minuten gelijk is aan 0,25 uur:

```text
1 kWh / 0,25 uur = 4 kW
```

Mijn kwartierpiek is dan 4 kW.

### 9.2 Maandpiek

De maandpiek is de hoogste kwartierpiek van die maand.

Voorbeeld:

```text
Hoogste kwartierpiek januari = 3,8 kW
Hoogste kwartierpiek februari = 4,2 kW
Hoogste kwartierpiek maart = 3,5 kW
```

Die maandpieken tellen mee voor het capaciteitstarief.

### 9.3 Minimum van 2,5 kW

Iedereen betaalt minstens een bijdrage alsof de piek 2,5 kW is.

Dus zelfs als mijn werkelijke piek lager ligt, wordt voor dat onderdeel minstens 2,5 kW aangerekend.

### 9.4 Waarom bestaat het capaciteitstarief?

Het capaciteitstarief moet mensen aanzetten om grote verbruikers niet allemaal tegelijk te gebruiken.

Voorbeelden van toestellen die pieken veroorzaken:

* elektrische wagen,
* warmtepomp,
* inductiekookplaat,
* droogkast,
* wasmachine,
* vaatwasser,
* elektrische boiler.

Als ik die toestellen spreid, kan mijn piek lager blijven.

\---

## 10\. Heffingen en btw

Bovenop energie en nettarieven komen heffingen en btw.

Heffingen kunnen onder andere bestaan uit:

* federale accijnzen,
* bijdrage Energiefonds,
* kosten voor groene stroom,
* kosten voor warmtekrachtkoppeling,
* openbare dienstverplichtingen,
* andere gereguleerde bijdragen.

Daarna wordt btw toegepast.

Voor particuliere elektriciteit is de btw momenteel 6%.

\---

## 11\. Volledig fictief totaalvoorbeeld

Stel:

```text
Verbruik: 3.500 kWh
Variabele energieprijs: 10,50 c€/kWh excl. btw
Vaste vergoeding leverancier: €60
Variabele nettarieven: 10 c€/kWh
Capaciteitstarief: 3,5 kW × €53,39/kW/jaar
Heffingen: 3 c€/kWh
Btw: 6%
```

Dan wordt de berekening:

|Component|Berekening|Bedrag excl. btw|
|-|-:|-:|
|Energiekost variabel|3.500 × 10,50 c€/kWh + €60|€427,50|
|Variabele netkosten|3.500 × 10 c€/kWh|€350,00|
|Capaciteitstarief|3,5 × €53,39|€186,87|
|Heffingen|3.500 × 3 c€/kWh|€105,00|
|Subtotaal excl. btw||€1.069,37|
|Btw 6%||€64,16|
|Totaal incl. btw||**€1.133,53**|

Dit voorbeeld is fictief en gebruikt afgeronde waarden. Het dient alleen om de berekeningslogica te begrijpen.

\---

## 12\. Waar komt elk cijfer vandaan?

|Cijfer|Bron|
|-|-|
|Verbruik in kWh|Meterstanden of digitale meter|
|Verdeling per maand|Digitale maandmetingen of gebruiksprofielen|
|Index|Groothandelsmarkt, bv. Belpex, EPEX DAM of Endex|
|X en Y|Tariefkaart van mijn leverancier|
|Vaste vergoeding|Tariefkaart van mijn leverancier|
|Distributienettarieven|Gereguleerde nettarieven in mijn netgebied|
|Capaciteitstarief|Maandpieken via digitale meter of forfait bij klassieke meter|
|Transmissienettarieven|Hoogspanningsnet / Elia, gereguleerd via CREG|
|Heffingen|Federale en Vlaamse regelgeving|
|Btw|Fiscale regelgeving|

\---

## 13\. Checklist om mijn eigen factuur te controleren

Als ik mijn eigen variabel contract wil narekenen, moet ik deze gegevens verzamelen:

1. **Tariefkaart van mijn contract**

   * indexnaam,
   * indexeringsritme,
   * formule,
   * X-factor,
   * Y-waarde,
   * vaste vergoeding.
2. **Metergegevens**

   * jaarverbruik,
   * maandverbruik bij digitale meter,
   * dag/nachtverbruik indien van toepassing.
3. **Indexwaarden**

   * maand- of kwartaalwaarde van de gebruikte index.
4. **Netgegevens**

   * distributienetgebied,
   * nettarieven,
   * maandpieken voor capaciteitstarief.
5. **Heffingen en btw**

   * accijnzen,
   * bijdragen,
   * btw-percentage.

\---

## 14\. Belangrijkste conclusie

Een variabel elektriciteitstarief is dus een combinatie van twee werelden:

```text
Marktprijs elektriciteit
→ bepaalt vooral de energiekost
```

én

```text
Gereguleerde kosten
→ bepalen nettarieven, capaciteitstarief, heffingen en btw
```

De prijs die ik uiteindelijk betaal, hangt af van:

* hoeveel ik verbruik,
* wanneer ik verbruik,
* welke index mijn contract gebruikt,
* hoe vaak mijn contract geïndexeerd wordt,
* welke formule op mijn tariefkaart staat,
* mijn maandpieken,
* mijn netgebied,
* de geldende heffingen en btw.

Kort gezegd:

```text
Variabel tarief = marktindex × contractformule
Totale factuur = variabele energiekost + netkosten + heffingen + btw
```

\---

## 15\. Snelle vuistregels voor mezelf

* Een lage marktprijs betekent niet automatisch een lage factuur, want nettarieven en heffingen blijven meetellen.
* Bij een digitale meter telt mijn echte maandverbruik sterker door.
* Bij een klassieke meter wordt mijn verbruik verdeeld via profielen.
* Een hoge maandpiek kan mijn capaciteitstarief verhogen.
* De tariefkaart is het belangrijkste document om mijn energieprijs te controleren.
* De voorschotfactuur is geen exacte afrekening, maar een spreiding van verwachte kosten.
* De jaarafrekening of maandafrekening toont pas wat ik echt verschuldigd ben.

