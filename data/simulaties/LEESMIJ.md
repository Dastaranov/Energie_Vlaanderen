# Scenarioresultaten

Hier landen de JSON/YAML-bestanden die `energie_vlaanderen.scenario.opslag.sla_op()`
wegschrijft: het resultaat van een "wat als"-scenario (ander contract,
batterij, zonnepanelen, elektrische wagen, warmtepomp) — basislijn, scenario
en het verschil, met volledige kostendetail per energiedrager en per
deelperiode.

**Alles hier blijft lokaal**, net als `data/referentie/`: een scenarioresultaat
draagt het dossier van de gebruiker mee (postcode, verbruik, gekozen
contracten), en dat is persoonsgegevens in de zin van `docs/manifest.md` §4.3.

Wie een scenarioresultaat wil delen (bv. om een webinterface tegen te testen),
anonimiseert het eerst — of bouwt het na met een synthetisch dossier zoals
`tests/fixturen/dossiers/synthetisch_woning.toml`.
