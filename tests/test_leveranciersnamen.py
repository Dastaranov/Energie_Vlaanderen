"""Tests voor het normaliseren van leveranciersnamen.

VREG schrijft dezelfde leverancier op meerdere manieren. Alle gevallen
hieronder komen letterlijk uit de V-test-export van augustus 2026; ze zijn
geen verzonnen randgevallen maar de werkelijke inhoud van de kolom
`Handelsnaam`.

Zonder normalisatie kreeg één leverancier meerdere rijen in de databank en
raakten zijn producten daarover verdeeld — wat de vreg_id-koppeling liet
klappen met een CardinalityViolation.
"""

from __future__ import annotations

import pytest

from energie_vlaanderen.utility.normalizer import (
    leverancier_sleutel,
    ontleed_leveranciersnaam,
    split_leveranciersnaam,
)


class TestSplitsen:
    @pytest.mark.parametrize(
        ("ruw", "naam", "entiteit"),
        [
            ("ENGIE (handelsnaam van Electrabel)", "ENGIE", "Electrabel"),
            ("Mega (handelsnaam van Power Online)", "Mega", "Power Online"),
            (
                "Power2You (handelsnaam van Energy Together)",
                "Power2You",
                "Energy Together",
            ),
            (
                'Wind voor "A" (handelsnaam van Aspiravi Energy)',
                'Wind voor "A"',
                "Aspiravi Energy",
            ),
            (
                "evident energie (handelsnaam van Energy Together)",
                "evident energie",
                "Energy Together",
            ),
        ],
    )
    def test_haalt_de_juridische_entiteit_eruit(self, ruw, naam, entiteit):
        assert split_leveranciersnaam(ruw) == (naam, entiteit)

    @pytest.mark.parametrize(
        "naam",
        ["Bolt", "Luminus", "OCTA+ ENERGIE", "Ecofix Gas & Power", "Energie.be"],
    )
    def test_naam_zonder_achtervoegsel_blijft_ongewijzigd(self, naam):
        assert split_leveranciersnaam(naam) == (naam, None)

    def test_lege_waarde(self):
        assert split_leveranciersnaam("") == ("", None)
        assert split_leveranciersnaam(None) == ("", None)

    def test_achtervoegsel_midden_in_de_naam_wordt_niet_geraakt(self):
        """Het patroon staat aan het eind; alleen daar is het een annotatie."""
        naam = "X (handelsnaam van Y) Z"

        assert split_leveranciersnaam(naam) == (naam, None)


class TestSleutel:
    def test_korte_en_lange_schrijfwijze_delen_een_sleutel(self):
        """Het geval dat producten over twee leveranciers verdeelde."""
        assert leverancier_sleutel("ENGIE") == leverancier_sleutel(
            "ENGIE (handelsnaam van Electrabel)"
        )

    def test_hoofdletters_maken_geen_verschil(self):
        """"Dots Energy" (36 rijen) en "Dots energy" (38) staan beide in de export."""
        assert leverancier_sleutel("Dots Energy") == leverancier_sleutel("Dots energy")

    def test_verschillende_merken_blijven_gescheiden(self):
        """Zeven merken delen de entiteit Energy Together; het zijn er zeven.

        En 'Wind voor "A"' verkoopt onder Aspiravi Energy, maar Aspiravi
        Energy verkoopt daarnaast onder eigen naam. Samenvoegen zou twee
        aanbieders tot één maken.
        """
        assert leverancier_sleutel('Wind voor "A" (handelsnaam van Aspiravi Energy)') != (
            leverancier_sleutel("Aspiravi Energy")
        )
        assert leverancier_sleutel("Power2You (handelsnaam van Energy Together)") != (
            leverancier_sleutel("HOA Energy (handelsnaam van Energy Together)")
        )

    def test_gelijkende_namen_worden_niet_gegokt(self):
        """"Belvus" en "Belvus Energie" staan allebei in de export.

        Ze zijn mogelijk dezelfde aanbieder, maar er is geen bron die dat
        zegt. Samenvoegen op gelijkenis zou een aanname zijn die in de
        databank niet meer als aanname herkenbaar is.
        """
        assert leverancier_sleutel("Belvus") != leverancier_sleutel("Belvus Energie")


class TestVoorheenEnOnbekend:
    """"(voorheen X)" komt in de export van augustus 2026 niet voor, maar wel
    in de praktijk. Het betekent iets anders dan "(handelsnaam van X)": het
    eerste zegt hoe de aanbieder vroeger heette, het tweede onder welke
    juridische entiteit hij vandaag verkoopt. Ze op één veld zetten zou die
    twee betekenissen platslaan."""

    def test_voorheen_gaat_naar_een_eigen_veld(self):
        ontleed = ontleed_leveranciersnaam("ENGIE (voorheen Electrabel)")

        assert ontleed.naam == "ENGIE"
        assert ontleed.voormalige_naam == "Electrabel"
        assert ontleed.juridische_entiteit is None

    def test_handelsnaam_en_voorheen_worden_niet_verward(self):
        handelsnaam = ontleed_leveranciersnaam("ENGIE (handelsnaam van Electrabel)")
        voorheen = ontleed_leveranciersnaam("ENGIE (voorheen Electrabel)")

        assert handelsnaam.juridische_entiteit == "Electrabel"
        assert handelsnaam.voormalige_naam is None
        assert voorheen.voormalige_naam == "Electrabel"
        assert voorheen.juridische_entiteit is None

    def test_beide_annotaties_achter_elkaar(self):
        ontleed = ontleed_leveranciersnaam(
            "Merk (voorheen Oud) (handelsnaam van Entiteit)"
        )

        assert ontleed.naam == "Merk"
        assert ontleed.juridische_entiteit == "Entiteit"
        assert ontleed.voormalige_naam == "Oud"

    def test_onbekende_annotatie_wordt_gemeld_maar_niet_weggegooid(self):
        """Weglaten zou informatie verzinnen; stil laten staan zou een nieuwe
        schrijfwijze een tweede leverancier maken. Dus: laten staan én melden."""
        ontleed = ontleed_leveranciersnaam("Luminus (dochter van EDF)")

        assert ontleed.naam == "Luminus (dochter van EDF)"
        assert ontleed.onbekende_annotatie == "dochter van EDF"

    def test_gewone_naam_heeft_geen_onbekende_annotatie(self):
        assert ontleed_leveranciersnaam("Bolt").onbekende_annotatie is None
