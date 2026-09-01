---
tags: [research, api, mpc, ems]
---

# Architectuur van Publieke en Semi-Publieke Energie-API's en Model Predictive Control Platformen voor Particulieren en KMO's

De transitie naar een gedecentraliseerd en variabel energiesysteem vereist een geavanceerde integratie van data-infrastructuur en geautomatiseerde sturing. Voor zowel particuliere prosumers als kleine tot middelgrote ondernemingen (KMO's) is de toegang tot realtime en historische energiedata, gecombineerd met voorspellende sturingsalgoritmen, essentieel om energiekosten te optimaliseren, netkosten zoals het capaciteitstarief te beperken en de zelfconsumptie van lokaal gegenereerde hernieuwbare energie te maximaliseren. Dit onderzoeksrapport biedt een diepgaande analyse van de beschikbare publieke en semi-publieke Application Programming Interfaces (API's) op het niveau van distributienetbeheerders, transmissienetbeheerders en Europese marktplatforms, gecombineerd met de architectuur van Model Predictive Control (MPC) serverplatformen en Energy Management Systems (EMS).

1. Publieke en Semi-Publieke Energie-API Interfaces
Het ecosysteem van digitale energie-API's kan worden geframed binnen drie operationele lagen: distributienetdata (metermetingen en klantaansluitingen), transmissienetdata (netbelasting, frequentie en onbalans) en groothandelsmarktdata (day-ahead en intraday prijzen).

1.1 Distributienetbeheerder-API's: Fluvius (Vlaanderen)
In het Vlaamse gewest fungeert Fluvius als de centrale distributienetbeheerder die de gegevensstroom van digitale meters en AMR-meters beheert. Fluvius faciliteert geautomatiseerde gegevensontsluiting via gestandaardiseerde digitale koppelvlakken voor zowel eindgebruikers als externe dienstverleners.   

De gegevensstroom binnen het Fluvius-ecosysteem beweegt zich van de fysieke digitale meter naar het centrale platform Mijn Fluvius. De netgebruiker verleent via een digitale identificatieprocedure (itsme of eID) een expliciet mandaat aan een gekozen energiedienstverlener of activeert de API voor eigen professioneel beheer. Zodra dit mandaat is geregistreerd, genereert de Fluvius API V3 een veilige gegevensverbinding via een geauthenticeerde OAuth 2.0-omgeving naar de beheersystemen van de gebruiker of dienstverlener.   

Mijn Fluvius en de bijbehorende API V3 bieden geautomatiseerde ontsluiting van energiedata. De beschikbare datasets omvatten volumemetingen per kwartier voor elektriciteit en per uur voor gas, naast geaggregeerde dagvolumes en geregistreerde piekvermogens. Voor grootschalige AMR-meters worden tevens kwartierwaarden voor actief en reactief vermogen ontsloten.   

De toegang tot deze interfaces is onderworpen aan strikte beveiligings- en authenticatie-eisen:

Authenticatie en Autorisatie: De API maakt gebruik van het OAuth 2.0 Client Credentials Flow protocol. Na activatie op Mijn Fluvius ontvangt de organisatie inloggegevens waarmee een Bearer Token (JSON Web Token / JWT) kan worden opgehaald. Dit token identificeert de organisatie uniek en bepaalt tot welke EAN-codes het systeem toegang heeft. Het Bearer Token dient in de Authorization-header van elke API-aanvraag te worden meegegeven en moet jaarlijks worden hernieuwd.   

Certificeringsverplichting: Om een API-verbinding op te zetten, moet de aanvrager een geldig Organization Validated (OV) of Extended Validation (EV) SSL-certificaat overleggen van een erkende Certificate Authority. Domain Validated (DV) certificaten worden geweigerd. Het certificaat dient te beschikken over een KeySpec ingesteld op 'Signature', een RSA 256 ondertekeningsalgoritme en heeft een maximale geldigheid van 200 dagen.   

Contractuele Verplichtingen: Commerciële energiedienstverleners moeten een datatoegangscontract afsluiten met Fluvius en geregistreerd zijn onder toezicht van de Vlaamse Nutsregulator. KMO-netgebruikers die uitsluitend hun eigen aansluitingen beheren, kunnen via hun professionele Mijn Fluvius-account een rechtstreekse API-toegang activeren zonder commercieel dienstverlenerscontract, mits het intern beheer van eigen EAN-codes betreft.   

Mandaatstructuur: Gegevens van particulieren en KMO-eindgebruikers worden uitsluitend vrijgegeven na een digitaal mandaat. Dit mandaat wordt door de klant goedgekeurd op Mijn Fluvius en heeft een standaard geldigheid van drie jaar. Een leverancierswissel heeft geen invloed op de continuïteit van het mandaat.   

API Endpoints: De V3-architectuur ondersteunt specifieke eindpunten, zoals GET Mandate voor het verifiëren van goedgekeurde klantmandaten, GET Energy voor het opvragen van meetgegevens op EAN-niveau over een gekozen tijdsinterval, en Post Create Short URL voor het genereren van een unieke klant-onboardinglink.   

1.2 Transmissienetbeheerder-API's: Elia Open Data Portal
Elia, de Belgische transmissienetbeheerder, biedt via het Elia Open Data Portal openbare toegang tot net- en marktgegevens. Het platform maakt gebruik van de Explore API v2.1, die gebaseerd is op een RESTful Swagger/OpenAPI-specificatie.   

Het Elia-platform is publiek toegankelijk en vereist voor basistoegangen geen authenticatietokens of contractuele accreditatie. De API ondersteunt geavanceerde queryparameters zoals select, where, group_by, order_by, limit, offset en timezone, waardoor opvragingen op maat van MPC-modellen kunnen worden uitgevoerd.   

Voor dynamische energiebesturing en MPC-toepassingen zijn de volgende Elia-datasets essentieel:

Near Real-Time Onbalansprijzen (ODS080): Biedt een minuut-per-minuut weergave van de geactiveerde balanceringsenergieprijzen en de verwachte onbalansprijs binnen het lopende koppelingsinterval van 15 minuten.   

Systeemonbalans (ODS045 / ODS136-147): Geeft het actuele en verwachte onbalansvolume van het Belgische regelgebied weer, wat MPC-servers in staat stelt om te anticiperen op mogelijke piek- of dalprijzen op de balanceringsmarkt.   

Netbelasting (ODS003): Bevat kwartierwaarden van de totale fysieke belasting op het Elia-netwerk, gebruikt voor macro-economische forecasting.   

Hernieuwbare Generatieprognoses: Zowel intraday- als day-ahead voorspellingen van fotovoltaïsche energieproductie en windenergie (offshore en onshore) worden in kwartierresolutie bijgewerkt.   

Capaciteitsveilingen (ODS206 / ODS207): Bieden gestructureerde informatie over gecapaciteerde biedingen binnen het Capacity Remuneration Mechanism (CRM).   

1.3 Europese Groothandelsmarkt-API's: ENTSO-E Transparency Platform
Het ENTSO-E Transparency Platform centraliseert de Europese elektriciteitsmarktgegevens op grond van EU Verordening 543/2013. Het platform beschikt over een RESTful API die de Europese markt transparant en toegankelijk maakt voor marktdeelnemers, onderzoekers en softwareontwikkelaars.   

Beschikbare Datasets: Toegang tot day-ahead elektriciteitsprijzen per biedzone (zoals de Belgische Day-Ahead EPEX Spot prijzen), totale geaggregeerde belastingprognoses, grensoverschrijdende fysieke vermogensstromen en actuele productie per brandstoftype. Day-ahead prijzen vormen de input voor MPC-algoritmen bij het aansturen van batterijopslagsystemen en warmtepompen onder dynamische energiecontracten.   

Toegangsmechanisme: De API is kosteloos toegankelijk. Gebruikers dienen een account aan te maken op het Transparency Platform en een individuele API Token (Security Token) aan te vragen. Elke HTTP REST-aanvraag dient te worden geauthenticeerd via deze token ingevoegd in de request-parameters of headers.   

1.4 Central Clearing House en Sector-referentiedata: Atrias
Atrias fungeert als het centrale data-clearinghouse voor de Belgische energiemarkt, opgericht als een gezamenlijk initiatief van de Belgische distributienetbeheerders (Fluvius, Sibelga, ORES, Resa en Arewal).   

Het Atrias Central Market System (CMS) faciliteert de B2B-gegevensuitwisseling tussen energieleveranciers, netbeheerders en balansverantwoordelijken op basis van het MIG 6.0-protocol en de UMIG 6-standaard. Deze B2B-koppelvlakken rusten op beveiligde IPsec VPN-netwerkverbindingen, B2B SOAP Webservices (DEX- en CMS-endpoints) en geautomatiseerde sFTP-transfers. Authenticatie vereist een gekwalificeerd QWAC SSL-certificaat waarin het ondernemingsnummer van de marktpartij is verwerkt.   

Voor partijen die niet actief zijn als geregistreerde energieleverancier of balansverantwoordelijke, publiceert Atrias openbare sectordata die als referentie dienen voor voorspellingsmodellen:   

Synthetische en Genormaliseerde Belastingsprofielen (SLP / RLP): Profielen (zoals S01, S02, S10 voor elektriciteit en S01, S30 voor gas) die het genormaliseerde afnamegedrag van particulieren en KMO's zonder kwartieruitlezing beschrijven. MPC-algoritmen gebruiken deze profielen als baseline-voorspelling wanneer er geen realtime verbruiksmeting op locatieniveau aanwezig is.   

Bovennatuurlijke Verbrandingswaarde (GCV): Maandelijkse conversiefactoren (kWh/Nm³) per geaggregeerd ontvangststation (ARS) om kubieke meters aardgas om te rekenen naar fysieke energie-inhoud.   

Market Consultation Reports (MCR): Maandelijkse rapporten met residuale factoren (S88 voor gas en S89 voor elektriciteit) ter ondersteuning van portfolio-allocatieberekeningen.   

2. Model Predictive Control (MPC) Serverarchitecturen en EMS-Frameworks
Model Predictive Control (MPC) vormt de algoritmische kern van moderne Energy Management Systems (EMS). Waar klassieke regelgebaseerde systemen werken met statische 'als-dan'-regels (zoals het inschakelen van een laadpaal zodra de zonnepanelen meer dan een vastgesteld vermogen genereren), maakt MPC gebruik van een expliciet dynamisch model van de installatie. Hierbij wordt over een voortschrijdende tijdshorizon (receding horizon) een mathematisch optimalisatieprobleem opgelost, rekening houdend met verwachte prijzen, weersomstandigheden en lokaal verbruik.   

2.1 OpenEMS: Het Industrieel Open-Source EMS Framework
OpenEMS, ondersteund door de OpenEMS Association e.V., is het meest verspreide open-source framework voor energiebeheer in residentiële, KMO- en microgrid-omgevingen.   

OpenEMS is opgebouwd volgens een gedistribueerde software-architectuur die bestaat uit drie lagen:   

OpenEMS Edge: De softwarestack die lokaal draait op een ingebed platform (bijvoorbeeld een industriële Linux-controller of Raspberry Pi). Edge staat in directe verbinding met de fysieke apparatuur via industriële protocollen zoals Modbus RTU/TCP, SunSpec, REST en MQTT. Het voert de daadwerkelijke sturingslussen uit en bewaakt de systeemeisen.   

OpenEMS UI: Een realtime gebruikersinterface (gebaseerd op webtechnologieën) voor visualisatie en handmatige configuratie van het systeem op locatie of op afstand.   

OpenEMS Backend: Een schaalbaar cloud platform dat meerdere gedecentraliseerde OpenEMS Edge-systemen koppelt. Het maakt aggregatie, vlootbeheer, centrale gegevensopslag en externe monitoring via het internet mogelijk.   

Het sturingsmechanisme van OpenEMS Edge is ontworpen rond een strikte abstractielaag voor hardware (Hardware Abstraction Layer / HAL). Binnen het sturingssysteem luistert de component Ess.Power naar de cyclus-gebeurtenissen van de software. Tijdens elke cyclus verzamelt de solver alle actieve beperkingen van de verschillende beheermodules (zoals LimitActivePower of specifieke laad-/ontlaadgrenzen van de batterij). Deze beperkingen worden omgezet in een stelsel van lineaire vergelijkingen en ongelijkheden, dat door een ingebouwde solver wordt opgelost om de exacte instelpunten voor het actieve en reactieve vermogen van de omvormers te bepalen.   

De module Energy Scheduler v2 breidt deze functionaliteit uit door integratie van dynamische Time-of-Use (ToU) tarieven en voorspellingsalgoritmen. Via genetische algoritmen en lineaire programmering berekent de Scheduler optimale laad- en ontlaadschema's voor opslagsystemen en elektrische voertuigen op basis van externe markt-API's.   

2.2 Mathematische Formulering van MPC in Energiebeheer
Een MPC-server stelt op elk beslissingstijdstip t een optimalisatieprobleem op over een voorspellingshorizon N (bijvoorbeeld 96 stappen van 15 minuten voor een 24-uurs horizon).   

Doelfunctie (Cost Function)
De doelfunctie minimaliseert de totale operationele kosten over de horizon, uitgebreid met een strafterm voor netpieken om het capaciteitstarief te optimaliseren:

u 
0
​
 ,…,u 
N−1
​
 
min
​
  
k=0
∑
N−1
​
 (C 
buy
​
 (t+k)⋅P 
grid, buy
​
 (t+k)−C 
sell
​
 (t+k)⋅P 
grid, sell
​
 (t+k)+C 
deg
​
 ⋅∣P 
bat
​
 (t+k)∣)+λ⋅P 
peak
2
​
 
waarbij:

C 
buy
​
 (t+k),C 
sell
​
 (t+k): De dynamische elektriciteitsprijzen voor afname en injectie op tijdstip t+k (opgevraagd via de ENTSO-E of leveranciers-API).   

P 
grid, buy
​
 (t+k),P 
grid, sell
​
 (t+k): Het afgenomen respectievelijk geïnjecteerde vermogen op het netinvoedingspunt.

C 
deg
​
 : De marginale slijtagekost van de batterij per overgedragen kWh.

P 
peak
​
 : Het maximale kwartiervermogen dat binnen de afrekentermijn op het netinvoedingspunt wordt geregistreerd.

λ: De weegfactor die het relatieve belang van piekafvlakking binnen het optimalisatieprobleem instelt.

Systeembeperkingen (Constraints)
Vermogensbalans op het knooppunt:

P 
grid, buy
​
 (t+k)−P 
grid, sell
​
 (t+k)+P 
pv
​
 (t+k)+P 
bat, dis
​
 (t+k)−P 
bat, ch
​
 (t+k)=P 
load
​
 (t+k)+P 
ev
​
 (t+k)
Batterijdynamica en State of Charge (SoC):

SoC(t+k+1)=SoC(t+k)+(η 
ch
​
 ⋅P 
bat, ch
​
 (t+k)− 
η 
dis
​
 
P 
bat, dis
​
 (t+k)
​
 )⋅ 
E 
nom
​
 
Δt
​
 
SoC 
min
​
 ≤SoC(t+k)≤SoC 
max
​
 
Operationele Limieten:

0≤P 
bat, ch
​
 (t+k)≤P 
bat, max
​
 ,0≤P 
bat, dis
​
 (t+k)≤P 
bat, max
​
 
P 
grid, buy
​
 (t+k)≤P 
connection, max
​
 
In deze vergelijkingen stellen η 
ch
​
  en η 
dis
​
  de laad- en ontlaadrendementen voor, E 
nom
​
  de nominale batterijcapaciteit, en Δt de lengte van het tijdsinterval (bijvoorbeeld 0,25 uur).

2.3 Hiërarchische Regelstructuur binnen Microgrids
Binnen industriële KMO-sites en microgrids wordt het MPC-beheersysteem geïntegreerd binnen een hiërarchische regelstructuur met drie niveaus:   

Primaire Sturing (Local Control): Reageert binnen milliseconden. Deze laag is geïmplementeerd in de fysieke omvormers en gebruikt droop control om spannings- en frequentieafwijkingen op de lokale bus op te vangen zonder afhankelijkheid van communicatienetwerken.   

Secundaire Sturing (Grid Stabilization): Reageert binnen een tijdsbestek van seconden. Deze sturingslaag herziet de referentiepunten om de frequentie en spanning exact te herstellen naar hun nominale waarden en regelt de vermogensverdeling tussen meerdere parallelle bronnen.   

Tertiaire Sturing (MPC / EMS Server): Reageert op een tijdschaal van minuten tot uren (bijvoorbeeld elke 1 tot 15 minuten). De tertiaire MPC-server verzamelt externe API-data (prijzen van ENTSO-E, onbalans van Elia, historische metingen van Fluvius), berekent de optimale energiebalans over de voorspellingshorizon en stuurt de bijgestelde referentiepunten naar de secundaire en primaire regelaars.   

3. Vergelijkende Analyse van API's en MPC Systemen
Onderstaande tabellen bieden een gestructureerd overzicht van de publieke en semi-publieke energie-API's en de beschikbare MPC- en EMS-serverplatformen die inzetbaar zijn binnen het Belgische en Europese energielandschap voor particulieren en KMO's.

3.1 Publieke en Semi-Publieke Energie-API's
Provider / Platform	Type Access	Datatypen & Granulariteit	Authenticatie & Beveiliging	Primair Gebruiksdoel
Fluvius API V3

[cite: 3, 4, 6]

Semi-publiek (KMO & Dienstverleners)

Verbruik & injectie (15-min elec, 60-min gas), dagvolumes, piekvermogen

OAuth 2.0 (Bearer JWT), OV/EV SSL-certificaat (max 200 dagen), eID/itsme-mandaat

Geautomatiseerde historische verbruiksanalyses, facturatiecontrole, gepersonaliseerd advies

Elia Open Data Portal

[cite: 8, 11]

Publiek (Openbaar)

Minuut-onbalansprijzen (ODS080), netbelasting (ODS003), PV/Wind-prognoses

Open REST API v2.1 (Geen sleutel of certificaat vereist voor standaard queries)

Realtime MPC-sturing, onbalans-arbitrage, directe netondersteuning
ENTSO-E Transparency Platform

[cite: 15, 16]

Publiek (Na registratie)

Day-ahead prijzen per biedzone, geaggregeerde load-forecasts, grensoverschrijdende stromen

REST API met individuele API Security Token

Day-ahead economische dispatch, ToU-tariefoptimalisatie
Atrias Sector Data

[cite: 19, 23]

Publiek (Referentiedata)

Synthetische profielen (SLP/RLP), GCV-gas omrekeningswaarden, residuale factoren

Open data via webportal; B2B CMS gebruikt IPsec VPN met QWAC SSL

Baseline schattingen bij ontbreken van realtime kwartier- of uurmetingen
  
3.2 MPC- en EMS-Serverplatformen
Platform / Framework	Licentiestructuur	Architectuur & Componenten	Ondersteunde Koppelvlakken	Algoritmische Kenmerken
OpenEMS

[cite: 27, 28]

Open-source (Apache 2.0 / Association e.V.)

OpenEMS Edge (lokaal), OpenEMS UI (web/app), OpenEMS Backend (cloud)

SunSpec, Modbus RTU/TCP, REST, MQTT, digitale I/O-kaarten

Lineaire vergelijkingssolvers (Ess.Power), Energy Scheduler v2, Genetische Algoritmen

Custom MPC Frameworks (Python/MATLAB)

[cite: 24, 25]

Propriëtair / Academisch

Modulaire server (Pyomo, CVXPY, CasADi) gekoppeld aan lokale C++/Python edge-agents

Modbus TCP, OPC UA, MQTT, REST HTTP-gateways	
Convex Optimalisatie, SOCP-relaxaties, Mixed-Integer Linear Programming (MILP), Rolling Horizon

Commerciële SaaS EMS Platformen	Commercieel (SaaS)	Cloud-server gekoppeld aan propriëtaire hardware-bridge of IoT-gateway	P1-poort uitlezers, Slimme stekkers, Fabrikant-cloud API's	Machinaal leren gekoppeld aan regelgebaseerde heuristieken en day-ahead prijssturing
  
4. Strategische Integratie-architectuur en Dataflows
Om een werkend sturingssysteem op te zetten voor een KMO of residentiële prosumer, worden de externe data-API's, de centrale MPC-server en de lokale actuatoren gecombineerd in een verwerkingspijplijn.

De gegevensstroom binnen dit geïntegreerde energiebeheersysteem verloopt via vier opeenvolgende fasen:

[ EXTERNE DATA-APIS ]
   |-- ENTSO-E API  ---> Day-Ahead Prijzen
   |-- Elia API     ---> Realtime Onbalansprijzen
   |-- Fluvius API  ---> Historische Metingen (Kwartier/Uur)
   +-------------------------------------------------------------+
                                                                 |
                                                                 v
[ MPC SERVER / EMS CONTROL ENGINE ]
   |-- Forecasting Module (PV-opbrengst & Verbruiksprognoses)
   |-- Optimalisatie Engine (Receding Horizon MPC Solver)
   +-------------------------------------------------------------+
                                                                 |
                                                                 v
[ LOKALE EXECUTION & ACTUATIE (OpenEMS Edge) ]
   |-- Modbus / SunSpec / REST Protocol Vertaling
   +-------------------------------------------------------------+
                                                                 |
                                                                 v
[ FYSISCHE APPARATUUR ]
   |-- Batterijomvormers, EV Laadpalen, Warmtepompen
4.1 Datageneratie en Ingestie
Op extern niveau haalt de MPC-server automatisch de meest recente omgevings- en marktdata op. Dagelijks om 13:00 uur maakt de server een geautomatiseerde REST HTTP-call naar het ENTSO-E Transparency Platform om de day-ahead elektriciteitsprijzen voor het komende etmaal te downloaden. Parallel daaraan raadpleegt het systeem de open data-API van Elia op een continue interval (bijvoorbeeld elke 60 seconden) voor het ophalen van de actuele onbalansprijzen (ODS080) en netbelastingen (ODS003).   

Voor locaties van KMO's die beschikken over een geactiveerde Fluvius API V3-koppeling, worden historische kwartierwaarden periodiek gedownload om het interne verbruiksmodel te herkalibreren. Bij particulieren of kleinere KMO-aansluitingen waar de Fluvius API niet rechtstreeks aan het lokale EMS is gekoppeld, leest de lokale Edge-controller de P1-poort van de digitale meter in om realtime fysieke vermogensstromen te registreren.   

4.2 Voorspelling en Modelvorming (Forecasting Engine)
De verzamelde data wordt doorgevoerd naar de forecasting-module van de MPC-server:

Zonne-energieproductie: Op basis van meteorologische voorspellingen (opgevraagd via openbare weer-API's) en fysieke parameters van de PV-installatie (orientatie, hellingshoek, omvormercapaciteit) berekent het systeem het verwachte wekkromme-profiel via regressiemodellen (zoals Kernel Ridge Regression).   

Locatieverbruik: Het basiselektriciteitsverbruik van de site wordt geprojecteerd door historische kwartierwaarden te combineren met de Atrias Synthetische Belastingsprofielen (SLP/RLP).   

4.3 MPC Optimalisatie-executie
Met de voorspelde profielen, actuele batterijtoestand (SoC) en dynamische prijzen stelt de optimalisatie-engine het mathematische probleem op over de voorspellingshorizon N.   

Een ingebouwde solver (zoals CBC, GLPK of commerciële solvers als Gurobi) berekent de globale optimale vector van laad- en ontlaadvermogens. Van deze berekende tijdreeks wordt uitsluitend de eerste controlestap (u 
0
​
 , behorend bij het huidige kwartier) geëxporteerd naar de uitvoeringslaag. Bij de volgende controlecyclus (15 minuten later) herhaalt dit proces zich met verschoven horizon en bijgewerkte toestandsmetingen (receding horizon principle).   

4.4 Lokale Actuatie en Veiligheidsafhandeling
De berekende instelpunten (u 
0
​
 ) worden via een beveiligde JSON- of MQTT-verbinding naar het lokale Edge-platform (zoals OpenEMS Edge) verstuurd. OpenEMS Edge vertaalt deze wenswaarden naar fysieke veldbuscommando's:   

Via Modbus TCP / SunSpec worden de vermogenslimieten geschreven naar de batterijomvormers.   

Via OCPP (Open Charge Point Protocol) of Modbus wordt de maximale laadstroom van het wagenpark bijgestuurd.

Via SG-Ready contacten of Modbus wordt de warmtepomp aangestuurd om thermische energie op te slaan in het buffervat.

Indien de internetverbinding met de externe MPC-server uitvalt, valt OpenEMS Edge automatisch terug op een lokale regelgebaseerde noodstrategie, waardoor de fysieke veiligheid van de elektrische installatie gewaarborgd blijft.   

5. Conclusies
Het aanbod van publieke en semi-publieke energie-API's in combinatie met open-source en commerciële MPC-servers biedt een solide basis voor het realiseren van geavanceerd energiebeheer bij particulieren en KMO's.

De toegang tot data verschilt per beheerslaag. Waar groothandels- en transmissietariefdata (ENTSO-E, Elia) vrij toegankelijk zijn via moderne RESTful API's, is de toegang tot individuele distributiemeterdata (Fluvius) om privacyredenen afgeschermd achter strikte authenticatie- en autorisatieprocedures, waaronder OAuth 2.0, OV/EV SSL-certificaten en expliciete klantmandaten. KMO's met meerdere aansluitingen kunnen de Fluvius API V3 direct integreren, terwijl particulieren voor directe sturing voornamelijk zijn aangewezen op de lokale P1-poort van de digitale meter of gecertificeerde derden-dienstverleners.   

Op het vlak van sturingssoftware vormt OpenEMS het meest volwassen open-source framework voor lokale hardware-integratie en realtime actuatie. Door dit te koppelen aan een voortschrijdende MPC-optimalisatie-engine kan het energieverbruik van batterijen, laadpalen en warmtepompen continu worden afgestemd op dynamische marktprijzen, net-onbalans en capaciteitstarieven, wat leidt tot lagere energiekosten en een betere benutting van het distributienetwerk.   


fluvius.be
Hoe kan ik mijn energieverbruik online opvolgen in Mijn Fluvius?
Opent in een nieuw venster

fluvius.be
Verbruik opvolgen - Fluvius
Opent in een nieuw venster

partner.fluvius.be
Ontsluiten van verbruiksdata via API | Fluvius
Opent in een nieuw venster

fluvius.be
Meetgegevens ontsluiten via API voor professionele gebruikers - Fluvius
Opent in een nieuw venster

partner.fluvius.be
Ontsluiten meetgegevens aan energiedienstverleners via Mijn Fluvius
Opent in een nieuw venster

partner.fluvius.be
Ontsluiten meetgegevens aan energiedienstverleners via API | Fluvius
Opent in een nieuw venster

partner.fluvius.be
Energiedienstverleners | Fluvius
Opent in een nieuw venster

opendata.elia.be
API — Elia Open Data Portal
Opent in een nieuw venster

opendata.elia.be
Welcome — Elia Open Data Portal
Opent in een nieuw venster

opendata.elia.be
Incidents - Elia Open Data Portal
Opent in een nieuw venster

opendata.elia.be
Release Notes - Elia Open Data Portal
Opent in een nieuw venster

opendata.elia.be
Load on the Elia grid - Elia Open Data Portal
Opent in een nieuw venster

opendata.elia.be
106 datasets - Elia Open Data Portal
Opent in een nieuw venster

opendata.elia.be
Open Data News
Opent in een nieuw venster

apis.io
API Pricing Plans - APIs.io
Opent in een nieuw venster

fingrid.fi
European transparency platform - Fingrid
Opent in een nieuw venster

entsoe.eu
Electricity Market Transparency - ENTSO-e
Opent in een nieuw venster

github.com
asterixix/entsoe-fetch-tool: Fetching electricity market data from the ENTSO-E Transparency Platform RESTful API - GitHub
Opent in een nieuw venster

atrias.be
Atrias: Home
Opent in een nieuw venster

newsroom.accenture.com
Atrias Selects Accenture to Centralize Belgium's Energy Market Data in the Cloud
Opent in een nieuw venster

atrias.be
Onboarding - Atrias
Opent in een nieuw venster

sia-partners.com
Atrias and MIG6.0: Towards a new energy market model in Belgium - Sia Partners
Opent in een nieuw venster

atrias.be
Sector data - Atrias
Opent in een nieuw venster

arxiv.org
Efficient MPC-Based Energy Management System for Secure and Cost-Effective Microgrid Operations - arXiv
Opent in een nieuw venster

mdpi.com
Energy Management System (EMS) Based on Model Predictive Control (MPC) for an Isolated DC Microgrid - MDPI
Opent in een nieuw venster

arxiv.org
Forecasting and Optimization as a Service for Energy Management Applications at Scale
Opent in een nieuw venster

openems.io
OpenEMS Ready
Opent in een nieuw venster

openems.github.io
Introduction :: Open Energy Management System - GitHub Pages
Opent in een nieuw venster

community.openems.io
Use OpenEMS to manage a simulated microgrid - English Forum
Opent in een nieuw venster

openems.io
Seite 2 – the 100 % Energy Revolution needs a free and open source Energy Management System - OpenEMS

---
terug naar [MOC](../MOC.md)