# Energie Vlaanderen

[![Tests](https://github.com/Dastaranov/Energie_Vlaanderen/actions/workflows/tests.yml/badge.svg)](https://github.com/Dastaranov/Energie_Vlaanderen/actions/workflows/tests.yml)
[![Bronbewaking](https://github.com/Dastaranov/Energie_Vlaanderen/actions/workflows/bronbewaking.yml/badge.svg)](https://github.com/Dastaranov/Energie_Vlaanderen/actions/workflows/bronbewaking.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue?logo=python&logoColor=white)](https://www.python.org/downloads/)
[![PostgreSQL](https://img.shields.io/badge/databank-PostgreSQL-336791?logo=postgresql&logoColor=white)](https://www.postgresql.org/)
[![Decimal](https://img.shields.io/badge/financi%C3%ABle%20rekenkunde-Decimal-2ea44f)](#)
[![Licentie: Apache 2.0](https://img.shields.io/badge/licentie-Apache%202.0-lightgrey)](LICENSE)

Energievergelijker voor Vlaanderen. Haalt de officiële V-test- en
distributienettarieven op bij VREG, verwerkt ze via versiegebonden pipelines,
en zet ze in een PostgreSQL-databank als centrale bron voor prijsberekeningen.

Bovenop die data staat een gebruikersbasis: adressen, EAN's, meters,
installaties en leverancierscontracten met een geldigheidsperiode. Daarmee kan
een verbruiksperiode doorgerekend worden zoals een leverancier het doet — per
contractwissel, per tariefkaartversie, per heffingenregime en per tariefjaar.
Een echte eindafrekening is er tot op **0,003%** mee gereproduceerd.

## Inhoud

- [Vereisten](#vereisten)
- [Installatie](#installatie)
- [Van bron tot databank](#van-bron-tot-databank)
- [Gebruik](#gebruik)
- [Dataversies en de databank](#dataversies-en-de-databank)
- [Gebruikers en simulatie](#gebruikers-en-simulatie)
- [Masterdata en tariefbewaking](#masterdata-en-tariefbewaking)
- [Verbruiksprofielen (Synergrid)](#verbruiksprofielen-synergrid)
- [Testen](#testen)
- [Documentatie](#documentatie)

## Vereisten

- Python 3.11 of nieuwer
- Een lokale Chrome of Firefox, voor de commando's die vtest.be scrapen
  (`staging refine`, `staging calibrate`)
- Toegang tot een PostgreSQL-databank, voor de `db`-commando's en
  `market sync`

## Installatie

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[test,db,scrape]"
```

Voor de Synergrid-verbruiksprofielen (RLP0N/SLP-EX, `.xlsb`) is er een extra
`profielen`-groep nodig — SPP (`.xlsx`) werkt al met de basisinstallatie:

```bash
pip install -e ".[profielen]"
```

Maak daarnaast een `.env` in de projectroot (staat niet in git):

```plain text
ENTSOE_API_KEY=...
DB_HOST=...
DB_NAME=energie_vlaanderen
DB_USER=...
DB_PASSWORD=...
```

Zonder `.env` blijft de CLI bruikbaar; enkel `market sync`, de
`db`-commando's en de bijhorende dashboardvelden werken dan niet.

Controleer de installatie:

```bash
pytest -q -m "not integration"
python energievergelijker.py paths
```

## Van bron tot databank

```bash
# 1. Databankschema aanleggen (eenmalig)
energievergelijker db init

# 2. Bronbestanden ophalen — levert een versie-id terug
energievergelijker source download --year 2026

# 3. Werkboeken inlezen naar staging/
energievergelijker staging parse --version <id>

# 4. De live vergelijkingstool scrapen
energievergelijker staging refine --version <id> --matrix

# 5. Heffingen afleiden uit vtest.be
energievergelijker staging calibrate --version <id>

# 6. Controleren
energievergelijker audit sanity  --version <id>
energievergelijker audit golden  --version <id>
energievergelijker audit heffingen

# 7. Goedkeuren en publiceren
energievergelijker audit approve   --version <id>
energievergelijker version publish --version <id>

# 8. Toetsen dat bestanden en databank overeenkomen
energievergelijker db verify
```

`version publish` kopieert de versie naar `versions/`, importeert ze in
PostgreSQL en activeert ze als één handeling; `db verify` (stap 8) bevestigt
dat bestanden en databank één op één overeenkomen.

Verdeel stap 4 bij voorkeur over meerdere sessies met `--segment` en
`--energy` in plaats van in één keer `--matrix` te draaien: de scrapetool
werkt tegen een publieke website, geen API.

### Verbruiksprofielen: een apart traject

De stappen hierboven verwerken de vier VREG-bronnen (`vtest`, `tariffs`,
`curves` en de live scrape). De Synergrid-verbruiksprofielen (SLP-EX, RLP0N,
SPP) volgen een eigen download en een eigen `--only profielen`-run, met een
eigen versie-id voor de Synergrid-bron zelf:

```bash
# a. Profielbestanden ophalen bij Synergrid — levert een eigen versie-id terug
energievergelijker synergrid download --year 2026

# b. Inlezen naar staging/<id>/profielen/
energievergelijker staging parse --version <id> --only profielen \
    --synergrid-version <synergrid-id> --jaar 2026

# c. Rechtstreeks naar de databank
energievergelijker db import --version <id>
```

Stap c gaat hier bewust via `db import` en niet via `version publish`: die
laatste vereist nog altijd een `vtest/`-submap in de stagingmap, dus een
versie die uitsluitend `--only profielen` verwerkt publiceert niet. Bevat
`<id>` ook een vtest/tariffs/curves-run (dezelfde `--version` als hierboven,
gewoon aangevuld met de profielenstap), dan werkt `version publish` gewoon en
is deze losse `db import`-stap overbodig.

## Gebruik

**Interactieve shell** — zonder argumenten start een dashboard en een prompt:

```bash
python energievergelijker.py
Energie_vlaanderen >> raw status
Energie_vlaanderen >> staging parse --version <versie-id> --only vtest
Energie_vlaanderen >> exit
```

**Eenmalige commando's** — voor scripts en CI, vorm `<groep> <actie>
[opties]`. Elk commando ondersteunt `--json` voor machineleesbare output.

| Groep | Acties |
| --- | --- |
| `source` | `download --year`, `list --year` |
| `raw` | `verify --version`, `status` |
| `staging` | `parse --version [--only vtest\|tariffs\|curves\|profielen\|all] [--overwrite] [--synergrid-version] [--jaar]`, `refine --version [--postcode] [--segment] [--energy] [--matrix] [--met-contractdetails] [--browser]`, `calibrate --version [--postcode]` |
| `synergrid` | `list --year`, `download --year`, `verify --version`, `status` |
| `market` | `sync --start --end [--no-api]` |
| `audit` | `status`, `approve`, `golden`, `set-golden`, `sanity`, `sample` (alle `--version`), `heffingen [--datum] [--streng]`, `hardware [--streng] [--c10-26]` |
| `version` | `publish --version [--keep-staging] [--force] [--skip-db] [--db-overwrite]` |
| `db` | `init`, `import --version [--overwrite] [--gemeente]`, `verify`, `status` |
| `gebruiker` | `toon [--toml]`, `controleer [--toml] [--hardware]`, `bereken --van --tot [--toml] [--version] [--geen-metingen]` |
| `paths` | *(geen actie)* |

Toelichting per groep:

- **`source`** — haalt de vier VREG-werkboeken op (V-test, tarieven, curves)
  van vlaamsenutsregulator.be en levert een versie-id terug; `list` toont
  wat er voor een jaar beschikbaar staat zonder iets te downloaden.
- **`raw`** — controleert of een gedownloade versie compleet en geldig is
  (`verify`) en toont welke raw-versies lokaal staan (`status`).
- **`staging`** — de eigenlijke verwerking, met drie afzonderlijke acties:
  `parse` leest de ruwe werkboeken in tot CSV (`--only` kiest een deelverzameling: `vtest`, `tariffs`, `curves`, `profielen` of `all` —
  `profielen` zit bewust niet in `all`, zie de sectie hieronder); `refine`
  scrapet de live vergelijkingstool op vtest.be voor de echte productlijst en
  kostenopbouw (`--matrix` doorloopt alle segment/energie/postcode-
  combinaties, `--browser` is standaard Firefox); `calibrate` rekent de
  heffingen- en nettariefstructuur terug uit diezelfde website.
- **`synergrid`** — het downloadtraject voor de verbruiksprofielen
  (SLP-EX/RLP0N/SPP), los van `source`/`raw` omdat het een ander ritme en
  bestandsformaat heeft; zelfde vorm (`list`, `download`, `verify`,
  `status`) als de `source`/`raw`-groepen hierboven.
- **`market`** — synchroniseert de day-ahead marktprijzen (ENTSO-E, met
  automatische terugval op energy-charts.info) naar de lokale cache.
- **`audit`** — de controles vóór publicatie: `sanity` (plausibiliteit),
  `golden` (cel-voor-cel tegen het bron-XLSX), `sample` (steekproef),
  `status`/`approve` (goedkeuringsstatus zetten/tonen), `set-golden`
  (nieuwe referentie vastleggen), `heffingen` (structuur van
  `config/heffingen/` toetsen) en `hardware` (idem voor `config/hardware/`;
  met `--c10-26` ook tegen de Synergrid-homologatielijst). Die laatste twee
  hebben geen `--version` nodig.
- **`version`** — `publish` is de enige actie: kopieert een goedgekeurde
  versie naar `versions/`, importeert ze in de databank en activeert ze,
  als één samenhangende operatie (zie
  [Dataversies en de databank](#dataversies-en-de-databank)).
- **`db`** — databankbeheer: schema aanleggen (`init`), een versie
  importeren (`import`), en controleren of bestanden en databank nog
  overeenkomen (`verify`, `status`).
- **`gebruiker`** — leest een gebruikersdossier uit `gebruiker.toml` (`toon`),
  toetst het structureel (`controleer`) en rekent een periode door
  (`bereken`). Zie [Gebruikers en simulatie](#gebruikers-en-simulatie).
- **`paths`** — toont de actieve databankpaden (raw/staging/versions/
  current.txt), zonder subactie.

`staging refine` haalt per contract, naast de metadata, ook de volledige
kostenopbouw op zoals vtest.be die zelf berekent — inclusief de eigen
Nettarieven- en Heffingen-uitsplitsing.

## Dataversies en de databank

Elke ingest-run krijgt een versie-id (`YYYYMMDDTHHMMSSZ-<8hex>`) en doorloopt
`data/raw/` → `data/staging/` → `data/versions/`, met `data/current.txt` als
pointer naar de actieve versie.

De databank is het eindstation: `version publish` houdt de bestanden op
schijf en de rijen in PostgreSQL gesynchroniseerd, met een automatische
terugdraai als de import faalt. Publiceren vereist een goedgekeurde versie
(`audit approve`); `--force` en `--skip-db` zijn de bewuste uitzonderingen.

Tariefwijzigingen worden gehistoriseerd (SCD type 2): een nieuwe prijs sluit
de vorige af in plaats van ze te overschrijven, zodat een berekening over een
oudere periode nog steeds met het toen geldende tarief rekent.

## Gebruikers en simulatie

Een gebruikersdossier staat in `gebruiker.toml` — postcode, aansluitingspunten
met hun EAN, meterregime en registerschema, installaties (PV, batterij), en de
leverancierscontracten met hun geldigheidsperiode.
`gebruiker.voorbeeld.toml` documenteert de volledige vorm.

```bash
energievergelijker gebruiker toon                       # het dossier zoals het gelezen wordt
energievergelijker gebruiker controleer --hardware      # exitcode 2 bij een fout
energievergelijker gebruiker bereken --van 2025-06-25 --tot 2026-05-01
```

> **`gebruiker.toml` staat niet in git.** Zodra er een EAN, adres of
> meterstand in staat is het een persoonsgegeven (manifest §5.2). Hetzelfde
> geldt voor `data/referentie/` en `data/datasheets/`; daar staat alleen een
> `LEESMIJ.md` in git.

`bereken` knipt de periode op elke grens die het bedrag beïnvloedt — een
contractwissel, de bevriezingsdatum van een vaste tariefkaart, een
heffingenregime, de indexatiemaand van een variabel contract en de jaarwissel
van de nettarieven — en telt de stukken op. Het resultaat draagt een
**exactheidsklasse** (exact / gereconstrueerd / geschat / scenario) en de lijst
**aannames** waarop het steunt, elk met bron.

Wijst `[verbruik].fluvius_csv` naar een verbruikshistoriek van Fluvius, dan
komen de volumes per deelperiode uit de meting in plaats van pro rata over de
dagen verdeeld te worden. Dat maakt het verschil tussen "gereconstrueerd" en
"exact".

### Nagerekend tegen een echte factuur

Een betaalde eindafrekening (10 maanden, over de jaarwissel heen) is met de
eigen data hergesimuleerd:

| | simulatie | factuur | verschil |
| --- | ---: | ---: | ---: |
| Energie + groene stroom + WKK | 1132,40 | 1132,36 | +0,04 |
| Injectievergoeding | −71,22 | −71,20 | −0,02 |
| Netwerkkosten | 678,14 | 678,09 | +0,05 |
| Toeslagen en heffingen | 336,81 | 336,81 | **0,00** |
| **Subtotaal excl. btw** | **2076,13** | **2076,06** | **+0,07 (0,003%)** |

Buiten beschouwing blijven de commerciële kortingen en de correctie tussen
meteropname en factuurdatum: die staan in geen publieke bron.
`tests/test_referentiefactuur.py` bewaakt het geheel.

## Masterdata en tariefbewaking

Heffingen, btw en het gastransporttarief (`config/heffingen/*.toml`,
`config/nettarieven/*.toml`) zijn handmatig onderhouden en dragen elk een
bronvermelding en een tijdsas. Ze staan wél in git, in tegenstelling tot
`data/`.

Omdat er geen scrapebare bron voor heffingen bestaat, worden de cijfers
teruggerekend uit vtest.be zelf: `staging calibrate` vraagt hetzelfde profiel
op bij een reeks jaarverbruiken en leidt de tariefstructuur af uit VREG's
eigen kostenopbouw.

```bash
energievergelijker audit heffingen                     # structuur, offline
energievergelijker audit hardware [--c10-26]           # batterijen/omvormers
energievergelijker staging calibrate --version <id>    # Selenium
python scripts/check_tarieven.py --versie <id>         # config vs. vtest.be
python scripts/check_bronnen.py                        # nieuwe VREG-/Synergrid-bestanden?
python scripts/check_energiefonds.py                   # config vs. vlaanderen.be
python scripts/check_injectie_index.py                 # SPP-gewogen injectie-index
pytest -q tests/test_referentiefactuur.py              # tegen een echte afrekening
```

Een GitHub Action draait de bronbewaking dagelijks en meldt afwijkingen als
issue. Zie `docs/jaarwissel 2026-2027.md` voor het jaarlijkse
onderhoudsmoment: enkele tarieven wisselen per 1 januari en dat gebeurt
zonder waarschuwing als de masterdata niet meegaat. De bijdrage energiefonds
faalt daarbij *hard* op een ontbrekend jaar — `check_energiefonds.py` meldt
het zodra het volgende jaar nog niet gepubliceerd is.

**Let op bij vergelijken met externe bronnen:** de masterdata staat exclusief
btw, publieke communicatie noemt bedragen doorgaans inclusief 6%.

**vtest.be is leidend, maar niet onfeilbaar.** De vergelijkingstool toont voor
huishoudens géén "bijdrage op de energie", terwijl de programmawet van
25/12/2021 die op 1,9261 EUR/MWh zet en een echte eindafrekening ze ook
aanrekent. De masterdata stond daardoor op nul. De rangorde is dus: wetgeving
en een betaalde factuur samen > vtest.be > secundaire bronnen.

## Verbruiksprofielen (Synergrid)

Voor klassieke (niet-digitale) meters en variabele contracten wordt het
jaarverbruik verdeeld over kwartieren/uren met een gebruiksprofiel — zie
[`docs/research/verbruiksprofielen.md`](docs/research/verbruiksprofielen.md).
Synergrid publiceert die profielen (SLP-EX, RLP0N, SPP) jaarlijks als losse
werkboeken, grotendeels als `.xlsb` in plaats van `.xlsx`. Dat is een andere
bron, ander ritme en ander bestandsformaat dan de vier VREG-bronnen
hierboven, en heeft daarom een eigen `synergrid`-commandogroep en een eigen
raw-store (`data/raw/synergrid/`) los van `source`/`raw`.

```bash
energievergelijker synergrid download --year 2026
energievergelijker staging parse --version <staging-versie> --only profielen \
    --synergrid-version <synergrid-versie> --jaar 2026
```

`--version` is de gewone stagingversie (kan samenvallen met een vtest/
tariffs/curves-run); `--synergrid-version` wijst naar de Synergrid raw-versie
van de download hierboven. Verwerkt worden: SLP-EX, RLP0N (elektriciteit én
gas) en de SPP ex-ante-sheet — één nationaal profiel voor SLP-EX/RLP0N-gas/
SPP, één rij per netbeheerder (GLN-gekoppeld, alle Belgische DNB's) voor
RLP0N-elektriciteit. De regressiemodel-/parameterbestanden en de SPP
ex-post-historiek worden bewust nog niet geparsed.

Een harde validatieregel: profielgewichten moeten per jaar (en voor RLP0N per
netbeheerder) sommeren tot 1 — zie `docs/manifest.md` §4.4. SPP is daarvan
uitgezonderd: dat is productie per kWp geïnstalleerd vermogen, geen
verdeling.

`energievergelijker db import` neemt een `profielen/`-stagingmap automatisch
mee naar de `verbruiksprofiel_waarde`-tabel; ontbreekt die map, dan wordt er
gewoon niets geïmporteerd (geen fout). `version publish` doet dat niet voor
een versie die uitsluitend `--only profielen` verwerkt — zie
[Verbruiksprofielen: een apart traject](#verbruiksprofielen-een-apart-traject)
hierboven voor het volledige onderscheid.

## Testen

```bash
pytest -q                       # volledige suite
pytest -q -m "not integration"  # zonder tests die een lokale dataset vereisen
```

Integratietests worden automatisch overgeslagen als er geen lokale dataset
is. Zet `ENERGIEVERGELIJKER_DATA_DIR` naar een map met
`vtest/master_vast.csv` en `vtest/master_var_dyn.csv` om ze aan te zetten.

## Documentatie

- [`ROADMAP.md`](ROADMAP.md) — strategische fasering
- [`CLAUDE.md`](CLAUDE.md) — laagstructuur en ontwerpregels van de codebase
- [`docs/MOC.md`](docs/MOC.md) — overzicht van de overige documentatie
  (architectuur, prijsmodel, onderhoud, research)
