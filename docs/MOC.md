---
tags: [moc]
---

# MOC — Energie_Vlaanderen

Centrale ingang voor deze vault. Groepeert alle actieve documentatie per thema;
archief en code-referenties buiten de vault staan apart onderaan.

## Architectuur & CLI

- [[architecture|De 4 Controlepoorten (Audit Pipeline)]] — de audit-flow (sanity → sample → golden →
  approve/set-golden) met de bijhorende `audit *`-commando's.
- [[manifest|Manifest: Energie_Vlaanderen]] — de functionele/gegevenskundige specificatie van het hele
  platform (Manifest 3.0-concept).

## Prijsmodel

- [[price_model_low_voltage|Opbouw van de energieprijs in Vlaanderen]] — energiekost, nettarieven,
  heffingen en btw voor laagspanning, met volledige formules.

## Roadmap & status

- [[roadmap|ROADMAP: Energie_Vlaanderen]] — de strategische fasering (0.2-concept), incl. een
  status-paragraaf over de recente CLI-herstructurering.

## Onderhoud & planning

- [[jaarwissel 2026-2027|Jaarwissel 2026 → 2027]] — wat er in december nagekeken en aangevuld moet
  worden, en hoe. Bijna alle masterdata heeft een tijdsas; die schuift op 1 januari niet vanzelf mee.
- [[plan transporttarieven fluxys|Plan: transporttarieven aardgas (Fluxys)]] — uitgevoerd, met de
  herziene bronkeuze (vtest.be leidend boven de CREG-nota).
- [[plan parallellisatie|Plan: de core parallelliseren]] — gemeten in plaats van vermoed; de
  databankimport is intussen gebatcht, de scrape bewust nog niet parallel.

## Research

- [[Energie API en MPC Servers|Energie-API's en MPC-platformen]] — Fluvius/Elia/ENTSO-E-API's en
  MPC/EMS-architectuur voor particulieren en kmo's.
- [[Energievergelijkers en Simulators in Vlaanderen|Energievergelijkers en simulators in Vlaanderen]] —
  V-test, CREG Scan, commerciële en open-source vergelijkers/simulators.

## Archief

Puur ter referentie — inhoud niet bijgewerkt, niet geïntegreerd in de vault-structuur hierboven:

- `docs/history/Energie_Vlaanderen_P0_blockerfixes/` — P0-blockerfixes uit een eerdere projectfase.
- `docs/project/history/` — oudere README, projectstatus, roadmap v0.1-draft, architectuurschets en
  energie-notities (voorlopers van de huidige documenten hierboven).

## Buiten de vault

Deze vault is de `docs/`-map; onderstaande bestanden staan op de repo-root en
worden daarom niet als wikilink geopend, maar via een gewone relatieve link:

- [CLAUDE.md](../CLAUDE.md) — architectuur- en commando-referentie voor de codebase zelf (o.a. de
  `cli/`-package en de laagstructuur van `src/energie_vlaanderen/`).
- [README.md](../README.md) — installatie- en gebruiksinstructies (shell + eenmalige commando's).
