from decimal import Decimal as D
from pathlib import Path

import pytest

from energievergelijker_v3 import (
    Calculator,
    DataRepository,
    Profile,
    Product,
)

@pytest.mark.integration
def test_postcode_lebbeke(data_root: Path):
    repository = DataRepository(data_root)

    assert repository.dnb_for(
        "9280",
        "Lebbeke",
    ) == (
        "Fluvius Midden-Vlaanderen",
        "FMV",
    )

def test_variable_formula():
    formula = {
        "a": D("0.11"),
        "b": D("0"),
        "c": D("0"),
        "d": D("0"),
        "z": D("1.51"),
        "A": D("85.31"),
        "B": None,
        "C": None,
        "D": None,
        "name_A": "x",
        "name_B": "",
        "name_C": "",
        "name_D": "",
    }

    assert Calculator.formula_ct(formula) == D("10.8941")


def test_fixed_supplier():
    class EmptyRepository:
        pass

    calculator = Calculator(EmptyRepository())

    profile = Profile(
        "9280",
        "Lebbeke",
        afname_dag_kwh=D("2000"),
        afname_nacht_kwh=D("1000"),
    )

    product = Product(
        2026,
        6,
        "Woning",
        "Elektriciteit",
        "Afname",
        "X",
        "Y",
        "vast",
        {
            "day": D("20"),
            "night": D("15"),
            "fixed_fee": D("60"),
            "green": D("1"),
            "wkk": D("0.3"),
        },
    )

    cost, warnings = calculator.supplier_cost(
        product,
        profile,
    )

    assert cost == D("649")
    assert not warnings

def test_repository_reports_missing_data(tmp_path: Path):
    from energievergelijker_v3.repository import (
        DataRepositoryError,
    )

    with pytest.raises(
        DataRepositoryError,
        match="Datamap is onvolledig",
    ):
        DataRepository(tmp_path)