from pathlib import Path
from decimal import Decimal as D
import pandas as pd
import pytest
from experiments import RobustCsvParser, CsvSchema, ParseError
from src.energie_vlaanderen.utility.normalizer import dec

def test_decimalen():
    assert dec("1.234,56 €") == D("1234.56")
    assert dec("1,9710771") == D("1.9710771")
    assert dec("(Empty)") is None

def test_cp1252_multiline_en_delimiter(tmp_path: Path):
    path = tmp_path / "input.csv"
    path.write_bytes('Jaar;Naam;Beschrijving\r\n2026;Energie;"regel 1\nregel 2 met €"\r\n'.encode('cp1252'))
    df = RobustCsvParser(schema=CsvSchema(("Jaar", "Naam"))).read(path)
    assert len(df) == 1
    assert "regel 2" in df.loc[0, "Beschrijving"]
    assert df.attrs["delimiter"] == ";"

def test_schemafout(tmp_path: Path):
    path = tmp_path / "fout.csv"; path.write_text("A;B\n1;2\n", encoding="utf-8")
    with pytest.raises(ParseError):
        RobustCsvParser(schema=CsvSchema(("Jaar",))).read(path)
