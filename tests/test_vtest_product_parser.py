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
