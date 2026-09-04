"""Tests voor de terugrekenlogica van VTestCalibrator.

De scrape zelf is niet getest (dat vergt een live vtest.be); wel de fit, want
dat is het stuk dat masterdata gaat aansturen.
"""

from decimal import Decimal

import pytest

from energie_vlaanderen.ingest.vtest.calibration import (
    CalibrationError,
    Meting,
    VTestCalibrator,
)


pytestmark = pytest.mark.scrape


def _meting(kwh: int, **componenten: Decimal) -> Meting:
    return Meting(
        kwh=kwh,
        postcode="9120",
        energy="gas",
        segment="woning",
        producten=10,
        componenten={k: str(v) for k, v in componenten.items()},
        dominant_aandeel={k: "1" for k in componenten},
        spreiding={k: 1 for k in componenten},
    )


def _schijventarief(kwh: int, grens: int, tarief_laag: str, tarief_hoog: str) -> Decimal:
    """Bedrag bij een tweeschijventarief, afgerond op eurocent zoals vtest.be."""
    basis = min(kwh, grens)
    extra = max(0, kwh - grens)
    bedrag = (
        Decimal(basis) * Decimal(tarief_laag) + Decimal(extra) * Decimal(tarief_hoog)
    ) / Decimal(1000)
    return bedrag.quantize(Decimal("0.01"))


def test_vaste_term_wordt_als_vast_herkend():
    metingen = [
        _meting(kwh, **{"Nettarieven|Tarief databeheer (per jaar)": Decimal("17.85")})
        for kwh in (1_000, 5_000, 20_000)
    ]

    (fit,) = VTestCalibrator.fit(metingen)

    assert fit.component == "Tarief databeheer (per jaar)"
    assert fit.vaste_term_eur == "17.85"
    assert fit.schijven == []
    assert fit.sluitend


def test_enkel_tarief_wordt_teruggerekend():
    label = "Heffingen|Bijzondere accijns"
    metingen = [
        _meting(kwh, **{label: Decimal(kwh) * Decimal("46.00") / Decimal(1000)})
        for kwh in (1_000, 3_434, 10_000)
    ]

    (fit,) = VTestCalibrator.fit(metingen)

    assert len(fit.schijven) == 1
    assert Decimal(fit.schijven[0].eur_per_mwh) == Decimal("46")
    assert fit.sluitend


def test_schijfgrens_wordt_gevonden_en_ingesloten():
    """Een knik in de kostenfunctie moet als schijfgrens terugkomen.

    Opzet: 10,3113 EUR/MWh tot 12 MWh, 11,1604 daarboven — de structuur die
    vtest.be voor aardgas hanteert. De meetpunten sluiten de grens in op
    11.900-12.100 kWh.
    """
    label = "Heffingen|Bijzondere accijns (per kWh)"
    metingen = [
        _meting(
            kwh,
            **{label: _schijventarief(kwh, 12_000, "10.3113", "11.1604")},
        )
        for kwh in (4_000, 11_900, 12_100, 20_000, 35_000)
    ]

    (fit,) = VTestCalibrator.fit(metingen)

    assert len(fit.schijven) == 3, fit.schijven
    laag, overgang, hoog = fit.schijven
    assert laag.van_kwh == 4_000 and laag.tot_kwh == 11_900
    # De helling wordt uit op eurocent afgeronde bedragen gehaald; over een
    # span van 7.900 kWh geeft dat ~0,0013 EUR/MWh speling.
    assert abs(Decimal(laag.eur_per_mwh) - Decimal("10.3113")) < Decimal("0.005")
    # De grens ligt in dit interval; het gemiddelde tarief hoort ertussenin.
    assert overgang.van_kwh == 11_900 and overgang.tot_kwh == 12_100
    assert Decimal("10.311") < Decimal(overgang.eur_per_mwh) < Decimal("11.161")
    assert hoog.van_kwh == 12_100
    assert abs(Decimal(hoog.eur_per_mwh) - Decimal("11.1604")) < Decimal("0.005")
    assert fit.sluitend


def test_component_die_niet_in_elke_meting_stabiel_is_valt_af():
    metingen = [
        _meting(1_000, **{"Heffingen|Bijzondere accijns": Decimal("10.00")}),
        _meting(2_000, **{"Heffingen|Bijzondere accijns": Decimal("20.00")}),
    ]
    # Leveranciersafhankelijk: het meest voorkomende bedrag wordt maar door
    # een derde van de contracten gedragen, dus geen functie van het verbruik.
    for meting in metingen:
        meting.componenten["Energiekost|Korting"] = "5.00"
        meting.dominant_aandeel["Energiekost|Korting"] = "0.33"

    fits = VTestCalibrator.fit(metingen)

    assert [f.component for f in fits] == ["Bijzondere accijns"]


def test_te_weinig_metingen():
    with pytest.raises(CalibrationError):
        VTestCalibrator.fit([_meting(1_000, **{"a|b": Decimal("1")})])


def test_dominante_waarde_overleeft_een_afwijkend_sociaal_tarief():
    """Het sociaal tarief kent eigen accijnzen en is één contract op vele.

    De heffing hoort dan alsnog teruggerekend te worden uit het bedrag dat de
    grote meerderheid draagt — anders valt net de component weg die we willen
    controleren.
    """
    label = "Heffingen|Bijzondere accijns (per kWh)"
    metingen = []
    for kwh in (4_000, 12_000, 20_000):
        meting = _meting(kwh, **{label: Decimal(kwh) * Decimal("10.31") / Decimal(1000)})
        meting.dominant_aandeel[label] = "0.9867"
        meting.spreiding[label] = 2
        metingen.append(meting)

    (fit,) = VTestCalibrator.fit(metingen)

    assert abs(Decimal(fit.schijven[0].eur_per_mwh) - Decimal("10.31")) < Decimal("0.005")
