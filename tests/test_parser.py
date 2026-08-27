from decimal import Decimal as D
import pytest
from energie_vlaanderen.utility.normalizer import dec

def test_decimalen():
    assert dec("1.234,56 €") == D("1234.56")
    assert dec("1,9710771") == D("1.9710771")
    assert dec("(Empty)") is None
