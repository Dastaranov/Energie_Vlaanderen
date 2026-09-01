# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install (editable, with all dependencies)
pip install -e ".[test,db,scrape]"

# Run all tests
pytest -q

# Run a single test file
pytest tests/test_cli.py -q

# Run a single test by name
pytest tests/test_cli.py::test_paths_command_runs -q

# Run only unit tests (skip integration tests that need a local dataset)
pytest -q -m "not integration"

# Interactive shell (no arguments): opstart dashboard, then a prompt for
# repeated commands without repeating "energievergelijker" each time.
python energievergelijker.py

# One-shot, non-interactive form (for scripts/CI) — <groep> <actie> [opties]
python energievergelijker.py --help
python energievergelijker.py staging parse --version <id> --only vtest
energievergelijker --help   # after pip install -e .

# Connect to the remote PostgreSQL database (Tailscale network only)
# psql -h 100.110.20.114 -U endsor -d energie_vlaanderen
```

Integration tests are skipped automatically when no local dataset is present. Set `ENERGIEVERGELIJKER_DATA_DIR` to point at a directory that contains `vtest/master_vast.csv` and `vtest/master_var_dyn.csv` to enable them.

### CLI command groups

The CLI is grouped as `<groep> <actie> [opties]`; every action also accepts `--json`:

| Groep | Acties |
|---|---|
| `source` | `download --year`, `list --year` |
| `raw` | `verify --version`, `status` |
| `staging` | `parse --version [--only vtest\|tariffs\|curves\|all] [--overwrite]`, `refine --version [--postcode] [--segment woning\|onderneming] [--energy elektriciteit\|gas] [--matrix] [--no-download] [--browser chrome\|firefox] [--show]`, `calibrate --version [--postcode] [--browser] [--show]` |
| `market` | `sync --start --end [--no-api]` |
| `audit` | `status`, `approve`, `golden`, `set-golden`, `sanity`, `sample` (all `--version`), `heffingen [--datum] [--streng]` (geen versie nodig) |

`audit golden` vergelijkt de gestagede CSV's cel voor cel met het bron-XLSX. Voor elektriciteit dekt dat drie bestanden — afname, injectie én hoogspanning. Dat laatste ontbrak: de audit liep enkel over afname en injectie, waardoor 528 van de 776 elektriciteitsrijen nooit tegen het werkboek gelegd werden. Bovendien vergeleek ze de volledige verse normalisatie met alleen het afname-bestand, wat 108 verschillen meldde die geen van alle echt waren.
| `version` | `publish --version [--keep-staging] [--force] [--skip-db] [--db-overwrite]` |
| `db` | `init`, `import --version [--overwrite] [--gemeente]`, `verify`, `status` |
| `paths` | *(no action)* |

Running `energievergelijker` with no arguments starts the interactive shell instead of erroring; `energievergelijker <groep> <actie>` keeps working exactly as a normal one-shot CLI call for scripts.

`staging refine` scrapes the live vtest.be comparison tool via Selenium (requires `pip install -e ".[scrape]"` and a local Chrome or Firefox). `--segment`/`--energy` pick one of the four categories (woning/onderneming × elektriciteit/gas); `--matrix` runs all 4 × the 8 DNB-representative postcodes (32 combinations, one courtesy pause between each) and merges the results. Output per combination: `vtest_products_<segment>_<energy>_<postcode>.csv` (contract metadata) and `vtest_product_components_<segment>_<energy>_<postcode>.csv` (the full per-contract cost breakdown extracted from vtest.be's own `data-productinvoicestring`, incl. its own Nettarieven/Heffingen calculation — a useful cross-check against the tariffs/heffingen pipelines).

### Tariefbewaking

De masterdata in `config/heffingen/` is handgeschreven en heeft geen scrapebare
bron. Ze wordt daarom *teruggerekend* uit vtest.be, de officiële
vergelijkingstool van VREG: `staging calibrate` vraagt hetzelfde profiel op bij
een reeks jaarverbruiken en leidt uit VREG's eigen kostenopbouw
(`data-productinvoicestring`) de tariefstructuur af — elk recht stuk van de
kostenfunctie is één verbruiksschijf, de helling het tarief in EUR/MWh, een
knik een schijfgrens.

```bash
energievergelijker audit heffingen                     # structuur, offline
energievergelijker staging calibrate --version <id>    # ~13 min, Selenium
python scripts/check_tarieven.py --versie <id>         # config vs. vtest.be
python scripts/check_bronnen.py                        # nieuwe VREG-bestanden?
```

`config/bronregister.toml` legt vast welke bronbestanden de pipeline verwerkt
heeft; `.github/workflows/bronbewaking.yml` vergelijkt dat dagelijks met de
VREG-pagina's en maakt er een issue van. De agent `.claude/agents/tariefwacht.md`
en de skill `.claude/skills/tariefcontrole/` beschrijven de werkwijze bij een
afwijking.

**Let op bij vergelijken**: de masterdata staat exclusief btw, publieke
communicatie noemt bedragen doorgaans inclusief 6%. Een verschil van precies
factor 1,06 is een eenheidsverwarring, geen afwijking.

## Architecture

The package lives in `src/energie_vlaanderen/`. `energievergelijker.py` at the root is the entry point; it delegates to `src/energie_vlaanderen/cli/` (a package, not a single module).

### CLI package (`src/energie_vlaanderen/cli/`)

```
__init__.py    # build_parser(), main() — re-exports the public API used by tests/pyproject
__main__.py    # `python -m energie_vlaanderen.cli`
groups.py      # builds the group→action parser tree (source/raw/staging/market/audit/version/db/paths)
shell.py       # interactive REPL: opstart/werking dashboards, generic ✓/!/✗ result rendering
status.py      # dashboard data sources (live where possible, honest placeholders otherwise)
paths_cmd.py   # `paths` — run_paths, show_paths
ingest.py      # source/raw/staging/market/version handlers (incl. run_staging_parse)
audit.py       # audit group handlers
db.py          # db group handlers
args.py        # add_version_arg(), add_json_flag() — shared argparse registration helpers
output.py      # print_kv(), print_json(), emit() — shared text/--json output helpers
helpers.py     # fail(), require_valid_raw_version(), resolve_artifact(), positive_integer()
```

Business logic lives in `paths_cmd.py`/`ingest.py`/`audit.py`/`db.py`; `groups.py` only decides the CLI's *shape* (which group/action maps to which handler). Handlers keep the signature `(args: argparse.Namespace, settings: Settings) -> int` and never call `Settings.load()` themselves — only `main()` does, so tests can call handlers directly with a hand-built `Settings`. Exit codes: `0` success, `2` an expected/business failure (invalid version, missing staging dir, pipeline rejection, ...); anything else is an uncaught bug (default Python traceback, exit 1).

`main(argv=None)`: with no arguments it starts the interactive shell (`shell.run_shell`); with arguments it parses and dispatches exactly as before — one-shot invocations never go through the shell's rendering.

### Layer structure (`src/energie_vlaanderen/`)

```
domain/          # Pure data models: Profile, Product, Cost
settings.py      # Settings dataclass, env-var loading, project root discovery
data/
  paths.py       # DataPaths: versioned data directory layout (raw/, staging/, versions/, current.txt)
  repository.py  # DataRepository: reads canonicalized vtest CSVs into Product objects
calculation/
  calculator.py  # Calculator: grid_cost(), supplier_cost(), full cost breakdown
ingest/
  sources.py     # VnrSourceScraper: scrapes XLSX download links from vlaamsenutsregulator.be
  downloader.py  # ArtifactDownloader: downloads XLSX files safely
  raw_store.py   # RawStore: persists raw downloads with version IDs
  vtest/         # Two separate paths for the same domain:
                 #   1) bulk export: workbook.py → normalizer.py → validator.py → pipeline.py
                 #      (parses the VREG "V-test data" XLSX into master_vast/var_dyn.csv)
                 #   2) live scrape: html_downloader.py (Selenium, vtest.be) → product_parser.py
                 #      (BeautifulSoup, incl. the data-productinvoicestring cost breakdown) →
                 #      product_normalizer.py → refine_pipeline.py (one segment/energy/postcode) →
                 #      refine_matrix.py (all 32 combinations) → product_matcher.py (best-effort
                 #      vreg_id ↔ Handelsnaam/Productnaam koppeling met de bulk export)
                 #   3) calibratie: calibration.py — rekent heffingen- en nettariefstructuren
                 #      terug uit vtest.be door hetzelfde profiel bij meerdere verbruiken op
                 #      te vragen; de enige geautomatiseerde controle op config/heffingen/
  tariffs/       # Same pipeline shape as the vtest bulk export, for distribution tariff workbooks
  curves/        # Pipeline for energy price curve workbooks
market/
  entsoe.py      # EntsoeMarketData: day-ahead prijzen, met cache in JSON. Valt bij een
                 # storing bij ENTSO-E luidruchtig terug op energy_charts.py; elke rij
                 # draagt een `source`-veld zodat de herkomst traceerbaar blijft
  energy_charts.py # Tweede bron (Fraunhofer ISE, geen API-sleutel). Geverifieerd
                 # identiek aan ENTSO-E: 958 overlappende kwartierpunten, max
                 # verschil 0,0000 EUR/MWh
  sync.py        # MarketSyncManager: houdt de lokale prijscache actueel
metering/
  fluvius_csv.py # FluviusIntervals: parses Fluvius quarter-hour CSV exports
audit/
  manager.py     # ApprovalManager: quarantine → approve → activate version lifecycle
  sanity.py      # SanityChecker: cross-checks on processed data
  sampler.py     # DataSampler: spot-check samples
  golden.py      # Golden master management
heffingen/
  models.py      # AccijnsSchijf/AccijnsTabel, EnergiefondsTarief, BtwTarief dataclasses
  repository.py  # HeffingenRepository: loads config/heffingen/*.toml, progressive schijven-berekening
                 # op de tarieven die op een peildatum gelden; raises HeffingenError instead of
                 # silently defaulting to 0 for missing data
  validation.py  # Structurele controle (gaten/overlappingen/ontbrekende jaren) — `audit heffingen`
infrastructure/
  csv.py         # Low-level CSV helpers
  db/            # SQLAlchemy Core schema.py + importer.py; Alembic migrations in db/migrations/versions/
utility/
  constants.py   # D() (Decimal factory), LOCAL_TZ, DNB_CODES
  normalizer.py  # money(), dec() helpers
```

### Masterdata (`config/`)

`config/heffingen/*.toml` — hand-maintained (not scraped) source-of-truth for levies and VAT,
each with a `bron` field citing where the figures come from:
`bijzondere_accijns_elektriciteit.toml` en `bijzondere_accijns_aardgas.toml`
(teruggerekend uit vtest.be, zie Tariefbewaking), `bijdrage_energiefonds.toml`
(vlaanderen.be, 2022-2026), `btw.toml`. Loaded via `HeffingenRepository.load(config_dir)` —
alle `bijzondere_accijns_*.toml` worden ingelezen, de energievorm staat in het bestand zelf.

De accijnstabellen dragen een **tijdsas**: elke `[[schijf]]` heeft een `geldig_vanaf` en een
`geverifieerd`-vlag. De bijzondere accijns wijzigde binnen 2026 (47,4811 → 46,00 EUR/MWh op
01/08), dus een berekening geeft een peildatum mee en de repository kiest het regime met de
meest recente ingangsdatum. Regimes worden nooit vermengd. Voor datums vóór het oudste regime
volgt een `HeffingenError` in plaats van een verkeerd tarief.

`config/nettarieven/transport_aardgas.toml` — het vervoerstarief van Fluxys, de doorrekening
van het vervoersnet op een distributienetaansluiting. Staat in geen VREG-werkboek (die dekken
alleen de distributie) en ontbrak daardoor volledig, wat elke gasfactuur ongeveer 25 EUR per
jaar te laag maakte. Geladen via `TransportTariefRepository.load(config_dir)`, met dezelfde
tijdsas en verificatievlag als de accijnzen.

**Let op**: vtest.be past op gewone woningproducten 1,5565 EUR/MWh toe waar CREG 1,56
vastlegt — 0,22% lager, oorzaak niet vastgesteld. De masterdata draagt het officiële cijfer;
`scripts/check_tarieven.py` pint de afwijking vast zodat ze bekend blijft en opvalt als ze
verandert.

`config/bronregister.toml` — welke bronbestanden de pipeline verwerkt heeft, als vaste
referentie voor de bronbewaking (`data/` staat niet in git).

Committed to git, unlike `data/` (mostly `.gitignore`d generated pipeline output).

### Marktprijzen: twee bronnen

ENTSO-E's Transparency Platform is het officiële publicatiekanaal voor
day-ahead prijzen, maar het is een *rapporteringsplatform* en staat los van de
markt. Het kan in onderhoud zijn terwijl de prijzen wel degelijk bestaan — dat
gebeurde op 2026-08-31, toen zowel de API-host als de webinterface een
onderhoudspagina serveerden terwijl Elia's open data en energy-charts.info
gewoon live Belgische data teruggaven.

`EntsoeMarketData` valt daarom terug op `EnergyChartsMarketData` (Fraunhofer
ISE, geen API-sleutel). Die terugval is bewust luidruchtig: er wordt
gewaarschuwd, en elke rij in de cache draagt een `source`-veld. Wie enkel de
officiële publicatie wil, zet `allow_fallback=False` en krijgt een harde fout.

De twee bronnen zijn tegen elkaar gelegd over 958 overlappende kwartierpunten
(10-14 augustus 2026): elk punt identiek, maximaal verschil 0,0000 EUR/MWh.

### Data versioning

Every ingest run produces a version ID (`YYYYMMDDTHHMMSSZ-<8hex>`). Data flows through:

1. `data/raw/<version_id>/` — raw downloaded artifacts
2. `data/staging/<version_id>/` — intermediate processing
3. `data/versions/<version_id>/` — fully processed and validated
4. `data/current.txt` + de databank — de actieve versie, op beide plekken

**De databank is het eindstation.** `current.txt` en `data_version` in
PostgreSQL horen één op één hetzelfde te zeggen; `energievergelijker db verify`
toetst dat en faalt met exitcode 2 bij elk verschil.

De volledige levenscyclus:

```bash
energievergelijker source download --year 2026        # → raw/
energievergelijker staging parse    --version <id>    # → staging/
energievergelijker staging refine   --version <id> --matrix
energievergelijker staging calibrate --version <id>   # tarieven terugrekenen
energievergelijker audit sanity     --version <id>    # plausibiliteit
energievergelijker audit golden     --version <id>    # cel-voor-cel vs. XLSX
energievergelijker audit approve    --version <id>    # goedkeuring
energievergelijker version publish  --version <id>    # versions/ + databank + current.txt
energievergelijker db verify                          # komen ze overeen?
```

`version publish` is één handeling met drie gevolgen die niet uit elkaar mogen
lopen: de kopie in `versions/`, de rijen in de databank, en `current.txt`.
Faalt de databankimport, dan wordt de versiemap teruggedraaid en blijft de
vorige actieve versie staan — `current.txt` wijst nooit naar een versie die de
databank niet heeft.

Twee dingen die eerder niet klopten en nu wel:

- **`audit approve` dwong niets af.** `publish` raadpleegde de auditstatus
  niet, zodat een versie in quarantaine gewoon actief kon worden. Publiceren
  weigert nu op een niet-goedgekeurde versie; `--force` is de bewuste
  uitzondering.
- **`db import` las enkel uit `staging/`, terwijl `publish` staging opruimt.**
  Publiceren maakte een versie daarmee onimporteerbaar. De import zoekt nu
  eerst in `versions/` en valt terug op `staging/`.

`--skip-db` publiceert zonder databank; dan lopen bestanden en databank
bewust uiteen en zegt `db verify` dat ook.

`DataPaths.activate()` writes the pointer. `DataPaths.current_data_dir()` resolves it for callers.

### Ingest pipelines

Each ingest domain (vtest, tariffs, curves) follows the same three-stage pattern:
`Workbook parser → Normalizer → Validator → Pipeline` that orchestrates them and writes output CSVs.

### Calculator

`Calculator` takes a `Profile` (usage figures, postcode, meter type), a `Product` from `DataRepository`, and a `HeffingenRepository`, then computes a `Cost` (supplier, grid, levies, injection credit, VAT). Grid costs use distribution network tariff data from the repository; levies come from `config/heffingen/` via progressive schijven — `calculate()` raises without a `HeffingenRepository` rather than silently defaulting levies to 0, and for gas (not yet covered by the heffingen data). Only laagspanning is wired up so far; MS/HS tariff and levy data exists but the calculator won't use it until that segment is formally validated (see Manifest §7.2/§12). Financial math uses `Decimal` throughout; no floats in cost calculations.

### Key design rules (from Manifest 3.0)

- `Decimal` only for financial values — never `float`.
- No silent data loss: missing intervals, gaps, and DST anomalies must be reported.
- Provenance is mandatory on every derived value — en op elk vastgelegd getal
  in een test (zie "Tests: herkomst boven aantal").
- Middle/high-voltage tariffs must not reuse residential formulas.
- The billing engine, forecasting, and active control are separate domains.

### Tests: herkomst boven aantal

De testsuite telt ongeveer 300 tests en draait in 8 seconden. Het aantal is
geen probleem en snoeien erin is geen doel — de kosten zitten niet in de
runtime.

**De regel die hier wél telt: een test die een getal vastlegt, moet in het
bestand zelf zeggen waar dat getal vandaan komt.**

Waarom die regel bestaat: `test_heffingen_repository.py` bevatte maandenlang

```python
assert eerste.bijzondere_accijns_eur_mwh == D("13.60")
```

Groen, elke run. Het cijfer was fout — de werkelijke bijzondere accijns voor
gezinnen is 46,00 EUR/MWh — en de test maakte die fout *geverifieerd*. Dat is
erger dan geen test: zonder die assertie was er twijfel geweest.

Elke fout die dit project heeft opgeleverd was van dezelfde soort: een stil
verkeerd getal, geen crash. De accijns van 13,60. Vijftigduizend
Excel-serienummers als tijdstempel. Een sanity-check die zijn bestanden niet
vond en toch "geslaagd" meldde. Een vreg_id die op twee producten belandde.
Geen daarvan gooit een exception; een testsuite is het enige goedkope
mechanisme dat merkt wanneer ze terugkeren.

Concreet betekent de regel:

```python
def test_residentieel_elektriciteitstarief_is_het_gekalibreerde_tarief(repo):
    # 46,00 EUR/MWh excl. btw is teruggerekend uit vtest.be zelf
    # (7 verbruikspunten, residu 0,00 EUR) en komt overeen met de
    # 48,76 EUR/MWh incl. btw die de officiële communicatie noemt.
    (schijf,) = repo.accijns_schijven("elektriciteit", "niet_zakelijk", date(2026, 8, 31))
    assert schijf.bijzondere_accijns_eur_mwh == D("46.0000")
```

Zonder die herkomst is een assertie een bewering; met herkomst is het een
controle. Een getal waarvan de herkomst niet op te schrijven valt, hoort niet
in een assertie thuis — dan is het een aanname en moet het eerst gekalibreerd
of opgezocht worden.

Twee gevolgen voor het dagelijks werk:

- **Een falende test is eerst een vraag, geen taak.** Wijzigde het tarief, of
  brak de code? De bronvermelding in de test zegt waartegen je moet toetsen.
  Een assertie aanpassen tot de test slaagt is hier de gevaarlijkste
  reflex die er is.
- **Regressietests weggooien is duurder dan ze houden.**
  `tests/test_p0_regressions.py` bewaakt met twee tests dat een nulprijs geen
  ontbrekende prijs is en dat decimaaltekst behouden blijft. Dat zijn
  littekens van deze foutklasse.

Wat wél opgeruimd mag worden, en pas op het juiste moment: de tests die aan de
`Calculator` hangen (`test_energievergelijker.py`,
`test_calculator_heffingen.py`) gaan mee met de herschrijving daarvan. Tot dan
documenteren ze het bedoelde gedrag dat die herschrijving moet reproduceren —
inclusief de tariefwissel op 01/08/2026. Weggooien ná de herschrijving, niet
ervoor.

### Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `ENERGIEVERGELIJKER_DATA_DIR` | `<project_root>/data` | Override data root |
| `ENERGIEVERGELIJKER_REQUEST_TIMEOUT` | `60` | HTTP timeout in seconds |
| `ENERGIEVERGELIJKER_VTEST_PAGE_URL` | vlaamsenutsregulator.be URL | V-test scrape target |
| `ENERGIEVERGELIJKER_TARIFF_PAGE_URL` | vlaamsenutsregulator.be URL | Tariff scrape target |
| `ENERGIEVERGELIJKER_MAX_DOWNLOAD_BYTES` | `52428800` | Download size cap |

`ENTSOE_API_KEY` and database credentials are in `.env` (not committed to git beyond `.env` itself).

### User configuration

`gebruiker.toml` in the project root holds the personal profile (postcode, consumption, Fluvius CSV path, analysis settings). The CLI reads this when no explicit flags override it.
