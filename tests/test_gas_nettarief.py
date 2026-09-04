"""De distributienetkost voor aardgas, tegen de referentiefactuur.

Aardgas rekent anders dan elektriciteit, en het verschil zit niet in de
bedragen maar in de *soorten* grootheid. Drie ervan lopen door elkaar, en elk
ervan verkeerd toepassen geeft een plausibel maar fout bedrag:

- **de tariefgroep** volgt het *jaar*verbruik. Uit het VREG-werkboek, rij 7 van
  een "<DNB> GAS Afname"-blad: T1 "0 - 5 000", T2 "5 001 - 150 000",
  T3 "150 001 - 1 000 000", T4 "> 1 000 000". T5/T6 zijn telegemeten klanten —
  een metersoort, geen volgende schijf.
- **vaste term en databeheer** zijn jaarbedragen. Het werkboek is expliciet:
  "Voor de facturatie van de vaste term en het tarief databeheer worden de
  jaartarieven geproratiseerd over het aantal dagen die de gemeten periode
  bestrijkt."
- **de volumetrische termen** volgen het volume dat in de periode valt, en dat
  volume wordt over de tariefperiodes verdeeld met het RLP0-profiel — niet naar
  dagen. Ook dat staat in het werkboek: "Voor de effectief toe te passen
  tarieven dienen de gemeten kWh over de verschillende tariefperioden verdeeld
  te worden op basis van het reëel lastprofiel RLP0."

Dat laatste is geen detail. Gas is winterzwaar: van 25/06/2025 tot 30/04/2026
valt 53,8% van het volume in de 120 dagen van januari tot april, waar een
verdeling naar dagen 32,9% zou geven. De tarieven van 2026 liggen hoger dan die
van 2025, dus wie naar dagen verdeelt rekent structureel te weinig aan.

Alle bedragen hieronder komen van één betaalde ENGIE-eindafrekening
(factuurdatum 27/05/2026, Fluvius Midden-Vlaanderen, 12.181 kWh over 365 dagen).
"""
from __future__ import annotations

from decimal import Decimal as D
from pathlib import Path

import pytest

pytestmark = pytest.mark.rekenen

ROOT = Path(__file__).resolve().parents[1]


class TestTariefgroep:
    """De groep volgt het jaarverbruik, met de grenzen uit het werkboek."""

    @pytest.mark.parametrize("kwh,verwacht", [
        (D("0"), "GAS_T1"),
        (D("5000"), "GAS_T1"),        # "0 - 5 000", bovengrens inbegrepen
        (D("5001"), "GAS_T2"),        # "5 001 - 150 000"
        (D("12181"), "GAS_T2"),       # het verbruik van de referentiefactuur
        (D("150000"), "GAS_T2"),
        (D("150001"), "GAS_T3"),      # "150 001 - 1 000 000"
        (D("1000000"), "GAS_T3"),
        (D("1000001"), "GAS_T4"),     # "> 1 000 000"
    ])
    def test_de_grenzen_komen_uit_het_werkboek(self, kwh, verwacht):
        from energie_vlaanderen.calculation.calculator import Calculator

        assert Calculator.gas_tariefgroep(kwh) == verwacht

    def test_telegemeten_groepen_worden_niet_op_verbruik_gekozen(self):
        """T5 en T6 zijn een metersoort, geen schijf. Een grootverbruiker met
        een gewone meter hoort in T4 te vallen en niet in T5 — die twee dragen
        een capaciteitsterm die hier niet geldt."""
        from energie_vlaanderen.calculation.calculator import Calculator

        for kwh in (D("2000000"), D("50000000")):
            assert Calculator.gas_tariefgroep(kwh) == "GAS_T4"


@pytest.mark.integration
class TestTegenDeReferentiefactuur:
    """De vier gereguleerde gasposten, uit de databank en config/.

    Samen 327,78 EUR op de factuur. Wat er níét in zit: de energiecomponent
    (662,11, een contractprijs) en de kortingen (-190,10, contractueel en in
    geen publieke bron).
    """

    # RLP0N-gasprofiel 2026, aandeel van januari t/m april. Uit de databank
    # (`verbruiksprofiel_waarde`), niet met de hand ingevuld: de test rekent
    # het zelf uit zodat een gewijzigd profiel hier opvalt.
    VERBRUIK_KWH = D("12181")
    DAGEN_2025 = 245          # 2025-05-01 .. 2025-12-31
    DAGEN_2026 = 120          # 2026-01-01 .. 2026-04-30

    @pytest.fixture
    def rlp0_aandeel_2026(self, db_conn) -> D:
        import sqlalchemy as sa

        rij = db_conn.execute(sa.text("""
            select sum(case when extract(month from tijdstip at time zone 'Europe/Brussels')
                            between 1 and 4 then waarde else 0 end) as jan_apr,
                   sum(waarde) as totaal
              from verbruiksprofiel_waarde
             where energie_type = 'gas' and profiel_type = 'rlp0n' and jaar = 2026
        """)).mappings().one()
        if not rij["totaal"]:
            pytest.skip("Geen RLP0N-gasprofiel in de databank.")
        return D(str(float(rij["jan_apr"]) / float(rij["totaal"])))

    def test_het_profiel_is_winterzwaar(self, rlp0_aandeel_2026):
        """Zonder deze controle zou een vlak profiel de test hieronder laten
        slagen om de verkeerde reden."""
        naar_dagen = D(self.DAGEN_2026) / D("365")
        assert rlp0_aandeel_2026 > naar_dagen * D("1.5"), (
            f"RLP0 geeft {rlp0_aandeel_2026:.3f} voor jan-apr, naar dagen zou "
            f"{naar_dagen:.3f} zijn; het profiel lijkt vlak"
        )

    def test_de_distributiekost_komt_uit_op_de_factuur(self, db_conn, rlp0_aandeel_2026):
        from energie_vlaanderen.calculation.calculator import Calculator
        from energie_vlaanderen.data.db_repository import DbDataRepository
        from energie_vlaanderen.domain.models import Profile

        profiel = Profile(postcode="9300", gemeente="Aalst", segment="Woning",
                          meter="digitaal")
        totaal = D("0")
        for jaar, dagen, deel in (
            (2025, self.DAGEN_2025, D(1) - rlp0_aandeel_2026),
            (2026, self.DAGEN_2026, rlp0_aandeel_2026),
        ):
            repo = DbDataRepository(db_conn, tariefjaar=jaar)
            if len(repo.dnb) == 0:
                pytest.skip(f"Geen nettarieven voor {jaar} in de databank.")
            totaal += Calculator(repo).gas_grid_cost(
                profiel, self.VERBRUIK_KWH, self.VERBRUIK_KWH * deel, dagen=dagen
            )

        # 196,24 EUR op de factuur, als "distributiekosten".
        assert abs(totaal - D("196.24")) < D("0.10"), (
            f"berekend {totaal:.2f}, factuur 196,24"
        )



@pytest.mark.integration
class TestDeGasheffingen:
    """De bijdrage op de energie stond op nul, en dat was fout.

    Precies dezelfde fout als bij elektriciteit: vtest.be toont die post niet,
    maar dat is iets anders dan dat hij nul is. De afrekening rekent hem als
    aparte regel aan — 12,15 EUR op 12.181 kWh, afgedrukt als 0,9975 EUR/MWh.
    """

    def test_de_bijdrage_op_de_energie_is_niet_nul(self):
        from datetime import date

        from energie_vlaanderen.heffingen.repository import HeffingenRepository

        repo = HeffingenRepository.load(ROOT / "config" / "heffingen")
        _, bijdrage = repo.bereken_accijns_en_energiebijdrage(
            "aardgas", "niet_zakelijk", D("12181"), date(2025, 10, 1)
        )
        assert bijdrage > D("0"), (
            "de bijdrage op de energie voor aardgas stond op nul; de "
            "eindafrekening rekent hem wel degelijk aan"
        )
        assert abs(bijdrage - D("12.15")) < D("0.005"), (
            f"berekend {bijdrage}, factuur 12,15 EUR op 12.181 kWh "
            "(0,9975 EUR/MWh, afgedrukt op de eindafrekening)"
        )

    def test_de_bijzondere_accijns_komt_uit_op_de_factuur(self):
        from datetime import date

        from energie_vlaanderen.heffingen.repository import HeffingenRepository

        repo = HeffingenRepository.load(ROOT / "config" / "heffingen")
        accijns, _ = repo.bereken_accijns_en_energiebijdrage(
            "aardgas", "niet_zakelijk", D("12181"), date(2025, 10, 1)
        )
        # 100,39 EUR, afgedrukt als 8,2415 EUR/MWh. Vergelijken op de cent:
        # de engine rondt bewust pas op het eind af (Manifest §7), dus hier
        # staat 100,3897115.
        assert abs(accijns - D("100.39")) < D("0.005")

    def test_het_vervoerstarief_dekt_ook_2025(self):
        """De masterdata begon op 01/01/2026, waardoor een berekening over een
        periode die eerder start hard faalde — correct bij ontbrekende data,
        maar het maakte de referentiefactuur onberekenbaar."""
        from datetime import date

        from energie_vlaanderen.nettarieven.transport import TransportTariefRepository

        repo = TransportTariefRepository.load(ROOT / "config" / "nettarieven")
        tarief = repo.tarief("aardgas", "niet_zakelijk", date(2025, 10, 1))
        # 19,00 EUR op 12.181 kWh, afgedrukt als 1,5599 EUR/MWh.
        assert abs(tarief.eur_per_kwh * D("12181") - D("19.00")) < D("0.01")


class TestGeenStilleNul:
    """Manifest §12: een ontbrekend verplicht tarief stopt de berekening.

    Getoetst met een kale tarieftabel in plaats van via een postcode: de vraag
    is of `gas_grid_cost()` weigert wanneer de rij er niet is, en niet of een
    bepaalde gemeente toevallig ontbreekt in de databank.
    """

    class _Bron:
        """Een minimale `TariefBron` met precies de meegegeven rijen."""

        def __init__(self, rijen):
            import pandas as pd

            self.dnb = pd.DataFrame(rijen)
            self.tariefjaar = 2026

        def dnb_for(self, postcode, gemeente="", energie_type="elektriciteit"):
            return ("Fluvius Midden-Vlaanderen", "FMV")

        def products(self, *a, **k):
            return []

    @staticmethod
    def _rij(klanttype, detail, notering, prijs):
        return {
            "Netbeheerder": "FMV", "Klanttype": klanttype, "Contracttype": "Afname",
            "Tarieftype": None, "Tariefdetail": detail,
            "Tariefnotering": notering, "Prijs_num": prijs,
        }

    def _profiel(self):
        from energie_vlaanderen.domain.models import Profile

        return Profile(postcode="9300", gemeente="Aalst", segment="Woning",
                       meter="digitaal")

    def test_zonder_vaste_term_weigert_de_berekening(self):
        from energie_vlaanderen.calculation.calculator import Calculator

        bron = self._Bron([
            self._rij("GAS_T2", "Proportionele term", "EUR/kWh", 0.008117),
            self._rij("GAS_DBH_JAAROPNAME", "Jaaropname (…)", "EUR/jaar", 17.85),
        ])
        with pytest.raises(ValueError, match="Vaste term"):
            Calculator(bron).gas_grid_cost(self._profiel(), D("12181"), D("12181"))

    def test_zonder_databeheertarief_weigert_de_berekening(self):
        """De fout die migratie 0023 rechtzet: het tarief hing aan GAS_T1, dus
        een T2-gezin vond niets en betaalde stil 17,62 EUR te weinig."""
        from energie_vlaanderen.calculation.calculator import Calculator

        bron = self._Bron([
            self._rij("GAS_T2", "Vaste term", "EUR/jaar", 81.8),
            self._rij("GAS_T2", "Proportionele term", "EUR/kWh", 0.008117),
            self._rij("GAS_T1", "Jaaropname (…)", "EUR/jaar", 17.85),   # verkeerd gesleuteld
        ])
        with pytest.raises(ValueError, match="Jaaropname"):
            Calculator(bron).gas_grid_cost(self._profiel(), D("12181"), D("12181"))

    def test_een_onbekende_tariefgroep_noemt_wat_er_wel_is(self):
        from energie_vlaanderen.calculation.calculator import Calculator

        bron = self._Bron([self._rij("GAS_T1", "Vaste term", "EUR/jaar", 15.41)])
        with pytest.raises(ValueError, match="GAS_T1"):
            Calculator(bron).gas_grid_cost(self._profiel(), D("12181"), D("12181"))
