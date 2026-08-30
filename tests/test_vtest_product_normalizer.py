from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from energie_vlaanderen.ingest.vtest.product_normalizer import (
    NormalizedVTestProduct,
    VTestProductNormalizer,
    parse_date_range,
    parse_looptijd,
    parse_price,
    normalize_energy,
)
from energie_vlaanderen.ingest.vtest.product_parser import RawVTestProduct


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
