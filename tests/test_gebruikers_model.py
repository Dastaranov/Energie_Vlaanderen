"""Tests voor het domeinmodel van de gebruikersbasis.

Wat hier vastligt zijn regels, geen tarieven: welke combinaties van gegevens
elkaar tegenspreken en dus niet mogen bestaan. De getallen die wel voorkomen
(4,218 en 2,5 kW) dragen hun herkomst in de assertie zelf.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal as D

import pytest

from energie_vlaanderen.gebruikers.models import (
    Aanname,
    Aansluitingspunt,
    AssetType,
    Contracttype,
    EnergieType,
    Exactheidsklasse,
    Gebruiker,
    GebruikersError,
    InstallatieAsset,
    Leveringscontract,
    Meter,
    Meterregime,
    OpgaveBron,
    Toestemming,
    Topologie,
    Verbruiksopgave,
    ean_controlecijfer,
    normaliseer_ean,
)


pytestmark = pytest.mark.dossier


@pytest.fixture
def gebruiker() -> Gebruiker:
    return Gebruiker()


class TestAansluitingspunt:
    def test_postcode_van_vier_cijfers_is_het_minimum(self, gebruiker):
        """Postcode is de sleutel waarop het nettarief geselecteerd wordt.

        Zonder geldige postcode is er geen netbeheerder en dus geen nettarief;
        Manifest §5.2 noemt postcode daarom verplicht.
        """
        punt = Aansluitingspunt(
            gebruiker_id=gebruiker.id,
            energie_type=EnergieType.ELEKTRICITEIT,
            postcode="9300",
        )
        assert punt.postcode == "9300"

        for ongeldig in ("930", "93000", "AB12", ""):
            with pytest.raises(GebruikersError):
                Aansluitingspunt(
                    gebruiker_id=gebruiker.id,
                    energie_type=EnergieType.ELEKTRICITEIT,
                    postcode=ongeldig,
                )

    def test_elektriciteit_en_gas_zijn_aparte_punten(self, gebruiker):
        """Eén EAN per energiedrager, dus twee aansluitingspunten.

        Er is bewust geen veld "heeft gas": het bestaan van een gaspunt ís dat
        antwoord, en een boolean ernaast zou de lijst kunnen tegenspreken.
        """
        punten = [
            Aansluitingspunt(gebruiker.id, energie, "9300")
            for energie in (EnergieType.ELEKTRICITEIT, EnergieType.GAS)
        ]
        assert {p.energie_type for p in punten} == {
            EnergieType.ELEKTRICITEIT,
            EnergieType.GAS,
        }
        assert punten[0].id != punten[1].id

    def test_aantal_fasen_is_1_of_3(self, gebruiker):
        """Een laagspanningsaansluiting is 1x230 V of 3x400 V — niets ertussen."""
        for fasen in (1, 3):
            Aansluitingspunt(gebruiker.id, EnergieType.ELEKTRICITEIT, "9300", aantal_fasen=fasen)
        with pytest.raises(GebruikersError):
            Aansluitingspunt(gebruiker.id, EnergieType.ELEKTRICITEIT, "9300", aantal_fasen=2)


class TestEan:
    def test_controlecijfer_volgt_de_gs1_mod10_regel(self):
        """GS1 General Specifications, mod-10 over de eerste 17 cijfers.

        Geen echt EAN als voorbeeld: dat zou een verzonnen nummer als geldig
        Belgisch toegangspunt laten doorgaan. De test bouwt er zelf een, en
        toetst dat één gewijzigd cijfer de controle laat falen — dat is precies
        wat een controlecijfer moet doen.
        """
        stam = "54144800000000000"
        cijfer = ean_controlecijfer(stam)
        ean = stam + str(cijfer)

        assert normaliseer_ean(ean) == ean

        # Eén cijfer verdraaien moet opvallen.
        verminkt = list(ean)
        verminkt[5] = str((int(verminkt[5]) + 1) % 10)
        with pytest.raises(GebruikersError):
            normaliseer_ean("".join(verminkt))

    def test_onbekende_ean_is_geldig(self):
        """Veel gebruikers kennen hun EAN niet, en de berekening heeft hem niet nodig."""
        assert normaliseer_ean(None) is None
        assert normaliseer_ean("") is None

    def test_verkeerde_lengte_wordt_geweigerd(self):
        with pytest.raises(GebruikersError):
            normaliseer_ean("5414480000000")


class TestMeter:
    def test_alleen_een_klassieke_meter_kan_terugdraaien(self, gebruiker):
        """Digitaal + PV valt niet onder het prosumententarief, klassiek wel.

        Zie `docs/price_model_low_voltage.md` §4.5. Deze combinatie verkeerd
        zetten scheelt honderden euro's per jaar, dus ze mag niet bestaan.
        """
        punt = Aansluitingspunt(gebruiker.id, EnergieType.ELEKTRICITEIT, "9300")
        Meter(punt.id, meterregime=Meterregime.KLASSIEK, terugdraaiend=True)
        with pytest.raises(GebruikersError):
            Meter(punt.id, meterregime=Meterregime.DIGITAAL, terugdraaiend=True)

    def test_standaardpieken_zijn_twee_verschillende_getallen(self, gebruiker):
        """4,218 kW is een schatting, 2,5 kW is de wettelijke ondergrens.

        4,218 kW is teruggerekend uit de capaciteitstarieven van de acht Vlaamse
        netbeheerders op vtest.be (2026-08-31) en is de piek waarmee die tool
        zijn standaardwoning doorrekent. 2,5 kW is de ondergrens van het
        capaciteitstarief. Toen ze één veld met dezelfde waarde waren, rekende
        elk profiel zonder eigen meetdata op de bodem — ongeveer 86 EUR per jaar
        te laag. Zie migratie 0015 en `domain/models.py`.
        """
        punt = Aansluitingspunt(gebruiker.id, EnergieType.ELEKTRICITEIT, "9300")
        meter = Meter(punt.id)
        assert meter.geschatte_maandpiek_kw == D("4.218")
        assert meter.minimum_maandpiek_kw == D("2.5")
        assert meter.geschatte_maandpiek_kw != meter.minimum_maandpiek_kw

    def test_alleen_digitaal_en_amr_meten_een_maandpiek(self, gebruiker):
        punt = Aansluitingspunt(gebruiker.id, EnergieType.ELEKTRICITEIT, "9300")
        assert Meter(punt.id, meterregime=Meterregime.DIGITAAL).heeft_gemeten_maandpiek
        assert Meter(punt.id, meterregime=Meterregime.AMR).heeft_gemeten_maandpiek
        assert not Meter(punt.id, meterregime=Meterregime.KLASSIEK).heeft_gemeten_maandpiek


class TestInstallatie:
    def test_pv_zonder_kwp_bestaat_niet(self, gebruiker):
        """SPP geeft productie *per kWp*; zonder kWp is er niets te schalen."""
        punt = Aansluitingspunt(gebruiker.id, EnergieType.ELEKTRICITEIT, "9300")
        with pytest.raises(GebruikersError):
            InstallatieAsset(punt.id, AssetType.PV)
        InstallatieAsset(punt.id, AssetType.PV, kwp=D("4.6"))

    def test_batterij_zonder_topologie_bestaat_niet(self, gebruiker):
        """AC- en DC-gekoppeld verschillen in welke kWh de meter passeert."""
        punt = Aansluitingspunt(gebruiker.id, EnergieType.ELEKTRICITEIT, "9300")
        with pytest.raises(GebruikersError):
            InstallatieAsset(punt.id, AssetType.BATTERIJ, merk="Marstek", model="Venus E")
        InstallatieAsset(
            punt.id,
            AssetType.BATTERIJ,
            merk="Marstek",
            model="Venus E",
            topologie=Topologie.AC_GEKOPPELD,
        )


class TestContract:
    def test_vast_en_tou_bevriezen_hun_prijs(self, gebruiker):
        """De kern van een correcte historische kost.

        Een vast contract volgt de actuele tariefkaart niet: de prijs ligt vast
        bij ondertekening. Een variabel of dynamisch contract volgt wél de
        markt, per indexatieperiode.
        """
        punt = Aansluitingspunt(gebruiker.id, EnergieType.ELEKTRICITEIT, "9300")
        bevroren = Leveringscontract(
            punt.id, "Bolt", "Bolt Vast", Contracttype.VAST, date(2026, 1, 1)
        )
        vrij = Leveringscontract(
            punt.id, "Bolt", "Bolt Flex", Contracttype.VARIABEL, date(2026, 1, 1)
        )
        assert bevroren.prijs_bevriest
        assert not vrij.prijs_bevriest

    def test_peildatum_valt_terug_op_de_startdatum(self, gebruiker):
        punt = Aansluitingspunt(gebruiker.id, EnergieType.ELEKTRICITEIT, "9300")
        zonder = Leveringscontract(
            punt.id, "Bolt", "Bolt Vast", Contracttype.VAST, date(2026, 3, 1)
        )
        met = Leveringscontract(
            punt.id,
            "Bolt",
            "Bolt Vast",
            Contracttype.VAST,
            date(2026, 3, 1),
            tariefkaart_geldig_van=date(2026, 1, 1),
        )
        assert zonder.peil_tariefkaart() == date(2026, 3, 1)
        assert met.peil_tariefkaart() == date(2026, 1, 1)

    def test_periode_moet_vooruit_lopen(self, gebruiker):
        punt = Aansluitingspunt(gebruiker.id, EnergieType.ELEKTRICITEIT, "9300")
        with pytest.raises(GebruikersError):
            Leveringscontract(
                punt.id,
                "Bolt",
                "Bolt Vast",
                Contracttype.VAST,
                date(2026, 8, 1),
                date(2026, 1, 1),
            )


class TestExactheidsklasse:
    def test_de_zwakste_schakel_bepaalt_de_klasse(self):
        """Manifest §5.8: één geschatte invoer maakt het hele resultaat geschat."""
        assert (
            Exactheidsklasse.zwakste(
                [Exactheidsklasse.EXACT, Exactheidsklasse.GESCHAT, Exactheidsklasse.EXACT]
            )
            is Exactheidsklasse.GESCHAT
        )
        assert (
            Exactheidsklasse.zwakste([Exactheidsklasse.EXACT, Exactheidsklasse.EXACT])
            is Exactheidsklasse.EXACT
        )

    def test_geen_klasse_is_geen_exacte_klasse(self):
        """Een leeg resultaat mag niet stil als exact doorgaan."""
        with pytest.raises(GebruikersError):
            Exactheidsklasse.zwakste([])

    def test_manuele_opgave_is_gereconstrueerd_geen_meting(self, gebruiker):
        """Een doorgegeven jaarverbruik is de beste opgave, geen bewijs."""
        punt = Aansluitingspunt(gebruiker.id, EnergieType.ELEKTRICITEIT, "9300")
        opgave = Verbruiksopgave(
            punt.id,
            date(2026, 1, 1),
            date(2027, 1, 1),
            afname_dag_kwh=D("3000"),
            bron=OpgaveBron.MANUEEL,
        )
        assert opgave.exactheidsklasse is Exactheidsklasse.GERECONSTRUEERD

    def test_onvolledige_meting_is_geen_exacte_meting(self, gebruiker):
        """Manifest §9: onvoldoende meetdekking wordt zichtbaar gerapporteerd."""
        punt = Aansluitingspunt(gebruiker.id, EnergieType.ELEKTRICITEIT, "9300")
        volledig = Verbruiksopgave(
            punt.id, date(2026, 1, 1), date(2027, 1, 1), bron=OpgaveBron.METING
        )
        deels = Verbruiksopgave(
            punt.id,
            date(2026, 1, 1),
            date(2027, 1, 1),
            bron=OpgaveBron.METING,
            dekkingsgraad=D("0.6"),
        )
        assert volledig.exactheidsklasse is Exactheidsklasse.EXACT
        assert deels.exactheidsklasse is Exactheidsklasse.GERECONSTRUEERD


class TestAanname:
    def test_een_aanname_zonder_bron_bestaat_niet(self):
        """Een ingevulde waarde zonder herkomst is een gok die zich als gegeven voordoet."""
        Aanname(veld="pv_kwp", waarde="4.6", bron="datasheet")
        with pytest.raises(GebruikersError):
            Aanname(veld="pv_kwp", waarde="4.6", bron="")


class TestToestemming:
    def test_ingetrokken_toestemming_geldt_niet_meer(self, gebruiker):
        """ROADMAP §9: een ingetrokken mandaat stopt toekomstige opvragingen."""
        toestemming = Toestemming(
            gebruiker.id, "meterdata", date(2026, 1, 1), ingetrokken_op=date(2026, 6, 1)
        )
        assert toestemming.geldig_op(date(2026, 3, 1))
        assert not toestemming.geldig_op(date(2026, 6, 1))
        assert not toestemming.geldig_op(date(2025, 12, 31))
