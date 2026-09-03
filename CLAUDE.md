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
| `staging` | `parse --version [--only vtest\|tariffs\|curves\|profielen\|all] [--overwrite] [--synergrid-version] [--jaar]`, `refine --version [--postcode] [--segment woning\|onderneming] [--energy elektriciteit\|gas] [--matrix] [--no-download] [--browser chrome\|firefox] [--show]`, `calibrate --version [--postcode] [--browser] [--show]` |
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
```

`config/bronregister.toml` legt vast welke bronbestanden de pipeline verwerkt
heeft; `.github/workflows/bronbewaking.yml` vergelijkt dat dagelijks met de
VREG- en Synergrid-pagina's en maakt er een issue van. De agent `.claude/agents/tariefwacht.md`
en de skill `.claude/skills/tariefcontrole/` beschrijven de werkwijze bij een
afwijking — beide gaan over tarieven/heffingen, niet over verbruiksprofielen
(zie hieronder), maar volgen wel hetzelfde stramien.

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
  repository.py  # DataRepository: reads canonicalized vtest CSVs into Product objects
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
  csv.py         # Low-level CSV helpers
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

De testsuite telt ongeveer 395 tests en draait in 6 seconden. Het aantal is
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
| `ENERGIEVERGELIJKER_SYNERGRID_PROFIELEN_PAGE_URL` | synergrid.be URL | Verbruiksprofielen scrape target |
| `ENERGIEVERGELIJKER_MAX_DOWNLOAD_BYTES` | `104857600` (100 MiB — was 50 MiB, te krap voor het ~49,7 MiB SPP-bestand) | Download size cap |

`ENTSOE_API_KEY` and database credentials are in `.env` (not committed to git beyond `.env` itself).

### User configuration

`gebruiker.toml` in the project root holds the personal profile (postcode, consumption, Fluvius CSV path, analysis settings). The CLI reads this when no explicit flags override it.
