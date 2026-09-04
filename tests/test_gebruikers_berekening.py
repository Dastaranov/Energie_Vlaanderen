"""Tests voor het doorrekenen van een dossier over een periode.

De centrale eigenschap die hier vastligt: **knippen mag het totaal niet
veranderen.** Een jaar dat door een contractwissel of een heffingenwissel in
stukken valt, moet dezelfde netkost opleveren als hetzelfde jaar in één stuk.

Waarom dat geen vanzelfsprekendheid is: bijna elke component van een
energiefactuur is een jaargrootheid. Het capaciteitstarief heeft een jaarlijkse
ondergrens en een maximumtarief per kWh over het jaarverbruik, databeheer en de
vaste vergoeding zijn EUR per jaar, de accijnsschijven zijn progressief over
het jaarverbruik, en het energiefonds is een vast bedrag per maand. Wie de
deelperiodevolumes rechtstreeks door de rekenengine haalt, betaalt al die vaste
componenten één keer per deelperiode.

Dit is tijdens de bouw ook echt gebeurd: een contractwissel op 01/08/2026 gaf
603,24 EUR netkost waar één jaar er 373,96 kost — ruim 60% te veel, zonder
enige foutmelding.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal as D
from pathlib import Path

import pytest

from energie_vlaanderen.gebruikers.berekening import (
    BerekeningError,
    Kostberekening,
    bouw_profile,
    dagaandeel,
)
from energie_vlaanderen.gebruikers.models import (
    Aansluitingspunt,
    Contracttype,
    EnergieType,
    Exactheidsklasse,
    Gebruiker,
    Leveringscontract,
    Meter,
    Meterregime,
    OpgaveBron,
    Segment,
    Verbruiksopgave,
)
from energie_vlaanderen.gebruikers.periodes import Deelperiode
from energie_vlaanderen.domain.models import Cost
from energie_vlaanderen.heffingen.repository import HeffingenRepository
from energie_vlaanderen.utility.normalizer import money

ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = ROOT / "config" / "heffingen"


@pytest.fixture(scope="module")
def heffingen() -> HeffingenRepository:
    return HeffingenRepository.load(CONFIG_DIR)


@pytest.fixture
def punt() -> Aansluitingspunt:
    return Aansluitingspunt(Gebruiker().id, EnergieType.ELEKTRICITEIT, "9300", "Aalst")


class TestComponentenSchalenNietHetzelfde:
    """Waarom `_reken_periode` de componenten uit elkaar houdt.

    Nettarieven, heffingen en de vaste vergoeding zijn jaargrootheden en worden
    naar dagen geschaald. De energiecomponent volgt de volumes — en bij een
    dynamisch product zelfs de individuele kwartieren, want dáár hangt de kost
    af van wélke uren in de periode vallen.

    Dat de som van de delen het geheel blijft, staat in
    `test_knippen_verandert_de_netkost_niet` hieronder. Wat hier vastligt, is dat
    212/365 + 153/365 samen precies 1 is — de aandelen mogen niet lekken.
    """

    def test_de_dagaandelen_sommeren_tot_een(self, punt):
        opgave = Verbruiksopgave(punt.id, date(2026, 1, 1), date(2027, 1, 1))
        eerste, _ = dagaandeel(opgave, Deelperiode(date(2026, 1, 1), date(2026, 8, 1), None))
        tweede, _ = dagaandeel(opgave, Deelperiode(date(2026, 8, 1), date(2027, 1, 1), None))
        assert eerste + tweede == D("365") / D("365")
        assert eerste * D("365") == D("212")
        assert tweede * D("365") == D("153")


class TestDagaandeel:
    def test_het_aandeel_is_de_dagverhouding(self, punt):
        opgave = Verbruiksopgave(punt.id, date(2026, 1, 1), date(2027, 1, 1))
        periode = Deelperiode(date(2026, 1, 1), date(2026, 8, 1), None)
        aandeel, aanname = dagaandeel(opgave, periode)
        assert aandeel == D("212") / D("365")
        assert aanname.waarde == "212/365 dagen"
        # De verdeling is een aanname en geen meting: seizoenseffecten zitten
        # er niet in, en dat moet zichtbaar blijven in het eindresultaat.
        assert not aanname.geverifieerd


class TestProfileBouwen:
    def test_amr_gedraagt_zich_als_digitaal(self, punt):
        """Voor het capaciteitstarief telt of er een gemeten kwartierpiek is."""
        meter = Meter(punt.id, meterregime=Meterregime.AMR)
        assert bouw_profile(punt, meter, {}).meter == "digitaal"

    def test_klassiek_gedraagt_zich_als_analoog(self, punt):
        meter = Meter(punt.id, meterregime=Meterregime.KLASSIEK)
        assert bouw_profile(punt, meter, {}).meter == "analoog"

    def test_prosumententarief_alleen_bij_terugdraaiend_en_klassiek(self, punt):
        """Digitaal + PV valt niet onder het prosumententarief (§4.5 prijsmodel).

        `grid_cost()` kiest `ELEK_LS_ANA_PRO` zodra `omvormer_kva > 0` bij een
        analoge meter. Het vermogen doorgeven bij een digitale meter zou dat
        tarief kunnen aanzetten waar het niet geldt.
        """
        klassiek = Meter(punt.id, meterregime=Meterregime.KLASSIEK, terugdraaiend=True)
        digitaal = Meter(punt.id, meterregime=Meterregime.DIGITAAL)
        assert bouw_profile(punt, klassiek, {}, omvormer_kva=D("5")).omvormer_kva == D("5")
        assert bouw_profile(punt, digitaal, {}, omvormer_kva=D("5")).omvormer_kva == D("0")

    def test_het_segment_wordt_doorgegeven(self, punt):
        """`Calculator._levies()` kiest de heffingencategorie op het segment.

        Stond dit vast op "Woning", dan kreeg een onderneming residentiële
        heffingen: 140,58 in plaats van 169,25 EUR op 3 MWh in 2026, zonder
        foutmelding.
        """
        assert bouw_profile(punt, None, {}, segment="Onderneming").segment == "Onderneming"

    def test_exclusief_nacht_blijft_een_eigen_register(self, punt):
        """"Dal" van een tweevoudige meter is geen exclusief-nachtaansluiting.

        Het lagere ODV-tarief "kWh-tarief exclusief nacht" geldt alleen voor het
        aparte register van toestellen die enkel 's nachts draaien
        (accumulatieverwarming, boiler). Piek- en daluren krijgen allebei het
        normale tarief.

        Ze samenvoegen paste dat lagere tarief toe op het hele dalverbruik. Op
        een echte eindafrekening — 4.218 kWh dal bij Fluvius Midden-Vlaanderen
        2025, waar het verschil 0,0083166 EUR/kWh bedraagt — scheelde dat
        35 EUR per jaar te weinig netkost.
        """
        profiel = bouw_profile(
            punt,
            None,
            {
                "afname_dag_kwh": D("2000"),
                "afname_nacht_kwh": D("1000"),
                "afname_exclusief_nacht_kwh": D("500"),
            },
        )
        assert profiel.afname_nacht_kwh == D("1000")
        assert profiel.afname_exclusief_nacht_kwh == D("500")
        assert profiel.afname_kwh == D("3500")


# --- Tests die de echte dataset nodig hebben -------------------------------


@pytest.fixture
def dataset(db_conn):
    """De tarieven uit de databank.

    Deze fixture las eerst de gestagede CSV's uit `data/`, die niet in git
    staan. Daardoor sloegen twaalf tests altijd over in CI — en dat waren net
    de tests die de netkost tegen echte tariefdata leggen.

    Sinds de databank de bron is, komen ze uit PostgreSQL. In CI vult de
    zaaddump die databank, dus deze tests draaien daar nu mee. `Calculator` en
    `Kostberekening` zijn ongewijzigd: alleen de herkomst van de data
    verschilt, niet de rekenregels.
    """
    import sqlalchemy as sa

    from energie_vlaanderen.data.db_repository import DbDataRepository

    jaren = [
        int(r[0]) for r in db_conn.execute(sa.text(
            "select distinct extract(year from geldig_van)::int "
            "from netbeheerder_tarief order by 1 desc"
        ))
    ]
    if not jaren:
        pytest.skip("Geen nettarieven in de databank.")
    return DbDataRepository(db_conn, tariefjaar=jaren[0])


@pytest.mark.integration
class TestTegenDeEchteDataset:
    def _opzet(self, punt):
        opgave = Verbruiksopgave(
            punt.id,
            date(2026, 1, 1),
            date(2027, 1, 1),
            afname_dag_kwh=D("2000"),
            afname_nacht_kwh=D("1000"),
            bron=OpgaveBron.MANUEEL,
        )
        return Meter(punt.id), opgave

    def test_knippen_verandert_de_netkost_niet(self, dataset, heffingen, punt):
        """Dezelfde leverancier heel het jaar, één keer geknipt en één keer niet.

        De netkost moet identiek zijn: de vaste jaarcomponenten
        (capaciteitstarief, databeheer) mogen niet per deelperiode opnieuw
        aangerekend worden.
        """
        meter, opgave = self._opzet(punt)
        rekenaar = Kostberekening(dataset, heffingen)

        heel = [
            Leveringscontract(
                punt.id,
                "Bolt",
                "Bolt Vast",
                Contracttype.VAST,
                date(2026, 1, 1),
                tariefkaart_geldig_van=date(2026, 1, 1),
            )
        ]
        geknipt = [
            Leveringscontract(
                punt.id, "Bolt", "Bolt Vast", Contracttype.VAST,
                date(2026, 1, 1), date(2026, 5, 1), tariefkaart_geldig_van=date(2026, 1, 1),
            ),
            Leveringscontract(
                punt.id, "Bolt", "Bolt Vast", Contracttype.VAST,
                date(2026, 5, 1), tariefkaart_geldig_van=date(2026, 1, 1),
            ),
        ]

        a = rekenaar.bereken(punt, meter, heel, [opgave], date(2026, 1, 1), date(2027, 1, 1))
        b = rekenaar.bereken(punt, meter, geknipt, [opgave], date(2026, 1, 1), date(2027, 1, 1))

        # Vergelijken op centniveau: 212/365 + 153/365 is in Decimal niet
        # exact 1, dus de twee sommen verschillen op de 25e decimaal. Dat is
        # geen modelfout maar deelrest, en de cent is het niveau waarop dit
        # project afrondt (Manifest §7: afronden op een duidelijk bepaald
        # facturatiemoment).
        assert len(b.regels) > len(a.regels)
        assert money(a.totalen["grid"]) == money(b.totalen["grid"])
        assert money(a.totalen["levies"]) == money(b.totalen["levies"])
        assert money(a.totalen["totaal"]) == money(b.totalen["totaal"])

    def test_de_accijnswissel_zit_in_de_heffingen(self, dataset, heffingen, punt):
        """3 MWh gezinsverbruik, verdeeld over twee accijnsregimes in 2026.

        212 dagen tegen 47,4811 EUR/MWh en 153 dagen tegen 46,00 EUR/MWh geeft
        3 x (212/365 x 47,4811 + 153/365 x 46,00) = 140,58 EUR. Beide tarieven
        zijn teruggerekend uit vtest.be en staan in
        `config/heffingen/bijzondere_accijns_elektriciteit.toml`. Het jaar in
        één stuk rekenen zou 142,44 (oud regime) of 138,00 (nieuw) geven.
        """
        meter, opgave = self._opzet(punt)
        rekenaar = Kostberekening(dataset, heffingen)
        contracten = [
            Leveringscontract(
                punt.id, "Bolt", "Bolt Vast", Contracttype.VAST,
                date(2026, 1, 1), tariefkaart_geldig_van=date(2026, 1, 1),
            )
        ]
        resultaat = rekenaar.bereken(
            punt, meter, contracten, [opgave], date(2026, 1, 1), date(2027, 1, 1)
        )

        # Beide regimes dragen daarnaast dezelfde bijdrage op de energie van
        # 1,9261 EUR/MWh (programmawet 25/12/2021 art. 39), die de hervorming
        # van 01/08/2026 niet raakte.
        verwacht = D("3") * (
            D("212") / D("365") * (D("47.4811") + D("1.9261"))
            + D("153") / D("365") * (D("46.0000") + D("1.9261"))
        )
        assert money(resultaat.totalen["levies"]) == money(verwacht)
        # En het ligt tussen de twee regimes in — één van beide op het hele
        # jaar toepassen zou 142,4433 of 138,00 geven.
        assert D("143.78") < resultaat.totalen["levies"] < D("148.2216")

    def test_een_variabel_contract_krijgt_per_maand_zijn_eigen_index(
        self, dataset, heffingen, punt
    ):
        """Acht maanden, acht indexwaarden — geen enkele prijs uitgesmeerd.

        Eén index over de hele looptijd toepassen scheelde op deze combinatie
        (Aspiravi Energy "Eco Plus flex", 3 MWh, januari tot september 2026)
        ongeveer 30 EUR op een leverancierskost van 329 EUR: zo'n 10%, zonder
        foutmelding. De netkost mag er niet door veranderen — die is een
        jaargrootheid en wordt naar dagen geschaald.
        """
        meter, opgave = self._opzet(punt)
        rekenaar = Kostberekening(dataset, heffingen)
        contracten = [
            Leveringscontract(
                punt.id, "Aspiravi Energy", "Eco Plus flex",
                Contracttype.VARIABEL, date(2026, 1, 1),
            )
        ]
        resultaat = rekenaar.bereken(
            punt, meter, contracten, [opgave], date(2026, 1, 1), date(2026, 9, 1)
        )

        assert [r.periode.van.month for r in resultaat.regels] == [1, 2, 3, 4, 5, 6, 7, 8]
        # Elke deelperiode haalt zijn prijs uit de snapshot van zijn eigen maand.
        assert [r.product.month for r in resultaat.regels] == [1, 2, 3, 4, 5, 6, 7, 8]
        # En die prijzen verschillen echt — anders bewijst de test niets.
        assert len({r.kost.supplier / D(r.periode.dagen) for r in resultaat.regels}) > 1

    def test_een_maand_zonder_productdata_stopt_de_berekening(
        self, dataset, heffingen, punt
    ):
        """De V-test-export loopt tot augustus 2026; daarna is er geen index.

        Manifest §12: liever stoppen dan een tarief van een andere maand
        gebruiken.
        """
        meter, opgave = self._opzet(punt)
        rekenaar = Kostberekening(dataset, heffingen)
        contracten = [
            Leveringscontract(
                punt.id, "Aspiravi Energy", "Eco Plus flex",
                Contracttype.VARIABEL, date(2026, 1, 1),
            )
        ]
        with pytest.raises(BerekeningError, match="Geen productdata"):
            rekenaar.bereken(
                punt, meter, contracten, [opgave], date(2026, 1, 1), date(2027, 1, 1)
            )

    def test_een_gat_in_de_contracthistoriek_stopt_de_berekening(self, dataset, heffingen, punt):
        """Manifest §12: een ontbrekend verplicht gegeven levert geen nul op."""
        meter, opgave = self._opzet(punt)
        rekenaar = Kostberekening(dataset, heffingen)
        contracten = [
            Leveringscontract(
                punt.id, "Bolt", "Bolt Vast", Contracttype.VAST,
                date(2026, 1, 1), date(2026, 4, 1), tariefkaart_geldig_van=date(2026, 1, 1),
            )
        ]
        with pytest.raises(BerekeningError, match="Geen leveringscontract"):
            rekenaar.bereken(punt, meter, contracten, [opgave], date(2026, 1, 1), date(2027, 1, 1))

    def test_een_onbekend_product_stopt_de_berekening(self, dataset, heffingen, punt):
        """Stil een ander product pakken zou een willekeurige prijs opleveren."""
        meter, opgave = self._opzet(punt)
        rekenaar = Kostberekening(dataset, heffingen)
        contracten = [
            Leveringscontract(
                punt.id, "Bolt", "Bestaat Niet", Contracttype.VAST,
                date(2026, 1, 1), tariefkaart_geldig_van=date(2026, 1, 1),
            )
        ]
        with pytest.raises(BerekeningError, match="niet gevonden"):
            rekenaar.bereken(punt, meter, contracten, [opgave], date(2026, 1, 1), date(2027, 1, 1))

    def test_injectie_wordt_verrekend(self, dataset, heffingen, punt):
        """2.500 kWh injectie op "Bolt Variabel", augustus 2026.

        De injectieprijs komt uit de indexformule, niet uit de meegeleverde
        prijs: `a x A + z` met a = 0,094, z = -1,133 en indexwaarde 70,54139
        EUR/MWh voor "Q EPEX Spot Belgium/Belpex SPP_BE TH (uur)" — allemaal uit
        `master_var_dyn.csv`, richting Injectie, augustus 2026. Dat geeft
        5,49789066 ct/kWh, tegenover de 5,5 die VREG zelf als berekende prijs
        meelevert: onze formule reproduceert die tot op 0,002 ct/kWh nauwkeurig.

        Over augustus valt 31 van de 365 dagen: 2.500 x 31/365 = 212,3288 kWh
        x 0,0549789066 = 11,67 EUR.

        Het krediet verlaagt hier ook de btw-basis. Dat is wat de engine vandaag
        doet; `docs/price_model_low_voltage.md` §9.1 schrijft in plaats daarvan
        `T - injectieprijs x kWh x 1,06`, en Manifest §14 noemt de
        btw-behandeling van injectievergoedingen een openstaande validatie. Deze
        assertie legt het huidige gedrag vast, niet de eindbeslissing.
        """
        meter, _ = self._opzet(punt)
        rekenaar = Kostberekening(dataset, heffingen)
        contracten = [
            Leveringscontract(
                punt.id, "Bolt", "Bolt Variabel", Contracttype.VARIABEL, date(2026, 8, 1)
            )
        ]

        def reken(injectie):
            opgave = Verbruiksopgave(
                punt.id, date(2026, 1, 1), date(2027, 1, 1),
                afname_dag_kwh=D("2000"), afname_nacht_kwh=D("1000"),
                injectie_dag_kwh=injectie, bron=OpgaveBron.MANUEEL,
            )
            return rekenaar.bereken(
                punt, meter, contracten, [opgave], date(2026, 8, 1), date(2026, 9, 1)
            )

        zonder = reken(D("0"))
        met = reken(D("2500"))

        assert zonder.totalen["injection_credit"] == D("0")
        assert money(met.totalen["injection_credit"]) == D("11.67")
        # Alleen het krediet en de btw wijzigen; nettarieven en heffingen niet.
        assert money(met.totalen["grid"]) == money(zonder.totalen["grid"])
        assert money(met.totalen["levies"]) == money(zonder.totalen["levies"])
        assert met.totalen["totaal"] < zonder.totalen["totaal"]

    def test_zonder_injectieproduct_blijft_het_krediet_nul_maar_niet_stil(
        self, dataset, heffingen, punt
    ):
        """Geen injectieproduct is geen injectievergoeding van nul.

        Het is een onbekend bedrag: de doorgerekende kost staat te hoog. Dat moet
        uit het resultaat blijken via een waarschuwing én een aanname, niet
        alleen uit het feit dat er 0 staat.
        """
        meter, _ = self._opzet(punt)
        opgave = Verbruiksopgave(
            punt.id, date(2026, 1, 1), date(2027, 1, 1),
            afname_dag_kwh=D("2000"), injectie_dag_kwh=D("2500"), bron=OpgaveBron.MANUEEL,
        )
        contracten = [
            Leveringscontract(
                punt.id, "Bolt", "Bolt Variabel", Contracttype.VARIABEL,
                date(2026, 8, 1), injectie_product="Bestaat Niet",
            )
        ]
        resultaat = Kostberekening(dataset, heffingen).bereken(
            punt, meter, contracten, [opgave], date(2026, 8, 1), date(2026, 9, 1)
        )

        assert resultaat.totalen["injection_credit"] == D("0")
        assert any("Injectie niet verrekend" in w for w in resultaat.warnings)
        (aanname,) = [a for a in resultaat.aannames if a.veld == "injectievergoeding"]
        assert not aanname.geverifieerd
        assert resultaat.exactheidsklasse is Exactheidsklasse.GESCHAT

    def test_een_terugdraaiende_meter_krijgt_geen_injectiekrediet(
        self, dataset, heffingen, punt
    ):
        """Terugdraaien én een injectievergoeding is hetzelfde voordeel twee keer.

        Een klassieke terugdraaiende meter registreert geen injectie; daarvoor
        betaalt de klant het prosumententarief (`price_model_low_voltage.md`
        §4.5).
        """
        meter = Meter(punt.id, meterregime=Meterregime.KLASSIEK, terugdraaiend=True)
        opgave = Verbruiksopgave(
            punt.id, date(2026, 1, 1), date(2027, 1, 1),
            afname_dag_kwh=D("2000"), injectie_dag_kwh=D("2500"), bron=OpgaveBron.MANUEEL,
        )
        contracten = [
            Leveringscontract(
                punt.id, "Bolt", "Bolt Variabel", Contracttype.VARIABEL, date(2026, 8, 1)
            )
        ]
        with pytest.raises(BerekeningError, match="terugdraaiende meter"):
            Kostberekening(dataset, heffingen).bereken(
                punt, meter, contracten, [opgave], date(2026, 8, 1), date(2026, 9, 1)
            )

    def test_dezelfde_productnaam_in_twee_smaken_wordt_op_contracttype_gekozen(
        self, dataset, heffingen, punt
    ):
        """"Bolt Variabel" bestaat in augustus 2026 als variabel én als dynamisch.

        Het contract weet welke van de twee de klant heeft. Zonder dat filter
        weigert de opzoeking terecht te kiezen — een willekeurige prijs is erger
        dan geen prijs.
        """
        meter, opgave = self._opzet(punt)
        rekenaar = Kostberekening(dataset, heffingen)
        contracten = [
            Leveringscontract(
                punt.id, "Bolt", "Bolt Variabel", Contracttype.VARIABEL, date(2026, 8, 1)
            )
        ]
        resultaat = rekenaar.bereken(
            punt, meter, contracten, [opgave], date(2026, 8, 1), date(2026, 9, 1)
        )
        (regel,) = resultaat.regels
        assert regel.product.kind.startswith("variabel")

    def test_gas_wordt_expliciet_geweigerd(self, dataset, heffingen):
        """`grid_cost()` dekt enkel elektriciteit-laagspanning."""
        gaspunt = Aansluitingspunt(Gebruiker().id, EnergieType.GAS, "9300", "Aalst")
        rekenaar = Kostberekening(dataset, heffingen)
        with pytest.raises(BerekeningError, match="gas"):
            rekenaar.bereken(gaspunt, None, [], [], date(2026, 1, 1), date(2027, 1, 1))


class TestTariefjaar:
    """De distributienettarieven gelden per kalenderjaar, en de rijen zeggen dat niet.

    `tariffs_electricity_afname.csv` bevat geen datum: aan de data is niet te
    zien of ze bij 2025 of bij 2026 hoort. Een berekening over 2025 met het
    werkboek van 2026 geeft dus een plausibel ogend en verkeerd bedrag. Het jaar
    komt uit `tariffs_*_report.json`, dat het overneemt uit de oorspronkelijke
    bestandsnaam van het VREG-werkboek — niet uit het versie-id, want dat draagt
    de downloaddatum.
    """

    class NepRepo:
        def __init__(self, jaar):
            self.tariefjaar = jaar

    def _rekenaar(self, heffingen, jaar):
        return Kostberekening(self.NepRepo(jaar), heffingen)

    def test_een_ander_tariefjaar_stopt_de_berekening(self, heffingen):
        rekenaar = self._rekenaar(heffingen, 2026)
        periode = Deelperiode(date(2025, 1, 1), date(2026, 1, 1), None)
        with pytest.raises(BerekeningError, match="gelden voor 2026"):
            rekenaar._controleer_tariefjaar(periode)

    def test_hetzelfde_tariefjaar_gaat_door(self, heffingen):
        rekenaar = self._rekenaar(heffingen, 2026)
        rekenaar._controleer_tariefjaar(Deelperiode(date(2026, 3, 1), date(2026, 4, 1), None))

    def test_een_dataversie_zonder_tariefjaar_wordt_niet_geblokkeerd(self, heffingen):
        """Oudere staging-versies dragen het veld nog niet; daar valt niets te toetsen."""
        rekenaar = self._rekenaar(heffingen, None)
        rekenaar._controleer_tariefjaar(Deelperiode(date(2025, 1, 1), date(2026, 1, 1), None))


@pytest.mark.integration
class TestOntbrekendeNettarieven:
    """Een ontbrekend nettarief is een fout, geen nul.

    Het VREG-werkboek van 2024 parseert met de huidige parser maar 4 van de 8
    netbeheerders en kent geen `ELEK_LS_DIGI`. `grid_cost()` gaf daar 0,00 EUR
    terug: elke lookup vond niets en leverde stil `D("0")`. Een digitale meter
    in Aalst zat daarmee gratis op het net, zonder enige melding.

    Manifest §12: een ontbrekend verplicht tarief stopt de berekening.
    """

    def test_een_onbekende_netbeheerder_stopt_de_berekening(self, dataset):
        from energie_vlaanderen.calculation.calculator import Calculator
        from energie_vlaanderen.domain.models import Profile

        profiel = Profile(
            "9300", "Aalst", "Woning", "digitaal",
            afname_dag_kwh=D("2000"), afname_nacht_kwh=D("1000"),
        )
        calculator = Calculator(dataset)
        # Bewijst eerst dat het pad werkt met de geladen dataset ...
        assert calculator.grid_cost(profiel) > D("0")

        # ... en dan dat een netbeheerder zonder rijen niet stil 0 oplevert.
        leeg = dataset.dnb.iloc[0:0]
        calculator.repo = type("Leeg", (), {"dnb": leeg, "dnb_for": lambda s, p, g, e="elektriciteit": (g, "FMV")})()
        with pytest.raises(ValueError, match="Geen nettarieven"):
            calculator.grid_cost(profiel)
