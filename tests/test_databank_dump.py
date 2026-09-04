"""De zaaddump: klein genoeg voor git, groot genoeg om mee te rekenen.

Ze bestaat om de integratietests in CI te laten draaien. Die draaiden nooit —
ze hebben PostgreSQL nodig en de testworkflow slaat ze over — en juist zij zijn
de enige die de databank tegen haar doel leggen. Daardoor kon `energieprijs_kwh`
op alle 25.937 tariefrijen leeg staan terwijl 681 tests groen bleven.

De tests hieronder draaien zonder databank en dus wél in CI: ze toetsen de
*selectie*, niet de inhoud.
"""
from __future__ import annotations

import gzip
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DUMP = ROOT / "tests" / "fixturen" / "databank" / "referentie.sql.gz"
MANIFEST = ROOT / "tests" / "fixturen" / "databank" / "manifest.json"

# De gebruikersfamilie. Deze tabellen dragen EAN, adres en meterstanden en
# horen niet in een dump die in git staat.
PERSOONSGEGEVENS = (
    "gebruiker", "gebruiker_persoonsgegeven", "aansluitingspunt", "meter",
    "installatie_asset", "leveringscontract", "verbruiksopgave", "toestemming",
    "meterinterval", "simulatie", "simulatie_regel",
)


pytestmark = pytest.mark.databank


@pytest.fixture(scope="module")
def inhoud() -> str:
    if not DUMP.is_file():
        pytest.skip(f"{DUMP.name} ontbreekt.")
    with gzip.open(DUMP, "rt", encoding="utf-8", errors="replace") as fh:
        return fh.read()


class TestGeenPersoonsgegevens:
    def test_geen_enkele_gebruikerstabel_staat_in_de_dump(self, inhoud):
        """Het is een selectie, geen anonimisering.

        De gebruikersfamilie staat niet in `REFERENTIE_TABELLEN` en komt er dus
        niet in. Dat is een sterkere garantie dan scrubben: er valt niets te
        vergeten wat er niet in gaat. Manifest §5.2 noemt de EAN gevoelig.
        """
        gevonden = [t for t in PERSOONSGEGEVENS if f"COPY public.{t} " in inhoud]
        assert not gevonden, f"persoonsgegevens in de dump: {gevonden}"

    def test_de_dump_bevat_geen_ean(self, inhoud):
        """Een EAN18 begint met 54144 (België). Een tweede net, mocht een
        tabel ooit verhuizen tussen de families."""
        import re

        assert not re.search(r"\b54144\d{13}\b", inhoud)


class TestBruikbaarheid:
    def test_de_dump_draagt_de_tabellen_om_mee_te_rekenen(self, inhoud):
        """Zonder deze vier valt er geen factuur te berekenen."""
        for tabel in ("tarief_afname", "netbeheerder_tarief",
                      "gemeente", "overheidsheffing_accijns_schijf"):
            assert f"COPY public.{tabel} " in inhoud, tabel

    def test_de_zware_tabellen_zitten_er_niet_in(self, inhoud):
        """`marktcurve` is 70 MB en `verbruiksprofiel_waarde` 374 MB, tegenover
        ~7 MB voor al de rest. Ze meenemen maakt de repo zwaar en CI traag; ze
        zijn alleen nodig voor dynamische contracten en verbruiksschatting."""
        for tabel in ("marktcurve", "verbruiksprofiel_waarde"):
            assert f"COPY public.{tabel} " not in inhoud, tabel

    def test_de_dump_blijft_klein_genoeg_voor_git(self):
        omvang = DUMP.stat().st_size
        assert omvang < 2 * 1024 * 1024, f"{omvang / 1024:.0f} kB — te groot voor git"


class TestManifest:
    def test_het_manifest_legt_de_herkomst_vast(self):
        """Zonder herkomst is een dump een bestand zonder betekenis: je weet
        niet bij welke code hij hoort en niet waaruit hij gemaakt is."""
        if not MANIFEST.is_file():
            pytest.skip("manifest.json ontbreekt.")
        m = json.loads(MANIFEST.read_text(encoding="utf-8"))
        assert m["alembic_revisie"]
        assert m["actieve_dataversie"]
        assert m["met_zware_tabellen"] is False
        assert m["rijen"]["tarief_afname"] > 0

    def test_het_manifest_noemt_geen_gebruikerstabellen(self):
        if not MANIFEST.is_file():
            pytest.skip("manifest.json ontbreekt.")
        m = json.loads(MANIFEST.read_text(encoding="utf-8"))
        assert not (set(m["rijen"]) & set(PERSOONSGEGEVENS))
