"""`dec()` uit `utility/normalizer.py`: tekst naar `Decimal`.

Eén test, en hij hoort er te zijn: hier komt elk bedrag van de brondata binnen.
Een duizendtalpunt dat als decimaalteken gelezen wordt, of `(Empty)` dat als nul
binnenkomt in plaats van als ontbrekend, is precies de stille fout waar dit
project last van heeft. Heette tot 2026-09-04 `test_parser.py`, wat het niet is.
"""
from decimal import Decimal as D
import pytest
from energie_vlaanderen.utility.normalizer import dec

pytestmark = pytest.mark.parsers


def test_decimalen():
    assert dec("1.234,56 €") == D("1234.56")
    assert dec("1,9710771") == D("1.9710771")
    assert dec("(Empty)") is None
