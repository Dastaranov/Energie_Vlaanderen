# ENTSO-E Day-Ahead CLI

## Installatie

```bash
pip install rich
```

Het script zelf gebruikt alleen de Python-standaardbibliotheek. `rich` is optioneel en zorgt voor de fraaiere terminalweergave.

## API-key

Linux/macOS:

```bash
export ENTSOE_API_KEY="jouw-api-key"
```

PowerShell:

```powershell
$env:ENTSOE_API_KEY="jouw-api-key"
```

De sleutel kan ook rechtstreeks worden meegegeven met `--api-key`.

## Gebruik

Standaard vraagt het script morgen op. Als morgen nog niet beschikbaar is, toont het vandaag:

```bash
python entsoe_dayahead_cli.py
```

Een specifieke dag:

```bash
python entsoe_dayahead_cli.py --date 2025-01-01
```

Vandaag:

```bash
python entsoe_dayahead_cli.py --today
```

Met lokale cache:

```bash
python entsoe_dayahead_cli.py --cache entsoe_day_ahead_prices.json
```

Met refresh:

```bash
python entsoe_dayahead_cli.py --refresh
```

Eenvoudige weergave zonder Rich:

```bash
python entsoe_dayahead_cli.py --no-rich
```

Export van de getoonde dag:

```bash
python entsoe_dayahead_cli.py --date 2025-01-01 --export-json prijzen.json
```

## Terugval

Als de gevraagde datum geen prijzen bevat, vraagt het script exact één kalenderdag eerder op. Dat geldt zowel voor de standaardaanvraag als voor `--date`.
