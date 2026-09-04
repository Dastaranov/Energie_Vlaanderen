from __future__ import annotations
import csv
import io
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Sequence
import pandas as pd
from energie_vlaanderen.utility.normalizer import clean_text, nullify

LOG = logging.getLogger(__name__)

class ParseError(ValueError):
    pass

@dataclass(frozen=True)
class CsvSchema:
    required: tuple[str, ...]
    aliases: dict[str, tuple[str, ...]] = field(default_factory=dict)

PRODUCT_SCHEMA = CsvSchema(
    required=("Jaar", "Maand", "Segment", "Energietype", "Contracttype", "Handelsnaam", "Productnaam", "Prijsonderdeel"),
    aliases={
        "Variabel/Dynamisch": ("Vast/variabel/dynamisch",),
        "Prijs": ("Prijs (c€/kWh)", "Prijs (c�/kWh)"),
    },
)

class RobustCsvParser:
    """CSV-inleeslaag met encoding/delimiter-detectie, multiline quotes en schema-validatie."""
    ENCODINGS = ("utf-8-sig", "utf-8", "cp1252", "latin-1")

    def __init__(self, *, schema: CsvSchema | None = None, strict: bool = True):
        self.schema = schema
        self.strict = strict
        self.warnings: list[str] = []

    def read(self, path: Path) -> pd.DataFrame:
        raw = path.read_bytes()
        text, encoding = self._decode(raw, path)
        delimiter = self._delimiter(text)
        try:
            df = pd.read_csv(
                io.StringIO(text), sep=delimiter, dtype=str, engine="python",
                quotechar='"', keep_default_na=False, na_filter=False,
                on_bad_lines="error" if self.strict else "warn",
            )
        except Exception as exc:
            raise ParseError(f"Kan {path.name} niet parsen: {exc}") from exc
        df.columns = self._unique_headers([clean_text(c) for c in df.columns])
        df = self._repair_headers(df)
        for col in df.columns:
            df[col] = df[col].map(nullify)
        self._validate(df, path)
        df.attrs.update(source=str(path), encoding=encoding, delimiter=delimiter, warnings=tuple(self.warnings))
        return df

    def read_chunks(self, path: Path, chunksize: int = 50_000) -> Iterable[pd.DataFrame]:
        # Eén robuuste decode vooraf, daarna echte chunkverwerking door pandas.
        raw = path.read_bytes()
        text, encoding = self._decode(raw, path)
        delimiter = self._delimiter(text)
        reader = pd.read_csv(io.StringIO(text), sep=delimiter, dtype=str, engine="python",
                             quotechar='"', keep_default_na=False, na_filter=False, chunksize=chunksize,
                             on_bad_lines="error" if self.strict else "warn")
        for df in reader:
            df.columns = self._unique_headers([clean_text(c) for c in df.columns])
            df = self._repair_headers(df)
            for col in df.columns: df[col] = df[col].map(nullify)
            self._validate(df, path)
            df.attrs.update(source=str(path), encoding=encoding, delimiter=delimiter, warnings=tuple(self.warnings))
            yield df

    def _decode(self, raw: bytes, path: Path) -> tuple[str, str]:
        for encoding in self.ENCODINGS:
            try:
                text = raw.decode(encoding)
                if encoding not in {"utf-8-sig", "utf-8"}:
                    self.warnings.append(f"{path.name}: fallback-encoding {encoding}")
                return text, encoding
            except UnicodeDecodeError:
                continue
        raise ParseError(f"Geen ondersteunde encoding voor {path.name}")

    @staticmethod
    def _delimiter(text: str) -> str:
        sample = text[:65536]
        try:
            return csv.Sniffer().sniff(sample, delimiters=";,\t,").delimiter
        except csv.Error:
            return ";"

    @staticmethod
    def _unique_headers(headers: Sequence[str]) -> list[str]:
        seen: dict[str, int] = {}
        out = []
        for header in headers:
            base = header or "Unnamed"
            key = base.casefold()
            seen[key] = seen.get(key, 0) + 1
            out.append(base if seen[key] == 1 else f"{base}__{seen[key]}")
        return out

    def _repair_headers(self, df: pd.DataFrame) -> pd.DataFrame:
        if not self.schema:
            return df
        folded = {clean_text(c).casefold(): c for c in df.columns}
        for canonical, aliases in self.schema.aliases.items():
            if canonical in df.columns:
                continue
            for alias in aliases:
                match = folded.get(clean_text(alias).casefold())
                if match:
                    df = df.rename(columns={match: canonical})
                    break
        return df

    def _validate(self, df: pd.DataFrame, path: Path) -> None:
        if not self.schema:
            return
        missing = [c for c in self.schema.required if c not in df.columns]
        if missing:
            raise ParseError(f"{path.name}: verplichte kolommen ontbreken: {', '.join(missing)}")
        empty = [c for c in self.schema.required if df[c].isna().all()]
        if empty:
            msg = f"{path.name}: verplichte kolommen volledig leeg: {', '.join(empty)}"
            if self.strict: raise ParseError(msg)
            self.warnings.append(msg)
