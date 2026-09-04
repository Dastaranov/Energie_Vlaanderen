"""De feitelijke gegevens uit een tariefkaart lezen.

Wat een kaart draagt en de V-test-export niet, is de **bevroren** formule van
een lopend contract. Achtentwintig leveranciers, achtentwintig opmaken — maar
de formule komt in drie schrijfwijzen voor, en meer zijn het er niet.

De getallen in deze tests komen uit de gearchiveerde kaarten zelf; bij elke
staat welke leverancier hem zo afdrukt.
"""

from __future__ import annotations

from decimal import Decimal as D

import pytest

from energie_vlaanderen.ingest.tariefkaart_parser import parse_kaart

pytestmark = pytest.mark.parsers


class TestDeDrieSchrijfwijzen:
    def test_vorm_a_coefficient_eerst(self):
        """Eneco: `(0,102 X BELPEX-RLP-M + 3,001)`. Ook Ebem, zonder maalteken."""
        inhoud = parse_kaart("Tariefformule (0,102 X BELPEX-RLP-M + 3,001) X 1,06")
        (formule,) = inhoud.formules
        assert (formule.a, formule.index_naam, formule.z) == (D("0.102"), "BELPEX-RLP-M", D("3.001"))
        assert formule.vorm == "A"

    def test_vorm_a_zonder_maalteken(self):
        """Ebem: `0,110 BelpexRLP0 + 2,2` — de index volgt direct op het getal."""
        (formule,) = parse_kaart("Enkelvoudige teller | 0,110 BelpexRLP0 + 2,2").formules
        assert (formule.a, formule.index_naam, formule.z) == (D("0.110"), "BelpexRLP0", D("2.2"))

    def test_vorm_b_index_eerst(self):
        """Bolt: `Belpex * 1,168 + 16,90`. Ook OCTA+."""
        (formule,) = parse_kaart("Tariefformule Belpex * 1,168 + 16,90").formules
        assert (formule.a, formule.z, formule.vorm) == (D("1.168"), D("16.90"), "B")
        assert "Belpex" in formule.index_naam

    def test_vorm_c_constante_eerst(self):
        """ENGIE: `- Enkelvoudig = -1,5470 + (0,0449 x EPEXDAM)`."""
        (formule,) = parse_kaart("- Enkelvoudig = -1,5470 + (0,0449 x EPEXDAM)").formules
        assert (formule.a, formule.index_naam, formule.vorm) == (D("0.0449"), "EPEXDAM", "C")
        assert formule.z == D("-1.5470")

    def test_een_regel_levert_niet_drie_keer_dezelfde_formule(self):
        """De vormen overlappen: C herkent wat B en A ook half zouden matchen.

        Zonder die uitsluiting staat dezelfde formule er drie keer in, en dan
        telt elke samenvatting erover verkeerd.
        """
        inhoud = parse_kaart("Enkelvoudig = -1,5470 + (0,0449 x EPEXDAM)")
        assert len(inhoud.formules) == 1

    def test_een_negatieve_constante_houdt_haar_teken(self):
        """Injectieformules staan bijna allemaal met een min.

        Ebem: `0,0925 BelpexSPP0 - 1,25`. Het teken kwijtraken maakt van een
        aftrek een opslag — 2,50 EUR/MWh verschil op elke geïnjecteerde kWh.
        """
        (formule,) = parse_kaart("Injectie alle uren | 0,0925 BelpexSPP0 - 1,25").formules
        assert formule.z == D("-1.25")


class TestWatGeenFormuleIs:
    def test_een_getal_zonder_index_telt_niet(self):
        """Zonder anker op een indexnaam matcht een regex vrolijk op elke
        `x + y` die op een kaart staat — en een tariefkaart staat er vol mee."""
        assert parse_kaart("Vaste vergoeding 65,00 + 3,50 administratie").formules == []

    def test_een_coefficient_van_nul_telt_niet(self):
        assert parse_kaart("0,000 x Belpex + 12,50").formules == []


class TestDeEenheidEnDeBtw:
    """De eenheid is het gevaarlijke deel.

    `0,102 x BELPEX + 3,001` levert ct/kWh, `Belpex * 1,168 + 16,90` levert
    EUR/MWh. Dat is een factor tien, en op een kaart staat het soms alleen in
    de kolomkop. Een verkeerd omgerekend getal is erger dan een onomgerekend
    getal: het eerste ziet er plausibel uit.
    """

    def test_de_eenheid_komt_uit_de_kolomkop(self):
        tekst = "VERBRUIK (€cent/kWh)\n\n\n\n(0,102 X BELPEX-RLP-M + 3,001)"
        (formule,) = parse_kaart(tekst).formules
        assert formule.eenheid == "ct/kWh"

    def test_een_onbekende_eenheid_blijft_leeg(self):
        """Niet raden. Een lege eenheid is een zichtbaar gat; een verzonnen
        eenheid is een stille factor tien."""
        (formule,) = parse_kaart("0,102 x BELPEX-RLP-M + 3,001").formules
        assert formule.eenheid == ""

    def test_maal_1_06_betekent_inclusief_btw(self):
        """Eneco drukt `(...) X 1,06` af: de kaart is inclusief 6%, de databank
        exclusief. Dat staat als vlag naast de waarde en wordt niet stil
        weggedeeld."""
        (formule,) = parse_kaart("(0,102 X BELPEX-RLP-M + 3,001) X 1,06").formules
        assert formule.btw == "incl"

    def test_exclusief_btw_wordt_herkend(self):
        tekst = "Tariefformule (€/MWh, Excl. BTW)\nBelpex * 1,168 + 16,90"
        (formule,) = parse_kaart(tekst).formules
        assert (formule.btw, formule.eenheid) == ("excl", "EUR/MWh")


class TestHetRegister:
    @pytest.mark.parametrize("regel,verwacht", [
        ("Dubbele teller piek | 0,120 BelpexRLP0 + 2,2", "dag"),
        ("Dubbele teller dal | 0,099 BelpexRLP0 + 2,2", "nacht"),
        ("Exclusief nacht | 0,099 BelpexRLP0 + 2,2", "exclusief_nacht"),
        ("Injectie alle uren | 0,0925 BelpexSPP0 - 1,25", "injectie"),
        ("Enkelvoudige teller | 0,110 BelpexRLP0 + 2,2", "enkelvoudig"),
    ])
    def test_het_register_wordt_uit_de_regel_afgeleid(self, regel, verwacht):
        """"Exclusief nacht" moet vóór "nacht" getoetst worden.

        Dezelfde valkuil als bij het energiefonds, waar "niet-residentiële
        afnemer" de deelstring "residentiële afnemer" bevat: de specifiekere
        eerst, anders krijgt het exclusief-nachtregister het dalprofiel.
        """
        (formule,) = parse_kaart(regel).formules
        assert formule.register == verwacht


class TestDeVasteVergoeding:
    def test_op_dezelfde_regel(self):
        """ENGIE: `vergoeding van 22,83€/jaar`."""
        inhoud = parse_kaart("Voor die klanten geldt een vergoeding van 22,83€/jaar.")
        assert any(v["waarde"] == "22.83" for v in inhoud.vaste_vergoeding)

    def test_onder_de_kolomkop_worden_kandidaten_gegeven(self):
        """Bij Eneco staan het verbruikstarief (17,67) en de vaste vergoeding
        (65,00) naast elkaar in dezelfde tabel; `pdftotext -layout` houdt de
        kolommen naast elkaar maar niet uit elkaar.

        Er wordt daarom niet één getal gekozen maar een handvol kandidaten
        doorgegeven — welke het is, blijkt uit de toets tegen `tarief_afname`.
        Hier gokken levert een bedrag op dat er staat maar iets anders betekent.
        """
        tekst = "VASTE VERGOEDING (€/jaar)\n   17,67   17,67\n   65,00   17,61"
        waarden = {v["waarde"] for v in parse_kaart(tekst).vaste_vergoeding}
        assert {"17.67", "65.00"} <= waarden


class TestDeKaartmaand:
    def test_de_maand_van_de_kaart(self):
        """"Tariefkaart september 2026 van Eneco Belgium nv".

        Zonder die maand valt de formule tegen de verkeerde snapshot te leggen:
        de coëfficiënten wijzigen maandelijks.
        """
        inhoud = parse_kaart("Tariefkaart september 2026 van Eneco Belgium nv voor ...")
        assert inhoud.kaartmaand == "2026-09"

    def test_zonder_maand_blijft_het_veld_leeg(self):
        assert parse_kaart("Tariefkaart voor particulieren").kaartmaand == ""
