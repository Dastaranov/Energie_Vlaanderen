"""Tests voor het vervoerstarief aardgas (Fluxys).

Dit tarief staat in geen enkel VREG-werkboek — die dekken alleen de
distributie — en ontbrak daardoor volledig in dit repo. Op een gemiddeld
gezinsverbruik maakte dat elke gasfactuur ongeveer 25 EUR per jaar te laag.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal as D
from pathlib import Path

import pytest

from energie_vlaanderen.nettarieven.transport import (
    TransportTarief,
    TransportTariefError,
    TransportTariefRepository,
)

CONFIG_DIR = Path(__file__).resolve().parents[1] / "config" / "nettarieven"
PEILDATUM = date(2026, 8, 31)


@pytest.fixture(scope="module")
def repo() -> TransportTariefRepository:
    return TransportTariefRepository.load(CONFIG_DIR)


class TestMasterdata:
    def test_het_officiele_tarief_van_2026(self, repo):
        """CREG-nota (Z)3230 van 11/06/2026: 1,56 EUR/MWh excl. btw, uniform
        voor heel België sinds 01/01/2026.

        Onafhankelijk bevestigd op vtest.be, segment onderneming: vijf
        verbruikspunten, alle vijf exact gereproduceerd door 0,00156 EUR/kWh.
        """
        assert repo.eur_per_kwh("aardgas", "niet_zakelijk", PEILDATUM) == D("0.00156")

    def test_beide_klantcategorieen_delen_het_tarief(self, repo):
        """Het tarief is uniform; de scheiding bestaat om dezelfde
        categorienamen te kunnen gebruiken als config/heffingen/."""
        woning = repo.eur_per_kwh("aardgas", "niet_zakelijk", PEILDATUM)
        onderneming = repo.eur_per_kwh("aardgas", "zakelijk_laagspanning", PEILDATUM)

        assert woning == onderneming

    def test_het_tarief_is_geverifieerd(self, repo):
        assert repo.tarief("aardgas", "niet_zakelijk", PEILDATUM).geverifieerd

    def test_elke_geverifieerde_regel_noemt_haar_bron(self, repo):
        """Geverifieerd zonder bronvermelding laat een cijfer gecontroleerd
        lijken zonder dat na te gaan is waartegen."""
        zonder_bron = [
            t for t in repo.tarieven() if t.geverifieerd and not t.bron.strip()
        ]

        assert zonder_bron == []


class TestBerekening:
    def test_standaardprofiel_komt_overeen_met_vtest(self, repo):
        """vtest.be rekent voor zijn standaardwoning met 16.262 kWh aardgas.

        Het sociaal tarief daar toont 25,37 EUR vervoerstarief — precies
        16,262 x 1,56.
        """
        kost = repo.kost_per_jaar(
            "aardgas", "niet_zakelijk", D("16262"), PEILDATUM
        )

        assert kost.quantize(D("0.01")) == D("25.37")

    @pytest.mark.parametrize(
        ("kwh", "verwacht"),
        [
            ("4000", "6.24"),
            ("11900", "18.56"),
            ("12100", "18.88"),
            ("20000", "31.20"),
            ("35000", "54.60"),
        ],
    )
    def test_alle_gekalibreerde_meetpunten(self, repo, kwh, verwacht):
        """De vijf verbruikspunten uit de kalibratie van segment onderneming."""
        kost = repo.kost_per_jaar(
            "aardgas", "zakelijk_laagspanning", D(kwh), PEILDATUM
        )

        assert kost.quantize(D("0.01")) == D(verwacht)

    def test_het_tarief_is_vlak(self, repo):
        """Geen knik, ook niet op de 12 MWh-grens waar de accijns wél knikt."""
        onder = repo.kost_per_jaar("aardgas", "niet_zakelijk", D("11900"), PEILDATUM)
        boven = repo.kost_per_jaar("aardgas", "niet_zakelijk", D("12100"), PEILDATUM)

        assert (boven - onder) / D("200") == repo.eur_per_kwh(
            "aardgas", "niet_zakelijk", PEILDATUM
        )


class TestOntbrekendeData:
    def test_datum_voor_de_masterdata_faalt_hard(self, repo):
        """Liever stoppen dan met een tarief rekenen dat toen niet gold."""
        with pytest.raises(TransportTariefError, match="2026-01-01"):
            repo.tarief("aardgas", "niet_zakelijk", date(2025, 6, 1))

    def test_onbekende_energievorm_faalt_hard(self, repo):
        """Elektriciteit heeft dit gat niet: het transporttarief van Elia zit
        al in de ODV-post van het distributiewerkboek."""
        with pytest.raises(TransportTariefError, match="elektriciteit"):
            repo.tarief("elektriciteit", "niet_zakelijk", PEILDATUM)

    def test_onbekende_klantcategorie_faalt_hard(self, repo):
        with pytest.raises(TransportTariefError, match="hoogspanning"):
            repo.tarief("aardgas", "zakelijk_hoogspanning", PEILDATUM)

    def test_lege_configmap_faalt_hard(self, tmp_path):
        with pytest.raises(TransportTariefError, match="Geen vervoerstarief"):
            TransportTariefRepository.load(tmp_path)


class TestRegimes:
    def _repo(self, *tarieven: TransportTarief) -> TransportTariefRepository:
        return TransportTariefRepository(tarieven)

    def _tarief(self, vanaf: date, prijs: str) -> TransportTarief:
        return TransportTarief(
            energievorm="aardgas",
            klantcategorie="niet_zakelijk",
            eur_per_kwh=D(prijs),
            geldig_vanaf=vanaf,
            geverifieerd=True,
            bron="testfixture",
        )

    def test_het_meest_recente_regime_wint(self):
        repo = self._repo(
            self._tarief(date(2024, 1, 1), "0.00140"),
            self._tarief(date(2026, 1, 1), "0.00156"),
        )

        assert repo.eur_per_kwh(
            "aardgas", "niet_zakelijk", date(2026, 6, 1)
        ) == D("0.00156")

    def test_een_oudere_peildatum_krijgt_het_oudere_regime(self):
        repo = self._repo(
            self._tarief(date(2024, 1, 1), "0.00140"),
            self._tarief(date(2026, 1, 1), "0.00156"),
        )

        assert repo.eur_per_kwh(
            "aardgas", "niet_zakelijk", date(2025, 6, 1)
        ) == D("0.00140")

    def test_een_toekomstig_regime_geldt_nog_niet(self):
        repo = self._repo(
            self._tarief(date(2026, 1, 1), "0.00156"),
            self._tarief(date(2027, 1, 1), "0.00170"),
        )

        assert repo.eur_per_kwh(
            "aardgas", "niet_zakelijk", date(2026, 12, 31)
        ) == D("0.00156")
