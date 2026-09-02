"""Tests voor de validatie van verbruiksprofielen.

Aanleiding: `docs/manifest.md` §4.4 eist dat profielgewichten per periode
sommeren tot één. Deze tests verifiëren dat de validator dat afdwingt als
harde fout (niet voor SPP, dat geen verdeling maar een productiefractie is),
dat een verkeerd aantal intervallen wordt opgemerkt, en dat een bekende
eigenaardigheid in de brondata — twee kolommen met exact dezelfde GLN-code —
correct wordt afgehandeld (stil genegeerd bij gelijke waarden, harde fout bij
een tegenstrijdigheid).
"""

from __future__ import annotations

from energie_vlaanderen.ingest.profielen.validator import ProfielenValidator
from energie_vlaanderen.ingest.profielen.workbook import ProfielRow


def _rij(tijdstip: str, waarde: float | None, gln: str | None = None, naam: str | None = None) -> ProfielRow:
    return ProfielRow(
        tijdstip=tijdstip,
        netbeheerder_gln=gln,
        netbeheerder_naam=naam,
        waarde=waarde,
        source_sheet="TEST",
    )


class TestSomTotEen:
    def test_slp_ex_som_precies_een_is_geldig(self):
        # 4 kwartieren i.p.v. de echte 35.040 — de intervaltelling wordt
        # apart getest, hier gaat het enkel om de somcontrole.
        rows = [
            _rij("2027-01-01T00:00:00", 0.25),
            _rij("2027-01-01T00:15:00", 0.25),
            _rij("2027-01-01T00:30:00", 0.25),
            _rij("2027-01-01T00:45:00", 0.25),
        ]
        validator = ProfielenValidator()
        # jaar 2027 heeft 35.040 kwartieren; met 4 rijen faalt de
        # intervaltelling sowieso, dus die controle bewust overslaan door
        # de verwachte-aantal-methode direct te toetsen op de somlogica.
        report = validator.validate(rows, profiel_type="slp_ex", energie_type=None, jaar=2027)
        somfouten = [i for i in report.errors if i.code == "sum_not_one"]
        assert somfouten == []

    def test_afwijkende_som_is_een_harde_fout(self):
        rows = [
            _rij("2027-01-01T00:00:00", 0.5),
            _rij("2027-01-01T00:15:00", 0.5),
            _rij("2027-01-01T00:30:00", 0.5),
        ]
        validator = ProfielenValidator()
        report = validator.validate(rows, profiel_type="slp_ex", energie_type=None, jaar=2027)
        assert not report.valid
        assert any(i.code == "sum_not_one" for i in report.errors)

    def test_spp_wordt_niet_op_som_tot_een_gecontroleerd(self):
        """SPP is productie per kWp, geen verdeling — een som van 1000+ is normaal."""
        rows = [_rij("2027-01-01T00:00:00", 1000.0)]
        validator = ProfielenValidator()
        report = validator.validate(rows, profiel_type="spp", energie_type=None, jaar=2027)
        assert not any(i.code == "sum_not_one" for i in report.errors)


class TestIntervaltelling:
    def test_juist_aantal_kwartieren_voor_een_gewoon_jaar(self):
        # 35.040 rijen genereren zou de test traag maken; test in plaats
        # daarvan rechtstreeks de rekenregel.
        verwacht = ProfielenValidator._verwacht_aantal_intervallen("slp_ex", None, 2027)
        assert verwacht == 35040

    def test_schrikkeljaar_heeft_een_kwartier_meer_per_dag_extra(self):
        verwacht = ProfielenValidator._verwacht_aantal_intervallen("slp_ex", None, 2028)
        assert verwacht == 35136

    def test_rlp0n_gas_is_uurresolutie(self):
        assert ProfielenValidator._verwacht_aantal_intervallen("rlp0n", "gas", 2027) == 8760
        assert ProfielenValidator._verwacht_aantal_intervallen("rlp0n", "gas", 2028) == 8784

    def test_verkeerd_aantal_rijen_is_een_harde_fout(self):
        rows = [_rij("2027-01-01T00:00:00", 1.0)]
        validator = ProfielenValidator()
        report = validator.validate(rows, profiel_type="slp_ex", energie_type=None, jaar=2027)
        fouten = [i for i in report.errors if i.code == "interval_count"]
        assert len(fouten) == 1
        assert "35040" in fouten[0].message


class TestDubbeleGln:
    def test_identieke_dubbele_gln_kolommen_worden_stil_genegeerd(self):
        rows = [
            _rij("2027-01-01T00:00:00", 0.001, gln="123", naam="AIEG"),
            _rij("2027-01-01T00:00:00", 0.001, gln="123", naam="AIEG"),
        ]
        validator = ProfielenValidator()
        report = validator.validate(rows, profiel_type="rlp0n", energie_type="elektriciteit", jaar=2027)
        assert not any(i.code == "duplicate_gln_conflict" for i in report.errors)

    def test_tegenstrijdige_dubbele_gln_kolommen_is_een_harde_fout(self):
        rows = [
            _rij("2027-01-01T00:00:00", 0.001, gln="123", naam="AIEG"),
            _rij("2027-01-01T00:00:00", 0.002, gln="123", naam="AIEG"),
        ]
        validator = ProfielenValidator()
        report = validator.validate(rows, profiel_type="rlp0n", energie_type="elektriciteit", jaar=2027)
        assert not report.valid
        assert any(i.code == "duplicate_gln_conflict" for i in report.errors)


class TestLegeInvoer:
    def test_geen_rijen_is_een_harde_fout(self):
        validator = ProfielenValidator()
        report = validator.validate([], profiel_type="slp_ex", energie_type=None, jaar=2027)
        assert not report.valid
        assert report.errors[0].code == "empty"
