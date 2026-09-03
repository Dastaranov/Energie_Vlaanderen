# Datasheets en homologatielijsten

Bronmateriaal voor `config/hardware/`: fabrikantsdatasheets van batterijen en
omvormers, en de Synergrid C10/26-lijst van gehomologeerde
productie-eenheden.

**De bestanden zelf blijven lokaal** (`.gitignore` sluit deze map uit behalve dit
bestand). Ze zijn samen tientallen MB binair, en de fabrikants-PDF's zijn
auteursrechtelijk beschermd materiaal van derden. Wat eruit overgenomen wordt,
staat met bronvermelding in de TOML-masterdata — `bron`, `datasheet_versie`,
`datasheet_datum` en `opgehaald_op` per model.

## De C10/26-lijst

`synergrid C10-26/c10_26_list_of_pgu_compliant_with_c10_11_ed2_1_12_2019.xlsx`

De officiële lijst van productie-eenheden (omvormers, batterijen, WKK's) die
voldoen aan C10/11 en dus op een Belgisch distributienet mogen. Bijgewerkt
2026-08-26; 8.168 gehomologeerde eenheden van 334 merken, plus een blad met 74
vervallen homologaties.

Drie bladen:

| Blad | Inhoud |
|---|---|
| `C10-26 power-generating units` | de geldige homologaties; kop op Excel-rij 10 |
| `explanation` | toelichting bij de kolommen |
| `C10-26 expired homologations` | vervallen homologaties |

De kolommen sluiten rechtstreeks aan op `hardware.models.BatterijSpec`:
Synergrid-referentie (`GLVxxx-yy-zzzz`), merk, productserie, modelreferentie,
firmwareversie, power control system, `Pac,r` (W), `Smax` (VA) en 1- of 3-fasig.

`hardware/homologatie.py` leest het bestand en `energievergelijker audit
hardware --c10-26` legt de masterdata ernaast. Nieuwe versie ophalen bij
Synergrid en hier vervangen; het pad is instelbaar met
`ENERGIEVERGELIJKER_C1026_PAD`.
