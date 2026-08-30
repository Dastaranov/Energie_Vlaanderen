from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from energie_vlaanderen.ingest.vtest.product_parser import RawVTestProduct


_DATE_RANGE_RE = re.compile(
    r"(\d{1,2})/(\d{2})/(\d{4})\s+tot\s+en\s+met\s+(\d{1,2})/(\d{2})/(\d{4})",
    re.IGNORECASE,
)

_LOOPTIJD_RE = re.compile(r"(\d+)\s*(jaar|maand(?:en)?)", re.IGNORECASE)


@dataclass(frozen=True)
class NormalizedVTestProduct:
    vreg_id: str
    supplier_raw: str
    product_raw: str
    energy: str
    tariff_type: str
    looptijd_tekst: str
    looptijd_maanden: int | None
    datum_intekenen_van: date | None
    datum_intekenen_tot: date | None
    datum_start_levering_van: date | None
    datum_start_levering_tot: date | None
    doelgroep_zonnepanelen: str
    doelgroep_ev: str
    doelgroep_energiedelen: str
    doelgroep_leegstand: str
    doelgroep_groepsaankoop: str
    prijszekerheid_termijn: str
    prijs_indicatie_eur: Decimal | None
    link_tariefkaart: str
    link_voorwaarden: str
    link_supplier: str
    scraped_at: datetime


class VTestProductNormalizer:
    def normalize(
        self,
        products: list[RawVTestProduct],
        scraped_at: datetime,
    ) -> list[NormalizedVTestProduct]:
        return [self._normalize_one(p, scraped_at) for p in products]

    def _normalize_one(
        self,
        product: RawVTestProduct,
        scraped_at: datetime,
    ) -> NormalizedVTestProduct:
        d_inteken_van, d_inteken_tot = parse_date_range(product.datum_intekenen)
        d_start_van, d_start_tot = parse_date_range(product.datum_start_levering)

        return NormalizedVTestProduct(
            vreg_id=product.vreg_id,
            supplier_raw=product.leverancier,
            product_raw=product.product,
            energy=normalize_energy(product.energietype),
            tariff_type=product.tarief_type,
            looptijd_tekst=product.looptijd,
            looptijd_maanden=parse_looptijd(product.looptijd),
            datum_intekenen_van=d_inteken_van,
            datum_intekenen_tot=d_inteken_tot,
            datum_start_levering_van=d_start_van,
            datum_start_levering_tot=d_start_tot,
            doelgroep_zonnepanelen=product.doelgroep.get("zonnepanelen", ""),
            doelgroep_ev=product.doelgroep.get("EV", ""),
            doelgroep_energiedelen=product.doelgroep.get("energiedelen", ""),
            doelgroep_leegstand=product.doelgroep.get("leegstand", ""),
            doelgroep_groepsaankoop=product.doelgroep.get("groepsaankoop", ""),
            prijszekerheid_termijn=product.prijszekerheid.get("termijn", ""),
            prijs_indicatie_eur=parse_price(product.prijs_indicatie),
            link_tariefkaart=product.links.get("tariefkaart", ""),
            link_voorwaarden=product.links.get("voorwaarden", ""),
            link_supplier=product.links.get("link", ""),
            scraped_at=scraped_at,
        )


def parse_date_range(text: str) -> tuple[date | None, date | None]:
    """Parse "D/MM/YYYY tot en met D/MM/YYYY" naar (start, eind)."""
    if not text:
        return None, None
    m = _DATE_RANGE_RE.search(text)
    if not m:
        return None, None
    d1, m1, y1, d2, m2, y2 = m.groups()
    try:
        return date(int(y1), int(m1), int(d1)), date(int(y2), int(m2), int(d2))
    except ValueError:
        return None, None


def parse_looptijd(text: str) -> int | None:
    """Parse "N jaar" of "N maand(en)" naar aantal maanden."""
    if not text:
        return None
    m = _LOOPTIJD_RE.search(text)
    if not m:
        return None
    n = int(m.group(1))
    unit = m.group(2).lower()
    return n * 12 if "jaar" in unit else n


def parse_price(text: str) -> Decimal | None:
    """Parse "€ 1.276,46" of "€954,87" naar Decimal."""
    if not text:
        return None
    # Verwijder euroteken, punt (duizendtaldelen) en spaties; vervang komma door punt
    cleaned = text.replace("€", "").replace(".", "").strip().replace(",", ".")
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def normalize_energy(text: str) -> str:
    """Mapt energietype-tekst naar canonieke vorm."""
    folded = text.casefold()
    if "elektr" in folded:
        return "Elektriciteit"
    if "gas" in folded:
        return "Gas"
    return text
