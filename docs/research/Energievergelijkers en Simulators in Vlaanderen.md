---
tags: [research, energievergelijkers, opensource]
---

# Systematisch Overzicht van Energievergelijkers, Simulators en Open-Source Ecosystemen in Vlaanderen

De Vlaamse energiemarkt heeft zich ontwikkeld tot een complex digitaal ecosysteem waarin consumenten en bedrijven niet langer louter afhankelijk zijn van statische jaarlijkse prijsvergelijkingen. De introductie van het capaciteitstarief op 1 januari 2023, de grootschalige uitrol van digitale meters en de opkomst van dynamische energiecontracten hebben een nieuw paradigma gecreëerd. In dit landschap spelen zowel officieel gereglementeerde vergelijkers, gebouw- en renovatiesimulators, commerciële platformen als een snelgroeiend open-source ecosysteem op GitHub een cruciale rol.   

Officieel Gereglementeerde Energievergelijkers en Nettariefsimulators
De overheidsorganen en marktregulatoren in Vlaanderen en België bieden gestandaardiseerde instrumenten om contracten te vergelijken en de impact van de nettariefhervorming te modelleren.

De V-test® en V-check (VREG)
De V-test®, beheerd door de Vlaamse Regulator van de Elektriciteits- en Gasmarkt (VREG), is de officiële referentietool voor het vergelijken van elektriciteits- en aardgascontracten in Vlaanderen. Het instrument is toegankelijk voor huishoudens en kleine ondernemingen met een jaarlijks verbruik tot 100.000 kWh voor elektriciteit en 150.000 kWh voor aardgas.   

De V-test® berekent een geschatte jaarprijs op basis van de meest actuele tariefkaarten van energieleveranciers. Het systeem verwerkt diverse contractvormen, waaronder vaste contracten waarbij de prijzen gedurende de looptijd vaststaan, en variabele contracten waarbij prijzen periodiek worden geïndexeerd via specifieke marktparameters. Voor dynamische contracten baseren leveranciers zich op de dag-vooruitkoersen (spotmarkt) op de energiebeurzen, waarbij het werkelijke verbruik per uur wordt afgerekend. Om dynamische contracten nauwkeurig te analyseren, verwerkt de V-test® gedetailleerde kwartierwaarden die rechtstreeks vanuit het energieportaal van netbeheerder Fluvius geüpload kunnen worden. Daarnaast vergelijkt de V-test® terugleveringscontracten voor gezinnen met zonnepanelen, waarbij zowel vaste als variabele injectievergoedingen gecombineerd kunnen worden met afnamecontracten.   

Een vereenvoudigde variant, de V-check, voert een snelle screening uit op basis van een gemiddeld verbruiksprofiel om aan te geven of een lopend contract marktconform dan wel boven gemiddeld geprijsd is. Hoewel de V-test® een betrouwbare momentopname biedt, kan het instrument geen vooruitwerkende garanties bieden over de uiteindelijke jaarafrekening omdat toekomstige prijsschommelingen bij variabele en dynamische tarieven en afwijkende verbruikspatronen niet exact voorspeld kunnen worden. Ook historische afrekeningen herberekenen is niet mogelijk.   

De CREG Scan
Op federaal niveau biedt de Commissie voor de Regulering van de Elektriciteit en het Gas (CREG) de CREG Scan aan. Deze tool richt zich specifiek op het in kaart brengen van passieve contracten. Veel consumenten blijven jarenlang bij dezelfde leverancier op contracten die niet langer actief aan nieuwe klanten worden aangeboden. De CREG Scan vergelijkt de slapende tariefkaart van de consument met het actuele marktaanbod om het loyaliteitsverlies te kwantificeren. In tegenstelling tot commerciële vergelijkers verwerkt de CREG Scan geen tijdelijke welkomstpromoties en biedt het geen directe overstapfunctionaliteit.   

Capaciteitstarief Simulators (VREG / Fluvius / Marktpartijen)
Sinds 1 januari 2023 worden de distributienettarieven in Vlaanderen voor een belangrijk deel aangerekend op basis van de netcapaciteit (in kW) die een huishouden gebruikt, in plaats van louter het totale energieverbruik (in kWh). Dit capaciteitstarief dient om overbelasting van het elektriciteitsnet te vermijden door piekverbruik te ontmoedigen.   

Parameter	Digitale Meter	Klassieke (Analoge) Meter
Meetprincipe	
Registratie van het gemiddeld vermogen per klokkwartier (15 min).

Geen kwartier- of piekmeting mogelijk.

Maandpiek (P 
maand
​
 )	
Hoogste kwartierwaarde (in kW) gemeten binnen een kalendermaand.

Niet van toepassing.

Facturatiebasis (P 
facturatie
​
 )	
Voortschrijderend gemiddelde van de laatste 12 maandpieken.

Vast forfaitair bedrag.

Minimumgrens	
Wettelijke ondergrens van 2,5 kW (bij lagere pieken geldt 2,5 kW).

Vast ingesteld op de minimumbijdrage van 2,5 kW.

Tariefimpact	
Ca. € 53,39 / kW / jaar (excl. btw, gemiddelde richtprijs netbeheerders).

Vast nettarief op basis van de 2,5 kW grens.

Uitzonderingen	
Gezinnen met sociaal tarief betalen geen capaciteitstarief.

Gezinnen met sociaal tarief vrijgesteld.

  
De officiële VREG-simulator (simulatornieuwenettarieven.vreg.be) evenals de integratie op Mijn Fluvius stellen gebruikers in staat om op basis van hun historische kwartierwaarden uit het P1-poort- of netbeheerdersregister de exacte impact van hun verbruiksgedrag op de distributienetkosten te berekenen.   

Regionale Gebouwsimulators en Renovatietools van het VEKA
Naast markt- en nettariefvergelijkers stelt het Vlaams Energie- en Klimaatagentschap (VEKA) in samenwerking met onderzoekscentra zoals EnergyVille diverse fysische en energetische gebouwsimulators ter beschikking.   

De tool Warmtepompklaar (warmtepompklaar.be) is gebaseerd op rekenmodellen die door EnergyVille zijn ontwikkeld op basis van uitgebreide haalbaarheidsstudies. De simulator analyseert de thermische schil van een woning, waaronder de isolatiegraad van het dak, de muren, de vloer en de beglazing, om te bepalen of het afgiftesysteem geschikt is voor verwarming op lage temperatuur. Naast een technische haalbaarheidsanalyse geeft de tool een indicatieve weergave van de verwachte verbetering van de EPC-score na de installatie van een elektrische warmtepomp.   

Voor de analyse van de gebouwschil en de opwekking van hernieuwbare energie biedt het Zonnekaart Vlaanderen platform uitkomst. Dit instrument verwerkt LIDAR-hoogtegegevens en oriëntatiedata ingewonnen via overvliegtuigen om het zonne-energiepotentieel van elk dak in Vlaanderen te berekend. De rekenmodule simuleert de geschikte dakoppervlakte voor fotovoltaïsche panelen of zonneboilers, houdt rekening met schaduwinval van omliggende obakels en berekent de verwachte financiële terugverdientijd en CO₂-reductie. In het verlengde hiervan integreert Fluvius Dakinzicht netbeheerdersgegevens om thermische isolatiekwaliteiten en dakbedekkingscondities op schaal visueel in kaart te brengen.   

Het VEKA-ecosysteem omvat daarnaast de tools Test je EPC en Bereken zelf je EPC, waarmee gebouweigenaren de theoretische energiekost en het energielabel van een gebouw kunnen simuleren voorafgaand aan een formeel audit- of renovatietraject. Voor het selecteren van de juiste verwarmingstechnologie biedt de Groene Warmte Tool een vergelijkende analyse tussen hybride warmtepompen, geothermie, warmtenetten en biomassa op basis van de specifieke gebouwkarakteristieken. Al deze gegevens worden gebundeld in de Woningpas, het centrale digitale gebouwdossier dat het energetische traject van de woning op lange termijn opvolgt.   

Commerciële en Coöperatieve Verbruiks- en Vergelijkingsplatformen
Naast de overheids- en gereguleerde initiatieven bieden onafhankelijke marktpartijen en coöperaties geavanceerde simulators en monitoringsoftware aan.

Commerciële vergelijkingsplatformen zoals Mijnenergie.be, Aanbieders.be en Test-Aankoop gebruiken gepurste tariefkaarten in combinatie met commerciële promoties. In tegenstelling tot de officiële V-test® verwerken commerciële vergelijkers tijdelijke welkomstkortingen op kWh-prijzen of vaste vergoedingen rechtstreeks in de berekening van de geschatte jaarkost. Platformen zoals Mijnenergie.be bieden tevens interactieve capaciteitstarief-simulators aan waarin gebruikers specifieke huishoudelijke apparaten, zoals elektrische voertuigen of warmtepompen, kunnen selecteren om hun vermoedelijke piekvermogen en de bijbehorende netvergoeding af te lezen.   

Op het vlak van verbruiksmonitoring is EnergieID, een erkende coöperatieve onderneming uit Antwerpen, een centraal platform voor meer dan 70.000 huishoudens en kleine bedrijven. Het platform integreert rechtstreeks met de digitale meter via de API's van Fluvius, alsook met zonne-omvormers en slimme laadpalen. EnergieID normaliseert het energieverbruik op basis van graaddagen en lokale zoninstraling gecapteerd via Elia-netwerkdata, waardoor het werkelijke effect van isolatiemaatregelen of gedragsveranderingen kan worden geïsoleerd van weersinvloeden. Bovendien stelt EnergieID via GitHub de open-source bibliotheek OpenEnergyID ter beschikking, waarmee ontwikkelaars geavanceerde piekanalyses en capaciteitsdrempelberekeningen kunnen uitvoeren.   

Open-Source Software, Home Assistant Integraties en GitHub Repositories
Voor technisch onderlegde consumenten en installateurs is het zwaartepunt van energiesimulatie en piekbeheer verschoven naar open-source projecten op GitHub. Deze repositories maken het mogelijk om de fysieke P1-poort van de Vlaamse digitale meter (DSMR 5.0.2 / e-MUCS protocol) in real-time uit te lezen en automatiseringen te koppelen aan dynamische prijzen en capaciteitstarieven.   

Repository / Project	Ontwikkelaar / Maintainer	Domein & Functionaliteit	Protocol / API / Core Tech	Vlaams-Specifieke Eigenschap
homeassistant_be_electricity_prices

[cite: 18]

renaudallard	Dyn. prijsberekening & tariefvergelijking	Home Assistant Integration, Python	
Haalt tariefkaarten op van Belgische leveranciers; verwerkt capaciteitstarief-pieken en injectietarieven.

node-red-contrib-effekttariff

[cite: 21]

dirkjanfaber	Real-time peak shaving & capaciteitstarief-sturing	Node-RED, MQTT, DSMR P1	
Bevat "Flanders/Belgium" preset: 15-minuten kwartierpiekberekener met 12-maands voortschrijderend gemiddelde.

Fluvius_API

[cite: 22]

sander110419	Programmatische data-extractie uit Fluvius	Python, Azure B2C PKCE Flow, REST API	
Haalt verbruiksdata, historische kwartierpieken en injectiemetingsdata rechtstreeks op uit Mijn Fluvius.

fluvius2mqtt

[cite: 17]

smartathome	P1-telegram parser naar Home Automation	Python 3, Serial P1, MQTT	
Scalair uitlezen van DSMR 5 telegrammen (fases, kwartierwaarden, gasmeterindex) met HA Auto Discovery.

OpenEnergyID

[cite: 16]

EnergieID	Analytische Python-bibliotheek voor pieken	Python (openenergyid.capacity)	
Automatische identificatie van vermogenspieken boven de 2.5 kW drempel op tijdreeksdata.

evcc

[cite: 23]

evcc-io	Slimme laadpaalsturing & curtailment	Go, Modbus, DSMR P1, MQTT	
"Follow the Peak" algoritme gebaseerd op de Vlaamse OBIS 1.6.0 piekwaarde om overtreding van de maandpiek te vermijden.

hass-engie-be

[cite: 25]

DaanVervacke	Leveranciers-API integratie voor Engie BE	Home Assistant Custom Component	
Importeert persoonlijke tarieven, Happy Hours, EPEX dag-vooruitkoersen en specifieke capaciteitstarief-pieksensoren.

b2500-meter / HA Peak Shaving

[cite: 26]

tomquist / Community	Thuisbatterijsturing op capaciteitstarief	Home Assistant, ESPHome, DSMR	
Dynamische aansturing van plugin-batterijen op basis van de verstreken tijd binnen het lopende klokkwartier.

  
De Vlaamse digitale meters (voornamelijk merken zoals Sagemcom en Landis+Gyr uitgerold door Fluvius) verzenden P1-telegrammen volgens het e-MUCS (Belgische DSMR 5.0.2 specificatie) protocol. Open-source software leest specifieke OBIS-codes (Object Identification System) uit om sturingen te voeden. De belangrijkste OBIS-code binnen de Belgische P1-specificatie is 1-0:1.6.0, die het hoogste gemeten kwartierpiekvermogen van de lopende kalendermaand (in kW) bevat. Dit veld wordt op de eerste dag van elke kalendermaand om 00:00 uur gereset. Daarnaast rapporteert code 1-0:1.4.0 het actuele gemiddelde vermogen van het lopende kwartier, terwijl 1-0:1.7.0 en 1-0:2.7.0 respectievelijk het momentane afgenomen en ingevoerde vermogen weergeven. Het cumulatieve aardgasverbruik wordt gecapteerd via code 0-1:24.2.1.   

Algoritmes voor Piekbeheersing (Peak Shaving)
De op GitHub beschikbare integraties implementeren specifieke regelstrategieën die rekening houden met de unieke Vlaamse nettariefstructuur. In plaats van continu op een hard vermogenslimiet te begrenzen, verdelen geavanceerde Home Assistant-automatiseringen en Node-RED-nodes (node-red-contrib-effekttariff) elk klokkwartier (uu:00-uu:15, uu:15-uu:30, etc.) in twee fasen.   

Gedurende de eerste tien minuten observeert het systeem de energie-opname. Indien er een tijdelijke piek optreedt door het inschakelen van huishoudelijke apparaten, grijpt het systeem nog niet in zolang de totale kwartier-energie onder het streefbudget blijft. Tijdens de laatste vijf minuten berekent het algoritme het resterende toegestane vermogen:   

Resterend Toegestaan Vermogen (W)= 
Resterende Seconden in Kwartier
Pieklimiet (Wh)−Gerealiseerd Verbruik (Wh)
​
 ×3600
Als het benodigde huishoudelijke vermogen hoger is dan deze waarde, wordt een thuisbatterij aangestuurd om exact het verschil bij te passen, of wordt het laadvermogen van een elektrische wagen teruggeregeld.   

Een alternatieve benadering is de "Dynamic Peak Following" functionaliteit in het evcc project. Indien een huishouden er in een vroege fase van de maand niet in slaagt een piek onder de 2,5 kW te houden, en er ontstaat een geregistreerde maandpiek van bijvoorbeeld 4,8 kW, past evcc zijn instelpunt aan. De laadpaal zal vanaf dat moment de auto opladen met een vermogen dat exact aansluit bij deze reeds veroorzaakte piek van 4,8 kW. Omdat het capaciteitstarief enkel wordt afgerekend op de hoogste piek van die maand, kost het benutten van de reeds getrokken vermogensruimte de consument niets extra op de distributiefactuur.   

Synthese en Strategische Conclusie
Het landschap van energievergelijkers en simulators in Vlaanderen toont een duidelijke taakverdeling tussen regulerende instanties, marktpartijen en open-source gemeenschappen:

Op het beleids- en vergelijkingsniveau blijven de VREG V-test® en de CREG Scan de juridisch en markttechnisch neutrale ankers voor het selecteren van leverancierscontracten, hoewel ze de real-time automatisering missen die nodig is voor dynamische sturing. Voor fysische gebouwanalyses leveren VEKA en EnergyVille gedetailleerde simulatietools zoals Warmtepompklaar en de Zonnekaart, die consumenten in staat stellen om vooraf de impact van duurzame investeringen op de EPC-score en energiekosten te modelleren.   

Op dataniveau slaat EnergieID de brug tussen ruwe meetdata en klimaatgecorrigeerde analyses, terwijl het met zijn open-source rekenmodules de theoretische onderbouwing levert voor piekanalyse. Tot slot vult het open-source ecosysteem (Home Assistant, Node-RED, evcc) de operationele leemte op. Door directe interfacing met de DSMR 5 P1-poort en het verwerken van de Vlaamse nettariefparameters maken deze projecten geautomatiseerde en kostenefficiënte sturing op huishoudniveau mogelijk.   


vlaanderen.be
V-test® vergelijkt de verschillende energiecontracten en -leveranciers | Vlaanderen.be
Opent in een nieuw venster

mijnenergie.be
Simulator toont impact capaciteitstarief op energiefactuur - Mijnenergie.be
Opent in een nieuw venster

eneco.be
Capaciteitstarief berekenen en simulaties | Eneco België
Opent in een nieuw venster

cregscan.be
CREG Scan
Opent in een nieuw venster

mijnenergie.be
CREG Scan: wat is het? En kan je ermee besparen op je energiefactuur? - Mijnenergie.be
Opent in een nieuw venster

vlaamsenutsregulator.be
Capaciteitstarief - Vlaamse Nutsregulator
Opent in een nieuw venster

nieuwerkerken.be
Capaciteitstarief - Gemeente Nieuwerkerken
Opent in een nieuw venster

userbase.be
Capaciteitstarief maandpiek zichtbaar maken in home assistant - Pagina 3 - Userbase
Opent in een nieuw venster

callmepower.be
Capaciteitstarief Vlaanderen: berekenen en impact factuur (2026) - CallMePower
Opent in een nieuw venster

fluvius.be
Hoe wordt het capaciteitstarief aangerekend? - Fluvius
Opent in een nieuw venster

warmerwonen.be
Laat je woning onderzoeken en bespaar energie | Warmer Wonen
Opent in een nieuw venster

wevelgem.be
Advies en Begeleiding - Gemeente Wevelgem
Opent in een nieuw venster

smart-save.be
Batterijopslag Hasselt | BESS voor Logistiek & Transport - SmartSave
Opent in een nieuw venster

energyid.eu
Alles om je verbruik op te volgen, individueel of in groep - EnergyID
Opent in een nieuw venster

energyid.eu
About us - EnergyID
Opent in een nieuw venster

github.com
GitHub - EnergieID/OpenEnergyID: Open Source energy data analytics and simulations
Opent in een nieuw venster

github.com
smartathome/fluvius2mqtt: Fluvius smart energy meter to MQTT - GitHub
Opent in een nieuw venster

github.com
renaudallard/homeassistant_be_electricity_prices: Live Belgian electricity prices for homeassistant · GitHub
Opent in een nieuw venster

github.com
Add support for eMUCs – P1 V1.7.1 DSMR messages (peak tarrif Belgium) #2046 - GitHub
Opent in een nieuw venster

jensd.be
Read data from the Belgian digital meter through the P1 port | Jensd's I/O buffer
Opent in een nieuw venster

github.com
dirkjanfaber/node-red-contrib-effekttariff - GitHub
Opent in een nieuw venster

github.com
sander110419/Fluvius_API: Access the Fluvius (Belgian energy network operator) "public"-ish API - GitHub
Opent in een nieuw venster

github.com
Follow the peak (Belgium piektarief) · Issue #21970 · evcc-io/evcc - GitHub
Opent in een nieuw venster

github.com
Belgian capacity tarif curtailment · evcc-io evcc · Discussion #26563 - GitHub
Opent in een nieuw venster

github.com
GitHub - DaanVervacke/hass-engie-be: Home Assistant integration for ENGIE Belgium: integrates energy prices, capacity-tariff peaks, EPEX dynamic prices and Happy Hours free-energy windows.
Opent in een nieuw venster

gathering.tweakers.net
Capaciteitstarief beperken met Marstek batterij(en). - Duurzame energie en installaties - GoT
Opent in een nieuw venster

community.home-assistant.io
DSMR - monthly 15 minute peak values for Belgium - Home Assistant Community
Opent in een nieuw venster

---
terug naar [MOC](../MOC.md)
