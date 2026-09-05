"""Tests voor het schatten van een verbruik met de Synergrid-profielen.

Twee eigenschappen van de brondata die door elkaar halen een stil verkeerd
getal oplevert, en die daarom hier vastliggen:

- **SLP-EX en RLP0N sommeren tot 1.** Het zijn verdelingen.
- **SPP sommeert niet tot 1.** Het werkboek zegt op het blad "Read Me First"
  letterlijk: *"SPP-value expressed in mW/mWp"* — MW per MWp, dus een
  dimensieloze *vermogens*verhouding. Om er energie van te maken moet met de
  intervalduur vermenigvuldigd worden. Over 2026 sommeren de kwartierwaarden
  tot 4.119,94; als energie gelezen zou dat 4.120 kWh per kWp per jaar zijn,
  vier keer de werkelijke Vlaamse opbrengst. Maal 0,25 uur wordt het
  1.030 kWh/kWp/jaar, wat wél klopt.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal as D

import pandas as pd
import pytest

from energie_vlaanderen.gebruikers.schatting import (
    SchattingError,
    controleer_som,
    dekkingsgraad,
    gewichten_uit_databank,
    intervalduur_uren,
    maandpieken_uit_metingen,
    maandpieken_uit_profiel,
    productie_uit_kwp,
    verdeel_jaarverbruik,
)


pytestmark = pytest.mark.dossier


def kwartieren(aantal: int, gewicht: float, start: str = "2026-01-01") -> pd.DataFrame:
    return pd.DataFrame(
        {
            "tijdstip": pd.date_range(start, periods=aantal, freq="15min", tz="UTC"),
            "gewicht": [gewicht] * aantal,
        }
    )


class TestVerdeling:
    def test_een_genormaliseerd_profiel_verdeelt_precies_het_jaarverbruik(self):
        """kWh_t = jaarverbruik x gewicht_t, en de som is het jaarverbruik terug."""
        gewichten = kwartieren(4, 0.25)
        verdeeld = verdeel_jaarverbruik(D("3000"), gewichten, "slp_ex")
        assert verdeeld["kwh"].sum() == pytest.approx(3000.0)
        assert verdeeld["kwh"].iloc[0] == pytest.approx(750.0)

    def test_een_profiel_dat_niet_tot_1_sommeert_stopt_de_berekening(self):
        """Een verdeling die niet tot 1 sommeert verdeelt het jaarverbruik verkeerd."""
        with pytest.raises(SchattingError, match="sommeert"):
            verdeel_jaarverbruik(D("3000"), kwartieren(4, 0.30), "slp_ex")

    def test_spp_mag_niet_als_verdeling_gebruikt_worden(self):
        """SPP is productie per kWp; het als verdeling gebruiken is een categoriefout."""
        with pytest.raises(SchattingError, match="geen verdeling"):
            verdeel_jaarverbruik(D("3000"), kwartieren(4, 0.25), "spp")

    def test_de_som_tot_1_controle_geldt_niet_voor_spp(self):
        """Ze uitzetten voor alles zou de controle op SLP-EX en RLP0N meenemen."""
        gewichten = kwartieren(4, 0.30)
        assert controleer_som(gewichten, "spp") == pytest.approx(1.2)


class TestProductie:
    def test_spp_wordt_met_de_intervalduur_vermenigvuldigd(self):
        """Zonder de kwartierduur komt de PV-productie vier keer te hoog uit.

        Vier kwartieren met waarde 1,0 mW/mWp betekent één uur op vol vermogen:
        5 kWp x 1,0 x 1 uur = 5 kWh. Zonder de factor 0,25 zou er 20 kWh uitkomen.
        """
        gewichten = kwartieren(4, 1.0)
        assert intervalduur_uren(gewichten) == D("0.25")
        productie = productie_uit_kwp(D("5"), gewichten)
        assert productie["kwh"].sum() == pytest.approx(5.0)

    def test_uurdata_krijgt_een_intervalduur_van_een_uur(self):
        """RLP0N-gas is uurresolutie, geen kwartier — de duur komt uit de data zelf."""
        uren = pd.DataFrame(
            {
                "tijdstip": pd.date_range("2026-01-01", periods=4, freq="h", tz="UTC"),
                "gewicht": [1.0] * 4,
            }
        )
        assert intervalduur_uren(uren) == D("1")
        assert productie_uit_kwp(D("5"), uren)["kwh"].sum() == pytest.approx(20.0)

    def test_zonder_kwp_is_er_geen_pv_productie_te_schatten(self):
        with pytest.raises(SchattingError, match="kWp"):
            productie_uit_kwp(D("0"), kwartieren(4, 1.0))


class TestMaandpiek:
    def test_uit_een_profiel_komt_geen_maandpiek(self):
        """De piek van een profiel is de piek van een gemiddelde over duizenden
        aansluitingen, niet die van dit gezin. Manifest §12 laat enkel een
        *gedocumenteerde* schatting toe — dat is de 4,218 kW uit vtest.be, geen
        afgeleide van een profiel.
        """
        with pytest.raises(SchattingError, match="geen maandpiek"):
            maandpieken_uit_profiel(kwartieren(4, 0.25))

    def test_uit_metingen_komt_de_piek_in_kw_niet_in_kwh(self):
        """Een maandpiek is het hoogste kwartiergemiddelde x 4.

        0,75 kWh in één kwartier is 3 kW gemiddeld vermogen. De factor 4
        vergeten maakt de piek een kwart van wat ze is, en daarmee het
        capaciteitstarief ook.
        """
        metingen = pd.DataFrame(
            {
                "tijdstip": pd.date_range("2026-01-01", periods=4, freq="15min", tz="UTC"),
                "afname_kwh": [0.25, 0.75, 0.50, 0.10],
            }
        )
        (piek,) = maandpieken_uit_metingen(metingen, 2026)
        assert piek == D("3.0")

    def test_maanden_zonder_meting_krijgen_geen_piek_van_nul(self):
        """Een nulpiek zou de laagste maand van het jaar verzinnen."""
        metingen = pd.DataFrame(
            {
                "tijdstip": pd.date_range("2026-01-01", periods=4, freq="15min", tz="UTC"),
                "afname_kwh": [0.25, 0.75, 0.50, 0.10],
            }
        )
        assert len(maandpieken_uit_metingen(metingen, 2026)) == 1


class TestDekking:
    def test_een_halfjaar_meting_dekt_de_helft_van_het_jaar(self):
        """Manifest §9: onvoldoende meetdekking wordt zichtbaar gerapporteerd."""
        metingen = pd.DataFrame(
            {
                "tijdstip": pd.date_range("2026-01-01", periods=48, freq="h", tz="UTC"),
                "afname_kwh": [1.0] * 48,
            }
        )
        # 48 uurpunten over een venster van 4 dagen = de helft.
        assert dekkingsgraad(metingen, date(2026, 1, 1), date(2026, 1, 5)) == pytest.approx(
            D("0.5"), rel=1e-6
        )

    def test_geen_metingen_is_geen_dekking(self):
        leeg = pd.DataFrame({"tijdstip": [], "afname_kwh": []})
        assert dekkingsgraad(leeg, date(2026, 1, 1), date(2027, 1, 1)) == D("0")

    def test_dekking_is_nooit_meer_dan_een(self):
        metingen = pd.DataFrame(
            {
                "tijdstip": pd.date_range("2026-01-01", periods=96, freq="15min", tz="UTC"),
                "afname_kwh": [1.0] * 96,
            }
        )
        assert dekkingsgraad(metingen, date(2026, 1, 1), date(2026, 1, 2)) == D("1")


class _NepConn:
    """Een minimale stand-in voor `sqlalchemy.Connection.execute(...).all()`,
    zodat `gewichten_uit_databank()` zonder echte databank te toetsen is."""

    def __init__(self, rijen: list[tuple]) -> None:
        self._rijen = rijen

    def execute(self, _query, _params=None):
        return self

    def all(self):
        return self._rijen


class TestGewichtenUitDatabank:
    """Zelfde contract als `ProfielenUitCsv.gewichten()`, maar uit
    `verbruiksprofiel_waarde` — voor code die de databank toch al open heeft
    (bv. `scenario.batterij`)."""

    def test_geeft_tijdstip_en_gewicht_terug(self):
        conn = _NepConn([
            ("2026-01-01T00:00:00+00:00", 0.5),
            ("2026-01-01T00:15:00+00:00", 0.5),
        ])
        gewichten = gewichten_uit_databank(conn, "slp_ex", 2026, "elektriciteit")
        assert list(gewichten.columns) == ["tijdstip", "gewicht"]
        assert len(gewichten) == 2

    def test_leeg_resultaat_is_een_fout(self):
        conn = _NepConn([])
        with pytest.raises(SchattingError, match="Geen slp_ex-profiel"):
            gewichten_uit_databank(conn, "slp_ex", 2026)

    def test_meerdere_netbeheerders_zonder_filter_is_een_fout(self):
        """Twee waarden op hetzelfde tijdstip (twee netbeheerders) zonder
        `netbeheerder_code`-filter zou stil opgeteld worden — dat moet een
        fout zijn, geen verkeerd getal."""
        conn = _NepConn([
            ("2026-01-01T00:00:00+00:00", 0.5),
            ("2026-01-01T00:00:00+00:00", 0.3),
        ])
        with pytest.raises(SchattingError, match="per netbeheerder"):
            gewichten_uit_databank(conn, "rlp0n", 2026, "elektriciteit")

    def test_spp_heeft_geen_netbeheerderfilter_nodig(self):
        """SPP is geen genormaliseerd profiel; de vangrail hierboven geldt
        alleen voor SLP-EX/RLP0N."""
        conn = _NepConn([
            ("2026-01-01T00:00:00+00:00", 0.5),
            ("2026-01-01T00:15:00+00:00", 0.6),
        ])
        gewichten = gewichten_uit_databank(conn, "spp", 2026)
        assert len(gewichten) == 2

    def test_de_dubbele_winterurenwissel_is_geen_dubbele_netbeheerder(self):
        """De terugval naar wintertijd (laatste zondag van oktober) geeft
        twee échte, opeenvolgende UTC-uren die allebei als lokale klok
        '02:00' gelden. Kale Python-datetimevergelijking ziet die (bij
        gelijke tzinfo) ten onrechte als gelijk — `fold` wordt genegeerd bij
        `==`/`hash()` — en zou dit RLP0N-gasprofiel (nationaal, één rij per
        écht uur) laten doorgaan voor een per-netbeheerderprofiel. Gevonden
        tegen de echte databank: 8760 rijen, 8759 "unieke" tijdstippen volgens
        kale Python, 8760 unieke UTC-instanten in werkelijkheid."""
        conn = _NepConn([
            ("2026-10-25T00:00:00+00:00", 5.63127e-05),  # lokaal 02:00 CEST
            ("2026-10-25T01:00:00+00:00", 5.63127e-05),  # lokaal 02:00 CET
        ])
        gewichten = gewichten_uit_databank(conn, "rlp0n", 2026, "gas")
        assert len(gewichten) == 2
