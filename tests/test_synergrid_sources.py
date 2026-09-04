"""Tests voor de linkselectie van SynergridSourceScraper.

Geen netwerkaanroepen: `parse_links` + `_select_one` worden rechtstreeks op
een stuk HTML aangeroepen, naar het patroon van de bestaande VREG-scraper-
tests. De regexpatronen zelf zijn bovendien manueel geverifieerd tegen de
echte Synergrid-pagina voor de jaren 2025 en 2026 (zie de commit die deze
module invoert) — dat dekt het geval waarbij 2026-bestanden onder een
`/SLP-RLP-SPP/2026/`-submap staan en 2025-bestanden grotendeels niet.
"""

from __future__ import annotations

import pytest

from energie_vlaanderen.ingest.sources import SourceDiscoveryError
from energie_vlaanderen.ingest.synergrid_sources import SynergridSourceScraper
from energie_vlaanderen.settings import Settings


pytestmark = pytest.mark.bronnen


def _settings(tmp_path) -> Settings:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    return Settings.load(project_root=tmp_path, environ={})


_HTML_2026 = """
<html><body>
<a href="/images/downloads/SLP-RLP-SPP/2026/SLP_EX_2026.xlsb">SLP EX 2026</a>
<a href="/images/downloads/SLP-RLP-SPP/2026/SLP_EX_parameters_2026.xlsb">SLP EX parameters 2026</a>
<a href="/images/downloads/SLP-RLP-SPP/2026/RLP0N%202026%20Electricity%20all%20DSOs.xlsb">RLP0N 2026 Electricity all DSOs</a>
<a href="/images/downloads/SLP-RLP-SPP/2026/RLP0N%202026%20Electricity.xlsb">RLP0N 2026 Electricity</a>
<a href="/images/downloads/SLP-RLP-SPP/2026/RLP0N%202026%20Gas%20GOS.xlsb">RLP0N 2026 Gas GOS</a>
<a href="/images/downloads/SLP-RLP-SPP/2026/RLP0N%202026%20Gas.xlsb">RLP0N 2026 Gas</a>
<a href="/images/downloads/SLP-RLP-SPP/2026/SPP_ex-ante_and_ex-post_2026.xlsx">SPP 2026 ex-ante and ex-post</a>
<a href="/images/downloads/SLP-RLP-SPP/2026/SPP%20Handbook%202026.pdf">Handbook SPP 2026</a>
</body></html>
"""

# Ouder jaar: geen submap, en de bestandsnaam draagt geen underscore vóór
# het jaartal (zoals het echte 2025-bestand op synergrid.be).
_HTML_2025 = """
<html><body>
<a href="/images/downloads/SLP_EX_2025.xlsb">SLP EX 2025</a>
<a href="/images/downloads/RLP0N%202025%20Electricity%20all%20DSOs.xlsb">RLP0N 2025 Electricity all DSOs</a>
<a href="/images/downloads/RLP0N%202025%20Gas%20GOS.xlsb">RLP0N 2025 Gas GOS</a>
<a href="/images/downloads/SLP-RLP-SPP/2025/spp-2025-ex-ante-and-ex-post_v3.0.xlsx">SPP 2025 ex ante and ex post</a>
</body></html>
"""


class TestLinkSelectie:
    def test_2026_kiest_de_juiste_vier_bestanden(self, tmp_path):
        scraper = SynergridSourceScraper(_settings(tmp_path))
        page_url = "https://www.synergrid.be/nl/documentencentrum/statistieken-gegevens/profielen-slp-spp-rlp"
        links = scraper.parse_links(html=_HTML_2026, page_url=page_url)

        gevonden = {}
        for kind, required, excluded in [
            ("slp_ex", (r"slp[\s_-]*ex", r"\b2026\b"), (r"parameter",)),
            ("rlp0n_elektriciteit", (r"rlp0n", r"electricity", r"all[\s-]*dsos", r"\b2026\b"), (r"parameter",)),
            ("rlp0n_gas", (r"rlp0n", r"gas", r"gos", r"\b2026\b"), (r"parameter",)),
            ("spp", (r"spp", r"ex[\s_-]*ante", r"\b2026\b"), ()),
        ]:
            gevonden[kind] = scraper._select_one(
                links=links, page_url=page_url, kind=kind,
                required_patterns=required, excluded_patterns=excluded,
            )

        assert gevonden["slp_ex"].filename == "SLP_EX_2026.xlsb"
        assert gevonden["rlp0n_elektriciteit"].filename == "RLP0N 2026 Electricity all DSOs.xlsb"
        assert gevonden["rlp0n_gas"].filename == "RLP0N 2026 Gas GOS.xlsb"
        assert gevonden["spp"].filename == "SPP_ex-ante_and_ex-post_2026.xlsx"

    def test_discover_werkt_voor_2025_ondanks_afwijkende_padstructuur(self, tmp_path, monkeypatch):
        settings = _settings(tmp_path)
        scraper = SynergridSourceScraper(settings)

        def fake_links_from_page(self, page_url):
            return scraper.parse_links(html=_HTML_2025, page_url=page_url)

        monkeypatch.setattr(SynergridSourceScraper, "links_from_page", fake_links_from_page)

        result = scraper.discover(2025)
        assert result["slp_ex"].filename == "SLP_EX_2025.xlsb"
        assert result["spp"].filename == "spp-2025-ex-ante-and-ex-post_v3.0.xlsx"

    def test_parameterbestand_wordt_niet_als_slp_ex_gekozen(self, tmp_path):
        scraper = SynergridSourceScraper(_settings(tmp_path))
        page_url = "https://www.synergrid.be/nl/documentencentrum/statistieken-gegevens/profielen-slp-spp-rlp"
        links = scraper.parse_links(html=_HTML_2026, page_url=page_url)

        result = scraper._select_one(
            links=links, page_url=page_url, kind="slp_ex",
            required_patterns=(r"slp[\s_-]*ex", r"\b2026\b"),
            excluded_patterns=(r"parameter",),
        )
        assert result.filename == "SLP_EX_2026.xlsb"

    def test_xlsb_en_xlsx_worden_beide_toegelaten_pdf_niet(self, tmp_path):
        scraper = SynergridSourceScraper(_settings(tmp_path))
        links = scraper.parse_links(
            html=_HTML_2026,
            page_url="https://www.synergrid.be/nl/documentencentrum/statistieken-gegevens/profielen-slp-spp-rlp",
        )
        extensies = {link.url.rsplit(".", 1)[-1].casefold() for link in links}
        assert extensies == {"xlsb", "xlsx"}
