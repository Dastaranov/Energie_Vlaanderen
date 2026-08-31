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
| `staging` | `parse --version [--only vtest\|tariffs\|curves\|all] [--overwrite]`, `refine --version [--postcode] [--segment woning\|onderneming] [--energy elektriciteit\|gas] [--matrix] [--no-download] [--browser chrome\|firefox] [--show]` |
| `market` | `sync --start --end [--no-api]` |
| `audit` | `status`, `approve`, `golden`, `set-golden`, `sanity`, `sample` (all `--version`) |
| `version` | `publish --version [--keep-staging]` |
| `db` | `init`, `import --version`, `status` |
| `paths` | *(no action)* |

Running `energievergelijker` with no arguments starts the interactive shell instead of erroring; `energievergelijker <groep> <actie>` keeps working exactly as a normal one-shot CLI call for scripts.

`staging refine` scrapes the live vtest.be comparison tool via Selenium (requires `pip install -e ".[scrape]"` and a local Chrome or Firefox). `--segment`/`--energy` pick one of the four categories (woning/onderneming × elektriciteit/gas); `--matrix` runs all 4 × the 8 DNB-representative postcodes (32 combinations, one courtesy pause between each) and merges the results. Output per combination: `vtest_products_<segment>_<energy>_<postcode>.csv` (contract metadata) and `vtest_product_components_<segment>_<energy>_<postcode>.csv` (the full per-contract cost breakdown extracted from vtest.be's own `data-productinvoicestring`, incl. its own Nettarieven/Heffingen calculation — a useful cross-check against the tariffs/heffingen pipelines).

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
  tariffs/       # Same pipeline shape as the vtest bulk export, for distribution tariff workbooks
  curves/        # Pipeline for energy price curve workbooks
market/
  entsoe.py      # EntsoeMarketData: reads ENTSO-E day-ahead prices from local JSON
  sync.py        # MarketSyncManager: keeps the local ENTSO-E cache up to date
metering/
  fluvius_csv.py # FluviusIntervals: parses Fluvius quarter-hour CSV exports
audit/
  manager.py     # ApprovalManager: quarantine → approve → activate version lifecycle
  sanity.py      # SanityChecker: cross-checks on processed data
  sampler.py     # DataSampler: spot-check samples
  golden.py      # Golden master management
heffingen/
  models.py      # AccijnsSchijf/AccijnsTabel, EnergiefondsTarief, BtwTarief dataclasses
  repository.py  # HeffingenRepository: loads config/heffingen/*.toml, progressive schijven-berekening;
                 # raises HeffingenError instead of silently defaulting to 0 for missing data
infrastructure/
  csv.py         # Low-level CSV helpers
  db/            # SQLAlchemy Core schema.py + importer.py; Alembic migrations in db/migrations/versions/
utility/
  constants.py   # D() (Decimal factory), LOCAL_TZ, DNB_CODES
  normalizer.py  # money(), dec() helpers
```

### Masterdata (`config/`)

`config/heffingen/*.toml` — hand-maintained (not scraped) source-of-truth for levies and VAT,
each with a `bron` field citing where the figures come from: `bijzondere_accijns_elektriciteit.toml`
(programmawet 25/12/2021, art. 39), `bijdrage_energiefonds.toml` (vlaanderen.be, 2022-2026),
`btw.toml`. Loaded via `HeffingenRepository.load(config_dir)`. Committed to git, unlike `data/`
(mostly `.gitignore`d generated pipeline output).

### Data versioning

Every ingest run produces a version ID (`YYYYMMDDTHHMMSSZ-<8hex>`). Data flows through:

1. `data/raw/<version_id>/` — raw downloaded artifacts
2. `data/staging/<version_id>/` — intermediate processing
3. `data/versions/<version_id>/` — fully processed and validated
4. `data/current.txt` — pointer to the active version (atomic file replace)

`DataPaths.activate()` writes the pointer. `DataPaths.current_data_dir()` resolves it for callers.

### Ingest pipelines

Each ingest domain (vtest, tariffs, curves) follows the same three-stage pattern:
`Workbook parser → Normalizer → Validator → Pipeline` that orchestrates them and writes output CSVs.

### Calculator

`Calculator` takes a `Profile` (usage figures, postcode, meter type), a `Product` from `DataRepository`, and a `HeffingenRepository`, then computes a `Cost` (supplier, grid, levies, injection credit, VAT). Grid costs use distribution network tariff data from the repository; levies come from `config/heffingen/` via progressive schijven — `calculate()` raises without a `HeffingenRepository` rather than silently defaulting levies to 0, and for gas (not yet covered by the heffingen data). Only laagspanning is wired up so far; MS/HS tariff and levy data exists but the calculator won't use it until that segment is formally validated (see Manifest §7.2/§12). Financial math uses `Decimal` throughout; no floats in cost calculations.

### Key design rules (from Manifest 3.0)

- `Decimal` only for financial values — never `float`.
- No silent data loss: missing intervals, gaps, and DST anomalies must be reported.
- Provenance is mandatory on every derived value.
- Middle/high-voltage tariffs must not reuse residential formulas.
- The billing engine, forecasting, and active control are separate domains.

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
