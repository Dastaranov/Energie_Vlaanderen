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
