# Referentiedocumenten

Hier komen persoonlijke documenten die als referentiecase dienen: eindafrekeningen,
tussentijdse facturen, Fluvius-meterexports.

**Alles in deze map blijft lokaal.** `.gitignore` sluit de map uit behalve dit
bestand. Ze bevatten naam, adres, EAN en klantnummer, en `docs/manifest.md` §4.3
vraagt dat persoonsgegevens doelgebonden en minimaal verwerkt worden.

## Wat ermee gebeurt

Een factuur is hier het bewijsstuk, niet de test. Uit het document worden alleen
de *cijfers* overgenomen naar een geanonimiseerde fixture onder
`tests/fixturen/facturen/`: periode, verbruik, tarieven, en de kostenopbouw regel
per regel met btw-percentage. Die fixture gaat wél in git — zonder naam, adres,
EAN of klantnummer — en wordt de referentiecase waartegen de rekenengine getoetst
wordt.

Zo blijft de eis uit `CLAUDE.md` overeind dat elk vastgelegd getal in een test
zijn herkomst draagt: de fixture verwijst naar het document en de datum, het
document zelf blijft hier staan.

## Wat een factuur bruikbaar maakt

Nodig om er een volwaardige referentiecase van te maken:

- de **periode** (van/tot) en of het een eindafrekening of tussentijdse factuur is;
- **leverancier en productnaam**, en of het contract vast, variabel of dynamisch is;
- **verbruik** per register (dag/nacht/exclusief nacht) en **injectie**;
- de **maandpieken** als de factuur ze toont — anders rekent de engine met de
  gedocumenteerde schatting van 4,218 kW;
- de **kostenopbouw regel per regel**: energiekost, vaste vergoeding, nettarieven,
  heffingen, en per regel het btw-percentage;
- de **injectievergoeding** en hoe die verrekend is — of ze van de btw-basis
  afgetrokken werd of zelf met btw verhoogd. Dat is de openstaande vraag uit
  `docs/manifest.md` §14.

## Beperkingen van de huidige dataset

- Leveranciersproducten zijn er vanaf **januari 2025** (V-test-export, 20
  maandsnapshots tot augustus 2026).
- Distributienettarieven zijn er alleen voor **2026**.
- Marktprijzen voor dynamische contracten zitten in de lokale cache en hebben
  gaten; `energievergelijker market sync --start --end` vult ze aan.

Een afrekening over een periode die daarbuiten valt, is dus nog niet na te
rekenen — de engine stopt dan met een duidelijke fout in plaats van te benaderen.
