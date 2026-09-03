# Plan: de databank als enige bron voor de berekening

*Opgesteld 2026-09-03.*

De regel die dit plan stuurt: **de berekening komt uit de code, de data komt uit
de databank.** Geen enkele rekenstap leest nog een CSV.

## Waarom dit plan bestaat

`tarief_afname` telt 16.642 rijen en `tarief_injectie` 9.295. In geen van beide
staat één energieprijs:

| kolom | `tarief_afname` | `tarief_injectie` |
|---|---|---|
| `vaste_vergoeding_jaar`, `groene_stroom_kwh`, `wkk_kwh` | gevuld | gevuld |
| `param_a` / `param_z` | 12.313 / 12.252 niet-nul | gevuld |
| **`energieprijs_kwh`** | **0 van 16.642** | **0 van 9.295** |
| **`index_naam_*` / `index_waarde_*`** | **0 van 16.642** | **0 van 9.295** |

Dat is niet één vergeten kolom maar de grootste post van elke factuur.

**Hoe het onopgemerkt bleef, is het eigenlijke punt.** Niets leest uit de
databank. `DataRepository` leest CSV's uit `versions/`, en `calculation/` raakt
de databank nergens aan. De databank was dus schrijf-only: er was geen enkele
consument die kon merken dat er iets ontbrak, en dus faalde er nooit iets. Elke
import meldde netjes "25.937 tarief-snapshots".

Dat is dezelfde foutklasse als alles wat deze week bovenkwam — de lege
contractmetadata, het nettarief zonder einddatum, de audit die op nul rijen
slaagde. Steeds een stil verkeerd of ontbrekend getal, nooit een crash. Het
verschil is dat die drie wél een consument hadden en deze niet.

**De les voor de volgorde hieronder:** een dataset is pas af als iets ze
gebruikt. Daarom eindigt elke fase met een controle die faalt zodra de data
ontbreekt, en is het exitcriterium een berekening en geen rijentelling.

## Exitcriterium

Het plan is klaar wanneer de referentiefactuur uit de databank gereconstrueerd
wordt met hetzelfde resultaat als vandaag uit de CSV's:

```
leverancier 1132,40 + net 678,14 + heffingen 336,81 − injectie 71,22
= 2076,13 tegenover 2076,06 op de factuur   (+0,07 / 0,003%)
```

Vandaag haalt die reconstructie haar data uit `versions/<id>/`. Straks uit
PostgreSQL, met exact dezelfde bedragen. Wijkt er iets af, dan is dat een
bevinding en geen afronding.

---

## Fase 1 — De databank moet de prijzen dragen  ✅ *afgerond 2026-09-03*

Zonder deze fase heeft de rest geen zin.

### 1.1 De energieprijs per register opslaan

**Probleem.** `energieprijs_kwh` is leeg op alle 25.937 tariefrijen.

**Oorzaak.** De V-test-export is lange vorm: één rij per component, met de
prijs in de kolom `price`. De prijs per meterregister staat op de
componentrijen `single`, `day`, `night`, `exclusive_night`, `dynamic`,
`tou_peak`, `tou_offpeak`, `tou_super_offpeak`, `consumptiontotal`. De
importlus in `import_leverancier_en_product` gebruikt die codes om
`meter_type` te bepalen en slaat ze daarna over:

```python
if comp_code.lower() in METER_TYPES:
    continue          # <- hier gaat de prijs verloren
```

`_map_component_code_to_field` kent alleen `"energieprijs"`,
`"energieprijs_kwh"` en `"energy_price"`, en die codes komen in de brondata
niet voor. Elke aanroep valt dus in `unmapped_components` of wordt overgeslagen.

**Aanpak.** De rij voor `meter_type = X` moet de prijs van componentrij `X`
overnemen in `energieprijs_kwh`. Let op de gevallen die geen gewoon register
zijn: `fixed_fee_single` / `fixed_fee_double` / `fixed_fee_exclusive_night` zijn
vaste vergoedingen per metertype, `single_and_exclusive_night` dekt twee
registers tegelijk, en `day_vast` / `single_vast` / `night_vast` zijn de vaste
tak van een gemengd product. Die horen niet blind als energieprijs geboekt te
worden.

**Bewijs.** Voor ENGIE Easy (product 35698, woning, elektriciteit) moet de
energieprijs per register en per maand overeenkomen met `master_vast.csv` —
niet steekproefsgewijs maar voor alle 163 maandrijen.

### 1.2 De indexnaam en -waarde opslaan

**Probleem.** `index_naam_*` en `index_waarde_*` zijn leeg op alle rijen.

**Oorzaak.** Ze worden gelezen uit `groep.iloc[0]` — de eerste rij van de
groep. Dat is meestal `green` of `fixed_fee`, en die dragen de indexkolommen
niet.

**Waarom dit blokkeert.** Een variabel product levert nu `param_a = 0,1145` en
`param_z = 1,645`, dus de formule `0,1145 × index + 1,645` — zonder index.
`Calculator.formula_ct()` rekent bewust met de door VREG *meegeleverde*
indexwaarde en nooit met een zelf berekende (zie CLAUDE.md, "De injectie-index
is SPP-gewogen"). Zonder die waarde is de formule onbruikbaar.

**Aanpak.** De indexvelden overnemen van de componentrij die ze werkelijk
draagt, niet van de eerste rij van de groep. Verschillen ze binnen één groep,
dan is dat een bevinding en geen keuze.

**Bewijs.** Voor "Bolt Variabel" injectie augustus 2026 moet gelden:
`0,094 × 70,54139 − 1,133 = 5,49789 ct/kWh`, tegenover de 5,5 die VREG zelf als
berekende prijs meelevert.

### 1.3 Een importcontrole die dit had gevangen

**Probleem.** De import meldde succes terwijl de kernkolom leeg bleef.

**Aanpak.** `import_leverancier_en_product` moet weigeren wanneer een
verwachte kolom over de hele import leeg blijft — dezelfde regel die
`audit sanity` sinds deze week op de contractmetadata toepast. Ook
`unmapped_components` hoort luid te zijn in plaats van stil verzameld.

**Bewijs.** De controle terugdraaien op de huidige data moet de import laten
falen.

---

## Fase 2 — Eén schrijfwijze voor de energievorm  ✅ *afgerond 2026-09-03*

**Probleem.** `energie_product` schrijft `'Elektriciteit'` / `'Gas'`, terwijl
`netbeheerder_tarief`, `marktcurve` en `verbruiksprofiel_waarde`
`'elektriciteit'` / `'gas'` gebruiken. Een join tussen die tabellen levert stil
nul rijen op.

**Aanpak.** Eén schrijfwijze (kleine letters, zoals de meerderheid), met een
migratie die bestaande rijen omzet en een `CHECK`-constraint die de andere vorm
voortaan weigert. Een constraint en niet alleen een normalisatie in de code:
het probleem ontstond juist doordat twee importers los van elkaar schreven.

**Bewijs.** Een join tussen `energie_product` en `netbeheerder_tarief` op
`energie_type` levert rijen op. Vandaag nul.

---

## Fase 3 — De rekenengine leest uit de databank

### 3.1 Een databankgestuurde repository  ✅ *afgerond 2026-09-03*

**Aanpak.** Een `DbDataRepository` met dezelfde interface als `DataRepository`
(`products()`, `dnb_for()`, `tariefjaar`, `netbeheerders`), maar gevoed uit
PostgreSQL. `Calculator` en `Kostberekening` blijven ongewijzigd — dat is het
punt van "de berekening komt uit de code".

De interface moet een **peildatum** aankunnen, niet alleen een versie: de
tarieftabellen dragen maandelijkse SCD2, en dat is precies wat een contract van
april 2026 herberekenbaar maakt. `DataRepository` is versie-gebonden en kan dat
niet.

**Bewijs.** De reconstructie van de referentiefactuur uit de databank geeft
dezelfde vier bedragen als uit de CSV's.

### 3.2 De CSV-weg uitfaseren

Pas ná 3.1 en pas wanneer het exitcriterium haalt. Zolang beide bestaan is de
CSV-weg de referentie waartegen de databankweg bewezen wordt; dat is de enige
onafhankelijke controle die er is.

---

## Fase 4 — De bewaking die dit had moeten vangen  ✅ *afgerond 2026-09-03*

### 4.1 De referentiefactuur mag niet op een oude versie staan

`tests/test_referentiefactuur.py` heeft `VERSIE = "20260829T202059Z-853a7046"`
hard ingebakken. De test slaagt dus ook als de actuele data breekt. Hij moet de
versie uit `current.txt` nemen.

### 4.2 Een test die de databank tegen haar doel legt

Er is geen enkele test die vaststelt dat de databank bevat wat een berekening
nodig heeft. Precies daarom bleef dit een week onzichtbaar. Er komt een test
die per verplichte kolom vaststelt dat ze niet leeg is — en die faalt op de
databank zoals die er vandaag bij staat.

---

## Wat er uiteindelijk gevonden is

Vier fouten in de import, alle vier stil:

1. **De energieprijs werd weggegooid.** De registercodes (`single`, `day`, ...)
   dienden als `meter_type` en werden daarna overgeslagen — inclusief de prijs
   die eraan hing. `energieprijs_kwh`: 0 van 25.937.
2. **De formule kwam uit de verkeerde rij.** Uit `groep.iloc[0]` in plaats van
   de eigen registerrij, waardoor elk register dezelfde vector kreeg.
3. **De indexkolom werd nooit gevonden.** Gezocht op `index_name_a`, de kolom
   heet `index_name_A`. `index_waarde_a`: 0 van 25.937.
4. **De vaste vergoeding per meteropstelling viel samen.**
   `fixed_fee_single`/`_double`/`_exclusive_night` belandden alle drie in
   dezelfde kolom; de laatste won, voor élk metertype. Bij Ebem "Groen B@sic+"
   kreeg de single-meter 33,06 in plaats van 70,75.

En drie bevindingen die pas zichtbaar werden door de databank écht als bron te
gebruiken:

- **`energie_type` in twee schrijfwijzen** — een join tussen producten en
  nettarieven gaf 0 producten, nu 686 (migratie 0020).
- **Maar één tariefjaar geladen.** De 2025-nettarieven ontbraken, en de
  SCD2-upsert weigerde ze bij te laden ("begint op 2025-01-01 terwijl de
  laatste rij al op 2026-01-01 begint"). Beide opgelost; 2025 en 2026 sluiten
  naadloos aan.
- **Tarieven zonder herkomst.** Migratie 0021 en `db backfill` sluiten dat.

**Uitkomst:** de referentiefactuur reconstrueert uit PostgreSQL met exact
dezelfde bedragen als uit de CSV's — supplier 1132,35, grid 677,42, levies
336,81, injectie 71,20 — met ongewijzigde `Calculator` en `Kostberekening`.

**De poort:** `db audit` staat binnen de importtransactie. Een databank die niet
bruikbaar is, wordt niet gecommit. Nagegaan door de oude toestand na te bootsen:
4 fouten, import geblokkeerd. En de referentiefactuur-uit-databank stopt dan met
"Vast product mist afnameprijs" — die guard bestond al, er was alleen nooit iets
dat hem tegen de databank aanriep.

---

## Fase 5 — Opruimwerk (blokkeert niets)

### 5.1 `marktcurve` groeit per publicatie

265.080 rijen na twee publicaties, telkens dezelfde curves onder een nieuw
versie-id. Bij maandelijks publiceren is dat ~1,6 miljoen grotendeels
identieke rijen per jaar. Overwegen: de curves koppelen aan het bronbestand
(sha256 uit het raw-manifest) in plaats van aan de dataversie.

### 5.2 `vreg_id` ontbreekt op 480 van de 686 producten

Slechts 206 producten zijn aan een scrape-contract gekoppeld. Zonder die
koppeling kan de contractmetadata (tariefkaart, doelgroep, intekenperiode) niet
bij het product uit de bulk-export. Dit is best-effort matching op handelsnaam;
het verklaart ook waarom `tariefkaart_url` maar op 199 producten staat.

### 5.3 `contract_id` op `vtest_postcode_prijs`

Migratie 0019 liet de foreign key naar `vtest_contract` vervallen omdat
`vreg_id` niet meer uniek is. Een `contract_id` die naar het juiste snapshot
wijst herstelt de integriteit én maakt "toon het contract zoals het was toen
deze prijs gold" een join.

### 5.5 Een tariefjaar bijladen is geen publicatie

De nettarieven van 2025 zitten sinds 2026-09-03 in de databank, maar ze zijn er
met een rechtstreekse aanroep van `import_netbeheerder_tarieven` in gezet — niet
via `version publish`. Er is dus geen `data_version`-rij en geen map in
`versions/` voor de bron (`20260903T052414Z-3f119f7d`, het VREG-werkboek 2025).
De data klopt, maar een herbouw vanuit de pipeline zou ze niet reproduceren, en
niets legt vast waar ze vandaan komt.

Daaronder zit een modelleerspanning die opgelost moet worden voor de databank
echt de waarheid is:

- `data_version` beschrijft één momentopname van de hele dataset, met precies
  één actieve versie. Dat past bij de V-test-export, die maandelijks in zijn
  geheel vervangen wordt.
- `netbeheerder_tarief` (per tariefjaar) en `tarief_afname`/`tarief_injectie`
  (per maand) zijn **cumulatief**. Ze horen niet bij één versie; juist het
  opstapelen maakt het herberekenen van april 2026 mogelijk.

Een historisch tariefjaar bijladen is dus geen publicatie van een nieuwe versie
— dat zou de actieve dataset verzetten naar een jaargang van vorig jaar. Het is
een aparte handeling die nog geen commando heeft.

Te doen: een ondersteunde manier om een tariefjaar bij te laden (bijvoorbeeld
`db backfill --raw-versie <id> --jaar 2025`), die de herkomst vastlegt zodat de
databank herbouwbaar blijft. Nu is de enige vastlegging deze paragraaf.

Dit werd pas zichtbaar doordat de SCD2-upsert een oudere jaargang aanvankelijk
weigerde ("begint op 2025-01-01 terwijl de laatste rij al op 2026-01-01
begint"). Die weigering is opgeheven; de bookkeeping niet.

### 5.4 Het werkboek van 2024

Levert alleen tarieven voor FA, FI, FL en FW; de tien Fluvius-entiteiten van
vóór de fusie staan niet in `DNB_CODES`. Bekend en gedocumenteerd, raakt de
huidige tariefjaren niet.

---

## Wat bewust buiten dit plan valt

- **De rekenregels zelf.** Er wordt in dit plan geen enkele formule gewijzigd.
  Als de databankweg een ander bedrag geeft dan de CSV-weg, is dat een
  invoerfout en geen rekenfout.
- **Nieuwe functionaliteit in de simulator.** Eerst de bron op orde, dan pas
  uitbouwen. Bouwen op een databank die de prijzen niet draagt is precies hoe
  dit ontstaan is.

## Volgorde

Fase 1 → 2 → 3.1 → 4 → 3.2, en fase 5 wanneer het uitkomt. Fase 1 en 2 vragen
één herimport van de bestaande versie; geen nieuwe scrape, geen nieuwe download.
