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

## Inhoud

- [Vereisten](#vereisten)
- [Installatie](#installatie)
- [Van bron tot databank](#van-bron-tot-databank)
- [Gebruik](#gebruik)
- [Dataversies en de databank](#dataversies-en-de-databank)
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
| `audit` | `status`, `approve`, `golden`, `set-golden`, `sanity`, `sample` (alle `--version`), `heffingen [--datum] [--streng]` |
| `version` | `publish --version [--keep-staging] [--force] [--skip-db] [--db-overwrite]` |
| `db` | `init`, `import --version [--overwrite] [--gemeente]`, `verify`, `status` |
| `paths` | *(geen actie)* |

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
energievergelijker staging calibrate --version <id>    # Selenium
python scripts/check_tarieven.py --versie <id>         # config vs. vtest.be
python scripts/check_bronnen.py                        # nieuwe VREG-/Synergrid-bestanden?
```

Een GitHub Action draait de laatste twee dagelijks en meldt afwijkingen als
issue. Zie `docs/jaarwissel 2026-2027.md` voor het jaarlijkse
onderhoudsmoment: enkele tarieven wisselen per 1 januari en dat gebeurt
zonder waarschuwing als de masterdata niet meegaat.

**Let op bij vergelijken met externe bronnen:** de masterdata staat exclusief
btw, publieke communicatie noemt bedragen doorgaans inclusief 6%.

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

`energievergelijker db import`/`version publish` nemen een `profielen/`-
stagingmap automatisch mee naar de `verbruiksprofiel_waarde`-tabel; ontbreekt
die map, dan wordt er gewoon niets geïmporteerd (geen fout).

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
