"""De rekenengine tegen een echte eindafrekening.

`tests/fixturen/facturen/engie_easy_vast_2025_2026.toml` is de geanonimiseerde
neerslag van een betaalde ENGIE-eindafrekening (factuurdatum 2026-05-27,
verbruiksperiode 28/05/2025-27/05/2026). Het brondocument blijft lokaal in
`data/referentie/` en valt buiten git.

Dit is de eerste van de tien onafhankelijke referentiefacturen die ROADMAP
fase 5 als exitcriterium noemt. Ze deed meteen waarvoor ze bedoeld is: de
bijdrage op de energie stond in de masterdata op nul, en deze factuur rekent ze
wél aan.

Wat hier getoetst wordt zijn de componenten die de engine vandaag dekt. De
leverancierskost blijft buiten beschouwing: die hangt aan drie
tariefkaartversies met eigen kortingen, en de V-test-export kent alleen
maandsnapshots van publieke productprijzen — geen contractueel
welkomstvoordeel.
"""
from __future__ import annotations

import tomllib
from datetime import date
from decimal import Decimal as D
from pathlib import Path

import pytest

from energie_vlaanderen.heffingen.repository import HeffingenRepository
from energie_vlaanderen.utility.normalizer import money

ROOT = Path(__file__).resolve().parents[1]
FIXTUUR = ROOT / "tests" / "fixturen" / "facturen" / "engie_easy_vast_2025_2026.toml"


pytestmark = pytest.mark.rekenen


@pytest.fixture(scope="module")
def factuur() -> dict:
    if not FIXTUUR.is_file():
        pytest.skip(f"{FIXTUUR.name} ontbreekt.")
    with FIXTUUR.open("rb") as fh:
        return tomllib.load(fh)


@pytest.fixture(scope="module")
def heffingen() -> HeffingenRepository:
    return HeffingenRepository.load(ROOT / "config" / "heffingen")


class TestHeffingenElektriciteit:
    def test_de_totale_toeslagen_komen_exact_uit(self, factuur, heffingen):
        """336,81 EUR op 6.817 kWh — de regel "Toeslagen" van de factuur.

        Dat is 6,817 MWh x (47,4811 bijzondere accijns + 1,9261 bijdrage op de
        energie), plus 0,00 EUR energiefonds voor een residentiële afnemer op
        laagspanning. De peildatum valt in het regime van 01/07/2023.

        Deze assertie zou vóór de correctie 323,68 gegeven hebben: 13,13 EUR te
        laag, precies de weggelaten bijdrage op de energie.
        """
        elek = factuur["elektriciteit"]
        verbruik = D(elek["afname_totaal_kwh"])

        accijns, bijdrage = heffingen.bereken_accijns_en_energiebijdrage(
            "elektriciteit", "niet_zakelijk", verbruik, date(2026, 4, 1)
        )
        energiefonds = heffingen.energiefonds_per_jaar("laag", "residentieel", 2026)

        assert money(accijns + bijdrage + energiefonds) == D(
            elek["componenten"]["toeslagen_eur"]
        )

    def test_de_bijzondere_accijns_komt_los_uit(self, factuur, heffingen):
        """323,68 EUR, de som van de twee accijnsregels op de factuur."""
        elek = factuur["elektriciteit"]
        accijns, _ = heffingen.bereken_accijns_en_energiebijdrage(
            "elektriciteit", "niet_zakelijk",
            D(elek["afname_totaal_kwh"]), date(2026, 4, 1),
        )
        assert money(accijns) == D(elek["heffingen"]["bijzondere_accijns_eur"])

    def test_de_bijdrage_op_de_energie_komt_los_uit(self, factuur, heffingen):
        """13,13 EUR — de post die de masterdata op nul had staan."""
        elek = factuur["elektriciteit"]
        _, bijdrage = heffingen.bereken_accijns_en_energiebijdrage(
            "elektriciteit", "niet_zakelijk",
            D(elek["afname_totaal_kwh"]), date(2026, 4, 1),
        )
        assert money(bijdrage) == D(elek["heffingen"]["bijdrage_op_de_energie_eur"])

    def test_het_energiefonds_is_nul_voor_een_gezin(self, factuur, heffingen):
        """De factuur toont geen energiefondsregel, en de tarieftabel van
        vlaanderen.be zet residentieel op laagspanning sinds 2023 op 0,00
        EUR/maand."""
        assert heffingen.energiefonds_per_jaar("laag", "residentieel", 2026) == D("0")


class TestBtwBehandeling:
    def test_de_injectievergoeding_valt_buiten_de_btw_basis(self, factuur):
        """Het antwoord op de openstaande validatie uit docs/manifest.md §14.

        De btw-tabel van de factuur splitst het totaal van 584,42 EUR in een
        6%-basis van 668,57 en twee vrijstellingen: -12,95 (artikel 28
        btw-wetboek) en -71,20 (Beslissing ET 131.616/2 van 25-10-2019). Dat
        laatste bedrag is exact de som van de vier injectieregels.

        De injectievergoeding is dus btw-vrijgesteld en valt volledig buiten de
        btw-basis. Niet ervan afgetrokken zoals de rekenengine deed, en niet
        met 6% verhoogd zoals `docs/price_model_low_voltage.md` §9.1 schrijft.
        """
        btw = factuur["btw"]
        injectie = D(factuur["elektriciteit"]["componenten"]["energie_injectie_eur"])

        assert D(btw["vrijgesteld_injectie"]) == injectie
        assert "ET 131.616/2" in btw["vrijgesteld_injectie_grond"]

        # De drie delen sommeren tot het factuurtotaal exclusief btw.
        totaal = (
            D(btw["basis_6pct"])
            + D(btw["vrijgesteld_injectie"])
            + D(btw["vrijgesteld_art28"])
        )
        assert totaal == D(factuur["factuur"]["totaal_excl_btw"])


class TestVasteVergoeding:
    def test_de_vaste_vergoeding_loopt_pro_rata_per_dag(self, factuur):
        """Twee tariefkaartversies, twee periodes, dezelfde jaarwaarde.

        22,29 EUR over 125 dagen en 32,99 EUR over 185 dagen komen allebei op
        65,09 EUR per jaar uit. Dat bevestigt de aanpak in
        `gebruikers/berekening.py::_leverancierskost`, die de vaste vergoeding
        uit het periodebedrag haalt en naar dagen schaalt in plaats van ze per
        deelperiode voluit aan te rekenen.
        """
        verwacht = D(factuur["elektriciteit"]["controle"]["vaste_vergoeding_per_jaar_eur"])
        for kaart in factuur["elektriciteit"]["tariefkaart"]:
            per_jaar = D(kaart["vaste_vergoeding_eur"]) / D(kaart["dagen"]) * D("365")
            assert money(per_jaar) == verwacht


class TestVervoerstarief:
    def test_het_fluxys_transporttarief_klopt_in_orde_van_grootte(self, factuur):
        """19,00 EUR op 12.181 kWh gas = 1,56 EUR/MWh.

        Het vervoerstarief staat in geen enkel VREG-werkboek — daarvoor bestaat
        `config/nettarieven/transport_aardgas.toml`. De factuur noemt het
        "Transportkosten (geschat door Fluxys)" en bevestigt de grootteorde.
        """
        gas = factuur["aardgas"]
        per_mwh = D(gas["netwerk"]["transportkosten_eur"]) / (
            D(gas["verbruik_kwh"]) / D("1000")
        )
        assert D("1.5") < per_mwh < D("1.6")


class TestMaandpiek:
    def test_de_gemeten_piek_ligt_ver_boven_de_standaardschatting(self, factuur):
        """7,409 kW gemeten tegenover 4,218 kW als standaard.

        4,218 kW is de piek waarmee vtest.be zijn standaardwoning doorrekent en
        die dit project als schatting gebruikt wanneer er geen meetdata is. Deze
        huishouding piekt 76% hoger. Een geschatte maandpiek is dus geen kleine
        onnauwkeurigheid: hier scheelt ze 311 tegenover ongeveer 177 EUR
        capaciteitstarief.
        """
        gemeten = D(factuur["elektriciteit"]["gemeten_maandpiek_kw"])
        standaard = D("4.218")
        assert gemeten > standaard
        assert gemeten / standaard > D("1.7")


@pytest.mark.integration
class TestVolledigeSimulatie:
    """De hele keten tegen de factuur: dossier -> periodes -> tarieven -> bedrag.

    Wat de engine claimt te kennen zijn de gereguleerde posten en de publieke
    productprijzen. Twee posten op de factuur vallen daar buiten en worden dus
    niet vergeleken:

    - **"Periode tussen meteropname en factuurdatum"** (+112,66 EUR): een
      facturatiemechanisme van de leverancier voor de dagen tussen de opname en
      de factuurdatum, dat op de vólgende factuur weer rechtgezet wordt.
    - **Kortingen** (-380,70 EUR): ENGIE-voordeel en welkomstvoordeel, contractueel
      en in geen enkele publieke bron terug te vinden.

    Wat wél vergeleken wordt, komt uit op 0,033% van het factuurbedrag.
    """

    # Geen vastgepind versie-id. Die stond hier op 20260829T202059Z-853a7046,
    # waardoor deze test ook slaagde wanneer de *actieve* dataset brak: hij
    # bewaakte een momentopname van augustus in plaats van wat er vandaag
    # gepubliceerd is. Precies de schijnzekerheid waar dit project op stukloopt
    # — een groene test die iets anders toetst dan je denkt.
    #
    # `current_version()` leest `current.txt`, dezelfde aanwijzer die
    # `db verify` tegen de databank legt.

    @pytest.fixture
    def resultaat(self, factuur, heffingen):
        import json

        from energie_vlaanderen.data.paths import DataPaths
        from energie_vlaanderen.data.repository import DataRepository
        from energie_vlaanderen.gebruikers.berekening import Kostberekening
        from energie_vlaanderen.gebruikers.models import EnergieType
        from energie_vlaanderen.gebruikers.toml_io import lees_dossier
        from energie_vlaanderen.nettarieven.netbeheerder import (
            NetbeheerderRegister,
            standaard_gemeente_csv,
        )
        from energie_vlaanderen.settings import Settings

        profiel = ROOT / "gebruiker.toml"
        if not profiel.is_file():
            pytest.skip("gebruiker.toml ontbreekt (persoonlijk, staat niet in git).")

        settings = Settings.load(project_root=ROOT)
        actieve_versie = DataPaths.from_settings(settings).current_version()
        if not actieve_versie:
            pytest.skip("Geen actieve dataversie (current.txt ontbreekt).")
        vtest_dir = DataPaths.from_settings(settings).versions / actieve_versie
        gemeente_csv = standaard_gemeente_csv(settings.data_root)
        if not (vtest_dir / "vtest").is_dir() or not gemeente_csv.is_file():
            pytest.skip("Dataversie of DnbPerGemeente.csv ontbreekt.")

        # Elke tariefjaargang met haar eigen dataversie; de periode kruist de
        # jaarwissel van 2025 naar 2026.
        paden = DataPaths.from_settings(settings)
        per_jaar = {}
        for map_ in sorted(paden.versions.glob("*")) + sorted(paden.staging.glob("*")):
            for rapport in sorted((map_ / "tariffs").glob("tariffs_*_report.json")):
                try:
                    jaar = json.loads(rapport.read_text(encoding="utf-8")).get("tarief_jaar")
                except (OSError, json.JSONDecodeError):
                    continue
                if isinstance(jaar, int):
                    per_jaar[jaar] = map_ / "tariffs"
        if not {2025, 2026} <= set(per_jaar):
            pytest.skip("Nettarieven van 2025 én 2026 zijn nodig voor deze periode.")

        repos = {
            jaar: DataRepository(vtest_dir, gemeente_csv=gemeente_csv, tariff_dir=map_)
            for jaar, map_ in per_jaar.items()
        }
        dossier = lees_dossier(
            profiel,
            project_root=ROOT,
            netbeheerders=NetbeheerderRegister.load(gemeente_csv),
        )
        punt = dossier.punt(EnergieType.ELEKTRICITEIT)
        rekenaar = Kostberekening(
            repos[2026], heffingen,
            segment=str(dossier.gebruiker.segment),
            nettarieven_per_jaar=repos,
        )
        return rekenaar.bereken(
            punt,
            dossier.meter_van(punt),
            dossier.contracten_van(punt),
            dossier.opgaven_van(punt),
            date(2025, 6, 25),
            date(2026, 5, 1),
            extra_aannames=dossier.aannames,
        )

    def test_heffingen_komen_exact_uit(self, resultaat, factuur):
        """336,81 EUR — de regel "Toeslagen"."""
        verwacht = D(factuur["elektriciteit"]["componenten"]["toeslagen_eur"])
        assert money(resultaat.totalen["levies"]) == verwacht

    def test_de_injectievergoeding_komt_exact_uit(self, resultaat, factuur):
        """71,20 EUR over vier registerregels en twee tariefkaartversies."""
        verwacht = -D(factuur["elektriciteit"]["componenten"]["energie_injectie_eur"])
        assert money(resultaat.totalen["injection_credit"]) == verwacht

    def test_de_netkost_wijkt_minder_dan_een_euro_af(self, resultaat, factuur):
        """677,42 tegenover 678,09 EUR.

        Het restverschil zit in de verdeling van het verbruik over de
        jaarwissel: binnen de tweede tariefkaartperiode (28/10-30/04) wordt pro
        rata per dag geknipt op 01/01, terwijl dit gezin in november-december
        meer verbruikt dan in maart-april. Sluiten kan alleen met
        maandmeterstanden; de factuur geeft er twee periodes.
        """
        verwacht = D(factuur["elektriciteit"]["componenten"]["netwerkkosten_eur"])
        verschil = abs(resultaat.totalen["grid"] - verwacht)
        assert verschil < D("1.00"), f"netkost wijkt {verschil} af"

    def test_de_leverancierskost_wijkt_een_cent_af(self, resultaat, factuur):
        """De publieke V-test-prijzen van ENGIE Easy komen overeen met de
        tariefkaart die deze klant contractueel heeft.

        Vergeleken wordt energie-afname plus groene stroom plus WKK; kortingen
        en de periodecorrectie vallen buiten wat de engine kent.
        """
        componenten = factuur["elektriciteit"]["componenten"]
        verwacht = (
            D(componenten["energie_afname_eur"])
            + D(componenten["groene_stroom_eur"])
            + D(componenten["wkk_eur"])
        )
        verschil = abs(resultaat.totalen["supplier"] - verwacht)
        assert verschil <= D("0.05"), f"leverancierskost wijkt {verschil} af"

    def test_het_geheel_blijft_binnen_een_promille(self, resultaat, factuur):
        """Alle vergeleken posten samen: 0,033% van het factuurbedrag."""
        componenten = factuur["elektriciteit"]["componenten"]
        verwacht = (
            D(componenten["energie_afname_eur"])
            + D(componenten["groene_stroom_eur"])
            + D(componenten["wkk_eur"])
            + D(componenten["energie_injectie_eur"])
            + D(componenten["netwerkkosten_eur"])
            + D(componenten["toeslagen_eur"])
        )
        t = resultaat.totalen
        onze = t["supplier"] - t["injection_credit"] + t["grid"] + t["levies"]
        assert abs(onze - verwacht) / verwacht < D("0.001")


class TestRestverschilIsVerklaard:
    """Waar de laatste 0,67 EUR op de netkost vandaan komt.

    Het verschil zit niet in de tarieven en niet in de code. Het valt uiteen in
    twee stukken, en beide zijn na te rekenen uit de factuur zelf.
    """

    # Fluvius Midden-Vlaanderen, som van netgebruik + ODV normaal + toeslagen.
    TARIEF_2025 = D("0.0236764") + D("0.027722") + D("0.0014996")
    TARIEF_2026 = D("0.0248638") + D("0.0236385") + D("0.0013038")

    def test_het_capaciteitstarief_klopt_exact(self, factuur):
        """De toets die bewijst dat de tarieven en de tariefjaren juist zijn.

        Het capaciteitstarief hangt niet van het volume af, alleen van de
        gemeten piek en van hoeveel dagen in welk tariefjaar vallen. Onze
        berekening komt op 311,238 uit tegenover 311,23 op de factuur: acht
        duizendsten van een euro. Zit er iets fout in de tariefselectie of in
        de verdeling over de jaarwissel, dan zou het hier al blijken.
        """
        piek = D(factuur["elektriciteit"]["gemeten_maandpiek_kw"])
        # 25/06-31/12/2025 is 190 dagen, 01/01-30/04/2026 is 120 dagen.
        onze = piek * (
            D("190") / D("365") * D("49.0426291")
            + D("120") / D("365") * D("50.1239818")
        )
        assert abs(onze - D(factuur["elektriciteit"]["capaciteitstarief_eur"])) < D("0.01")

    def test_de_jaarwissel_verklaart_het_grootste_deel(self):
        """0,73 EUR: wij verdelen het volume naar dagen, de meter weet beter.

        Over de tweede tariefkaartperiode (28/10/2025-30/04/2026, 4.693 kWh)
        valt 65 van de 185 dagen nog in tariefjaar 2025. Naar dagen verdeeld
        geeft dat 238,84 EUR; de factuur rekent 239,57. Dat bedrag hoort bij een
        verdeling van 1.886 kWh in 2025 en 2.807 in 2026 — 40,2% van het volume
        in 35,1% van de dagen, precies wat je verwacht van een winter.

        De leverancier verdeelt tijdgrootheden (databeheer) naar dagen en
        volumegrootheden (distributiekosten) naar de werkelijke meterstand. Een
        meterstand op 31 december sluit dit gat; die staat niet op de factuur.
        """
        volume = D("4693")
        naar_dagen = volume * (
            D("65") * self.TARIEF_2025 + D("120") * self.TARIEF_2026
        ) / D("185")
        assert abs(naar_dagen - D("238.84")) < D("0.01")

        # De verdeling die de factuur impliceert.
        in_2025 = (D("239.57") - volume * self.TARIEF_2026) / (
            self.TARIEF_2025 - self.TARIEF_2026
        )
        assert D("1880") < in_2025 < D("1892")
        aandeel_volume = in_2025 / volume
        aandeel_dagen = D("65") / D("185")
        assert aandeel_volume > aandeel_dagen  # winter verbruikt zwaarder

    def test_de_rest_is_de_afronding_op_hele_kwh(self, factuur):
        """0,05 EUR: de factuur drukt de registers in hele kWh af.

        De eerste tariefkaartperiode (25/06-27/10/2025) ligt volledig in
        tariefjaar 2025 — geen jaargrens, geen verdeling, geen dubbelzinnigheid.
        Onze berekening geeft 2.124 kWh x 0,0528980 = 112,355 EUR; de factuur
        rekent 112,31. Dat bedrag hoort bij 2.123,14 kWh.

        De factuur drukt piek en dal elk afgerond af (710 + 1.414 = 2.124). Vier
        afgeronde registers geven makkelijk een kWh verschil op de som, en
        daarmee vier cent. Dit is de precisiegrens van het document zelf, niet
        van de berekening.
        """
        onze = D("2124") * self.TARIEF_2025
        verschil = onze - D("112.31")
        assert D("0.03") < verschil < D("0.06")

        impliciet_volume = D("112.31") / self.TARIEF_2025
        assert D("2123") < impliciet_volume < D("2124")


@pytest.mark.integration
class TestVolledigeSimulatieUitDeDatabank:
    """Dezelfde factuur, maar met de databank als bron in plaats van de CSV's.

    Dit is de test die er niet was. `energieprijs_kwh` stond een week lang op
    alle 25.937 tariefrijen leeg terwijl 681 tests groen bleven: geen enkele
    daarvan rekende iets uit met de databank. De CSV-weg werkte, dus de
    referentiefactuur klopte — en dat verhulde dat het eindstation leeg was.

    De drempels zijn dezelfde als bij de CSV-weg, en bewust tegen de *factuur*
    en niet tegen de CSV-uitkomst: zo blijft deze test staan wanneer de CSV-weg
    verdwijnt (zie `docs/plan databank als bron.md`, fase 3.2).
    """

    @pytest.fixture
    def resultaat(self, factuur, heffingen, db_conn):
        from energie_vlaanderen.data.db_repository import DbDataRepository
        from energie_vlaanderen.gebruikers.berekening import Kostberekening
        from energie_vlaanderen.gebruikers.models import EnergieType
        from energie_vlaanderen.gebruikers.toml_io import lees_dossier

        profiel = ROOT / "gebruiker.toml"
        if not profiel.is_file():
            pytest.skip("gebruiker.toml ontbreekt (persoonlijk, staat niet in git).")

        # De verbruiksperiode kruist de jaarwissel, dus beide tariefjaren zijn
        # nodig. Ze konden aanvankelijk niet naast elkaar bestaan: de
        # SCD2-upsert weigerde een oudere jaargang na een nieuwere.
        repos = {jaar: DbDataRepository(db_conn, tariefjaar=jaar) for jaar in (2025, 2026)}
        for jaar, repo in repos.items():
            if len(repo.dnb) == 0:
                pytest.skip(f"Geen nettarieven voor {jaar} in de databank.")

        dossier = lees_dossier(
            profiel, project_root=ROOT, netbeheerders=repos[2026].netbeheerders
        )
        punt = dossier.punt(EnergieType.ELEKTRICITEIT)
        return Kostberekening(
            repos[2026], heffingen,
            segment=str(dossier.gebruiker.segment),
            nettarieven_per_jaar=repos,
        ).bereken(
            punt, dossier.meter_van(punt), dossier.contracten_van(punt),
            dossier.opgaven_van(punt),
            date(2025, 6, 25), date(2026, 5, 1),
            extra_aannames=dossier.aannames,
        )

    def test_de_heffingen_komen_exact_uit(self, resultaat, factuur):
        """336,81 EUR — de regel "Toeslagen"."""
        verwacht = D(factuur["elektriciteit"]["componenten"]["toeslagen_eur"])
        assert money(resultaat.totalen["levies"]) == verwacht

    def test_de_leverancierskost_komt_uit_de_databank(self, resultaat, factuur):
        """De post die helemaal ontbrak: zonder `energieprijs_kwh` en zonder
        indexwaarde is er geen leverancierskost te berekenen."""
        componenten = factuur["elektriciteit"]["componenten"]
        verwacht = (
            D(componenten["energie_afname_eur"])
            + D(componenten["groene_stroom_eur"])
            + D(componenten["wkk_eur"])
        )
        assert resultaat.totalen["supplier"] > D("0"), (
            "De leverancierskost is nul. Draagt de databank de energieprijzen? "
            "Controleer met: energievergelijker db audit"
        )
        verschil = abs(resultaat.totalen["supplier"] - verwacht)
        assert verschil <= D("0.05"), f"leverancierskost wijkt {verschil} af"

    def test_de_netkost_wijkt_minder_dan_een_euro_af(self, resultaat, factuur):
        """Vereist beide tariefjaren; met alleen 2026 zou de eerste helft van de
        periode met het verkeerde jaar gerekend worden."""
        verwacht = D(factuur["elektriciteit"]["componenten"]["netwerkkosten_eur"])
        verschil = abs(resultaat.totalen["grid"] - verwacht)
        assert verschil < D("1.00"), f"netkost wijkt {verschil} af"

    def test_het_geheel_blijft_binnen_een_promille(self, resultaat, factuur):
        componenten = factuur["elektriciteit"]["componenten"]
        verwacht = (
            D(componenten["energie_afname_eur"])
            + D(componenten["groene_stroom_eur"])
            + D(componenten["wkk_eur"])
            + D(componenten["energie_injectie_eur"])
            + D(componenten["netwerkkosten_eur"])
            + D(componenten["toeslagen_eur"])
        )
        t = resultaat.totalen
        onze = t["supplier"] - t["injection_credit"] + t["grid"] + t["levies"]
        assert abs(onze - verwacht) / verwacht < D("0.001")
