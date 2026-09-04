"""Elke componentcode uit de normalizer moet bij de import terechtkomen.

De importer kent twee bestemmingen voor een componentcode: een eigen prijsband
(`METER_TYPES`, elk een eigen tariefrij) of een toeslagkolom
(`_map_component_code_to_field`). Wat in geen van beide past, wordt weggegooid
— stil, op een `LOG.warning` na die niemand leest.

Dat gebeurde met 295 van de 42.118 prijsrijen. Twee oorzaken tegelijk: de
ToU-banden waren in de normalizer hernoemd (`daluren` → `tou_offpeak`) zonder
de importer mee te nemen, en de `_vast`-varianten hadden er nooit in gestaan.

Deze test koppelt de twee kanten aan elkaar, zodat een nieuwe componentcode in
de normalizer niet meer stilzwijgend prijzen kan laten verdampen.
"""

from __future__ import annotations

import pytest

from energie_vlaanderen.infrastructure.db.importer import (
    METER_TYPES,
    _map_component_code_to_field,
)
from energie_vlaanderen.ingest.vtest.normalizer import (
    COMPONENT_MAPPING,
    FORMULA_COMPONENTS,
)


pytestmark = pytest.mark.databank


def _wordt_geimporteerd(code: str) -> bool:
    return code in METER_TYPES or _map_component_code_to_field(code) is not None


def test_elke_gemapte_componentcode_komt_in_de_databank():
    """Alles wat COMPONENT_MAPPING oplevert, moet de importer kennen."""
    ontbrekend = sorted(
        code for code in set(COMPONENT_MAPPING.values()) if not _wordt_geimporteerd(code)
    )

    assert ontbrekend == [], (
        "Deze componentcodes komen uit de normalizer maar worden bij de "
        f"databankimport weggegooid: {ontbrekend}"
    )


def test_de_vast_varianten_komen_in_de_databank():
    """De normalizer maakt van "(vast)" een eigen code per formulecomponent.

    Dat gewaarborgde vaste deel van een variabel contract is een echte prijs;
    hij hoorde nooit stil weg te vallen.
    """
    ontbrekend = sorted(
        f"{code}_vast" for code in FORMULA_COMPONENTS
        if not _wordt_geimporteerd(f"{code}_vast")
    )

    assert ontbrekend == []


def test_de_lage_verbruiksschijf_komt_in_de_databank():
    """De normalizer hangt "_low" aan een code bij een 0-N kWh-schijf."""
    ontbrekend = sorted(
        f"{code}_low" for code in ("day", "night")
        if not _wordt_geimporteerd(f"{code}_low")
    )

    assert ontbrekend == []


def test_meter_types_en_toeslagkolommen_overlappen_niet():
    """Een code hoort óf een eigen prijsband te zijn óf een toeslagkolom.

    Allebei zou betekenen dat dezelfde prijs op twee plaatsen belandt.
    """
    dubbel = sorted(
        code for code in METER_TYPES if _map_component_code_to_field(code) is not None
    )

    assert dubbel == []
