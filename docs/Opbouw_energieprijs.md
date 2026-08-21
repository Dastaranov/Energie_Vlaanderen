# Opbouw energieprijs in vlaanderen (voor Particulieren en KMO).

## Waaruit bestaat de energieprijs?

Bron: 	
 - https://www.vlaamsenutsregulator.be/elektriciteit-en-aardgas/energieprijzen-en-facturen/waaruit-bestaat-de-energieprijs-voor-elektriciteit-en-aardgas
 - https://www.vlaamsenutsregulator.be/elektriciteit-en-aardgas/nettarieven/hoeveel-bedragen-de-distributienettarieven
 - https://www.vlaamsenutsregulator.be/elektriciteit-en-aardgas/nettarieven/wat-zijn-nettarieven
 - https://www.vlaamsenutsregulator.be/elektriciteit-en-aardgas/nettarieven/capaciteitstarief
 - https://www.vlaamsenutsregulator.be/elektriciteit-en-aardgas/nettarieven/prosumententarief
 - https://www.vtest.be/
 - https://www.creg.be/nl/professionals/toegang-tot-het-net/elektriciteit-transmissie/tarieven-transmissienet
		
1. De Energiekost
2. De nettarieven
3. De heffingen
4. BTW
5. Formules en berekeningen

### 1. De Energiekost

#### A. Vaste vergoeding

Energieleveranciers rekenen de vaste vergoeding aan voor administratieve kosten zoals de klantendienst, verwerken en versturen van facturen, … 
Dat wordt soms ook **de jaarlijkse vergoeding** genoemd.

#### B. Energiecomponent

De energiecomponent is de prijs die je betaalt voor de energie die je verbruikt. 
Hoeveel je betaalt voor de energiecomponent hangt dus samen met je verbruik. 
De prijs van de energiecomponent wordt uitgedrukt in eurocent per kWh.

Bij aardgas kan de energiecomponent **vast** of **variabel** zijn.
Bij elektriciteit kan de prijs ook **dynamisch** of **tijdsgebonden (Time-of-Use of ToU)** zijn.

Soorten Energiecomponenten:
	 - **vaste energiecomponent**: je betaalt een vaste prijs per kWh. (Vast tarief)
	 - **variabele energiecomponent**: je prijs verandert maandelijks of per kwartaal, volgens de indexatieparameter die gebruikt wordt in het contract. (Variabel tarief)
	 - **dynamische energiecomponent**: je prijs volgt de uur- of kwartierprijzen op de markt. (Dynamisch tarief)
			Hoeveel je zal betalen tijdens het contract, hangt af van:
		- de evolutie van de prijzen in de energiemarkt.
		- je afnameprofiel: de hoeveelheid elektriciteit die je afneemt tijdens uren (of kwartieren) waarvoor lage of hoge prijzen gelden.
	 - **tijdsgebonden energiecomponent (Time-of-Use of ToU)**: je betaalt andere prijzen voor je verbruik in verschillende vaste tijdzones. De prijs per tijdzone is een vaste of variabele prijs.
 
 ***Berekening van variabele energieprijzen***
 
 Leveranciers gebruiken een formule om de prijs te berekenen: $(a * X) + b$
	  - $X$ is de indexatieparameter (bv. een beursprijs). Leveranciers kiezen welke indexatieparameter $X$ een contract volgt.
	  - $a$ en $b$ worden bepaald door de leverancier
	  - De formule staat in de tariefkaart van elk contract en vind je ook terug in de details van een product in de V-test®.
	 Het resultaat van die formule is de prijs die je per kWh betaalt. 
 
 Dus: $(a * X) + b = €/kWh$
 Waarbij X wijzigt per:
	  - **Kwartaal**: prijs wijzigt elke 3 maand.
	  - **Maandelijks**: prijs wijzigt elke maand.
 Waarbij X een beurs volgt:
	  - **Forwardparameter**: je volgt de prijs op een beurs voor langere termijn, bijvoorbeeld voor het volgende kwartaal.
	  - **Spotparameter**: je volgt de prijs op een beurs voor de dag nadien.
  [!NOTE] De meeste leveranciers nemen het gemiddelde van de desbetreffende maand en werken dus met maandgemiddelden om transparant en stabieler te zijn.
  [!NOTE] Zie /Energiekost/indexatieparameter.csv voor een overzicht van de indexatieparameters en bijhorende beurzen.
  
#### C. Kosten groene stroom en warmtekrachtkoppeling

Leveranciers rekenen extra kosten aan voor **groene stroom** en **warmtekrachtkoppeling (WKK )**.
Deze kosten zijn terug te vinden op je tariefkaart of factuur.

#### D. Kosten voor Energiedelen

Voor energiedelen kan er een afzonderlijke kosten worden aangerekend, jaarlijks en aan 21% BTW

### 2. De nettarieven

De nettarieven worden aangerekend door de verschillende distributienetbeheerders.
Er bestaan dire verschillende nettarieven:

 - **distributienettarieven**
	Distributienettarieven betaal je om elektriciteit of aardgas via het distributienet tot bij jou te brengen. 
	Je betaalt Fluvius via je energieleverancier voor de aanleg en het onderhoud van het distributienet. 
	De Vlaamse Nutsregulator keurt de distributienettarieven goed.
	
	Zie tarieflijsten /TarievenDNB/Vlaanderen/2026/elektriciteit/Distributienettarieven elektriciteit 2026.xls
	De tarieflijst omvat de distributienettarieven inclusief de transmissienetkosten. De transmissienetkosten zijn opgenomen onder 'Tarieven voor het netgebruik'.
	
		Bestaat uit:
		**Elektriciteit**
			- Capaciteitstarief (zie A)
			- Afnametarief
			- Maximumtarief: Is de som van Capaciteitstarief en Afnametarief hoger dan het Maximumtarief, dan betaal je het maximumtarief.
			- Tarief Databeheer
			- *Prosumententarief* (zie B)
			- *Excl nacht*
		**Aardgas**
		- Er zijn 3 verbruikscategorieën. Je betaalt een vast bedrag en een afnametarief. Die tarieven hangen af van de verbruikscategorie waartoe je behoort:
			- T1: aardgasverbruik tussen 0 en 5.000 kWh per jaar.
			- T2: aardgasverbruik tussen 5.001 tot 150.000 kWh per jaar.
			- T3: aardgasverbruik tussen 150.001 tot 1.000.000 kWh per jaar.
		- Tarief Databeheer
	
 - **transmissietarieven** (Elektriciteit)
	Transmissienettarieven dekken de kosten om elektriciteit over het transmissienet tot bij grote bedrijven, aangesloten op dat net, 
	en de distributienetbeheerder te brengen. Deze worden aan gezinnen en bedrijven, aangesloten op het distributienet, 
	doorgerekend via de distributienettarieven. Elia beheert het transmissienet. De CREG keurt de transmissienettarieven goed.
	
 - **transporttarieven** (Aardgas)
	Transportnettarieven betaal je om aardgas over het transportnet tot bij de distributienetbeheerder te brengen. 
	Fluxys beheert het transportnet. De CREG keurt de transporttarieven goed. 
 
 [!NOTE] De verschillende nettarieve zijn terug te vinden op /TarievenDNB
 
#### A. Capaciteitstarief

Het capaciteitstarief is een deel van de nettarieven op de elektriciteitsfactuur.
Je betaalt een stuk van de nettarieven niet langer per kWh, maar op basis van hoeveel elektriciteit je tegelijk gebruikt (je piekvermogen).

**Digitale meter**: Het capaciteitstarief wordt berekend op basis van de hoogste kwartierpiek van je elektriciteitsverbruik in een maand. 
Wat is de hoogste (kwartier)piek? Dat is de hoogste gemiddelde hoeveelheid elektriciteit die je in 15 minuten hebt afgenomen van het net. 
De hoogste piek wordt uitgedrukt in kilowatt (kW).

	 - **Maandpiek**: De netbeheerder meet elke 15 minuten je verbruik. Hij gebruikt de hoogste kwartierpiek in die maand om je capaciteitstarief te bepalen. 
		De kwartierpiek (in kW) is je **gemiddeld verbruik in die 15 minuten**. Wanneer we spreken over de maandpiek, dan gaat het eigenlijk over de hoogste kwartierpiek. 
		De kosten voor het capaciteitstarief worden berekend op basis van je maandpiek.
	 - Kosten per kilowatt: Wat betaal je per kilowatt (kW) voor het capaciteitstarief? 
		Voor 2026 is de gemiddelde kostprijs voor 1 kW:
		- op jaarbasis ongeveer 53,39 euro (excl. btw).
		- op maandbasis is dat 4,45 euro (excl. btw). 
			Dat bedrag kan verschillen per netbeheerder.
	 - Minimum bijdrage: Iedereen betaalt een minimumbijdrage. Die bijdrage komt overeen met een piek van 2,5 kW. 
		Zelfs als je hoogste piek lager is. Zo draagt iedereen bij aan de kosten voor de aanleg en het onderhoud van het elektriciteitsnet, 
		want het elektriciteitsnet ligt er voor iedereen.
	
**Analoge meter**
Hierbij betaal je een vast bedrag, op basis van een geschatte **maandpiek van 2,5kW**.
Omdat je enkel de minimumbijdrage betaalt, betaal je wel een hoger afnametarief dan met een digitale meter.

#### B. Prosumententarief

Het prosumententarief is een onderdeel van de distributienettarieven voor zonnepaneleneigenaars met een klassieke (terugdraaiende) elektriciteitsmeter.
	 - **Klassieke meter**: Als je zonnepanelen én een terugdraaiende teller hebt, betaal je het prosumententarief.
	 - **Digitale meter** : Je betaalt geen prosumententarief als je een digitale meter hebt.
 
Er zijn 2 factoren die het tarief bepalen:

	 - het hangt af van het netgebied waar je woont;
	 - het wordt berekend op het maximale AC-vermogen van de omvormer(s) van de installatie (in kW).

### 3. Heffingen
 
De federale overheid en de Vlaamse overheid heffen een aantal belastingen op je energie:
	 - energiebijdrage
	 - bijzondere accijns (ook federale accijns genoemd)
			- Verbruik tussen 0 kWh en 3.000 kWh
			- Verbruik tussen 3.000 kWh en 20.000 kWh
			- Verbruik tussen 20.000 kWh en 50.000 kWh
			- Verbruik tussen 50.000 kWh en 1.000.000 kWh
	 - bijdrage Energiefonds (vrijgesteld van BTW)
 
### 4. BTW

Op moment van schrijven (26/01/2026) bedraagt het BTW-tarief in Vlaanderen 6%.
Dus:
	 - Aardgas: 6%
	 - Elektriciteit: 6%
	 - *Administratiekost Energiedelen: 21%*
 
 BTW wordt betaald op alle componenten van de factuur, tenzij expliciet anders vermeld (bv. bijdrage Energiefonds).

### 5. Formules en Berekeningen

#### Vast tarief

	**Formule A (Digitale meter - Enkelvoudig of Dag): **
		- Energiekost
			- Jaarlijkse vergoeding (j)				€/jaar (6% BTW)
			- Energiecomponent afname (a)			c€/kWh (6% BTW)
			- Groenestroom (G)						c€/kWh (6% BTW)
			- WKK (W)								c€/kWh (6% BTW)
		- Nettarief
			- Capaciteitstarief (C)					€/kW/jaar (6% BTW)
			- Afnametarief (A)						c€/kWh (6% BTW)
		- Heffingen
			- Energiebijdrage (Eb)					c€/kWh (6% BTW)
			- bijzondere accijns (Ab)				c€/kWh (6% BTW)
			- bijdrage energiefonds (Fb) 			€/maand (vrijgesteld van BTW)
		- Optie Energiedelen (ED)					€/jaar (21% BTW)
		- Energiecomponent injectie (i)				c€/kWh (6% BTW)
		
		Dit is een poging om het geheel in een begrijpbare formule te gieten.
		We gaan uit van een verbruiksperiode van 1 jaar (365 dagen) en de verbruiksperiode ligt in hetzelfde jaar.
		We hebben 2 meterstanden en één piekmeting per maand: kWh(afname), kWh(injectie) en piek (minimum 2,5kW).
			- kWh(afname) = stand(opname) - stand(opname - 1 jaar)
			- kWh(injectie) = stand(opname) - stand(opname - 1 jaar)
		
		Berekening Totaal Energiekost (TE)
			$$
			**TE_excl** = {((a x kWh(afname)) + (G x kWh(afname)) + (W x kWh(afname)) + j)}
			**TE** = TE_excl x 1,06
			$$
		Berekening Totaal Nettarief (TN)
			Eerst berekening van Ctotaal:
			$$
				- C_1 = piek van maand 1 x (C / 12)
				- C_2 = piek van maand 2 x (C / 12)
				- C_3 = piek van maand 3 x (C / 12)
				- ...
				- C_12 = piek van maand 12 x (C / 12)
				- C_totaal = C1 + C2 + C3 + ... + C12
			**TN_excl** = {((A x kWh(afname)) + C_totaal)}
			**TN** = TN_excl x 1,06
			$$
		Berekening Totaal Heffingen (TH)
			$**TH_excl** = ((Eb x kWh(afname)) + (Ab x kWh(afname)))$
			$**TH** = TH_excl x 1,06 + (Fb x aantal maanden)$
			
		Totaal $T = TE + TN + TH + (ED x 1,21)$ (incl BTW)
		Totaal $T_inj = T - (i x kWh(injectie))
		

	**Formule B (Digitale meter - Tweevoudiguurtarief of Dag/Nacht)**

	- Energiekost
	  - Jaarlijkse vergoeding (j)                    €/jaar (6% BTW)
	  - Energiecomponent afname dag (a_dag)          c€/kWh (6% BTW)
	  - Energiecomponent afname nacht (a_nacht)      c€/kWh (6% BTW)
	  - Groenestroom (G)                             c€/kWh (6% BTW)
	  - WKK (W)                                      c€/kWh (6% BTW)

	- Nettarief
	  - Capaciteitstarief (C)                        €/kW/jaar (6% BTW)
	  - Afnametarief (A)                             c€/kWh (6% BTW)
	  - (Optioneel) Maximumtarief (M)                (zoals in tarieflijst DNB)

	- Heffingen
	  - Energiebijdrage (Eb)                         c€/kWh (6% BTW)
	  - Bijzondere accijns (Ab)                      c€/kWh (6% BTW)
	  - Bijdrage energiefonds (Fb)                   €/maand (vrijgesteld van BTW)

	- Optie Energiedelen (ED)                        €/jaar (21% BTW)

	- Energiecomponent injectie (i)                  c€/kWh (6% BTW)

	We gaan uit van een verbruiksperiode van 1 jaar (365 dagen) en de verbruiksperiode ligt in hetzelfde jaar.
	We hebben 3 meterstanden en één piekmeting per maand: kWh(afname_dag), kWh(afname_nacht), kWh(injectie) en piek (minimum 2,5kW).

	- kWh(afname_dag)     = stand(opname_dag)   - stand(opname_dag   - 1 jaar)
	- kWh(afname_nacht)   = stand(opname_nacht) - stand(opname_nacht - 1 jaar)
	- kWh(afname_totaal)  = kWh(afname_dag) + kWh(afname_nacht)
	- kWh(injectie)       = stand(injectie) - stand(injectie - 1 jaar)  (indien aparte injectiemeting)
	- piek_m              = hoogste kwartierpiek in maand m (minimum 2,5 kW)

	Berekening Totaal Energiekost (TE)
	TE_excl = (a_dag * kWh(afname_dag))
			+ (a_nacht * kWh(afname_nacht))
			+ (G * kWh(afname_totaal))
			+ (W * kWh(afname_totaal))
			+ j
	TE = TE_excl * 1,06

	Berekening Totaal Nettarief (TN)
	Eerst berekening van Ctotaal (met maandpieken):

	- C_1  = max(2,5 ; piek_1)  * (C / 12)
	- C_2  = max(2,5 ; piek_2)  * (C / 12)
	- ...
	- C_12 = max(2,5 ; piek_12) * (C / 12)

	C_totaal = C_1 + C_2 + ... + C_12

	TN_excl = (A * kWh(afname_totaal)) + C_totaal

	(Optioneel: Maximumtarief)
	Indien je DNB-tarieflijst een maximummechanisme heeft:
	- Als (A * kWh + C_totaal) > M, dan geldt TN_excl = M
	- Anders blijft TN_excl zoals berekend.

	TN = TN_excl * 1,06

	Berekening Totaal Heffingen (TH)
	TH_excl = (Eb * kWh(afname_totaal)) + (Ab * kWh(afname_totaal))
	TH = (TH_excl * 1,06) + (Fb * aantal maanden)

	Totaal (incl BTW)
	T = TE + TN + TH + (ED * 1,21)

	Totaal met injectie (incl BTW)
	T_inj = T - (i * kWh(injectie) * 1,06)



#### Variabel tarief

Bij variabele energiecontracten wordt de energiecomponent periodiek herberekend met een leveranciersformule:
p_t = (a * X_t) + b
waarbij:
- X_t = indexatieparameter voor periode t (maand of kwartaal)
- a en b = parameters van de leverancier
- p_t = energiecomponent (€/kWh of c€/kWh) voor periode t

BELANGRIJK:
- Om exact te rekenen heb je verbruik per periode nodig (kWh_t).
- Als je enkel jaarverbruik hebt, moet je dat verdelen over periodes via een (maand/kwartaal) verbruiksprofiel of maak je een benadering (bv. gemiddelde index).


**Formule VA (Digitale meter - Enkelvoudig/Dag - Variabel)**


Definities:
- a_t = (a * X_t) + b
- kWh(afname)_t = afname in periode t
- kWh(afname_totaal) = som over alle periodes

Berekening Totaal Energiekost (TE)
TE_excl = SUM_over_t( a_t * kWh(afname)_t )
        + (G * kWh(afname_totaal))
        + (W * kWh(afname_totaal))
        + j
TE = TE_excl * 1,06

Berekening Totaal Nettarief (TN)  (digitale meter = maandpiek)
- C_m = max(2,5 ; piek_m) * (C / 12)  voor m=1..12
- C_totaal = SUM_over_m(C_m)

TN_excl = (A * kWh(afname_totaal)) + C_totaal
TN = TN_excl * 1,06

Berekening Totaal Heffingen (TH)
TH_excl = (Eb * kWh(afname_totaal)) + (Ab * kWh(afname_totaal))
TH = (TH_excl * 1,06) + (Fb * aantal maanden)

Totaal (incl BTW)
T = TE + TN + TH + (ED * 1,21)

Totaal met injectie
- Als injectietarief vast is: T_inj = T - (i * kWh(injectie) * 1,06)
- Als injectietarief variabel is: i_t per periode
  T_inj = T - SUM_over_t( i_t * kWh(injectie)_t * 1,06 )


-------------------------
Formule VB (Digitale meter - Dag/Nacht - Variabel)
-------------------------

Definities (mogelijk 1 of 2 leveranciersformules):
- a_dag,t   = (a_dag * X_t) + b_dag    (of zelfde formule als nacht)
- a_nacht,t = (a_nacht * X_t) + b_nacht

Berekening Totaal Energiekost (TE)
TE_excl = SUM_over_t( a_dag,t   * kWh(afname_dag)_t )
        + SUM_over_t( a_nacht,t * kWh(afname_nacht)_t )
        + (G * kWh(afname_totaal))
        + (W * kWh(afname_totaal))
        + j
TE = TE_excl * 1,06

Nettarief, Heffingen, Totaal
- identiek aan Formule B (digitale meter), met:
  kWh(afname_totaal) = kWh(afname_dag) + kWh(afname_nacht)


----------------------------------------
#### Dynamisch tarief
----------------------------------------

Bij dynamische contracten volgt de energiecomponent de marktprijs per uur (of kwartier).
De totale kost hangt af van:
- marktprijzen per uur/kwartier
- je afnameprofiel (wanneer je verbruikt)

-------------------------
Formule DA (Digitale meter - Enkelvoudig - Dynamisch)
-------------------------

Notatie:
- h = uur (of kwartier) in het jaar
- P_h = marktprijs op uur h (€/kWh)
- m = marge/markup leverancier (€/kWh) (vast of variabel)
- a_h = energiecomponent op uur h = P_h + m
- kWh(afname)_h = afname op uur h (uit digitale meter)

Berekening Totaal Energiekost (TE)
TE_excl = SUM_over_h( a_h * kWh(afname)_h )
        + (G * kWh(afname_totaal))
        + (W * kWh(afname_totaal))
        + j
TE = TE_excl * 1,06

Nettarief (TN) (digitale meter = maandpiek)
- C_m = max(2,5 ; piek_m) * (C / 12)
- C_totaal = SUM_over_m(C_m)
TN_excl = (A * kWh(afname_totaal)) + C_totaal
TN = TN_excl * 1,06

Heffingen (TH)
TH_excl = (Eb * kWh(afname_totaal)) + (Ab * kWh(afname_totaal))
TH = (TH_excl * 1,06) + (Fb * aantal maanden)

Totaal (incl BTW)
T = TE + TN + TH + (ED * 1,21)

Injectie bij dynamisch (optioneel)
- Indien injectievergoeding ook dynamisch is:
  i_h (€/kWh) per uur h
  T_inj = T - SUM_over_h( i_h * kWh(injectie)_h * 1,06 )


========================================================
NIEUW: ANALOGE METER (klassieke meter) — Vast/Variabel/Dynamisch
========================================================

Bij een analoge meter betaal je een vast bedrag voor het capaciteitstarief op basis van een geschatte maandpiek van 2,5 kW (minimumbijdrage).
Daarom nemen we voor elke maand: piek_m = 2,5 kW.

----------------------------------------
Analoge meter — Vast tarief
----------------------------------------

Formule A' (Analoge meter - Enkelvoudig - Vast)

Capaciteitstarief:
C_totaal = SUM_over_m( 2,5 * (C / 12) ) = 2,5 * C

Nettarief:
TN_excl = (A_analoog * kWh(afname_totaal)) + (2,5 * C)
TN = TN_excl * 1,06

Energiekost (TE), Heffingen (TH), Totaal (T) en injectie (T_inj):
- identiek aan Formule A (enkelvoudig), maar met TN zoals hierboven.
- Gebruik A_analoog indien DNB-tarieflijst een ander afnametarief heeft voor analoge meter.

Formule B' (Analoge meter - Dag/Nacht - Vast)

- kWh(afname_totaal) = kWh(afname_dag) + kWh(afname_nacht)
- C_totaal = 2,5 * C
TN_excl = (A_analoog * kWh(afname_totaal)) + (2,5 * C)
TN = TN_excl * 1,06

TE/TH/T/T_inj:
- identiek aan Formule B, maar met bovenstaande TN.


----------------------------------------
Analoge meter — Variabel tarief
----------------------------------------

Formule VA' (Analoge meter - Enkelvoudig - Variabel)

Energiecomponent per periode:
a_t = (a * X_t) + b

TE_excl = SUM_over_t( a_t * kWh(afname)_t )
        + (G * kWh(afname_totaal))
        + (W * kWh(afname_totaal))
        + j
TE = TE_excl * 1,06

Capaciteit:
C_totaal = 2,5 * C

TN_excl = (A_analoog * kWh(afname_totaal)) + (2,5 * C)
TN = TN_excl * 1,06

TH en T:
- zoals bij variabel (digitale meter), maar met TN zoals hierboven.

Formule VB' (Analoge meter - Dag/Nacht - Variabel)
- analoog aan Formule VB (digitale meter), maar:
  C_totaal = 2,5 * C
  TN_excl = (A_analoog * kWh(afname_totaal)) + (2,5 * C)


----------------------------------------
Analoge meter — Dynamisch tarief (BELANGRIJKE NUANCE)
----------------------------------------

Dynamisch tarief vereist uur- of kwartierverbruik. Met een analoge meter heb je meestal enkel jaarstanden, dus geen exacte berekening.
Optioneel kan je een BENADERING doen met een standaard lastprofiel (w_h), waarbij:
- SUM_over_h(w_h) = 1
- kWh(afname)_h = kWh(afname_jaar) * w_h

Formule DA' (Analoge meter - Dynamisch - Benadering)

a_h = P_h + m
kWh(afname)_h = kWh(afname_jaar) * w_h

TE_excl = SUM_over_h( a_h * kWh(afname)_h )
        + (G * kWh(afname_jaar))
        + (W * kWh(afname_jaar))
        + j
TE = TE_excl * 1,06

TN_excl = (A_analoog * kWh(afname_jaar)) + (2,5 * C)
TN = TN_excl * 1,06

TH en T:
- zoals dynamisch (digitale meter), maar met bovenstaande TN.


