Plan: de core parallelliseren

Status: voorstel. Opgesteld 2026-09-01 op basis van metingen tijdens de
databankopbouw, niet op basis van een vermoeden.

## Waarom dit niet één antwoord heeft

"Alles draait single-threaded" is waar, maar de drie zware onderdelen zijn om
verschillende redenen traag. Threads helpen alleen waar de GIL wordt
losgelaten — dus bij wachten, niet bij rekenen. Dat verschil bepaalt hier
alles:

| onderdeel | duur | aard | wat helpt |
|---|---|---|---|
| matrix-scrape | ~30 min | wachten op vtest.be | threads |
| databankimport | ~15 min | 56% Python, 44% wachten op de server | eerst minder queries, dan threads |
| werkboek parsen + normaliseren | ~10 min | rekenen in pandas | processen, of pandas zelf |

De middelste is gemeten met een profiler tijdens de import: 8.427 queries voor
960 productgroepen, 13,5 van de 30,3 seconden in de databank. De rest is
Python — pandas-rijen omzetten, Decimals bouwen, dicts samenstellen.

## 1. De scrape — grootste winst, kleinste risico

`refine --matrix` doorloopt 32 combinaties, elk een volledige browsersessie
die grotendeels staat te wachten op vtest.be. Dat is puur I/O: de GIL is los
tijdens het wachten, dus threads werken hier echt.

Met vier gelijktijdige browsers zou een matrixrun van ongeveer 30 naar 8
minuten gaan. Maar er is een reden om dat niet blind te doen: **vtest.be is
een publieke dienst, geen API.** De huidige code pauzeert bewust tussen
aanvragen. Vier parallelle sessies is nog steeds bescheiden verkeer, acht is
dat niet meer.

Voorstel: `--parallel N` met standaard 1, een harde bovengrens van 4, en de
hoffelijkheidspauze behouden per worker. Elke worker een eigen
WebDriver-instantie; die zijn niet thread-safe en mogen niet gedeeld worden.

Let op bij de foutafhandeling: de matrix vangt nu per combinatie een fout op
en gaat door. Met threads moet dat blijven werken, inclusief de resume-logica
die al bestaande bestanden overslaat.

## 2. De databankimport — eerst minder werk, dan pas parallel

Hier is parallelliseren de verkeerde eerste stap. 8,8 queries per groep bij
10.188 groepen is bijna 90.000 rondreizen naar een twintig jaar oude server;
dat aantal omlaag brengen levert meer op dan ze gelijktijdig doen, en het is
veiliger.

In volgorde van opbrengst:

**a. Batch de SCD2-upserts.** Nu drie queries per tariefsnapshot: een SELECT
op de open rij, een UPDATE om ze af te sluiten, een INSERT. Voor 25.937
snapshots is dat ruim 75.000 queries. Alternatief: alle open rijen voor de
betrokken producten in één query ophalen, in Python beslissen wat afgesloten
en wat ingevoegd moet worden, en dan één `executemany` per bewerking. Dat
brengt drie queries per snapshot terug tot een handvol per batch.

Verwachte winst: het grootste deel van de 44% databanktijd, plus de
bijbehorende Python-overhead per query.

**b. Vervang de resterende `iterrows()`.** De grootste zat al in de
productlus en is weg (`to_dict("records")` in plaats van vijf keer per groep
itereren, 32 → 24 ms per groep). In `import_gemeente`,
`import_vtest_contract_en_prijzen` en `import_netbeheerder_tarieven` staan er
nog.

**c. Pas dan threads.** Met SQLAlchemy kan dat via een connection pool en
werkers per domein. Maar: de import draait nu in één transactie, wat precies
de eigenschap is die maakt dat een mislukte import de databank ongemoeid
laat. Dat opgeven voor snelheid is een slechte ruil. Parallelliseren binnen
één transactie kan niet; parallelliseren over meerdere transacties betekent
dat een gedeeltelijke import mogelijk wordt.

Als (a) en (b) de import onder de vijf minuten brengen, is (c) het niet waard.

## 3. Het parsen en normaliseren — processen, geen threads

`VTestDataNormalizer.normalize` verwerkt 42.118 rijen met een Python-lus per
rij. Dat is CPU-werk: threads winnen daar niets, want de GIL blijft vast.

Twee wegen:

- **Vectoriseren.** De meeste normalisatiestappen (kolommen hernoemen,
  Decimals bouwen, componentcodes mappen) kunnen als pandas-operaties over
  de hele kolom in plaats van rij per rij. Dat is doorgaans een orde van
  grootte sneller dan multiprocessing en houdt de code enkelvoudig. Eerst
  proberen.
- **Multiprocessing per werkblad.** Het werkboek heeft aparte bladen per jaar
  en per producttype; die zijn onafhankelijk. `ProcessPoolExecutor` met een
  worker per blad is een natuurlijke opdeling. Nadeel: DataFrames moeten
  heen en weer gebeitst worden, wat een deel van de winst opeet, en fouten
  uit een subproces zijn lastiger te herleiden.

## Wat parallellisatie hier níet mag kosten

Drie eigenschappen die deze codebase net verworven heeft en die zwaarder
wegen dan snelheid:

- **Eén transactie per import.** Een mislukte import laat de databank staan
  zoals ze stond. Dat is vandaag twee keer van pas gekomen.
- **Chronologische verwerking.** De SCD2-historiek wordt maand na maand
  opgebouwd; die volgorde is essentieel en niet parallelliseerbaar binnen één
  product. Parallelliseren mag alleen óver producten heen, nooit over
  perioden.
- **Herleidbare fouten.** Een stille fout in een worker is erger dan een
  trage import. Elke worker moet zijn fout doorgeven, niet loggen en
  doorgaan.

## Voorgestelde volgorde

1. Batch de SCD2-upserts (2a) — grootste winst, raakt de transactiegrens niet.
2. Meet opnieuw. Waarschijnlijk is de import dan snel genoeg en vervalt 2c.
3. `--parallel` op de matrix-scrape, standaard uit, maximaal 4.
4. Vectoriseer de normalizer; multiprocessing alleen als dat onvoldoende is.

Stap 1 en 3 zijn afgebakend werk. Stap 4 is een herschrijving van de
normalizer en hoort samen te gaan met de herschrijving van DataRepository en
Calculator die toch al op de planning staat.
