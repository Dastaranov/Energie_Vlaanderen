from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from energie_vlaanderen.utility.constants import LOCAL_TZ, UTC
from energie_vlaanderen.utility.normalizer import clean_text

class FluviusIntervals:
    @staticmethod
    def read(path: Path) -> pd.DataFrame:
        df=pd.read_csv(path,sep=";",dtype=str,encoding="utf-8-sig")
        cols={c.casefold():c for c in df.columns}
        def col(*parts):
            for c in df.columns:
                if all(p in c.casefold() for p in parts): return c
            return None
        date_c=col("van","datum"); time_c=col("van","tijd"); reg_c=col("register"); vol_c=col("volume")
        if not all([date_c,time_c,reg_c,vol_c]): raise ValueError("Fluvius CSV mist datum, tijd, register of volume")
        ts=pd.to_datetime(df[date_c].str.strip()+" "+df[time_c].str.strip(),dayfirst=True,errors="coerce")
        ts=ts.dt.tz_localize(LOCAL_TZ,ambiguous="infer",nonexistent="shift_forward").dt.tz_convert(UTC)
        vol=pd.to_numeric(df[vol_c].str.replace(",",".",regex=False),errors="coerce").fillna(0)
        reg=df[reg_c].str.casefold()
        out=pd.DataFrame({"timestamp":ts,"afname_kwh":0.0,"injectie_kwh":0.0})
        out.loc[reg.str.contains("afname",na=False),"afname_kwh"]=vol
        out.loc[reg.str.contains("injectie",na=False),"injectie_kwh"]=vol
        return out.dropna(subset=["timestamp"]).groupby("timestamp",as_index=False).sum().sort_values("timestamp")


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
