CSV / brondata
   ↓
DataManager
   ↓
Referentiedata in objecten
   - Contract
   - DnbTariefStructuur
   - DnbPerGemeente

Klant + meetdata
   ↓
Klant
ElektriciteitMeterSnapshot / GasMeterSnapshot
ElektriciteitMeetReeks / GasMeetReeks
   ↓
VerbruikManager / MeterDataManager
   ↓
VerbruiksSamenvatting
   ↓
KlantProfielService
   ↓
- geselecteerde contracten
- DNB-elek klanttype
- DNB-gas klanttype
- juiste DNB-structuren
   ↓
PricingEngine



A. DataManager = referentiedata-laag
Centrale brondata-manager.
Wat erin zit:

- vaste contracten
- variabele/dynamische contracten
- DNB-elektriciteit structuren
DNB-gas structuren
- gemeente → DNB mapping

Wat hij doet:

- CSV’s inladen
- normaliseren
- groeperen
- filteren
- juiste DNB op basis van adres ophalen

Belangrijk
DataManager bevat geen klantverbruik
→ alleen de externe referentiedata

B. Klant = wie is de klant?
Dit object bundelt alle klantcontext:

- postcode
- gemeente
- segment (woning / onderneming)
- heeft elektriciteit / gas
- digitale meter
- meter type
- prosument / PV / batterij / laadpaal

Waarom nodig?
Omdat niet elke klant:

- dezelfde contracten kan kiezen
- hetzelfde DNB-klanttype heeft
- dezelfde tariefstructuur gebruikt


C. ElektriciteitMeterSnapshot en GasMeterSnapshot = ruwe meterstanden
Dit zijn de fysieke metingen, geen prijsinfo.
Elektriciteit
Een snapshot bevat de cumulatieve telwerken van de digitale meter:

- afname dag
- afname nacht
- injectie dag
- injectie nacht
- eventueel totalen

Fluvius beschrijft die telwerken expliciet als:

1.8.1 afname dag
1.8.2 afname nacht
2.8.1 injectie dag
2.8.2 injectie nacht. [fluvius.be]

Gas
Een snapshot bevat enkel:

- gasmeterstand in m³

Waarom deze laag belangrijk is
Dit is de fysieke werkelijkheid.
Verbruik wordt hieruit afgeleid als verschil tussen twee meetmomenten.

D. ElektriciteitMeetReeks / GasMeetReeks = dag/uur/kwartierdata
Dit zijn de gedetailleerde tijdsreeksen.
Elektriciteit
Kan bevatten:

- afname per dag / uur / kwartier
- injectie per dag / uur / kwartier

Gas
Kan bevatten:

- gasverbruik per dag / uur

Fluvius biedt effectief CSV-/rapportdata aan met:

- voor elektriciteit: dag- en kwartierwaarden en piekvermogens
- voor gas: dag- en uurwaarden en piekvermogens (voor AMR) via hun datarapportkanaal. [stackoverflow.com]

Waarom dit belangrijk is
Deze laag is noodzakelijk voor:

- dynamische contracten
- capaciteitstarief
- batterijsimulatie
- PV-injectie
- load shifting

E. MeterDataManager = ingestie van meetdata
Dit is de laag die meetdata binnenbrengt.
Wat hij doet

- Fluvius CSV inlezen
- dag/uur/kwartierdata herkennen
- DataFrame normaliseren
- manuele meetpunten toelaten
- meetreeksen beheren

Waarom aparte manager?
Omdat meetdata een ander probleem is dan:

- referentiedata (DataManager)
- afleiding van verbruik (VerbruikManager)

Dus:

- DataManager = contracten en tarieven
- MeterDataManager = ruwe meetdata
- VerbruikManager = afgeleide verbruiken

Dat is een nette scheiding.

F. VerbruiksSamenvatting = afgeleid verbruik
Dit object is de brug tussen:

- ruwe meterdata
- prijsberekening

Wat erin zit

- totale elektriciteitsafname
- totale elektriciteitsinjectie
- detail afname/injectie dag/nacht
- gas in m³
- optioneel gas in kWh
- maandpieken
- optioneel kwartierprofielen

Waarom nodig?
Omdat de pricing engine straks niet rechtstreeks op ruwe meterstanden werkt, maar op:

- afgeleide volumes
- afgeleide pieken
- bruikbare totalen


G. VerbruikManager = afleiding van verbruik
Dit is de laag die verbruik berekent uit snapshots en profielen.
Wat hij doet

- snapshots bewaren
- verschillen tussen snapshots berekenen
- verbruikssamenvattingen opbouwen
- kwartierprofielen koppelen
- maandpieken berekenen
- validatie doen t.o.v. de klantcontext

Kort:
- VerbruikManager vertaalt:
meterstanden / meetdata -> verbruiksdata

H. KlantProfielService = selectielaag
Dit is de laag die interpreteert wat de klant nodig heeft.
Wat hij bepaalt

- welk DNB-elek klanttype van toepassing is
- welk DNB-gas klanttype van toepassing is
- welke contracten relevant zijn
- welke DNB-structuren moeten gebruikt worden

Kort:
KlantProfielService vertaalt:
klant + verbruik -> juiste tarievenstructuren