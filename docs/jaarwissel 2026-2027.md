# Jaarwissel 2026 → 2027

Wat er rond de jaarwissel nagekeken en aangevuld moet worden, en hoe.

Opgesteld 2026-09-01. Bedoeld om ergens in **december 2026** open te slaan en
van boven naar beneden af te werken.

## Waarom deze lijst bestaat

Bijna alle masterdata in dit project heeft een tijdsas met `geldig_vanaf` of
`jaar`. Dat is met opzet: een tarief dat wijzigt mag het oude niet
overschrijven, en een berekening voor augustus moet met het augustusregime
rekenen. De keerzijde is dat de data op 1 januari niet vanzelf meeschuift.

Wat er dan gebeurt hangt af van het bestand:

- De **accijnzen** en het **vervoerstarief** stoppen met een harde fout op een
  datum vóór hun oudste regime, maar rekenen ná de laatste ingangsdatum
  gewoon door met het laatst bekende tarief. Wijzigt er iets op 01/01/2027 en
  vult niemand het aan, dan blijft de berekening stil het tarief van 2026
  gebruiken. **Dat is de gevaarlijkste categorie: geen fout, alleen een
  verkeerd bedrag.**
- Het **energiefonds** is per kalenderjaar en heeft geen 2027-rij. Daar volgt
  wél een `HeffingenError`, en `audit heffingen` waarschuwt er nu al voor.
- De **distributienettarieven** komen uit jaarlijkse VREG-werkboeken. Zonder
  het werkboek van 2027 rekent de pipeline door met dat van 2026.

De rode draad: dit project is dertien keer gebeten door een stil verkeerd
getal, nooit door een crash. De jaarwissel is het moment waarop die hele klasse
fouten tegelijk kan terugkeren.

## Volgorde

Punt 1 tot 3 kunnen los van elkaar. Punt 4 is de afsluiting en hoort pas als de
rest binnen is.

---

## 1. Bijdrage energiefonds 2027

**Status vandaag:** dekt 2022 t/m 2026. `audit heffingen` meldt het ontbreken
van 2027 al als waarschuwing.

**Wat je nodig hebt:** de tarieftabel op vlaanderen.be, doorgaans gepubliceerd
in het najaar voor het volgende jaar.
[Tarief van de bijdrage energiefonds](https://www.vlaanderen.be/belastingen-en-begroting/vlaamse-belastingen/energieheffingen/bijdrage-energiefonds-heffing-op-afnamepunten-van-elektriciteit/tarief-van-de-bijdrage-energiefonds)

**Hoe:** voeg per klantcategorie een `[[tarief]]`-blok toe in
`config/heffingen/bijdrage_energiefonds.toml` met `jaar = 2027`. Neem de
bestaande blokken als vorm; vul `bron` in met de datum waarop je de pagina
geraadpleegd hebt.

**Let op de btw.** De pagina noemt bedragen doorgaans inclusief 6%, de
masterdata staat exclusief. Een verschil van precies factor 1,06 is een
eenheidsverwarring en geen tariefwijziging.

**Klaar wanneer:** `energievergelijker audit heffingen` de energiefonds-melding
niet meer geeft.

---

## 2. Bijzondere accijns per 01/01/2027

**Status vandaag:** elektriciteit en aardgas dragen een tijdsas. Het laatste
regime voor gezinnen begint op 01/08/2026 (46,00 EUR/MWh elektriciteit,
10,31/11,16 aardgas). Zakelijk laagspanning staat nog op het regime van
01/01/2022.

**Waarom dit het gevaarlijkste punt is:** hier komt geen waarschuwing. De
repository kiest het regime met de meest recente ingangsdatum, dus zonder
2027-rij rekent alles in 2027 gewoon door met het augustusregime van 2026. Dat
ziet er in elke uitvoer volkomen normaal uit.

**Hoe controleren — de betrouwbare weg is terugrekenen, niet opzoeken.** De
accijnzen zijn niet scrapebaar; ze zijn destijds afgeleid uit vtest.be zelf:

```bash
energievergelijker staging calibrate --version <id>    # ~13 min, Selenium
python scripts/check_tarieven.py --versie <id>
```

`calibrate` vraagt hetzelfde profiel op bij een reeks jaarverbruiken en leidt
uit VREG's eigen kostenopbouw de tariefstructuur af: elk recht stuk van de
kostenfunctie is één verbruiksschijf, de helling het tarief in EUR/MWh, een
knik een schijfgrens. `check_tarieven.py` legt het resultaat naast de config en
meldt elk verschil.

Doe dit **na 1 januari**, wanneer vtest.be met de nieuwe tarieven rekent — vóór
die datum meet je nog het regime van 2026.

**Bij een verschil:** voeg een nieuw regime toe met `geldig_vanaf = 2027-01-01`
in plaats van de bestaande schijven aan te passen. Regimes worden nooit
vermengd; een berekening over 2026 moet met 2026 blijven rekenen. Zet
`geverifieerd = true` alleen als je zelf gekalibreerd hebt, en vul `bron` met
de kalibratiedatum en het aantal meetpunten.

**Ook meenemen:** de vier schijven van `zakelijk_laagspanning` boven 20 MWh
dragen `geverifieerd = false` — ze komen uit een secundaire bron en zijn nooit
tegen vtest.be gelegd. Een kalibratie van het segment onderneming is de kans om
dat recht te zetten.

---

## 3. Nieuwe VREG-werkboeken en het vervoerstarief

### 3a. Distributienettarieven 2027

De werkboeken `Distributienettarieven elektriciteit 2027.xlsx` en
`... aardgas 2027.xlsx` verschijnen doorgaans in december.

De bronbewaking merkt ze zelf op: `.github/workflows/bronbewaking.yml` draait
dagelijks en maakt een GitHub-issue aan zodra er een bestand op de VREG-pagina
staat dat niet in `config/bronregister.toml` voorkomt. Handmatig checken kan
met:

```bash
python scripts/check_bronnen.py
```

Verwerken:

```bash
energievergelijker source download --year 2027
energievergelijker staging parse --version <id>
python scripts/check_bronnen.py --bijwerken      # pas ná de parse
```

Het register zegt "dit hebben we verwerkt", niet "dit staat online" — daarom
die volgorde.

### 3b. Vervoerstarief aardgas (Fluxys)

**Status vandaag:** 0,0015565 EUR/kWh voor woning, 0,00156 voor onderneming,
geldig vanaf 01/01/2026. CREG stelt dit jaarlijks vast per 1 januari.

Ook hier geen waarschuwing bij een gemiste wijziging: zonder 2027-rij rekent
de repository door met 2026.

De controle zit al in `scripts/check_tarieven.py` (punt 2 hierboven) — het
vervoerstarief wordt daar op vijf verbruikspunten tegen vtest.be gelegd. Wijst
dat op een verschil, zoek dan de nieuwe CREG-nota op en voeg een `[[tarief]]`
toe met `geldig_vanaf = "2027-01-01"`.

**Nota bij de bronkeuze:** sinds 2026-09-01 is vtest.be hier de leidende bron,
niet de CREG-nota. Op woningproducten past vtest 0,22% minder toe dan CREG
publiceert, om een reden die niet gevonden is. Wijkt dat percentage volgend
jaar af, dan is de eerste vraag of vtest.be zijn berekening veranderd heeft.
Zie de kop van `config/nettarieven/transport_aardgas.toml`.

### 3c. Btw

`config/heffingen/btw.toml` staat op 6% (woning) en 21% (onderneming) vanaf
01/01/2026. Een btw-wijziging op energie is politiek en komt niet stilletjes;
toch even nakijken, want het raakt elk bedrag.

---

## 4. Afsluiten: opnieuw kalibreren, importeren en toetsen

Pas als punt 1 tot 3 binnen zijn. De volledige levenscyclus:

```bash
energievergelijker source download --year 2027
energievergelijker staging parse     --version <id>
energievergelijker staging refine    --version <id> --matrix
energievergelijker staging calibrate --version <id>
energievergelijker audit sanity      --version <id>
energievergelijker audit golden      --version <id>
energievergelijker audit heffingen
energievergelijker audit approve     --version <id>
energievergelijker version publish   --version <id>
energievergelijker db verify
```

**Over de scrape:** doe `--matrix` niet in één ruk. Op 2026-09-01 leverde
vtest.be na een dag intensief scrapen zelf afgekapte resultaten — 744 producten
in plaats van 1880, zonder dat er iets misging. De matrix meldt truncatie nu
zelf (absolute ondergrens tegen de bulk-export én onderlinge vergelijking van
de postcodes), maar voorkomen is beter: verdeel de 32 combinaties over meerdere
nachten.

**Ook nakijken bij deze ronde:**

- **De standaardmaandpiek.** `geschatte_maandpiek_kw` staat op 4,218 kW, de
  waarde waarmee vtest.be zijn standaardwoning doorrekent (teruggerekend uit de
  capaciteitstarieven van alle acht netbeheerders op 2026-08-31). Verandert
  vtest zijn standaardprofiel, dan hoort dit mee. `minimum_maandpiek_kw` (2,5)
  is de wettelijke ondergrens en verandert alleen bij een tariefhervorming.
- **`db verify`** moet zeggen dat databank en `current.txt` één op één
  overeenkomen. Faalt dat met exitcode 2, dan is de publicatie niet af.

---

## Wat géén jaarwissel-werk is

Om te voorkomen dat het volgend jaar alsnog op deze lijst belandt:

- De **V-test-data** en de **energieprijscurves** zijn maandelijks, niet
  jaarlijks. Die lopen via de gewone maandelijkse ronde.
- De **marktprijzen** (ENTSO-E met energy-charts als terugval) hebben geen
  jaargrens.
- De **0,22%-afwijking** op het gastransporttarief is een bewuste keuze, geen
  openstaand punt. Ze staat gedocumenteerd en wordt niet meer gemeld.

## Nog steeds open, los van de jaarwissel

- `tariefkaart_url` en `bijzondere_voorwaarden_url` zijn nog leeg voor alle
  producten. De code werkt (`refine --met-contractdetails`); alleen de scrape
  moet slagen.
- Het segment onderneming en de gascombinaties zijn niet volledig gescrapet.
- `DataRepository` en `Calculator` worden nog herschreven; gasberekening en
  midden-/hoogspanning wachten daarop.
