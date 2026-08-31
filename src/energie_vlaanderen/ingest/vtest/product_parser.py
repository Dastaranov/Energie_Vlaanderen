from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from bs4 import BeautifulSoup


def _clean(text: str | None) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip()


@dataclass
class RawVTestProduct:
    vreg_id: str
    leverancier: str
    product: str
    prijs_indicatie: str
    datum_intekenen: str
    datum_start_levering: str
    energietype: str
    looptijd: str
    tarief_type: str
    doelgroep: dict[str, str] = field(default_factory=lambda: {
        "zonnepanelen": "", "EV": "", "energiedelen": "", "leegstand": "", "groepsaankoop": "",
    })
    prijszekerheid: dict[str, str] = field(default_factory=lambda: {
        "onderdelen": "", "termijn": "", "formule": "", "indexatieparameter": "", "ToU": "",
    })
    links: dict[str, str] = field(default_factory=dict)
    # Rechtstreeks van het .resultitem-div (data-*-attributen) — robuuster
    # dan tekst uit kindelementen te vissen.
    price_raw: str = ""
    discount_raw: str = ""
    contracttype: str = ""
    supplier_id: str = ""
    product_id: str = ""
    green_type: str = ""
    tariff_type_attr: str = ""
    stars: str = ""
    complex_product: str = ""
    grayedout: bool = False
    # Volledige JSON-kostenopbouw uit data-productinvoicestring
    # (button.toContractDetails) — None als niet gevonden/onparseerbaar.
    invoice_raw: dict[str, Any] | None = None


class VTestProductParser:
    """Parseert een HTML-dump van vtest.be naar ruwe productgegevens.

    Port van Vl-Tarief-Sym/src/vl_tarief_sym/scrapers/vtest_parser.py.
    Neemt HTML als string (i.p.v. bestandspad) en retourneert dataclasses.
    """

    def parse(self, html: str) -> list[RawVTestProduct]:
        soup = BeautifulSoup(html, "lxml")
        contracts: dict[str, dict[str, Any]] = {}

        # Pass 1: Elementen met data-contractid
        for el in soup.select("[data-contractid]"):
            cid = el.get("data-contractid")
            if not isinstance(cid, str) or not cid:
                continue

            if cid not in contracts:
                contracts[cid] = self._empty(cid)
            c = contracts[cid]

            if not c["leverancier"]:
                img = el.select_one("img.supplier-logo, .supplier img, img[alt]")
                if img and img.get("alt"):
                    alt = img.get("alt")
                    if isinstance(alt, str):
                        c["leverancier"] = alt.replace("Logo", "").strip()

                if not c["leverancier"]:
                    s_el = el.select_one(".supplier-name, .supplier, #supplier-name")
                    if s_el:
                        c["leverancier"] = _clean(s_el.get_text())

                if not c["leverancier"]:
                    for tag in el.select("h5, h6"):
                        txt = _clean(tag.get_text())
                        if any(kw in txt.lower() for kw in ("prijs", "energietype", "mijn gegevens")):
                            continue
                        if txt:
                            c["leverancier"] = txt
                            break

            if not c["product"]:
                p_el = el.select_one("h3, h4, .product-name, .title")
                if p_el:
                    c["product"] = _clean(p_el.get_text())

            if not c["prijs_indicatie"]:
                pr_el = el.select_one(".resultitemprice-price, .price")
                if pr_el:
                    c["prijs_indicatie"] = _clean(pr_el.get_text())

            self._collect_links(el, c["links"])
            self._collect_result_attrs(el, c)
            self._collect_invoice_json(el, c)

        # Pass 2: contractdetail-{id} blokken
        for block in soup.select("[id^='contractdetail-']"):
            block_id = block.get("id")
            if not isinstance(block_id, str):
                continue
            bid = block_id.replace("contractdetail-", "")
            if bid not in contracts:
                contracts[bid] = self._empty(bid)
            c = contracts[bid]

            self._collect_links(block, c["links"])
            self._parse_dates(block, c)
            self._parse_properties(block, c)
            self._parse_doelgroep(block, c)
            self._parse_prijszekerheid(block, c)

        results = []
        for c in contracts.values():
            if not c["leverancier"] and not c["product"]:
                continue
            results.append(RawVTestProduct(
                vreg_id=c["id"],
                leverancier=c["leverancier"],
                product=c["product"],
                prijs_indicatie=c["prijs_indicatie"],
                datum_intekenen=c["datum_intekenen"],
                datum_start_levering=c["datum_start_levering"],
                energietype=c["energietype"],
                looptijd=c["looptijd"],
                tarief_type=c["tarief_type"],
                doelgroep=dict(c["doelgroep"]),
                prijszekerheid=dict(c["prijszekerheid"]),
                links=dict(c["links"]),
                price_raw=c["price_raw"],
                discount_raw=c["discount_raw"],
                contracttype=c["contracttype"],
                supplier_id=c["supplier_id"],
                product_id=c["product_id"],
                green_type=c["green_type"],
                tariff_type_attr=c["tariff_type_attr"],
                stars=c["stars"],
                complex_product=c["complex_product"],
                grayedout=c["grayedout"],
                invoice_raw=c["invoice_raw"],
            ))
        return results

    @staticmethod
    def _empty(cid: str) -> dict[str, Any]:
        return {
            "id": cid,
            "leverancier": "",
            "product": "",
            "prijs_indicatie": "",
            "datum_intekenen": "",
            "datum_start_levering": "",
            "energietype": "",
            "looptijd": "",
            "tarief_type": "",
            "doelgroep": {"zonnepanelen": "", "EV": "", "energiedelen": "", "leegstand": "", "groepsaankoop": ""},
            "prijszekerheid": {"onderdelen": "", "termijn": "", "formule": "", "indexatieparameter": "", "ToU": ""},
            "links": {},
            "price_raw": "",
            "discount_raw": "",
            "contracttype": "",
            "supplier_id": "",
            "product_id": "",
            "green_type": "",
            "tariff_type_attr": "",
            "stars": "",
            "complex_product": "",
            "grayedout": False,
            "invoice_raw": None,
        }

    @staticmethod
    def _collect_result_attrs(el: Any, c: dict[str, Any]) -> None:
        """Leest de data-*-attributen op het .resultitem-div zelf."""
        if "resultitem" not in (el.get("class") or []):
            return
        c["price_raw"] = c["price_raw"] or (el.get("data-price") or "")
        c["discount_raw"] = c["discount_raw"] or (el.get("data-discount") or "")
        c["contracttype"] = c["contracttype"] or (el.get("data-contracttype") or "")
        c["supplier_id"] = c["supplier_id"] or (el.get("data-supplier") or "")
        c["product_id"] = c["product_id"] or (el.get("data-productid") or "")
        c["green_type"] = c["green_type"] or (el.get("data-greentype") or "")
        c["tariff_type_attr"] = c["tariff_type_attr"] or (el.get("data-tarifftype") or "")
        c["stars"] = c["stars"] or (el.get("data-stars") or "")
        c["complex_product"] = c["complex_product"] or (el.get("data-complexproduct") or "")
        if "grayedout" in (el.get("class") or []):
            c["grayedout"] = True

    @staticmethod
    def _collect_invoice_json(el: Any, c: dict[str, Any]) -> None:
        """Leest de volledige JSON-kostenopbouw uit data-productinvoicestring
        (staat op de "Meer details"-knop, niet op het resultitem-div zelf)."""
        if c["invoice_raw"] is not None:
            return
        raw = el.get("data-productinvoicestring")
        if not raw:
            return
        try:
            c["invoice_raw"] = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            pass

    @staticmethod
    def _collect_links(el: Any, links: dict[str, str]) -> None:
        for a in el.find_all("a"):
            href = a.get("href")
            if not isinstance(href, str) or not href or href == "#" or "javascript" in href:
                continue
            txt = _clean(a.get_text()).lower()
            name = "link"
            if "tariefkaart" in txt:
                name = "tariefkaart"
            elif "voorwaarden" in txt:
                name = "voorwaarden"
            elif ".pdf" in href:
                name = "pdf"
            if "vtest.be" in href and "download" not in href and ".pdf" not in href:
                continue
            links[name] = href

    @staticmethod
    def _parse_dates(block: Any, c: dict[str, Any]) -> None:
        try:
            inteken_row = block.find(
                lambda tag: tag.name == "td" and "Intekenen kan in" in tag.get_text()
            )
            if inteken_row:
                val_cell = inteken_row.find_next_sibling("td")
                if val_cell:
                    c["datum_intekenen"] = _clean(val_cell.get_text())

            start_row = block.find(
                lambda tag: tag.name == "td" and "Levering kan starten" in tag.get_text()
            )
            if start_row:
                val_cell = start_row.find_next_sibling("td")
                if val_cell:
                    c["datum_start_levering"] = _clean(val_cell.get_text())
        except Exception:
            pass

    @staticmethod
    def _parse_properties(block: Any, c: dict[str, Any]) -> None:
        try:
            for dl in block.select("dl"):
                dt = dl.select_one("dt")
                dd = dl.select_one("dd")
                if not dt or not dd:
                    continue
                label = _clean(dt.get_text()).lower()
                value = _clean(dd.get_text())
                if "energietype" in label:
                    c["energietype"] = value
                elif "looptijd" in label:
                    c["looptijd"] = value
                elif "tarief" in label:
                    c["tarief_type"] = value
        except Exception:
            pass

    @staticmethod
    def _parse_doelgroep(block: Any, c: dict[str, Any]) -> None:
        try:
            for row in block.select("tr"):
                text = _clean(row.get_text()).lower()
                cols = row.select("td")
                if len(cols) < 2:
                    continue
                val = _clean(cols[1].get_text())
                if "zonnepanelen" in text and "enkel voor klanten" in text:
                    c["doelgroep"]["zonnepanelen"] = val
                elif "elektrisch voertuig" in text:
                    c["doelgroep"]["EV"] = val
                elif "energiedelen" in text:
                    c["doelgroep"]["energiedelen"] = val
                elif "leegstaande woning" in text:
                    c["doelgroep"]["leegstand"] = val
                elif "groepsaankoop" in text:
                    c["doelgroep"]["groepsaankoop"] = val
        except Exception:
            pass

    @staticmethod
    def _parse_prijszekerheid(block: Any, c: dict[str, Any]) -> None:
        try:
            for row in block.select("tr"):
                text = _clean(row.get_text()).lower()
                cols = row.select("td")
                if len(cols) < 2:
                    continue
                val = _clean(cols[1].get_text())
                if "onderdelen met prijszekerheid" in text:
                    c["prijszekerheid"]["onderdelen"] = val
                elif "termijn prijszekerheid" in text:
                    c["prijszekerheid"]["termijn"] = val
                elif "hoe berekent de leverancier" in text or "volgens deze formule" in val.lower():
                    c["prijszekerheid"]["formule"] = val.replace("Volgens deze formule (excl. btw):", "").strip()
                elif "indexatieparameter" in text:
                    c["prijszekerheid"]["indexatieparameter"] = val
                elif "prijs per tijdsblok" in text or "time-of-use" in text:
                    c["prijszekerheid"]["ToU"] = val
        except Exception:
            pass
