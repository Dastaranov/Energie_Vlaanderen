"""Tests voor het inlezen van `gebruiker.toml` als gebruikersdossier.

Het bestaande bestandsformaat moet blijven werken — het staat in de repo en de
batterijsimulator leest het. Wat erbij komt is optioneel.

De tweede vraag die hier vastligt: wat er *niet* in het bestand staat en de
berekening wél nodig heeft, wordt ingevuld met een `Aanname` die haar bron
draagt. Dat is de directe uitwerking van "een deel van de data zal geraden
moeten worden": een schatting is geen slechter getal, ze is een getal van een
andere klasse.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal as D

import pytest

from energie_vlaanderen.gebruikers.models import (
    AssetType,
    Contracttype,
    EnergieType,
    GebruikersError,
    Meterregime,
    Registerschema,
    Segment,
    Topologie,
)
from energie_vlaanderen.gebruikers.toml_io import lees_dossier

MINIMAAL = """
[gebruiker]
postcode = "9300"
gemeente = "Aalst"

[aansluiting]
elektriciteit = true
gas = false
meter = "digitaal"
"""


pytestmark = pytest.mark.dossier


def schrijf(tmp_path, inhoud: str):
    pad = tmp_path / "gebruiker.toml"
    pad.write_text(inhoud, encoding="utf-8")
    return pad


class TestMinimum:
    def test_postcode_en_een_aansluiting_volstaan(self, tmp_path):
        dossier = lees_dossier(schrijf(tmp_path, MINIMAAL))
        (punt,) = dossier.aansluitingspunten
        assert punt.postcode == "9300"
        assert punt.energie_type is EnergieType.ELEKTRICITEIT
        assert dossier.gebruiker.segment is Segment.WONING

    def test_zonder_energiedrager_valt_er_niets_te_berekenen(self, tmp_path):
        pad = schrijf(
            tmp_path,
            "[gebruiker]\npostcode = \"9300\"\n\n[aansluiting]\n"
            "elektriciteit = false\ngas = false\n",
        )
        with pytest.raises(GebruikersError, match="Minstens elektriciteit of gas"):
            lees_dossier(pad)

    def test_een_ontbrekend_bestand_is_een_duidelijke_fout(self, tmp_path):
        with pytest.raises(GebruikersError, match="niet gevonden"):
            lees_dossier(tmp_path / "bestaat_niet.toml")


class TestGebruikerId:
    """Een vaste `id` maakt de gebruiker herkenbaar over meerdere inlezingen
    van hetzelfde bestand heen — nodig voor de simulatiehistoriek
    (`scenario.herkomst`), niet voor de berekening zelf."""

    def test_zonder_id_krijgt_elke_inlezing_een_andere_gebruiker(self, tmp_path):
        pad = schrijf(tmp_path, MINIMAAL)
        eerste = lees_dossier(pad)
        tweede = lees_dossier(pad)
        assert eerste.gebruiker.id != tweede.gebruiker.id

    def test_met_id_blijft_de_gebruiker_dezelfde_over_meerdere_inlezingen(self, tmp_path):
        inhoud = MINIMAAL.replace(
            "[gebruiker]\n", '[gebruiker]\nid = "12345678-1234-5678-1234-567812345678"\n',
        )
        pad = schrijf(tmp_path, inhoud)
        eerste = lees_dossier(pad)
        tweede = lees_dossier(pad)
        assert str(eerste.gebruiker.id) == "12345678-1234-5678-1234-567812345678"
        assert eerste.gebruiker.id == tweede.gebruiker.id

    def test_een_ongeldige_id_is_een_duidelijke_fout(self, tmp_path):
        inhoud = MINIMAAL.replace("[gebruiker]\n", '[gebruiker]\nid = "geen-uuid"\n')
        pad = schrijf(tmp_path, inhoud)
        with pytest.raises(GebruikersError, match="geldige UUID"):
            lees_dossier(pad)


class TestAansluitingen:
    def test_gas_krijgt_zijn_eigen_aansluitingspunt(self, tmp_path):
        """Eén EAN per energiedrager, dus twee punten — geen boolean-veld."""
        pad = schrijf(tmp_path, MINIMAAL.replace("gas = false", "gas = true"))
        dossier = lees_dossier(pad)
        assert {p.energie_type for p in dossier.aansluitingspunten} == {
            EnergieType.ELEKTRICITEIT,
            EnergieType.GAS,
        }

    def test_analoog_wordt_het_klassieke_meterregime(self, tmp_path):
        """Het bestaande formaat kent alleen digitaal/analoog; het domein meer."""
        pad = schrijf(tmp_path, MINIMAAL.replace('meter = "digitaal"', 'meter = "analoog"'))
        (meter,) = lees_dossier(pad).meters
        assert meter.meterregime is Meterregime.KLASSIEK

    def test_terugdraaiend_kan_niet_bij_een_digitale_meter(self, tmp_path):
        """Digitaal + PV valt niet onder het prosumententarief."""
        pad = schrijf(tmp_path, MINIMAAL + "terugdraaiend = true\n")
        with pytest.raises(GebruikersError, match="klassieke"):
            lees_dossier(pad)

    def test_registerschema_is_los_van_het_metertype(self, tmp_path):
        pad = schrijf(tmp_path, MINIMAAL + 'registerschema = "exclusief_nacht"\n')
        (meter,) = lees_dossier(pad).meters
        assert meter.registerschema is Registerschema.EXCLUSIEF_NACHT
        assert meter.meterregime is Meterregime.DIGITAAL

    def test_gebouwkenmerken_worden_ingelezen(self, tmp_path):
        pad = schrijf(
            tmp_path,
            MINIMAAL + 'bebouwingstype = "halfopen"\nbewoonbare_oppervlakte_m2 = 350\n',
        )
        (punt,) = lees_dossier(pad).aansluitingspunten
        assert punt.bebouwingstype == "halfopen"
        assert punt.bewoonbare_oppervlakte_m2 == D("350")

    def test_zonder_gebouwkenmerken_blijven_ze_leeg(self, tmp_path):
        (punt,) = lees_dossier(schrijf(tmp_path, MINIMAAL)).aansluitingspunten
        assert punt.bebouwingstype == ""
        assert punt.bewoonbare_oppervlakte_m2 is None


class TestZonnepaneelStrings:
    """`[[aansluiting.zonnepaneel]]` — een PV-string per oriëntatie, náást de
    bestaande enkelvoudige `pv_kwp`/`omvormer_kva`."""

    def test_meerdere_strings_worden_aparte_pv_assets(self, tmp_path):
        inhoud = MINIMAAL + (
            "\n[[aansluiting.zonnepaneel]]\n"
            "kwp = 4.5\nomvormer_kva = 4.0\nrichting = \"oost\"\n"
            "\n[[aansluiting.zonnepaneel]]\n"
            "kwp = 4.2\nomvormer_kva = 4.0\nrichting = \"west\"\n"
        )
        dossier = lees_dossier(schrijf(tmp_path, inhoud))
        pv_assets = [a for a in dossier.assets if a.type is AssetType.PV]
        assert len(pv_assets) == 2
        assert {a.richting for a in pv_assets} == {"oost", "west"}
        assert {a.kwp for a in pv_assets} == {D("4.5"), D("4.2")}

    def test_werkt_naast_de_bestaande_enkelvoudige_vorm(self, tmp_path):
        inhoud = (
            MINIMAAL.replace("meter = \"digitaal\"", "meter = \"digitaal\"\nzonnepanelen = true\npv_kwp = 5.0\n")
            + "\n[[aansluiting.zonnepaneel]]\nkwp = 4.5\nrichting = \"oost\"\n"
        )
        dossier = lees_dossier(schrijf(tmp_path, inhoud))
        pv_assets = [a for a in dossier.assets if a.type is AssetType.PV]
        assert len(pv_assets) == 2
        assert any(a.richting == "" and a.kwp == D("5.0") for a in pv_assets)
        assert any(a.richting == "oost" and a.kwp == D("4.5") for a in pv_assets)

    def test_zonder_kwp_is_een_duidelijke_fout(self, tmp_path):
        inhoud = MINIMAAL + "\n[[aansluiting.zonnepaneel]]\nrichting = \"oost\"\n"
        with pytest.raises(GebruikersError, match="geen kwp"):
            lees_dossier(schrijf(tmp_path, inhoud))

    def test_zonder_elektriciteitsaansluiting_is_een_fout(self, tmp_path):
        inhoud = (
            "[gebruiker]\npostcode = \"9300\"\n\n[aansluiting]\n"
            "elektriciteit = false\ngas = true\nmeter = \"digitaal\"\n"
            "\n[[aansluiting.zonnepaneel]]\nkwp = 4.5\n"
        )
        with pytest.raises(GebruikersError, match="elektriciteitsaansluiting"):
            lees_dossier(schrijf(tmp_path, inhoud))

    def test_een_onbekende_sleutel_wordt_geweigerd(self, tmp_path):
        inhoud = MINIMAAL + "\n[[aansluiting.zonnepaneel]]\nkwp = 4.5\nkleur = \"blauw\"\n"
        with pytest.raises(GebruikersError, match="kent de sleutel"):
            lees_dossier(schrijf(tmp_path, inhoud))


class TestGastoestellen:
    """`[[aansluiting.gastoestel]]` — een verwarmingstoestel op gas, los van
    het bestaande gasverbruik-jaartotaal."""

    def _met_gas(self, extra: str) -> str:
        return (
            "[gebruiker]\npostcode = \"9300\"\ngemeente = \"Aalst\"\n\n[aansluiting]\n"
            "elektriciteit = true\ngas = true\nmeter = \"digitaal\"\n" + extra
        )

    def test_kachel_en_ketel_worden_aparte_assets(self, tmp_path):
        inhoud = self._met_gas(
            "\n[[aansluiting.gastoestel]]\ntype = \"kachel\"\nvermogen_kw = 6\n"
            "doel = \"ruimteverwarming\"\n"
            "\n[[aansluiting.gastoestel]]\ntype = \"ketel\"\nvermogen_kw = 25\n"
            "doel = \"beide\"\n"
        )
        dossier = lees_dossier(schrijf(tmp_path, inhoud))
        gastoestellen = [a for a in dossier.assets if a.type is AssetType.GASTOESTEL]
        assert len(gastoestellen) == 2
        kachel = next(a for a in gastoestellen if a.model == "kachel")
        assert kachel.vermogen_kw == D("6")
        assert kachel.doel == "ruimteverwarming"
        ketel = next(a for a in gastoestellen if a.model == "ketel")
        assert ketel.vermogen_kw == D("25")
        assert ketel.doel == "beide"

    def test_hangt_aan_het_gaspunt_niet_het_elektriciteitspunt(self, tmp_path):
        inhoud = self._met_gas("\n[[aansluiting.gastoestel]]\ntype = \"ketel\"\nvermogen_kw = 25\n")
        dossier = lees_dossier(schrijf(tmp_path, inhoud))
        (asset,) = [a for a in dossier.assets if a.type is AssetType.GASTOESTEL]
        gas_punt = next(p for p in dossier.aansluitingspunten if p.energie_type is EnergieType.GAS)
        assert asset.aansluitingspunt_id == gas_punt.id

    def test_zonder_gasaansluiting_is_een_fout(self, tmp_path):
        inhoud = MINIMAAL + "\n[[aansluiting.gastoestel]]\ntype = \"ketel\"\nvermogen_kw = 25\n"
        with pytest.raises(GebruikersError, match="gasaansluiting"):
            lees_dossier(schrijf(tmp_path, inhoud))


class TestAannames:
    def test_de_standaardmaandpiek_draagt_haar_bron(self, tmp_path):
        """4,218 kW is teruggerekend uit vtest.be, niet gekozen.

        De wettelijke ondergrens van 2,5 kW wordt hier bewust níet als
        schatting gebruikt: dat is een bodem, geen piek. Als standaardwaarde
        maakte ze elke factuur ongeveer 86 EUR per jaar te laag.
        """
        dossier = lees_dossier(schrijf(tmp_path, MINIMAAL))
        (aanname,) = [a for a in dossier.aannames if a.veld == "geschatte_maandpiek_kw"]
        assert aanname.waarde == "4.218"
        assert aanname.geverifieerd
        assert "vtest.be" in aanname.bron

    def test_pv_zonder_kwp_leunt_op_de_omvormer_en_zegt_dat(self, tmp_path):
        """Panelen worden vaak ruimer gedimensioneerd dan de omvormer, dus dit
        onderschat de productie eerder dan ze te overschatten."""
        pad = schrijf(
            tmp_path, MINIMAAL + "zonnepanelen = true\nomvormer_kva = 5.0\n"
        )
        dossier = lees_dossier(pad)
        (pv,) = [a for a in dossier.assets if a.type is AssetType.PV]
        assert pv.kwp == D("5.0")
        (aanname,) = [a for a in dossier.aannames if a.veld == "pv_kwp"]
        assert not aanname.geverifieerd

    def test_een_opgegeven_kwp_geeft_geen_aanname(self, tmp_path):
        pad = schrijf(
            tmp_path,
            MINIMAAL + "zonnepanelen = true\nomvormer_kva = 5.0\npv_kwp = 4.6\n",
        )
        dossier = lees_dossier(pad)
        (pv,) = [a for a in dossier.assets if a.type is AssetType.PV]
        assert pv.kwp == D("4.6")
        assert not [a for a in dossier.aannames if a.veld == "pv_kwp"]

    def test_zonnepanelen_zonder_enig_vermogen_stopt(self, tmp_path):
        """SPP geeft opbrengst per kWp; zonder vermogen is er niets te schalen."""
        pad = schrijf(tmp_path, MINIMAAL + "zonnepanelen = true\n")
        with pytest.raises(GebruikersError, match="pv_kwp"):
            lees_dossier(pad)

    def test_batterij_zonder_topologie_wordt_voorzichtig_aangenomen(self, tmp_path):
        """AC-gekoppeld telt het omvormerverlies mee en geeft dus de laagste
        opbrengst; DC of hybride aannemen zou het resultaat gunstiger maken dan
        verantwoord is."""
        pad = schrijf(
            tmp_path,
            MINIMAAL + '\n[aansluiting.batterij]\nmerk = "Marstek"\nmodel = "Venus E"\n',
        )
        dossier = lees_dossier(pad)
        (batterij,) = [a for a in dossier.assets if a.type is AssetType.BATTERIJ]
        assert batterij.topologie is Topologie.AC_GEKOPPELD
        (aanname,) = [a for a in dossier.aannames if a.veld == "batterij.topologie"]
        assert not aanname.geverifieerd


class TestContracten:
    def test_een_lijst_met_periodes_wordt_ingelezen(self, tmp_path):
        pad = schrijf(
            tmp_path,
            MINIMAAL
            + """
[[contract.elektriciteit]]
leverancier = "Bolt"
product = "Bolt Vast"
type = "vast"
van = "2026-01-01"
tot = "2026-08-01"
tariefkaart_van = "2026-01-01"

[[contract.elektriciteit]]
leverancier = "Aspiravi Energy"
product = "Eco Plus flex"
type = "variabel"
van = "2026-08-01"
""",
        )
        dossier = lees_dossier(pad)
        contracten = dossier.contracten
        assert len(contracten) == 2
        assert contracten[0].contracttype is Contracttype.VAST
        assert contracten[0].geldig_tot == date(2026, 8, 1)
        assert contracten[0].tariefkaart_geldig_van == date(2026, 1, 1)
        assert contracten[1].geldig_tot is None

    def test_het_oude_huidig_contract_blijft_werken(self, tmp_path):
        """De bestaande bestandsvorm mag niet breken."""
        pad = schrijf(
            tmp_path,
            MINIMAAL
            + """
[huidig_contract.elektriciteit]
leverancier = "Onbekend"
product = "Onbekend"
type = "variabel"
startdatum = "2025-01-01"
""",
        )
        (contract,) = lees_dossier(pad).contracten
        assert contract.geldig_van == date(2025, 1, 1)
        assert contract.geldig_tot is None

    def test_hetzelfde_contract_twee_keer_genoteerd_wordt_niet_verdubbeld(self, tmp_path):
        """Anders zouden [[contract.*]] en [huidig_contract.*] elkaar overlappen."""
        pad = schrijf(
            tmp_path,
            MINIMAAL
            + """
[[contract.elektriciteit]]
leverancier = "Bolt"
product = "Bolt Vast"
type = "vast"
van = "2026-01-01"

[huidig_contract.elektriciteit]
leverancier = "Bolt"
product = "Bolt Vast"
type = "vast"
startdatum = "2026-01-01"
""",
        )
        assert len(lees_dossier(pad).contracten) == 1

    def test_een_contract_voor_een_afwezige_energiedrager_is_een_fout(self, tmp_path):
        pad = schrijf(
            tmp_path,
            MINIMAAL
            + """
[[contract.gas]]
leverancier = "Bolt"
product = "Bolt Gas"
type = "vast"
van = "2026-01-01"
""",
        )
        with pytest.raises(GebruikersError, match="staat niet aan"):
            lees_dossier(pad)


class TestVerbruik:
    def test_een_jaarverbruik_wordt_een_opgave_over_het_kalenderjaar(self, tmp_path):
        pad = schrijf(
            tmp_path,
            MINIMAAL
            + "\n[verbruik]\njaar = 2026\nafname_dag_kwh = 2000\nafname_nacht_kwh = 1000\n",
        )
        (opgave,) = lees_dossier(pad).verbruiksopgaven
        assert opgave.periode_van == date(2026, 1, 1)
        assert opgave.periode_tot == date(2027, 1, 1)
        assert opgave.afname_kwh == D("3000")

    def test_een_jaarverbruik_zonder_jaartal_wordt_geweigerd(self, tmp_path):
        """Zonder jaartal is niet te bepalen welke tarieven en heffingen gelden."""
        pad = schrijf(tmp_path, MINIMAAL + "\n[verbruik]\nafname_dag_kwh = 2000\n")
        with pytest.raises(GebruikersError, match="jaar"):
            lees_dossier(pad)

    def test_verbruik_wordt_als_decimal_ingelezen_niet_als_float(self, tmp_path):
        """Via de tekstvorm: `Decimal(5.1)` geeft 5.0999999..., `Decimal("5.1")` niet."""
        pad = schrijf(
            tmp_path, MINIMAAL + "\n[verbruik]\njaar = 2026\nafname_dag_kwh = 2000.1\n"
        )
        (opgave,) = lees_dossier(pad).verbruiksopgaven
        assert opgave.afname_dag_kwh == D("2000.1")


class TestVoorbeeldbestand:
    def test_het_meegeleverde_voorbeeld_leest_zonder_fouten(self):
        """`gebruiker.voorbeeld.toml` toont de volledige vorm; het moet werken."""
        from pathlib import Path

        pad = Path(__file__).resolve().parents[1] / "gebruiker.voorbeeld.toml"
        if not pad.is_file():
            pytest.skip("gebruiker.voorbeeld.toml ontbreekt in deze werkkopie.")
        dossier = lees_dossier(pad)
        assert len(dossier.contracten) == 2
        assert dossier.verbruiksopgaven
        assert any(a.type is AssetType.BATTERIJ for a in dossier.assets)
