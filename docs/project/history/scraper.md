# Werking Scraper

## Werkende ketting

```Plain Text
VNR-webpagina's
      │
      ▼
Web scraper / download discovery
      │
      ├── V-test® productdata.xlsx
      ├── energieprijscurves.xlsx
      ├── distributienettarieven elektriciteit.xlsx
      └── distributienettarieven aardgas.xlsx
      │
      ▼
Bronarchief met datum, URL en checksum
      │
      ▼
Specifieke Excel-parsers
      │
      ├── VTestWorkbookParser
      ├── EnergyCurveParser
      ├── ElectricityTariffParser
      └── GasTariffParser
      │
      ▼
Normalisatie en validatie
      │
      ├── master_vast_YYYY.csv
      ├── master_var_dyn_YYYY.csv
      ├── DNB_ELEK_YYYY.csv
      └── DNB_GAS_YYYY.csv
      │
      ▼
Pas bij geldige output: huidige productiegegevens vervangen
```

De officiële pagina publiceert een Excelbestand met alle producten die per maand in de V-test hebben gestaan.
Vaste producten staan op een ander tabblad dan variabele en dynamische producten.
Nettarieven en heffingen zitten niet in dat productbestand en alle vermelde prijzen zijn exclusief btw.
De pagina vermeldt ook expliciet een maandelijkse updatefrequentie.
Bv; Op 20 augustus 2026 vermeldt de pagina als laatste update 11 augustus 2026

[Bron: Vlaamse Nuts Regulator](https://www.vlaamsenutsregulator.be/cijfers/v-test-data-en-energieprijscurves)

De distributienettarieven worden via een andere officiële pagina aangeboden,
met afzonderlijke Excelbestanden voor elektriciteit en aardgas.
Voor 2026 staan daar momenteel zowel Distributienettarieven elektriciteit 2026 als Distributienettarieven aardgas 2026.

[Bron: Vlaamse Nuts Regulator](https://www.vlaamsenutsregulator.be/elektriciteit-en-aardgas/nettarieven/hoeveel-bedragen-de-distributienettarieven)
