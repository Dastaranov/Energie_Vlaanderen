"""De losse velden van een gescrapet contract.

Datums, looptijden en prijsindicaties komen als vrije tekst van vtest.be.
Onleesbare invoer levert hier `None` op en nooit een gok: een looptijd die niet
herkend wordt is onbekend, niet één jaar.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from energie_vlaanderen.ingest.vtest.product_normalizer import (
    NormalizedVTestProduct,
    VTestProductNormalizer,
    parse_comma_price,
    parse_date_range,
    parse_looptijd,
    parse_price,
    normalize_energy,
)
from energie_vlaanderen.ingest.vtest.product_parser import RawVTestProduct


pytestmark = pytest.mark.scrape


def _make_raw(**kwargs) -> RawVTestProduct:
    defaults = dict(
        vreg_id="123",
        leverancier="TestLev",
        product="TestProduct",
        prijs_indicatie="",
        datum_intekenen="",
        datum_start_levering="",
        energietype="elektriciteit",
        looptijd="",
        tarief_type="Vast tarief",
    )
    defaults.update(kwargs)
    return RawVTestProduct(**defaults)


_SCRAPED_AT = datetime(2026, 8, 30, 9, 0, 0, tzinfo=timezone.utc)


class TestParseDateRange:
    def test_parses_datum_intekenen(self):
        van, tot = parse_date_range("1/02/2026 tot en met 28/02/2026")
        assert van == date(2026, 2, 1)
        assert tot == date(2026, 2, 28)

    def test_parses_single_digit_day(self):
        van, tot = parse_date_range("5/03/2026 tot en met 31/03/2026")
        assert van == date(2026, 3, 5)
        assert tot == date(2026, 3, 31)

    def test_empty_datum_returns_none(self):
        assert parse_date_range("") == (None, None)

    def test_unparseable_returns_none(self):
        assert parse_date_range("onbekend") == (None, None)


class TestParseLooptijd:
    def test_parses_looptijd_jaar(self):
        assert parse_looptijd("1 jaar") == 12

    def test_parses_looptijd_two_year(self):
        assert parse_looptijd("2 jaar") == 24

    def test_parses_looptijd_drie_jaar(self):
        assert parse_looptijd("3 jaar") == 36

    def test_parses_looptijd_maanden(self):
        assert parse_looptijd("6 maanden") == 6

    def test_parses_looptijd_one_maand(self):
        assert parse_looptijd("1 maand") == 1

    def test_unknown_looptijd_returns_none(self):
        assert parse_looptijd("Onbepaald") is None

    def test_empty_string_returns_none(self):
        assert parse_looptijd("") is None


class TestParsePrice:
    def test_parses_prijs_indicatie(self):
        assert parse_price("€ 954,87") == Decimal("954.87")

    def test_parses_prijs_with_thousands(self):
        assert parse_price("€ 1.276,46") == Decimal("1276.46")

    def test_parses_prijs_no_space(self):
        assert parse_price("€954,87") == Decimal("954.87")

    def test_empty_returns_none(self):
        assert parse_price("") is None

    def test_unparseable_returns_none(self):
        assert parse_price("n/a") is None


class TestNormalizeEnergy:
    def test_elektriciteit(self):
        assert normalize_energy("elektriciteit") == "Elektriciteit"

    def test_gas(self):
        assert normalize_energy("gas") == "Gas"

    def test_mixed_case(self):
        assert normalize_energy("Elektriciteit") == "Elektriciteit"

    def test_unknown_passthrough(self):
        assert normalize_energy("stoom") == "stoom"


class TestVTestProductNormalizer:
    def test_normalize_doelgroep(self):
        raw = _make_raw(
            doelgroep={"zonnepanelen": "Ja", "EV": "Nee", "energiedelen": "", "leegstand": "", "groepsaankoop": ""},
        )
        result = VTestProductNormalizer().normalize([raw], _SCRAPED_AT)
        assert len(result) == 1
        p = result[0]
        assert p.doelgroep_zonnepanelen == "Ja"
        assert p.doelgroep_ev == "Nee"
        assert p.doelgroep_energiedelen == ""

    def test_normalize_full_product(self):
        raw = _make_raw(
            vreg_id="456",
            leverancier="Luminus",
            product="MyPlan",
            prijs_indicatie="€ 1.100,00",
            datum_intekenen="1/01/2026 tot en met 31/01/2026",
            datum_start_levering="1/02/2026 tot en met 28/02/2026",
            energietype="elektriciteit",
            looptijd="1 jaar",
            tarief_type="Vast tarief",
            prijszekerheid={"termijn": "12 maanden", "onderdelen": "", "formule": "", "indexatieparameter": "", "ToU": ""},
            links={"tariefkaart": "https://ex.com/kaart.pdf", "voorwaarden": "https://ex.com/av.pdf", "link": "https://ex.com"},
        )
        result = VTestProductNormalizer().normalize([raw], _SCRAPED_AT)
        p = result[0]
        assert p.vreg_id == "456"
        assert p.energy == "Elektriciteit"
        assert p.looptijd_maanden == 12
        assert p.prijs_indicatie_eur == Decimal("1100.00")
        assert p.datum_intekenen_van == date(2026, 1, 1)
        assert p.datum_intekenen_tot == date(2026, 1, 31)
        assert p.datum_start_levering_van == date(2026, 2, 1)
        assert p.scraped_at == _SCRAPED_AT
        assert p.link_tariefkaart == "https://ex.com/kaart.pdf"
        assert p.prijszekerheid_termijn == "12 maanden"

    def test_normalize_gas_product(self):
        raw = _make_raw(energietype="gas", looptijd="2 jaar")
        result = VTestProductNormalizer().normalize([raw], _SCRAPED_AT)
        p = result[0]
        assert p.energy == "Gas"
        assert p.looptijd_maanden == 24


class TestParseCommaPrice:
    def test_parses_simple_value(self):
        assert parse_comma_price("859,63") == Decimal("859.63")

    def test_parses_value_above_thousand_no_separator(self):
        # data-price gebruikt geen duizendtalscheiding, anders dan parse_price().
        assert parse_comma_price("1867,03") == Decimal("1867.03")

    def test_empty_returns_none(self):
        assert parse_comma_price("") is None


class TestVTestProductNormalizerResultAttrs:
    """data-*-attributen en data-productinvoicestring krijgen voorrang op de
    oude tekst-uit-detailtabel-aanpak."""

    _INVOICE = {
        "summary": {
            "totalUsage": 3434.0,
            "price": {"totalExVAT": 890.63, "total": 944.07, "totalVAT": 53.44},
        },
        "groupResults": [
            {
                "name": "Energiekost",
                "componentResults": [
                    {
                        "id": "1", "name": "Vaste vergoeding", "calculationType": "Fixed",
                        "price": {"totalExVAT": 47.17, "total": 50.0, "totalVAT": 2.83, "vatRates": {"0.06": 2.83}},
                        "flowResults": {},
                    },
                    {
                        "id": "2", "name": "Energiecomponent", "calculationType": "Variable",
                        "price": {"totalExVAT": 266.02, "total": 281.98, "totalVAT": 15.96, "vatRates": {"0.06": 15.96}},
                        "flowResults": {
                            "variabel": {"flowOutput": {"Formula": ["(0,112 * indexatieparameter)", "2"]}},
                        },
                    },
                ],
            },
        ],
    }

    def test_tariff_type_attr_takes_precedence(self):
        raw = _make_raw(tarief_type="Vast tarief", tariff_type_attr="VARIABLE")
        result = VTestProductNormalizer().normalize([raw], _SCRAPED_AT)
        assert result[0].tariff_type == "Variabel"

    def test_tariff_type_falls_back_to_raw_text_when_attr_missing(self):
        raw = _make_raw(tarief_type="Vast tarief", tariff_type_attr="")
        result = VTestProductNormalizer().normalize([raw], _SCRAPED_AT)
        assert result[0].tariff_type == "Vast tarief"

    def test_energy_prefers_contracttype_over_energietype_text(self):
        raw = _make_raw(energietype="", contracttype="GAS")
        result = VTestProductNormalizer().normalize([raw], _SCRAPED_AT)
        assert result[0].energy == "Gas"

    def test_stars_and_complex_product_and_grayedout(self):
        raw = _make_raw(stars="5", complex_product="True", grayedout=True)
        result = VTestProductNormalizer().normalize([raw], _SCRAPED_AT)
        p = result[0]
        assert p.stars == 5
        assert p.complex_product is True
        assert p.grayedout is True

    def test_missing_stars_is_none(self):
        raw = _make_raw(stars="")
        result = VTestProductNormalizer().normalize([raw], _SCRAPED_AT)
        assert result[0].stars is None

    def test_summary_totals_extracted_from_invoice_raw(self):
        raw = _make_raw(invoice_raw=self._INVOICE, price_raw="944,07")
        result = VTestProductNormalizer().normalize([raw], _SCRAPED_AT)
        p = result[0]
        assert p.total_excl_btw == Decimal("890.63")
        assert p.total_incl_btw == Decimal("944.07")
        assert p.btw_bedrag == Decimal("53.44")
        assert p.totaal_verbruik_kwh == Decimal("3434.0")
        assert p.prijs_indicatie_eur == Decimal("944.07")

    def test_summary_totals_none_when_no_invoice(self):
        raw = _make_raw(invoice_raw=None)
        result = VTestProductNormalizer().normalize([raw], _SCRAPED_AT)
        p = result[0]
        assert p.total_excl_btw is None
        assert p.totaal_verbruik_kwh is None


class TestNormalizeComponents:
    _INVOICE = TestVTestProductNormalizerResultAttrs._INVOICE

    def test_extracts_one_row_per_component(self):
        raw = _make_raw(vreg_id="456", invoice_raw=self._INVOICE)
        components = VTestProductNormalizer().normalize_components([raw])
        assert len(components) == 2
        assert {c.component_naam for c in components} == {"Vaste vergoeding", "Energiecomponent"}

    def test_component_amounts_and_vat(self):
        raw = _make_raw(vreg_id="456", invoice_raw=self._INVOICE)
        components = VTestProductNormalizer().normalize_components([raw])
        vaste = next(c for c in components if c.component_naam == "Vaste vergoeding")
        assert vaste.totaal_excl_btw == Decimal("47.17")
        assert vaste.totaal_incl_btw == Decimal("50.0")
        assert vaste.btw_bedrag == Decimal("2.83")
        assert vaste.btw_percentage == Decimal("0.06")
        assert vaste.groep_naam == "Energiekost"

    def test_formule_extracted_from_flow_output(self):
        raw = _make_raw(vreg_id="456", invoice_raw=self._INVOICE)
        components = VTestProductNormalizer().normalize_components([raw])
        energiecomponent = next(c for c in components if c.component_naam == "Energiecomponent")
        assert "indexatieparameter" in energiecomponent.formule

    def test_no_invoice_raw_produces_no_rows(self):
        raw = _make_raw(vreg_id="789", invoice_raw=None)
        components = VTestProductNormalizer().normalize_components([raw])
        assert components == []
