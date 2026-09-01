"""Tests voor de koppeling van vreg_id's aan producten.

Aanleiding: de koppeling matchte op leverancier + productnaam en negeerde
energievorm en segment. "Sociaal tarief" van "Mogelijk bij elke
energieleverancier" bestaat echter voor elektriciteit én gas, zodat één
vreg_id op meerdere rijen belandde — wat botste op de unieke sleutel van
`energie_product.vreg_id` en de hele import terugdraaide.

Deze tests draaien op SQLite in het geheugen: de fout zat in de WHERE-clausule
en die is dialectonafhankelijk.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import sqlalchemy as sa

from energie_vlaanderen.infrastructure.db.importer import (
    link_energie_product_vreg_ids,
)
from energie_vlaanderen.infrastructure.db.schema import energie_product, leverancier

KOP = (
    "vreg_id;supplier_raw;product_raw;segment;energy;"
    "matched_handelsnaam;matched_productnaam;match_status\n"
)


@pytest.fixture
def conn():
    engine = sa.create_engine("sqlite://")
    metadata = sa.MetaData()
    for tabel in (leverancier, energie_product):
        tabel.to_metadata(metadata)
    metadata.create_all(engine)
    with engine.begin() as verbinding:
        yield verbinding


def _zaai(conn, *producten: tuple[str, str, str, str]) -> None:
    """producten: (leveranciersnaam, productnaam, energievorm, segment)."""
    leveranciers = sorted({p[0] for p in producten})
    ids = {naam: i for i, naam in enumerate(leveranciers, start=1)}
    for naam, index in ids.items():
        conn.execute(sa.insert(leverancier).values(id=index, naam=naam))
    for index, (lev, prod, energie, segment) in enumerate(producten, start=1):
        conn.execute(
            sa.insert(energie_product).values(
                id=index,
                leverancier_id=ids[lev],
                product_naam=prod,
                energie_type=energie,
                segment=segment,
            )
        )


def _links(tmp_path: Path, *rijen: str) -> Path:
    pad = tmp_path / "vtest_product_links.csv"
    pad.write_text(KOP + "".join(rijen), encoding="utf-8-sig")
    return pad


def test_zelfde_productnaam_voor_gas_en_elektriciteit_botst_niet(conn, tmp_path):
    """Het geval dat de import liet klappen."""
    _zaai(
        conn,
        ("Mogelijk bij elke energieleverancier", "Sociaal tarief", "Elektriciteit", "Woning"),
        ("Mogelijk bij elke energieleverancier", "Sociaal tarief", "Gas", "Woning"),
    )
    links = _links(
        tmp_path,
        "10025;X;Sociaal tarief;woning;Elektriciteit;"
        "Mogelijk bij elke energieleverancier;Sociaal tarief;exact\n",
        "10099;X;Sociaal tarief;woning;Gas;"
        "Mogelijk bij elke energieleverancier;Sociaal tarief;exact\n",
    )

    resultaat = link_energie_product_vreg_ids(
        conn,
        vast_csv=tmp_path / "v.csv",
        var_dyn_csv=tmp_path / "d.csv",
        links_csv=links,
    )

    assert resultaat.rows_inserted == 2
    gekoppeld = dict(
        conn.execute(
            sa.select(energie_product.c.energie_type, energie_product.c.vreg_id)
        ).fetchall()
    )
    assert gekoppeld == {"Elektriciteit": "10025", "Gas": "10099"}


def test_segment_scheidt_woning_van_onderneming(conn, tmp_path):
    _zaai(
        conn,
        ("ENGIE", "Easy", "Elektriciteit", "Woning"),
        ("ENGIE", "Easy", "Elektriciteit", "Onderneming"),
    )
    links = _links(
        tmp_path, "20001;X;Easy;woning;Elektriciteit;ENGIE;Easy;exact\n"
    )

    resultaat = link_energie_product_vreg_ids(
        conn,
        vast_csv=tmp_path / "v.csv",
        var_dyn_csv=tmp_path / "d.csv",
        links_csv=links,
    )

    assert resultaat.rows_inserted == 1
    rijen = conn.execute(
        sa.select(energie_product.c.segment, energie_product.c.vreg_id)
    ).fetchall()
    assert dict(rijen) == {"Woning": "20001", "Onderneming": None}


def test_rij_zonder_energievorm_wordt_overgeslagen(conn, tmp_path):
    """Zonder volledige sleutel is koppelen gokken; dan liever niets."""
    _zaai(conn, ("ENGIE", "Easy", "Elektriciteit", "Woning"))
    links = _links(tmp_path, "20001;X;Easy;;;ENGIE;Easy;exact\n")

    resultaat = link_energie_product_vreg_ids(
        conn,
        vast_csv=tmp_path / "v.csv",
        var_dyn_csv=tmp_path / "d.csv",
        links_csv=links,
    )

    assert resultaat.rows_inserted == 0
    assert conn.execute(sa.select(energie_product.c.vreg_id)).scalar() is None


def test_ontbrekend_linksbestand_is_geen_fout(conn, tmp_path):
    resultaat = link_energie_product_vreg_ids(
        conn,
        vast_csv=tmp_path / "v.csv",
        var_dyn_csv=tmp_path / "d.csv",
        links_csv=tmp_path / "bestaat-niet.csv",
    )

    assert resultaat.rows_inserted == 0
