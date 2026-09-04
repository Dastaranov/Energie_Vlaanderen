"""Het detailpaneel van vtest.be, tegen echte markup.

De resultatenpagina van vtest.be draagt de contractmetadata niet: intekenperiode,
start levering, looptijd, doelgroep, prijszekerheid en de links naar de
tariefkaart en de algemene voorwaarden staan in een paneel dat de site pas
ophaalt bij een klik op "Meer details". Zolang dat paneel de parser niet
bereikte, bleven vijftien kolommen van `vtest_contract` leeg zonder dat er iets
faalde — de stille-nul-fout waar `CLAUDE.md` voor waarschuwt.

De fixture `fixturen/vtest/contractdetail_14972.html` is een echt paneel,
opgehaald op 2026-09-03 (contract 14972, Bolt "Plenty Variabel Online",
woning/elektriciteit/9120). De deelbomen zijn verbatim; alleen de prijstabellen
zijn weggelaten omdat de parser die niet leest.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from energie_vlaanderen.ingest.vtest.product_normalizer import VTestProductNormalizer
from energie_vlaanderen.ingest.vtest.product_parser import VTestProductParser

FIXTUUR = Path(__file__).parent / "fixturen" / "vtest" / "contractdetail_14972.html"

# Zoals het contract op de resultatenpagina staat: alleen naam, leverancier en
# de data-attributen. Geen enkele van de vijftien detailvelden.
_RESULTITEM = (
    '<html><body>'
    '<div class="resultitem" data-contractid="14972" data-tarifftype="DYNAMIC"'
    ' data-contracttype="ELECTRICITY">'
    '<h3>Plenty Variabel Online</h3><h5>Bolt</h5>'
    '<a href="javascript:void(0)">Meer details</a>'
    '</div></body></html>'
)


pytestmark = pytest.mark.scrape


@pytest.fixture
def fragment() -> str:
    return FIXTUUR.read_text(encoding="utf-8")


@pytest.fixture
def product(fragment: str):
    (p,) = VTestProductParser().parse(_RESULTITEM, detail_fragments={"14972": fragment})
    return p


class TestZonderDetailpaneel:
    def test_de_resultatenpagina_alleen_levert_geen_metadata(self):
        """Legt vast waarom het paneel nodig is: zonder fragment blijft alles leeg."""
        (p,) = VTestProductParser().parse(_RESULTITEM)
        assert p.vreg_id == "14972"
        assert p.datum_intekenen == ""
        assert p.datum_start_levering == ""
        assert p.looptijd == ""
        assert p.links == {}


class TestMetDetailpaneel:
    def test_intekenperiode_en_start_levering(self, product):
        # Uit section-duration-content-14972 van het opgehaalde paneel:
        # "Intekenen kan in volgende periode 1/09/2026 tot en met 30/09/2026",
        # "Levering kan starten in volgende periode 2/09/2026 tot en met 31/01/2027".
        assert product.datum_intekenen == "1/09/2026 tot en met 30/09/2026"
        assert product.datum_start_levering == "2/09/2026 tot en met 31/01/2027"

    def test_looptijd_en_tariefsoort(self, product):
        assert product.looptijd == "Onbepaald"
        assert product.energietype == "Elektriciteit"
        assert product.tarief_type == "Dynamisch tarief"

    def test_doelgroep(self, product):
        assert product.doelgroep["zonnepanelen"] == "Nee"
        assert product.doelgroep["EV"] == "Nee"
        assert product.doelgroep["groepsaankoop"] == "Nee"
        assert product.doelgroep["energiedelen"].startswith("Ja")

    def test_prijszekerheid(self, product):
        assert product.prijszekerheid["termijn"] == "Geen prijszekerheid"
        assert product.prijszekerheid["indexatieparameter"] == (
            "EPEX SPOT Belgium/Belpex (kwartier)"
        )

    def test_tariefkaart_en_voorwaarden(self, product):
        assert product.links["tariefkaart"] == (
            "https://files.boltenergie.be/pricelists/var/plenty_online_res_el_nl_13.pdf"
        )
        assert product.links["voorwaarden"] == (
            "https://www.boltenergie.be/nl/algemene-voorwaarden"
        )

    def test_leverancierswebsite_komt_uit_de_website_rij(self, product):
        """Niet uit de eerste de beste externe link in het paneel.

        Op ankertekst alleen matchen pikte hier de consumentenakkoord-link van
        FOD Economie op (economie.fgov.be) als "website van de leverancier".
        De Website-rij van de leverancierssectie geeft boltenergie.be.
        """
        assert product.links["leverancier"] == "https://www.boltenergie.be/"

    def test_links_staan_buiten_het_printblok(self, fragment):
        """Waarom er over het hele fragment gezocht wordt.

        Het paneel draagt het contract twee keer: een verborgen printversie in
        #contractdetail-<id> en de zichtbare .contractDetailsContent. De
        tariefkaartlink staat alleen in die tweede. Scopen op het printblok —
        wat de parser voor de oude, inline uitgeserveerde pagina deed — geeft
        dus wel datums en geen enkele link.
        """
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(fragment, "lxml")
        printblok = soup.select_one("#contractdetail-14972")
        assert printblok is not None
        assert not printblok.select("a[onclick*='matomoLinks']")
        assert soup.select("a[onclick*='matomoLinks']")


class TestGenormaliseerd:
    def test_datums_worden_echte_datums(self, product):
        from datetime import date, datetime

        (n,) = VTestProductNormalizer().normalize([product], datetime.now())
        assert n.datum_intekenen_van == date(2026, 9, 1)
        assert n.datum_intekenen_tot == date(2026, 9, 30)
        assert n.datum_start_levering_van == date(2026, 9, 2)
        assert n.datum_start_levering_tot == date(2027, 1, 31)

    def test_onbepaalde_looptijd_geeft_geen_maandental(self, product):
        """"Onbepaald" is geen getal — raden zou een looptijd verzinnen."""
        from datetime import datetime

        (n,) = VTestProductNormalizer().normalize([product], datetime.now())
        assert n.looptijd_tekst == "Onbepaald"
        assert n.looptijd_maanden is None


class TestSanityCheck:
    """`audit sanity` moet het merken wanneer het detailpaneel niet opgehaald
    is. Zonder deze controle bleef het verschil tussen "opgehaald" en "niet
    opgehaald" onzichtbaar tot de kolommen leeg in de databank stonden."""

    def _paths(self, tmp_path):
        from energie_vlaanderen.data.paths import DataPaths
        from energie_vlaanderen.settings import Settings

        paths = DataPaths.from_settings(
            Settings(project_root=tmp_path, data_root=tmp_path)
        )
        vtest = paths.staging / "20260903T120000Z-abcdef12" / "vtest"
        vtest.mkdir(parents=True)
        return paths, vtest

    _KOP = (
        "vreg_id;supplier_raw;product_raw;energy;looptijd_tekst;datum_intekenen_van;"
        "datum_intekenen_tot;datum_start_levering_van;datum_start_levering_tot;"
        "doelgroep_zonnepanelen;doelgroep_ev;doelgroep_energiedelen;"
        "doelgroep_groepsaankoop;prijszekerheid_termijn;link_tariefkaart;"
        "link_voorwaarden;link_supplier\n"
    )

    _ELEK_VOL = (
        "14972;Bolt;Plenty;Elektriciteit;Onbepaald;2026-09-01;2026-09-30;"
        "2026-09-02;2027-01-31;Nee;Nee;Ja;Nee;Geen prijszekerheid;"
        "https://x/tk.pdf;https://x/av;https://x/\n"
    )
    # Een gaspaneel draagt geen vraag over zonnepanelen, EV of energiedelen.
    _GAS_VOL = (
        "11595;Mega;Smart Flex;Gas;1 jaar;2026-09-01;2026-09-30;"
        "2026-09-02;2027-01-31;;;;Nee;1 jaar;"
        "https://x/tkg.pdf;https://x/av;https://x/\n"
    )

    def test_lege_detailkolommen_geven_een_bevinding(self, tmp_path):
        from energie_vlaanderen.audit.sanity import SanityChecker

        paths, vtest = self._paths(tmp_path)
        (vtest / "vtest_products.csv").write_text(
            self._KOP + "14972;Bolt;Plenty;Elektriciteit;;;;;;;;;;;;;\n",
            encoding="utf-8-sig",
        )
        report = SanityChecker(paths).check_version("20260903T120000Z-abcdef12")
        regels = [v.rule for v in report.violations]
        assert "Contractmetadata ontbreekt" in regels
        assert not report.valid

    def test_gevulde_detailkolommen_geven_geen_bevinding(self, tmp_path):
        from energie_vlaanderen.audit.sanity import SanityChecker

        paths, vtest = self._paths(tmp_path)
        (vtest / "vtest_products.csv").write_text(
            self._KOP + self._ELEK_VOL, encoding="utf-8-sig"
        )
        report = SanityChecker(paths).check_version("20260903T120000Z-abcdef12")
        assert [v.rule for v in report.violations] == []

    def test_een_enkel_contract_zonder_tariefkaart_is_geen_bevinding(self, tmp_path):
        """Het sociaal tarief verwijst naar de CREG en heeft geen tariefkaart.
        Alleen een kolom die voor élk contract leeg is, wijst op een
        ontbrekende scrape."""
        from energie_vlaanderen.audit.sanity import SanityChecker

        paths, vtest = self._paths(tmp_path)
        (vtest / "vtest_products.csv").write_text(
            self._KOP
            + "10025;Sociaal;Sociaal tarief;Elektriciteit;;2026-08-01;2026-09-30;"
              "2026-08-01;2026-09-30;;;;;3 maanden;;;\n"
            + self._ELEK_VOL,
            encoding="utf-8-sig",
        )
        report = SanityChecker(paths).check_version("20260903T120000Z-abcdef12")
        assert [v.rule for v in report.violations] == []

    def test_gas_only_run_faalt_niet_op_elektriciteitsvragen(self, tmp_path):
        """Een gaspaneel draagt geen vraag over zonnepanelen, elektrisch
        voertuig of energiedelen — die secties staan alleen in een
        elektriciteitspaneel. Nagerekend op de scrape van 2026-09-03: 0% op
        776 gasrijen tegenover 99% op 1.709 elektriciteitsrijen. Ze meetellen
        zou een gas-only run vals laten falen.
        """
        from energie_vlaanderen.audit.sanity import SanityChecker

        paths, vtest = self._paths(tmp_path)
        (vtest / "vtest_products.csv").write_text(
            self._KOP + self._GAS_VOL, encoding="utf-8-sig"
        )
        report = SanityChecker(paths).check_version("20260903T120000Z-abcdef12")
        assert [v.rule for v in report.violations] == []

    def test_elektriciteit_zonder_doelgroep_geeft_wel_een_bevinding(self, tmp_path):
        """Andersom moet het wél opvallen: staan er elektriciteitsrijen in en
        is de zonnepanelenvraag daar overal leeg, dan is het paneel niet
        opgehaald."""
        from energie_vlaanderen.audit.sanity import SanityChecker

        paths, vtest = self._paths(tmp_path)
        zonder_doelgroep = (
            "14972;Bolt;Plenty;Elektriciteit;Onbepaald;2026-09-01;2026-09-30;"
            "2026-09-02;2027-01-31;;;;Nee;Geen prijszekerheid;"
            "https://x/tk.pdf;https://x/av;https://x/\n"
        )
        (vtest / "vtest_products.csv").write_text(
            self._KOP + self._GAS_VOL + zonder_doelgroep, encoding="utf-8-sig"
        )
        report = SanityChecker(paths).check_version("20260903T120000Z-abcdef12")
        assert [v.rule for v in report.violations] == ["Contractmetadata ontbreekt"]
        assert "doelgroep_zonnepanelen" in report.violations[0].message
