# Tariefkaartarchief

De tariefkaarten van de contracten die vtest.be vandaag toont, zoals wij ze op
het moment van ophalen gezien hebben.

## Waarom dit bestaat

Een variabel contract bevriest bij ondertekening zijn **formule**, niet zijn
prijs: de vaste vergoeding en de coëfficiënten liggen vast in de kaartversie
die de klant tekende, en alleen de index beweegt nog. De V-test-export levert
per maand de kaart die op dat moment *verkocht* wordt.

Die twee lopen uiteen zodra een contract een tijdje loopt. Op een echte
Eneco-afrekening scheelde alleen al de vaste vergoeding 11,74 EUR per jaar
(61,321 in de export tegenover 49,59 op de kaart van de klant); bij ENGIE
"Direct Online" week bovendien de indexcoëfficiënt af (0,0954 tegenover
0,0996), en de Eneco-kaart uit 2023 gebruikt zelfs een *kwartaal*index waar de
export een maandindex noemt.

Dat verschil is niet met code te overbruggen — het is een gegeven dat we niet
hebben. En anders dan de index, die uit de day-ahead historiek altijd nog terug
te rekenen valt, is een tariefkaart **weg zodra de leverancier hem vervangt**.
Vandaag archiveren is de enige manier om een contract van vandaag over drie
jaar nog exact na te rekenen.

Sommige leveranciers houden zelf een kaartarchief bij. Dat is per leverancier
te bekijken en verandert niets aan deze map: wat hier staat is wat wij zelf
waargenomen hebben, met een hash erbij.

## Vorm

```
data/tariefkaarten/
  index.json                       het register van waarnemingen
  documenten/<xx>/<sha256>.pdf     de documenten, op inhoud geadresseerd
```

Inhoudsgeadresseerd, en dat lost twee dingen tegelijk op. Leveranciers delen
één kaart over meerdere producten, dus hetzelfde document komt langs meerdere
URL's binnen en wordt één keer bewaard. En een kaart die *wijzigt* krijgt
vanzelf een nieuw pad, zodat de oude versie blijft staan — precies wat een
archief moet doen. De vorige versies staan per contract onder
`eerdere_versies` in het register.

Het register houdt ook de **mislukte** pogingen bij. Een leverancier die zijn
kaart achter een aanmeldpagina zet levert gewoon HTML op; dat stil als "kaart"
bewaren zou het archief onbetrouwbaar maken zonder dat iets faalt. Er wordt
daarom op de PDF-signatuur getoetst en niet op de bestandsnaam.

## Omvang

Een kaart is gemiddeld een halve MB. Een run die niets nieuws vindt kost geen
schijfruimte — inhoudsgeadresseerd, dus een ongewijzigde kaart schrijft niets.
Wat wél groeit is het aantal *wijzigingen*: leveranciers vernieuwen hun kaarten
ongeveer maandelijks, dus reken op de orde van 150 MB per jaar. Dat is de prijs
van het enige gegeven dat niet retroactief te herstellen is.

## Bijwerken

```bash
python scripts/archiveer_tariefkaarten.py --droogloop   # wat zou er opgehaald worden
python scripts/archiveer_tariefkaarten.py               # ophalen
python scripts/archiveer_tariefkaarten.py --leverancier ENGIE
```

De bron is `vtest_contract.link_tariefkaart` van de **lopende** snapshots
(`geldig_tot is null`). Een afgesloten snapshot hoort bij een kaart die we
destijds al gezien zouden moeten hebben; die nu alsnog ophalen zou het huidige
document onder een oude waarneming hangen.

Deze map valt buiten git — auteursrechtelijk materiaal van derden, en
afgeleide data. Het register ook: het beschrijft wat er lokaal staat.
