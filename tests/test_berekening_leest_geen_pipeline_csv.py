"""De berekening opent geen enkel pipelinebestand.

De regel van dit project: de berekening komt uit de code, de data uit de
databank. De CSV's onder `staging/` en `versions/` zijn een transportband naar
de databank en verder niets.

Die regel stond nergens vastgelegd -- ze werd nageleefd omdat het zo bedoeld
was. En dat hield niet: een spoorloop over `gebruiker bereken` liet zien dat het
postcode-naar-netbeheerderregister nog uit `DnbPerGemeente.csv` kwam. Dat is
geen bijzaak, want de netbeheerder bepaalt wélke nettarieven gelden; de
tarieven kwamen uit de databank en de koppeling ernaartoe uit een bestand.
Precies de tweede weg naar hetzelfde antwoord die uiteen kan lopen.

Deze test hangt een audithaak in de interpreter en kijkt naar wat er werkelijk
geopend wordt. Dat is sterker dan een grep op importregels: het vangt ook een
pad dat via een omweg of een string wordt samengesteld.

Wat een berekening wél mag lezen:
  - `gebruiker.toml`             het dossier zelf
  - `config/heffingen/*.toml`    handgeschreven masterdata, staat in git
  - `data/market/*.json`         de marktprijscache
  - `data/referentie/**`         de eigen meterexport van de gebruiker
  - `.env`                       verbindingsgegevens
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.dossier

ROOT = Path(__file__).resolve().parents[1]

# De mappen waar de pipeline haar CSV's neerzet. Niets hieruit hoort tijdens
# een berekening geopend te worden.
PIPELINEMAPPEN = ("data/staging", "data/versions", "data/current")


@pytest.fixture
def geopende_bestanden():
    """Registreert elk bestand dat binnen het blok geopend wordt."""
    gezien: list[str] = []

    def haak(gebeurtenis: str, args) -> None:
        if gebeurtenis != "open":
            return
        pad = args[0]
        if isinstance(pad, bytes):
            pad = pad.decode("utf-8", "replace")
        if isinstance(pad, (str, os.PathLike)):
            gezien.append(os.fspath(pad))

    sys.addaudithook(haak)   # een audithaak kan niet verwijderd worden;
    return gezien            # daarom wordt er per test een verse lijst gevuld


@pytest.mark.integration
def test_gebruiker_bereken_opent_geen_pipeline_csv(geopende_bestanden):
    """Draait de echte berekening over de referentieperiode.

    Integratie: dit heeft de databank en een dossier nodig. Zonder die twee is
    er ook niets te bewijzen -- een berekening die niet draait, leest ook geen
    CSV.
    """
    if not (ROOT / "gebruiker.toml").is_file():
        pytest.skip("gebruiker.toml ontbreekt (persoonlijk, staat niet in git).")

    from energie_vlaanderen.cli import main

    code = main([
        "gebruiker", "bereken",
        "--van", "2025-06-25", "--tot", "2026-05-01",
        "--json",
    ])
    if code != 0:
        pytest.skip(f"Berekening niet uitgevoerd (exitcode {code}); niets te toetsen.")

    wortel = str(ROOT)
    overtredingen = sorted({
        pad[len(wortel) + 1:]
        for pad in geopende_bestanden
        if pad.startswith(wortel)
        and any(pad[len(wortel) + 1:].startswith(m) for m in PIPELINEMAPPEN)
    })
    assert not overtredingen, (
        "De berekening opende pipelinebestanden: "
        + ", ".join(overtredingen)
        + ". De databank hoort de enige bron te zijn."
    )
