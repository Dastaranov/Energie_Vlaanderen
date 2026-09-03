---
name: tariefcontrole
description: Controleer of de tarieven, heffingen en nettarieven in dit repo nog kloppen door ze terug te rekenen uit vtest.be. Gebruik bij "kloppen de tarieven nog", "controleer de heffingen", "is er nieuwe VREG-data", "waarom wijkt mijn berekening af van vtest.be", na het inlezen van een nieuwe dataversie, of wanneer de bronbewaking een issue aanmaakte.
---

# Tariefcontrole

Deze skill beschrijft hoe je vaststelt of de cijfers in dit repo nog
overeenkomen met de werkelijkheid — en hoe je ze bijwerkt als dat niet zo is.

## Waarom terugrekenen en niet overschrijven

`config/heffingen/*.toml` is handgeschreven masterdata. Er is geen API die
zegt "de bijzondere accijns bedraagt vandaag X". Wat er wel is: vtest.be, de
officiële vergelijkingstool van VREG, die de berekening *uitvoert*. Elke
resultaatrij daar draagt een `data-productinvoicestring` met de volledige
kostenopbouw — energiekost, nettarieven én heffingen, per contract.

Die heffingsbedragen zijn een zuivere functie van het ingevulde jaarverbruik.
Vraag hetzelfde profiel op bij verschillende verbruiken, zet de bedragen tegen
het verbruik uit, en de tariefstructuur valt eruit af te lezen: elk recht stuk
is een verbruiksschijf, de helling is het tarief in EUR/MWh, een knik is een
schijfgrens. Dat is geen schatting maar een reconstructie.

## De commando's

```bash
# 1. Structuur — offline, seconden. Gaten, overlappingen, ontbrekende jaren.
energievergelijker audit heffingen

# 2. Inhoud — tegen een bestaand kalibratierapport.
python scripts/check_tarieven.py --versie <versie>

# 3. Inhoud — vers ophalen. ~13 minuten, 12 scrapes met pauzes ertussen.
energievergelijker staging calibrate --version <versie> [--postcode 9120]

# 4. Bronversheid — staat er nieuwe data bij VREG?
python scripts/check_bronnen.py          # exitcode 3 = ja
python scripts/check_bronnen.py --bijwerken --versie <versie>

# 5. Bijdrage energiefonds — tegen vlaanderen.be.
python scripts/check_energiefonds.py                 # live
python scripts/check_energiefonds.py --html <kopie>  # zonder netwerk

# 6. Referentiefacturen — een betaalde afrekening nagerekend.
pytest -q tests/test_referentiefactuur.py

# 7. Homologatie van batterijen/omvormers (Synergrid C10/26).
energievergelijker audit hardware --c10-26

# 8. De SPP-gewogen injectie-index (nog niet sluitend, zie onder).
python scripts/check_injectie_index.py
```

## vtest.be is leidend, maar niet onfeilbaar

De vergelijkingstool toont voor huishoudens géén "bijdrage op de energie",
terwijl artikel 39 van de programmawet van 25/12/2021 ze op 1,9261 EUR/MWh zet
en een echte eindafrekening ze ook aanrekent — als aparte regel náást de
bijzondere accijns. De masterdata stond daardoor op nul en de kalibratie
bevestigde die nul netjes.

De rangorde is dus: **wetgeving en een betaalde factuur samen > vtest.be >
secundaire bronnen.** Een reconstructie van een echte afrekening
(`tests/test_referentiefactuur.py`) is de sterkste toets die dit repo heeft.

Nog open: de injectie-index `M EPEX Spot Belgium/Belpex SPP_BE (kwartier)` is
het maandgemiddelde Belpex gewogen met het zonneprofiel — 35% lager dan het
rekenkundig gemiddelde. `scripts/check_injectie_index.py` toetst zes
conventies; geen enkele reproduceert de gepubliceerde waarde. Zolang dat zo is
rekent `formula_ct()` met de door VREG meegeleverde indexwaarde en nooit met
een zelf berekende.

## Het kalibratierapport lezen

`data/staging/<versie>/calibration_report.json`, per energievorm:

- `metingen[]` — wat vtest.be werkelijk teruggaf per verbruikspunt. Dit is de
  waarneming; alles daarna is interpretatie.
- `dominant_aandeel` — welk deel van de contracten dat bedrag droeg. Ligt dit
  rond 0,98 dan is er één afwijkend contract, doorgaans het sociaal tarief.
  Ligt het laag, dan is de post leveranciersafhankelijk en geen heffing.
- `componenten[].schijven` — de teruggerekende structuur.
- `componenten[].sluitend` — `true` betekent dat die structuur alle metingen
  verklaart binnen de afronding op eurocent van vtest.be. `false` betekent dat
  er meer aan de hand is dan een stuksgewijs lineair tarief; onderzoek dat
  voordat je er iets mee doet.

Een schijfgrens ligt altijd *tussen* twee meetpunten. De verbruikspunten in
`calibration.py` zijn zo gekozen dat ze de verwachte grenzen dicht insluiten
(11.900 / 12.100 rond de 12 MWh-grens voor gas). Verschuift een grens, pas dan
de punten aan zodat ze de nieuwe grens weer insluiten.

## Segment: de tweede valkuil

De accijnshervorming van 2023 gold **enkel voor residentiële afnemers**. De
paginatitel bij de leveranciers zegt het letterlijk: "Hervorming van de
bijzondere accijns voor residentiële klanten". Ondernemingen bleven op de
oude tarieven uit de programmawet van 2021 staan.

Het verschil is groot genoeg om onmiddellijk op te vallen zodra je het weet,
en onzichtbaar zolang je het niet weet:

    woning        46,00 EUR/MWh   energiebijdrage 0
    onderneming   14,21 EUR/MWh   energiebijdrage 1,9261

Kalibreer daarom altijd het segment dat je wil controleren:

```bash
energievergelijker staging calibrate --version <id> --segment woning
energievergelijker staging calibrate --version <id> --segment onderneming
```

Beide schrijven een eigen rapport (`calibration_report.json` respectievelijk
`calibration_report_onderneming.json`). Een cijfer uit het ene segment naar het
andere overzetten is de snelste manier om een fout te introduceren.

## Btw: de meest gemaakte fout

De masterdata staat **exclusief** btw. Persberichten, nieuwsartikelen en de
meeste leverancierspagina's noemen bedragen **inclusief** 6%. Een verschil van
precies factor 1,06 is dus geen afwijking maar een eenheidsverwarring:

    48,76 EUR/MWh incl. btw  =  46,00 EUR/MWh excl. btw
    10,93 EUR/MWh incl. btw  =  10,31 EUR/MWh excl. btw

Reken altijd om voordat je concludeert dat een cijfer fout is.

## Een tarief bijwerken

Overschrijf nooit een bestaande `[[schijf]]`. Voeg er een toe met een eigen
`geldig_vanaf`: oude periodes moeten berekenbaar blijven, want de bulk-export
bevat producten uit voorgaande maanden en jaren. De repository kiest per
peildatum het regime met de meest recente ingangsdatum en vermengt regimes
nooit.

```toml
[[schijf]]
klantcategorie = "niet_zakelijk"
van_mwh = "0"
tot_mwh = ""
accijns_eur_mwh = "0"
bijzondere_accijns_eur_mwh = "46.0000"
energiebijdrage_eur_mwh = "0"
geldig_vanaf = "2026-08-01"
geverifieerd = true
bron = "vtest.be kalibratie 2026-08-31, postcode 9120, 7 verbruikspunten, residu 0,00 EUR"
```

`geverifieerd = true` betekent: zelf teruggerekend uit vtest.be, of gelezen in
een officiële publicatie. Niet: een nieuwsartikel noemde dit getal.

Draai daarna `python scripts/check_tarieven.py` en neem de uitvoertabel op in
je verslag. Een bewering zonder die tabel is geen controle.

Werk ook de test bij die het oude cijfer vastlegde, en schrijf de herkomst
erbij — waar het getal vandaan komt en hoe het gecontroleerd is. Een assertie
zonder bronvermelding maakt een fout geverifieerd in plaats van zichtbaar; zie
"Tests: herkomst boven aantal" in `CLAUDE.md`.

## Nettarieven

De distributienettarieven komen wél uit een gestructureerde bron (de
VREG-werkboeken) en hoeven niet teruggerekend te worden. Ze zijn wel te
controleren: de gescrapete `vtest_product_components.csv` bevat vtest.be's
eigen `Nettarieven`-groep per postcode. Voor elektriciteit hoort de som van
`kWh-tarief` + `kWh-tarief normaal` + `Tarieven voor de toeslagen` uit
`tariffs_electricity_afname.csv` exact gelijk te zijn aan het
`Afnametarief (per kWh)` van vtest gedeeld door het verbruik. Bij de laatste
controle klopte dat voor alle acht netbeheerders tot op 1e-6 EUR/kWh.

Twee dingen die daarbij van pas komen:
- vtest.be rekent voor een woning met een standaardprofiel van 3.434 kWh
  elektriciteit en 16.262 kWh aardgas, en een gemiddelde maandpiek van
  4,218 kW.
- Voor aardgas hangt de tariefgroep (GAS_T1..T6) af van het jaarverbruik; bij
  16.262 kWh gebruikt vtest GAS_T2.

## Wat níet gedekt is

- Het transporttarief van Fluxys voor aardgas zit niet in de
  VREG-distributiewerkboeken, maar staat sinds 2026-09-01 wél in dit repo:
  `config/nettarieven/transport_aardgas.toml`, met de waarden die vtest.be
  werkelijk toepast (1,5565 EUR/MWh voor een woning, 1,5600 voor een
  onderneming). Dat verschil van 0,22% is onverklaard; vtest.be geldt hier als
  leidende bron, dus het wordt niet meer als afwijking gemeld. Voor
  elektriciteit bestaat dit gat niet: het transporttarief van Elia zit al in
  de ODV-post van het distributiewerkboek.
- De accijnsschijven boven 50 MWh zijn niet op vtest.be te meten en dragen
  daarom `geverifieerd = false`.
- Periodes vóór 01/07/2023 staan niet in de masterdata; de repository stopt
  daar met een `HeffingenError` in plaats van een verkeerd tarief te geven.
