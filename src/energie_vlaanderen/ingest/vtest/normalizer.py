from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import pandas as pd

from .....experiments.constants import MONTHS
from ...utility.normalizer import clean_text, dec


class VTestNormalizationError(RuntimeError):
    pass


ALLOWED_SEGMENTS = {
    "woning": "Woning",
    "onderneming": "Onderneming",
}

ALLOWED_ENERGY_TYPES = {
    "elektriciteit": "Elektriciteit",
    "gas": "Gas",
    "aardgas": "Gas",
}

ALLOWED_DIRECTIONS = {
    "afname": "Afname",
    "injectie": "Injectie",
    "teruglevering": "Injectie",
}

PRODUCT_TYPES = {
    "vast": "vast",
    "variabel": "variabel",
    "dynamisch": "dynamisch",
}

COMPONENT_MAPPING = {
    "vaste vergoeding": "fixed_fee",
    "kosten groene stroom": "green",
    "groene stroom": "green",
    "kosten wkk": "wkk",
    "wkk": "wkk",
    "dynamisch tarief": "dynamic",
    "uitsluitend nacht": "exclusive_night",
    "enkelvoudige meter dagtarief": "single",
}


@dataclass(frozen=True)
class RowIssue:
    source_sheet: str
    source_row: int | None
    severity: str
    message: str


@dataclass(frozen=True)
class NormalizedVTestData:
    fixed: pd.DataFrame
    variable_dynamic: pd.DataFrame
    issues: tuple[RowIssue, ...]

    @property
    def errors(self) -> tuple[RowIssue, ...]:
        return tuple(
            issue
            for issue in self.issues
            if issue.severity == "error"
        )

    @property
    def warnings(self) -> tuple[RowIssue, ...]:
        return tuple(
            issue
            for issue in self.issues
            if issue.severity == "warning"
        )


class VTestDataNormalizer:
    def normalize(
        self,
        fixed: pd.DataFrame,
        variable_dynamic: pd.DataFrame,
    ) -> NormalizedVTestData:
        issues: list[RowIssue] = []

        normalized_fixed = self._normalize_frame(
            fixed,
            expected_types={"vast"},
            issues=issues,
        )

        normalized_variable = self._normalize_frame(
            variable_dynamic,
            expected_types={
                "variabel",
                "dynamisch",
            },
            issues=issues,
        )

        return NormalizedVTestData(
            fixed=normalized_fixed,
            variable_dynamic=normalized_variable,
            issues=tuple(issues),
        )

    def _normalize_frame(
        self,
        frame: pd.DataFrame,
        expected_types: set[str],
        issues: list[RowIssue],
    ) -> pd.DataFrame:
        if frame.empty:
            return pd.DataFrame()

        rows: list[dict[str, Any]] = []

        for _, source_row in frame.iterrows():
            normalized = self._normalize_row(
                source_row,
                expected_types=expected_types,
                issues=issues,
            )

            if normalized is not None:
                rows.append(normalized)

        if not rows:
            return pd.DataFrame()

        df = pd.DataFrame(rows)
        return df.drop_duplicates(
            subset=[
                "year",
                "month",
                "segment",
                "energy",
                "direction",
                "supplier",
                "product",
                "product_type",
                "component",
            ],
            keep="first",
        )
           
    def _normalize_row(
        self,
        row: pd.Series,
        expected_types: set[str],
        issues: list[RowIssue],
    ) -> dict[str, Any] | None:
        source_sheet = clean_text(
            row.get("source_sheet")
        )

        source_row = self._source_row(
            row.get("source_row")
        )

        def add_issue(
            severity: str,
            message: str,
        ) -> None:
            issues.append(
                RowIssue(
                    source_sheet=source_sheet,
                    source_row=source_row,
                    severity=severity,
                    message=message,
                )
            )

        year = self._year(
            row.get("Jaar")
        )

        if year is None:
            add_issue(
                "error",
                "Jaar ontbreekt of is ongeldig.",
            )
            return None

        month = self._month(
            row.get("Maand")
        )

        if month is None:
            add_issue(
                "error",
                "Maand ontbreekt of is ongeldig.",
            )
            return None

        supplier = clean_text(
            row.get("Handelsnaam")
        )

        if not supplier:
            add_issue(
                "error",
                "Handelsnaam ontbreekt.",
            )
            return None

        product_name = clean_text(
            row.get("Productnaam")
        )

        if not product_name:
            add_issue(
                "error",
                "Productnaam ontbreekt.",
            )
            return None

        segment = self._canonical(
            row.get("Segment"),
            ALLOWED_SEGMENTS,
        )

        if segment is None:
            add_issue(
                "error",
                "Segment is onbekend.",
            )
            return None

        energy_type = self._canonical(
            row.get("Energietype"),
            ALLOWED_ENERGY_TYPES,
        )

        if energy_type is None:
            add_issue(
                "error",
                "Energietype is onbekend.",
            )
            return None

        direction = self._canonical(
            row.get("Contracttype"),
            ALLOWED_DIRECTIONS,
        )

        if direction is None:
            add_issue(
                "error",
                "Contracttype of richting is onbekend.",
            )
            return None

        product_type = self._product_type(
            row
        )

        if product_type is None:
            add_issue(
                "error",
                "Producttype ontbreekt of is onbekend.",
            )
            return None

        if product_type not in expected_types:
            add_issue(
                "error",
                "Producttype staat in de verkeerde tabel.",
            )
            return None

        component_label = clean_text(
            row.get("Prijsonderdeel")
        )

        if not component_label:
            add_issue(
                "error",
                "Prijsonderdeel ontbreekt.",
            )
            return None

        component_key = self._component_key(
            component_label
        )

        price = dec(
            row.get("Prijs")
        )

        coefficients = {
            name: dec(
                row.get(name),
                Decimal("0"),
            )
            for name in (
                "a",
                "b",
                "c",
                "d",
                "z",
            )
        }

        index_names: dict[str, str] = {}
        index_values: dict[str, Decimal | None] = {}

        for letter in "ABCD":
            index_names[letter] = self._index_name(
                row,
                letter,
            )

            index_values[letter] = self._index_value(
                row,
                letter,
            )

        for coefficient_name, index_letter in (
            ("a", "A"),
            ("b", "B"),
            ("c", "C"),
            ("d", "D"),
        ):
            coefficient = coefficients[
                coefficient_name
            ]

            if (
                coefficient != Decimal("0")
                and index_values[index_letter] is None
            ):
                add_issue(
                    "warning",
                    "Niet-nulcoëfficiënt "
                    f"{coefficient_name} zonder "
                    f"indexwaarde {index_letter}.",
                )

        if (
            product_type == "vast"
            and price is None
        ):
            add_issue(
                "warning",
                "Vast prijsonderdeel zonder prijs.",
            )

        return {
            "year": year,
            "month": month,
            "segment": segment,
            "energy": energy_type,
            "direction": direction,
            "supplier": supplier,
            "product": product_name,
            "product_type": product_type,
            "component": component_key,
            "component_label": component_label,
            "price": price,
            "a": coefficients["a"],
            "b": coefficients["b"],
            "c": coefficients["c"],
            "d": coefficients["d"],
            "z": coefficients["z"],
            "index_name_A": index_names["A"],
            "index_name_B": index_names["B"],
            "index_name_C": index_names["C"],
            "index_name_D": index_names["D"],
            "index_value_A": index_values["A"],
            "index_value_B": index_values["B"],
            "index_value_C": index_values["C"],
            "index_value_D": index_values["D"],
            "source_sheet": source_sheet,
            "source_row": source_row,
        }

    @staticmethod
    def _canonical(
        value: Any,
        mapping: dict[str, str],
    ) -> str | None:
        normalized = clean_text(
            value
        ).casefold()

        return mapping.get(
            normalized
        )

    @staticmethod
    def _year(
        value: Any,
    ) -> int | None:
        number = dec(
            value
        )

        if number is None:
            return None

        if number != number.to_integral_value():
            return None

        year = int(
            number
        )

        if not 2000 <= year <= 2100:
            return None

        return year

    @staticmethod
    def _month(
        value: Any,
    ) -> int | None:
        text = clean_text(
            value
        ).casefold()

        if text in MONTHS:
            return MONTHS[text]

        number = dec(
            value
        )

        if number is None:
            return None

        if number != number.to_integral_value():
            return None

        month = int(
            number
        )

        if not 1 <= month <= 12:
            return None

        return month

    @staticmethod
    def _product_type(
        row: pd.Series,
    ) -> str | None:
        columns = (
            "Vast/variabel/dynamisch",
            "Variabel/Dynamisch",
            "Contractformule",
            "Producttype",
        )

        for column in columns:
            value = clean_text(
                row.get(column)
            ).casefold()

            if value in PRODUCT_TYPES:
                return PRODUCT_TYPES[value]

        return None

    @staticmethod
    def _component_key(
        label: str,
    ) -> str:
        folded = label.casefold()

        if (
            "tweevoudige" in folded
            and (
                "nacht" in folded
                or "dal" in folded
            )
        ):
            return "night"

        if (
            "tweevoudige" in folded
            and (
                "dag" in folded
                or "piek" in folded
            )
        ):
            return "day"

        for phrase, key in COMPONENT_MAPPING.items():
            if phrase in folded:
                return key

        return folded

    @staticmethod
    def _index_name(
        row: pd.Series,
        letter: str,
    ) -> str:
        exact_column = (
            f"Indexatieparameter {letter} "
            "(a.A + b.B + c.C + d.D + z)"
        )

        value = clean_text(
            row.get(exact_column)
        )

        if value:
            return value

        return clean_text(
            row.get(
                f"Indexatieparameter {letter}"
            )
        )

    @staticmethod
    def _index_value(
        row: pd.Series,
        letter: str,
    ) -> Decimal | None:
        prefixes = (
            f"Waarde {letter} (€/MWh)",
            f"Waarde {letter}",
        )

        for column in row.index:
            label = clean_text(
                column
            )

            if not any(
                label.startswith(prefix)
                for prefix in prefixes
            ):
                continue

            value = dec(
                row.get(column)
            )

            if value is not None:
                return value

        return None

    @staticmethod
    def _source_row(
        value: Any,
    ) -> int | None:
        number = dec(
            value
        )

        if number is None:
            return None

        if number != number.to_integral_value():
            return None

        return int(
            number
        )
