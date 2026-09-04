"""De vergelijkingsregels van de golden master.

`audit golden` legt de gestagede waarden cel voor cel naast het bron-XLSX. Alles
staat of valt bij wanneer twee cellen "gelijk" heten: een lege cel tegenover 0,
een Belgische komma tegenover een punt, `None` tegenover 0. Elk van die gevallen
is óf ruis die honderd valse verschillen meldt, óf een echt verschil dat
weggemoffeld wordt — vandaar dat ze hier stuk voor stuk vastliggen.
"""
from __future__ import annotations

import io
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest

from energie_vlaanderen.audit.golden import (
    FieldMismatch,
    GoldenAuditResult,
    VTestGoldenAuditor,
    _decimals_equal,
    _floats_equal,
)


# ---------------------------------------------------------------------------
# Unit tests: decimal comparison helper
# ---------------------------------------------------------------------------

pytestmark = pytest.mark.databank


def test_decimals_equal_both_zero() -> None:
    assert _decimals_equal("0", Decimal("0"))

def test_decimals_equal_belgian_comma() -> None:
    assert _decimals_equal("0,105", Decimal("0.105"))

def test_decimals_equal_mismatch() -> None:
    assert not _decimals_equal("0,106", Decimal("0.105"))

def test_decimals_equal_empty_csv_and_zero_fresh() -> None:
    # CSV "" treated as zero; Decimal("0") == zero → pass
    assert _decimals_equal("", Decimal("0"))

def test_decimals_equal_empty_csv_nonzero_fresh() -> None:
    assert not _decimals_equal("", Decimal("1.5"))

def test_decimals_equal_none_fresh_and_zero_csv() -> None:
    assert _decimals_equal("0", None)

def test_decimals_equal_none_fresh_and_nonzero_csv() -> None:
    assert not _decimals_equal("1,5", None)

def test_decimals_equal_both_none() -> None:
    assert _decimals_equal("", None)


# ---------------------------------------------------------------------------
# Unit tests: float comparison helper
# ---------------------------------------------------------------------------

def test_floats_equal_within_tolerance() -> None:
    assert _floats_equal("49.4036", "49.4037", 1e-3)

def test_floats_equal_outside_tolerance() -> None:
    assert not _floats_equal("49.4036", "49.5000", 1e-4)

def test_floats_equal_exact() -> None:
    assert _floats_equal("1.23456", "1.23456", 1e-4)

def test_floats_equal_non_numeric_fallback() -> None:
    assert _floats_equal("abc", "abc", 1e-4)
    assert not _floats_equal("abc", "def", 1e-4)


# ---------------------------------------------------------------------------
# GoldenAuditResult dataclass
# ---------------------------------------------------------------------------

def test_passed_when_no_mismatches() -> None:
    result = GoldenAuditResult(
        version_id="test",
        domain="vtest_vast",
        source_xlsx=Path("vtest.xlsx"),
        total_rows=5,
        verified_rows=5,
        mismatches=(),
    )
    assert result.passed

def test_failed_when_mismatches_present() -> None:
    mm = FieldMismatch(
        domain="vtest_vast",
        source_sheet="Producten vast",
        source_row=10,
        field="price",
        csv_value="1,23",
        xlsx_value="1.24",
        row_key="A / B / 2026-1 / single",
    )
    result = GoldenAuditResult(
        version_id="test",
        domain="vtest_vast",
        source_xlsx=Path("vtest.xlsx"),
        total_rows=5,
        verified_rows=5,
        mismatches=(mm,),
    )
    assert not result.passed


# ---------------------------------------------------------------------------
# Een audit die niets vergeleken heeft, slaagt niet
# ---------------------------------------------------------------------------
#
# Deze test beweerde eerder het omgekeerde: een resultaat met 0 rijen en 0
# verschillen moest `passed` zijn. Daarmee legde ze een echte fout vast als
# gewenst gedrag. `version publish` ruimt de stagingmap op, en `audit golden`
# las alleen daar — op een gepubliceerde versie vond ze dus geen enkel CSV en
# meldde "OK 0/0 rijen geverifieerd" voor alle zeven domeinen. Een groene
# audit die niets gecontroleerd had, en juist deze audit is de poort naar
# publicatie. Precies de foutklasse uit CLAUDE.md: "een sanity-check die zijn
# bestanden niet vond en toch geslaagd meldde".


def test_ontbrekend_bestand_laat_de_audit_falen(tmp_path: Path) -> None:
    result = GoldenAuditResult(
        version_id="v1",
        domain="vtest_vast",
        source_xlsx=tmp_path / "dummy.xlsx",
        total_rows=0,
        verified_rows=0,
        mismatches=(),
        ontbrekend_bestand=tmp_path / "master_vast.csv",
    )
    assert not result.passed
    assert result.ontbrekend_bestand is not None


def test_nul_geverifieerde_rijen_laat_de_audit_falen(tmp_path: Path) -> None:
    """Ook zonder ontbrekend bestand: nul vergelijkingen is geen bewijs."""
    result = GoldenAuditResult(
        version_id="v1",
        domain="vtest_vast",
        source_xlsx=tmp_path / "dummy.xlsx",
        total_rows=0,
        verified_rows=0,
        mismatches=(),
    )
    assert not result.passed


def test_auditor_meldt_welk_bestand_ontbreekt(tmp_path: Path, monkeypatch) -> None:
    """De auditor zelf moet het ontbrekende pad teruggeven, niet stil slagen."""
    import pandas as pd

    from energie_vlaanderen.audit import golden as golden_mod

    class _LeegWerkboek:
        fixed = pd.DataFrame()
        variable_dynamic = pd.DataFrame()

    monkeypatch.setattr(
        golden_mod.VTestWorkbookParser, "parse", lambda self, pad: _LeegWerkboek()
    )
    xlsx = tmp_path / "dummy.xlsx"
    xlsx.write_bytes(b"")
    ontbreekt = tmp_path / "master_vast.csv"

    result = VTestGoldenAuditor().audit(
        staged_csv=ontbreekt, source_xlsx=xlsx, domain="vtest_vast", version_id="v1"
    )
    assert result.ontbrekend_bestand == ontbreekt
    assert not result.passed


# ---------------------------------------------------------------------------
# VTestGoldenAuditor._decimals_equal via public API
# ---------------------------------------------------------------------------

def test_audit_passes_when_staged_csv_matches_fresh(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Auditor returns 0 mismatches when the CSV matches the normalizer output exactly."""
    from energie_vlaanderen.audit.golden import VTestGoldenAuditor
    from energie_vlaanderen.ingest.vtest.normalizer import VTestDataNormalizer, NormalizedVTestData
    from energie_vlaanderen.ingest.vtest.workbook import VTestWorkbookParser, ParsedVTestWorkbook, ParsedSheet

    fixed_row = {
        "year": 2026, "month": 1, "segment": "Woning", "energy": "Elektriciteit",
        "direction": "Afname", "supplier": "TestCo", "product": "TestProd",
        "product_type": "vast", "component": "single",
        "component_label": "Enkelvoudige meter dagtarief (c€/kWh)",
        "price": Decimal("10.50"),
        "a": Decimal("0"), "b": Decimal("0"), "c": Decimal("0"),
        "d": Decimal("0"), "z": Decimal("0"),
        "index_name_A": "", "index_name_B": "", "index_name_C": "", "index_name_D": "",
        "index_value_A": None, "index_value_B": None, "index_value_C": None, "index_value_D": None,
        "source_sheet": "Producten vast", "source_row": 6,
    }
    fresh_fixed = pd.DataFrame([fixed_row])

    # Monkeypatch parser and normalizer so we don't need a real XLSX
    def fake_parse(self: VTestWorkbookParser, path: Path) -> ParsedVTestWorkbook:
        return ParsedVTestWorkbook(
            source_path=path,
            fixed=pd.DataFrame([{
                "Jaar": 2026, "Maand": "jan", "Segment": "Woning",
                "Energietype": "Elektriciteit", "Contracttype": "Afname",
                "Handelsnaam": "TestCo", "Productnaam": "TestProd",
                "Vast/variabel/dynamisch": "Vast",
                "Prijsonderdeel": "Enkelvoudige meter dagtarief (c€/kWh)",
                "Prijs": "10,50",
                "source_sheet": "Producten vast", "source_row": 6,
            }]),
            variable_dynamic=pd.DataFrame(),
            sheets=(ParsedSheet("Producten vast", 0, 1, (), (6,)),),
            warnings=(),
        )

    def fake_normalize(self: VTestDataNormalizer, fixed: pd.DataFrame, variable_dynamic: pd.DataFrame) -> NormalizedVTestData:
        return NormalizedVTestData(fixed=fresh_fixed.copy(), variable_dynamic=pd.DataFrame(), issues=())

    monkeypatch.setattr(VTestWorkbookParser, "parse", fake_parse)
    monkeypatch.setattr(VTestDataNormalizer, "normalize", fake_normalize)

    # Write a staged CSV that exactly mirrors the fresh output
    staged_csv = tmp_path / "master_vast.csv"
    staged_csv.write_text(
        "year;month;segment;energy;direction;supplier;product;product_type;component;"
        "component_label;price;a;b;c;d;z;index_name_A;index_name_B;index_name_C;index_name_D;"
        "index_value_A;index_value_B;index_value_C;index_value_D;source_sheet;source_row\r\n"
        "2026;1;Woning;Elektriciteit;Afname;TestCo;TestProd;vast;single;"
        "Enkelvoudige meter dagtarief (c€/kWh);10,50;0;0;0;0;0;;;;;;;"
        ";;Producten vast;6\r\n",
        encoding="utf-8-sig",
    )

    result = VTestGoldenAuditor().audit(
        staged_csv=staged_csv,
        source_xlsx=tmp_path / "vtest.xlsx",
        domain="vtest_vast",
        version_id="test",
    )

    assert result.passed, result.mismatches
    assert result.verified_rows == 1


def test_audit_detects_price_mismatch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Auditor reports a mismatch when a price differs between CSV and fresh data."""
    from energie_vlaanderen.audit.golden import VTestGoldenAuditor
    from energie_vlaanderen.ingest.vtest.normalizer import VTestDataNormalizer, NormalizedVTestData
    from energie_vlaanderen.ingest.vtest.workbook import VTestWorkbookParser, ParsedVTestWorkbook, ParsedSheet

    fresh_fixed = pd.DataFrame([{
        "year": 2026, "month": 1, "segment": "Woning", "energy": "Elektriciteit",
        "direction": "Afname", "supplier": "TestCo", "product": "TestProd",
        "product_type": "vast", "component": "single",
        "component_label": "Enkelvoudige meter dagtarief (c€/kWh)",
        "price": Decimal("10.50"),
        "a": Decimal("0"), "b": Decimal("0"), "c": Decimal("0"),
        "d": Decimal("0"), "z": Decimal("0"),
        "index_name_A": "", "index_name_B": "", "index_name_C": "", "index_name_D": "",
        "index_value_A": None, "index_value_B": None, "index_value_C": None, "index_value_D": None,
        "source_sheet": "Producten vast", "source_row": 6,
    }])

    def fake_parse(self: VTestWorkbookParser, path: Path) -> ParsedVTestWorkbook:
        return ParsedVTestWorkbook(
            source_path=path, fixed=pd.DataFrame(), variable_dynamic=pd.DataFrame(),
            sheets=(), warnings=(),
        )

    def fake_normalize(self: VTestDataNormalizer, fixed: pd.DataFrame, variable_dynamic: pd.DataFrame) -> NormalizedVTestData:
        return NormalizedVTestData(fixed=fresh_fixed.copy(), variable_dynamic=pd.DataFrame(), issues=())

    monkeypatch.setattr(VTestWorkbookParser, "parse", fake_parse)
    monkeypatch.setattr(VTestDataNormalizer, "normalize", fake_normalize)

    staged_csv = tmp_path / "master_vast.csv"
    staged_csv.write_text(
        "year;month;segment;energy;direction;supplier;product;product_type;component;"
        "component_label;price;a;b;c;d;z;index_name_A;index_name_B;index_name_C;index_name_D;"
        "index_value_A;index_value_B;index_value_C;index_value_D;source_sheet;source_row\r\n"
        "2026;1;Woning;Elektriciteit;Afname;TestCo;TestProd;vast;single;"
        "Enkelvoudige meter dagtarief (c€/kWh);9,99;0;0;0;0;0;;;;;;;"  # wrong price
        ";;Producten vast;6\r\n",
        encoding="utf-8-sig",
    )

    result = VTestGoldenAuditor().audit(
        staged_csv=staged_csv,
        source_xlsx=tmp_path / "vtest.xlsx",
        domain="vtest_vast",
        version_id="test",
    )

    assert not result.passed
    price_mismatch = next((m for m in result.mismatches if m.field == "price"), None)
    assert price_mismatch is not None
    assert price_mismatch.csv_value == "9,99"
    assert "10" in price_mismatch.xlsx_value


# ---------------------------------------------------------------------------
# De hoogspanningskolommen: ELEK_LS_DC hoort erbij
# ---------------------------------------------------------------------------
#
# Kolom 11 van het afnameblad is "≤1 kV / distributiecabine" (ELEK_LS_DC): in
# naam laagspanning, maar met een eigen kolom náást de kop "Laagspanningsnet"
# en met MS/HS-achtige tarieven (toegangsvermogen in kVA). De splitsing tussen
# "uit de koppen afgeleid" en "op vaste index" liep op de naam
# (startswith("ELEK_LS_")), waardoor dit klanttype uit beide groepen viel en
# kolom 11 door niemand gelezen werd. 96 afnamerijen met echte prijzen, voor
# alle acht netbeheerders, verdwenen zo stil uit de dataset.


def test_ls_distributiecabine_hoort_bij_de_vaste_kolommen() -> None:
    from energie_vlaanderen.ingest.tariffs.normalizer import (
        ELEK_AFNAME_KOPKOLOMMEN,
        ELEK_AFNAME_VASTE_KOLOMMEN,
        ELEK_LS_STANDAARDKAART,
    )

    vaste = {k for _, k in ELEK_AFNAME_VASTE_KOLOMMEN}
    # ELEK_LS_DC wordt op vaste index gelezen, samen met MS en HS.
    assert "ELEK_LS_DC" in vaste
    assert {"ELEK_HS1", "ELEK_HS2", "ELEK_MS1", "ELEK_MS2"} <= vaste
    # En het is géén kopkolom: de kop boven kolom 11 is "≤1 kV", niet
    # "Laagspanningsnet".
    assert "ELEK_LS_DC" not in ELEK_AFNAME_KOPKOLOMMEN
    assert "ELEK_LS_DC" not in ELEK_LS_STANDAARDKAART.values()
    # De kopkaart dekt precies de drie meetsoorten onder "Laagspanningsnet".
    assert set(ELEK_LS_STANDAARDKAART.values()) == {
        "ELEK_LS_DIGI", "ELEK_LS_ANA", "ELEK_LS_ANA_PRO",
    }


def test_geen_klanttype_valt_tussen_de_twee_groepen() -> None:
    """Het invariant dat de fout onmogelijk maakt: elk klanttype uit de
    kolomlijst zit in precies één van de twee groepen."""
    from energie_vlaanderen.ingest.tariffs.normalizer import (
        ELEK_AFNAME_COLS,
        ELEK_AFNAME_KOPKOLOMMEN,
        ELEK_AFNAME_VASTE_KOLOMMEN,
    )

    alle = {k for _, k in ELEK_AFNAME_COLS}
    vaste = {k for _, k in ELEK_AFNAME_VASTE_KOLOMMEN}
    assert vaste | set(ELEK_AFNAME_KOPKOLOMMEN) == alle
    assert not (vaste & set(ELEK_AFNAME_KOPKOLOMMEN))


def test_verschillend_rij_aantal_onderdrukt_de_positieverschillen(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bij een afwijkend rij-aantal is alleen `_row_count` bruikbaar.

    De vergelijking loopt op positie. Ontbreken er rijen, dan staan de twee
    kanten vanaf dat punt uit de pas en telt bijna elk veld als verschil — in
    het geval dat dit blootlegde 2.220 stuks, geen ervan echt (het CSV miste
    96 ELEK_LS_DC-rijen). Die lijst afdrukken stuurt de lezer een dwaalspoor
    op; het rij-aantal is de enige echte bevinding.
    """
    import pandas as pd

    from energie_vlaanderen.audit import golden as golden_mod

    kolommen = ["Netbeheerder", "Klanttype", "Tarieftype", "Tariefdetail",
                "Tariefnotering", "Prijs_num", "source_sheet", "source_row"]

    def _rij(klanttype: str, prijs: str, rij: int) -> dict:
        return {
            "Netbeheerder": "FA", "Klanttype": klanttype,
            "Tarieftype": "Netgebruik", "Tariefdetail": "Toegangsvermogen",
            "Tariefnotering": "EUR/kVA/jaar", "Prijs_num": prijs,
            "source_sheet": "FA ELEK Afname", "source_row": str(rij),
        }

    # De verse kant heeft één rij méér dan het CSV.
    vers = pd.DataFrame([_rij("ELEK_HS1", "1.0", 1), _rij("ELEK_LS_DC", "2.0", 2)],
                        columns=kolommen)
    staged = tmp_path / "tariffs_electricity_hoogspanning.csv"
    pd.DataFrame([_rij("ELEK_HS1", "1.0", 1)], columns=kolommen).to_csv(
        staged, sep=";", index=False, encoding="utf-8-sig"
    )

    class _Parsed:
        afname = pd.DataFrame()
        injectie = pd.DataFrame()

        @staticmethod
        def kolomkaarten():
            return {}

    class _Norm:
        afname = vers
        injectie = pd.DataFrame()

    monkeypatch.setattr(
        golden_mod.TariffWorkbookParser, "parse",
        lambda self, pad, energy_type=None: _Parsed(),
    )
    monkeypatch.setattr(
        golden_mod.TariffDataNormalizer, "normalize",
        lambda self, a, i, k=None: _Norm(),
    )

    xlsx = tmp_path / "elek.xlsx"
    xlsx.write_bytes(b"")
    result = golden_mod.TariffGoldenAuditor().audit(
        staged_csv=staged, source_xlsx=xlsx, energy_type="electricity",
        direction="hoogspanning", version_id="v1",
    )

    assert not result.passed
    velden = [mm.field for mm in result.mismatches]
    assert velden == ["_row_count"], f"alleen het rij-aantal verwacht, kreeg {velden}"
