from __future__ import annotations
import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Optional
import pandas as pd
from ....experiments.constants import CENT, D

NULL_TOKENS = {"", "nan", "none", "null", "(empty)", "n/a", "na"}
MOJIBAKE = {"�": "€", "â‚¬": "€", "\u00a0": " ", "\ufeff": ""}

def clean_text(value: Any) -> str:
    if value is None or (not isinstance(value, str) and pd.isna(value)):
        return ""
    text = str(value)
    for bad, good in MOJIBAKE.items():
        text = text.replace(bad, good)
    return re.sub(r"\s+", " ", text).strip()

def nullify(value: Any) -> Optional[str]:
    text = clean_text(value)
    return None if text.casefold() in NULL_TOKENS else text

def dec(value: Any, default: Optional[Decimal] = None) -> Optional[Decimal]:
    text = nullify(value)
    if text is None:
        return default
    s = text.replace("€", "").replace(" ", "")
    if "," in s and "." in s:
        # Belgische notatie: punt als duizendtalseparator, komma als decimaalteken.
        s = s.replace(".", "").replace(",", ".")
    else:
        s = s.replace(",", ".")
    s = re.sub(r"[^0-9eE+.-]", "", s)
    try:
        return D(s)
    except InvalidOperation:
        return default

def money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)

def norm(value: Any) -> str:
    return clean_text(value)
