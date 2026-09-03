# Plan: opstart en gereedheid van server, API, MCP en simulator

*Opgesteld 2026-09-03.*

Een simulator of API-server start op, haalt zijn data — bij vtest en consoorten,
of uit een bestaande databank die aan de vereisten voldoet — en pas daarna kan
hij functioneren. Dit plan beschrijft wat "voldoet aan de vereisten" precies
betekent, hoe dat gecontroleerd wordt, en wat er gebeurt als het niet zo is.

Het uitgangspunt is dat van deze week: **falen is geen optie, en stil doorrekenen
is de ergste vorm van falen.** Een server die een plausibel maar verkeerd bedrag
teruggeeft is schadelijker dan een die weigert te starten. Elke poort hieronder
is daarom een harde poort.

## Drie vragen, en ze zijn niet hetzelfde

Bij het opstarten moeten drie onafhankelijke vragen beantwoord worden. Ze door
elkaar halen is precies hoe deze week een databank vol lege prijzen ontstond.

| vraag | wat het toetst | bestaat vandaag |
|---|---|---|
| **Vorm** | Heeft de databank de tabellen en kolommen die deze code verwacht? | `alembic current` |
| **Inhoud** | Staat er in die kolommen ook iets waarmee te rekenen valt? | `db audit` |
| **Versheid** | Is die inhoud recent genoeg voor de vraag die gesteld wordt? | nog niets |

`db verify` beantwoordt een vierde, kleinere vraag: wijzen `current.txt` en de
databank naar dezelfde versie.

De vorm is de makkelijkste en de minst nuttige: een schema kan compleet zijn en
de tabellen leeg. De inhoud is wat er deze week ontbrak. De versheid is wat er
nog ontbreekt, en die is voor een langlopende server belangrijker dan voor een
CLI: een proces dat in januari opstartte rekent in december nog met de tarieven
van vorig jaar tenzij iemand dat toetst.

## Het datacontract

Er is een schemaversie (Alembic) maar geen **inhoudsversie**. Daardoor kan een
nieuwe server op een oude databank draaien: het schema klopt, de inhoud is
verouderd van vorm, en niets merkt het.

Voorstel: een `datacontract`-nummer dat de code kent en dat de databank draagt.
De importer schrijft het weg; de server eist een minimum. Wordt de betekenis van
een kolom gewijzigd — zoals `energieprijs_kwh` die nu pas gevuld wordt — dan
gaat het nummer omhoog en weigert een nieuwe server een databank die nog met de
oude importer gevuld is.

Zonder dat nummer is de enige bescherming dat iemand eraan denkt te herimporteren.

## Twee startpaden

### Warme start — de databank voldoet

De normale weg, en de enige die snel is.

```
1. schemaversie == verwachte revisie          -> anders: weigeren
2. datacontract >= minimum van deze code      -> anders: weigeren
3. precies één actieve dataversie             -> anders: weigeren
4. db audit slaagt                            -> anders: weigeren of beperkt starten
5. versheid past bij de gevraagde periode     -> anders: waarschuwen
   => klaar om te antwoorden
```

Seconden, geen netwerk, geen scrape.

### Koude start — er is nog niets

Een lege databank, of een die zakt op stap 1, 2 of 4.

```
1. schema aanmaken/migreren        alembic upgrade head
2. bronbestanden ophalen           source download / synergrid download
3. verwerken                       staging parse
4. verrijken (Selenium, traag)     staging refine
5. controleren                     audit sanity / audit golden
6. goedkeuren en publiceren        audit approve / version publish
7. inhoud toetsen                  db audit
```

Dit duurt uren en vraagt een browser. **Dat hoort geen opstartpad van een server
te zijn.** Een server die bij het booten vtest.be gaat scrapen is traag,
onbetrouwbaar en een slechte gast op een publieke dienst — de scraper pauzeert
niet voor niets tussen aanvragen.

Daarom: de koude start is een *aparte handeling* (`energievergelijker bootstrap`),
bewust gestart, niet iets wat een server zelf doet omdat hij data mist. Mist hij
data, dan weigert hij en zegt hij welk commando dat oplost.

## Wat er nooit bij het opstarten gebeurt

- **Scrapen.** Zie hierboven.
- **Migreren.** Een server die zelf `alembic upgrade` draait, wijzigt bij het
  starten de databank van een ander draaiend proces. Migreren is een handeling,
  geen opstartstap.
- **Gaten opvullen met schattingen.** Ontbreekt er een tarief, dan stopt de
  berekening — `HeffingenError` doet dat al bewust (Manifest §12). Bij het
  opstarten geldt hetzelfde: liever niet starten dan starten met gaten.

## Gedeeltelijke gereedheid

Niet alles is voor alles nodig. Weigeren te starten omdat de marktprijzen
ontbreken terwijl er alleen vaste contracten gevraagd worden, is te streng — en
te streng leidt ertoe dat mensen de poort uitzetten.

Voorstel: gereedheid **per vermogen**, niet als één vlag.

| vermogen | vereist |
|---|---|
| vaste contracten doorrekenen | tariefhistoriek met prijs, nettarieven, heffingen |
| variabele contracten | idem plus indexwaarden |
| dynamische contracten | idem plus marktprijzen voor de gevraagde periode |
| injectie | injectietarieven |
| verbruik schatten zonder meetdata | verbruiksprofielen (Synergrid) |
| contractmetadata tonen | `vtest_contract` met detailpanelen |

De server start met de vermogens die hij waar kan maken en **weigert expliciet**
de vraag die hij niet correct kan beantwoorden — met de reden erbij, niet met een
stil ander antwoord. Dat sluit aan bij `Exactheidsklasse` en `Aanname`, die al
tot in het eindbedrag meereizen.

## De data mag niet onder een lopende berekening verschuiven

Een server die `current.txt` volgt, kan midden in een berekening een andere
dataversie krijgen: de eerste deelperiode uit versie A, de tweede uit B. Dat
levert een plausibel en onverklaarbaar bedrag op.

De versie hoort dus **bij het opstarten vastgezet** te worden, en een publicatie
tijdens de looptijd is een expliciete herlaadhandeling — geen stille wissel. Een
antwoord vermeldt met welke dataversie het berekend is, zodat het reproduceerbaar
blijft.

---

## Todo's

### O1. Versheidscontrole

De derde vraag heeft nog geen antwoord. Toetsen: draagt de tariefhistoriek de
maanden die de gevraagde periode dekt, valt de peildatum binnen een bekend
heffingenregime, en is het tariefjaar van de nettarieven niet verlopen.
Vandaag rekent een periode buiten de laatste indexmaand door met de laatst
bekende waarde; `zoek_product()` stopt daar wel op, maar dat is één plek.

### O2. Datacontractnummer

Een nummer dat de importer wegschrijft en de code als minimum eist. Zonder dit
kan een nieuwe server op een oude databank draaien zonder dat iets het merkt.

### O3. `energievergelijker bootstrap`

Eén commando dat de koude start uitvoert in de juiste volgorde, met duidelijke
meldingen over wat lang gaat duren en wat een browser nodig heeft. Vandaag is
die volgorde alleen als documentatie beschikbaar en moet je zeven commando's
kennen.

### O4. Gereedheid per vermogen

`db audit` uitbreiden zodat het niet alleen "geslaagd/gefaald" zegt maar per
vermogen. De server gebruikt dat om te bepalen wat hij aanbiedt.

### O5. De poort in de startweg

De server (en straks de simulator) roept bij het opstarten de vorm-, inhoud- en
versheidscontrole aan en weigert bij een harde bevinding, met het commando dat
het oplost in de foutmelding.

### O6. Een vastgezette dataversie per proces

Bij het opstarten kiezen en vasthouden; herladen is expliciet. Elk antwoord
vermeldt de gebruikte versie.

### O7. Het opstartscherm hergebruiken

`cli/status.py::collect()` verzamelt al een deel hiervan voor de interactieve
shell. Dat is de natuurlijke plek om de drie vragen te bundelen, zodat shell,
server en simulator dezelfde controle draaien in plaats van elk hun eigen.

---

## Drie consumenten, twee vertrouwensniveaus

De API- en de MCP-server worden op termijn publiek; de simulator draait in een
gesloten omgeving en biedt méér. Dat is geen detail van uitrol maar een scheidslijn die
door het schema loopt.

De tabellen vallen al uiteen in twee families:

| familie | tabellen | aard |
|---|---|---|
| **Referentie** | `leverancier`, `energie_product`, `tarief_afname`, `tarief_injectie`, `netbeheerder_tarief`, `overheidsheffing_*`, `marktcurve`, `verbruiksprofiel_waarde`, `vtest_contract`, `gemeente`, `netbeheerder` | publiek van nature — tarieven, producten, curves |
| **Gebruikersbasis** | `gebruiker`, `gebruiker_persoonsgegeven`, `aansluitingspunt`, `meter`, `installatie_asset`, `leveringscontract`, `verbruiksopgave`, `toestemming`, `meterinterval`, `simulatie`, `simulatie_regel` | persoonsgegevens — EAN, adres, meterstanden |

**De publieke API en de MCP-server raken uitsluitend de referentiefamilie.** Dat is geen
afspraak in code maar een databankrol: de API krijgt een gebruiker met
`SELECT`-recht op die tabellen en op geen enkele andere. Een fout in de code kan
dan geen EAN lekken, want de verbinding heeft er geen recht op. Manifest §5.2
noemt de EAN expliciet gevoelig; een `WHERE`-clausule vergeten is te makkelijk om
het daarvan te laten afhangen.

De simulator draait met een rol die beide families mag lezen én de
gebruikersbasis mag schrijven.

Gevolg voor de gereedheidspoort: die verschilt per pad. De API is klaar zodra de
referentiefamilie voldoet; de simulator heeft daarnaast een leesbare
gebruikersbasis nodig.

## De MCP-server: zelfde doel, één extra risico

De MCP-server heeft hetzelfde doel als de API — publiek, alleen lezen, alleen de
referentiefamilie — en valt dus onder dezelfde rol en dezelfde gereedheidspoort.
Drie dingen komen er specifiek bij.

**De berekening mag niet naar het model verhuizen.** Zou MCP ruwe tabelrijen
teruggeven, dan telt het model ze zelf op. Dat is precies wat de regel "de
berekening komt uit de code" verbiedt, en een taalmodel dat een factuur optelt
is het tegenovergestelde van herleidbaar. De MCP-gereedschappen leveren dus
**uitgerekende resultaten**, geen rijen om mee te rekenen: "kost voor dit profiel
op deze datum", niet "geef me de tariefrijen". Ruwe SQL blootstellen is om
dezelfde reden geen optie.

**Alles wat teruggaat is invoer voor een model.** Productnamen, de
`clarification`-teksten uit vtest.be, contractvoorwaarden en tariefkaart-URL's
komen van een gescrapete website. Een model behandelt die tekst als instructie
tenzij ze als gegeven gemarkeerd is. Dat is geen theoretisch risico: die velden
worden letterlijk door leveranciers aangeleverd. Ze horen dus als data
gepresenteerd te worden, en URL's als tekst en niet als iets wat opgehaald moet
worden.

**De onzekerheid moet mee in het antwoord, niet ernaast.** Een model laat een
kanttekening makkelijk vallen wanneer die in een apart veld staat. `Exactheids-
klasse`, de gebruikte dataversie en de gedane aannames horen daarom in hetzelfde
antwoord als het bedrag — en een vraag die niet correct te beantwoorden is,
levert een weigering met reden op en geen bedrag met een voetnoot.

## Bewaarde simulaties

De server mag schrijven, de API niet. Simulaties bewaren — "hoe meer data hoe
beter" — is waardevol, maar het is wel de plek waar persoonsgegevens zich
ophopen, en het is een **ander doel** dan één factuur berekenen. Manifest §4.3
vraagt doelgebonden en minimale verwerking, dus dat tweede doel hoort
opgeschreven te staan en niet impliciet mee te liften.

Twee regels die dat werkbaar houden:

- **De-identificeren bij het schrijven, niet achteraf.** Een bewaarde simulatie
  heeft de EAN niet nodig; postcode kan naar netbeheerder, geboortejaar hoeft
  niet. Wat je niet opslaat, kan later niet lekken en hoeft niet gewist te
  worden. Achteraf anonimiseren van een tabel die al maanden vol staat is werk
  dat zelden gebeurt.
- **Een simulatie zonder herkomst is ruis.** Bewaar de dataversie, de peildatum
  en de invoer, niet alleen de uitkomst. Zonder dat is "meer data" gewoon meer
  onverklaarbare getallen, en kun je een oude simulatie niet naspelen wanneer de
  rekenregels wijzigen — precies wat je wél wil kunnen als je er later van wil
  leren.

`simulatie` en `simulatie_regel` bestaan al als tabel sinds migratie 0017, maar
worden door niets geschreven. Ze zijn dus nog vrij vorm te geven.

## Een databankdump in de repo

Voor een verse installatie zonder scrapemogelijkheid is een meegeleverde dump de
enige weg. Drie dingen bepalen of dat werkt.

**Het is geen anonimisering maar een selectie.** De referentiefamilie bevat geen
persoonsgegevens; de gebruikersbasis wel. De dump bevat dus alleen de eerste
familie. Dat is een sterkere garantie dan scrubben: er valt niets te vergeten
omdat er niets persoonlijks in gaat.

**De omvang moet ergens vandaan komen.** Eén dataversie draagt vandaag 132.540
curverijen en, met profielen, 849.720 profielwaarden. Dat is te groot om
ongefilterd in git te zetten. Keuze nodig: alleen de tarieven en producten (klein,
genoeg om een factuur te berekenen), of ook curves en profielen (nodig voor
dynamische contracten en verbruiksschatting). Een tussenweg is de dump beperken
tot één tariefjaar en de curves tot de periode die de meegeleverde
referentiefactuur dekt.

**De dump draagt het datacontractnummer.** Anders weet een server na een
`git pull` niet of de meegeleverde dump nog bij de code past — dezelfde val als
hierboven, alleen met een bestand in plaats van een server.

## Waarom er twee wegen naar dezelfde data zijn

Dit project begon zonder databank: `DataRepository` leest CSV's, en dat was
lange tijd de enige weg. De databank kwam er later bij en werd nooit door een
berekening gelezen — waardoor ze jarenlang lege prijskolommen kon dragen zonder
dat iets faalde.

De regel is nu omgekeerd en eenduidig: **de CSV-bestanden zijn een hulpmiddel om
de databank te vullen, de databank is de waarheid, en elke berekening leest uit
de databank.** Zolang beide wegen bestaan is de CSV-weg alleen nog het
controle-orakel waartegen de databankweg bewezen wordt (zie
`docs/plan databank als bron.md`, fase 3.2); daarna verdwijnt ze.

---

## Aanvullende todo's

### O8. Twee databankrollen

Een rol met alleen `SELECT` op de referentiefamilie voor de API, en een rol met
schrijfrecht op de gebruikersbasis voor de server/simulator. Plus een test die
vaststelt dat de API-rol een `SELECT` op `aansluitingspunt` niet mag.

### O9. Gereedheid per pad

`db audit` moet los kunnen rapporteren over de referentiefamilie en over de
gebruikersbasis, zodat de API kan starten wanneer alleen de eerste voldoet.

### O10. Bewaarde simulaties vormgeven

Vastleggen welke velden een bewaarde simulatie draagt, welke bewust niet, en dat
dataversie en invoer meegaan. Pas daarna `simulatie`/`simulatie_regel` vullen.

### O11. Dump exporteren en inlezen

`energievergelijker db dump` en `db restore`, beperkt tot de referentiefamilie,
met het datacontractnummer erin. Inclusief de keuze wat er wel en niet in gaat.

### O12b. MCP-gereedschappen ontwerpen

Vastleggen welke gereedschappen de MCP-server aanbiedt, elk met een uitgerekend
resultaat in plaats van ruwe rijen, met de exactheidsklasse en de dataversie in
hetzelfde antwoord. Geen ruwe SQL, geen tabeldumps.

### O12. De scheidslijn API versus simulator uitwerken

Nog open: wat biedt de publieke API precies aan, en wat blijft voorbehouden aan
de gesloten simulator. Dat bepaalt mee welke tabellen de API-rol nodig heeft.

---

## Nog open

- **Wat de publieke API precies aanbiedt** tegenover de simulator (zie O12).
- **Authenticatie en snelheidsbeperking** op de publieke API: nog niet
  uitgewerkt, maar de referentiefamilie is publieke data, dus dit gaat over
  misbruik en belasting en niet over vertrouwelijkheid.
