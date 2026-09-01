from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from energie_vlaanderen.ingest.vtest.product_parser import RawVTestProduct


_DATE_RANGE_RE = re.compile(
    r"(\d{1,2})/(\d{2})/(\d{4})\s+tot\s+en\s+met\s+(\d{1,2})/(\d{2})/(\d{4})",
    re.IGNORECASE,
)

_LOOPTIJD_RE = re.compile(r"(\d+)\s*(jaar|maand(?:en)?)", re.IGNORECASE)

_TARIEFTYPE_MAP = {"FIXED": "Vast", "VARIABLE": "Variabel", "DYNAMIC": "Dynamisch"}


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
    # Rechtstreeks van de data-*-attributen van het .resultitem-div.
    contracttype: str
    supplier_id: str
    product_id: str
    green_type: str
    stars: int | None
    complex_product: bool
    grayedout: bool
    discount_eur: Decimal | None
    # Uit de samenvatting (summary) van data-productinvoicestring —
    # het VREG-schattingsverbruik waarop deze bedragen zijn gebaseerd.
    total_excl_btw: Decimal | None
    total_incl_btw: Decimal | None
    btw_bedrag: Decimal | None
    totaal_verbruik_kwh: Decimal | None


@dataclass(frozen=True)
class NormalizedVTestComponent:
    """Eén rij per kostencomponent uit data-productinvoicestring
    (groupResults[].componentResults[]) — de volledige, per-contract
    kostenopbouw i.p.v. enkel de totaalprijs."""

    vreg_id: str
    groep_naam: str
    component_id: str
    component_naam: str
    calculation_type: str  # "Fixed" | "Variable"
    totaal_excl_btw: Decimal | None
    totaal_incl_btw: Decimal | None
    btw_bedrag: Decimal | None
    btw_percentage: Decimal | None
    formule: str


class VTestProductNormalizer:
    def normalize(
        self,
        products: list[RawVTestProduct],
        scraped_at: datetime,
    ) -> list[NormalizedVTestProduct]:
        return [self._normalize_one(p, scraped_at) for p in products]

    def normalize_components(
        self,
        products: list[RawVTestProduct],
    ) -> list[NormalizedVTestComponent]:
        """Ontleedt data-productinvoicestring per contract naar één rij per
        kostencomponent (groupResults[].componentResults[])."""
        rows: list[NormalizedVTestComponent] = []
        for product in products:
            if not product.invoice_raw:
                continue
            for groep in product.invoice_raw.get("groupResults") or []:
                groep_naam = groep.get("name", "")
                for comp in groep.get("componentResults") or []:
                    prijs = comp.get("price") or {}
                    vat_rates = prijs.get("vatRates") or {}
                    formule = _extract_formule(comp.get("flowResults") or {})
                    rows.append(NormalizedVTestComponent(
                        vreg_id=product.vreg_id,
                        groep_naam=groep_naam,
                        component_id=str(comp.get("id", "")),
                        component_naam=comp.get("name", ""),
                        calculation_type=comp.get("calculationType", ""),
                        totaal_excl_btw=_dec_or_none(prijs.get("totalExVAT")),
                        totaal_incl_btw=_dec_or_none(prijs.get("total")),
                        btw_bedrag=_dec_or_none(prijs.get("totalVAT")),
                        btw_percentage=_dec_or_none(next(iter(vat_rates), None)),
                        formule=formule,
                    ))
        return rows

    def _normalize_one(
        self,
        product: RawVTestProduct,
        scraped_at: datetime,
    ) -> NormalizedVTestProduct:
        d_inteken_van, d_inteken_tot = parse_date_range(product.datum_intekenen)
        d_start_van, d_start_tot = parse_date_range(product.datum_start_levering)

        # data-tarifftype (FIXED/VARIABLE/DYNAMIC) is een betrouwbare, vaste
        # enum-waarde — geef die voorrang boven de vrije tekst uit de
        # detailtabel wanneer aanwezig.
        tariff_type = _TARIEFTYPE_MAP.get(product.tariff_type_attr, product.tarief_type)

        summary = (product.invoice_raw or {}).get("summary") or {}
        summary_prijs = summary.get("price") or {}

        return NormalizedVTestProduct(
            vreg_id=product.vreg_id,
            supplier_raw=product.leverancier,
            product_raw=product.product,
            energy=normalize_energy(product.contracttype or product.energietype),
            tariff_type=tariff_type,
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
            prijs_indicatie_eur=parse_comma_price(product.price_raw) or parse_price(product.prijs_indicatie),
            link_tariefkaart=product.links.get("tariefkaart", ""),
            link_voorwaarden=product.links.get("voorwaarden", ""),
            # "leverancier" komt uit het detailpaneel, "link" uit de
            # resultatenpagina; die laatste is er in de praktijk nooit.
            link_supplier=product.links.get("leverancier")
            or product.links.get("link", ""),
            scraped_at=scraped_at,
            contracttype=product.contracttype,
            supplier_id=product.supplier_id,
            product_id=product.product_id,
            green_type=product.green_type,
            stars=int(product.stars) if product.stars.isdigit() else None,
            complex_product=product.complex_product == "True",
            grayedout=product.grayedout,
            discount_eur=parse_comma_price(product.discount_raw),
            total_excl_btw=_dec_or_none(summary_prijs.get("totalExVAT")),
            total_incl_btw=_dec_or_none(summary_prijs.get("total")),
            btw_bedrag=_dec_or_none(summary_prijs.get("totalVAT")),
            totaal_verbruik_kwh=_dec_or_none(summary.get("totalUsage")),
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
    """Mapt energietype-tekst (of de data-contracttype-enum ELECTRICITY/GAS)
    naar canonieke vorm."""
    folded = text.casefold()
    if "elect" in folded or "elektr" in folded:
        return "Elektriciteit"
    if "gas" in folded:
        return "Gas"
    return text


def parse_comma_price(text: str) -> Decimal | None:
    """Parse een data-price/data-discount-waarde zoals "1867,03" (komma als
    decimaalteken, geen duizendtalscheiding) naar Decimal."""
    if not text:
        return None
    try:
        return Decimal(text.replace(",", "."))
    except InvalidOperation:
        return None


def _dec_or_none(value: Any) -> Decimal | None:
    """Zet een JSON-getal (of numerieke string-sleutel) om naar Decimal via
    de tekstvorm — nooit rechtstreeks van float naar Decimal, om
    floatingpoint-ruis te vermijden."""
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None


def _extract_formule(flow_results: dict[str, Any]) -> str:
    """Haalt de indexatieformule (flowOutput.Formula) uit de flowResults van
    een component, indien aanwezig — enkel variabele/geïndexeerde
    componenten hebben dit veld."""
    for flow in flow_results.values():
        formula = (flow.get("flowOutput") or {}).get("Formula")
        if formula:
            return " ".join(str(f) for f in formula)
    return ""
