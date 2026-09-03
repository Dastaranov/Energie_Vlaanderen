# Monsters van een Fluvius-verbruikshistoriek

Geanonimiseerde stukken uit een echte export van drie jaar. Structuur en
waarden zijn onaangeroerd; EAN en meternummer zijn vervangen door verzonnen
nummers die bij niemand horen. Het volledige bestand blijft lokaal in
`data/referentie/meterdata/` en valt buiten git.

De monsters bevatten met opzet vier dagen:

| Dag | Waarom |
|---|---|
| 15-01-2026 | winterdag, veel afname, weinig injectie |
| 15-06-2026 | zomerdag met veel injectie |
| 26-10-2025 | overgang naar wintertijd — 100 kwartieren op 96 lokale tijdstippen |
| 29-03-2026 | overgang naar zomertijd — 92 kwartieren, 02:00-03:00 bestaat niet |

## Wat er in het echte bestand zit

Vier eigenschappen die `metering/fluvius_csv.py` moet aankunnen, alle vier
gevonden door de volledige export te ontleden (210.625 regels elektriciteit,
52.657 gas):

1. **Vier registers**, niet twee: `Afname Dag`, `Afname Nacht`, `Injectie Dag`,
   `Injectie Nacht`. Het dag-/nachtonderscheid bepaalt het tarief.
2. **Gas staat er dubbel in**: elk uur één regel in m³ en één in kWh. Optellen
   per tijdstip telt volume en energie bij elkaar op.
3. **`Validatiestatus` onderscheidt drie dingen**: `Uitgelezen` (meting),
   `Geschat` (schatting van Fluvius, mét waarde) en `Geen verbruik` (géén
   meting, leeg volume). In de export: 508 geschat en 193 zonder meting.
4. **Lokale tijd met de zomertijdsprongen erin.** Elk register wordt apart naar
   UTC omgezet; binnen één register staan de twee doorgangen van de
   oktobernacht na elkaar, en daarop is het onderscheid te maken.

De EAN staat in de export als Excel-formule (`="541448..."`).

## Het monster opnieuw maken

Filter het volledige bestand op de vier datums en vervang EAN en meternummer.
De koptekst en het scheidingsteken (`;`, `utf-8-sig`) blijven zoals ze zijn.
