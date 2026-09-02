# Documentatie-overzicht — Energie_Vlaanderen

Centrale ingang voor de documentatie in deze map.

## Architectuur & CLI

- [De 4 Controlepoorten (Audit Pipeline)](audit%20pipeline/architecture.md) — de audit-flow (sanity →
  sample → golden → approve/set-golden) met de bijhorende `audit *`-commando's.
- [Manifest: Energie_Vlaanderen](manifest.md) — de functionele/gegevenskundige specificatie van het
  hele platform (Manifest 3.0-concept).

## Prijsmodel

- [Opbouw van de energieprijs in Vlaanderen](price_model_low_voltage.md) — energiekost, nettarieven,
  heffingen en btw voor laagspanning, met volledige formules.

## Onderhoud

- [Jaarwissel 2026 → 2027](jaarwissel%202026-2027.md) — wat er in december nagekeken en aangevuld
  moet worden, en hoe. Bijna alle masterdata heeft een tijdsas; die schuift op 1 januari niet vanzelf
  mee.

## Research

- [Energie-API's en MPC-platformen](research/Energie%20API%20en%20MPC%20Servers.md) —
  Fluvius/Elia/ENTSO-E-API's en MPC/EMS-architectuur voor particulieren en kmo's.
- [Energievergelijkers en simulators in Vlaanderen](research/Energievergelijkers%20en%20Simulators%20in%20Vlaanderen.md) —
  V-test, CREG Scan, commerciële en open-source vergelijkers/simulators.
- [Tarief bijzonder accijns](research/tarief%20bijzonder%20accijns.md) — wetsartikel waarop
  `config/heffingen/bijzondere_accijns_*.toml` zich baseert.
- [Tarief energiebijdrage](research/tarief%20energiebijdrage.md) — brontabel waarop
  `config/heffingen/bijdrage_energiefonds.toml` zich baseert.
- [Verbruiksprofielen](research/verbruiksprofielen.md) — wat SLP-EX, RLP0N en SPP zijn, waar Synergrid
  ze publiceert en hoe ze berekend worden; de inhoudelijke basis voor `ingest/profielen/`
  (zie CLAUDE.md, sectie "Verbruiksprofielen (Synergrid)").

## Archief

Puur ter referentie — inhoud niet bijgewerkt:

- `docs/project/history/` — oudere README, projectstatus, roadmap v0.1-draft, architectuurschets en
  energie-notities (voorlopers van de huidige documenten hierboven).

## Buiten deze map

- [../README.md](../README.md) — installatie- en gebruiksinstructies.
- [../ROADMAP.md](../ROADMAP.md) — de strategische fasering.
- [../CLAUDE.md](../CLAUDE.md) — architectuur- en commandoreferentie voor de codebase zelf.
