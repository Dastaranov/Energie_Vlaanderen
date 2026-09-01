"""Tests voor het opsporen van afgekapte matrixcombinaties.

vtest.be laadt de resultatenlijst lui bij. Stopt het scrollen te vroeg, dan
levert de combinatie een afgekapte lijst op zonder dat er iets misgaat: de run
slaagt en de matrix meldt "32/32 geslaagd". Bij de run van 2026-09-01 gaven
zeven van de acht onderneming/elektriciteit-postcodes precies 20 producten,
tegenover 97 bij de combinatie die los gedraaid was.

Dat het aanbod nauwelijks per netbeheerder verschilt is gemeten, niet
aangenomen: van de 123 woningcontracten waren er 120 in alle acht postcodes
aanwezig, en de enige echte uitzondering was Wase Wind — een regionale
coöperatie.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from energie_vlaanderen.ingest.vtest.refine_matrix import VTestRefineMatrix
from energie_vlaanderen.ingest.vtest.refine_pipeline import VTestRefinePipelineResult


def _resultaat(segment: str, energy: str, postcode: str, aantal: int):
    return VTestRefinePipelineResult(
        version_id="v1",
        directory=Path("."),
        segment=segment,
        energy=energy,
        postcode=postcode,
        products_csv=Path("p.csv"),
        components_csv=Path("c.csv"),
        dump_html=Path("d.html"),
        products_found=aantal,
        scraped_at=datetime.now(timezone.utc),
    )


def test_afgekapte_combinatie_wordt_gemeld():
    """Het geval uit de run van 2026-09-01."""
    resultaten = [
        _resultaat("onderneming", "elektriciteit", pc, 20)
        for pc in ("1540", "1910", "2150", "2290", "3511", "8000", "8432")
    ] + [_resultaat("onderneming", "elektriciteit", "9120", 97)]

    meldingen = VTestRefineMatrix._verdachte_combinaties(resultaten)

    # Alle zeven afgekapte combinaties moeten gemeld worden. Afzetten tegen
    # de mediaan zou hier falen: die is 20, waardoor de fout de norm wordt en
    # de énige volledige run als uitschieter zou gelden.
    assert len(meldingen) == 7
    assert all("tegenover 97" in m for m in meldingen)
    assert not any("9120" in m for m in meldingen)


def test_de_minderheid_die_afwijkt_wordt_gevonden():
    """Eén postcode blijft achter bij de rest: dat is het echte signaal."""
    resultaten = [
        _resultaat("woning", "elektriciteit", pc, 120)
        for pc in ("1540", "1910", "2150", "2290", "3511", "8000", "8432")
    ] + [_resultaat("woning", "elektriciteit", "9120", 20)]

    (melding,) = VTestRefineMatrix._verdachte_combinaties(resultaten)

    assert "9120" in melding
    assert "20 producten" in melding
    assert "tegenover 120" in melding


def test_gelijke_aantallen_geven_geen_melding():
    resultaten = [
        _resultaat("woning", "gas", pc, 75)
        for pc in ("1540", "1910", "2150", "2290", "3511", "8000", "8432", "9120")
    ]

    assert VTestRefineMatrix._verdachte_combinaties(resultaten) == []


def test_kleine_natuurlijke_spreiding_geeft_geen_melding():
    """120 tegenover 123 is normaal: Wase Wind verkoopt enkel in het Waasland."""
    resultaten = [
        _resultaat("woning", "elektriciteit", pc, 120)
        for pc in ("1540", "1910", "2150", "2290", "3511", "8000", "8432")
    ] + [_resultaat("woning", "elektriciteit", "9120", 123)]

    assert VTestRefineMatrix._verdachte_combinaties(resultaten) == []


def test_groepen_worden_apart_beoordeeld():
    """Gas heeft van nature veel minder producten dan elektriciteit."""
    resultaten = [
        _resultaat("woning", "elektriciteit", pc, 120) for pc in ("1540", "1910", "2150")
    ] + [_resultaat("woning", "gas", pc, 75) for pc in ("1540", "1910", "2150")]

    assert VTestRefineMatrix._verdachte_combinaties(resultaten) == []


def test_te_weinig_combinaties_om_te_vergelijken():
    """Met één of twee postcodes is er geen mediaan om tegen af te zetten."""
    resultaten = [
        _resultaat("woning", "elektriciteit", "1540", 120),
        _resultaat("woning", "elektriciteit", "9120", 5),
    ]

    assert VTestRefineMatrix._verdachte_combinaties(resultaten) == []
