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
    def test_het_woningtarief_volgt_vtest_en_niet_de_creg_nota(self, repo):
        """1,5565 EUR/MWh — wat vtest.be werkelijk toepast, niet wat CREG publiceert.

        CREG-nota (Z)3230 van 11/06/2026 legt 1,56 EUR/MWh excl. btw vast,
        uniform voor heel België sinds 01/01/2026. Maar op woningproducten
        rekent vtest.be consistent 0,22% lager: 1,5565, over vijf
        verbruikspunten van 4.000 tot 35.000 kWh (kalibratie 2026-08-31). De
        oorzaak is onderzocht en niet gevonden.

        Keuze van 2026-09-01: vtest.be is hier de leidende bron, omdat deze
        toepassing vergelijkt met wat die tool een klant toont. Wijzigt dit
        cijfer bij een volgende kalibratie, dan is de eerste vraag of vtest.be
        zijn berekening veranderd heeft — niet of deze assertie mag verschuiven.
        """
        assert repo.eur_per_kwh("aardgas", "niet_zakelijk", PEILDATUM) == D("0.0015565")

    def test_onderneming_draagt_wel_het_creg_tarief(self, repo):
        """Het segment onderneming reproduceert 1,56 exact.

        Vijf verbruikspunten uit de kalibratie van 2026-08-31, alle vijf exact
        gereproduceerd door 0,00156 EUR/kWh. De afwijking zit dus uitsluitend
        op woningproducten.
        """
        assert repo.eur_per_kwh(
            "aardgas", "zakelijk_laagspanning", PEILDATUM
        ) == D("0.00156")

    def test_de_twee_categorieen_verschillen_maar_nauwelijks(self, repo):
        """Het verschil is 0,22% en hoort dat te blijven.

        Deze test bestaat om een tikfout te vangen: zou één van beide cijfers
        ooit een decimaal verschuiven, dan lopen ze veel verder uiteen dan de
        onverklaarde afwijking rechtvaardigt.
        """
        woning = repo.eur_per_kwh("aardgas", "niet_zakelijk", PEILDATUM)
        onderneming = repo.eur_per_kwh("aardgas", "zakelijk_laagspanning", PEILDATUM)

        assert woning < onderneming
        assert abs(woning - onderneming) / onderneming < D("0.01")

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

        Op een gewoon woningproduct toont vtest.be daar 25,31 EUR
        vervoerstarief: 16,262 x 1,5565.

        Het sociaal tarief op diezelfde pagina toont 25,37 EUR — dat rekent met
        1,56 exact. Sociale tarieven vallen nu onder dezelfde categorie
        `niet_zakelijk` en krijgen dus 6 cent per jaar te weinig; zodra ze
        apart doorgerekend worden, hoort daar een eigen categorie bij.
        """
        kost = repo.kost_per_jaar(
            "aardgas", "niet_zakelijk", D("16262"), PEILDATUM
        )

        assert kost.quantize(D("0.01")) == D("25.31")

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
