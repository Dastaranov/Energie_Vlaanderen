# EnergieVergelijker

Modulaire energievergelijker voor Vlaanderen: haalt de officiële V-test- en
distributienettarieven op, verwerkt ze via versiegebonden pipelines, en zet ze
in een PostgreSQL-databank die als enige waarheid geldt.

De leidraad van dit project is dat **een verkeerd getal erger is dan een
crash**. Elke fout die het tot nu toe opgeleverd heeft was stil: een accijns van
13,60 in plaats van 46,00, Excel-serienummers als tijdstempel, een sanity-check
die zijn bestanden niet vond en toch "geslaagd" meldde. Vandaar de tijdsassen,
de harde fouten bij ontbrekende data, en de regel dat elk vastgelegd cijfer zijn
herkomst vermeldt.

## Vereisten

- **Python 3.11 of nieuwer.** De masterdata wordt met `tomllib` ingelezen; op
  3.10 loopt de import stuk.
- Een lokale **Chrome of Firefox** voor de commando's die vtest.be scrapen
  (`staging refine`, `staging calibrate`).
- Toegang tot de PostgreSQL-databank via **Tailscale**, voor de `db`-commando's
  en `market sync`.

## Installatie

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[test,db,scrape]"
```

Installeer altijd mét de `db`-extra, ook als je niet naar de databank schrijft:
vier testmodules importeren SQLAlchemy en falen anders al bij het inlezen. Ze
draaien op SQLite in het geheugen en hebben geen server nodig.

Maak daarnaast een `.env` in de projectroot (staat bewust niet in git):

```plain text
ENTSOE_API_KEY=...
DB_HOST=100.110.20.114
DB_NAME=energie_vlaanderen
DB_USER=...
DB_PASSWORD=...
```

Zonder `.env` blijft de CLI bruikbaar; enkel `market sync`, de `db`-commando's
en de bijhorende dashboardvelden werken dan niet.

Controleer de installatie:

```bash
pytest -q -m "not integration"     # ~395 tests, ~6 seconden
python energievergelijker.py paths # toont de datamappen en de actieve versie
```

## Van nul tot een gevulde databank

De volledige route, in volgorde. Elke stap geeft exitcode 0 bij succes en 2 bij
een verwachte fout; alles daarbuiten is een bug.

```bash
# 1. Databankschema aanleggen (eenmalig)
energievergelijker db init

# 2. Bronbestanden ophalen — levert een versie-id terug
energievergelijker source download --year 2026

# 3. Werkboeken inlezen naar staging/
energievergelijker staging parse --version <id>

# 4. De live vergelijkingstool scrapen (Selenium, ~30 min voor de volle matrix)
energievergelijker staging refine --version <id> --matrix

# 5. Heffingen terugrekenen uit vtest.be (~13 min, Selenium)
energievergelijker staging calibrate --version <id>

# 6. Controleren
energievergelijker audit sanity  --version <id>   # plausibiliteit
energievergelijker audit golden  --version <id>   # cel voor cel vs. het XLSX
energievergelijker audit heffingen                # structuur van de masterdata

# 7. Goedkeuren en publiceren
energievergelijker audit approve   --version <id>
energievergelijker version publish --version <id>

# 8. Toetsen dat bestanden en databank hetzelfde zeggen
energievergelijker db verify
```

Stap 8 is niet optioneel. `version publish` doet drie dingen die niet uit elkaar
mogen lopen — de kopie in `versions/`, de rijen in de databank, en
`current.txt` — en `db verify` is wat dat vaststelt. Faalt hij met exitcode 2,
dan is de publicatie niet af.

### Over stap 4: scrape gefaseerd

Doe `--matrix` liefst niet in één ruk. Op 2026-09-01 leverde vtest.be na een dag
intensief scrapen zelf afgekapte resultaten — 744 producten in plaats van 1880,
zonder dat er iets misging. De matrix meldt truncatie nu zelf, maar voorkomen is
beter: verdeel de 32 combinaties met `--segment` en `--energy` over meerdere
nachten.

## De terugkerende rondes

**Maandelijks.** VREG publiceert nieuwe V-test-data rond de 28e en nieuwe
energieprijscurves eind van de voorgaande maand. `scripts/check_bronnen.py`
merkt ze op; de route is dan stap 2 → 8 hierboven.

**Jaarlijks.** Zie **`docs/jaarwissel 2026-2027.md`**. De accijnzen, het
vervoerstarief en de distributienettarieven wisselen per 1 januari, en de eerste
twee doen dat *stil*: zonder nieuwe rij rekent de repository gewoon door met het
laatst bekende regime. Het document zet per bestand op een rij wat er nagekeken
moet worden, met de bron, het commando en waaraan je ziet dat het af is.

## Gebruik

**Interactieve shell** — zonder argumenten start een dashboard en een prompt,
zodat je niet telkens `python energievergelijker.py` hoeft te herhalen:

```bash
python energievergelijker.py
Energie_vlaanderen >> raw status
Energie_vlaanderen >> staging parse --version <versie-id> --only vtest
Energie_vlaanderen >> exit
```

**Eenmalige commando's** — voor scripts en CI, vorm `<groep> <actie> [opties]`.
Elk commando ondersteunt `--json` voor machineleesbare output.

| Groep | Acties |
| --- | --- |
| `source` | `download --year`, `list --year` |
| `raw` | `verify --version`, `status` |
| `staging` | `parse --version [--only vtest\|tariffs\|curves\|all] [--overwrite]`, `refine --version [--postcode] [--segment] [--energy] [--matrix] [--met-contractdetails] [--browser]`, `calibrate --version [--postcode]` |
| `market` | `sync --start --end [--no-api]` |
| `audit` | `status`, `approve`, `golden`, `set-golden`, `sanity`, `sample` (alle `--version`), `heffingen [--datum] [--streng]` |
| `version` | `publish --version [--keep-staging] [--force] [--skip-db] [--db-overwrite]` |
| `db` | `init`, `import --version [--overwrite] [--gemeente]`, `verify`, `status` |
| `paths` | *(geen actie)* |

`staging refine` scrapet de live vergelijkingstool op vtest.be.
`--segment`/`--energy` kiezen één van de vier categorieën (woning/onderneming ×
elektriciteit/gas); `--matrix` doorloopt alle vier × de acht
DNB-representatieve postcodes en voegt de resultaten samen. Per contract wordt
naast de metadata ook de volledige kostenopbouw opgeslagen — vtest.be's eigen
berekening, inclusief zijn Nettarieven- en Heffingen-uitsplitsing. Dat is
meteen de kruiscontrole op onze eigen pipelines.

## Dataversies en de databank

Elke ingest-run krijgt een versie-id (`YYYYMMDDTHHMMSSZ-<8hex>`) en doorloopt
`data/raw/` → `data/staging/` → `data/versions/`, met `data/current.txt` als
pointer naar de actieve versie.

**De databank is het eindstation.** `version publish` kopieert de versie naar
`versions/`, importeert ze naar PostgreSQL en activeert ze — één handeling, met
terugdraaien als de import faalt. Zo kan `current.txt` nooit naar een versie
wijzen die de databank niet heeft.

Publiceren vereist een goedgekeurde versie (`audit approve`); `--force` is de
bewuste uitzondering, `--skip-db` publiceert zonder databank en laat bestanden
en databank dan bewust uiteenlopen — `db verify` zegt dat ook.

Tariefwijzigingen worden gehistoriseerd (SCD type 2): een nieuwe prijs sluit de
vorige af in plaats van ze te overschrijven, zodat een berekening over een
oudere maand nog steeds klopt.

## Masterdata en tariefbewaking

Heffingen, btw en het vervoerstarief (`config/heffingen/*.toml`,
`config/nettarieven/*.toml`) zijn handmatig onderhouden masterdata, geen
scraper-output — elk bestand vermeldt zijn eigen bron en draagt een tijdsas.
Dit staat wél in git, in tegenstelling tot `data/`.

Omdat er geen scrapebare bron voor heffingen bestaat, worden de cijfers
*teruggerekend* uit vtest.be zelf: `staging calibrate` vraagt hetzelfde profiel
op bij een reeks jaarverbruiken en leidt uit VREG's eigen kostenopbouw de
tariefstructuur af. Elk recht stuk van de kostenfunctie is één verbruiksschijf,
de helling het tarief in EUR/MWh, een knik een schijfgrens.

```bash
energievergelijker audit heffingen                     # structuur, offline
energievergelijker staging calibrate --version <id>    # ~13 min, Selenium
python scripts/check_tarieven.py --versie <id>         # config vs. vtest.be
python scripts/check_bronnen.py                        # nieuwe VREG-bestanden?
```

`.github/workflows/bronbewaking.yml` draait de laatste twee dagelijks en maakt
er een issue van. De agent `.claude/agents/tariefwacht.md` en de skill
`.claude/skills/tariefcontrole/` beschrijven de werkwijze bij een afwijking.

**Twee valkuilen bij het vergelijken.** De masterdata staat *exclusief* btw
terwijl publieke communicatie doorgaans inclusief 6% noemt — een verschil van
precies factor 1,06 is een eenheidsverwarring, geen afwijking. En de
accijnshervorming van 2023 gold alleen voor gezinnen; zakelijke tarieven op het
residentiële regime leggen is een fout die hier al eens gemaakt is.

**vtest.be is de leidende bron** waar hij afwijkt van de regulator. Op
woningproducten past hij 1,5565 EUR/MWh gastransport toe waar CREG 1,56
vastlegt — 0,22% lager, oorzaak onderzocht en niet gevonden. De masterdata
volgt vtest, omdat deze toepassing vergelijkt met wat die tool een klant toont.

## Testen

```bash
pytest -q                       # volledige suite
pytest -q -m "not integration"  # zonder tests die een lokale dataset vereisen
pytest tests/test_maandpiek.py -q
```

Integratietests worden automatisch overgeslagen als er geen lokale dataset is.
Zet `ENERGIEVERGELIJKER_DATA_DIR` naar een map met `vtest/master_vast.csv` en
`vtest/master_var_dyn.csv` om ze aan te zetten.

**Eén regel telt hier zwaarder dan de rest: een test die een getal vastlegt,
moet in het bestand zelf zeggen waar dat getal vandaan komt.** Zonder herkomst
is een assertie een bewering; met herkomst is het een controle. En een falende
test is daarom eerst een vraag — wijzigde het tarief, of brak de code? De
bronvermelding zegt waartegen je moet toetsen. Een assertie aanpassen tot de
test slaagt is hier de gevaarlijkste reflex die er is.

Zie `CLAUDE.md` voor de volledige laagstructuur, de ontwerpregels uit Manifest
3.0 en de achtergrond bij die testregel. `docs/MOC.md` is het startpunt van de
documentatie.
