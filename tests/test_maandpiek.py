"""De geschatte maandpiek en de wettelijke ondergrens zijn twee getallen.

Ze waren er lang één. `geschatte_maandpiek_kw` stond op 2,5 kW, maar 2,5 is de
bodem van het capaciteitstarief — de waarde waaronder niet gerekend wórdt —
en niet de piek van een gemiddeld gezin. Wie geen eigen meetdata aanleverde,
rekende daardoor per definitie op die bodem: een factuur die klopte in vorm en
ongeveer 86 EUR per jaar te laag was.

Dat is dezelfde foutsoort als de accijns van 13,60: geen crash, geen
waarschuwing, alleen een te laag getal.
"""

from __future__ import annotations

import pytest

from decimal import Decimal

from energie_vlaanderen.domain.models import Profile
from energie_vlaanderen.utility.constants import D


pytestmark = pytest.mark.rekenen


def test_de_standaardschatting_is_de_vtest_waarde():
    """4,218 kW is teruggerekend uit vtest.be zelf.

    Bron: de gescrapete capaciteitstarieven van alle acht netbeheerders op
    2026-08-31. Uit het bedrag dat vtest.be voor zijn standaardwoning aanrekent
    en het gepubliceerde EUR/kW/jaar-tarief volgt precies één piek, en die is
    voor alle acht netbeheerders dezelfde: 4,218 kW.

    Het is dus geen natuurwet maar de waarde waarmee de officiële
    vergelijkingstool van VREG rekent. Wijkt dit af, dan is de vraag eerst of
    vtest.be zijn standaardprofiel gewijzigd heeft — niet of deze assertie
    aangepast moet worden.
    """
    assert Profile(postcode="9120").geschatte_maandpiek_kw == D("4.218")


def test_de_ondergrens_staat_apart_en_blijft_de_wettelijke_bodem():
    """2,5 kW blijft bestaan, maar als ondergrens en niet als schatting.

    Bron: het capaciteitstarief rekent nooit met minder dan 2,5 kW, ook niet
    bij een lagere gemeten piek (VREG-tariefmethodologie laagspanning).
    """
    assert Profile(postcode="9120").minimum_maandpiek_kw == D("2.5")


def test_de_schatting_ligt_boven_de_ondergrens():
    """De regressie die deze scheiding moet voorkomen.

    Zolang beide velden dezelfde waarde dragen, is de schatting stilzwijgend
    de bodem geworden en rekent elk profiel zonder meetdata te laag. Deze test
    faalt zodra dat opnieuw gebeurt, ongeacht wélke waarden het worden.
    """
    profiel = Profile(postcode="9120")

    assert profiel.geschatte_maandpiek_kw > profiel.minimum_maandpiek_kw


def test_drie_decimalen_overleven():
    """4,218 mag niet stil 4,22 worden.

    De databankkolom stond op Numeric(6, 2) en zou de derde decimaal bij het
    opslaan hebben weggerond. Hier wordt alleen het domeinmodel getoetst; de
    kolom is in migratie 0015 op Numeric(7, 3) gezet.
    """
    piek = Profile(postcode="9120").geschatte_maandpiek_kw

    assert piek.as_tuple().exponent == -3
    assert piek != Decimal("4.22")


def test_eigen_waarden_worden_overgenomen():
    """Beide velden blijven instelbaar; het zijn standaardwaarden, geen wet."""
    profiel = Profile(
        postcode="9120",
        geschatte_maandpiek_kw=D("6.5"),
        minimum_maandpiek_kw=D("3.0"),
    )

    assert profiel.geschatte_maandpiek_kw == D("6.5")
    assert profiel.minimum_maandpiek_kw == D("3.0")
