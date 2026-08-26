from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pandas as pd

from energie_vlaanderen.domain.models import Product
from energie_vlaanderen.utility.normalizer import dec


class DataRepositoryError(RuntimeError):
    pass


class DataRepository:
    """
    Repository voor de canonieke V-test datasets.

    Leest uitsluitend de output van ingest/vtest/pipeline.py.
    """

    REQUIRED_FILES = (
        "master_vast.csv",
        "master_var_dyn.csv",
    )

    def __init__(
        self,
        data_dir: Path,
    ) -> None:

        self.data_dir = Path(data_dir)

        self.fixed_file = (
            self.data_dir
            / "vtest"
            / "master_vast.csv"
        )

        self.variable_file = (
            self.data_dir
            / "vtest"
            / "master_var_dyn.csv"
        )

        self._validate()

        self.fixed = pd.read_csv(
            self.fixed_file,
            sep=";",
            encoding="utf-8-sig",
        )

        self.variable = pd.read_csv(
            self.variable_file,
            sep=";",
            encoding="utf-8-sig",
        )

    def _validate(self) -> None:

        missing: list[str] = []

        if not self.fixed_file.is_file():
            missing.append(str(self.fixed_file))

        if not self.variable_file.is_file():
            missing.append(str(self.variable_file))

        if missing:
            raise DataRepositoryError(
                "Ontbrekende datasetbestanden:\n"
                + "\n".join(missing)
            )

    def products(
        self,
        year: int,
        month: int,
        segment: str,
        *,
        energy: str = "electricity",
        direction: str = "consumption",
    ) -> list[Product]:

        frames = [
            self.fixed,
            self.variable,
        ]

        result: list[Product] = []

        for frame in frames:

            filtered = frame.loc[
                (frame["year"] == year)
                & (frame["month"] == month)
                & (frame["segment"] == segment)
                & (frame["energy"] == energy)
                & (frame["direction"] == direction)
            ]

            grouped = filtered.groupby(
                [
                    "year",
                    "month",
                    "segment",
                    "energy",
                    "direction",
                    "supplier",
                    "product",
                    "product_type",
                ],
                dropna=False,
            )

            for key, rows in grouped:

                (
                    row_year,
                    row_month,
                    row_segment,
                    row_energy,
                    row_direction,
                    supplier,
                    product_name,
                    product_type,
                ) = key

                components: dict[str, Decimal] = {}
                formulas: dict[str, dict] = {}

                source = ""

                for _, row in rows.iterrows():

                    source = str(
                        row.get(
                            "source_sheet",
                            "",
                        )
                    )

                    component = str(
                        row["component"]
                    )

                    price = dec(
                        row.get("price")
                    )

                    if price is not None:
                        components[
                            component
                        ] = price

                    formula = {}

                    for letter in (
                        "a",
                        "b",
                        "c",
                        "d",
                        "z",
                    ):
                        value = dec(
                            row.get(letter)
                        )

                        if value is not None:
                            formula[
                                letter
                            ] = value

                    for suffix in (
                        "A",
                        "B",
                        "C",
                        "D",
                    ):
                        name = row.get(
                            f"index_name_{suffix}"
                        )

                        value = row.get(
                            f"index_value_{suffix}"
                        )

                        if (
                            pd.notna(name)
                            and name
                        ):
                            formula[
                                f"index_{suffix}"
                            ] = {
                                "name": str(name),
                                "value": (
                                    dec(value)
                                ),
                            }

                    if formula:
                        formulas[
                            component
                        ] = formula

                result.append(
                    Product(
                        year=int(row_year),
                        month=int(row_month),
                        segment=str(row_segment),
                        energy=str(row_energy),
                        direction=str(row_direction),
                        supplier=str(supplier),
                        name=str(product_name),
                        kind=str(product_type),
                        components=components,
                        formulas=formulas,
                        source=source,
                    )
                )

        return result