''' 
Project: Energievergelijker
Auteur: Gert Botte
Licentie: Apache License 2.0

Beschrijving:
    Test voor Bronnen en webscraping

Testen:
    - test_parse_links_finds_only_allowed_xlsx
        Controleert of de scraper uitsluitend links naar Excel-bestanden (.xlsx) verzamelt en alleen van goedgekeurde websites. 
        Links naar bijvoorbeeld PDF's of verkeerde domeinen worden genegeerd.
    - test_parse_links_removes_duplicates
        Verifieert dat dubbele links op een webpagina netjes worden weggefilterd zodat elke bron maar één keer voorkomt.
    - test_selects_vtest_source
        Test of het juiste V-test databestand wordt geselecteerd op basis van specifieke naamgevingspatronen,
        waarbij irrelevante bestanden zoals prijscurves worden genegeerd.
    - test_selects_tariff_sources
        Controleert of de bestanden voor distributienettarieven (zowel gas als elektriciteit) correct worden geïdentificeerd.
    - test_select_one_rejects_missing_source
        Zorgt ervoor dat het systeem een foutmelding geeft wanneer het vereiste bronbestand ontbreekt op de webpagina.
    - test_select_one_rejects_multiple_sources
        Garandeert dat het programma stopt met een fout als er meerdere bestanden voldoen aan de zoekcriteria, 
        om dubbelzinnigheid te voorkomen.
    - test_discover_returns_four_sources
        Controleert of de bronontdekking vier bronnen retourneert.

'''

from __future__ import annotations

from pathlib import Path

import pytest

from energievergelijker_v3 import Settings
from energievergelijker_v3.sources import (
    SourceDiscoveryError,
    VnrSourceScraper,
)

# HTML-tekens voor '<' en '>'
LT = chr(60)
GT = chr(62)

def html_anchor(
    url: str,
    text: str,
) -> str:
    return (
        f'{LT}a href="{url}"{GT}'
        f"{text}"
        f"{LT}/a{GT}"
    )

def html_document(
    *elements: str,
) -> str:
    body = "".join(elements)

    return (
        f"{LT}html{GT}"
        f"{LT}body{GT}"
        f"{body}"
        f"{LT}/body{GT}"
        f"{LT}/html{GT}"
    )

VTEST_HTML = html_document(
    html_anchor(
        (
            "https://assets.vlaamsenutsregulator.be/"
            "2026-08/"
            "202608-v-test-data-exclbtw%20v2_0.xlsx"
            "?VersionId=test-vtest"
        ),
        "V-test data",
    ),
    html_anchor(
        (
            "https://assets.vlaamsenutsregulator.be/"
            "2026-08/"
            "202608-Energieprijscurves%20v2.xlsx"
            "?VersionId=test-curves"
        ),
        "Energieprijscurves",
    ),
)

TARIFF_HTML = html_document(
    html_anchor(
        (
            "https://assets.vlaamsenutsregulator.be/"
            "2025-11/"
            "Distributienettarieven%20"
            "elektriciteit%202026.xlsx"
            "?VersionId=test-electricity"
        ),
        "Distributienettarieven elektriciteit 2026",
    ),
    html_anchor(
        (
            "https://assets.vlaamsenutsregulator.be/"
            "2025-11/"
            "Distributienettarieven%20"
            "aardgas%202026.xlsx"
            "?VersionId=test-gas"
        ),
        "Distributienettarieven aardgas 2026",
    ),
    html_anchor(
        (
            "https://assets.vlaamsenutsregulator.be/"
            "2025-12/"
            "Enexis%20-%202026%20-%20GAS.xlsx"
        ),
        "Enexis aardgas 2026",
    ),
)

@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        project_root=tmp_path,
        data_root=tmp_path / "data",
    )

class FakeResponse:
    def __init__(
        self,
        text: str,
        status_code: int = 200,
    ):
        '''
        Test of de neprespons correct wordt geïnitialiseerd.

        Args:
            text (str): De inhoud van de respons.
            status_code (int, optional): De HTTP-statuscode van de respons. Standaard is 200.
        '''
        self.text = text
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(
                f"HTTP {self.status_code}"
            )

class FakeSession:
    def __init__(
        self,
        pages: dict[str, str],
    ):
        '''
        Test of de nepsessie correct wordt geïnitialiseerd.

        Args:
            pages (dict[str, str]): Een mapping van URL's naar HTML-inhoud.
        '''
        self.pages = pages
        self.headers: dict[str, str] = {}

    def get(
        self,
        url: str,
        timeout: float,
    ) -> FakeResponse:
        del timeout
        return FakeResponse(
            self.pages[url]
        )

def test_parse_links_finds_only_allowed_xlsx(
    settings: Settings,
):
    '''
    Test of de scraper uitsluitend links naar toegestane Excel-bestanden vindt.

    Args: 
        settings (Settings): De configuratie-instellingen voor de scraper.
    '''
    scraper = VnrSourceScraper(settings)

    html = html_document(
        html_anchor(
            (
                "https://assets.vlaamsenutsregulator.be/"
                "data/test.xlsx"
            ),
            "Geldig",
        ),
        html_anchor(
            (
                "https://example.com/"
                "data/ongewenst.xlsx"
            ),
            "Verkeerde host",
        ),
        html_anchor(
            (
                "https://assets.vlaamsenutsregulator.be/"
                "data/test.pdf"
            ),
            "Geen Excel",
        ),
    )

    links = scraper.parse_links(
        html=html,
        page_url=settings.vtest_page_url,
    )

    assert len(links) == 1
    assert links[0].text == "Geldig"
    assert links[0].url.endswith("test.xlsx")

def test_parse_links_removes_duplicates(
    settings: Settings,
):
    '''
    Test of de scraper dubbele links correct verwijdert.

    Args:
        settings (Settings): De configuratie-instellingen voor de scraper.
    '''
    scraper = VnrSourceScraper(settings)

    url = (
        "https://assets.vlaamsenutsregulator.be/"
        "test.xlsx"
    )

    html = html_document(
        html_anchor(
            url,
            "Eerste",
        ),
        html_anchor(
            url,
            "Tweede",
        ),
    )

    links = scraper.parse_links(
        html=html,
        page_url=settings.vtest_page_url,
    )

    assert len(links) == 1
    assert links[0].url == url
    assert links[0].text == "Eerste"

def test_selects_vtest_source(
    settings: Settings,
):
    '''
    Test of de scraper het juiste V-test databestand selecteert.

    Args:
        settings (Settings): De configuratie-instellingen voor de scraper.
    '''
    scraper = VnrSourceScraper(settings)

    links = scraper.parse_links(
        html=VTEST_HTML,
        page_url=settings.vtest_page_url,
    )

    source = scraper._select_one(
        links=links,
        page_url=settings.vtest_page_url,
        kind="vtest",
        required_patterns=(
            r"v-test",
            r"data",
            r"\.xlsx(?:$|\?)",
        ),
        excluded_patterns=(
            r"energieprijscurves",
        ),
    )

    assert source.kind == "vtest"
    assert (
        source.filename
        == "202608-v-test-data-exclbtw v2_0.xlsx"
    )

def test_selects_tariff_sources(
    settings: Settings,
):
    '''
    Test of de scraper de juiste distributienettarieven voor elektriciteit en gas selecteert.

    Args:
        settings (Settings): De configuratie-instellingen voor de scraper.
    '''
    scraper = VnrSourceScraper(settings)

    links = scraper.parse_links(
        html=TARIFF_HTML,
        page_url=settings.tariff_page_url,
    )

    electricity = scraper._select_one(
        links=links,
        page_url=settings.tariff_page_url,
        kind="electricity_tariffs",
        required_patterns=(
            r"distributienettarieven",
            r"elektriciteit",
            r"\b2026\b",
            r"\.xlsx(?:$|\?)",
        ),
    )

    gas = scraper._select_one(
        links=links,
        page_url=settings.tariff_page_url,
        kind="gas_tariffs",
        required_patterns=(
            r"distributienettarieven",
            r"aardgas",
            r"\b2026\b",
            r"\.xlsx(?:$|\?)",
        ),
        excluded_patterns=(
            r"enexis",
        ),
    )

    assert (
        electricity.filename
        == "Distributienettarieven elektriciteit 2026.xlsx"
    )

    assert (
        gas.filename
        == "Distributienettarieven aardgas 2026.xlsx"
    )

def test_select_one_rejects_missing_source(
    settings: Settings,
):
    '''
    Test of de scraper een foutmelding geeft wanneer het vereiste bronbestand ontbreekt.

    Args:
        settings (Settings): De configuratie-instellingen voor de scraper.
    '''
    scraper = VnrSourceScraper(settings)

    with pytest.raises(
        SourceDiscoveryError,
        match="Geen geschikte bron",
    ):
        scraper._select_one(
            links=[],
            page_url=settings.vtest_page_url,
            kind="vtest",
            required_patterns=(r"v-test",),
        )

def test_select_one_rejects_multiple_sources(
    settings: Settings,
):
    '''
    Test of de scraper een foutmelding geeft wanneer er meerdere bestanden voldoen aan de zoekcriteria.

    Args:
        settings (Settings): De configuratie-instellingen voor de scraper.
    '''
    scraper = VnrSourceScraper(settings)

    html = html_document(
        html_anchor(
            (
                "https://assets.vlaamsenutsregulator.be/"
                "a/v-test-data.xlsx"
            ),
            "V-test data versie A",
        ),
        html_anchor(
            (
                "https://assets.vlaamsenutsregulator.be/"
                "b/v-test-data.xlsx"
            ),
            "V-test data versie B",
        ),
    )

    links = scraper.parse_links(
        html=html,
        page_url=settings.vtest_page_url,
    )

    assert len(links) == 2

    with pytest.raises(
        SourceDiscoveryError,
        match="niet eenduidig",
    ):
        scraper._select_one(
            links=links,
            page_url=settings.vtest_page_url,
            kind="vtest",
            required_patterns=(
                r"v-test",
                r"data",
            ),
        )

def test_discover_returns_four_sources(
    settings: Settings,
):
    '''
    Test of de bronontdekking vier bronnen retourneert.

    Args:
        settings (Settings): De configuratie-instellingen voor de scraper.
    '''
    session = FakeSession(
        {
            settings.vtest_page_url: VTEST_HTML,
            settings.tariff_page_url: TARIFF_HTML,
        }
    )

    scraper = VnrSourceScraper(
        settings,
        session=session,
    )

    sources = scraper.discover(2026)

    assert set(sources) == {
        "vtest",
        "energy_curves",
        "electricity_tariffs",
        "gas_tariffs",
    }

    assert sources["vtest"].filename.endswith(
        ".xlsx"
    )

    assert (
        "elektriciteit 2026"
        in sources[
            "electricity_tariffs"
        ].filename.casefold()
    )