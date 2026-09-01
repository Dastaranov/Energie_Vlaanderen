# Plan: transporttarieven aardgas (Fluxys) toevoegen

Status: **uitgevoerd op 2026-09-01.** Opgesteld 2026-08-31 na de vaststelling
dat dit de enige kostenpost was die vtest.be wel doorrekende en dit repo niet
kende.

Wat er anders liep dan gepland: het plan ging uit van twee verschillende
tarieven per segment (1,5565 voor woning, 1,5600 voor onderneming), afgeleid
uit de metingen. CREG-nota (Z)3230 van 11/06/2026 blijkt echter één uniform
tarief van **1,56 EUR/MWh excl. btw** voor heel België vast te leggen sinds
01/01/2026 — precies de ondernemingsmeting, en ook precies wat het sociaal
tarief binnen de woningscrape hanteert.

De 1,5565 die vtest.be op gewone woningproducten toepast is daarmee geen
tweede tarief maar een onverklaarde afwijking van 0,22%. In de masterdata
kwam eerst het officiële cijfer te staan, met de afwijking vastgepind in
`scripts/check_tarieven.py` zodat ze bekend bleef.

**Herzien op 2026-09-01.** Die keuze is teruggedraaid: vtest.be geldt nu als
leidende bron, dus de masterdata draagt 1,5565 voor woning en 1,5600 voor
onderneming — precies wat oorspronkelijk gemeten was. De redenering is dat
deze toepassing vergelijkt met de officiële vergelijkingstool van VREG, en dat
overeenkomen met wat die tool een klant toont dan zwaarder weegt dan
overeenkomen met de nota waarop ze zich baseert. Het verschil blijft
onverklaard; het wordt alleen niet meer als afwijking gemeld. Zie de kop van
`config/nettarieven/transport_aardgas.toml`.

## Wat er ontbreekt

vtest.be splitst de nettarieven voor aardgas in vier posten:

| post | bron in dit repo |
|---|---|
| Vast tarief distributie (per jaar) | `tariffs_gas_afname.csv`, "Vaste term" |
| Afnametarief distributie (per kWh) | idem, proportionele term + toeslagen |
| Tarief databeheer (per jaar) | idem, "Jaaropname" |
| **Afnametarief transport (per kWh)** | **nergens** |

De eerste drie komen exact overeen — gecontroleerd voor alle acht
netbeheerders, afwijking ≤ 3e-7 EUR/kWh. De vierde staat in geen enkel
VREG-werkboek, want het is geen distributietarief: het is het vervoerstarief
van Fluxys, dat de netbeheerder als doorrekening op de factuur zet.

Bij elektriciteit bestaat dit gat niet. Daar blijkt het transporttarief van
Elia al verrekend te zitten in de ODV-post van het distributiewerkboek; de som
van `kWh-tarief` + `kWh-tarief normaal` + `Tarieven voor de toeslagen` komt
exact uit op het `Afnametarief (per kWh)` van vtest.be. Dit plan gaat dus enkel
over aardgas.

## Wat we al weten

Uit de kalibraties van 2026-08-31 (postcode 9120, vijf verbruikspunten per
segment):

| verbruik | woning | onderneming |
|---|---|---|
| 4.000 kWh | 6,23 EUR | 6,24 EUR |
| 11.900 kWh | 18,52 EUR | 18,56 EUR |
| 12.100 kWh | 18,83 EUR | 18,88 EUR |
| 20.000 kWh | 31,13 EUR | 31,20 EUR |
| 35.000 kWh | 54,48 EUR | 54,60 EUR |

Daaruit volgt:

- **Het tarief is vlak.** Geen knik, ook niet op de 12 MWh-grens waar de
  accijns wél knikt. Eén tarief per segment volstaat.
- **De tarieven staan vast tot op vier decimalen.** Voor onderneming
  reproduceert 0,00156 EUR/kWh alle vijf metingen exact. Voor woning laat een
  zoektocht over alle waarden met zeven decimalen precies twee kandidaten
  over, 0,0015565 en 0,0015566, die alle vijf metingen tot op de eurocent
  verklaren.
- **Woning en onderneming verschillen.** 1,5565 tegenover 1,5600 EUR/MWh —
  klein, maar reëel: 0,00156 reproduceert de woningmetingen níet (6,24 waar
  6,23 gemeten werd). De masterdata moet dus per segment gescheiden blijven,
  net als bij de accijnzen.
- **Het tarief is niet postcode-afhankelijk.** Alle acht representatieve
  postcodes geven hetzelfde bedrag. Het hoort dus niet in
  `tariffs_gas_afname.csv` thuis, dat per netbeheerder is opgebouwd.
- **Het sociaal tarief kent een eigen waarde** (25,37 tegenover 25,31 EUR bij
  16.262 kWh). Dat is een aparte tariefregeling, geen afwijking.

Grootteorde: ongeveer **25 EUR per jaar** op een gemiddeld gezinsverbruik.
Klein tegenover de accijnsfout van ~105 EUR, maar het is de laatste post die
een gasfactuur van dit repo systematisch te laag maakt.

## Voorgestelde aanpak

### Stap 1 — masterdata, niet pipeline

Het transporttarief hoort niet in de ingest-pipelines: er is geen werkboek om
te parsen, het is één landelijk getal dat per reguleringsperiode wijzigt
(CREG keurde de methodologie 2024-2027 goed). Behandel het zoals de
heffingen: handmatig onderhouden masterdata met een tijdsas en een
verificatievlag.

Nieuw bestand `config/nettarieven/transport_aardgas.toml`:

```toml
energievorm = "aardgas"
bron = "vtest.be kalibratie 2026-08-31 + CREG-goedgekeurde Fluxys-tarieven 2024-2027"

[[tarief]]
klantcategorie = "niet_zakelijk"
eur_per_kwh = "0.0015565"
geldig_vanaf = "2026-01-01"
geverifieerd = true
bron = "vtest.be kalibratie 2026-08-31, segment woning, 5 verbruikspunten"

[[tarief]]
klantcategorie = "zakelijk_laagspanning"
eur_per_kwh = "0.00156"
geldig_vanaf = "2026-01-01"
geverifieerd = true
bron = "vtest.be kalibratie 2026-08-31, segment onderneming, 5 verbruikspunten, alle bedragen exact gereproduceerd"

[[tarief]]
klantcategorie = "sociaal"
eur_per_kwh = "0.0015602"
geldig_vanaf = "2026-01-01"
geverifieerd = false
bron = "Afgeleid uit één meetpunt (25,37 EUR bij 16.262 kWh); nog niet gekalibreerd"
```

De klantcategorieën volgen bewust dezelfde namen als in
`config/heffingen/` (`niet_zakelijk`, `zakelijk_laagspanning`), zodat een
calculator één categorie kan doorgeven aan beide repositories.

Een nieuwe map `config/nettarieven/` in plaats van het bij `config/heffingen/`
te zetten: een vervoerstarief is geen heffing, en de bestaande
`HeffingenRepository` zou er conceptueel scheef van gaan staan.

De `geldig_vanaf` van 2026-01-01 is een aanname — het gemeten tarief geldt
vandaag, maar wanneer het inging is niet vastgesteld. Zet daarom
`geverifieerd = true` op de waarde en niet op de datum, en noteer dat in de
bron. Wie een factuur van 2025 wil narekenen, moet die datum eerst
onderbouwen.

### Stap 2 — repository

`src/energie_vlaanderen/nettarieven/transport.py`, in de vorm van
`HeffingenRepository`:

```python
class TransportTariefRepository:
    @classmethod
    def load(cls, config_dir: Path) -> "TransportTariefRepository": ...

    def eur_per_kwh(
        self, energievorm: str, klantcategorie: str, op_datum: date
    ) -> Decimal: ...
```

Zelfde regel als bij de heffingen: geen stille 0 bij ontbrekende data maar een
`TransportTariefError`. Een gasfactuur zonder transporttarief is per definitie
te laag, en dat mag niet onopgemerkt gebeuren.

### Stap 3 — validatie en bewaking

- `controleer_transport()` naast `controleer_accijns()` in
  `heffingen/validation.py` — of, netter, een eigen
  `nettarieven/validation.py` met dezelfde `Bevinding`-vorm zodat
  `audit heffingen` beide kan tonen. Overweeg het commando te hernoemen naar
  `audit masterdata`, want het dekt dan meer dan heffingen alleen.
- `scripts/check_tarieven.py` uitbreiden: het kalibratierapport bevat het
  transporttarief al onder `Nettarieven|Afnametarief transport (per kWh)`, dus
  de controle is een kwestie van één koppeling toevoegen. Dat maakt het tarief
  meteen onderdeel van de dagelijkse bronbewaking.

### Stap 4 — calculator

Dit is het punt waarop het plan botst met een grotere openstaande beslissing:
`Calculator.calculate()` ondersteunt vandaag **geen** aardgas. `grid_cost()`
rekent met elektriciteitsbegrippen (capaciteitstarief, ODV) en aardgas werkt
anders — een vaste term plus een proportionele term per tariefgroep
(`GAS_T1..T6`), waarbij de groep van het jaarverbruik afhangt.

Twee volgordes zijn verdedigbaar:

**A. Eerst de data, dan de calculator.** Stap 1-3 uitvoeren, het tarief
beschikbaar maken, en de calculator laten zoals hij is. Voordeel: de data is
compleet en gecontroleerd voordat er iets op steunt, en de bewaking pakt
wijzigingen meteen op. Nadeel: het tarief ligt een tijd ongebruikt.

**B. Samen met een `gas_cost()`.** Het transporttarief is één term in een
gasnetkostberekening die er toch moet komen; los toevoegen betekent de
gaskosten twee keer aanraken.

**Aanbeveling: A.** Het transporttarief is klein, af te bakenen en nu
meetbaar; de gascalculator is een ontwerpvraag met een eigen scope (welke
tariefgroep bij welk verbruik, hoe de groepsgrenzen bepaald worden, of
MS/HS meemoet). Ze koppelen betekent dat een controleerbaar stuk werk blijft
liggen op een onbeslist stuk ontwerp. En omdat `check_tarieven.py` het tarief
dan al bewaakt, is het bij het bouwen van `gas_cost()` gegarandeerd actueel.

### Stap 5 — de tariefgroep bepalen (aparte scope, hier alleen genoteerd)

Voor een volledige gasnetkost is nog nodig: welke `GAS_T*`-groep hoort bij
welk jaarverbruik. vtest.be gebruikte GAS_T2 bij 16.262 kWh, en de kalibratie
liet een knik zien in `Afnametarief distributie` rond 11.900 kWh — wat
suggereert dat de grens T1/T2 daar ligt. Dat is met dezelfde kalibratietechniek
exact vast te stellen: meet `Vast tarief distributie` en
`Afnametarief distributie` bij oplopend verbruik en zoek waar de vaste term
springt. Dat verdient een eigen kalibratieronde met meetpunten die die grens
insluiten.

## Wat dit niet oplost

- **De echte Fluxys-tariefstructuur.** Fluxys hanteert entry/exit-capaciteit
  en commodity-tarieven per aansluitpunt op het vervoersnet. Wat hier
  gemodelleerd wordt is de doorrekening zoals ze op een
  distributienetaansluiting terechtkomt — één gemiddeld tarief per kWh. Voor
  een huishouden of KMO is dat de juiste abstractie; voor een klant die
  rechtstreeks op het vervoersnet zit, niet. Leg dat vast in de bestandskop,
  zoals de heffingenbestanden hun eigen beperkingen vermelden.
- **Het sociaal tarief.** Eén meetpunt volstaat niet om vast te stellen of
  het vlak is. Wie die categorie nodig heeft, kalibreert ze apart.

## Volgorde en inschatting

1. ~~Kalibreer transport voor segment onderneming~~ — gedaan op 2026-08-31;
   beide segmenten zijn gemeten en verschillen licht.
2. `config/nettarieven/transport_aardgas.toml` + `TransportTariefRepository` + tests.
3. Koppeling in `scripts/check_tarieven.py` en de validatie.
4. Documentatie in `CLAUDE.md` en de `tariefcontrole`-skill.

Wat rest is klein werk: de meetgegevens liggen er, en de vorm bestaat al bij
de heffingen en valt te kopiëren. Het echte werk zit in stap 5 — de
gascalculator — en dat is bewust een aparte beslissing.
