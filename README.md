# EnergieVergelijker

Modulaire energievergelijker voor Vlaanderen: haalt de officiële V-test- en
distributienettarieven op, verwerkt ze via versiegebonden pipelines, en
maakt ze bruikbaar voor prijsberekeningen.

## Structuur

De code leeft in `src/energie_vlaanderen/`. Zie `CLAUDE.md` voor de volledige
laagstructuur (domain/data/calculation/ingest/market/audit/infrastructure);
hieronder enkel wat je nodig hebt om het project op te starten en te gebruiken.

## Installatie

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[test,db,scrape]"
```

Maak daarnaast een `.env`-bestand aan in de projectroot (staat bewust niet in
git — bevat geheimen):

```plain text
ENTSOE_API_KEY=...
DB_HOST=100.110.20.114
DB_NAME=energie_vlaanderen
DB_USER=...
DB_PASSWORD=...
```

Zonder `.env` blijft de CLI bruikbaar; enkel `market sync` en de `db`-commando's
(en de bijhorende dashboardvelden) werken dan niet. De Postgres-databank is
enkel bereikbaar via **Tailscale**.

## Testen

```bash
pytest -q                     # volledige suite
pytest -q -m "not integration"  # zonder tests die een lokale dataset vereisen
```

## Gebruik

**Interactieve shell** — start zonder argumenten een dashboard en een prompt
waarop je commando's typt zonder telkens `python energievergelijker.py` te
herhalen:

```bash
python energievergelijker.py
Energie_vlaanderen >> raw status
Energie_vlaanderen >> staging parse --version <versie-id> --only vtest
Energie_vlaanderen >> exit
```

**Eenmalige commando's** — voor scripts/CI, vorm `<groep> <actie> [opties]`:

```bash
python energievergelijker.py source download --year 2026
python energievergelijker.py raw verify --version <versie-id>
python energievergelijker.py staging parse --version <versie-id>
python energievergelijker.py audit status --version <versie-id>
python energievergelijker.py version publish --version <versie-id>
```

| Groep | Acties |
| --- | --- |
| `source` | `download --year`, `list --year` |
| `raw` | `verify --version`, `status` |
| `staging` | `parse --version [--only vtest\|tariffs\|curves\|all] [--overwrite]`, `refine --version [--postcode] [--segment woning\|onderneming] [--energy elektriciteit\|gas] [--matrix] [--no-download] [--browser chrome\|firefox] [--show]` |
| `market` | `sync --start --end` |
| `audit` | `status`, `approve`, `golden`, `set-golden`, `sanity`, `sample` |
| `version` | `publish --version` |
| `db` | `init`, `import --version [--gemeente] [--overwrite]`, `status` |
| `paths` | *(geen actie)* |

Elk commando ondersteunt ook `--json` voor machineleesbare output.

`staging refine` scrapet de live vergelijkingstool op vtest.be via Selenium
(vereist een lokale Chrome of Firefox, meegeïnstalleerd via de
`scrape`-extra hierboven). `--segment`/`--energy` kiezen één van de vier
categorieën (woning/onderneming × elektriciteit/gas); `--matrix` doorloopt
alle 4 × de 8 DNB-representatieve postcodes (32 combinaties, met een pauze
ertussen uit respect voor de site) en voegt de resultaten samen. Per
contract wordt naast de metadata ook de volledige kostenopbouw opgeslagen
(vtest.be's eigen berekening, incl. een Nettarieven- en Heffingen-uitsplitsing).

## Dataversies

Elke ingest-run krijgt een versie-id (`YYYYMMDDTHHMMSSZ-<8hex>`) en doorloopt
`data/raw/` → `data/staging/` → `data/versions/`, met `data/current.txt` als
pointer naar de actieve versie. `python energievergelijker.py paths` toont de
gebruikte mappen en de actieve versie.

## Heffingen-masterdata

Heffingen en btw (`config/heffingen/*.toml`) zijn handmatig onderhouden
masterdata, geen scraper-output — elk bestand vermeldt zijn eigen bron. Dit
is wél gecommit (in tegenstelling tot `data/`), en wordt geladen via
`HeffingenRepository.load(...)`. Zie `CLAUDE.md` voor detail.
