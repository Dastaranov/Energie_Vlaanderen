"""Tests voor TariffDataNormalizer — voetnootfilter en basisstructuur."""
from __future__ import annotations

import pandas as pd
import pytest

from energie_vlaanderen.ingest.tariffs.normalizer import TariffDataNormalizer


def _elek_row(col0, desc, hs1=None, hs2=None, ms1=None, ms2=None, ls_dc=None,
              digi=None, ana=None, pro=None, sheet="FA ELEK Afname", source_row=10):
    """Bouw een minimale elektriciteitsrij met de vereiste kolomindices.

    Kolommen: 0=col0, 1=desc, 2=x, 3=unit, 4=x,
              5=HS1, 6=HS2, 7=x, 8=MS1, 9=MS2, 10=x, 11=LS_DC, 12=x,
              13=DIGI, 14=ANA, 15=ANA_PRO
    """
    data = [col0, desc, None, None, None, hs1, hs2, None, ms1, ms2, None, ls_dc, None, digi, ana, pro]
    return {i: v for i, v in enumerate(data)} | {"source_sheet": sheet, "source_row": source_row}


def _elek_injectie_row(col0, desc, val=None, unit="EUR/kWh", sheet="FA ELEK Injectie", source_row=6):
    """Bouw een minimale elektriciteit-injectierij (5 kolommen: col0, desc, x, Tarief, Eenheid)."""
    data = [col0, desc, None, val, unit]
    return {i: v for i, v in enumerate(data)} | {"source_sheet": sheet, "source_row": source_row}


def _gas_injectie_row(col0, desc, val=None, unit="EUR/kWh", sheet="FA GAS Injectie", source_row=8):
    """Bouw een minimale gas-injectierij (4 kolommen: col0, desc, Eenheid, Tarief)."""
    data = [col0, desc, unit, val]
    return {i: v for i, v in enumerate(data)} | {"source_sheet": sheet, "source_row": source_row}


def _make_frame(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows)


def _normalizer():
    return TariffDataNormalizer()


class TestVoetnootFilter:
    """Voetnootrijen mogen nooit in de output terechtkomen."""

    def test_dash_footnote_filtered(self):
        rows = [
            _elek_row("1", "Tarieven voor het netgebruik"),
            _elek_row("", "Gemiddelde maandpiek", digi=49.40, ana=45.00, pro=45.00),
            _elek_row("", "- Deze tarieflijst geldt van 01/01/2026 t.e.m. 31/12/2026.", digi=0.27),
        ]
        df = _make_frame(rows)
        result = _normalizer().normalize(df, pd.DataFrame())
        details = result.afname["Tariefdetail"].tolist()
        assert not any(d.startswith("- ") for d in details), "Dash-voetnoten mogen niet in output staan"

    def test_star_footnote_filtered(self):
        rows = [
            _elek_row("1", "Tarieven voor het netgebruik"),
            _elek_row("", "kWh-tarief", digi=0.023),
            _elek_row("", "*1 Aandeel transmissienetkosten in 'Tarieven voor het netgebruik'", digi=0.268),
        ]
        df = _make_frame(rows)
        result = _normalizer().normalize(df, pd.DataFrame())
        details = result.afname["Tariefdetail"].tolist()
        assert not any(d.startswith("*") for d in details), "Ster-voetnoten mogen niet in output staan"

    def test_real_tariff_rows_kept(self):
        rows = [
            _elek_row("1", "Tarieven voor het netgebruik"),
            _elek_row("", "Gemiddelde maandpiek", digi=49.40, ana=45.00, pro=45.00),
            _elek_row("", "kWh-tarief", digi=0.023, ana=0.023, pro=0.023),
            _elek_row("", "- Footnote zonder prijs"),
        ]
        df = _make_frame(rows)
        result = _normalizer().normalize(df, pd.DataFrame())
        details = result.afname["Tariefdetail"].tolist()
        assert "Gemiddelde maandpiek" in details
        assert "kWh-tarief" in details
        assert len(details) == 6  # 2 tariefdetails × 3 klanttypes

    def test_footnote_with_price_still_filtered(self):
        """Een voetnoot met prijs is geen tariefregel — ook filteren."""
        rows = [
            _elek_row("1", "Aanvullend capaciteitstarief"),
            _elek_row("", "Aanvullend capaciteitstarief voor prosumenten", pro=51.54),
            _elek_row("", "- Aanbieders van vraagresponsdiensten...", pro=1.56),
        ]
        df = _make_frame(rows)
        result = _normalizer().normalize(df, pd.DataFrame())
        details = result.afname["Tariefdetail"].tolist()
        assert not any(d.startswith("- ") for d in details)


class TestNormalizerOutput:
    """Basisstructuur van de genormaliseerde output."""

    def test_output_columns_present(self):
        rows = [
            _elek_row("1", "Tarieven voor het netgebruik"),
            _elek_row("", "Gemiddelde maandpiek", digi=49.40),
        ]
        result = _normalizer().normalize(_make_frame(rows), pd.DataFrame())
        for col in ("Netbeheerder", "Contracttype", "Tarieftype", "Tariefdetail",
                    "Tariefnotering", "Klanttype", "Prijs_num", "source_sheet", "source_row"):
            assert col in result.afname.columns, f"Kolom {col} ontbreekt in output"

    def test_klanttype_mapped_correctly(self):
        rows = [
            _elek_row("1", "Netgebruik"),
            _elek_row("", "Capaciteit", digi=49.0, ana=45.0, pro=51.0),
        ]
        result = _normalizer().normalize(_make_frame(rows), pd.DataFrame())
        klanttypes = set(result.afname["Klanttype"])
        assert klanttypes == {"ELEK_LS_DIGI", "ELEK_LS_ANA", "ELEK_LS_ANA_PRO"}

    def test_row_without_price_skipped(self):
        rows = [
            _elek_row("1", "Netgebruik"),
            _elek_row("", "Vaste term"),  # geen prijs → geen output
        ]
        result = _normalizer().normalize(_make_frame(rows), pd.DataFrame())
        assert result.afname.empty

    def test_empty_input_returns_empty(self):
        result = _normalizer().normalize(pd.DataFrame(), pd.DataFrame())
        assert result.afname.empty
        assert result.injectie.empty

    def test_unknown_dnb_code_skipped(self):
        rows = [
            _elek_row("1", "Tarieven", sheet="ONBEKEND ELEK Afname"),
            _elek_row("", "kWh-tarief", digi=0.02, sheet="ONBEKEND ELEK Afname"),
        ]
        result = _normalizer().normalize(_make_frame(rows), pd.DataFrame())
        assert result.afname.empty

    def test_hs_ms_only_row_produces_hs_ms_klanttypes(self):
        """Rijen als 'Toegangsvermogen' bestaan enkel in de HS/MS-kolommen
        (geen LS-waarden) en waren voorheen volledig onzichtbaar."""
        rows = [
            _elek_row("1", "Afnameklanten op 26-36 kV, 1-26 kV en distributiecabine"),
            _elek_row("", "Toegangsvermogen", hs1=3.470105, hs2=2.804856, ms1=3.470105, ms2=2.804856, ls_dc=4.24418),
        ]
        result = _normalizer().normalize(_make_frame(rows), pd.DataFrame())
        assert set(result.afname["Klanttype"]) == {
            "ELEK_HS1", "ELEK_HS2", "ELEK_MS1", "ELEK_MS2", "ELEK_LS_DC",
        }
        assert len(result.afname) == 5

    def test_row_with_ls_and_hs_ms_values_produces_all_eight_klanttypes(self):
        rows = [
            _elek_row("1", "Netgebruik"),
            _elek_row(
                "", "kWh-tarief",
                hs1=0.02, hs2=0.02, ms1=0.02, ms2=0.02, ls_dc=0.02,
                digi=0.023, ana=0.023, pro=0.023,
            ),
        ]
        result = _normalizer().normalize(_make_frame(rows), pd.DataFrame())
        assert len(result.afname) == 8
        assert set(result.afname["Klanttype"]) == {
            "ELEK_HS1", "ELEK_HS2", "ELEK_MS1", "ELEK_MS2", "ELEK_LS_DC",
            "ELEK_LS_DIGI", "ELEK_LS_ANA", "ELEK_LS_ANA_PRO",
        }


class TestInjectieFanOut:
    """Injectietarieven moeten uitwaaieren naar de klanttypes waarop ze
    daadwerkelijk van toepassing zijn, i.p.v. hardcoded ELEK_LS_DIGI."""

    def test_netgebruik_fans_out_to_all_eight_klanttypes(self):
        rows = [_elek_injectie_row("1", "Tarief voor het netgebruik", val=0.001751)]
        result = _normalizer().normalize(pd.DataFrame(), _make_frame(rows))
        assert len(result.injectie) == 8
        assert set(result.injectie["Klanttype"]) == {
            "ELEK_HS1", "ELEK_HS2", "ELEK_MS1", "ELEK_MS2", "ELEK_LS_DC",
            "ELEK_LS_DIGI", "ELEK_LS_ANA", "ELEK_LS_ANA_PRO",
        }
        assert (result.injectie["Prijs_num"] == 0.001751).all()

    def test_hs_ms_dc_group_fans_out_to_five_klanttypes(self):
        rows = [_elek_injectie_row("", "26-36 kV, 1-26 kV, distributiecabine", val=57.65)]
        result = _normalizer().normalize(pd.DataFrame(), _make_frame(rows))
        assert set(result.injectie["Klanttype"]) == {
            "ELEK_HS1", "ELEK_HS2", "ELEK_MS1", "ELEK_MS2", "ELEK_LS_DC",
        }
        assert len(result.injectie) == 5

    def test_laagspanningsnet_group_fans_out_to_three_klanttypes(self):
        rows = [_elek_injectie_row("", "Laagspanningnet", val=17.85)]
        result = _normalizer().normalize(pd.DataFrame(), _make_frame(rows))
        assert set(result.injectie["Klanttype"]) == {
            "ELEK_LS_DIGI", "ELEK_LS_ANA", "ELEK_LS_ANA_PRO",
        }
        assert len(result.injectie) == 3

    def test_unmatched_injectie_text_produces_warning_not_silent_drop(self):
        rows = [_elek_injectie_row("", "Een volledig onbekende tariefomschrijving", val=1.23)]
        result = _normalizer().normalize(pd.DataFrame(), _make_frame(rows))
        assert result.injectie.empty
        assert any("onbekende tariefomschrijving" in w.message for w in result.warnings)

    def test_gas_injectie_unaffected_single_klanttype(self):
        rows = [_gas_injectie_row("1)", "Het tarief voor het systeembeheer", val=0.000963)]
        result = _normalizer().normalize(pd.DataFrame(), _make_frame(rows))
        assert len(result.injectie) == 1
        assert result.injectie.iloc[0]["Klanttype"] == "GAS_INJ"


class TestKolomkaartUitDeKoppen:
    """De laagspanningskolommen staan niet elk jaar op dezelfde plaats.

    Het VREG-werkboek van 2025 en 2026 zet piekmeting/analoog/prosument op
    kolom 13/14/15. Dat van 2024 heeft één kolom méér — de hoogspanning is er
    anders ingedeeld — en schuift ze naar 14/15/16.

    Met de vaste indeling werd de *piekmeting* van 2024 als "analoge meter"
    gelabeld en de klassieke meter als "prosument": geen ontbrekende data maar
    verkeerd gelabelde data. En omdat er op kolom 13 niets stond, kende de
    2024-export helemaal geen `ELEK_LS_DIGI`, waarna `grid_cost()` stilzwijgend
    0,00 EUR teruggaf voor een digitale meter.
    """

    SHEET = "FA ELEK Afname"
    KAART_2024 = {14: "ELEK_LS_DIGI", 15: "ELEK_LS_ANA", 16: "ELEK_LS_ANA_PRO"}

    @staticmethod
    def _rij_2024(waarden, sheet="FA ELEK Afname"):
        """Een rij met de kolomindeling van 2024: 17 kolommen, LS op 14/15/16."""
        rij = {i: None for i in range(17)}
        rij[1] = "Gemiddelde maandpiek"
        rij[3] = "EUR/kW/jaar"
        rij.update(waarden)
        rij["source_sheet"] = sheet
        rij["source_row"] = 15
        return rij

    def test_de_kaart_uit_de_koppen_krijgt_voorrang(self):
        """Kolom 14 is in 2024 de piekmeting, niet de analoge meter.

        De waarden komen uit het werkboek zelf: Fluvius Antwerpen 2024,
        capaciteitstarief 37,9640234 EUR/kW/jaar en een vaste term van 94,91
        EUR/jaar voor de klassieke meter en de prosument.
        """
        frame = _make_frame([self._rij_2024({14: 37.9640234, 15: 94.91, 16: 94.91})])

        resultaat = _normalizer().normalize(
            frame, pd.DataFrame(), {self.SHEET: self.KAART_2024}
        )
        per_type = dict(zip(resultaat.afname.Klanttype, resultaat.afname.Prijs_num))

        assert per_type["ELEK_LS_DIGI"] == pytest.approx(37.9640234)
        assert per_type["ELEK_LS_ANA"] == pytest.approx(94.91)
        assert per_type["ELEK_LS_ANA_PRO"] == pytest.approx(94.91)

    def test_zonder_kaart_geldt_de_vaste_indeling(self):
        """De jaargangen 2025 en 2026 blijven werken zoals voorheen.

        49,042629 EUR/kW/jaar is het capaciteitstarief van Fluvius
        Midden-Vlaanderen in 2025.
        """
        frame = _make_frame([_elek_row("1.2", "Gemiddelde maandpiek", digi=49.042629)])

        resultaat = _normalizer().normalize(frame, pd.DataFrame())
        per_type = dict(zip(resultaat.afname.Klanttype, resultaat.afname.Prijs_num))

        assert per_type["ELEK_LS_DIGI"] == pytest.approx(49.042629)

    def test_een_afwijkende_indeling_slaat_midden_en_hoogspanning_over(self):
        """Ze op een vaste index lezen zou ze aan het verkeerde niveau hangen.

        Het werkboek van 2024 kent geen "26-36 kV-post"/"26-36 kV-net" maar
        "TRANS HS" en "AV >= 5 MVA"/"AV < 5 MVA". Manifest §7.2 verbiedt sowieso
        residentiële formules op midden- en hoogspanning, dus overslaan is hier
        veiliger dan gokken.
        """
        frame = _make_frame([
            self._rij_2024({5: 12.3852936, 14: 37.9640234, 15: 94.91, 16: 94.91})
        ])

        resultaat = _normalizer().normalize(
            frame, pd.DataFrame(), {self.SHEET: self.KAART_2024}
        )

        assert set(resultaat.afname.Klanttype) == {
            "ELEK_LS_DIGI", "ELEK_LS_ANA", "ELEK_LS_ANA_PRO",
        }

    def test_een_onbekende_netbeheerder_wordt_gemeld(self):
        """De tien Fluvius-entiteiten van vóór de fusie van 2025 staan niet in
        DNB_CODES. Ze overslaan is juist, ze stil overslaan niet."""
        frame = _make_frame([
            self._rij_2024({14: 1.0}, sheet="IVRLK ELEK Afname")
        ])

        resultaat = _normalizer().normalize(frame, pd.DataFrame())

        assert resultaat.afname.empty
        assert any("IVRLK" in issue.message for issue in resultaat.issues)
