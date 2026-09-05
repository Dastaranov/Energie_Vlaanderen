# Tests

979 tests over 66 bestanden, in ongeveer 11 seconden zonder de integratietests
(gemeten over drie runs: 11,0 / 10,2 / 10,3 s). Het aantal is geen doel en snoeien erin ook niet — de kosten
zitten niet in de looptijd.

## De regel die hier geldt

**Een test die een getal vastlegt, zegt in het bestand zelf waar dat getal
vandaan komt.**

`test_heffingen_repository.py` beweerde maandenlang dat de bijzondere accijns
13,60 EUR/MWh was. Groen bij elke run. Het cijfer was fout — het is 46,00 — en
de test maakte die fout *geverifieerd*. Dat is erger dan geen test: zonder die
assertie was er twijfel geweest.

Elke fout die dit project heeft opgeleverd was van die soort. Een stil verkeerd
getal, geen crash. Vijftigduizend Excel-serienummers als tijdstempel. Een
sanity-check die zijn bestanden niet vond en toch "geslaagd" meldde. Een kolom
die op 25.937 rijen leeg stond terwijl 681 tests groen waren. Geen daarvan gooit
een uitzondering, en een testsuite is het enige goedkope mechanisme dat merkt
wanneer ze terugkeren.

Twee gevolgen voor het dagelijks werk:

- **Een falende test is eerst een vraag, geen taak.** Wijzigde het tarief, of
  brak de code? De bronvermelding zegt waartegen je moet toetsen. Een assertie
  bijstellen tot de test slaagt is hier de gevaarlijkste reflex die er is.
- **Een getal waarvan de herkomst niet op te schrijven valt, hoort niet in een
  assertie.** Dan is het een aanname en moet het eerst gekalibreerd of opgezocht
  worden.

## Categorieën

Elk testbestand draagt één marker, op modulehoogte. `pytest -m rekenen` draait
een domein; de som van de categorieën is de hele suite.

Dat laatste is geen afspraak maar een test. `test_suite_indeling.py` leest elk
testbestand en eist precies één bekende categorie: zonder die controle draait
een nieuw bestand zonder marker nog steeds mee in `pytest -q`, maar valt het weg
uit `pytest -m <categorie>` — groene CI, en toch een heel bestand dat niet meer
gedraaid wordt zodra iemand per domein werkt. `--strict-markers` staat aan, dus
een tikfout in een markernaam breekt de verzameling in plaats van stil niets te
selecteren.

```bash
ruff check .                     # smal: E9 + F, zie pyproject.toml
pytest -q                        # alles behalve de integratietests
pytest -q -m rekenen             # één domein
pytest -q -m "parsers or scrape" # de hele weg van bron naar CSV
pytest -q -m integration         # vereist PostgreSQL of een lokale dataset
```

| Marker | Wat | Tests |
|---|---|---|
| `bronnen` | bronbestanden ophalen, bewaren en de marktprijsbronnen | 59 |
| `parsers` | werkboeken lezen en normaliseren naar een canonieke vorm | 135 |
| `scrape` | de live weg naar vtest.be | 93 |
| `databank` | import, SCD2-historiek en de controles op de databank | 132 |
| `masterdata` | handgeschreven gegevens in `config/` | 115 |
| `rekenen` | de rekenengine en de hardwaremodellen | 127 |
| `dossier` | het gebruikersdossier | 125 |
| `cli` | de commandoschil | 20 |
| `suite` | de organisatie van pakket en testsuite zelf | 173 |

`integration` staat daarnaast en niet in de plaats ervan: het merkt tests
die PostgreSQL of een volledige lokale dataset nodig hebben. Ze worden
overgeslagen wanneer die er niet zijn, en draaien in CI tegen de zaaddump
(`.github/workflows/databank.yml`).

---

## `bronnen` — bronbestanden ophalen en bewaren

| Bestand | Wat het bewaakt |
|---|---|
| `test_sources.py` | De VREG-scraper kiest uit een downloadpagina precies de toegelaten XLSX-links en negeert de rest. |
| `test_synergrid_sources.py` | Dezelfde linkselectie voor synergrid.be, waar de URL's niet af te leiden zijn en dus van de pagina zelf moeten komen. |
| `test_downloader.py` | Een batchdownload schrijft alle bestanden plus een manifest, en breekt af op een te groot of onverwacht bestand. |
| `test_raw_store.py` | De ruwe bestanden en hun checksums: gewijzigd en ontbrekend zijn fouten, een extra bestand een waarschuwing. |
| `test_paths.py` | De versiemappen en `current.txt` — de wijzer kan nooit naar een versie wijzen die er niet is. |
| `test_config.py` | `Settings`, de projectwortel en de netbeheerderlijst; elke ongeldige ondergrens wordt geweigerd in plaats van overgenomen. |
| `test_settings_dotenv.py` | `.env` wordt echt gelezen. Stond eerder alleen in de documentatie, waardoor `market sync` zonder API-sleutel draaide. |
| `test_market_fallback.py` | De terugval van ENTSO-E op energy-charts is luidruchtig en elke rij draagt haar herkomst. |
| `test_tariefkaarten.py` | Het tariefkaartarchief: dezelfde kaart één keer op schijf, een gewijzigde kaart naast de oude, en HTML achter een `.pdf`-URL wordt geweigerd in plaats van als kaart bewaard. |

## `parsers` — werkboeken lezen en normaliseren

| Bestand | Wat het bewaakt |
|---|---|
| `test_vtest_workbook.py` | Hoe een blad van het V-test-werkboek herkend wordt; op vaste index lezen zou data aan de verkeerde kolom hangen. |
| `test_vtest_normalizer.py` | Het oude en het nieuwe indexschema (`d` versus `z`), en de drie vaste vergoedingen per meteropstelling. |
| `test_vtest_validator.py` | Elke bronrij komt precies één keer in precies één tabel terecht; een vast product zonder prijs is een fout. |
| `test_vtest_pipeline.py` | De bulkexport van werkboek tot CSV: weigeren gaat vóór half slagen, en decimalen blijven behouden. |
| `test_tariff_workbook.py` | De kop-rij verschilt per tabbladsoort — injectie staat op Excel-rij 3, alle andere op rij 4. |
| `test_tariff_normalizer.py` | Voetnootregels worden eruit gefilterd voordat ze als tarief doorgaan. |
| `test_tariff_of_rijen.py` | Een naamloze vervolgregel met het woord "of" is hetzelfde tarief in een tweede eenheid, geen nieuw tarief. |
| `test_tariff_pipeline.py` | Midden- en hoogspanning gaan naar hun eigen CSV en worden niet met laagspanning vermengd. |
| `test_curves_timestamps.py` | Excel-serienummers worden tijdstempels. 52.560 curverijen droegen ooit het ruwe getal — juist, maar onbruikbaar. |
| `test_profielen_workbook.py` | De Synergrid-profielen, nationaal en breed per netbeheerder, komen beide als lange vorm binnen. |
| `test_profielen_validator.py` | Profielgewichten sommeren tot één (Manifest §4.4), behalve SPP — dat is vermogen, geen verdeling. |
| `test_leveranciersnamen.py` | VREG schrijft dezelfde leverancier op meerdere manieren; alle gevallen komen letterlijk uit de export. |
| `test_utility_normalizer.py` | `dec()`: tekst naar `Decimal`. Eén test, op de plek waar elk bedrag van de brondata binnenkomt. |
| `test_p0_regressions.py` | Een nulprijs is geen ontbrekende prijs, en decimaaltekst wordt niet stil afgerond. |
| `test_tariefkaart_parser.py` | De prijsformule uit een tariefkaart: drie schrijfwijzen, en de eenheid die er soms alleen in de kolomkop staat — ct/kWh tegenover EUR/MWh is een factor tien. |

## `scrape` — de live weg naar vtest.be

| Bestand | Wat het bewaakt |
|---|---|
| `test_vtest_product_parser.py` | De resultatenpagina tegen echte markup: leveranciersnaam uit een `alt`-attribuut, links uit een `matomoLinks(...)`-aanroep. |
| `test_vtest_product_normalizer.py` | Datums, looptijden en prijsindicaties komen als vrije tekst binnen; onleesbaar levert `None`, nooit een gok. |
| `test_vtest_contractdetails.py` | Het detailpaneel draagt de contractmetadata die de resultatenpagina niet heeft — intekenperiode, doelgroep, tariefkaarten. |
| `test_vtest_product_matcher.py` | De koppeling van een gescrapet `vreg_id` aan een rij uit de bulkexport, best-effort maar nooit dubbel. |
| `test_vtest_calibration.py` | De terugrekenlogica die uit vtest.be's eigen kostenopbouw een tariefstructuur afleidt. De enige machinale controle op `config/heffingen/`. |
| `test_refine_matrix_volledigheid.py` | Een afgekapte matrixcombinatie wordt gemeld. vtest.be laadt lui bij; te vroeg stoppen levert een korte lijst zonder foutmelding. |

## `databank` — import, historiek en de controles daarop

| Bestand | Wat het bewaakt |
|---|---|
| `test_db_importer.py` | Het breedste bestand van dit domein: componentcodes naar kolommen, netbeheerdercode naar naam, de marktcurves, en de metadata-snapshots die alleen wijzigen als er echt iets wijzigde. |
| `test_db_scd2.py` | Dezelfde versie twee keer importeren mag geen tweede rij op dezelfde dag geven, en een ouder tariefjaar moet nog aangevuld kunnen worden. |
| `test_db_componentdekking.py` | Elke componentcode uit de normalizer komt bij de import ergens terecht — in een eigen prijsband of in een toeslagveld. |
| `test_db_productkenmerken.py` | De eigenschappen die alleen de live scrape kent (groene stroom, doelgroep) overleven de import. |
| `test_db_vreg_linking.py` | Een `vreg_id` hoort bij één product: matchen op leverancier en naam alleen liet hetzelfde id op twee producten belanden. |
| `test_db_repository.py` | De rekenengine gevoed uit de databank. Hier ligt vast dat de berekening uit de code komt en de data uit de databank. |
| `test_databank_audit.py` | De inhoudscontrole: lege kolommen, onbruikbare tarieven, inconsistente energievorm. 681 tests vonden een kolom die op 25.937 rijen leeg stond niet. |
| `test_databank_dump.py` | De zaaddump blijft klein genoeg voor git en actueel genoeg om mee te rekenen. |
| `test_golden.py` | Wanneer twee cellen "gelijk" heten bij de cel-voor-celvergelijking met het bron-XLSX. |
| `test_sanity_tariffs.py` | De plausibiliteitscontrole vindt haar bestanden echt. Ze zocht ooit namen die de pipeline nooit gebruikt heeft en meldde toch "geslaagd". |

## `masterdata` — handgeschreven gegevens in `config/`

| Bestand | Wat het bewaakt |
|---|---|
| `test_heffingen_repository.py` | De accijnzen en het energiefonds tegen de échte `config/heffingen/*.toml`, met de peildatum die het regime kiest. |
| `test_heffingen_validation.py` | Gaten, overlappingen en ontbrekende jaren in de tijdsas. Deze controle draait in CI, dus ze moet zelf betrouwbaar zijn. |
| `test_energiefonds_ingest.py` | De tarieftabel van vlaanderen.be: `<br>`-afgebroken labels, en "niet-residentiële" die "residentiële" als deelstring bevat. |
| `test_transport_tarieven.py` | Het Fluxys-vervoerstarief, dat in geen VREG-werkboek staat en elke gasfactuur ~25 EUR per jaar te laag maakte. |
| `test_hardware_repository.py` | Alleen cijfers die rechtstreeks uit een fabrikantdatasheet komen, met paginaverwijzing. |
| `test_hardware_zonnepaneel_ev_warmtepomp.py` | Idem, voor de masterdata die de fysieke assetsimulatie gelijktrekt met batterijen: één zonnepaneel-, EV- en warmtepompmodel, elk met een echte bronvermelding. |
| `test_hardware_validation.py` | `geverifieerd = true` zonder bronvermelding is een fout — dezelfde regel als bij heffingen. |
| `test_homologatie.py` | De C10/26-lijst: merken in wisselende schrijfwijze, en één serie met een 1- en een 3-fasige vermelding. |
| `test_netbeheerder.py` | Postcode naar netbeheerder. Postcode 2387 dekt twee netbeheerders en moet weigeren in plaats van gokken. |

## `rekenen` — de rekenengine en de hardwaremodellen

| Bestand | Wat het bewaakt |
|---|---|
| `test_energievergelijker.py` | De kern van `Calculator`: een variabel product rekent uit zijn eigen formule, en injectie wordt op de injectiereeks gewaardeerd. |
| `test_calculator_heffingen.py` | De heffingenkoppeling in `calculate()`, met een DNB-tabel waarin elk tarief expliciet 0 is zodat alleen de heffingen overblijven. |
| `test_maandpiek.py` | De geschatte maandpiek (4,218 kW) en de wettelijke ondergrens (2,5 kW) zijn twee getallen. Ze waren er lang één. |
| `test_tariefbron.py` | De CSV-bron en de databankbron voldoen aan hetzelfde contract; afwijken zou nergens gemeld worden. |

Drie bestanden hierboven importeren `DataRepository` uit
`experiments/remove/data_repository.py` in plaats van uit `src/`. Dat is geen
vergissing: er wordt niet meer uit CSV's gerekend, dus die lezer hoort niet in
de productiecode — maar `test_referentiefactuur.py` rekent dezelfde factuur wél
nog langs beide wegen na, en dat twee onafhankelijke paden op dezelfde euro
uitkomen is precies wat de overstap naar de databank rechtvaardigt. Het getal
overhouden en de vergelijking weggooien zou de waarde van die test omkeren.
| `test_referentiefactuur.py` | De volledige engine tegen een echte ENGIE-eindafrekening, inclusief de verklaring van elk restverschil. |
| `test_referentiefacturen_reeks.py` | Vier andere echte afrekeningen, elk voor wat de eerste niet raakt: een register "uitsluitend nacht", de netkost regel per regel, een contract dat niet op de markt bestaat, en een tweede netbeheerder. |
| `test_battery.py` | De batterij bewaakt haar eigen grenzen: laadtoestand, cyclustelling, en een nameplate van nul die vroeger deelde door nul. |
| `test_dispatch.py` | De brug tussen een fysiek assetmodel en een tijdreeks: zelfconsumptie-eerst-dispatch, per kwartier na te rekenen — overschot laadt, tekort ontlaadt, een volle batterij laat overschot naar injectie gaan. Ook de prijsarbitrage erbovenop: laadt maximaal tijdens de goedkoopste Belpex-uren, verkoopt maximaal tijdens de duurste, blijft zelfconsumptie ertussenin, `marktprijzen=None` raakt het bestaande gedrag niet, en arbitragekoop overschrijdt nooit de bestaande maandpiek. |
| `test_dispatch_ev_warmtepomp.py` | EV-laadprofiel (jaartotaal klopt, blijft binnen het laadvenster, weigert bij een fysiek te kort venster) en warmtepompprofiel (thermisch/COP zonder vermogenslimiet, correcte begrenzing erboven). |
| `test_omvormer.py` | Dezelfde zelfbewaking voor de omvormer — drie vermogensvelden die strikt positief moeten zijn. |
| `test_zonnepaneel.py` | Instraling, celtemperatuur en ouderdom naar DC-vermogen; elk van de drie kan stil een verkeerd getal geven. |
| `test_elektrische_wagen.py` | Een EV als verplaatsbare batterij met een kilometerteller: AC en DC laden kennen elk hun eigen limiet, de teller kan niet terug, en stranden geeft de werkelijk gereden afstand. |

## `dossier` — het gebruikersdossier

| Bestand | Wat het bewaakt |
|---|---|
| `test_gebruikers_model.py` | Welke combinaties van gegevens elkaar tegenspreken en dus niet mogen bestaan — regels, geen tarieven. |
| `test_gebruikers_toml.py` | `gebruiker.toml` blijft in zijn bestaande vorm werken; alles wat erbij komt is optioneel. |
| `test_dossier_sleutels.py` | Een onbekende sleutel wordt geweigerd. `afname_kwh` in plaats van `afname_dag_kwh` gaf een opgave van 0 kWh en een berekening die gewoon doorliep. |
| `test_gebruikers_periodes.py` | De periodesnijder, op elke contractwissel, tariefkaart, heffingenregime en jaarwissel. |
| `test_gebruikers_berekening.py` | Het invariant van dit domein: **knippen mag het totaal niet veranderen.** Ook `_maandpieken()`: het capaciteitstarief leunde altijd op de statische maandpiekschatting, ook met een echte kwartierreeks voorhanden — nu gemeten waar mogelijk, met een aanname voor ontbrekende maanden. |
| `test_gebruikers_schatting.py` | Verbruik schatten met de Synergrid-profielen. SPP is vermogen, SLP-EX en RLP0N zijn verdelingen; door elkaar halen scheelt factor vier. Bewaakt ook `gewichten_uit_databank()`, incl. de dubbele winterurenwissel die kale Python-datetimevergelijking ten onrechte als dezelfde netbeheerder-rij zag. |
| `test_gebruikers_repository.py` | De opslaglaag, op SQLite in het geheugen — de logica is bewust dialectonafhankelijk. |
| `test_fluvius_csv.py` | Vier registers, gas dubbel in m³ en kWh, drie validatiestatussen, en de zomertijdsprongen. Uit een echte export van drie jaar. |
| `test_gebruikers_orchestratie.py` | `bereken_dossier()`, geëxtraheerd uit `cli/gebruikers.py`, geeft dezelfde structuur terug als de CLI vroeger opbouwde — het fundament dat elk scenario hergebruikt. |
| `test_scenario_contract.py` | `AnderContractScenario.pas_toe()`: pure dossiersurgerie, muteert het origineel nooit, raakt enkel het gekozen aansluitingspunt, en bewaart de bestaande contractgrenzen bij meerdere contracten — anders overlappen twee `Verbruiksopgave`'s dezelfde, te brede deelperiode. |
| `test_scenario_basis.py` | De generieke scenario-diff: basislijn min scenario, `Exactheidsklasse.SCENARIO` weegt altijd minstens mee, en een mislukt punt in het scenario verdwijnt niet stil uit het verschil. |
| `test_scenario_opslag.py` | JSON/YAML-opslag van een `ScenarioResultaat`: geen `Decimal`/datum/enum die de encoder doet struikelen, beide formaten dragen dezelfde cijfers. |
| `test_scenario_batterij.py` | `BatterijScenario`'s dossiersurgerie en de gedeelde reeksopbouw (`scenario.reeksen`): Fluvius-meting bij voorkeur, SLP-EX als terugval, geen PV geeft een waarschuwing i.p.v. een stille nul, een bestaande PV-installatie wordt niet dubbel geteld via een nieuwe SPP-synthese, en prijsarbitrage schakelt zichzelf uit (met waarschuwing) op een niet-overal-dynamisch contract. |
| `test_scenario_reeksen.py` | `dag_nacht_masker()`/`verdeel_dag_nacht()` — de regressietest voor een echte fout: een gesimuleerde reeks zonder dag/nacht-registers viel bij `Kostberekening` terug op "alles is dagverbruik", wat zonnepanelen toevoegen op de echte databank een gestégen kost gaf en EV-nachtladen tegen het dure dagtarief rekende. |
| `test_scenario_zonnepaneel.py` | `ZonnepaneelScenario`'s dossiersurgerie: voegt de PV-asset met het gevraagde vermogen toe, muteert het origineel niet. |
| `test_scenario_elektrische_wagen_warmtepomp.py` | Idem voor `ElektrischeWagenScenario`/`WarmtepompScenario`, inclusief `vervangt_gas` dat het gasverbruik op nul zet zonder het origineel te raken. |
| `test_scenario_optimaliseer.py` | `optimaliseer_elektriciteitscontract()`, de "zware calculator" die elk kandidaatcontract afzet tegen het dossier: `kandidaat_contracten()`'s SQL-filters (energievorm, segment, peildatum) en dat hetzelfde product in twee contracttypes (variabel/dynamisch) twee aparte kandidaten oplevert; dat een gefaalde kandidaat de rest niet laat vervallen; en dat een batterij drie modi oplevert (zonder/met batterij/met arbitrage, dat laatste enkel op een dynamisch contract mét marktprijzen) met de drie gevraagde deltas (winst_contractwissel_alleen, winst_batterij_zelfde_contract, winst_gecombineerd) correct berekend. |

## `cli` — de commandoschil

| Bestand | Wat het bewaakt |
|---|---|
| `test_cli.py` | Dat elk `<groep> <actie>` bestaat en zijn opties aanvaardt, plus de twee handelingen die de actieve versie wijzigen: `publish` en `db import`. |

## `suite` — de organisatie zelf

| Bestand | Wat het bewaakt |
|---|---|
| `test_suite_indeling.py` | Elk testbestand draagt precies één bekende categorie. Houdt de tabel hierboven eerlijk in plaats van een momentopname. |
| `test_pakket_importeert.py` | Elke module van het pakket is importeerbaar. Ving een hernoeming die `simulator_battery.py` stukmaakte terwijl 809 tests groen bleven. |

---

## Fixturen

`tests/fixturen/` bevat het bewijsmateriaal waartegen getoetst wordt:

- `facturen/` — geanonimiseerde neerslag van echte afrekeningen. Alleen de
  cijfers worden overgenomen; het document zelf blijft lokaal in
  `data/referentie/`, dat buiten git valt.
- `vtest/` — opgeslagen markup van vtest.be, zodat de parsers tegen echte vorm
  draaien in plaats van tegen bedachte HTML.
- `metering/` — stukken uit een Fluvius-export van drie jaar, met EAN en
  meternummer vervangen.
- `databank/` — de zaaddump waarmee de integratietests in CI draaien.
- `dossiers/` — synthetische dossiers voor gevallen die niemands echte data zijn.
- `heffingen/` — kleine TOML-stukken voor de randgevallen van de tijdsas (gaten,
  overlappingen) die in de echte masterdata niet mogen voorkomen.

De regel eromheen: persoonsgegevens gaan niet in git. Een fixture die uit een
echt document komt draagt alleen de cijfers, nooit naam, adres, EAN of
klantnummer.
