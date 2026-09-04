"""Tests voor producteigenschappen die alleen de live scrape kent.

De bulk-export levert de prijzen maar niet of een product groene stroom is;
dat staat als `data-greentype` op de resultatenpagina van vtest.be. De kolom
`energie_product.groene_stroom` bleef daardoor leeg terwijl de gegevens wel
gescrapet waren — 821 van de 1.200 elektriciteitsrijen dragen GREEN of
GREENLOCAL.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import sqlalchemy as sa

from energie_vlaanderen.infrastructure.db.importer import (
    import_energie_product_kenmerken,
)
from energie_vlaanderen.infrastructure.db.schema import energie_product, leverancier

KOP = "vreg_id;supplier_raw;product_raw;energy;green_type;segment;postcode\n"


pytestmark = pytest.mark.databank


@pytest.fixture
def conn():
    engine = sa.create_engine("sqlite://")
    metadata = sa.MetaData()
    for tabel in (leverancier, energie_product):
        kopie = tabel.to_metadata(metadata)
        for kolom in kopie.columns:
            if kolom.primary_key:
                kolom.type = sa.Integer()
    metadata.create_all(engine)
    with engine.begin() as verbinding:
        verbinding.execute(sa.insert(leverancier).values(id=1, naam="Testlev"))
        for index, (vreg_id, naam, energie) in enumerate(
            [
                ("10025", "Groen product", "Elektriciteit"),
                ("10026", "Lokaal groen", "Elektriciteit"),
                ("10027", "Grijs product", "Elektriciteit"),
                (None, "Alleen in de bulk-export", "Elektriciteit"),
            ],
            start=1,
        ):
            verbinding.execute(
                sa.insert(energie_product).values(
                    id=index,
                    leverancier_id=1,
                    vreg_id=vreg_id,
                    product_naam=naam,
                    energie_type=energie,
                    segment="Woning",
                )
            )
        yield verbinding


def _csv(tmp_path: Path, *rijen: str) -> Path:
    pad = tmp_path / "vtest_products.csv"
    pad.write_text(KOP + "".join(rijen), encoding="utf-8-sig")
    return pad


def _kenmerken(conn) -> dict[str, tuple]:
    return {
        rij.product_naam: (rij.groene_stroom, rij.groene_stroom_type)
        for rij in conn.execute(
            sa.select(
                energie_product.c.product_naam,
                energie_product.c.groene_stroom,
                energie_product.c.groene_stroom_type,
            )
        )
    }


def test_groen_en_lokaal_groen_blijven_onderscheiden(conn, tmp_path):
    """GREENLOCAL is lokaal opgewekte groene stroom.

    Beide zijn groen, maar het onderscheid telt voor een vergelijker; alleen
    een boolean bewaren zou ze gelijkschakelen.
    """
    csv = _csv(
        tmp_path,
        "10025;X;Groen product;Elektriciteit;GREEN;woning;9120\n",
        "10026;X;Lokaal groen;Elektriciteit;GREENLOCAL;woning;9120\n",
    )

    import_energie_product_kenmerken(conn, csv)

    kenmerken = _kenmerken(conn)
    assert kenmerken["Groen product"] == (True, "GREEN")
    assert kenmerken["Lokaal groen"] == (True, "GREENLOCAL")


def test_niet_groen_wordt_expliciet_op_false_gezet(conn, tmp_path):
    csv = _csv(tmp_path, "10027;X;Grijs product;Elektriciteit;NONE;woning;9120\n")

    import_energie_product_kenmerken(conn, csv)

    assert _kenmerken(conn)["Grijs product"] == (False, "NONE")


def test_product_zonder_scrape_blijft_leeg(conn, tmp_path):
    """NULL betekent "niet gescrapet", niet "niet groen".

    Een product dat alleen in de bulk-export voorkomt — bijvoorbeeld omdat het
    niet meer aangeboden wordt — hoort geen false te krijgen; dat zou een
    onbekend gegeven als een vaststelling laten lezen.
    """
    csv = _csv(tmp_path, "10025;X;Groen product;Elektriciteit;GREEN;woning;9120\n")

    import_energie_product_kenmerken(conn, csv)

    assert _kenmerken(conn)["Alleen in de bulk-export"] == (None, None)


def test_hetzelfde_product_over_meerdere_postcodes_telt_een_keer(conn, tmp_path):
    """De scrape levert elk contract per postcode; de eigenschappen zijn gelijk."""
    csv = _csv(
        tmp_path,
        *[
            f"10025;X;Groen product;Elektriciteit;GREEN;woning;{pc}\n"
            for pc in ("1540", "2150", "9120")
        ],
    )

    resultaat = import_energie_product_kenmerken(conn, csv)

    assert resultaat.rows_inserted == 1
    assert _kenmerken(conn)["Groen product"] == (True, "GREEN")


def test_ontbrekend_bestand_is_geen_fout(conn, tmp_path):
    resultaat = import_energie_product_kenmerken(conn, tmp_path / "bestaat-niet.csv")

    assert resultaat.rows_inserted == 0
