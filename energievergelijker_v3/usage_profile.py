from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from .constants import LOCAL_TZ, UTC
from .normalizer import clean_text


class FluviusDataError(ValueError):
    """Het Fluviusbestand kan niet betrouwbaar worden verwerkt."""


@dataclass(frozen=True)
class UsageProfile:
    intervals: pd.DataFrame

    source: Path

    warnings: tuple[str, ...] = field(
        default_factory=tuple
    )

    @property
    def start(self) -> pd.Timestamp | None:
        if self.intervals.empty:
            return None

        return self.intervals["timestamp"].min()

    @property
    def end(self) -> pd.Timestamp | None:
        if self.intervals.empty:
            return None

        return self.intervals["timestamp"].max()

    @property
    def consumption_kwh(self) -> float:
        return float(
            self.intervals["afname_kwh"].sum()
        )

    @property
    def injection_kwh(self) -> float:
        return float(
            self.intervals["injectie_kwh"].sum()
        )

    @property
    def interval_count(self) -> int:
        return len(self.intervals)
