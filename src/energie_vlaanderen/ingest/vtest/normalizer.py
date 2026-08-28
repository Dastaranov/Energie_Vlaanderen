from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import pandas as pd

from energie_vlaanderen.utility.constants import MONTHS
from energie_vlaanderen.utility.normalizer import clean_text, dec

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

FORMULA_COMPONENTS = {
    "single",
    "day",
    "night",
    "exclusive_night",
    "dynamic",
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
        return df
           
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

        coefficients = self._coefficients(row)

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

        if component_key in FORMULA_COMPONENTS:
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
                        "error",
                        "Niet-nulcoëfficiënt "
                        f"{coefficient_name} zonder "
                        f"indexwaarde {index_letter}.",
                    )
        if (
            product_type in {"variabel", "dynamisch"}
            and component_key in FORMULA_COMPONENTS
        ):
            has_coefficient = any(
                coefficients[name] != Decimal("0")
                for name in ("a", "b", "c", "d")
            )

            has_index = any(
                value is not None
                for value in index_values.values()
            )

            if has_coefficient and not has_index:
                add_issue(
                    "error",
                    "Variabel of dynamisch tarief heeft "
                    "coëfficiënten maar geen indexwaarden.",
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
    def _component_key(label: str) -> str:
        folded = label.casefold()

        is_fixed_fee = (
            "vaste vergoeding" in folded
        )

        if is_fixed_fee:
            if (
                "uitsluitend nacht" in folded
                or "exclusief nacht" in folded
            ):
                return "fixed_fee_exclusive_night"

            if "tweevoudig" in folded:
                return "fixed_fee_double"

            if "enkelvoudig" in folded:
                return "fixed_fee_single"

            return "fixed_fee"

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

    @classmethod
    def _coefficients(
        cls,
        row: pd.Series,
    ) -> dict[str, Decimal]:
        zero = Decimal("0")

        a = dec(row.get("a"), zero)
        b = dec(row.get("b"), zero)
        c = dec(row.get("c"), zero)

        if cls._uses_legacy_index_schema(row):
            # Oude formule: a.X + b.Y + c.Z + d
            return {
                "a": a,
                "b": b,
                "c": c,
                "d": zero,
                "z": dec(row.get("d"), zero),
            }

        # Nieuwe formule: a.A + b.B + c.C + d.D + z
        return {
            "a": a,
            "b": b,
            "c": c,
            "d": dec(row.get("d"), zero),
            "z": dec(row.get("z"), zero),
        }

    @classmethod
    def _index_name(
        cls,
        row: pd.Series,
        letter: str,
    ) -> str:
        legacy_mapping = {
            "A": "X",
            "B": "Y",
            "C": "Z",
            "D": None,
        }

        source_letter = letter

        if cls._uses_legacy_index_schema(row):
            source_letter = legacy_mapping[letter]

        if source_letter is None:
            return ""

        prefix = f"Indexatieparameter {source_letter}"

        for column in row.index:
            label = clean_text(column)

            if label.casefold().startswith(
                prefix.casefold()
            ):
                return clean_text(row.get(column))

        return ""


    @classmethod
    def _index_value(
        cls,
        row: pd.Series,
        letter: str,
    ) -> Decimal | None:
        legacy_mapping = {
            "A": "X",
            "B": "Y",
            "C": "Z",
            "D": None,
        }

        source_letter = letter

        if cls._uses_legacy_index_schema(row):
            source_letter = legacy_mapping[letter]

        if source_letter is None:
            return None

        prefixes = (
            f"Waarde {source_letter} (€/MWh)",
            f"Waarde {source_letter}",
        )

        candidate_columns = []

        for column in row.index:
            label = clean_text(column)

            if any(
                label.casefold().startswith(
                    prefix.casefold()
                )
                for prefix in prefixes
            ):
                candidate_columns.append(label)

        # Geef voorrang aan de VNR/VREG-waarde, niet aan
        # de laatst gekende waarde.
        preferred_markers = (
            "vnr waarde",
            "vreg waarde",
        )

        for marker in preferred_markers:
            for column in candidate_columns:
                if marker in column.casefold():
                    value = dec(row.get(column))

                    if value is not None:
                        return value

        # Fallback als er slechts één geschikte waardekolom is.
        for column in candidate_columns:
            if "laatst gekende waarde" in column.casefold():
                continue

            value = dec(row.get(column))

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

    @staticmethod
    def _uses_legacy_index_schema(row: pd.Series) -> bool:
        """
        Bepaal of een bronrij het oude indexatieschema gebruikt.

        Geeft True terug voor:
            a.X + b.Y + c.Z + d

        Geeft False terug voor:
            a.A + b.B + c.C + d.D + z
        """
        columns = {
            clean_text(column).casefold()
            for column in row.index
        }

        has_legacy_columns = any(
            "indexatieparameter x" in column
            for column in columns
        )

        has_new_columns = any(
            "indexatieparameter a" in column
            for column in columns
        )

        if has_legacy_columns and has_new_columns:
            raise VTestNormalizationError(
                "Rij bevat zowel het oude als het nieuwe "
                "indexatieschema."
            )

        return has_legacy_columns
