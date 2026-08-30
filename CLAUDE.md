# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install (editable, with test dependencies)
pip install -e ".[test]"

# Run all tests
pytest -q

# Run a single test file
pytest tests/test_cli.py -q

# Run a single test by name
pytest tests/test_cli.py::test_paths_command_runs -q

# Run only unit tests (skip integration tests that need a local dataset)
pytest -q -m "not integration"

# Run the CLI
python energievergelijker.py --help
energievergelijker --help   # after pip install -e .

# Connect to the remote PostgreSQL database (Tailscale network only)
# psql -h 100.110.20.114 -U endsor -d energie_vlaanderen
```

Integration tests are skipped automatically when no local dataset is present. Set `ENERGIEVERGELIJKER_DATA_DIR` to point at a directory that contains `vtest/master_vast.csv` and `vtest/master_var_dyn.csv` to enable them.

## Architecture

The project has **two package roots**:

| Root | Package | Status |
|---|---|---|
| `src/energie_vlaanderen/` | `energie_vlaanderen` | Active, canonical |
| `energievergelijker_v3/` | `energievergelijker_v3` | Legacy, being migrated away from |

`energievergelijker.py` at the root is the entry point; it delegates to `src/energie_vlaanderen/cli.py`.

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
  vtest/         # Parser → Normalizer → Validator → Pipeline for V-test XLSX workbooks
  tariffs/       # Same pipeline shape for distribution tariff workbooks
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
infrastructure/
  csv.py         # Low-level CSV helpers
utility/
  constants.py   # D() (Decimal factory), LOCAL_TZ
  normalizer.py  # money(), dec() helpers
```

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

`Calculator` takes a `Profile` (usage figures, postcode, meter type) and a `Product` from `DataRepository`, then computes a `Cost` (supplier, grid, levies, injection credit, VAT). Grid costs use distribution network tariff data from the repository. Financial math uses `Decimal` throughout; no floats in cost calculations.

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
