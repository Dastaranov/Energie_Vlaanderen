from __future__ import annotations

import pytest

from energie_vlaanderen.ingest.vtest.product_parser import VTestProductParser


_HTML_SINGLE_CONTRACT = """\
<html><body>
<div data-contractid="VREG-001">
  <img class="supplier-logo" alt="TotalEnergies Logo" src="logo.png">
  <h3>MyPlan Vast</h3>
  <span class="resultitemprice-price">€ 954,87</span>
  <a href="https://example.com/tariefkaart.pdf">Tariefkaart</a>
  <a href="https://example.com/voorwaarden.pdf">Algemene voorwaarden</a>
  <a href="https://example.com">Website leverancier</a>
</div>
<div id="contractdetail-VREG-001">
  <table>
    <tr><td>Intekenen kan in</td><td>1/02/2026 tot en met 28/02/2026</td></tr>
    <tr><td>Levering kan starten</td><td>1/03/2026 tot en met 31/03/2026</td></tr>
  </table>
  <dl><dt>Energietype</dt><dd>Elektriciteit</dd></dl>
  <dl><dt>Looptijd</dt><dd>1 jaar</dd></dl>
  <dl><dt>Tariefsoort</dt><dd>Vast tarief</dd></dl>
  <table>
    <tr><td>Enkel voor klanten met zonnepanelen</td><td>Nee</td></tr>
    <tr><td>Enkel voor klanten met elektrisch voertuig</td><td>Nee</td></tr>
  </table>
</div>
</body></html>
"""

_HTML_TWO_CONTRACTS = """\
<html><body>
<div data-contractid="VREG-A">
  <img class="supplier-logo" alt="Eneco Logo" src="eneco.png">
  <h3>Eneco Flex</h3>
</div>
<div data-contractid="VREG-B">
  <img class="supplier-logo" alt="Luminus Logo" src="luminus.png">
  <h3>Luminus Fixed</h3>
</div>
</body></html>
"""


_HTML_RESULTITEM = """\
<html><body>
<div id="resultitem-123" class="resultitem w-100 bg-white mb-2 ct-ELECTRICITY"
     data-price="944,07" data-discount="944,07" data-contractid="123"
     data-contracttype="ELECTRICITY" data-supplier="90" data-productid="123"
     data-greentype="GREENLOCAL" data-tarifftype="VARIABLE" data-stars="5"
     data-complexproduct="False">
  <img class="supplier-logo" alt="EnergyVision Logo" src="ev.png">
  <h3>Goedkope stroom 1.800 kWh vast</h3>
  <button class="btn-link toContractDetails" data-contractid="123"
    data-productinvoicestring='{"summary": {"totalUsage": 3434.0, "price": {"totalExVAT": 890.63, "total": 944.07, "totalVAT": 53.44}}, "groupResults": [{"name": "Energiekost", "componentResults": [{"id": "1", "name": "Vaste vergoeding", "calculationType": "Fixed", "price": {"totalExVAT": 47.17, "total": 50.0, "totalVAT": 2.83, "vatRates": {"0.06": 2.83}}, "flowResults": {}}]}]}'>
  </button>
</div>
<div id="resultitem-999" class="resultitem w-100 bg-white mb-2 ct-ELECTRICITY grayedout"
     style="display:none;" data-price="859,63" data-contractid="999"
     data-contracttype="ELECTRICITY" data-supplier="12" data-productid="999"
     data-greentype="NONE" data-tarifftype="FIXED" data-stars="" data-complexproduct="False">
  <h5>Sociaal tarief</h5>
</div>
</body></html>
"""


class TestVTestProductParser:
    def test_parser_extracts_vreg_id(self):
        products = VTestProductParser().parse(_HTML_SINGLE_CONTRACT)
        assert len(products) == 1
        assert products[0].vreg_id == "VREG-001"

    def test_parser_extracts_leverancier_from_img_alt(self):
        products = VTestProductParser().parse(_HTML_SINGLE_CONTRACT)
        assert products[0].leverancier == "TotalEnergies"

    def test_parser_extracts_product_name(self):
        products = VTestProductParser().parse(_HTML_SINGLE_CONTRACT)
        assert products[0].product == "MyPlan Vast"

    def test_parser_extracts_datum_intekenen(self):
        products = VTestProductParser().parse(_HTML_SINGLE_CONTRACT)
        assert "1/02/2026" in products[0].datum_intekenen
        assert "28/02/2026" in products[0].datum_intekenen

    def test_parser_extracts_datum_start_levering(self):
        products = VTestProductParser().parse(_HTML_SINGLE_CONTRACT)
        assert "1/03/2026" in products[0].datum_start_levering

    def test_parser_extracts_energietype(self):
        products = VTestProductParser().parse(_HTML_SINGLE_CONTRACT)
        assert products[0].energietype == "Elektriciteit"

    def test_parser_extracts_looptijd(self):
        products = VTestProductParser().parse(_HTML_SINGLE_CONTRACT)
        assert products[0].looptijd == "1 jaar"

    def test_parser_extracts_links(self):
        products = VTestProductParser().parse(_HTML_SINGLE_CONTRACT)
        links = products[0].links
        assert "tariefkaart.pdf" in links.get("tariefkaart", "")
        assert "voorwaarden.pdf" in links.get("voorwaarden", "")

    def test_parser_handles_empty_html(self):
        products = VTestProductParser().parse("")
        assert products == []

    def test_parser_handles_html_without_contracts(self):
        products = VTestProductParser().parse("<html><body><p>Geen resultaten</p></body></html>")
        assert products == []

    def test_parser_extracts_multiple_contracts(self):
        products = VTestProductParser().parse(_HTML_TWO_CONTRACTS)
        ids = {p.vreg_id for p in products}
        assert ids == {"VREG-A", "VREG-B"}

    def test_parser_extracts_prijs_indicatie(self):
        products = VTestProductParser().parse(_HTML_SINGLE_CONTRACT)
        assert "954,87" in products[0].prijs_indicatie

    def test_parser_extracts_doelgroep(self):
        products = VTestProductParser().parse(_HTML_SINGLE_CONTRACT)
        assert products[0].doelgroep.get("zonnepanelen") == "Nee"
        assert products[0].doelgroep.get("EV") == "Nee"


class TestVTestProductParserResultAttrs:
    """Data-*-attributen rechtstreeks van het .resultitem-div (rijker en
    robuuster dan tekst uit kindelementen)."""

    def test_extracts_result_attrs(self):
        products = {p.vreg_id: p for p in VTestProductParser().parse(_HTML_RESULTITEM)}
        p = products["123"]
        assert p.price_raw == "944,07"
        assert p.contracttype == "ELECTRICITY"
        assert p.supplier_id == "90"
        assert p.product_id == "123"
        assert p.green_type == "GREENLOCAL"
        assert p.tariff_type_attr == "VARIABLE"
        assert p.stars == "5"
        assert p.complex_product == "False"
        assert p.grayedout is False

    def test_grayedout_flag_set(self):
        products = {p.vreg_id: p for p in VTestProductParser().parse(_HTML_RESULTITEM)}
        assert products["999"].grayedout is True

    def test_invoice_raw_parsed_from_productinvoicestring(self):
        products = {p.vreg_id: p for p in VTestProductParser().parse(_HTML_RESULTITEM)}
        invoice = products["123"].invoice_raw
        assert invoice is not None
        assert invoice["summary"]["totalUsage"] == 3434.0
        assert invoice["groupResults"][0]["name"] == "Energiekost"

    def test_invoice_raw_none_when_absent(self):
        products = {p.vreg_id: p for p in VTestProductParser().parse(_HTML_RESULTITEM)}
        assert products["999"].invoice_raw is None
