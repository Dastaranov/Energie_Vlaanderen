"""Vijf echte eindafrekeningen, nagerekend uit de databank.

`test_referentiefactuur.py` bewaakt één afrekening tot op de cent. Dit bestand
zet er een reeks naast, en de winst zit niet in het aantal maar in de spreiding:
elke factuur hier raakt iets wat die ene niet raakt.

    engie_direct_online_exclusief_nacht  een derde register, "uitsluitend nacht"
    eneco_zon_wind_flex                  de netkost regel per regel, met de
                                         ondergrens van 2,5 kW en het maximumtarief
    engie_personeelstarief               een contract dat niet op de markt bestaat
    engie_drive_empower                  Fluvius Halle-Vilvoorde in plaats van
                                         Midden-Vlaanderen

Wat ze samen opleverden, staat per bevinding bij de test die het bewaakt. De
grootste: `supplier_cost()` prijsde het register "uitsluitend nacht" niet.

De bedragen in de fixtures komen uit de facturen zelf; de brondocumenten
blijven lokaal in `data/referentie/` en staan niet in git.
"""

from __future__ import annotations

import tomllib
from datetime import date
from decimal import Decimal as D
from pathlib import Path

import pytest

from energie_vlaanderen.heffingen.repository import HeffingenRepository
from energie_vlaanderen.utility.normalizer import money

pytestmark = pytest.mark.rekenen

ROOT = Path(__file__).resolve().parents[1]
FACTUREN = ROOT / "tests" / "fixturen" / "facturen"
DOSSIERS = ROOT / "tests" / "fixturen" / "dossiers"


def _lees(naam: str) -> dict:
    with (FACTUREN / naam).open("rb") as fh:
        return tomllib.load(fh)


@pytest.fixture(scope="module")
def exclusief_nacht() -> dict:
    return _lees("engie_direct_online_exclusief_nacht_2025_2026.toml")


@pytest.fixture(scope="module")
def eneco() -> dict:
    return _lees("eneco_zon_wind_flex_2025_2026.toml")


@pytest.fixture(scope="module")
def personeelstarief() -> dict:
    return _lees("engie_personeelstarief_2025_2026.toml")


@pytest.fixture(scope="module")
def drive_empower() -> dict:
    return _lees("engie_drive_empower_2025_2026.toml")


@pytest.fixture(scope="module")
def heffingen() -> HeffingenRepository:
    return HeffingenRepository.load(ROOT / "config" / "heffingen")


# ---------------------------------------------------------------------------
# Wat de facturen over de masterdata zeggen
# ---------------------------------------------------------------------------


class TestHeffingenBevestigdDoorDeFacturen:
    """Drie heffingen, elk bevestigd door een betaald document.

    Tot nu toe was de masterdata in `config/heffingen/` alleen tegen zijn eigen
    bron gelegd — vlaanderen.be voor het energiefonds, vtest.be voor de
    accijnzen. Een factuur is een onafhankelijke bron: ze is betaald, en de
    leverancier drukt het tarief erbij af.
    """

    def test_de_bijdrage_op_de_energie_staat_op_drie_facturen(
        self, exclusief_nacht, personeelstarief, drive_empower
    ):
        """1,9261 EUR/MWh, letterlijk afgedrukt op drie ENGIE-facturen.

        Dit is de post die tot augustus 2026 op nul stond omdat vtest.be hem
        niet toont. De wettekst (art. 39 programmawet 25/12/2021) en één
        afrekening corrigeerden dat; deze drie bevestigen het.
        """
        for factuur in (exclusief_nacht, personeelstarief, drive_empower):
            afgedrukt = D(factuur["elektriciteit"]["heffingen"][
                "bijdrage_op_de_energie_eur_mwh"
            ])
            assert afgedrukt == D("1.9261")

    def test_het_energiefonds_klopt_op_twee_kalenderjaren(self, eneco, heffingen):
        """118,56 en 120,84 EUR/jaar = 9,88 en 10,07 EUR/maand.

        De Eneco-afrekening rekent de bijdrage energiefonds aan het
        **niet-residentiële** tarief aan en drukt het jaarbedrag af. Gedeeld
        door twaalf zijn dat exact de waarden uit
        `config/heffingen/bijdrage_energiefonds.toml` — de eerste bevestiging
        van die tabel uit iets anders dan de pagina waar ze vandaan komt.
        """
        h = eneco["elektriciteit"]["heffingen"]
        for jaar, sleutel in ((2025, "bijdrage_energiefonds_2025_eur_jaar"),
                              (2026, "bijdrage_energiefonds_2026_eur_jaar")):
            uit_de_factuur = D(h[sleutel])
            uit_de_masterdata = heffingen.energiefonds_per_jaar(
                "laag", "niet_residentieel", jaar
            )
            assert money(uit_de_masterdata) == money(uit_de_factuur)

    def test_geen_energiefondsregel_op_een_residentiele_factuur(
        self, exclusief_nacht, drive_empower, heffingen
    ):
        """De bevestiging vanuit de andere richting.

        Op de residentiële ENGIE-facturen staat géén regel "bijdrage
        energiefonds", en de masterdata zegt 0,00 EUR/maand voor een
        residentiële laagspanningsaansluiting sinds 2023. Een afwezige regel is
        zwak bewijs op zichzelf; samen met een factuur die de heffing wél
        aanrekent zodra ze niet-residentieel is, is het sluitend.
        """
        for factuur in (exclusief_nacht, drive_empower):
            assert D(factuur["elektriciteit"]["heffingen"][
                "bijdrage_energiefonds_eur"
            ]) == 0
        for jaar in (2025, 2026):
            assert heffingen.energiefonds_per_jaar("laag", "residentieel", jaar) == 0


class TestDeGasaccijnsIsProgressief:
    """De bijzondere accijns op aardgas vóór 01/08/2026 is niet vlak.

    `config/heffingen/bijzondere_accijns_aardgas.toml` draagt één schijf van
    8,2415 EUR/MWh voor het hele regime vóór de hervorming. Dat cijfer is
    teruggerekend uit één factuur door het aangerekende bedrag door het volume
    te delen — dus het is het *gemiddelde* van die ene factuur, en niet het
    tarief.

    Drie facturen met verschillende volumes over vrijwel dezelfde periode geven
    drie verschillende gemiddelden, en ze stijgen mee met het volume. Dat is de
    vorm van een progressieve tabel en van niets anders.

    Deze test legt de waarneming vast, niet de oplossing: de bovenste schijf is
    uit drie punten afgeleid en niet uit een wettekst. Zodra de masterdata
    gecorrigeerd is, hoort hier een test bij die het model zelf toetst.
    """

    # (volume kWh, aangerekende accijns EUR, bron)
    WAARNEMINGEN = (
        (D("12181"), D("100.39"), "engie_easy_vast_2025_2026"),
        (D("13599"), D("113.07"), "engie_drive_empower_2025_2026"),
        (D("14230"), D("118.79"), "engie_personeelstarief_2025_2026"),
    )

    def test_het_gemiddelde_tarief_stijgt_met_het_volume(self):
        gemiddelden = [
            (volume, bedrag / volume * D("1000")) for volume, bedrag, _ in self.WAARNEMINGEN
        ]
        # 8,2415 -> 8,3146 -> 8,3479 EUR/MWh
        for (v1, t1), (v2, t2) in zip(gemiddelden, gemiddelden[1:]):
            assert v2 > v1
            assert t2 > t1, (
                f"Een vlak tarief zou hetzelfde gemiddelde geven op {v1} en "
                f"{v2} kWh; gemeten {t1:.4f} tegenover {t2:.4f} EUR/MWh."
            )

    def test_een_tweeschijvenmodel_reproduceert_de_drie_facturen(self):
        """8,23 EUR/MWh tot 12 MWh en 8,98 daarboven.

        De grens van 12 MWh is dezelfde als in het regime ná 01/08/2026 (het
        "basisverbruik" uit de programmawet 2026): de hervorming wijzigde de
        tarieven, niet de schijfindeling.

        De bovenste schijf is met drie punten niet scherper te bepalen dan
        ongeveer 8,97 tot 8,99; de tolerantie hieronder is daarop gekozen en
        niet op wat toevallig slaagt.
        """
        grens, onder, boven = D("12000"), D("8.23"), D("8.98")
        for volume, bedrag, naam in self.WAARNEMINGEN:
            model = (
                min(volume, grens) * onder + max(volume - grens, D("0")) * boven
            ) / D("1000")
            assert abs(model - bedrag) <= D("0.06"), (
                f"{naam}: model {model:.2f} tegenover factuur {bedrag:.2f}"
            )

    def test_het_huidige_vlakke_tarief_wijkt_af_bij_hogere_volumes(self, heffingen):
        """Waar de fout zit, en hoe groot ze is.

        Op het volume waarop het tarief gekalibreerd is (12.181 kWh) klopt het
        vlakke model per definitie. Daarboven loopt het weg: 1,00 EUR op
        13.599 kWh en 1,52 EUR op 14.230 kWh, telkens te weinig.
        """
        peildatum = date(2025, 12, 1)
        afwijkingen = []
        for volume, bedrag, _ in self.WAARNEMINGEN:
            accijns, _bijdrage = heffingen.bereken_accijns_en_energiebijdrage(
                "aardgas", "niet_zakelijk", volume, peildatum
            )
            afwijkingen.append(money(accijns) - bedrag)
        assert afwijkingen[0] == D("0.00")
        assert afwijkingen[1] < D("-0.90")
        assert afwijkingen[2] < D("-1.40")


class TestDeTweeKlantcategorieenVallenNietSamen:
    """Eén `segment`-veld stuurt twee heffingen met twee eigen definities aan.

    De Eneco-afrekening rekent de bijzondere accijns aan het **niet-zakelijke**
    tarief (4,75 ct/kWh — een privépersoon, geen onderneming) maar de bijdrage
    energiefonds aan het **niet-residentiële** tarief (120,84 EUR/jaar). Dat is
    geen tegenstrijdigheid in het document: "zakelijk gebruik" bij de accijns en
    "residentiële afnemer" bij het energiefonds komen uit twee verschillende
    wetten en betekenen niet hetzelfde.

    `Calculator.levies_gesplitst()` leidt beide categorieën uit één veld af:
    `segment == "Woning"` geeft niet_zakelijk + residentieel, alles anders geeft
    zakelijk + niet_residentieel. Geen van beide waarden reproduceert deze
    factuur; met "Woning" mist de berekening 120,80 EUR.

    Deze test legt vast dát ze uiteenlopen. Ze oplossen vraagt een eigen veld in
    het dossier, en dat is een wijziging aan het gebruikersmodel.
    """

    def test_de_factuur_combineert_niet_zakelijk_met_niet_residentieel(self, eneco):
        h = eneco["elektriciteit"]["heffingen"]
        assert D(h["bijzondere_accijns_ct_kwh"]) == D("4.75")
        assert h["bijdrage_energiefonds_klantcategorie"] == "niet_residentieel"
        assert D(h["bijdrage_energiefonds_totaal_eur"]) > 100


class TestHetExclusiefNachtregisterWordtGeprijsd:
    """De bevinding waarvoor deze reeks alleen al de moeite was.

    `supplier_cost()` rekende de energiekost over `afname_dag_kwh` en
    `afname_nacht_kwh`. Het derde register — "uitsluitend nacht", een aparte
    aansluiting voor nachtverwarming — werd nergens vermenigvuldigd. Het volume
    telde wél mee in de kosten groene stroom en WKK (die gaan over
    `afname_kwh`), zodat er ook geen verdacht ronde nul te zien was.

    Op deze factuur: 2.076 van de 11.738 kWh, 223,77 EUR per jaar gratis
    stroom. Geen exception, geen falende test — de netkost kende het register
    al wel, want `grid_cost()` splitst er sinds een eerdere referentiefactuur
    het ODV-tarief precies op.

    Een ontbrekende prijs voor dit register is nu een fout en geen nul: de
    nachtprijs zou een aanname zonder bron zijn, en het exclusief-nachttarief
    ligt structureel lager — dat verschil ís de reden dat het register bestaat.
    """

    @staticmethod
    def _product(kind: str, met_exclusief_nacht: bool):
        from energie_vlaanderen.domain.models import Product

        componenten = {"day": D("20"), "night": D("15"), "fixed_fee": D("0")}
        formules = {
            "day": {"z": D("20")},
            "night": {"z": D("15")},
        }
        if met_exclusief_nacht:
            componenten["exclusive_night"] = D("10")
            formules["exclusive_night"] = {"z": D("10")}
        return Product(
            year=2026, month=1, segment="Woning", energy="Elektriciteit",
            direction="Afname", supplier="T", name="T", kind=kind,
            components=componenten, formulas=formules, source="test",
        )

    @staticmethod
    def _profiel(exclusief_nacht_kwh):
        from energie_vlaanderen.domain.models import Profile

        return Profile(
            postcode="9500", gemeente="Geraardsbergen", segment="Woning",
            meter="digitaal", afname_dag_kwh=D("1000"), afname_nacht_kwh=D("1000"),
            afname_exclusief_nacht_kwh=D(exclusief_nacht_kwh),
            injectie_dag_kwh=D("0"), injectie_nacht_kwh=D("0"), omvormer_kva=D("0"),
        )

    @pytest.fixture
    def rekenaar(self, heffingen):
        from energie_vlaanderen.calculation.calculator import Calculator

        class _LegeBron:
            dnb = None

            def dnb_for(self, *a, **kw):  # pragma: no cover - niet gebruikt
                raise AssertionError("supplier_cost raakt de nettarieven niet")

        return Calculator(_LegeBron(), heffingen=heffingen)

    @pytest.mark.parametrize("kind", ["vast", "variabel"])
    def test_het_register_telt_mee_in_de_energiekost(self, rekenaar, kind):
        product = self._product(kind, met_exclusief_nacht=True)
        zonder, _ = rekenaar.supplier_cost(product, self._profiel(0))
        met, _ = rekenaar.supplier_cost(product, self._profiel(2076))
        # 2.076 kWh x 10 ct/kWh = 207,60 EUR. Vóór de correctie was dit verschil
        # nul voor de energieprijs; alleen de groene-stroom- en WKK-opslag
        # bewoog mee, en die staan hier op nul.
        assert money(met - zonder) == D("207.60")

    @pytest.mark.parametrize("kind", ["vast", "variabel"])
    def test_een_ontbrekende_prijs_is_een_fout_en_geen_nul(self, rekenaar, kind):
        product = self._product(kind, met_exclusief_nacht=False)
        with pytest.raises(ValueError, match="uitsluitend nacht"):
            rekenaar.supplier_cost(product, self._profiel(2076))

    def test_zonder_volume_wordt_er_niets_geeist(self, rekenaar):
        """Een product zonder exclusief-nachttarief blijft bruikbaar voor een
        aansluiting die dat register niet heeft — anders zou de correctie de
        gewone gevallen breken."""
        product = self._product("vast", met_exclusief_nacht=False)
        bedrag, _ = rekenaar.supplier_cost(product, self._profiel(0))
        assert bedrag > 0


# ---------------------------------------------------------------------------
# De hele keten, tegen de databank
# ---------------------------------------------------------------------------


def _bereken(db_conn, heffingen, dossierbestand: str, van: date, tot: date,
             energie=None):
    """Draait `Kostberekening` op een dossierfixture, zoals de CLI het doet."""
    from energie_vlaanderen.data.db_repository import (
        DbDataRepository,
        netbeheerders_uit_databank,
    )
    from energie_vlaanderen.gebruikers.berekening import Kostberekening
    from energie_vlaanderen.gebruikers.toml_io import lees_dossier

    jaren = sorted({van.year, tot.year})
    repos = {jaar: DbDataRepository(db_conn, tariefjaar=jaar) for jaar in jaren}
    for jaar, repo in repos.items():
        if len(repo.dnb) == 0:
            pytest.skip(f"Geen nettarieven voor {jaar} in de databank.")

    from energie_vlaanderen.gebruikers.schatting import gasaandeel_uit_rlp0
    from energie_vlaanderen.nettarieven.transport import TransportTariefRepository

    dossier = lees_dossier(
        DOSSIERS / dossierbestand,
        project_root=ROOT,
        netbeheerders=netbeheerders_uit_databank(db_conn),
    )
    punt = dossier.punt(energie) if energie else dossier.aansluitingspunten[0]
    return Kostberekening(
        repos[max(jaren)], heffingen,
        segment=str(dossier.gebruiker.segment),
        nettarieven_per_jaar=repos,
        # Dezelfde twee die `cli/gebruikers.py` meegeeft: het vervoerstarief van
        # Fluxys staat in geen werkboek, en de RLP0-verdeling van het gasvolume
        # komt uit de databank.
        transport=TransportTariefRepository.load(ROOT / "config" / "nettarieven"),
        gasverdeler=lambda van, tot: gasaandeel_uit_rlp0(db_conn, van, tot),
    ).bereken(
        punt, dossier.meter_van(punt), dossier.contracten_van(punt),
        dossier.opgaven_van(punt), van, tot,
        extra_aannames=dossier.aannames,
    )


@pytest.mark.integration
class TestExclusiefNachtUitDeDatabank:
    """De afrekening met het derde register, volledig doorgerekend."""

    @pytest.fixture
    def resultaat(self, db_conn, heffingen):
        return _bereken(
            db_conn, heffingen,
            "engie_direct_online_exclusief_nacht.toml",
            date(2025, 4, 1), date(2026, 4, 1),
        )

    def test_de_heffingen_komen_op_een_cent_uit(self, resultaat, exclusief_nacht):
        """579,93 EUR — de regel "Toeslagen"."""
        verwacht = D(exclusief_nacht["elektriciteit"]["componenten"]["toeslagen_eur"])
        assert abs(money(resultaat.totalen["levies"]) - verwacht) <= D("0.01")

    def test_de_netkost_blijft_binnen_een_half_procent(self, resultaat, exclusief_nacht):
        """1.111,67 tegenover 1.106,81.

        Het restverschil van 4,86 zit volledig in de volumetrische
        distributieterm. Het is géén verdelingsprobleem over de jaarwissel: om
        met een verdeling op het factuurbedrag uit te komen zou 48,2% van het
        volume in 2026 moeten vallen, terwijl de factuur zelf 34,5% afdrukt (en
        het dossier die verdeling ook zo declareert). Er zit dus ongeveer
        0,0004 EUR/kWh verschil in het tarief zelf, en dat is nog niet
        thuisgebracht. De drempel staat op een half procent zodat een echte
        verslechtering opvalt.
        """
        verwacht = D(exclusief_nacht["elektriciteit"]["componenten"]["netwerkkosten_eur"])
        onze = money(resultaat.totalen["grid"])
        assert abs(onze - verwacht) / verwacht < D("0.005")

    def test_het_exclusief_nachtvolume_zit_in_de_leverancierskost(
        self, resultaat, exclusief_nacht
    ):
        """De regressie op de bevinding, nu op de echte data.

        Zonder de correctie kwam de leverancierskost op 1.262,48 uit; met de
        2.076 kWh erbij op 1.486,25. De factuur rekent 1.564,99 (energie plus
        groene stroom en WKK). Het resterende verschil van 78,74 komt doordat de
        V-test-export per maand de tariefkaart levert die op dat moment verkocht
        wordt, terwijl een lopend variabel contract de formule van zijn eigen
        kaartversie houdt — hier param A = 0,0954 in de export tegenover 0,0996
        op de kaart van de klant.

        De ondergrens hieronder ligt boven de 1.262,48 van vóór de correctie:
        die drempel is precies wat de fout zou terugvangen.
        """
        componenten = exclusief_nacht["elektriciteit"]["componenten"]
        factuur = (
            D(componenten["energie_afname_eur"])
            + D(componenten["groene_stroom_eur"])
            + D(componenten["wkk_eur"])
        )
        onze = money(resultaat.totalen["supplier"])
        assert onze > D("1300"), (
            "De leverancierskost is teruggevallen naar de orde van grootte van "
            "vóór de correctie; het register 'uitsluitend nacht' wordt "
            "vermoedelijk niet meer geprijsd."
        )
        assert abs(onze - factuur) / factuur < D("0.06")


@pytest.mark.integration
class TestEnecoNetkostUitDeDatabank:
    """De scherpste toets op `grid_cost()` die dit repo heeft.

    15,09 kWh over 369 dagen: de energiekost is verwaarloosbaar en wat overblijft
    is de netkost, die Eneco regel per regel met eenheidsprijs afdrukt. Drie
    deelperiodes, twee tariefjaren, de ondergrens van 2,5 kW en de
    maximumtariefcorrectie — en het komt op één cent uit.
    """

    @pytest.fixture
    def resultaat(self, db_conn, heffingen):
        return _bereken(
            db_conn, heffingen, "eneco_zon_wind_flex.toml",
            date(2025, 6, 1), date(2026, 6, 5),
        )

    def test_de_netkost_komt_op_een_cent_uit(self, resultaat, eneco):
        verwacht = D(eneco["elektriciteit"]["componenten"]["nettarieven_eur"])
        assert abs(money(resultaat.totalen["grid"]) - verwacht) <= D("0.01")

    def test_de_heffingen_missen_precies_het_energiefonds(self, resultaat, eneco):
        """Het gat is de niet-residentiële bijdrage energiefonds, niet meer.

        Zie `TestDeTweeKlantcategorieenVallenNietSamen`: het dossier staat op
        `segment = "Woning"` en dan rekent de engine het residentiële tarief van
        0,00 EUR/maand. Wat overblijft is de bijzondere accijns, en die klopt.
        """
        h = eneco["elektriciteit"]["heffingen"]
        accijns = D(h["bijzondere_accijns_eur"])
        fonds = D(h["bijdrage_energiefonds_totaal_eur"])
        onze = money(resultaat.totalen["levies"])
        assert abs(onze - accijns) <= D("0.05")
        assert abs((onze + fonds) - (accijns + fonds)) <= D("0.05")


@pytest.mark.integration
class TestGasUitDeDatabank:
    """De gashelft van de personeelstariefafrekening.

    Twee tariefkaarten, een jaarwissel, RLP0-verdeling van het volume: netkost
    op één cent.
    """

    @pytest.fixture
    def resultaat(self, db_conn, heffingen):
        from energie_vlaanderen.gebruikers.models import EnergieType

        return _bereken(
            db_conn, heffingen, "engie_personeelstarief_elek_gas.toml",
            date(2025, 5, 8), date(2026, 5, 7), energie=EnergieType.GAS,
        )

    def test_de_netkost_komt_op_een_cent_uit(self, resultaat, personeelstarief):
        verwacht = D(personeelstarief["aardgas"]["componenten"]["netwerkkosten_eur"])
        assert abs(money(resultaat.totalen["grid"]) - verwacht) <= D("0.01")

    def test_de_heffingen_missen_de_progressieve_schijf(self, resultaat, personeelstarief):
        """131,47 tegenover 132,99 — precies de tweede accijnsschijf.

        Zie `TestDeGasaccijnsIsProgressief`. Zodra de masterdata die schijf
        draagt, hoort dit verschil op nul te komen en moet deze test dat eisen.
        """
        verwacht = D(personeelstarief["aardgas"]["componenten"]["toeslagen_eur"])
        onze = money(resultaat.totalen["levies"])
        assert D("-1.6") < onze - verwacht < D("-1.4")


@pytest.mark.integration
class TestEenContractDatNietOpDeMarktBestaat:
    """Het personeelstarief hoort te weigeren, niet te schatten.

    Een tarief dat alleen voor werknemers bestaat staat niet op vtest.be en zal
    er nooit op staan. De prijs is er ook niet uit af te leiden: de formule is
    `0,1097 + 0,00114 x Epex DAM` en de factuur draagt géén aparte
    netwerkkostenregel voor elektriciteit — het is een all-in prijs. Een engine
    die hier het dichtstbijzijnde marktproduct naast legt, geeft een bedrag dat
    er plausibel uitziet en volledig verzonnen is.
    """

    def test_zoek_product_weigert(self, db_conn, heffingen):
        from energie_vlaanderen.gebruikers.berekening import BerekeningError
        from energie_vlaanderen.gebruikers.models import EnergieType

        with pytest.raises(BerekeningError, match="personeelstarief"):
            _bereken(
                db_conn, heffingen, "engie_personeelstarief_elek_gas.toml",
                date(2025, 7, 6), date(2026, 5, 7),
                energie=EnergieType.ELEKTRICITEIT,
            )


@pytest.mark.integration
class TestEenAndereNetbeheerder:
    """Fluvius Halle-Vilvoorde, de enige referentiecase buiten Midden-Vlaanderen.

    Zolang elke factuur op dezelfde netbeheerder staat, bewijst geen enkele
    toets dat de opzoeking werkelijk op de netbeheerder gaat en niet op een
    stilzwijgende standaard.

    De volledige afrekening is niet door te rekenen: het product "Drive"
    verdween in juni 2025 uit de V-test-export terwijl de klant het tot maart
    2026 hield. De export bevat wat er te koop is, niet wat er loopt. Wat hier
    getoetst wordt is de netkost, en die hangt niet van het product af.
    """

    @staticmethod
    def _netkost(db_conn, heffingen, factuur, *, gas: bool):
        from energie_vlaanderen.calculation.calculator import Calculator
        from energie_vlaanderen.data.db_repository import DbDataRepository
        from energie_vlaanderen.domain.models import Profile

        # 01/06/2025..31/05/2026: 214 dagen in tariefjaar 2025, 151 in 2026.
        # Dezelfde vorm als de capaciteitstarieftoets in
        # `test_referentiefactuur.py`; er is geen meting, dus het volume volgt
        # de dagen.
        totaal = D("0")
        for jaar, dagen in ((2025, 214), (2026, 151)):
            deel = D(dagen) / D("365")
            elek = factuur["elektriciteit"]
            profiel = Profile(
                postcode=factuur["factuur"]["postcode"],
                gemeente="Roosdaal", segment="Woning", meter="digitaal",
                afname_dag_kwh=(
                    D(factuur["aardgas"]["verbruik_kwh"]) if gas
                    else D(elek["afname_piek_kwh"])
                ) * deel,
                afname_nacht_kwh=D("0") if gas else D(elek["afname_dal_kwh"]) * deel,
                afname_exclusief_nacht_kwh=D("0"),
                injectie_dag_kwh=D("0"), injectie_nacht_kwh=D("0"),
                omvormer_kva=D("0"),
                geschatte_maandpiek_kw=D("0") if gas else D(elek["gemiddelde_maandpiek_kw"]),
                minimum_maandpiek_kw=D("2.5"),
            )
            repo = DbDataRepository(db_conn, tariefjaar=jaar)
            if len(repo.dnb) == 0:
                pytest.skip(f"Geen nettarieven voor {jaar} in de databank.")
            rekenaar = Calculator(repo, heffingen=heffingen)
            totaal += (
                rekenaar.gas_grid_cost(
                    profiel, D(factuur["aardgas"]["verbruik_kwh"]),
                    profiel.afname_kwh, dagen=dagen,
                )
                if gas else rekenaar.grid_cost(profiel, dagen=dagen)
            )
        return totaal

    def test_de_elektriciteitsnetkost_klopt_op_fhv(self, db_conn, heffingen, drive_empower):
        """1.153,65 tegenover 1.150,39 — 0,28%."""
        verwacht = D(drive_empower["elektriciteit"]["componenten"]["netwerkkosten_eur"])
        onze = self._netkost(db_conn, heffingen, drive_empower, gas=False)
        assert abs(money(onze) - verwacht) / verwacht < D("0.005")

    def test_de_gasdistributiekost_klopt_op_fhv(self, db_conn, heffingen, drive_empower):
        """219,78 tegenover 220,94 — 0,53%.

        Vergeleken wordt met de distributiekost en niet met de volledige
        netwerkkost: die laatste bevat ook het vervoerstarief van Fluxys, dat
        `gas_grid_cost()` niet dekt (het staat in geen VREG-werkboek en komt uit
        `config/nettarieven/transport_aardgas.toml`).
        """
        verwacht = D(drive_empower["aardgas"]["netwerk"]["distributiekosten_eur"])
        onze = self._netkost(db_conn, heffingen, drive_empower, gas=True)
        assert abs(money(onze) - verwacht) / verwacht < D("0.01")

    def test_een_verdwenen_product_stopt_de_berekening(self, db_conn, heffingen):
        """De keerzijde, en ze is scherper dan ze lijkt.

        `zoek_product()` weigert terecht: "Drive" bestaat niet in de export voor
        juni 2025. Maar daarmee valt de héle berekening weg — ook de netkost en
        de heffingen, die niet van het product afhangen en hierboven wél op een
        half procent uitkomen. Dat is de bevinding: een dossier waarvan het
        product van de markt is, levert vandaag geen enkel cijfer op, terwijl
        het gereguleerde deel volledig bekend is.
        """
        from energie_vlaanderen.gebruikers.berekening import BerekeningError

        with pytest.raises(BerekeningError, match="Drive"):
            _bereken(
                db_conn, heffingen, "engie_drive_empower_elek_gas.toml",
                date(2025, 6, 1), date(2026, 6, 1),
            )
