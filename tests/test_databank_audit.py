"""De inhoudscontrole op de databank.

Deze controle bestaat omdat 681 tests een kolom die op 25.937 rijen leeg was
niet vonden: 644 ervan raken de databank niet, en de 37 die dat wél doen
schrijven eerst hun eigen CSV van een paar rijen, importeren die in een
teruggerolde transactie en toetsen dan díé rijen. De werkelijke dataset werd
nooit bekeken.

De tests hieronder zijn daarom bewust van twee soorten: de eerste klasse toetst
de beslisregel zonder databank (en draait dus in CI), de tweede legt de échte
databank tegen die regel (en wordt in CI overgeslagen). Alleen de tweede zou de
oorspronkelijke fout gevonden hebben — vandaar dat dezelfde controle ook als
`energievergelijker db audit` in de pipeline zit en niet enkel in pytest.
"""
from __future__ import annotations

import pytest

from energie_vlaanderen.audit.databank import Bevinding, DatabankRapport


class TestErnst:
    """Fout betekent: de import is stuk. Waarschuwing: de bron levert het niet."""

    def _b(self, ernst: str) -> Bevinding:
        return Bevinding(tabel="t", regel="r", melding="m", ernst=ernst)

    def test_zonder_bevindingen_is_geslaagd(self):
        rapport = DatabankRapport(bevindingen=())
        assert rapport.geslaagd
        assert rapport.geslaagd_streng()

    def test_een_fout_laat_de_poort_falen(self):
        rapport = DatabankRapport(bevindingen=(self._b("fout"),))
        assert not rapport.geslaagd
        assert not rapport.geslaagd_streng()

    def test_een_waarschuwing_alleen_faalt_niet(self):
        """Een poort die permanent rood staat wordt uitgezet — en mist dan ook
        de dag dat er echt iets breekt. Zeven producten waarvoor VREG geen
        energiecomponent publiceert horen een gezonde dataset niet te blokkeren.
        """
        rapport = DatabankRapport(bevindingen=(self._b("waarschuwing"),))
        assert rapport.geslaagd
        assert not rapport.geslaagd_streng(), "met --streng telt ze wel mee"

    def test_fouten_en_waarschuwingen_zijn_gescheiden(self):
        rapport = DatabankRapport(
            bevindingen=(self._b("fout"), self._b("waarschuwing"), self._b("fout"))
        )
        assert len(rapport.fouten) == 2
        assert len(rapport.waarschuwingen) == 1

    def test_standaardernst_is_fout(self):
        """Een nieuwe controle is streng tenzij ze bewust milder gezet wordt."""
        assert Bevinding(tabel="t", regel="r", melding="m").ernst == "fout"


@pytest.mark.integration
class TestTegenDeEchteDatabank:
    """Het soort test dat er niet was.

    Deze legt de dataset zoals ze er werkelijk bij staat tegen wat een
    berekening nodig heeft. Ze zou de lege `energieprijs_kwh` op dag één
    gevonden hebben.
    """

    def test_de_databank_bevat_wat_een_berekening_nodig_heeft(self, db_conn):
        from energie_vlaanderen.audit.databank import DatabankAudit

        rapport = DatabankAudit(db_conn).run()
        assert rapport.geslaagd, "\n".join(
            f"[{b.tabel}] {b.regel}: {b.melding}" for b in rapport.fouten
        )

    def test_de_energievorm_is_overal_hetzelfde_geschreven(self, db_conn):
        """"Elektriciteit" naast "elektriciteit" liet een join stil nul rijen
        opleveren. Migratie 0020 legt kleine letters vast met een CHECK."""
        import sqlalchemy as sa

        for tabel in ("energie_product", "vtest_contract", "netbeheerder_tarief"):
            waarden = {
                str(r[0]) for r in db_conn.execute(
                    sa.text(f"select distinct energie_type from {tabel} "  # noqa: S608
                            "where energie_type is not null")
                )
            }
            assert waarden <= {"elektriciteit", "gas"}, f"{tabel}: {waarden}"

    def test_de_join_tussen_producten_en_nettarieven_levert_rijen(self, db_conn):
        """De concrete gevolgtrekking: vóór 0020 gaf deze join nul producten."""
        import sqlalchemy as sa

        aantal = db_conn.execute(sa.text("""
            select count(distinct p.id) from energie_product p
            join netbeheerder_tarief n on n.energie_type = p.energie_type
        """)).scalar()
        assert aantal and aantal > 0


def _db_conn_fixture():
    """De fixture uit test_db_importer.py hergebruiken."""


pytest_plugins = ()


@pytest.mark.integration
class TestVtestTegenWerkboek:
    """De vtest-waarden in de databank, tegen het bronwerkboek.

    Dit is de controle die overeind moest blijven toen de CSV-weg verdween. Het
    werkboek is de onafhankelijke bron; welke kant ermee vergeleken wordt is een
    implementatiekeuze, en die is verhuisd van het CSV naar de databank.

    Bewust op sleutel en niet op positie. De databank draagt de vtest-data in
    brede vorm (één rij per meterregister, componenten als kolom), het werkboek
    in lange vorm (één rij per component). De rijaantallen verschillen dus per
    definitie — en juist bij ongelijke aantallen liep de oude positievergelijking
    uit de pas: 2.220 gemelde verschillen waarvan er geen enkele echt was.
    """

    VERSIE = "20260903T172618Z-f82afd0a"

    def _werkboek(self):
        from pathlib import Path

        pad = Path(__file__).resolve().parents[1] / "data" / "raw" / self.VERSIE / "vtest.xlsx"
        if not pad.is_file():
            pytest.skip("Het V-testwerkboek van deze versie ontbreekt lokaal.")
        return pad

    def test_de_databank_komt_overeen_met_het_werkboek(self, db_conn):
        from energie_vlaanderen.audit.databank import vtest_tegen_werkboek

        resultaat = vtest_tegen_werkboek(db_conn, self._werkboek())
        assert resultaat.verified_rows > 0, "er is niets vergeleken"
        assert resultaat.passed, "\n".join(
            f"{m.row_key} {m.field}: werkboek {m.xlsx_value} vs databank {m.csv_value}"
            for m in resultaat.mismatches[:10]
        )

    def test_de_vaste_vergoeding_behoudt_haar_decimalen(self, db_conn):
        """`vaste_vergoeding_jaar` stond op Numeric(10, 2) terwijl elke andere
        prijskolom er zes heeft. 61,321 werd stil 61,32 — bij 4.631 rijen, en
        het maakte een exacte audit op die kolom onmogelijk. Migratie 0022
        verbreedde de kolom; een tolerantie inbouwen zou de kolom juist
        onbewaakt hebben gelaten.
        """
        import sqlalchemy as sa

        met_decimalen = db_conn.execute(sa.text("""
            select count(*) from tarief_afname
             where vaste_vergoeding_jaar is not null
               and vaste_vergoeding_jaar <> round(vaste_vergoeding_jaar, 2)
        """)).scalar()
        assert met_decimalen > 0, (
            "Geen enkele vaste vergoeding draagt meer dan twee decimalen; "
            "de precisie is vermoedelijk opnieuw weggerond."
        )


class TestGoldenBinnenDeTransactie:
    """De controle tegen het bronwerkboek staat binnen de importtransactie.

    Ze stond vroeger ervóór, als aparte stap op de gestagede CSV's. Zonder die
    bestanden is er vóór de import niets om tegen te vergelijken: de
    tarieftabellen zijn cumulatief, dus data bestaat pas zodra ze ingevoegd is.

    Binnen de transactie is dat geen bezwaar maar een verbetering. `audit
    golden` was een losse stap die je gewoon kon overslaan — je kon publiceren
    zonder haar ooit te draaien, net zoals `audit approve` ooit niets afdwong.
    Nu rolt een afwijking de import terug en blijft er niets van over.
    """

    def test_de_import_kent_de_werkboekcontrole(self):
        import inspect

        from energie_vlaanderen.cli.db import import_version_into_db

        params = inspect.signature(import_version_into_db).parameters
        assert "golden_werkboeken" in params
        assert "droogloop" in params

    def test_zonder_werkboeken_draait_de_controle_niet(self):
        """En dat hoort zichtbaar te zijn, niet stil. `_werkboeken_voor_golden`
        waarschuwt wanneer het raw-manifest ontbreekt; stil overslaan zou een
        publicatie laten doorgaan zonder dat iemand het merkt — precies de fout
        die deze audit ooit zelf maakte toen ze op nul rijen "OK" meldde."""
        from pathlib import Path

        from energie_vlaanderen.cli.ingest import _werkboeken_voor_golden

        class _Paden:
            raw = Path("/bestaat/niet")

        assert _werkboeken_voor_golden(_Paden(), "20260101T000000Z-deadbeef") == {}

    def test_de_droogloop_rolt_terug_via_een_eigen_uitzondering(self):
        """De terugrol gebeurt door een uitzondering binnen de transactie, niet
        door achteraf te verwijderen. Verwijderen zou de SCD2-historiek niet
        kunnen herstellen: een afgesloten periode blijft afgesloten."""
        from energie_vlaanderen.cli.db import _Droogloop

        fout = _Droogloop(["a", "b"])
        assert fout.resultaten == ["a", "b"]
        assert isinstance(fout, Exception)
