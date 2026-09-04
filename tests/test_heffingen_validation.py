"""Tests voor de structurele controle op de heffingen-masterdata.

Deze controle draait in CI bij elke commit, dus ze moet zelf betrouwbaar zijn:
een validator die een gat níet vindt, is erger dan geen validator.
"""

from __future__ import annotations

import pytest

from datetime import date
from decimal import Decimal as D

from energie_vlaanderen.heffingen.models import (
    AccijnsSchijf,
    AccijnsTabel,
    BtwTarief,
    EnergiefondsTarief,
)
from energie_vlaanderen.heffingen.repository import HeffingenRepository
from energie_vlaanderen.heffingen.validation import (
    controleer_accijns,
    controleer_dekking,
    controleer_energiefonds,
    controleer_transport,
)

INGANG = date(2026, 8, 1)


pytestmark = pytest.mark.masterdata


def _schijf(van: str, tot: str | None, *, tarief: str = "46", categorie: str = "wonen"):
    return AccijnsSchijf(
        klantcategorie=categorie,
        van_mwh=D(van),
        tot_mwh=None if tot is None else D(tot),
        accijns_eur_mwh=D("0"),
        bijzondere_accijns_eur_mwh=D(tarief),
        energiebijdrage_eur_mwh=D("0"),
        geldig_vanaf=INGANG,
        geverifieerd=True,
        # Een geverifieerde schijf hoort haar bron te noemen; zonder die
        # vermelding meldt de validatie terecht een fout.
        bron="testfixture",
    )


def _repo(*schijven: AccijnsSchijf, jaren: tuple[int, ...] = (2026, 2027)):
    return HeffingenRepository(
        accijns_tabellen={
            "elektriciteit": AccijnsTabel("elektriciteit", "test", tuple(schijven))
        },
        energiefonds=tuple(
            EnergiefondsTarief(jaar, "laag", "residentieel", D("0"), "test")
            for jaar in jaren
        ),
        btw=(BtwTarief("elektriciteit", D("0.06"), False, "2026-01-01", "test"),),
    )


def _fouten(bevindingen):
    return [b for b in bevindingen if b.ernst == "fout"]


class TestAccijnsStructuur:
    def test_sluitende_indeling_geeft_geen_fouten(self):
        repo = _repo(_schijf("0", "12"), _schijf("12", None))

        assert _fouten(controleer_accijns(repo)) == []

    def test_gat_tussen_schijven_wordt_gemeld(self):
        # Verbruik tussen 12 en 15 MWh zou onbelast blijven.
        repo = _repo(_schijf("0", "12"), _schijf("15", None))

        (fout,) = _fouten(controleer_accijns(repo))

        assert "Gat" in fout.bericht

    def test_overlap_tussen_schijven_wordt_gemeld(self):
        # Verbruik tussen 10 en 12 MWh zou dubbel belast worden.
        repo = _repo(_schijf("0", "12"), _schijf("10", None))

        fouten = _fouten(controleer_accijns(repo))

        assert any("Overlap" in f.bericht for f in fouten)

    def test_indeling_die_niet_bij_nul_begint_wordt_gemeld(self):
        repo = _repo(_schijf("3", None))

        (fout,) = _fouten(controleer_accijns(repo))

        assert "begint bij 3" in fout.bericht

    def test_ontbrekende_bovenschijf_wordt_gemeld(self):
        repo = _repo(_schijf("0", "12"))

        fouten = _fouten(controleer_accijns(repo))

        assert any("zonder bovengrens" in f.bericht for f in fouten)

    def test_ongeverifieerde_schijf_is_een_waarschuwing_geen_fout(self):
        onbevestigd = AccijnsSchijf(
            klantcategorie="wonen",
            van_mwh=D("0"),
            tot_mwh=None,
            accijns_eur_mwh=D("0"),
            bijzondere_accijns_eur_mwh=D("46"),
            energiebijdrage_eur_mwh=D("0"),
            geldig_vanaf=INGANG,
            geverifieerd=False,
        )
        bevindingen = controleer_accijns(_repo(onbevestigd))

        assert _fouten(bevindingen) == []
        assert any(b.ernst == "waarschuwing" for b in bevindingen)

    def test_regimes_worden_apart_beoordeeld(self):
        """Twee regimes mogen elk hun eigen schijfindeling hebben.

        Samen zouden ze op elkaar lijken te overlappen; dat is geen fout.
        """
        oud = AccijnsSchijf(
            klantcategorie="wonen",
            van_mwh=D("0"),
            tot_mwh=None,
            accijns_eur_mwh=D("0"),
            bijzondere_accijns_eur_mwh=D("47"),
            energiebijdrage_eur_mwh=D("0"),
            geldig_vanaf=date(2023, 7, 1),
            geverifieerd=True,
            bron="testfixture",
        )
        repo = _repo(oud, _schijf("0", "12"), _schijf("12", None))

        assert _fouten(controleer_accijns(repo)) == []


class TestEnergiefonds:
    def test_ontbrekend_tussenjaar_wordt_gemeld(self):
        repo = _repo(_schijf("0", None), jaren=(2024, 2026))

        (fout,) = _fouten(controleer_energiefonds(repo))

        assert "2025" in fout.bericht

    def test_aaneensluitende_jaren_geven_geen_fout(self):
        repo = _repo(_schijf("0", None), jaren=(2024, 2025, 2026))

        assert _fouten(controleer_energiefonds(repo)) == []


class TestDekking:
    # De peildatum ligt na INGANG, zodat enkel het energiefonds in beeld is.
    PEILDATUM = date(2026, 9, 1)

    def test_jaar_zonder_energiefondstarief_is_een_fout(self):
        repo = _repo(_schijf("0", None), jaren=(2024, 2025))

        fouten = _fouten(controleer_dekking(repo, self.PEILDATUM))

        assert any("2026" in f.bericht for f in fouten)

    def test_volgend_jaar_nog_niet_gekend_is_een_waarschuwing(self):
        repo = _repo(_schijf("0", None), jaren=(2025, 2026))

        bevindingen = controleer_dekking(repo, self.PEILDATUM)

        assert _fouten(bevindingen) == []
        assert any(b.ernst == "waarschuwing" for b in bevindingen)

    def test_datum_voor_het_eerste_accijnsregime_is_een_fout(self):
        """Beter hier melden dan een berekening laten stuklopen."""
        repo = _repo(_schijf("0", None), jaren=(2022, 2023))

        fouten = _fouten(controleer_dekking(repo, date(2022, 1, 1)))

        assert any("masterdata begint pas" in f.bericht for f in fouten)


def test_geverifieerd_zonder_bron_is_een_fout():
    """`geverifieerd = true` zonder bron laat een cijfer gecontroleerd lijken.

    Dat is dezelfde val als een test die een getal vastlegt zonder te zeggen
    waar het vandaan komt: de bewering krijgt gewicht dat ze niet verdient.
    """
    zonder_bron = AccijnsSchijf(
        klantcategorie="wonen",
        van_mwh=D("0"),
        tot_mwh=None,
        accijns_eur_mwh=D("0"),
        bijzondere_accijns_eur_mwh=D("46"),
        energiebijdrage_eur_mwh=D("0"),
        geldig_vanaf=INGANG,
        geverifieerd=True,
        bron="   ",
    )

    (fout,) = _fouten(controleer_accijns(_repo(zonder_bron)))

    assert "geen bron" in fout.bericht


def test_geverifieerd_met_bron_geeft_geen_bevinding():
    met_bron = AccijnsSchijf(
        klantcategorie="wonen",
        van_mwh=D("0"),
        tot_mwh=None,
        accijns_eur_mwh=D("0"),
        bijzondere_accijns_eur_mwh=D("46"),
        energiebijdrage_eur_mwh=D("0"),
        geldig_vanaf=INGANG,
        geverifieerd=True,
        bron="vtest.be kalibratie 2026-08-31, 7 verbruikspunten",
    )

    assert controleer_accijns(_repo(met_bron)) == []


class TestTransport:
    """Het vervoerstarief van Fluxys volgt dezelfde regels als de heffingen.

    Een ontbrekend vervoerstarief maakt elke gasfactuur ongeveer 25 EUR per
    jaar te laag, dus dat is een fout en geen waarschuwing.
    """

    def _schrijf(self, tmp_path, inhoud: str):
        (tmp_path / "transport_aardgas.toml").write_text(inhoud, encoding="utf-8")
        return tmp_path

    def test_geldige_masterdata_geeft_geen_bevindingen(self, tmp_path):
        map_ = self._schrijf(tmp_path, '''
energievorm = "aardgas"
bron = "CREG"
[[tarief]]
klantcategorie = "niet_zakelijk"
eur_per_kwh = "0.00156"
geldig_vanaf = "2026-01-01"
geverifieerd = true
bron = "CREG-nota (Z)3230"
''')

        assert controleer_transport(map_, date(2026, 6, 1)) == []

    def test_ontbrekend_bestand_is_een_fout(self, tmp_path):
        (fout,) = _fouten(controleer_transport(tmp_path, date(2026, 6, 1)))

        assert "Geen vervoerstarief" in fout.bericht

    def test_negatief_tarief_is_een_fout(self, tmp_path):
        map_ = self._schrijf(tmp_path, '''
energievorm = "aardgas"
bron = "test"
[[tarief]]
klantcategorie = "niet_zakelijk"
eur_per_kwh = "-0.001"
geldig_vanaf = "2026-01-01"
geverifieerd = true
bron = "test"
''')

        fouten = _fouten(controleer_transport(map_, date(2026, 6, 1)))

        assert any("niet positief" in f.bericht for f in fouten)

    def test_geverifieerd_zonder_bron_is_een_fout(self, tmp_path):
        map_ = self._schrijf(tmp_path, '''
energievorm = "aardgas"
bron = ""
[[tarief]]
klantcategorie = "niet_zakelijk"
eur_per_kwh = "0.00156"
geldig_vanaf = "2026-01-01"
geverifieerd = true
bron = "  "
''')

        fouten = _fouten(controleer_transport(map_, date(2026, 6, 1)))

        assert any("geen bron" in f.bericht for f in fouten)

    def test_peildatum_buiten_de_masterdata_is_een_fout(self, tmp_path):
        map_ = self._schrijf(tmp_path, '''
energievorm = "aardgas"
bron = "test"
[[tarief]]
klantcategorie = "niet_zakelijk"
eur_per_kwh = "0.00156"
geldig_vanaf = "2026-01-01"
geverifieerd = true
bron = "test"
''')

        fouten = _fouten(controleer_transport(map_, date(2025, 6, 1)))

        assert any("begint pas op" in f.bericht for f in fouten)
