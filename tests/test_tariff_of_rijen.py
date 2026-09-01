"""Tests voor "of"-vervolgregels in de tariefwerkboeken.

De VREG-werkboeken geven hetzelfde tarief soms in twee eenheden. De tweede
regel draagt dan geen naam maar het woord "of":

    Maandpiek                                EUR/kW/maand
    of                                       EUR/kW/jaar
    Tarief voor overschrijding toegangsverm  EUR/kW/maand
    of                                       EUR/kW/jaar

Dat letterlijk overnemen maakte van elke "of" een tariefnaam, waardoor
verschillende tarieven dezelfde omschrijving kregen. In het hoogspanningsblad
botsten daardoor 40 van de 488 sleutels, en de databankimport liep vast op de
unieke sleutel van `netbeheerder_tarief`.
"""

from __future__ import annotations

import pandas as pd

from energie_vlaanderen.ingest.tariffs.normalizer import TariffDataNormalizer


def _blad(*rijen: tuple[str, str, str], sheet: str = "FA ELEK Afname") -> pd.DataFrame:
    """rijen: (kolom0, omschrijving, eenheid).

    Kolomindeling zoals het werkboek: 0 = hoofdgroepnummer, 1 = omschrijving,
    3 = eenheid, 13 = de prijs voor ELEK_LS_DIGI.
    """
    data = []
    for nummer, (kolom0, omschrijving, eenheid) in enumerate(rijen, start=1):
        rij = [None] * 16
        rij[0] = kolom0 or None
        rij[1] = omschrijving or None
        rij[3] = eenheid or None
        # Kopregels ("1 | Tarieven voor het netgebruik") dragen in het
        # werkboek geen eenheid en geen prijs; alleen tariefregels wel.
        if eenheid:
            rij[13] = 10.0
        data.append(
            {i: v for i, v in enumerate(rij)}
            | {"source_sheet": sheet, "source_row": nummer}
        )
    return pd.DataFrame(data)


def _details(frame: pd.DataFrame) -> list[tuple[str, str]]:
    resultaat = TariffDataNormalizer().normalize(frame, pd.DataFrame())
    rijen = resultaat.afname
    return list(
        dict.fromkeys(zip(rijen["Tariefdetail"], rijen["Tariefnotering"]))
    )


def test_of_neemt_de_naam_van_de_regel_erboven_over():
    frame = _blad(
        ("1", "Tarieven voor het netgebruik", ""),
        ("", "Maandpiek", "EUR/kW/maand"),
        ("", "of", "EUR/kW/jaar"),
    )

    assert _details(frame) == [
        ("Maandpiek", "EUR/kW/maand"),
        ("Maandpiek", "EUR/kW/jaar"),
    ]


def test_opeenvolgende_blokken_krijgen_elk_hun_eigen_naam():
    """Het geval dat de sleutels liet botsen: twee "of"-regels in één blok."""
    frame = _blad(
        ("1", "Tarieven voor het netgebruik", ""),
        ("", "Maandpiek", "EUR/kW/maand"),
        ("", "of", "EUR/kW/jaar"),
        ("", "Tarief voor overschrijding toegangsvermogen", "EUR/kW/maand"),
        ("", "of", "EUR/kW/jaar"),
    )

    details = _details(frame)

    assert details == [
        ("Maandpiek", "EUR/kW/maand"),
        ("Maandpiek", "EUR/kW/jaar"),
        ("Tarief voor overschrijding toegangsvermogen", "EUR/kW/maand"),
        ("Tarief voor overschrijding toegangsvermogen", "EUR/kW/jaar"),
    ]
    # De sleutel (detail, notering) moet uniek zijn; dát botste.
    assert len(details) == len(set(details))


def test_of_lekt_niet_over_werkbladgrenzen():
    """Elk blad is een eigen netbeheerder met een eigen tarievenlijst."""
    eerste = _blad(
        ("1", "Tarieven voor het netgebruik", ""),
        ("", "Maandpiek", "EUR/kW/maand"),
        sheet="FA ELEK Afname",
    )
    tweede = _blad(
        ("", "of", "EUR/kW/jaar"),
        sheet="FHV ELEK Afname",
    )
    frame = pd.concat([eerste, tweede], ignore_index=True)

    resultaat = TariffDataNormalizer().normalize(frame, pd.DataFrame())
    fhv = resultaat.afname[resultaat.afname["Netbeheerder"] == "FHV"]

    # Zonder voorgaande regel op dit blad is er niets om aan te hangen; de
    # regel overslaan is beter dan hem aan het vorige blad te koppelen.
    assert fhv.empty


def test_gewone_omschrijvingen_blijven_ongewijzigd():
    frame = _blad(
        ("1", "Tarieven voor het netgebruik", ""),
        ("", "kWh-tarief", "EUR/kWh"),
        ("", "Vaste term", "EUR/jaar"),
    )

    assert _details(frame) == [
        ("kWh-tarief", "EUR/kWh"),
        ("Vaste term", "EUR/jaar"),
    ]
