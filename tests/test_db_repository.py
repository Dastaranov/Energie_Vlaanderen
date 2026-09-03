"""De rekenengine gevoed uit de databank.

De regel die dit bestand bewaakt: **de berekening komt uit de code, de data uit
de databank.** `DbDataRepository` biedt hetzelfde oppervlak als
`DataRepository`, zodat `Calculator` en `Kostberekening` ongewijzigd blijven —
wisselt de bron, dan verandert er niets aan de rekenregels.

De tests zijn tweeledig, om dezelfde reden als bij `test_databank_audit.py`: de
vertaalregels zijn zonder databank te toetsen en draaien dus in CI, maar of de
twee bronnen werkelijk hetzelfde bedrag opleveren is alleen tegen de echte
dataset vast te stellen.
"""
from __future__ import annotations

from decimal import Decimal as D

from energie_vlaanderen.utility.normalizer import money

import pytest

from energie_vlaanderen.data.db_repository import DbDataRepository


class TestProductOpbouw:
    """De databank staat in brede vorm (één rij per register), `Product`
    verwacht de lange vorm (één sleutel per component). Die vertaling is de kern
    van deze klasse en is zonder databank te toetsen."""

    def _rij(self, **extra):
        basis = {
            "leverancier": "ENGIE", "product_naam": "Easy", "segment": "Woning",
            "energie_type": "elektriciteit", "prijs_type": "vast",
            "meter_type": "single", "energieprijs_kwh": None,
            "vaste_vergoeding_jaar": None, "groene_stroom_kwh": None,
            "wkk_kwh": None, "energiebijdrage_kwh": None,
            "bron_bestand": "master_vast.csv",
        }
        for letter in ("a", "b", "c", "d", "z"):
            basis[f"param_{letter}"] = None
        for letter in ("a", "b", "c", "d"):
            basis[f"index_naam_{letter}"] = None
            basis[f"index_waarde_{letter}"] = None
        basis.update(extra)
        return basis

    def _bouw(self, rijen):
        return DbDataRepository._bouw_product(
            rijen, year=2026, month=8, segment="Woning", energy="elektriciteit",
            direction="afname", leverancier="ENGIE", naam="Easy", prijs_type="vast",
        )

    def test_de_prijs_per_register_wordt_een_component(self):
        """Elk meterregister draagt zijn eigen energieprijs; die stond nooit in
        de databank omdat de import de registercodes oversloeg."""
        p = self._bouw([
            self._rij(meter_type="day", energieprijs_kwh=D("17.884")),
            self._rij(meter_type="night", energieprijs_kwh=D("12.626")),
        ])
        assert p.components["day"] == D("17.884")
        assert p.components["night"] == D("12.626")

    def test_de_formule_hoort_bij_het_eigen_register(self):
        """Bij "Bolt Variabel" staat de coëfficiënt van `single` in kolom a en
        die van `day` in kolom b, op twee verschillende rijen. Ze uit één rij
        lezen gaf elk register dezelfde vector."""
        p = self._bouw([
            self._rij(meter_type="single", param_a=D("0.11192"), param_z=D("1.51"),
                      index_naam_a="Q EPEX", index_waarde_a=D("97.07361")),
            self._rij(meter_type="day", param_b=D("0.11192"), param_z=D("1.51"),
                      index_naam_a="Q EPEX", index_waarde_a=D("97.07361")),
        ])
        assert p.formulas["single"]["a"] == D("0.11192")
        assert "b" not in p.formulas["single"]
        assert p.formulas["day"]["b"] == D("0.11192")
        assert p.formulas["single"]["index_A"] == {
            "name": "Q EPEX", "value": D("97.07361"),
        }

    def test_gedeelde_componenten_gelden_voor_het_hele_product(self):
        """Groene stroom en WKK hangen aan het product, niet aan een register."""
        p = self._bouw([
            self._rij(meter_type="single", groene_stroom_kwh=D("1.1"), wkk_kwh=D("0.42")),
            self._rij(meter_type="day", groene_stroom_kwh=D("1.1"), wkk_kwh=D("0.42")),
        ])
        assert p.components["green"] == D("1.1")
        assert p.components["wkk"] == D("0.42")

    def test_de_vaste_vergoeding_komt_van_het_enkelvoudige_register(self):
        """`Calculator.supplier_cost()` leest maar één `fixed_fee`. De rij van
        het enkelvoudige register is de juiste keuze: dat is wat een aansluiting
        zonder dag/nachtmeter betaalt. Bij Ebem "Groen B@sic+" is dat 70,75 en
        niet de 33,06 van het exclusief-nachttarief."""
        p = self._bouw([
            self._rij(meter_type="night", vaste_vergoeding_jaar=D("33.06")),
            self._rij(meter_type="single", vaste_vergoeding_jaar=D("70.75")),
        ])
        assert p.components["fixed_fee"] == D("70.75")

    def test_een_register_zonder_prijs_levert_geen_component(self):
        """De import maakt voor elke groep ook een `single`-rij aan wanneer de
        bron dat register niet kent. Die hoort leeg te blijven en niet als
        prijs 0 door te gaan — een tarief dat er is en 0 bedraagt is iets
        anders dan een tarief dat ontbreekt."""
        p = self._bouw([self._rij(meter_type="single", energieprijs_kwh=None)])
        assert "single" not in p.components


@pytest.mark.integration
class TestTegenDeEchteDatabank:
    def _repo(self, db_conn, jaar=2026):
        return DbDataRepository(db_conn, tariefjaar=jaar)

    def test_de_nettarieven_dragen_de_kolomnamen_die_calculator_leest(self, db_conn):
        """`Calculator.grid_cost()` filtert letterlijk op deze namen; de
        databank noemt ze anders en de vertaling hoort op de grens te staan."""
        dnb = self._repo(db_conn).dnb
        verwacht = {"Netbeheerder", "Klanttype", "Contracttype", "Tarieftype",
                    "Tariefdetail", "Tariefnotering", "Prijs_num"}
        assert verwacht <= set(dnb.columns)
        # Hoofdletter: de databank schrijft sinds migratie 0020 "afname".
        assert "Afname" in set(dnb["Contracttype"])

    def test_twee_tariefjaren_zijn_beschikbaar(self, db_conn):
        """Een factuur die de jaarwissel kruist heeft er twee nodig. Ze konden
        aanvankelijk niet naast elkaar bestaan: de SCD2-upsert weigerde een
        oudere jaargang na een nieuwere."""
        for jaar in (2025, 2026):
            assert len(self._repo(db_conn, jaar).dnb) > 0, f"tariefjaar {jaar}"

    def test_een_onbekend_tariefjaar_stopt_met_een_fout(self, db_conn):
        """Stil doorrekenen met het verkeerde jaar geeft een plausibel en fout
        bedrag; stoppen is hier het juiste gedrag (Manifest §12)."""
        from energie_vlaanderen.data.db_repository import DbDataRepositoryError

        with pytest.raises(DbDataRepositoryError, match="2019"):
            _ = self._repo(db_conn, 2019).dnb

    def test_de_netbeheerder_komt_uit_de_databank(self, db_conn):
        naam, code = self._repo(db_conn).dnb_for("9120")
        assert code == "FMV"
        assert "Fluvius" in naam

    def test_een_maand_uit_2025_is_nog_opvraagbaar(self, db_conn):
        """Waar de tijdas voor bedoeld is: een versiemap draagt één momentopname,
        de databank draagt elke maand apart."""
        producten = self._repo(db_conn).products(
            2026, 4, "Woning", energy="elektriciteit", direction="afname"
        )
        assert producten, "april 2026 hoort opvraagbaar te zijn"
        assert any(p.components or p.formulas for p in producten)


@pytest.mark.integration
class TestHerkomstVanTarieven:
    """Een tariefjaar bijladen is geen publicatie.

    `data_version` beschrijft één momentopname met precies één actieve versie;
    `netbeheerder_tarief` is cumulatief en draagt meerdere jaargangen naast
    elkaar — dat is wat een factuur over de jaarwissel herberekenbaar maakt.
    `version publish` gebruiken om aan de tarieven van 2025 te komen zou de
    actieve dataset terugzetten naar vorig jaar.

    De 2025-tarieven zaten er eerst in via een rechtstreekse functieaanroep: de
    data klopte, maar zonder `data_version`-rij en zonder herkomst op de rijen,
    en dus niet reproduceerbaar vanuit de bronnen.
    """

    def test_elke_tariefrij_draagt_haar_bronversie(self, db_conn):
        """Manifest: herkomst is verplicht op elke afgeleide waarde.
        `source_sheet`/`source_row` zeggen wáár in een werkboek, niet uit wélk."""
        import sqlalchemy as sa

        zonder = db_conn.execute(sa.text(
            "select count(*) from netbeheerder_tarief where bron_versie is null"
        )).scalar()
        assert zonder == 0, f"{zonder} tariefrijen zonder herkomst"

    def test_elke_bronversie_is_geregistreerd(self, db_conn):
        """De herkomst moet naar een bekende dataversie wijzen, anders legt ze
        niets vast."""
        import sqlalchemy as sa

        wees = db_conn.execute(sa.text("""
            select count(*) from netbeheerder_tarief t
             where t.bron_versie is not null
               and not exists (select 1 from data_version v
                                where v.version_id = t.bron_versie)
        """)).scalar()
        assert wees == 0

    def test_een_jaargang_bijladen_verzet_de_actieve_versie_niet(self, db_conn):
        """Precies één actieve versie, en dat blijft de recentste V-test-export."""
        import sqlalchemy as sa

        actief = db_conn.execute(sa.text(
            "select count(*) from data_version where geactiveerd_op is not null"
        )).scalar()
        assert actief == 1


@pytest.mark.integration
class TestKetenDatabankNaarBedrag:
    """De hele keten databank → berekening, met een verzonnen dossier.

    Deze test bestaat omdat de sterkste bewaking die dit project heeft — de
    referentiefactuur nagerekend uit de databank — in CI overslaat: ze leest
    `gebruiker.toml`, en dat draagt EAN, adres en meterstanden en staat terecht
    niet in git. Van de 52 integratietests sloegen er daardoor 9 over, en dat
    waren net de negen die de volle keten aflegden.

    `tests/fixturen/dossiers/synthetisch_woning.toml` vult dat gat: verzonnen
    waarden, geen persoonsgegevens, en een periode die de jaarwissel kruist
    zodat beide tariefjaren nodig zijn.

    De uitkomst is géén factuurreconstructie — de volumes zijn verzonnen. Wat ze
    bewijst is dat de databank prijzen, formules, nettarieven van twee
    jaargangen en heffingen draagt en dat daar een bedrag uit komt. Met lege
    prijskolommen stopt de berekening met "Vast product mist afnameprijs".
    """

    @pytest.fixture
    def resultaat(self, db_conn):
        from datetime import date
        from pathlib import Path

        from energie_vlaanderen.gebruikers.berekening import Kostberekening
        from energie_vlaanderen.gebruikers.models import EnergieType
        from energie_vlaanderen.gebruikers.toml_io import lees_dossier
        from energie_vlaanderen.heffingen.repository import HeffingenRepository

        root = Path(__file__).resolve().parents[1]
        dossier_pad = root / "tests" / "fixturen" / "dossiers" / "synthetisch_woning.toml"
        if not dossier_pad.is_file():
            pytest.skip(f"{dossier_pad.name} ontbreekt.")

        repos = {jaar: DbDataRepository(db_conn, tariefjaar=jaar) for jaar in (2025, 2026)}
        for jaar, repo in repos.items():
            if len(repo.dnb) == 0:
                pytest.skip(f"Geen nettarieven voor {jaar} in de databank.")

        heffingen = HeffingenRepository.load(root / "config" / "heffingen")
        dossier = lees_dossier(
            dossier_pad, project_root=root, netbeheerders=repos[2026].netbeheerders
        )
        punt = dossier.punt(EnergieType.ELEKTRICITEIT)
        return Kostberekening(
            repos[2026], heffingen,
            segment=str(dossier.gebruiker.segment),
            nettarieven_per_jaar=repos,
        ).bereken(
            punt, dossier.meter_van(punt), dossier.contracten_van(punt),
            dossier.opgaven_van(punt),
            date(2025, 11, 1), date(2026, 3, 1),
            extra_aannames=dossier.aannames,
        )

    def test_er_komt_een_leverancierskost_uit(self, resultaat):
        """De assertie waar het om draait.

        `energieprijs_kwh` stond een week lang leeg op alle 25.937 tariefrijen.
        Met die toestand stopt deze berekening met "Vast product mist
        afnameprijs" — nagegaan door de kolommen in een teruggerolde transactie
        leeg te maken.
        """
        assert resultaat.totalen["supplier"] > D("0"), (
            "Geen leverancierskost. Draagt de databank de energieprijzen? "
            "Controleer met: energievergelijker db audit"
        )

    def test_de_leverancierskost_is_van_de_juiste_grootteorde(self, resultaat):
        """Een bandbreedte en geen vast bedrag: een exacte waarde zou wijzigen
        zodra de zaaddump ververst wordt, en dan is de reflex "de assertie
        aanpassen tot het weer groen is" — precies wat hier nooit mag.

        1.600 kWh bij een gangbaar vast tarief plus vaste vergoeding ligt
        ruwweg tussen 10 en 35 c€/kWh alles inbegrepen.
        """
        per_kwh = resultaat.totalen["supplier"] / D("1600") * D("100")
        assert D("10") < per_kwh < D("35"), f"{per_kwh:.2f} c€/kWh"

    def test_de_heffingen_zijn_exact_af_te_leiden(self, resultaat):
        """79,05 EUR = 1,6 MWh x (47,4811 bijzondere accijns + 1,9261 bijdrage
        op de energie), het regime dat op 01/07/2023 inging en tot 01/08/2026
        liep. Anders dan de leverancierskost hangt dit niet aan de zaaddump maar
        aan `config/heffingen/`, dus hier kan een exact bedrag staan.
        """
        assert money(resultaat.totalen["levies"]) == D("79.05")

    def test_de_periode_splitst_op_de_jaarwissel(self, resultaat):
        """Twee deelperiodes, dus beide tariefjaren zijn gebruikt. Ze konden
        aanvankelijk niet naast elkaar in de databank staan: de SCD2-upsert
        weigerde een oudere jaargang na een nieuwere."""
        from datetime import date

        assert len(resultaat.regels) == 2
        assert resultaat.regels[1].periode.van == date(2026, 1, 1)

    def test_er_komt_een_netkost_uit(self, resultaat):
        """`grid_cost()` gaf ooit stil 0,00 EUR terug wanneer elke lookup miste.
        Een digitale meter in Beveren zat daarmee gratis op het net."""
        assert resultaat.totalen["grid"] > D("0")
