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
    "meterinterval", "simulatie",
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

    def test_marktcurve_zit_er_niet_in(self, inhoud):
        """70 MB, en alleen nodig voor dynamische contracten. Meenemen maakt de
        repo zwaar en CI traag."""
        assert "COPY public.marktcurve " not in inhoud

    def test_van_de_profielen_zit_alleen_het_gasdeel_erin(self, inhoud):
        """849.720 rijen passen niet in git; 8.760 wel, en zonder die 8.760 kan
        CI geen enkele gasfactuur berekenen.

        `gasaandeel_uit_rlp0()` weigert hard zonder RLP0N-gasprofiel, dus een
        dump zonder dat profiel laat elke gastest overslaan of crashen — wat ze
        ook deed tot de dump van september 2026. Het elektriciteitsprofiel is
        wat de tabel groot maakt (35.040 kwartieren x 24 netbeheerders) en dat
        blijft eruit.
        """
        assert "COPY public.verbruiksprofiel_waarde " in inhoud
        regels = [
            r for r in inhoud.splitlines()
            if "\trlp0n\t" in r and r.startswith(tuple("0123456789"))
        ]
        assert len(regels) == 8760, f"{len(regels)} profielrijen, verwacht 8.760"
        assert all("\tgas\t" in r for r in regels), (
            "Er staan elektriciteitsprofielen in de lichte dump; die maken haar "
            "honderd keer zo groot."
        )

    def test_de_dump_blijft_klein_genoeg_voor_git(self):
        omvang = DUMP.stat().st_size
        assert omvang < 2 * 1024 * 1024, f"{omvang / 1024:.0f} kB — te groot voor git"


class TestErWordtAlleenGewistWatDeDumpTerugzet:
    """Het veiligheidsslot op `lees_dump`.

    Het inlezen begint met TRUNCATE. Zolang dat álle bekende tabellen wiste,
    was een lichte dump op een volle databank een wisser: `marktcurve` staat er
    niet in en van `verbruiksprofiel_waarde` alleen het gasdeel, dus 265.080
    curverijen en 840.960 profielwaarden verdwenen zonder dat er iets voor
    terugkwam. Eén verkeerd gezette DB_HOST volstaat daarvoor.

    `_valideer_dump` leest het bestand toch al volledig (de gzip-CRC staat aan
    het einde), dus de tabelnamen komen uit diezelfde pas.
    """

    def test_de_validatie_noemt_de_tabellen_die_in_de_dump_staan(self):
        from energie_vlaanderen.infrastructure.db.dump import _valideer_dump

        if not DUMP.is_file():
            pytest.skip("referentie.sql.gz ontbreekt.")
        tabellen = _valideer_dump(DUMP)
        assert "tarief_afname" in tabellen
        assert "netbeheerder_tarief" in tabellen
        # Het gasdeel zit erin, dus de tabel wordt wél leeggemaakt — ze wordt
        # ook weer gevuld.
        assert "verbruiksprofiel_waarde" in tabellen
        # En deze staat er niet in, dus ze blijft ongemoeid.
        assert "marktcurve" not in tabellen

    def test_een_kop_op_een_blokgrens_wordt_niet_gemist(self, tmp_path):
        """De COPY-kop kan doormidden vallen tussen twee leesblokken.

        Wordt hij dan gemist, dan blijft die tabel staan terwijl de dump haar
        wél vult — dubbele rijen in plaats van een verse tabel.
        """
        from energie_vlaanderen.infrastructure.db.dump import (
            _BLOKGROOTTE,
            _valideer_dump,
        )

        kop = b"COPY public.tarief_afname (id, product_id) FROM stdin;\n"
        pad = tmp_path / "grens.sql.gz"
        with gzip.open(pad, "wb") as fh:
            # Vulling zodat de kop precies over de blokgrens heen loopt, met de
            # regelovergang er nog vóór: in een echte dump staat COPY altijd aan
            # het begin van een regel, en daar hangt de patroonherkenning aan.
            fh.write(b"-" * (_BLOKGROOTTE - len(kop) // 2 - 1) + b"\n")
            fh.write(kop)
            fh.write(b"1\t2\n\\.\n")
        assert "tarief_afname" in _valideer_dump(pad)


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


class TestEenKapotteDumpWistNiets:
    """Inlezen begon met een `TRUNCATE` in een eigen psql-aanroep, en die commit
    meteen. Was de gzip stuk of liep de restore vast, dan bleef de databank leeg
    achter: geen herstel maar een wisser, en de weg terug is een nieuwe dump van
    een databank die er niet meer is.

    Er zijn nu twee lagen. `_valideer_dump` decomprimeert het bestand volledig
    vóór er iets aangeraakt wordt — de CRC van een gzip staat achteraan, dus dat
    kan niet goedkoper. Daarna gaan leegmaken en vullen samen door één
    `psql --single-transaction`, zodat een fout halverwege terugrolt.

    Deze tests dekken de eerste laag; de tweede wordt in CI gedekt, waar
    `.github/workflows/databank.yml` een echte restore doet tegen postgres:16.
    """

    @staticmethod
    def _valideer(pad: Path):
        from energie_vlaanderen.infrastructure.db.dump import _valideer_dump

        return _valideer_dump(pad)

    def test_de_echte_zaaddump_wordt_aanvaard(self):
        if not DUMP.is_file():
            pytest.skip(f"{DUMP.name} ontbreekt.")
        self._valideer(DUMP)  # geen uitzondering

    def test_een_afgekapte_gzip_wordt_geweigerd(self, tmp_path):
        """Een download of kopieeractie die halverwege stopt."""
        if not DUMP.is_file():
            pytest.skip(f"{DUMP.name} ontbreekt.")
        from energie_vlaanderen.infrastructure.db.dump import DumpError

        ruw = DUMP.read_bytes()
        half = tmp_path / "half.sql.gz"
        half.write_bytes(ruw[: len(ruw) // 2])
        with pytest.raises(DumpError, match="beschadigd"):
            self._valideer(half)

    def test_een_omgeslagen_bit_wordt_geweigerd(self, tmp_path):
        """Stille corruptie op schijf. De gzip-CRC vangt dit."""
        if not DUMP.is_file():
            pytest.skip(f"{DUMP.name} ontbreekt.")
        from energie_vlaanderen.infrastructure.db.dump import DumpError

        ruw = bytearray(DUMP.read_bytes())
        ruw[len(ruw) // 2] ^= 0xFF
        stuk = tmp_path / "stuk.sql.gz"
        stuk.write_bytes(bytes(ruw))
        with pytest.raises(DumpError, match="beschadigd"):
            self._valideer(stuk)

    def test_een_bestand_dat_geen_gzip_is_wordt_geweigerd(self, tmp_path):
        from energie_vlaanderen.infrastructure.db.dump import DumpError

        pad = tmp_path / "tekst.sql.gz"
        pad.write_bytes(b"dit is gewone tekst")
        with pytest.raises(DumpError, match="beschadigd"):
            self._valideer(pad)

    def test_een_lege_gzip_wordt_geweigerd(self, tmp_path):
        from energie_vlaanderen.infrastructure.db.dump import DumpError

        pad = tmp_path / "leeg.sql.gz"
        with gzip.open(pad, "wb") as fh:
            fh.write(b"")
        with pytest.raises(DumpError, match="leeg"):
            self._valideer(pad)

    def test_een_geldige_gzip_zonder_data_wordt_geweigerd(self, tmp_path):
        """Het gemeenste geval: technisch in orde, maar hij vult niets.

        Een pg_dump die op een lege selectie draaide levert een geldig bestand
        met alleen `SET`-regels. Inlezen zou de tabellen leegmaken en er niets
        voor terugzetten — en niets zou falen.
        """
        from energie_vlaanderen.infrastructure.db.dump import DumpError

        pad = tmp_path / "zonder_data.sql.gz"
        with gzip.open(pad, "wb") as fh:
            fh.write(b"SET statement_timeout = 0;\nSET lock_timeout = 0;\n")
        with pytest.raises(DumpError, match="geen COPY-opdrachten"):
            self._valideer(pad)

    def test_een_sleutelwoord_op_de_blokgrens_wordt_gevonden(self, tmp_path):
        """De datacontrole leest in blokken van 1 MiB. Valt "COPY " precies op
        die grens, dan zou een naïeve controle hem missen en een geldige dump
        weigeren."""
        from energie_vlaanderen.infrastructure.db.dump import _BLOKGROOTTE

        pad = tmp_path / "grens.sql.gz"
        vulling = b"-- " + b"x" * (_BLOKGROOTTE - 5) + b"\n"
        with gzip.open(pad, "wb") as fh:
            fh.write(vulling + b"COPY leverancier (id) FROM stdin;\n1\n\\.\n")
        self._valideer(pad)  # geen uitzondering
