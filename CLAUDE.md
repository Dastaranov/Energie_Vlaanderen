# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

Python 3.11 of nieuwer. De masterdata wordt met `tomllib` ingelezen en dat zit pas
vanaf 3.11 in de standaardbibliotheek; op 3.10 loopt de import stuk. CI test 3.11
en 3.12 — de ondergrens en de gebruikte versie.

Installeer altijd mét de `db`-extra, ook als je niet naar de databank schrijft:
vier testmodules importeren SQLAlchemy en falen anders bij het inlezen. Ze draaien
op SQLite in het geheugen en hebben geen server nodig.

De `profielen`-extra (`pyxlsb`) is enkel nodig om RLP0N/SLP-EX (.xlsb) te lezen —
SPP is .xlsx en werkt al met de basisinstallatie. Zonder deze extra faalt
`staging parse --only profielen` op die twee bronnen met een duidelijke foutmelding
i.p.v. een cryptische ImportError.

```bash
# Install (editable, with all dependencies)
pip install -e ".[test,db,scrape,profielen]"

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
| `staging` | `parse --version [--only vtest\|tariffs\|curves\|profielen\|all] [--overwrite] [--synergrid-version] [--jaar]`, `refine --version [--postcode] [--segment woning\|onderneming] [--energy elektriciteit\|gas] [--matrix] [--no-download] [--zonder-contractdetails] [--browser chrome\|firefox] [--show]`, `calibrate --version [--postcode] [--browser] [--show]` |
| `synergrid` | `list --year`, `download --year`, `verify --version`, `status` |
| `market` | `sync --start --end [--no-api]` |
| `audit` | `status`, `approve`, `golden`, `set-golden`, `sanity`, `sample` (all `--version`), `heffingen [--datum] [--streng]` (geen versie nodig) |

`audit golden` vergelijkt de gestagede CSV's cel voor cel met het bron-XLSX. Voor elektriciteit dekt dat drie bestanden — afname, injectie én hoogspanning. Dat laatste ontbrak: de audit liep enkel over afname en injectie, waardoor 528 van de 776 elektriciteitsrijen nooit tegen het werkboek gelegd werden. Bovendien vergeleek ze de volledige verse normalisatie met alleen het afname-bestand, wat 108 verschillen meldde die geen van alle echt waren.
| `version` | `publish --version [--keep-staging] [--force] [--skip-db] [--db-overwrite]` |
| `db` | `init`, `import --version [--overwrite] [--gemeente]`, `verify`, `status` |
| `gebruiker` | `toon [--toml]`, `controleer [--toml] [--hardware]`, `bereken --van --tot [--toml] [--version]` |
| `paths` | *(no action)* |

Running `energievergelijker` with no arguments starts the interactive shell instead of erroring; `energievergelijker <groep> <actie>` keeps working exactly as a normal one-shot CLI call for scripts.

`staging refine` scrapes the live vtest.be comparison tool via Selenium (requires `pip install -e ".[scrape]"` and a local Chrome or Firefox). `--segment`/`--energy` pick one of the four categories (woning/onderneming × elektriciteit/gas); `--matrix` runs all 4 × the 8 DNB-representative postcodes (32 combinations, one courtesy pause between each) and merges the results. Output per combination: `vtest_products_<segment>_<energy>_<postcode>.csv` (contract metadata) and `vtest_product_components_<segment>_<energy>_<postcode>.csv` (the full per-contract cost breakdown extracted from vtest.be's own `data-productinvoicestring`, incl. its own Nettarieven/Heffingen calculation — a useful cross-check against the tariffs/heffingen pipelines).

**`--browser` is standaard `firefox`, niet chrome.** Op 2026-09-02 bleek een volledige `--matrix`-run onder headless Chrome het onderneming-segment structureel af te kappen — telkens exact 20 producten (elektriciteit) of 10 (gas) op alle 8 postcodes, reproduceerbaar over twee onafhankelijke runs, ook na meer geduld bij het scrollen. Vier losse runs met Firefox (headless én zichtbaar) haalden telkens de volle lijst binnen (82/54). Geen timingprobleem dus, maar een renderverschil tussen de twee browsers bij vtest.be's lui-ladende resultatenlijst. Zie de toelichting in `ingest/vtest/html_downloader.py` bij het scroll-blok. `--browser chrome` blijft een keuze (`choices=("chrome", "firefox")`), maar gebruik die enkel bewust en controleer nadien de "Mogelijk onvolledig"-meldingen van `--matrix`.

`staging parse --only profielen` heeft, anders dan de andere drie doelen, een eigen `--synergrid-version` nodig naast de gewone `--version`: Synergrid heeft een eigen raw-store (`SynergridRawStore`, `data/raw/synergrid/<versie>/`) los van de VREG-raw-store, met een eigen jaarlijkse cadans. `--version` bepaalt enkel wáár de output landt (`staging/<versie>/profielen/`); `--synergrid-version` + `--jaar` bepalen wélke Synergrid-download verwerkt wordt. Daarom zit `profielen` bewust niet in `--only all` — de andere drie doelen hebben geen tweede versie-id nodig, `profielen` wel, en dat zou `all` een stille extra vereiste geven.

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
python scripts/check_bronnen.py                        # nieuwe VREG-/Synergrid-bestanden?
python scripts/verify_contract.py --leverancier ...    # een contract: CSV vs. databank
```

`verify_contract.py` vergelijkt één leverancierscontract rij voor rij tussen de
gestagede CSV's en de databank (exitcode 1 bij een afwijking, 2 als het contract
niet gevonden is). Het is het handmatige tegenhangertje van `audit golden`, en
het was het gereedschap waarmee de overstap naar de databank nagerekend is.

`config/bronregister.toml` legt vast welke bronbestanden de pipeline verwerkt
heeft; `.github/workflows/bronbewaking.yml` vergelijkt dat dagelijks met de
VREG- en Synergrid-pagina's en maakt er een issue van. De agent `.claude/agents/tariefwacht.md`
en de skill `.claude/skills/tariefcontrole/` beschrijven de werkwijze bij een
afwijking — beide gaan over tarieven/heffingen, niet over verbruiksprofielen
(zie hieronder), maar volgen wel hetzelfde stramien.

```bash
python scripts/check_energiefonds.py                   # config vs. vlaanderen.be
python scripts/check_energiefonds.py --html <kopie>    # zonder netwerk
python scripts/check_injectie_index.py                 # SPP-gewogen injectie-index
```

**De bijdrage op de energie stond op nul, en dat was fout.** De masterdata gaf
`energiebijdrage_eur_mwh = "0"` voor klantcategorie `niet_zakelijk`, met als
verantwoording dat vtest.be die post op 0,00 EUR zet. vtest.be *toont* hem
inderdaad niet — maar dat is iets anders dan dat hij nul is. Artikel 39 van de
programmawet van 25/12/2021 zet voor niet-zakelijk gebruik in élke schijf
"bijdrage op de energie: 1,9261 euro per MWh" (de wettekst staat in
`docs/research/tarief bijzonder accijns.md`), en een echte ENGIE-eindafrekening
rekent hem ook aan — als aparte regel náást de bijzondere accijns, dus niet
geïntegreerd maar additief. Op 6.817 kWh scheelde dat 13,13 EUR per jaar.

Dit is de ene plaats waar vtest.be **niet** leidend is: een wettekst en een
betaalde factuur die elkaar bevestigen wegen zwaarder dan een vergelijkingstool
die een post weglaat. Sinds de correctie reproduceert de heffingenberekening de
factuurregel "Toeslagen" exact — 336,81 EUR op 6.817 kWh — en
`tests/test_referentiefactuur.py` bewaakt dat.

Het regime vanaf 01/08/2026 draagt dezelfde 1,9261 op grond van continuïteit
(die hervorming wijzigde alleen de bijzondere accijns), maar met
`geverifieerd = false` tot een afrekening van ná die datum het bevestigt.

**De bijdrage energiefonds is nu machinaal te controleren.**
`ingest/heffingen/energiefonds.py` leest de tarieftabel van vlaanderen.be — de
enige heffing in deze masterdata met een publieke, jaarlijks bijgewerkte tabel.
Twee eigenaardigheden van die pagina liggen vast in de code: de labels zijn met
`<br>` afgebroken (`get_text()` zonder scheidingsteken maakt er
"Residentiëleafnemer" van, waarna geen enkel rijlabel meer matcht), en
"niet-residentiële afnemer" bevat "residentiële afnemer" als deelstring — de
specifiekere moet dus eerst getoetst worden, anders krijgt een gezin de
bedragen van een onderneming. Het script meldt ook wanneer het volgende
kalenderjaar nog niet gepubliceerd is; het energiefonds faalt hard op een
ontbrekend jaar.

De federale accijnzen hebben zo'n tabel niet: hun bron is wetgeving
(Belgisch Staatsblad), en de pagina's van FOD Economie en Fluvius verwijzen
alleen door. Daar blijven `staging calibrate` tegen vtest.be en de
referentiefactuur de controle.

**Let op bij vergelijken**: de masterdata staat exclusief btw, publieke
communicatie noemt bedragen doorgaans inclusief 6%. Een verschil van precies
factor 1,06 is een eenheidsverwarring, geen afwijking.

**De tijdsas schuift op 1 januari niet vanzelf mee.** De accijnzen en het
vervoerstarief rekenen ná hun laatste ingangsdatum gewoon door met het laatst
bekende regime: wijzigt er iets per 01/01 en vult niemand het aan, dan blijft
de berekening stil het oude tarief gebruiken. Geen fout, alleen een verkeerd
bedrag. Het energiefonds gedraagt zich anders en faalt wél hard.
`docs/jaarwissel 2026-2027.md` zet per bestand op een rij wat er in december
nagekeken moet worden, met bron, commando en eindtoets.

### Verbruiksprofielen (Synergrid)

Voor klassieke meters en variabele contracten wordt het jaarverbruik verdeeld
over kwartieren/uren met een gebruiksprofiel — zie
`docs/research/verbruiksprofielen.md` voor de achtergrond (SLP-EX, RLP0N,
SPP) en `docs/manifest.md` §4.4/§9 voor de functionele eis. De ingest hiervoor
(`ingest/synergrid_sources.py`, `ingest/synergrid_downloader.py`,
`ingest/profielen/`) is bewust een apart domein naast `ingest/curves/`:
`curves/` verwerkt een door VREG zelf gecureerd werkboek
(`energy_curves`-artefact, van vlaamsenutsregulator.be) dat toevallig ook
RLP/SPP-achtige sheets bevat, maar met een andere bron, ander
bestandsformaat en zonder per-netbeheerderdetail. De doeltabel waar dat naar
zou schrijven (`marktcurve`) is bovendien een ongebruikt scaffold zonder
importer.

```bash
energievergelijker synergrid download --year 2026
energievergelijker staging parse --version <staging-versie> --only profielen \
    --synergrid-version <synergrid-versie> --jaar 2026
energievergelijker db import --version <staging-versie>
```

**`version publish` neemt een profielen-only staging-versie niet mee** —
`run_publish` eist nog altijd een `vtest/`-submap in de staging-directory
(ongewijzigd gedrag, niet veralgemeend voor deze feature). Een versie die
enkel `--only profielen` verwerkt heeft, publiceert dus niet; ze gaat wél
via `energievergelijker db import --version <id>` rechtstreeks de databank
in (`import_verbruiksprofielen` wordt door `import_version_into_db`
aangeroepen, los van `run_publish`). Voor een versie die vtest/tariffs/
curves én profielen samen bevat, werkt `version publish` gewoon.

Wat geverifieerd is door de echte Synergrid-bestanden te downloaden en te
parsen (2026):

- **RLP0N en SLP-EX zijn `.xlsb`**, niet `.xlsx` — vereist de `pyxlsb`-
  engine (`profielen`-extra). Enkel SPP is `.xlsx` (openpyxl). `pyxlsb`
  geeft tijdstippen als ruw Excel-serienummer terug; `_format_ts` uit
  `ingest/curves/workbook.py` (`CurvesWorkbookParser`) lost dat al op en
  wordt hier hergebruikt, niet herïmplementeerd.
- **SLP-EX draagt CET als "UTC+1, no DST"** — niet hetzelfde als
  `Europe/Brussels` (dat wél zomertijd kent). De parser gebruikt daarom de
  `ENU_UTC`-sheet, niet `ENU_CET`.
- **RLP0N-elektriciteit ("all DSOs"-bestand) is breed**: één kolom per
  netbeheerder, geïdentificeerd via een GLN-code in de derde headerrij
  (`ingest/profielen/workbook.py::parse_breed_per_netbeheerder`, meldt naar
  lange vorm zoals `CurvesWorkbookParser._parse_timeseries` al doet). Dekt
  héél België — Fluvius, ORES-varianten, RESA, Sibelga, AIEG, AIESH, Régie
  de Wavre — niet enkel de 8 Vlaamse DNB's uit `DNB_CODES`. Een paar kleine
  netbeheerders komen dubbel als kolom voor met identieke GLN en waarden;
  de validator staat dat toe zolang de waarden overeenkomen en faalt hard
  bij een tegenstrijdigheid (`duplicate_gln_conflict`).
- **RLP0N-gas** (via het GOS-bestand) is, anders dan elektriciteit, een
  nationaal profiel — geen per-netbeheerderkolommen — en uurresolutie
  (dag begint om 6u CET, vaste gasconventie).
- **SPP ex-ante sommeert niet tot 1** — het is productie per kWp
  geïnstalleerd vermogen, geen verdeling. De som-tot-1-controle
  (`ProfielenValidator`, harde fout, citeert `docs/manifest.md` §4.4) geldt
  daarom enkel voor SLP-EX en RLP0N.
- **Regressiemodel-/parameterbestanden** (CL1/CL2/CL3-clusters,
  weer-/kalendercoëfficiënten) en de **SPP ex-post-historiek** (5 jaar, per
  netbeheerder) worden bewust nog niet geparsed — dat zijn geen
  kant-en-klare tijdreeksen maar invoer voor een eigen model.
- **Precisie**: profielgewichten zijn geen geldbedrag — `waarde` is
  `sa.Float` (double precision), niet `Numeric`, om de brondata (tot 16
  decimalen) niet stil af te ronden. Zie de toelichting in `schema.py` bij
  `verbruiksprofiel_waarde`.
- **`netbeheerder_code`/`energie_type` zijn `NOT NULL DEFAULT ''`**, niet
  nullable: PostgreSQL behandelt NULL in een unieke sleutel als onderling
  verschillend, wat de `ON CONFLICT`-upsert van de nationale profielen zou
  breken (zelfde reden als `netbeheerder_tarief.tariefnotering`).
- Synergrid-URL's zijn **niet af te leiden** — 2026-bestanden staan onder
  `/SLP-RLP-SPP/2026/`, 2025-bestanden grotendeels niet. De scraper leest
  altijd de links van de pagina zelf, net als `VnrSourceScraper`.

`ArtifactDownloader`/`RawStore` (VREG, maandelijks, altijd `.xlsx`) zijn
bewust niet uitgebreid met de Synergrid-bronnen (jaarlijks, `.xlsb`): een
gewone `source download` zou anders elke maand 50+ MB ongewijzigde
jaarbestanden meeslepen. `SynergridDownloader`/`SynergridRawStore`
(`ingest/synergrid_downloader.py`) zijn een kleinere, parallelle set met een
eigen manifestvorm en een `.xlsb`-tak in de containervalidatie
(`xl/workbook.bin` i.p.v. `xl/workbook.xml`).

### Gebruikersbasis

`gebruiker.toml` beschrijft één gebruiker; `src/energie_vlaanderen/gebruikers/`
maakt daar een domeinmodel van dat meerdere gebruikers, adressen, EAN's, meters,
installaties en contracten-met-periode aankan. Migratie 0017 verving daarvoor het
lege scaffold uit 0001 (`gebruiker`, `meterinterval`, `simulatie`) door
`gebruiker`, `gebruiker_persoonsgegeven`, `aansluitingspunt`, `meter`,
`installatie_asset`, `leveringscontract`, `verbruiksopgave`, `toestemming`,
`meterinterval` (nu aan het aansluitingspunt), `simulatie` en `simulatie_regel`.

```bash
energievergelijker gebruiker toon --toml gebruiker.toml
energievergelijker gebruiker controleer --hardware      # exitcode 2 bij een fout
energievergelijker gebruiker bereken --van 2026-01-01 --tot 2027-01-01
```

Zie `gebruiker.voorbeeld.toml` voor de volledige bestandsvorm. Het bestaande
formaat blijft geldig; alles wat erbij komt is optioneel. `toml_io.py` is de
**enige** lezer van `gebruiker.toml` — `hardware/installatie.py` en
`experiments/park/` zijn verwijderd, en `calculation/simulator_battery.py` haalt
zijn batterijkeuze nu uit het dossier.

**Een EAN hoort bij een aansluitingspunt, niet bij een gebruiker.** Eén EAN18
identificeert één toegangspunt voor één energiedrager; elektriciteit en gas
hebben elk hun eigen EAN, en injectie is géén aparte EAN maar een aparte
registerlezing. Er is daarom geen veld "heeft gas" — het bestaan van een
gasaansluitingspunt ís dat antwoord.

**Drie vermogensbegrippen die niet samenvallen**: het aansluitingsvermogen
(fysiek, kVA), de AC-limiet van de omvormer, en de maandpiek (een tariefconstruct).
Dezelfde soort fout als de `geschatte_maandpiek_kw`/`minimum_maandpiek_kw`-splitsing
uit migratie 0015.

**Drie tijdassen, en ze schuiven onafhankelijk.** `periodes.snijd()` knipt een
venster op elke contractwissel, elke bevroren tariefkaart, elk heffingenregime en
elke jaarwissel. Een *vast* contract volgt de actuele tariefkaart niet: de prijs
bevriest bij ondertekening (`tariefkaart_geldig_van`), terwijl de heffingen het
regime van de deelperiode volgen — de bijzondere accijns wijzigde op 01/08/2026
midden in elk lopend contract.

**Een variabel of dynamisch contract wordt per maand geknipt**
(`periodes.indexatiegrenzen`). De indexatieformule neemt per periode een andere
waarde aan, en de V-test-export levert die als maandsnapshot — 20 maanden,
januari 2025 tot en met augustus 2026. Zonder die knip krijgt een variabel
contract dat in januari begint en tot september loopt acht maanden lang de
januari-index: op Aspiravi "Eco Plus flex" met 3 MWh scheelde dat 30,31 EUR op
een leverancierskost van 328,96 (~10%). Een *vast* contract wordt niet per maand
geknipt — daar ligt de prijs juist stil. Loopt een variabel contract voorbij de
laatste maand in de export, dan stopt `zoek_product()` met een fout in plaats van
de laatst bekende index door te rekenen.

**Reken op jaarbasis en schaal daarna naar dagen** (`berekening.schaal_kost`).
Bijna elke component van een energiefactuur is een jaargrootheid: het
capaciteitstarief heeft een jaarlijkse ondergrens én een maximumtarief over het
jaarverbruik, databeheer en de vaste vergoeding zijn EUR/jaar, de accijnsschijven
zijn progressief over het *jaar*verbruik, en het energiefonds is een vast bedrag
per maand. Wie de deelperiodevolumes rechtstreeks door `Calculator` haalt,
betaalt die vaste componenten één keer per deelperiode: een contractwissel in
2026 gaf zo 603,24 EUR netkost waar één jaar er 373,96 kost. Het invariant dat
dit bewaakt staat in `tests/test_gebruikers_berekening.py`: **knippen mag het
totaal niet veranderen.**

**Een onbekende sleutel in `gebruiker.toml` wordt geweigerd, niet genegeerd.**
`afname_kwh` schrijven in plaats van `afname_dag_kwh` leverde een
`[[verbruiksopgave]]` van 0 kWh op. De berekening liep gewoon door en gaf
21,40 EUR terug waar 291,56 hoorde te staan — geen fout, geen waarschuwing,
alleen een bedrag dat te laag was. Het viel enkel op omdat het cijfer wantrouwen
wekte. `toml_io._SLEUTELS` legt per sectie vast wat er mag staan; de melding
noemt de dichtstbijzijnde bekende sleutel, want de fout is bijna altijd een
typfout. `resolutie` en `ontbrekende_data` staan in die lijst omdat de
documentatie ze noemt, al leest niets ze vandaag.

**Exactheidsklasse en aannames zijn types, geen rapportage.** `Exactheidsklasse`
(exact / gereconstrueerd / geschat / scenario, Manifest §5.8) en `Aanname`
(veld, waarde, bron, geverifieerd, beinvloedt_bedrag) reizen mee tot in het
eindbedrag. De zwakste schakel bepaalt de klasse: één geschatte invoer die het
bedrag raakt maakt het hele resultaat geschat, ook als elke tariefopzoeking exact
was. `beinvloedt_bedrag=False` bestaat voor administratieve aannames zoals een
onbekende EAN: die raken geen euro, en ze wél laten meetellen zou bijna elk
resultaat "geschat" maken en die klasse betekenisloos. Een `Aanname` zonder `bron`
bestaat niet — dat zou een gok zijn die zich als gegeven voordoet.

**SPP is vermogen, geen energie.** Het werkboek zegt het zelf op "Read Me First":
*"SPP-value expressed in mW/mWp"*. Over 2026 sommeren de kwartierwaarden tot
4.119,94; als energie gelezen zou dat 4.120 kWh/kWp/jaar zijn, vier keer de
werkelijke Vlaamse opbrengst. `schatting.productie_uit_kwp()` vermenigvuldigt
daarom met de intervalduur (0,25 uur) en komt op 1.030 kWh/kWp/jaar. SLP-EX en
RLP0N sommeren wél tot 1 en zijn verdelingen.

**Uit een genormaliseerd profiel komt geen maandpiek.** De piek van een profiel
is die van een gemiddelde over duizenden aansluitingen.
`schatting.maandpieken_uit_profiel()` bestaat alleen om te weigeren; Manifest §12
laat enkel een *gedocumenteerde* schatting toe, en dat is de 4,218 kW uit vtest.be.

**Postcode alleen volstaat niet altijd voor de netbeheerder.** Postcode 2387 dekt
zowel Zondereigen (gas: Fluvius Kempen) als Baarle-Hertog (gas: Enexis Netbeheer).
`NetbeheerderRegister.dnb_for()` eist daar de gemeentenaam en weigert te gokken;
`dnb_met_tarieven()` stopt bovendien op Enexis, dat geen tarieven in deze dataset
heeft.

### De CSV-lezer staat niet meer in `src/`

`data/repository.py` las de gestagede CSV's rechtstreeks in `Product`-objecten.
Sinds de knip is de databank de enige bron waaruit gerekend wordt, en werd die
klasse in productiecode nergens meer geconstrueerd — de CLI draait op
`DbDataRepository`. Zolang ze in `src/` stond, was ze een staande uitnodiging om
de regel te omzeilen; ze staat nu in `experiments/remove/data_repository.py`.

**De tests die haar gebruiken blijven bestaan, en dat is geen inconsistentie.**
`test_referentiefactuur.py` rekent dezelfde factuur langs beide wegen na en komt
op hetzelfde bedrag uit; `test_tariefbron.py` toetst dat beide bronnen aan
`TariefBron` voldoen. Die twee paden náást elkaar zijn juist het bewijs dat de
overstap veilig was — één ervan weggooien houdt het getal over en gooit de
vergelijking weg.

`infrastructure/csv.py` (RobustCsvParser) is om dezelfde reden verhuisd: niets
in het repo verwees er nog naar.

`DataRepositoryError` is uit `KNOWN_EXCEPTIONS` van de CLI gehaald — niets in
`src/` werpt hem nog. Zijn opvolger `DbDataRepositoryError` staat er bewust
*niet* in de plaats: die import trekt SQLAlchemy binnen, en de
masterdata-controles in CI draaien met een installatie zonder de `db`-extra.
`cli/gebruikers.py` vangt hem af op de enige plek die hem kan werpen.

### De postcodekoppeling kwam nog uit een CSV

De regel "de berekening komt uit de code, de data uit de databank" stond nergens
vastgelegd — ze werd nageleefd omdat het zo bedoeld was. Dat hield niet. Een
spoorloop over `gebruiker bereken` (een audithaak op `open`) liet zien dat het
postcode→netbeheerderregister nog uit `data/current/DnbPerGemeente.csv` kwam,
terwijl diezelfde 519 gemeenten in de tabel `gemeente` staan.

Geen bijzaak: de netbeheerder bepaalt wélke nettarieven gelden. De tarieven
kwamen uit de databank en de koppeling ernaartoe uit een bestand — precies de
tweede weg naar hetzelfde antwoord die uiteen kan lopen.

`netbeheerders_uit_databank(conn)` staat nu los van `DbDataRepository`, want die
vraagt een tariefjaar en dit register kent er geen: welke netbeheerder op een
postcode zit, hangt niet van een tariefjaar af. `gebruiker bereken` opent
daardoor eerst de databank en leest daarna pas het dossier — het dossier heeft
het register nodig om een aansluitingspunt aan een netbeheerder te hangen.

`gebruiker toon` en `gebruiker controleer` houden de CSV-weg: die rekenen niets
uit en horen zonder databank te werken.

**De regel is nu zelf een test.** `tests/test_berekening_leest_geen_pipeline_csv.py`
hangt een audithaak in de interpreter en faalt zodra een berekening iets uit
`data/staging/`, `data/versions/` of `data/current/` opent. Dat is sterker dan
een grep op importregels: het vangt ook een pad dat via een omweg wordt
samengesteld. Wat er ná de fix nog geopend wordt: `gebruiker.toml`,
`config/heffingen/*.toml`, de marktprijscache, `.env`, en de eigen
Fluvius-meterexport onder `data/referentie/`.

### Gas en elektriciteit worden apart doorgerekend

`gebruiker bereken` weigerde een dossier zonder elektriciteitsaansluiting. Het
rekent nu **elk aansluitingspunt apart door** en toont ze apart: twee EAN's,
twee contracten, twee tariefwerelden. Ze in één bedrag persen zou de herkomst
van elke post laten verdwijnen. Wie alleen gas heeft is geen uitzondering maar
een gewoon dossier.

```bash
energievergelijker gebruiker bereken --van 2025-05-01 --tot 2026-05-01
```

Op een gasdossier van 12.181 kWh (de referentiefactuur): netkost **215,25**
tegenover 215,24 en heffingen **112,54** tegenover 112,54 — exact. De
leverancierskost hangt af van hoeveel tariefkaartperiodes het dossier
declareert; met de drie van de factuur komt ze op 664,88 tegenover 662,11.

**Een fout op het ene punt laat het andere niet vervallen.** Ontbreekt het
gascontract, dan verschijnt de elektriciteitskost gewoon, met de reden waarom
gas ontbreekt eronder — want dan is het totaal onvolledig en dat hoort erbij te
staan.

Vier dingen die daarbij vastliggen:

- **`zoek_product()` kreeg de energievorm mee.** Die stond vast op
  "Elektriciteit", en "ENGIE Easy" bestaat in beide energievormen: een
  gascontract kreeg daardoor de elektriciteitsprijs, 0,172 in plaats van
  0,050 EUR/kWh — drie keer te veel, zonder foutmelding.
- **Het energiefonds is een elektriciteitsheffing** en wordt op gas niet
  aangerekend. `levies_gesplitst()` kent nu de energievorm.
- **De Fluvius-export gaat niet naar het gaspunt.** Die reeks is
  elektriciteit; ze aan gas meegeven zou elektriciteitskwartieren als gasvolume
  laten doorgaan.
- **Injectie op een gasaansluiting is een harde fout**, geen nul. Gas kent geen
  teruglevering; het is bijna zeker een verwisseld aansluitingspunt.

**De RLP0-verdeling is een derde tijdas**, en ze reist mee als `Aanname`.
`schatting.gasaandeel_uit_rlp0()` geeft naast het aandeel een `Aanname` terug
met het gebruikte profieljaar. Staat dat jaar niet in de databank — er is
vandaag alleen 2026 — dan valt ze terug op het dichtstbijzijnde jaar en wordt
de aanname `geverifieerd = false`: de seizoensvorm herhaalt zich, maar dat is
een aanname en geen meting. De aandelen van de deelperiodes sommeren over de
opgave tot 1; `tests/test_gas_nettarief.py` bewaakt dat, want anders verdwijnt
of verdubbelt er volume bij elke contractwissel.

### Aardgas: drie grootheden die niet hetzelfde schalen

`grid_cost()` dekte enkel elektriciteit-laagspanning. `gas_grid_cost()` dekt nu
aardgas, nagerekend op de referentiefactuur: **196,28 tegenover 196,24 EUR
distributiekost, vier cent op 0,02%.** Alle vier de gereguleerde gasposten samen
(distributie, vervoerstarief, bijzondere accijns, bijdrage op de energie) komen
op 327,82 tegenover 327,78.

Wat gas anders maakt dan elektriciteit zit niet in de bedragen maar in de
soorten grootheid:

- **de tariefgroep volgt het jaarverbruik.** T1 `0 - 5 000`, T2
  `5 001 - 150 000`, T3 `150 001 - 1 000 000`, T4 `> 1 000 000` — letterlijk
  uit rij 7 van een `<DNB> GAS Afname`-blad. T5 en T6 staan er bewust niet bij:
  dat zijn *telegemeten* klanten, een metersoort en geen volgende schijf. Ze op
  verbruik kiezen zou een grootverbruiker met een gewone meter in T5 laten
  belanden, mét een capaciteitsterm die daar niet geldt.
- **vaste term en databeheer zijn jaarbedragen**, naar dagen verdeeld. Het
  werkboek zegt het zelf: "Voor de facturatie van de vaste term en het tarief
  databeheer worden de jaartarieven geproratiseerd over het aantal dagen die de
  gemeten periode bestrijkt."
- **het volume wordt met RLP0 over de tariefperiodes verdeeld, niet naar
  dagen.** Ook dat staat er: "Voor de effectief toe te passen tarieven dienen
  de gemeten kWh over de verschillende tariefperioden verdeeld te worden op
  basis van het reëel lastprofiel RLP0." Gas is winterzwaar — over
  25/06/2025-30/04/2026 valt **53,8%** van het volume in de 120 dagen van
  januari tot april, waar een verdeling naar dagen 32,9% geeft. De tarieven van
  2026 liggen hoger, dus naar dagen verdelen rekent structureel te weinig aan.

**Twee data-fouten die dit blootlegde.**

*Het databeheertarief hing aan de verkeerde sleutel.* Het werkboek zet AMR, MMR
en Jaaropname onder "3) Tarief databeheer", elk met één bedrag in één
willekeurige kolom: AMR in de T5-kolom, MMR en Jaaropname in de T1-kolom. Met
de vaste kolomkaart van de normalizer kregen ze daardoor `GAS_T5` en `GAS_T1`
als klanttype — alsof ze alleen voor díé tariefgroep golden. Een gezin in T2
vond geen databeheertarief en betaalde er dus geen: 17,62 EUR op een
distributiekost van 196,24, bijna 9%, en niets faalde. Ze hebben nu een eigen
klanttype (`GAS_DBH_AMR`, `GAS_DBH_MMR`, `GAS_DBH_JAAROPNAME`). Dezelfde klasse
als `ELEK_LS_DC`.

*Het ODV-tarief had geen naam.* "II. Het tarief openbaredienstverplichtingen"
staat in kolom 0 in plaats van kolom 1, waardoor 24 rijen per tariefjaar een
lege `Tariefdetail` droegen — een tarief dat alleen op zijn eenheid te vinden
was. De normalizer valt nu terug op kolom 0.

Migratie 0023 ruimt beide op: een SCD2-upsert kent invoegen en afsluiten, geen
*verhuizen*, dus een herimport laat de oude sleutels naast de nieuwe staan.

### De nettarieven werden op zes decimalen afgerond

VREG publiceert de distributienettarieven met **zeven** decimalen.
`netbeheerder_tarief.prijs` stond op `Numeric(14, 6)`, dus 0,0230382 werd stil
0,023038 en 0,0000145 werd 0,000015. Geen randgeval: 186 van de 272 gasrijen en
513 van de 776 elektriciteitsrijen in het werkboek van 2026 dragen zeven
decimalen.

Dezelfde fout als `vaste_vergoeding_jaar` in migratie 0022, en de moeite om
dezelfde reden. Het bedrag is verwaarloosbaar — het grootste verlies is
5e-7 EUR/kWh — maar het is afronding van *brondata*, en het maakt een exacte
audit op deze kolom onmogelijk: de cel-voor-celvergelijking meldde 186
verschillen waarvan er geen enkele echt was. Een tolerantie inbouwen zou de
kolom juist onbewaakt laten.

Migratie 0024 verbreedt naar `Numeric(15, 7)`; de integerruimte blijft acht
cijfers. Na de herimport is gas cel voor cel gelijk aan het werkboek (256 van
256 rijen, nul verschillen) en verschilt elektriciteit alleen nog in de
drijvende-kommaruis van het werkboek zelf (`0.12364839999999999` tegenover de
correct opgeslagen `0.1236484`).

### De gasheffingen stonden onvolledig

Dezelfde referentiefactuur legde drie gaten bloot in de handgeschreven
masterdata, alle drie in het regime van vóór de hervorming van 01/08/2026 — de
bestanden waren daar eerlijk over ("nog niet gedekt"), maar de factuur ís een
primaire bron voor precies die periode.

- **De bijdrage op de energie stond op nul.** Exact dezelfde fout als bij
  elektriciteit: vtest.be toont die post niet, maar dat is iets anders dan dat
  hij nul is. De afrekening rekent hem als aparte regel aan — 12,15 EUR,
  afgedrukt als 0,9975 EUR/MWh. Het zakelijke tarief droeg al 0,9978, langs een
  andere weg gekalibreerd; die twee bevestigen elkaar.
- **De bijzondere accijns stond op 8,2300** uit een secundaire bron. De factuur
  drukt 8,2415 EUR/MWh af en rekent 100,39 EUR aan op 12.181 kWh.
- **Het vervoerstarief begon pas op 01/01/2026**, waardoor een berekening over
  een eerdere periode hard faalde. De factuur drukt 1,5599 EUR/MWh af over
  25/06/2025-30/04/2026, één tarief voor de hele periode.

`geverifieerd = true` slaat bij de eerste twee op de **waarde**, niet op de
ingangsdatum: wat vaststaat is dat deze tarieven golden over de periode van de
afrekening. Het vervoerstarief blijft `geverifieerd = false` — dat één
leverancier dit tarief toepaste, zegt niet dat het algemeen gold.

### Het tariefjaar komt uit het werkboek, niet uit het versie-id

`cli/db.py` leidde het tariefjaar af met `jaar = int(version_id[:4])`. Dat is de
*downloaddatum*: wie in september 2026 het werkboek van 2025 ophaalt, krijgt een
versie-id dat met 2026 begint, en de SCD2-import stempelt dan
`geldig_van = 2026-01-01` op tarieven van 2025. Twee tariefjaren botsen zo in
dezelfde unieke sleutel.

Het jaar staat betrouwbaar in `original_filename` van het raw-manifest
("Distributienettarieven elektriciteit 2025.xlsx").
`cli/helpers.py::tariefjaar_uit_manifest()` haalt het daaruit, de tariefpipeline
schrijft het als `tarief_jaar` in `tariffs_*_report.json`, en zowel `cli/db.py`
als `DataRepository.tariefjaar` lezen het daar. Staat er meer dan één jaartal in
de naam, dan volgt een fout — raden zou een heel tariefjaar verkeerd dateren.
Oudere staging-versies dragen het veld niet en vallen luidruchtig terug op het
versie-id.

`Kostberekening` toetst per deelperiode dat het geladen tariefjaar overeenkomt.
De tariefrijen dragen zelf geen datum, dus aan de data is niet te zien of ze bij
2025 of 2026 horen: zonder die toets geeft een berekening over 2025 met het
werkboek van 2026 een plausibel ogend en verkeerd bedrag.

**Alle drie de jaargangen staan op de VREG-pagina.** `source list --year 2024` en
`--year 2025` vinden ze; ze hoeven niet manueel geplaatst te worden. Netkost voor
3.000 kWh bij Fluvius Midden-Vlaanderen, digitale meter: 374,75 EUR in 2025
tegenover 373,96 in 2026.

**Het werkboek van 2024 parseert nog niet correct.** De huidige parser haalt er
116 in plaats van 200 afnamerijen uit, kent maar 4 van de 8 netbeheerders
(FA, FI, FL, FW) en géén `ELEK_LS_DIGI` — de bladindeling verschilt van 2025/2026.
Dat is apart werk; wat wél opgelost is, is dat het geen stille nul meer oplevert.

### Een ontbrekend nettarief is een fout, geen nul

`grid_cost()` gaf op de 2024-data 0,00 EUR terug: elke lookup vond niets en
leverde stil `D("0")`. Een digitale meter in Aalst zat daarmee gratis op het net.
Er zijn nu twee controles, en ze gaan bewust over de *afwezigheid van de rij* en
niet over de waarde — een tarief dat er is en 0 bedraagt is iets anders dan een
tarief dat ontbreekt:

- geen enkele rij voor deze netbeheerder en dit klanttype → fout, met de wél
  beschikbare klanttypes of netbeheerders in de melding;
- `val(..., verplicht=True)` voor het capaciteitstarief (digitale meter) en de
  vaste term (analoge meter), de twee grootste posten.

### Het werkboek van 2024 leest een andere kolomindeling

De VREG-werkboeken van 2025 en 2026 zetten de laagspanningskolommen
(piekmeting / analoge meter / prosument) op kolomindex 13/14/15. Dat van 2024
heeft **één kolom méér** — de hoogspanning is er anders ingedeeld, met
"TRANS HS" en "AV ≥ 5 MVA"/"AV < 5 MVA" in plaats van de post/net-splitsing —
en schuift ze naar 14/15/16.

Met de vaste indeling die `ingest/tariffs/normalizer.py` gebruikte, werd de
*piekmeting* van 2024 als "analoge meter" gelabeld en de klassieke meter als
"prosument". Geen ontbrekende data dus, maar verkeerd gelabelde data. En omdat
er op kolom 13 niets stond, kende de 2024-export helemaal geen `ELEK_LS_DIGI`
— waarna `grid_cost()` er 0,00 EUR voor teruggaf.

`TariffWorkbookParser` leidt de laagspanningskolommen nu af uit de koprijen:
Excel-rij 4 draagt de spanningsgroep ("Laagspanningsnet", "LS", "TRANS LS") en
rij 5 de meetsoort ("piekmeting", "analoge meter", "klassieke meter",
"prosumenten met terugdraaiende teller"). Die twee samen identificeren een
kolom; de groep is nodig omdat 2024 twéé kolommen "piekmeting" heeft, één onder
"TRANS LS" en één onder "LS". De kaart telt alleen wanneer alle drie de
categorieën gevonden zijn — een halve kaart zou stil rijen laten vallen.

Midden- en hoogspanning worden bij een afwijkende indeling **overgeslagen** met
een waarschuwing: hun kolommen op een vaste index lezen zou tarieven aan het
verkeerde spanningsniveau hangen, en Manifest §7.2 verbiedt daar sowieso
residentiële formules.

Twee dingen blijven open bij 2024:

- **De tien Fluvius-entiteiten van vóór de fusie van 2025** (GW, INT, IVK,
  IVRLK, PBE, SIB naast FA/FI/FL/FW) staan niet in `DNB_CODES`. Ze worden nu
  overgeslagen *met een bevinding* in plaats van stil; bruikbaar maken vergt ook
  een historische postcode→netbeheerder-koppeling, en `DnbPerGemeente.csv` is
  de huidige.
- Daardoor levert 2024 alleen tarieven voor FA, FI, FL en FW.

### De C10/26-lijst als controle op de hardware-masterdata

`hardware/homologatie.py` leest de Synergrid C10/26-lijst: de officiële
Belgische lijst van productie-eenheden die aan C10/11 voldoen en dus op een
distributienet aangesloten mogen worden. Staat een toestel er niet in, dan mag
de netbeheerder de aansluiting weigeren — voor een gebruiker die in een
interface een batterij kiest is dat de eerste vraag die telt.

```bash
energievergelijker audit hardware --c10-26
```

De lijst is bovendien de **enige onafhankelijke bron** op deze masterdata; al
het andere komt uit fabrikantsdatasheets. `BatterijSpec` draagt niet toevallig
`synergrid_id`, `power_control_system`, `p_active_power_w`,
`smax_apparent_power_w` en `num_phase`: dat zijn de kolommen van deze lijst.
Wat ze *niet* zegt: capaciteit in kWh, rendementen, cyclusleven.

Wat de eerste run opleverde (uitgave 2026-08-26, 8.238 eenheden, 319 merken):

- **Marstek Venus E** is gehomologeerd als `GLV265-07-0004`
  (MST-BIE5-2500). Dat id staat nu in de masterdata.
- **`smax_apparent_power_w` stond 40% te hoog.** Het veld had 3500 VA, met
  "3,5 kVA piek (10s)" als verantwoording. Dat cijfer staat in de datasheet,
  maar onder *Back-up (Off Grid)* — een off-grid piek van tien seconden. Het
  veld betekent het continu schijnbaar vermogen op het net, en daarvoor noemt de
  datasheet onder *AC Input/Output (On Grid)* "2.5kVA / 800VA". C10/26
  homologeert het toestel in precies die twee varianten. Twee grootheden door
  elkaar.
- **Venus E 4.0 en Venus E Mini staan niet in de lijst**, ook niet bij de
  vervallen homologaties. Van Marstek staan er alleen Venus-C en Venus-E in. Die
  twee modellen zijn in België dus niet gehomologeerd; de configbestanden dragen
  daar nu een waarschuwing over.

Twee valkuilen die in de code vastliggen:

- **Merken staan in wisselende schrijfwijze in de lijst** ("Growatt" naast
  "Growatt ", "MARSTEK" in hoofdletters), dus vergelijken gebeurt
  genormaliseerd.
- **Eén serie heeft meerdere vermeldingen.** Growatt's SPH 5000 bestaat 1-fasig
  (4.999 W) en 3-fasig (5.000 W). Op vermogen alleen wint de 3-fasige, terwijl
  de masterdata 1-fasig zegt. Het aantal fasen weegt daarom zwaarder dan het
  vermogen bij het kiezen van de variant.

De werkbladen melden Excel's maximum van 1.048.576 rijen omdat er opmaak tot
onderaan staat; zonder de bovengrens van `MAX_RIJEN` leest pandas een miljoen
lege rijen en duurt het inlezen minuten.

### Persoonlijke referentiedocumenten

`data/referentie/` is bedoeld voor echte facturen, afrekeningen en
meterexports — het bewijsmateriaal waartegen de rekenengine getoetst wordt.
`.gitignore` sluit die map uit behalve `LEESMIJ.md`: ze dragen naam, adres, EAN
en klantnummer, en `docs/manifest.md` §4.3 vraagt dat persoonsgegevens
doelgebonden en minimaal verwerkt worden. Let op dat `.gitignore` alleen
*specifieke* submappen van `data/` negeert, niet `data/` als geheel — een nieuwe
map eronder gaat zonder regel gewoon mee de repo in.

Uit zo'n document worden alleen de cijfers overgenomen naar een geanonimiseerde
fixture onder `tests/fixturen/facturen/`. Die gaat wél in git en wordt de
referentiecase; het document zelf blijft lokaal.

### Meterdata: `metering/fluvius_csv.py`

Een Fluvius-verbruikshistoriek is de enige bron van werkelijk verbruik die een
gebruiker zelf kan aanleveren, en ze maakt het verschil tussen een geschatte en
een exacte reconstructie. De parser is herschreven nadat een echte export van
drie jaar (210.625 regels elektriciteit, 52.657 gas) vier eigenschappen
blootlegde waarop de vorige versie stukliep:

- **Vier registers, niet twee.** `Afname Dag`, `Afname Nacht`, `Injectie Dag`,
  `Injectie Nacht`. Alleen op "afname" en "injectie" matchen gooit het
  dag-/nachtonderscheid weg — precies wat het nettarief en de meeste
  leveranciersproducten nodig hebben.
- **Gas staat er dubbel in**: elk uur één regel in m³ en één in kWh. Optellen
  per tijdstip telde volume en energie bij elkaar op. Er wordt op
  `Eenheid == "kWh"` gefilterd.
- **`Validatiestatus` onderscheidt drie dingen.** `Uitgelezen` is een meting,
  `Geschat` een schatting van Fluvius zelf (mét waarde), en `Geen verbruik`
  betekent dat er géén meting is — daar staat een leeg volume. Dat op nul zetten
  maakt van een ontbrekende meting een gemeten nul (Manifest §12). In de export:
  508 geschat, 193 zonder meting.
- **Lokale tijd met de zomertijdsprongen erin.** Op de laatste zondag van
  oktober telt de dag 100 kwartieren op 96 unieke lokale tijdstippen; groeperen
  op tijdstip plakt dat uur samen en laat verbruik verdwijnen. Elk register
  wordt apart naar UTC omgezet: binnen één register staan de twee doorgangen na
  elkaar, en de eerste is de zomertijddoorgang. `ambiguous="infer"` van pandas
  kan dat ook, maar slechts voor één overgang per aanroep — over drie jaar zijn
  het er drie of vier en gooit het een fout.

`FluviusReeks` draagt naast de intervallen ook de kwaliteit: resolutie, aantal
geschatte en ontbrekende intervallen, en waarschuwingen over onderbrekingen.
`maandpieken_kw()` levert de werkelijke maandpieken (hoogste kwartiergemiddelde
maal vier), `voor_berekening()` de vorm die `supplier_cost()` verwacht.

Zodra `[verbruik].fluvius_csv` naar zo'n bestand wijst, haalt
`gebruiker bereken` de volumes per deelperiode uit de meting in plaats van een
jaartotaal pro rata over de dagen te verdelen. Dat sluit onder meer de
jaarwissel. Staan er én een meetbestand én een `[[verbruiksopgave]]`, dan
bepaalt de opgave het volume waarover de progressieve accijnsschijven lopen en
de meting de verdeling over de periodes; lopen ze meer dan een procent uiteen,
dan wordt dat gemeld.

### Het capaciteitstarief wordt maandelijks herrekend

Onderzoek op de referentiefactuur en drie jaar meetdata: de "gemiddelde
maandpiek" van 7,409 kW op die factuur is geen piek van de periode maar het
resultaat van een **maandelijkse herrekening op een voortschrijdend
twaalfmaandsgemiddelde** van de maandpieken, met de wettelijke ondergrens van
2,5 kW per maand.

Nagerekend op de echte kwartierdata:

| model | capaciteitskost |
|---|---|
| onze maandpieken, per maand voluit | 352,76 |
| onze maandpieken, deelmaand naar rato | 331,19 |
| **voortschrijdend 12-maandsgemiddelde, maandelijks herrekend** | **312,59** |
| factuur | 311,23 |

Het voortschrijdende gemiddelde komt op 0,4% van de factuur uit; de andere
modellen zitten er 6 tot 13% naast. `grid_cost()` rekent vandaag nog met de
jaarvorm (`som(max(piek, ondergrens) x tarief/12)` naar dagen geschaald), wat
klopt zolang er één representatieve piek meegegeven wordt — maar het is niet de
manier waarop de netbeheerder factureert. Het restverschil van 1,36 EUR is
vermoedelijk het verschil tussen onze maandpieken en de door Fluvius
gevalideerde waarden.

### De referentiefactuur nagerekend

Een echte ENGIE-eindafrekening (verbruiksperiode 25/06/2025-30/04/2026, 310
gemeten dagen, Fluvius Midden-Vlaanderen) is met `gebruiker bereken`
hergesimuleerd uit de eigen data:

Met alleen de factuurvolumes (jaarwissel pro rata naar dagen):

| | simulatie | factuur | verschil |
|---|---|---|---|
| Energie afname + groene stroom + WKK | 1132,35 | 1132,36 | −0,01 |
| Injectievergoeding | −71,20 | −71,20 | **0,00** |
| Netwerkkosten | 677,42 | 678,09 | −0,67 |
| Toeslagen en heffingen | 336,81 | 336,81 | **0,00** |
| **Subtotaal excl. btw** | **2075,38** | **2076,06** | **−0,68 (0,033%)** |

Met de Fluvius-kwartierhistoriek erbij vervalt elke pro-rata-aanname en wordt
het resultaat `exact`:

| | simulatie | factuur | verschil |
|---|---|---|---|
| Energie afname + groene stroom + WKK | 1132,40 | 1132,36 | +0,04 |
| Injectievergoeding | −71,22 | −71,20 | −0,02 |
| Netwerkkosten | 678,14 | 678,09 | +0,05 |
| Toeslagen en heffingen | 336,81 | 336,81 | **0,00** |
| **Subtotaal excl. btw** | **2076,13** | **2076,06** | **+0,07 (0,003%)** |

De meetdata bevestigt de factuurvolumes: 2598,8 / 4217,5 kWh afname en
2788,1 / 1003,5 kWh injectie tegenover de afgedrukte 2599 / 4218 / 2788 / 1003.
Het echte totaal is 6816,3 kWh, niet 6817 — precies de afronding die het
restverschil verklaarde.

Twee factuurposten vallen buiten wat de engine kent en worden niet vergeleken:
de correctie "Periode tussen meteropname en factuurdatum" (+112,66, een
facturatiemechanisme dat op de volgende factuur weer rechtgezet wordt) en de
kortingen (−380,70, contractueel en in geen publieke bron).

**Het restverschil van 0,67 is uitgeklaard en zit niet in de code.** Het valt in
twee stukken uiteen, allebei na te rekenen uit de factuur zelf.

*0,73 EUR — de verdeling over de jaarwissel.* Een leverancier verdeelt
**tijd**grootheden naar dagen en **volume**grootheden naar de werkelijke
meterstand. Het databeheer bewijst het eerste: 125/365 x 17,51 = 5,997 (factuur
5,99) en 65/365 x 17,51 + 120/365 x 17,85 = 8,987 (factuur 8,99) — er wordt dus
wel degelijk op 01/01 geknipt. Maar de distributiekosten over 28/10-30/04
(4.693 kWh) komen naar dagen verdeeld op 238,84 uit terwijl de factuur 239,57
rekent; dat bedrag hoort bij 1.886 kWh in 2025 en 2.807 in 2026, oftewel 40,2%
van het volume in 35,1% van de dagen. Precies wat je van een winter verwacht.
Wij verdelen het volume naar dagen omdat we de meterstand op 31 december niet
hebben — die staat niet op de factuur. Voer je hem in als twee
`[[verbruiksopgave]]`-secties, dan sluit het: 678,15 tegenover 678,09.

*0,05 EUR — de afronding op hele kWh.* De eerste tariefkaartperiode
(25/06-27/10/2025) ligt volledig in tariefjaar 2025: geen jaargrens, geen
verdeling. Onze berekening geeft 2.124 kWh x 0,0528980 = 112,355 EUR, de factuur
112,31 — dat hoort bij 2.123,14 kWh. De factuur drukt piek en dal elk afgerond
af (710 + 1.414 = 2.124); vier afgeronde registers geven makkelijk een kWh
verschil op de som. Dit is de precisiegrens van het document, niet van de
berekening.

*Dat de tarieven zelf kloppen*, bewijst het capaciteitstarief: dat hangt niet
van het volume af, alleen van de gemeten piek en van hoeveel dagen in welk
tariefjaar vallen. 7,409 kW x (190/365 x 49,0426291 + 120/365 x 50,1239818) =
311,238 tegenover 311,23 op de factuur — acht duizendsten van een euro. Zat er
iets fout in de tariefselectie of in de verdeling over de jaarwissel, dan zou
het daar al blijken.

`aanname.veld` heet daarom `verdeling_over_de_jaarwissel` zodra een opgave de
jaargrens kruist: daar kost de aanname geld, elders niet.
`tests/test_referentiefactuur.py` bewaakt het geheel en de verklaring.

**Drie fouten die deze afrekening blootlegde**, alle drie onzichtbaar zolang er
alleen over hele kalenderjaren gerekend werd:

- **Jaargrootheden werden door de meetperiode gedeeld in plaats van door 365.**
  Het capaciteitstarief, het databeheer en de vaste vergoeding zijn
  jaarbedragen; `grid_cost()` kent daarvoor nu een `dagen`-parameter. Over 310
  gemeten dagen werd 365/310 = 1,177 keer te veel aangerekend. De factuur
  rekent 7,409 kW x (190/365 x 49,042629 + 120/365 x 50,123982) = 311,23 EUR,
  precies het jaarbedrag naar rato van de dagen.
- **Twee breuken die niet hetzelfde zijn.** `_reken_periode` onderscheidt nu
  `aandeel` (dagen van de deelperiode / dagen van de opgave — hoeveel van het
  *verbruik* hier valt) van `tijddeel` (dagen / 365 — hoeveel van een *jaar*
  dit is). Bij een opgave over een volledig kalenderjaar vallen ze samen; bij
  een afrekening niet. De accijnsschijven volgen het volumeaandeel omdat ze
  progressief zijn over het jaarverbruik, het energiefonds volgt het tijddeel
  omdat het een maandbedrag is.
- **"Dal" is geen "exclusief nacht".** Het lagere ODV-tarief "kWh-tarief
  exclusief nacht" geldt alleen voor het aparte register van toestellen die
  enkel 's nachts draaien. `bouw_profile` telde het dalvolume van een
  tweevoudige meter bij dat register op, waardoor 4.218 kWh het lagere tarief
  kreeg: 35 EUR per jaar te weinig netkost. `Profile` heeft nu een eigen
  `afname_exclusief_nacht_kwh`.

**De btw op de injectievergoeding is beslist.** `calculate()` trok het krediet
eerder van de btw-basis af; `docs/price_model_low_voltage.md` §9.1 schreef juist
voor het krediet met 6% te verhogen. Geen van beide klopte. De btw-tabel van de
factuur zet de injectievergoeding in een aparte vrijstellingsregel (Beslissing
ET 131.616/2 van 25-10-2019) náást de 6%-basis: ze valt volledig buiten die
basis en wordt zonder btw van het totaal afgetrokken. Daarmee is de openstaande
validatie uit Manifest §14 gesloten.

**Een vast contract volgt de tariefkaart van bij het intekenen.** Verdwijnt het
product een maand later van vtest.be, dan verandert er niets: `zoek_product()`
zoekt bij een bevroren contract in de snapshot van `tariefkaart_van`, niet in
die van de verbruiksperiode, en `indexatiegrenzen()` knipt alleen bij variabele
en dynamische contracten per maand.

**`gebruiker.toml` staat niet meer in git.** Zodra er een EAN, adres of
meterstand in staat is het een persoonsgegeven — Manifest §5.2 noemt de EAN
expliciet gevoelig. `gebruiker.voorbeeld.toml` blijft wel in git en
documenteert de volledige bestandsvorm, inclusief `gemeten_maandpiek_kw`,
`periode_van`/`periode_tot` en de lijst `[[verbruiksopgave]]` voor een verbruik
dat per tariefkaartperiode opgesplitst is.

### Vier facturen erbij, en wat ze blootlegden

Naast de eerste referentiefactuur staan er nu vier andere echte afrekeningen in
`tests/fixturen/facturen/`, met hun dossiers in `tests/fixturen/dossiers/` en
`tests/test_referentiefacturen_reeks.py` als bewaker. Ze zijn niet gekozen op
aantal maar op spreiding: elk raakt iets wat de eerste niet raakt — een derde
meterregister, de netkost regel per regel, een contract dat niet op de markt
bestaat, en een tweede netbeheerder. De brondocumenten blijven lokaal in
`data/referentie/facturen_2026-09/` (buiten git).

Wat er reproduceert:

| factuur | post | simulatie | factuur |
|---|---|---:|---:|
| Eneco "Zon & Wind Flex" | netkost | **142,94** | 142,95 |
| ENGIE "Flow" (aardgas) | netkost | **235,63** | 235,62 |
| ENGIE "Direct Online" | heffingen | **579,94** | 579,93 |
| ENGIE "Drive" (Halle-Vilvoorde) | netkost elektriciteit | 1153,65 | 1150,39 |
| ENGIE "Drive" (Halle-Vilvoorde) | distributiekost gas | 219,78 | 220,94 |

**Het register "uitsluitend nacht" werd niet geprijsd.** `supplier_cost()`
rekende de energiekost over `afname_dag_kwh` en `afname_nacht_kwh`;
`afname_exclusief_nacht_kwh` werd in geen enkele tak vermenigvuldigd. Het volume
telde wél mee in de kosten groene stroom en WKK — die gaan over `afname_kwh` —
zodat er ook geen verdachte nul te zien was. Op een afrekening met
nachtverwarming ging het om 2.076 van de 11.738 kWh: **223,77 EUR per jaar
gratis stroom**, geen exception, geen falende test. De prijs stond al die tijd
in de databank (`tarief_afname.meter_type = 'exclusive_night'`, 2.855 rijen,
evenveel als `day` en `night`); de netkost las het register wél, want
`grid_cost()` splitst er sinds een eerdere referentiefactuur het ODV-tarief
precies op. Alleen de leverancierskant was blijven staan. Een ontbrekende prijs
is nu een fout en geen nul: terugvallen op de nachtprijs zou een aanname zonder
bron zijn, en dat het exclusief-nachttarief lager ligt ís de reden dat het
register bestaat.

**De bijzondere accijns op aardgas is vóór 01/08/2026 progressief, niet vlak.**
`config/heffingen/bijzondere_accijns_aardgas.toml` draagt één schijf van 8,2415
EUR/MWh voor het hele oude regime. Dat cijfer is teruggerekend uit één factuur
door het bedrag door het volume te delen — dus het is het *gemiddelde* van die
ene factuur en niet het tarief. Drie facturen over vrijwel dezelfde periode
geven drie gemiddelden die met het volume meestijgen: 8,2415 op 12.181 kWh,
8,3146 op 13.599 en 8,3479 op 14.230. Een jaarwisselstap is uitgesloten (de
zuiver-2025-periode van één factuur geeft 8,2798, hóger dan het gemiddelde van
de factuur met het laagste volume). Een tweeschijvenmodel met de grens op
12 MWh — dezelfde grens als ná de hervorming — en 8,23 onder en ~8,98 boven
reproduceert de eerste en de derde tot op de cent. Gevolg vandaag: elk gezin
boven 12 MWh betaalt in onze berekening te weinig, 1,00 EUR op 13.599 kWh en
1,52 op 14.230. De bovenste schijf komt uit drie punten en niet uit een
wettekst; ze staat daarom nog niet in de masterdata.

**"Residentieel" en "niet-zakelijk" zijn niet hetzelfde, en `segment` doet alsof
van wel.** Eén afrekening rekent de bijzondere accijns aan het niet-zakelijke
tarief (een privépersoon, geen onderneming) maar de bijdrage energiefonds aan
het niet-residentiële — twee wetten, twee definities, en ze vallen hier niet
samen. `levies_gesplitst()` leidt beide categorieën uit `Profile.segment` af, dus
geen van beide waarden reproduceert die factuur; met "Woning" mist de berekening
120,80 EUR. Dat oplossen vraagt een eigen veld in het dossier.

**Twee dingen bevestigd die tot nu toe alleen hun eigen bron hadden.** De
bijdrage op de energie van 1,9261 EUR/MWh staat letterlijk op drie
ENGIE-facturen afgedrukt — de post die tot augustus 2026 op nul stond omdat
vtest.be hem niet toont. En het energiefonds: 118,56 en 120,84 EUR/jaar op de
Eneco-afrekening zijn exact 9,88 en 10,07 EUR/maand uit
`bijdrage_energiefonds.toml`, categorie `niet_residentieel`; de residentiële
facturen dragen géén energiefondsregel, wat de 0,00 van diezelfde tabel vanuit
de andere richting bevestigt.

**De leverancierskost heeft een plafond dat niet aan de code ligt.** Op elke
factuur in deze reeks rekent de simulatie 5 tot 22% naast de energiekost, altijd
in dezelfde richting, en de oorzaak is steeds dezelfde twee dingen. De
V-test-export levert per maand de tariefkaart die op dat moment *verkocht*
wordt, terwijl een lopend variabel contract de formule van zijn eigen
kaartversie houdt en alleen de index laat bewegen: bij Eneco is het verschil
precies de vaste vergoeding (61,321 in de export tegenover 49,59 op de kaart van
de klant), bij "Direct Online" ook param A (0,0954 tegenover 0,0996). En de
indexwaarde in de export is die welke VREG bij publicatie kende, niet de
gerealiseerde maandwaarde waarmee de leverancier afrekent — voor april 2026
110,75 tegenover 84,75 EUR/MWh. Dat is de nauwkeurigheidsgrens van deze
gegevensbron voor het reconstrueren van een *bestaand* contract; voor het
vergelijken van aanbiedingen, waar de tool voor gemaakt is, is het geen probleem.

**Een product dat van de markt verdwijnt maakt een dossier onberekenbaar.**
"Drive" stond t/m mei 2025 in de export; de klant hield het contract tot maart
2026. `zoek_product()` weigert dan terecht — maar daarmee valt de héle
berekening weg, ook de netkost en de heffingen, die niet van het product afhangen
en apart wél op een half procent uitkomen. Dezelfde soort scheiding als "een
fout op het ene aansluitingspunt laat het andere niet vervallen", maar dan
binnen één punt over de kostcomponenten heen. Hetzelfde geldt voor een
hernoeming: ENGIE's "Direct" heet vanaf 01/12/2025 "Direct Online", en een
variabel contract dat de jaarwissel kruist moet die naamswissel als aparte
contractperiode declareren of het vindt niets.

**Het personeelstarief hoort te weigeren, en doet dat.** Een tarief dat alleen
voor werknemers bestaat staat niet op vtest.be en zal er nooit op staan; de
factuur draagt bovendien géén aparte netwerkkostenregel voor elektriciteit — het
is een all-in prijs (`0,1097 + 0,00114 x Epex DAM`) met daarbovenop een
personeelskorting. Er is niets aan af te leiden, en de juiste uitkomst is dus
geen bedrag maar een fout.

### Het tariefkaartarchief

Een variabel contract bevriest bij ondertekening zijn **formule**, niet zijn
prijs: de vaste vergoeding en de coëfficiënten liggen vast in de kaartversie
die de klant tekende, en alleen de index beweegt nog. De V-test-export levert
per maand de kaart die op dat moment *verkocht* wordt. Op een echte
Eneco-afrekening scheelde alleen al de vaste vergoeding 11,74 EUR per jaar
(61,321 in de export tegenover 49,59 op de kaart van de klant); bij ENGIE
"Direct Online" week bovendien de indexcoëfficiënt af (0,0954 tegenover
0,0996), en de Eneco-kaart uit 2023 gebruikt zelfs een *kwartaal*index waar de
export een maandindex noemt.

Dat is geen rekenfout maar een ontbrekend gegeven, en het verschilt van de
index in één beslissend opzicht: **een index valt uit de day-ahead historiek
altijd nog terug te rekenen, een tariefkaart is weg zodra de leverancier hem
vervangt.** Vandaag archiveren is de enige manier om een contract van vandaag
over drie jaar nog exact na te rekenen.

`ingest/tariefkaarten.py` haalt de kaarten op uit
`vtest_contract.link_tariefkaart` van de lopende snapshots en legt ze
**inhoudsgeadresseerd** weg in `data/tariefkaarten/` (buiten git). Dat lost
twee dingen tegelijk op: leveranciers delen één kaart over meerdere producten,
en een kaart die wijzigt krijgt vanzelf een nieuw pad zodat de oude blijft
staan. `scripts/archiveer_tariefkaarten.py` draait het.

Stand op 2026-09-04: **302 van de 351** kaarten binnen, 133 MB.

**Niet elke link wijst naar een PDF.** 83 van de 351 kwamen uit op een
productoverzicht. De resolver haalt die pagina op, verzamelt de kandidaatlinks
mét hun ankertekst en matcht op productnaam én energievorm — over de tekst en
de URL, want Odoo levert de kaart als `/web/content/…/1772/file` waar de
bestandsnaam niets zegt en het anker "Tariefkaart_Flow_EL". Dat lost er 48 op.
**Bij twijfel wordt er niets gekozen**: een verkeerde kaart geeft een
berekening die klopt op de verkeerde formule, en dan faalt er niets. De
overwogen links reizen mee naar het foutenregister, en
`archiveer_tariefkaarten.py --kandidaten` leest ze terug — zonder netwerk,
want ze staan er al. Het uitzoekwerk per leverancier is daarmee een opzoeking
geworden en geen heronderzoek.

Uit die dump kwamen drie regels, en het zijn regels en geen uitzonderingen
omdat ze bij meerdere leveranciers tegelijk gelden:

- **`_NG` is "natural gas".** De Energy Together-sites labelen
  `Tariefkaart_APEX Online_NG` naast `_EL`; een gasherkenning die alleen op
  "gas" zocht liet bij een elektriciteitscontract beide kandidaten staan.
- **Een exacte naam wint van een deelstring.** "PRIME" zit ook in "PRIME Plus",
  "Flex" in "FlexPro", "Variabel" in "VariabelPro".
- **Gelijke kandidaten zijn geen dubbelzinnigheid.** Dezelfde kaart staat er
  onder twee id's met dezelfde ankertekst (`…/1751/file` en `…/1757/file`,
  beide "Tariefkaart_NOVA_NG"). Op naam niet te scheiden, en kiezen zou een gok
  zijn — maar zodra ze byte voor byte gelijk zijn, ís er niets te kiezen. Geen
  versoepeling van de regel maar de toepassing ervan: verschillen ze, dan
  blijft het een fout.

Twee valstrikken die daarbij vastliggen. "Flow" bestaat in beide energievormen
op dezelfde pagina — dezelfde fout als `zoek_product()` die vastzat op
"Elektriciteit". En een historiekpagina draagt oude kaarten: Aspiravi zet er 21
maandkaarten op, die horen in een archief thuis maar niet als "de kaart van dit
contract vandaag".

**Luminus zet een UTF-8 BOM vóór de PDF-kop.** Een toets op byte 0 wees
daardoor 35 geldige kaarten af als "geen PDF" — echte kaarten van 214 kB die
pdfinfo en pdftotext zonder morren lezen. ISO 32000-1 §7.5.2 laat de kop binnen
de eerste 1024 bytes toe; er wordt nu daar gezocht en de offset wordt bewaard.

**Het register wordt tussentijds weggeschreven.** Dit zijn 350 verzoeken naar
evenveel externe sites en het duurt minuten; een run die halverwege afgebroken
wordt — en dat gebeurde — had anders wél de documenten op schijf maar geen
enkele waarneming, en de volgende run telde ze allemaal opnieuw als "nieuw".
Daarmee is de eerste-waarnemingsdatum weg, en dat is nu net wat dit archief
onderscheidt van een map met PDF's.

Wat er overblijft zijn 49 stuks, en het zijn er geen die met een betere regel
op te lossen zijn: 17 HTTP 404's (Ecofix wijst naar een leeg portaal, ENGIE's
professionals-pagina naar een verlopen API-route), en 32 pagina's die hun
kaarten pas na uitvoering van JavaScript tonen (Servolt, Smappee Smiles) of ze
alleen onder een interne code voeren zonder productnaam (Wase Wind:
`WW-VD-HHKZ-2601` tot `-2607`). Die vragen een browser of een afspraak met de
leverancier, geen scraper. Sommige leveranciers houden zelf een kaartarchief
bij; dat is per leverancier te bekijken.

### Injectie

Het injectiekrediet komt uit dezelfde V-test-export als de afnameprijzen, maar
uit de rijen met `direction = Injectie`: 14 vaste en 136 variabele/dynamische
injectieproducten voor augustus 2026, inclusief ToU. Injectie hoort bij hetzelfde
leveringscontract — "Bolt Variabel" bestaat in beide richtingen — dus
`Kostberekening.zoek_product(contract, periode, richting)` haalt beide op.
`Leveringscontract.injectie_product` is er alleen voor het geval de leverancier
voor teruglevering een ándere productnaam hanteert.

**Dezelfde productnaam kan in twee smaken bestaan.** "Bolt Variabel" staat in
augustus 2026 zowel als `variabel` (maandelijkse indexformule) als `dynamisch`
(kwartierprijs) in de export. Het contracttype wijst aan welke; zonder dat filter
weigert de opzoeking te kiezen.

**Geen injectieproduct is geen injectievergoeding van nul.** Het is een onbekend
bedrag, en de doorgerekende kost staat dan te hoog. Dat levert een waarschuwing
én een `Aanname` op, niet stil een 0.

**Injectie en een terugdraaiende meter sluiten elkaar uit.** Een klassieke
terugdraaiende meter registreert geen injectie; daarvoor betaalt de klant het
prosumententarief. Beide tegelijk telt hetzelfde voordeel twee keer, en dat is
een harde fout.

**Dynamische injectie moet de injectiereeks krijgen, niet de afnamereeks.**
`Calculator.calculate()` gaf aan de injectie-tak de kwartierreeks van de afname
mee. Bij een vast of variabel injectieproduct viel dat niet op — die gebruiken
enkel de jaartotalen — maar de dynamische tak somt `volume_t x prijs_t` over de
meegegeven reeks. Zonneproductie piekt rond de middag, wanneer de marktprijs laag
staat; verbruik piekt 's avonds, wanneer ze hoog staat. Op een testgeval met vier
uren scheelde dat 0,40 tegenover 8,00 EUR — twintig keer. Er is nu een aparte
`injectie_intervals`-parameter, en `sta_vlak_profiel=False` weigert bij injectie
de terugval op een vlak profiel: voor zonneproductie is dat geen benadering maar
een systematische overschatting.

**De btw-behandeling van de injectievergoeding is nog niet beslist.** De engine
trekt het krediet van de btw-*basis* af; `docs/price_model_low_voltage.md` §9.1
schrijft `T - injectieprijs x kWh x 1,06`, dus het krediet zelf verhoogd met btw.
Manifest §14 noemt dit een openstaande validatie. Het staat in geen werkboek — je
ziet het alleen aan een factuur mét injectie, en daarvoor is
`VTestHtmlDownloader.download(injectie_kwh=..., omvormer_kva=...)` gebouwd. Tot
die kalibratie rond is, legt `tests/test_gebruikers_berekening.py` het huidige
gedrag vast, niet de eindbeslissing.

### De injectie-index is SPP-gewogen, en die conventie kennen we nog niet

De meest gebruikte index op injectieproducten is
"M EPEX Spot Belgium/Belpex SPP_BE (kwartier)": het maandgemiddelde Belpex
**gewogen met het zonneproductieprofiel**. Dat is niet het rekenkundig
gemiddelde — de zon schijnt op de goedkope uren. Op juni 2026: rekenkundig
113,98 EUR/MWh, SPP-gewogen 73,84 — ruim 35% lager. Wie injectie tegen de
gemiddelde marktprijs waardeert, overschat de opbrengst fors.

`scripts/check_injectie_index.py` rekent de index na onder zes conventies
(kwartier/uur, gewogen/rekenkundig, met en zonder maandverschuiving) en legt ze
naast `index_value_A` uit de export. Stand op 2026-09-03: **geen enkele
conventie reproduceert de gepubliceerde waarde.** De SPP-weging zit duidelijk in
de goede richting (rekenkundig zit er 84-115% naast, SPP-gewogen in de beste
maanden 6,7%), maar de afwijking is grillig — 126% in januari, 7% in maart, 60%
in april. Nog niet uitgesloten: ex-post in plaats van ex-ante SPP, een ander
perimeter dan `SPP_BE`, en de betekenis van de TH/HI/LO-varianten.

Zolang dat niet rond is, rekent `formula_ct()` met de door VREG *meegeleverde*
indexwaarde en nooit met een zelf berekende. Dat is trouwens ook een bevestiging
dat die tak nu klopt: voor "Bolt Variabel" injectie augustus 2026 geeft
`0,094 x 70,54139 - 1,133 = 5,49789 ct/kWh`, tegenover de 5,5 die VREG zelf als
berekende prijs meelevert.

### De marktprijscache was niet herbruikbaar

`EntsoeMarketData.load()` zocht alleen op een sleutel die de volledige
periodestring bevat, dus een ander datumbereik miste de cache altijd — ook
wanneer de gevraagde dagen er allang in zaten. Wie in januari een halfjaar
ophaalde en daarna één maand opvroeg, kreeg een lege reeks of haalde alles
opnieuw op. `_uit_cache()` voegt nu alle opgeslagen periodes samen en bedient het
venster daaruit, met een waarschuwing over ontbrekende intervallen.

Weigeren doet die laag níet meer bij gaten binnenin: dat gebeurt waar het telt.
`supplier_cost()` vergelijkt sinds deze wijziging het gekoppelde volume met het
aangeboden volume en stopt wanneer er energie zonder prijs overblijft — een
inner join liet die intervallen anders stil vallen, en dan is dat verbruik
gratis. Op de huidige cache (juni 2026, afkomstig van energy-charts.info na een
ENTSO-E-terugval) betekent dat: 59 van 2.880 kwartieren zonder prijs, dus de
berekening stopt tot `market sync` de gaten vult. Negatieve prijzen blijven wél
bewaard — 1.076 stuks, tot -499,29 EUR/MWh.

### De vtest-scraper kan nu injectie invullen

`download(injectie_kwh=..., omvormer_kva=...)` vinkt `HasSolarPanels` aan en vult
`InjectionDay` en `InverterPower`. Drie dingen die daarbij tegenvielen en nu
vastliggen in de code:

- `InverterPower` is **verplicht** zodra er zonnepanelen aangevinkt zijn. Zonder
  waarde weigert vtest.be te submitten en verschijnen er simpelweg geen
  resultaten — een foutbeeld dat er uitziet als een onbereikbare site. Daarom
  eist de downloader nu een `omvormer_kva` zodra er injectie gevraagd wordt.
- `KnowsInverterPower` aanklikken **verbergt** dat veld in plaats van het te
  tonen. Niet aanraken dus.
- `KnowsCapacityElectricity` moet uitgevinkt worden *vóór* `HasSolarPanels`
  aangaat: andersom hertekent het paneel nadat de zonnepaneelvelden verschenen
  zijn.

Bovendien zijn klikken en wachten samengevoegd tot één lus. vtest.be hertekent
het formulierpaneel nadat de laatste waarde ingevuld is; een knopreferentie van
vóór dat hertekenen is daarna stale, en de klik gaat verloren zonder dat er ooit
een resultaat komt. De lus zoekt de knop opnieuw en klikt opnieuw binnen hetzelfde
`timeout`-budget, en een uitblijvend resultaat citeert nu de validatiemeldingen
van de pagina in plaats van "controleer of vtest.be bereikbaar is".

### De golden-audit hangt aan het werkboek, niet aan het CSV

`audit golden` legt de **databank** cel voor cel naast het bronwerkboek. Er was
even een `--bron`-keuze; die is vervallen toen de CSV-weg wegviel, want het CSV
vergelijken was dezelfde pipeline één stap eerder en dus geen onafhankelijke
controle. Dat was de voorwaarde om de CSV-weg te kunnen laten vallen: het
XLSX is de onafhankelijke bron, en welke kant ermee vergeleken wordt is een
implementatiekeuze. Het CSV was dat nooit — het is dezelfde pipeline één stap
eerder.

De nettarieven gaan één op één: `netbeheerder_tarief` draagt dezelfde velden
als het gestagede CSV, en de audit geeft identiek oordeel (200/200, 48/48,
528/528, 256/256, 16/16).

**De vtest-data gaat op sleutel en niet op positie.** De databank draagt die in
brede vorm — één rij per meterregister, componenten als kolom — en het werkboek
in lange vorm. De rijaantallen verschillen dus per definitie, en juist bij
ongelijke aantallen loopt een positievergelijking uit de pas: dat leverde ooit
2.220 gemelde verschillen op waarvan er geen enkele echt was. Er wordt
vergeleken op (leverancier, product, maand, segment, richting, component), en
wat maar aan één kant bestaat wordt geteld in plaats van als verschil gemeld.
Stand: 174.870 vergelijkingen over 55.353 sleutels, nul afwijkingen.

Twee dingen draagt de databank bewust niet, en die worden dus niet vergeleken:
`component_label` (de menselijke omschrijving) en de bronrij per component. Ze
staan alleen in het werkboek — dat bewaard blijft. De databank is de werkvorm,
het werkboek het archief.

Twee structurele verschillen die verklaard zijn en geen fout:

- **4.528 sleutels alleen in de databank.** De import maakt voor elke groep ook
  een `single`-rij aan wanneer de bron dat register niet kent; die draagt geen
  prijs.
- **100 alleen in het werkboek.** Een vaste vergoeding voor een meteropstelling
  waarvan het register in de bron ontbreekt (`fixed_fee_double` zonder dag- of
  nachtrij). De databank hangt die vergoeding aan een registerrij, dus zonder
  register verdwijnt ze. Klein, maar het is dataverlies.

**En daarbij gevonden: de vaste vergoeding werd stil afgerond.**
`vaste_vergoeding_jaar` stond op `Numeric(10, 2)` terwijl elke andere prijskolom
in dezelfde tabel `Numeric(12, 6)` is. 61,321 werd 61,32 en 11,2075 werd 11,21 —
bij 4.631 rijen. Het bedrag is verwaarloosbaar (een duizendste euro per jaar),
maar het is afronding van brondata, en het maakte een exacte audit op die kolom
onmogelijk: een tolerantie inbouwen zou de kolom juist onbewaakt hebben gelaten.
Migratie 0022 verbreedt de kolom; de decimalen komen terug uit het werkboek.

### De contractmetadata staat niet in de resultatendump

`vtest_contract` stond grotendeels leeg: intekenperiode, start levering,
looptijd, doelgroep, prijszekerheid en de links naar de tariefkaart en de
algemene voorwaarden waren NULL voor alle 350 contracten. Vijftien kolommen,
en niets faalde — de stille-lege-waarde-fout in haar zuiverste vorm.

Twee oorzaken, los van elkaar, allebei nodig om op te lossen:

**1. Het detailpaneel bereikte de parser nooit.** vtest.be serveerde de
detailblokken vroeger inline in de resultatenpagina (`contractdetail-<id>` —
te zien in de archiefdumps van juni 2026), maar haalt ze nu pas op na een klik
op "Meer details", via een POST naar `/VTest/GetContractDetails`. Dat endpoint
heeft de zoekopdracht in de sessie nodig; losstaand aanroepen geeft een 500,
dus de klik in de lopende Selenium-sessie is de enige weg. In de opgeslagen
dumps staat daardoor alleen een leeg `<div id="contractDetailsModal">`.

De parser zelf was niet stuk: op een dump die de blokken wél bevat vult hij
199 van de 199 producten. Het was plumbing.

Wat er nu gebeurt: `_verzamel_contractdetails` bewaart de **volledige**
innerHTML van het paneel onder
`staging/<versie>/vtest/contractdetails/<vreg_id>.html`, en
`VTestProductParser.parse(html, detail_fragments=...)` ontleedt die achteraf.
Een extra veld kost daarmee een herparse (`--no-download`), geen nieuwe scrape
van een half uur. Eerder werden alleen de links uit het paneel geplukt en ging
de rest verloren.

Drie dingen die daarbij tegenvielen en nu vastliggen:

- **Het paneel draagt het contract twee keer**: een verborgen printversie in
  `#contractdetail-<vreg_id>` en de zichtbare `.contractDetailsContent`
  (een class, geen id). De sectietabellen staan in de zichtbare helft, en de
  tariefkaartlink ook — maar buiten het printblok. Op `#contractdetail-<id>`
  scopen levert dus wel de datums en de doelgroep op, en géén enkele link.
  Er wordt over het hele fragment gezocht.
- **De links matchen op `onclick="matomoLinks('...')"`**, niet op de zichtbare
  ankertekst. Op tekst alleen matchen pikte de consumentenakkoord-link van FOD
  Economie op als "website van de leverancier"; die komt nu uit de
  "Website"-rij van de leverancierssectie.
- **Er wordt gewacht op het paneel van dít contract** (`#contractDetailsModal
  #contractdetail-<id>`), niet op "paneel niet leeg". Bij een klik die niet
  aankomt blijft de vorige inhoud staan, en dan zouden de details van het
  vorige contract stil aan dit contract gehangen worden.

Het ophalen zit **niet meer achter een vlag**. Zolang `--met-contractdetails`
opt-in was, leverde een gewone refine-run vijftien lege kolommen op zonder dat
er iets faalde. Nu is het standaardgedrag; `--zonder-contractdetails` blijft
over voor een snelle prijs-only run, en de pipeline waarschuwt luid wanneer
een paneel ontbreekt. `--met-contractdetails` blijft aanvaard.

**2. De upsert werkte de metadata niet bij.** `import_vtest_contract_en_prijzen`
deed `ON CONFLICT DO UPDATE` op alleen `laatst_gezien_versie` en
`laatst_gezien_op`. Een contract dat ooit zonder detailpaneel ingelezen was,
bleef daardoor voorgoed leeg — ook na een verse scrape die de gegevens wél
had. Nieuwe waarden winnen nu, maar afwezigheid wist nooit iets: tekst gaat
door `COALESCE(NULLIF(excluded.x, ''), x)`, datums door `COALESCE`. Een run
zonder detailpanelen kan de eerder opgehaalde metadata dus niet overschrijven.

Binnen één import wordt bovendien per veld aangevuld in plaats van "de eerste
rij wint": bij een hervatte matrixrun kan de eerste combinatie nog van vóór de
contractdetails komen terwijl een latere ze wél draagt.

### Een nettarief loopt tot 31 december, niet eeuwig

`netbeheerder_tarief.geldig_tot` stond op NULL voor alle 1.048 rijen — de
SCD2-betekenis "nog lopend". VREG stelt de distributienettarieven per
kalenderjaar vast, dus dat klopte niet: het tarief van 2026 gold formeel ook
in 2027, en een berekening over dat jaar zou er stil mee rekenen. Dezelfde
klasse als de accijnzen die na hun laatste ingangsdatum doorrekenen.

Migratie 0018 vult `geldig_tot = 31 december van het tariefjaar`, en de
importer schrijft het voortaan zelf mee. Twee dingen die daaraan vastzitten:

- **De einddatum is inclusief** (31/12), niet half-open (01/01). Dat is de
  conventie die deze tabel al hanteerde — `_scd2_upsert_netbeheerder` sluit een
  voorganger af op `geldig_van - 1 dag`. De half-open conventie in de
  commentaar bij `schema.py` gaat over de gebruikerstabellen uit migratie 0017,
  een andere familie. Eén dag verschil is hier precies de stille fout die dit
  project probeert te vangen.
- **De SCD2-opzoeking moest mee.** Ze zocht de huidige rij op
  `geldig_tot IS NULL`; zodra elke rij een einddatum draagt vond ze niets, viel
  door naar de insert onderaan, en botste op `uq_netbeheerder_tarief` — een
  herimport van dezelfde versie liep stuk met een IntegrityError (nagegaan
  tegen de echte databank vóór de wijziging). Ze gaat nu op de hoogste
  `geldig_van`. De partiële index `ix_netbeheerder_tarief_open` bewaakte alleen
  open rijen en is geschrapt; `uq_netbeheerder_tarief` dekt de uniciteit
  volledig, want dat is de sleutel plus `geldig_van`.

### De hoogspanningsaudit meldde 2.220 verschillen die niet bestonden

`audit golden` gaf `NOK electricity_hoogspanning` met 2.220 verschillen. Geen
ervan was echt. Drie fouten, gevonden door de audit op de oude én de nieuwe
versie te draaien (identiek resultaat, dus niet door recente wijzigingen).

**1. De audit gaf de kolomkaarten niet mee.** `TariffPipeline` doet
`normalize(afname, injectie, parsed.kolomkaarten())`; de audit liet dat derde
argument weg. Zonder kaarten valt de normalisatie terug op de vaste
kolomindices en leest kolom 11 er alsnog bij: 528 hoogspanningsrijen tegenover
de 432 die de pipeline schrijft. Daarna vergelijkt de audit op positie, en dan
telt élke rij als verschil. Exact dezelfde soort fout als toen deze audit de
volledige verse normalisatie tegen alleen het afname-bestand legde en 108
onechte verschillen meldde.

**2. Erger: de audit slaagde op nul rijen.** `version publish` ruimt de
stagingmap op, en `audit golden` las uitsluitend daar. Op een gepubliceerde
versie vond ze dus geen enkel CSV en meldde `OK 0/0 rijen geverifieerd` voor
alle zeven domeinen — een groene audit die niets gecontroleerd had, en juist
deze audit is de poort naar `audit approve` en `version publish`. Ze zoekt nu
eerst in `versions/` en valt terug op `staging/` (dezelfde volgorde als
`db import`), en zowel een ontbrekend bestand als nul geverifieerde rijen
geldt nu als een **fout**.

Dit stond ook zo in een test: `test_missing_staged_csv_returns_empty_result`
beweerde `assert result.passed` bij nul rijen. De fout was dus als gewenst
gedrag vastgelegd — precies waar "Tests: herkomst boven aantal" over gaat.

**3. En daardoor gevonden: 96 afnamerijen verdwenen stil.** Kolom 11 is
`≤1 kV / distributiecabine` (`ELEK_LS_DC`): in naam laagspanning, maar met een
eigen kolom náást de kop "Laagspanningsnet" en met MS/HS-achtige tarieven
(toegangsvermogen in kVA, maandpiek, databeheer). De splitsing tussen "uit de
koppen afgeleid" en "op vaste index" liep op de naam
(`startswith("ELEK_LS_")`), waardoor dit klanttype uit *beide* groepen viel:
uitgesloten van de vaste kolommen om zijn naam, en expliciet uitgesloten van de
kopkaart omdat het geen kopkolom is. Niemand las kolom 11 nog. 96 rijen met
echte prijzen voor alle acht netbeheerders.

De groepen heten nu `ELEK_AFNAME_KOPKOLOMMEN` (precies de drie meetsoorten
onder "Laagspanningsnet") en `ELEK_AFNAME_VASTE_KOLOMMEN` (al de rest, dus HS,
MS én LS-distributiecabine). Een test bewaakt het invariant: elk klanttype uit
`ELEK_AFNAME_COLS` zit in precies één van de twee. De laagspanning-CSV's
blijven ongewijzigd (200 afname, 48 injectie) — `grid_cost()` is niet geraakt,
en `HS_MS_KLANTTYPES` routeerde `ELEK_LS_DC` al naar de hoogspannings-CSV.

Het werkboek van 2024 gedraagt zich onveranderd: de afwijkende indeling laat de
vaste kolommen (en dus ook `ELEK_LS_DC`) overslaan, met de bestaande
waarschuwing.

### Wat er van de historiek bewaard blijft, en wat niet

Een contract van april 2026 moet in 2028 nog na te rekenen zijn. Nagegaan op de
echte databank:

| tabel | historiek |
|---|---|
| `tarief_afname` / `tarief_injectie` | maandelijkse SCD2, jan 2025 t/m aug 2026 (16.642 rijen, 20 snapshots, 596 producten) |
| `netbeheerder_tarief` | per tariefjaar, afgesloten op 31/12 (migratie 0018) |
| `vtest_postcode_prijs` | per `version_id` — oudere versies blijven staan |
| `marktcurve` | per `version_id`; een herimport verwijdert alleen die ene versie |
| `verbruiksprofiel_waarde` | per `version_id` |
| `versions/<id>/` | blijft op schijf staan; publiceren ruimt alleen `staging/` op |

Getoetst: 336 producten hebben een aprilsnapshot en 1.527 tariefrijen zijn
geldig op 2026-04-17. De prijskant van de vraag is dus al gedekt.

**`vtest_contract` had dat gat, en heeft nu een tijdas** (migratie 0019). De
tabel had één rij per `vreg_id`: de metadata werd bij elke import overschreven,
zodat je in 2028 de *laatste* beschrijving van een contract uit september 2026
kreeg in plaats van die van toen.

**De tijdas ankert op de scrapedatum, niet op de publicatiedatum.**
`geldig_van` zegt vanaf wanneer deze metadata bij vtest.be écht zo stond — een
eigenschap van de bron. Wanneer wij die gegevens publiceerden is administratie
van deze toepassing en kan er dagen na liggen: versie `20260829T202059Z` is op
31 augustus gescrapet en pas op 2 september geïmporteerd. Die twee door elkaar
halen zou de historiek de administratie laten volgen in plaats van de
werkelijkheid. De publicatiedatum staat daarom apart in `gepubliceerd_op`.

`gepubliceerd_op` wordt gezet bij het **activeren** van de versie, niet bij de
import: `version publish` importeert eerst en activeert daarna, dus tijdens de
import bestaat er nog geen publicatiemoment. Een versie die alleen met
`db import` ingelezen is, draagt daar NULL — dat is de juiste uitspraak, geen
ontbrekend gegeven. Alleen nog lopende snapshots krijgen de stempel; een
afgesloten snapshot droeg de publicatiedatum van zijn eigen tijd.

Daarmee draagt deze tabel vier datumfamilies die elk iets anders betekenen en
onafhankelijk schuiven — `datum_intekenen_*`, `datum_start_levering_*`,
`geldig_van`/`geldig_tot` en `gepubliceerd_op`. Ze staan met die uitleg naast
elkaar in `schema.py`.

Twee gevolgen die niet los kunnen van de tijdas:

- **`vreg_id` is niet meer de primaire sleutel.** Er is een surrogaat `id` en
  een unieke sleutel op (`vreg_id`, `geldig_van`) — dezelfde vorm als
  `netbeheerder_tarief` en `tarief_afname`.
- **De foreign key vanuit `vtest_postcode_prijs.vreg_id` verviel**, want die
  wees naar een kolom die niet meer uniek is; er staat een index voor in de
  plaats. Beide tabellen worden in dezelfde transactie uit hetzelfde CSV
  geschreven, en een SCD2-tabel verwijdert niets, dus het `ON DELETE CASCADE`
  werd nooit uitgeoefend. Een `contract_id` die rechtstreeks naar het juiste
  snapshot wijst is de natuurlijke volgende stap.

**Er komt alleen een snapshot bij wanneer de beschrijving werkelijk wijzigt.**
Zonder die regel zou elke scrape 355 rijen toevoegen zonder één extra feit.
Afwezigheid telt daarbij niet als wijziging: een run zonder detailpanelen
levert lege velden, en die mogen noch de metadata overschrijven, noch een lege
contractversie naast de bestaande zetten. Draagt een nieuwe waarneming iets dat
er nog niet was, dan vult dat het lopende snapshot aan — het is dezelfde
waarneming, alleen vollediger. Nagerekend op de echte data: een herimport van
dezelfde versie levert 0 nieuwe snapshots op 355 contracten.

Let op bij het vergelijken: `False` is een waarde, geen afwezigheid.
`grayedout` en `complex_product` zouden met een gewone waarheidstoets als
"niets waargenomen" gelden.

**`energie_product.tariefkaart_url` en `bijzondere_voorwaarden_url` stonden op
0 van 686.** `import_energie_product_kenmerken` vulde alleen `groene_stroom` en
`groene_stroom_type`, en raakte die twee velden nooit aan — ook niet nadat de
scrape ze wél binnenhaalde. Ze worden nu meegenomen, met dezelfde regel als
elders: een leeg veld overschrijft een eerder opgehaalde link niet.

### De marktcurves werden geparsed maar nooit ingelezen

`marktcurve` stond op nul rijen terwijl `staging/<versie>/curves/` de drie
CSV's al maanden klaar had staan: er was simpelweg geen importer. CLAUDE.md
noemde de tabel daarom "een ongebruikt scaffold". `import_marktcurves` vult
hem nu — 132.540 rijen voor augustus 2026.

De drie bestanden hebben verschillende vormen en gaan op één generieke tabel:

- `curves_spot.csv` — één waarde per groep/parameter, zonder tijdstip.
- `curves_forward.csv` — per datum en energievorm **twee** waarden, voor afname
  en teruglevering. Dat worden twee rijen, uit elkaar gehouden door `groep`;
  ze in één rij persen zou er stil een van laten vallen.
- `curves_timeseries.csv` — de eigenlijke reeksen (EPC, RLP, SPP), ~132.000
  rijen, gechunkt weggeschreven zoals de profielenimport.

Twee dingen die daarbij vastliggen:

- **De energievorm staat in vier schrijfwijzen door elkaar**: `E`/`G`, voluit,
  als voorvoegsel van een marktplaats (`Gas TTF`, `Gas ZTP`) en met de richting
  erachter (`Elektriciteit_Injectie`). Ongenormaliseerd belanden die alle vier
  als aparte `energie_type` in de databank en levert een filter op "gas" niets
  op. Een onbekende vorm wordt bewust níét naar elektriciteit geraden maar
  ruw doorgegeven, zodat ze opvalt.
- **Geen unieke sleutel, dus geen `ON CONFLICT`.** De natuurlijke sleutel zou
  `datum` en `tijdstip` moeten bevatten, en die zijn per bestandsvorm
  afwisselend NULL — PostgreSQL ziet NULLs in een unieke sleutel als onderling
  verschillend, waardoor een echt duplicaat er alsnog in mag (dezelfde valkuil
  als `netbeheerder_tarief.tariefnotering`). In de plaats daarvan wordt eerst
  alles van deze versie verwijderd: een versie levert haar curves in hun
  geheel, niet aanvullend.

### Twee stille nullen in de rekenengine, nu weg

Beide kwamen aan het licht toen `DataRepository.dnb_for()` er eindelijk was en
`grid_cost()` voor het eerst tegen echte tariefdata draaide.

- **Het volumetrische distributienettarief viel weg.** `grid_cost()` zocht op
  notering `EUR/kW` en tarieftype `"Tarieven voor netgebruik"`, terwijl het
  werkboek `EUR/kWh` en `"Tarieven voor het netgebruik"` schrijft. Beide filters
  misten, dus stond de term stil op nul: bij FMV 2026 en 3.000 kWh scheelde dat
  74,62 EUR per jaar. Idem voor de vaste term van de analoge klantcategorie
  (125,31 EUR/jaar). De lookup matcht nu op de deelstring `netgebruik`.
- **Elk variabel product viel terug op de meegeleverde prijs.**
  `DataRepository.products()` schrijft `formula["index_A"] = {"name", "value"}`;
  `Calculator.formula_ct()` las `f.get("A")` en `f.get("name_A")`. Die sleutels
  bestonden niet, dus zag de guard nooit een indexwaarde. Van de 61 variabele
  producten van augustus 2026 rekenen er nu 58 uit hun eigen formule. De test die
  dit afdekte legde de kapotte vorm vast — een vorm die niets produceert.

## Architecture

The package lives in `src/energie_vlaanderen/`. `energievergelijker.py` at the root is the entry point; it delegates to `src/energie_vlaanderen/cli/` (a package, not a single module).

### CLI package (`src/energie_vlaanderen/cli/`)

```
__init__.py    # build_parser(), main() — re-exports the public API used by tests/pyproject
__main__.py    # `python -m energie_vlaanderen.cli`
groups.py      # builds the group→action parser tree (source/raw/staging/synergrid/market/audit/version/db/paths)
shell.py       # interactive REPL: opstart/werking dashboards, generic ✓/!/✗ result rendering
status.py      # dashboard data sources (live where possible, honest placeholders otherwise)
paths_cmd.py   # `paths` — run_paths, show_paths
ingest.py      # source/raw/staging/market/version handlers (incl. run_staging_parse)
synergrid.py   # synergrid group handlers + run_parse_profielen (staging parse --only profielen)
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
  bron.py        # TariefBron: het protocol dat de rekenengine van een gegevensbron vraagt
  db_repository.py # DbDataRepository: de enige bron waaruit gerekend wordt
calculation/
  calculator.py  # Calculator: grid_cost(), supplier_cost(), full cost breakdown
ingest/
  sources.py     # VnrSourceScraper: scrapes XLSX download links from vlaamsenutsregulator.be
  downloader.py  # ArtifactDownloader: downloads XLSX files safely
  raw_store.py   # RawStore: persists raw downloads with version IDs
  synergrid_sources.py    # SynergridSourceScraper: scrapes .xlsb/.xlsx profile links
                 #   from synergrid.be (subclasses VnrSourceScraper's link-select logic)
  synergrid_downloader.py # SynergridDownloader/SynergridRawStore: parallel, smaller
                 #   set of the two classes above — own manifest shape, own .xlsb
                 #   container check, own raw-store path (data/raw/synergrid/)
  profielen/     # Verbruiksprofielen (SLP-EX, RLP0N, SPP): workbook.py (nationaal
                 #   1-waarde-per-tijdstip vs. breed 1-kolom-per-netbeheerder,
                 #   beide gemold naar lange vorm) → validator.py (som-tot-1,
                 #   intervaltelling, dubbele-GLN-conflict) → pipeline.py
                 #   (1 process()-aanroep per bronbestand, zoals TariffPipeline)
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
gebruikers/       # De gebruikersbasis: models.py (Gebruiker, Aansluitingspunt, Meter,
                  #   InstallatieAsset, Leveringscontract, Verbruiksopgave, Aanname,
                  #   Exactheidsklasse) -> toml_io.py (gebruiker.toml -> domein) ->
                  #   periodes.py (snijdt een venster op elke tijdasgrens) ->
                  #   berekening.py (per deelperiode een Profile, dan Calculator) ->
                  #   schatting.py (Synergrid-profielen) -> repository.py (PostgreSQL)
                  #   + validation.py (audit-achtige Bevindingen)
nettarieven/
  netbeheerder.py # NetbeheerderRegister: postcode (+ gemeente) -> netbeheerder, per
                 # energiedrager. Voedt DataRepository.dnb_for(), dat Calculator.grid_cost()
                 # aanriep zonder dat het bestond.
  transport.py   # TransportTariefRepository: het vervoerstarief dat de netbeheerder doorrekent
                 # maar niet vaststelt (Fluxys voor aardgas). Zelfde vorm als heffingen/repository.py:
                 # tijdsas, geverifieerd-vlag, harde fout in plaats van een stille 0. Elektriciteit
                 # heeft dit gat niet — het Elia-transport zit al in de ODV-post van het werkboek.
infrastructure/
  db/            # SQLAlchemy Core schema.py + importer.py; Alembic migrations in db/migrations/versions/
                 # importer.py schrijft de SCD2-historiek gebatcht: de beslissing (welke periodes
                 # bestaan al, welke komen erbij) gebeurt in Python, het verschil gaat er in twee
                 # bulkbewerkingen in. 5.252 queries in plaats van ~90.000; 64 s in plaats van ~900.
                 # `_scd2_upsert` is een schil om `_scd2_bulk_upsert` zodat er één implementatie
                 # van de semantiek bestaat. Alles blijft in één transactie.
                 # verbruiksprofiel_waarde (migratie 0016) is bewust géén SCD2: Synergrid
                 # vervangt een jaarprofiel in zijn geheel, geen wijzigingshistoriek binnen
                 # het jaar. import_verbruiksprofielen() doet een gebatchte ON CONFLICT-upsert
                 # (chunks van 10.000 rijen) i.p.v. de SCD2-machinerie.
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

**vtest.be is hier de leidende bron.** Op gewone woningproducten past vtest.be 1,5565
EUR/MWh toe waar CREG 1,56 vastlegt — 0,22% lager, oorzaak onderzocht en niet gevonden.
De masterdata draagt sinds 2026-09-01 de vtest-waarde: deze toepassing vergelijkt met de
officiële vergelijkingstool van VREG, en dan weegt overeenkomen met wat die tool een klant
toont zwaarder dan overeenkomen met de nota waarop ze zich baseert. Onderneming draagt
1,56, want daar past vtest.be dat cijfer wél exact toe.

Het sociaal tarief valt onder dezelfde categorie `niet_zakelijk` maar rekent met 1,56;
zodra sociale tarieven apart doorgerekend worden, hoort daar een eigen categorie bij.

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

**Twee maandpieken, en dat is met opzet.** `Profile` draagt
`geschatte_maandpiek_kw` (4,218 kW) én `minimum_maandpiek_kw` (2,5 kW). Ze waren
één veld met de waarde 2,5 — maar 2,5 is de wettelijke ondergrens van het
capaciteitstarief, niet de piek van een gemiddeld gezin. Als standaardwaarde
betekende dat: wie geen eigen maandpieken aanlevert, rekent per definitie op de
bodem, ongeveer 86 EUR/jaar te laag. 4,218 kW is teruggerekend uit vtest.be
(capaciteitstarieven van alle acht netbeheerders, 2026-08-31) en is de piek
waarmee die tool zijn standaardwoning doorrekent. De ondergrens komt uit het
profiel en niet uit een constante, zodat een berekening kan zeggen wélke
ondergrens ze toegepast heeft. Databankkolommen zijn `Numeric(7, 3)`: op twee
decimalen zou 4,218 stil 4,22 worden.

### Key design rules (from Manifest 3.0)

- `Decimal` only for financial values — never `float`.
- No silent data loss: missing intervals, gaps, and DST anomalies must be reported.
- Provenance is mandatory on every derived value — en op elk vastgelegd getal
  in een test (zie "Tests: herkomst boven aantal").
- Middle/high-voltage tariffs must not reuse residential formulas.
- The billing engine, forecasting, and active control are separate domains.

### Tests: herkomst boven aantal

De testsuite telt 979 tests over 66 bestanden; zonder de integratietests draait
ze in ongeveer 11 seconden. Het aantal is geen probleem en snoeien erin is geen
doel — de kosten zitten niet in de runtime.

**`tests/README.md` beschrijft per bestand wat het bewaakt.** Elk testbestand
draagt één categoriemarker op modulehoogte (`bronnen`, `parsers`, `scrape`,
`databank`, `masterdata`, `rekenen`, `dossier`, `cli`), geregistreerd in
`pyproject.toml`. `pytest -m rekenen` draait één domein. Dat de som van de
categorieën de hele suite is, is zelf een test: `tests/test_suite_indeling.py`
eist per bestand precies één bekende categorie, want een bestand zonder marker
draait wél mee in `pytest -q` maar valt weg uit `pytest -m <categorie>` — groen,
en toch stil minder. `--strict-markers` staat aan. `integration` staat daarnaast
en niet in de plaats ervan: die tests hebben PostgreSQL of een volledige lokale
dataset nodig.

**Er staat ook een linter voor de tests in CI**, bewust smal: `E9` en `F`, dus
syntaxfouten en pyflakes, geen stijl. De brede regelsets van ruff melden 778
dingen in dit repo; daar een poort van maken betekent dat de poort maanden rood
staat en dus genegeerd wordt. Wat er wél in zit, vond bij het aanzetten meteen
drie echte dingen: een test die twee keer gedefinieerd was (de eerste draaide
nooit), een `groupby` in de vtest-validator waarvan het resultaat nergens heen
ging, en `from unittest import result` — twee keer, per ongeluk. `experiments/`
valt erbuiten: dat is archief en soms bewust stuk.

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
| `ENERGIEVERGELIJKER_SYNERGRID_PROFIELEN_PAGE_URL` | synergrid.be URL | Verbruiksprofielen scrape target |
| `ENERGIEVERGELIJKER_MAX_DOWNLOAD_BYTES` | `104857600` (100 MiB — was 50 MiB, te krap voor het ~49,7 MiB SPP-bestand) | Download size cap |

`ENTSOE_API_KEY` and database credentials are in `.env` (not committed to git beyond `.env` itself).

### User configuration

`gebruiker.toml` in the project root holds the personal profile (postcode, consumption, Fluvius CSV path, analysis settings). The CLI reads this when no explicit flags override it.
