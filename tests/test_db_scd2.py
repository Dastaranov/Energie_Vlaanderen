"""Tests voor de SCD2-historiek van tarieven.

Aanleiding: dezelfde versie twee keer importeren sloot de open rij af met
`geldig_tot = geldig_van - 1 dag` en voegde daarna een nieuwe rij in die op
diezelfde `geldig_van` begon. Op `netbeheerder_tarief` liep dat vast op de
unieke sleutel; op `tarief_afname`, dat er geen heeft, groeide de tabel stil
aan met rijen die een negatieve geldigheidsduur beschreven.

Een herimport van dezelfde gegevens hoort niets te veranderen.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
import sqlalchemy as sa

from energie_vlaanderen.infrastructure.db.importer import _scd2_upsert
from energie_vlaanderen.infrastructure.db.schema import energie_product, leverancier, tarief_afname


@pytest.fixture
def conn():
    """SQLite in het geheugen; de SCD2-logica is dialectonafhankelijk.

    Twee aanpassingen aan het schema, allebei omdat SQLite iets niet kan:

    - geen autoincrement op BIGINT, dus sleutelkolommen worden INTEGER;
    - geen partiële indexen. `ix_tarief_afname_open` is uniek *alleen over de
      open rijen* (geldig_tot IS NULL). SQLite zou daar een volledig unieke
      index van maken, wat elke historiek verbiedt — precies wat we willen
      testen. Die indexen laten we hier dus weg.

    Alleen het schema wijkt af; de logica die getest wordt niet.
    """
    engine = sa.create_engine("sqlite://")
    metadata = sa.MetaData()
    for tabel in (leverancier, energie_product, tarief_afname):
        kopie = tabel.to_metadata(metadata)
        for kolom in kopie.columns:
            if kolom.primary_key:
                kolom.type = sa.Integer()
        for index in list(kopie.indexes):
            if index.dialect_options.get("postgresql", {}).get("where") is not None:
                kopie.indexes.discard(index)
    metadata.create_all(engine)
    with engine.begin() as verbinding:
        verbinding.execute(sa.insert(leverancier).values(id=1, naam="Testlev"))
        verbinding.execute(
            sa.insert(energie_product).values(
                id=1, leverancier_id=1, product_naam="P",
                energie_type="Elektriciteit", segment="Woning",
            )
        )
        yield verbinding


def _rij(geldig_van: date, prijs: str) -> dict:
    return {
        "product_id": 1,
        "meter_type": "single",
        "prijs_type": "vast",
        "energieprijs_kwh": Decimal(prijs),
        "geldig_van": geldig_van,
    }


def _rijen(conn):
    return conn.execute(
        sa.select(
            tarief_afname.c.geldig_van,
            tarief_afname.c.geldig_tot,
            tarief_afname.c.energieprijs_kwh,
        ).order_by(tarief_afname.c.geldig_van, tarief_afname.c.id)
    ).fetchall()


def test_eerste_invoer_geeft_een_open_rij(conn):
    _scd2_upsert(conn, tarief_afname, _rij(date(2026, 1, 1), "0.20"))

    assert _rijen(conn) == [(date(2026, 1, 1), None, Decimal("0.20"))]


def test_dezelfde_periode_opnieuw_importeren_verandert_niets(conn):
    """Het geval dat de import liet stuklopen."""
    _scd2_upsert(conn, tarief_afname, _rij(date(2026, 1, 1), "0.20"))
    _scd2_upsert(conn, tarief_afname, _rij(date(2026, 1, 1), "0.20"))

    assert _rijen(conn) == [(date(2026, 1, 1), None, Decimal("0.20"))]


def test_gecorrigeerde_prijs_in_dezelfde_periode_werkt_de_rij_bij(conn):
    """Een correctie op dezelfde maand is geen nieuwe versie."""
    _scd2_upsert(conn, tarief_afname, _rij(date(2026, 1, 1), "0.20"))
    _scd2_upsert(conn, tarief_afname, _rij(date(2026, 1, 1), "0.25"))

    assert _rijen(conn) == [(date(2026, 1, 1), None, Decimal("0.25"))]


def test_een_latere_periode_sluit_de_vorige_af(conn):
    _scd2_upsert(conn, tarief_afname, _rij(date(2026, 1, 1), "0.20"))
    _scd2_upsert(conn, tarief_afname, _rij(date(2026, 2, 1), "0.22"))

    assert _rijen(conn) == [
        (date(2026, 1, 1), date(2026, 1, 31), Decimal("0.20")),
        (date(2026, 2, 1), None, Decimal("0.22")),
    ]


def test_een_vroegere_periode_wordt_overgeslagen(conn):
    """Terugwerkend invoegen zou een rij afsluiten vóór haar eigen begin."""
    _scd2_upsert(conn, tarief_afname, _rij(date(2026, 2, 1), "0.22"))
    _scd2_upsert(conn, tarief_afname, _rij(date(2026, 1, 1), "0.20"))

    assert _rijen(conn) == [(date(2026, 2, 1), None, Decimal("0.22"))]


def test_een_reeks_maanden_geeft_een_sluitende_historiek(conn):
    """De bulk-export bevat meerdere maanden; die horen op elkaar aan te sluiten."""
    for maand, prijs in ((1, "0.20"), (2, "0.22"), (3, "0.21")):
        _scd2_upsert(conn, tarief_afname, _rij(date(2026, maand, 1), prijs))

    rijen = _rijen(conn)

    assert rijen == [
        (date(2026, 1, 1), date(2026, 1, 31), Decimal("0.20")),
        (date(2026, 2, 1), date(2026, 2, 28), Decimal("0.22")),
        (date(2026, 3, 1), None, Decimal("0.21")),
    ]
    # Geen gaten en geen overlap: elke periode sluit aan op de volgende.
    for vorige, volgende in zip(rijen, rijen[1:]):
        assert vorige.geldig_tot is not None
        assert vorige.geldig_tot.toordinal() + 1 == volgende.geldig_van.toordinal()
