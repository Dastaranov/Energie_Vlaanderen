# EnergieVergelijker

## Structuur

- `parser.py`: robuuste CSV-inleeslaag en schema's
- `normalizer.py`: tekst, nulls, Belgische decimalen en geldafronding
- `models.py`: `Profile`, `Product` en `Cost`
- `repository.py`: databronnen en productmapping
- `calculator.py`: prijsberekeningen
- `market.py`: ENTSO-E marktdata
- `intervals.py`: Fluvius kwartierwaarden
- `scraper.py`: V-test snapshots
- `validation.py`: Excel/CSV sanity checks
- `cli.py`: command-line interface

## Gebruik

```bash
pip install -e ".[test]"
pytest -q
python energievergelijker.py --data /data --postcode 9280 --gemeente Lebbeke --year 2026 --month 6
```

De datamappen blijven extern. Plaats de bestaande CSV/XLSX-bestanden samen in de map die je via `--data` doorgeeft.
