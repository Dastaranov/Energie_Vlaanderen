from decimal import Decimal as D
from pathlib import Path

import pytest

from energie_vlaanderen.calculation.calculator import Calculator
from energie_vlaanderen.data.repository import DataRepository, DataRepositoryError
from energie_vlaanderen.domain.models import Cost, Product, Profile
from energie_vlaanderen.settings import Settings


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
    with pytest.raises(
        DataRepositoryError,
        match="Ontbrekende datasetbestanden",
    ):
        DataRepository(tmp_path)