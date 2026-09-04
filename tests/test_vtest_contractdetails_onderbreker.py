"""Bij een storing wordt het ophalen van contractdetails gestaakt.

De panelen komen noodgedwongen serieel binnen: vtest.be haalt ze per contract
op met een POST die de zoekopdracht in de sessie nodig heeft, dus de klik in de
lopende Selenium-sessie is de enige weg. Per contract wordt tot
`DETAIL_TIMEOUT_SECONDEN` gewacht.

Valt het endpoint structureel uit, dan werd dat volle budget voor élk contract
opgesoupeerd. Op de 350 contracten van een matrixrun is dat 350 x 30 s: bijna
drie uur wachten om vervolgens niets te hebben, en een matrixrun waarvan de
duur niet te voorspellen is.

Losse missers blijven gewoon een waarschuwing -- die komen voor, en één
onbereikbaar paneel mag de run niet kosten.
"""
from __future__ import annotations

import sys
import types

import pytest

pytestmark = pytest.mark.scrape


@pytest.fixture(autouse=True)
def _selenium_stub(monkeypatch):
    """Vervang selenium door een stuk of wat lege huls.

    `_verzamel_contractdetails` importeert `By` en `WebDriverWait` binnenin.
    CI installeert de scrape-extra niet -- de testworkflow draait op
    `[test,db]` -- dus zonder deze stub faalt dit bestand daar op een
    ModuleNotFoundError terwijl het lokaal groen is. Precies de divergentie
    die een test waardeloos maakt: hij bewaakt dan alleen de machine van
    degene die hem schreef.

    De stub is bovendien scherper dan het echte pakket: `WebDriverWait` roept
    de conditie hier onmiddellijk aan, zodat een test die per ongeluk op een
    echte timeout zou wachten, dat meteen laat zien in plaats van na 30 s.
    """
    class _By:
        CSS_SELECTOR = "css selector"
        ID = "id"

    class _WebDriverWait:
        def __init__(self, driver, timeout):
            self._driver = driver
            self.timeout = timeout

        def until(self, conditie):
            return conditie(self._driver)

    modules = {
        "selenium": types.ModuleType("selenium"),
        "selenium.webdriver": types.ModuleType("selenium.webdriver"),
        "selenium.webdriver.common": types.ModuleType("selenium.webdriver.common"),
        "selenium.webdriver.common.by": types.ModuleType("selenium.webdriver.common.by"),
        "selenium.webdriver.support": types.ModuleType("selenium.webdriver.support"),
        "selenium.webdriver.support.ui": types.ModuleType("selenium.webdriver.support.ui"),
    }
    modules["selenium.webdriver.common.by"].By = _By
    modules["selenium.webdriver.support.ui"].WebDriverWait = _WebDriverWait
    for naam, module in modules.items():
        monkeypatch.setitem(sys.modules, naam, module)
    yield


class _Knop:
    def __init__(self, contract_id: str) -> None:
        self._id = contract_id

    def get_attribute(self, naam: str) -> str:
        return self._id if naam == "data-contractid" else ""


class _Driver:
    """Een driver die elk detailpaneel laat mislukken, of juist niet."""

    def __init__(self, aantal: int, faal_vanaf: int = 0) -> None:
        self.knoppen = [_Knop(str(1000 + i)) for i in range(aantal)]
        self.faal_vanaf = faal_vanaf
        self.pogingen = 0

    def find_elements(self, by, selector):          # noqa: ARG002
        if "toContractDetails" in str(selector):
            return self.knoppen
        # de wachtlus vraagt hier naar het paneel van dit contract
        return [object()]

    def find_element(self, by, naam):               # noqa: ARG002
        return _Modal()

    def execute_script(self, script, *args):        # noqa: ARG002
        if "click" in script:
            self.pogingen += 1
            if self.pogingen > self.faal_vanaf:
                raise RuntimeError("endpoint geeft 500")


class _Modal:
    @staticmethod
    def get_attribute(naam):                        # noqa: ARG004
        return "<div>paneel</div>"


def _haal_op(driver, monkeypatch, max_fouten: int = 5):
    from energie_vlaanderen.ingest.vtest.html_downloader import VTestHtmlDownloader

    monkeypatch.setattr(
        VTestHtmlDownloader, "DETAIL_MAX_OPEENVOLGENDE_FOUTEN", max_fouten
    )
    monkeypatch.setattr(VTestHtmlDownloader, "_sluit_modal", staticmethod(lambda d: None))
    verzameling: dict[str, str] = {}
    VTestHtmlDownloader._verzamel_contractdetails(driver, verzameling, set())
    return verzameling


class TestStroomonderbreker:
    def test_een_structurele_storing_stopt_na_vijf_pogingen(self, monkeypatch, caplog):
        """350 contracten, alles kapot: er wordt 5 keer geprobeerd, niet 350."""
        driver = _Driver(aantal=350, faal_vanaf=0)
        with caplog.at_level("ERROR"):
            verzameling = _haal_op(driver, monkeypatch)

        assert driver.pogingen == 5, (
            f"er zijn {driver.pogingen} pogingen gedaan in plaats van 5; "
            "bij 30 s per poging is dat het verschil tussen 2,5 minuut en 3 uur"
        )
        assert verzameling == {}
        assert "gestopt na" in caplog.text

    def test_losse_missers_stoppen_de_run_niet(self, monkeypatch):
        """De eerste tien lukken, daarna vier missers: dat is geen storing."""
        driver = _Driver(aantal=14, faal_vanaf=10)
        verzameling = _haal_op(driver, monkeypatch)

        assert driver.pogingen == 14, "de run is te vroeg gestaakt"
        assert len(verzameling) == 10

    def test_zonder_fouten_wordt_alles_opgehaald(self, monkeypatch):
        driver = _Driver(aantal=20, faal_vanaf=10_000)
        verzameling = _haal_op(driver, monkeypatch)
        assert len(verzameling) == 20

    def test_de_teller_gaat_terug_op_nul_na_een_geslaagd_paneel(self, monkeypatch):
        """Anders zou een run met verspreide missers alsnog afgebroken worden."""
        from energie_vlaanderen.ingest.vtest.html_downloader import VTestHtmlDownloader

        class _AfwisselendeDriver(_Driver):
            def execute_script(self, script, *args):   # noqa: ARG002
                if "click" in script:
                    self.pogingen += 1
                    if self.pogingen % 2 == 0:         # om de andere mislukt
                        raise RuntimeError("hik")

        driver = _AfwisselendeDriver(aantal=30)
        monkeypatch.setattr(VTestHtmlDownloader, "DETAIL_MAX_OPEENVOLGENDE_FOUTEN", 5)
        monkeypatch.setattr(
            VTestHtmlDownloader, "_sluit_modal", staticmethod(lambda d: None)
        )
        verzameling: dict[str, str] = {}
        VTestHtmlDownloader._verzamel_contractdetails(driver, verzameling, set())

        assert driver.pogingen == 30, "afgebroken terwijl het om losse missers ging"
        assert len(verzameling) == 15
