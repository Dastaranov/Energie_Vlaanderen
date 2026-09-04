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


pytestmark = pytest.mark.databank


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


def test_maanden_worden_chronologisch_verwerkt(tmp_path, conn, monkeypatch):
    """De CSV wordt met dtype=str gelezen, dus groupby sorteert de maanden als
    tekst: 1, 10, 11, 12, 2, 3, ...

    De historiek werd daardoor in de verkeerde volgorde opgebouwd: na december
    kwamen februari tot september nog langs, elk als een terugwerkende
    wijziging. Deze test leest een CSV met precies die maanden en controleert
    dat de historiek er chronologisch uitkomt.
    """
    from energie_vlaanderen.infrastructure.db.importer import (
        import_leverancier_en_product,
    )

    kop = (
        "year;month;segment;energy;direction;supplier;product;product_type;"
        "component;price\n"
    )
    # Bewust in de volgorde waarin groupby ze zou opleveren.
    maanden = [1, 10, 11, 12, 2, 3]
    rijen = "".join(
        f"2025;{m};Woning;Elektriciteit;Afname;Testlev;P;vast;single;{20 + m}\n"
        for m in maanden
    )
    csv = tmp_path / "master_vast.csv"
    csv.write_text(kop + rijen, encoding="utf-8-sig")

    import_leverancier_en_product(
        conn, vast_csv=csv, var_dyn_csv=tmp_path / "bestaat-niet.csv"
    )

    rijen_uit_db = _rijen(conn)
    periodes = [(r.geldig_van, r.geldig_tot) for r in rijen_uit_db]

    # Zes maanden, chronologisch, elk aansluitend op de volgende.
    assert [p[0].month for p in periodes] == [1, 2, 3, 10, 11, 12]
    for vorige, volgende in zip(periodes, periodes[1:]):
        assert vorige[1] is not None, "een afgesloten periode hoort een einddatum te hebben"
        assert vorige[1] < volgende[0]
    assert periodes[-1][1] is None, "de laatste maand hoort de open rij te zijn"


def test_variabel_en_dynamisch_verdringen_elkaars_historiek_niet(conn):
    """Hetzelfde product wordt soms in twee prijstypes aangeboden.

    Bij Bolt is "Bolt Variabel" zowel variabel als dynamisch, elk met een eigen
    indexatieformule. In de databank delen ze één energie_product, want de
    identiteit daarvan is (leverancier, naam, energievorm, segment). Zonder
    prijs_type in de SCD2-sleutel bouwde het ene type de historiek op tot de
    laatste maand en werd het andere vanaf de eerste maand als terugwerkend
    afgewezen.
    """
    for maand in (1, 2):
        _scd2_upsert(
            conn,
            tarief_afname,
            {**_rij(date(2026, maand, 1), "0.20"), "prijs_type": "variabel"},
        )
    for maand in (1, 2):
        _scd2_upsert(
            conn,
            tarief_afname,
            {**_rij(date(2026, maand, 1), "0.30"), "prijs_type": "dynamisch"},
        )

    per_type = {}
    for rij in conn.execute(
        sa.select(
            tarief_afname.c.prijs_type,
            tarief_afname.c.geldig_van,
            tarief_afname.c.geldig_tot,
        ).order_by(tarief_afname.c.prijs_type, tarief_afname.c.geldig_van)
    ):
        per_type.setdefault(rij.prijs_type, []).append((rij.geldig_van, rij.geldig_tot))

    # Beide prijstypes hebben hun eigen, volledige historiek van twee maanden.
    assert set(per_type) == {"variabel", "dynamisch"}
    for prijs_type, periodes in per_type.items():
        assert periodes == [
            (date(2026, 1, 1), date(2026, 1, 31)),
            (date(2026, 2, 1), None),
        ], prijs_type


def test_herimport_van_een_oudere_bekende_periode_is_stil(conn):
    """Een herimport loopt de maanden opnieuw af, van oud naar nieuw.

    De historiek staat dan al tot de laatste maand, dus elke maand daarvóór is
    ouder dan de open rij. Zonder een controle op "bestaat deze periode al"
    kwamen die allemaal binnen als terugwerkende wijziging: 21.459
    waarschuwingen over 580 producten, terwijl er niets aan de hand was.
    """
    for maand in (1, 2, 3):
        _scd2_upsert(conn, tarief_afname, _rij(date(2026, maand, 1), "0.20"))

    voor = _rijen(conn)

    # Precies dezelfde import nog een keer.
    for maand in (1, 2, 3):
        _scd2_upsert(conn, tarief_afname, _rij(date(2026, maand, 1), "0.20"))

    assert _rijen(conn) == voor


def test_herimport_met_gewijzigde_prijs_werkt_de_juiste_periode_bij(conn):
    """Een correctie op een afgesloten maand hoort die maand te raken, niet
    een nieuwe rij te maken of de open rij te overschrijven."""
    for maand, prijs in ((1, "0.20"), (2, "0.22")):
        _scd2_upsert(conn, tarief_afname, _rij(date(2026, maand, 1), prijs))

    _scd2_upsert(conn, tarief_afname, _rij(date(2026, 1, 1), "0.21"))

    assert _rijen(conn) == [
        (date(2026, 1, 1), date(2026, 1, 31), Decimal("0.21")),
        (date(2026, 2, 1), None, Decimal("0.22")),
    ]


class TestBulkGelijkAanRijVoorRij:
    """De bulkweg en de rij-voor-rij weg moeten dezelfde historiek opleveren.

    Er is één implementatie (`_scd2_bulk_upsert`); `_scd2_upsert` is er een
    schil omheen. Deze tests bewaken dat die schil geen ander gedrag geeft,
    want een verschil tussen "één rij tegelijk" en "alles ineens" zou pas bij
    een productie-import zichtbaar worden.
    """

    def _historiek(self, conn):
        return [
            (r.geldig_van, r.geldig_tot, r.energieprijs_kwh, r.prijs_type)
            for r in conn.execute(
                sa.select(
                    tarief_afname.c.geldig_van,
                    tarief_afname.c.geldig_tot,
                    tarief_afname.c.energieprijs_kwh,
                    tarief_afname.c.prijs_type,
                ).order_by(tarief_afname.c.prijs_type, tarief_afname.c.geldig_van)
            )
        ]

    def test_een_reeks_maanden_ineens(self, conn):
        from energie_vlaanderen.infrastructure.db.importer import _scd2_bulk_upsert

        rijen = [_rij(date(2026, m, 1), f"0.{19 + m}") for m in (1, 2, 3)]
        _scd2_bulk_upsert(conn, tarief_afname, rijen)

        assert self._historiek(conn) == [
            (date(2026, 1, 1), date(2026, 1, 31), Decimal("0.20"), "vast"),
            (date(2026, 2, 1), date(2026, 2, 28), Decimal("0.21"), "vast"),
            (date(2026, 3, 1), None, Decimal("0.22"), "vast"),
        ]

    def test_ineens_geeft_hetzelfde_als_een_voor_een(self, conn):
        from energie_vlaanderen.infrastructure.db.importer import _scd2_bulk_upsert

        rijen = [_rij(date(2026, m, 1), f"0.{19 + m}") for m in (1, 2, 3)]
        for rij in rijen:
            _scd2_upsert(conn, tarief_afname, rij)
        een_voor_een = self._historiek(conn)

        conn.execute(sa.delete(tarief_afname))
        _scd2_bulk_upsert(conn, tarief_afname, rijen)

        assert self._historiek(conn) == een_voor_een

    def test_ongeordende_invoer_geeft_een_geordende_historiek(self, conn):
        """De bulkweg krijgt de rijen in de volgorde van de CSV binnen."""
        from energie_vlaanderen.infrastructure.db.importer import _scd2_bulk_upsert

        rijen = [_rij(date(2026, m, 1), f"0.{19 + m}") for m in (3, 1, 2)]
        _scd2_bulk_upsert(conn, tarief_afname, rijen)

        periodes = [(v, t) for v, t, _, _ in self._historiek(conn)]
        assert periodes == [
            (date(2026, 1, 1), date(2026, 1, 31)),
            (date(2026, 2, 1), date(2026, 2, 28)),
            (date(2026, 3, 1), None),
        ]

    def test_een_nieuwe_maand_sluit_de_bestaande_open_rij(self, conn):
        """Het geval bij een maandelijkse update in productie."""
        from energie_vlaanderen.infrastructure.db.importer import _scd2_bulk_upsert

        _scd2_bulk_upsert(
            conn, tarief_afname, [_rij(date(2026, m, 1), "0.20") for m in (1, 2)]
        )
        _scd2_bulk_upsert(conn, tarief_afname, [_rij(date(2026, 3, 1), "0.25")])

        assert [(v, t) for v, t, _, _ in self._historiek(conn)] == [
            (date(2026, 1, 1), date(2026, 1, 31)),
            (date(2026, 2, 1), date(2026, 2, 28)),
            (date(2026, 3, 1), None),
        ]

    def test_prijstypes_krijgen_elk_hun_eigen_reeks(self, conn):
        from energie_vlaanderen.infrastructure.db.importer import _scd2_bulk_upsert

        rijen = [
            {**_rij(date(2026, m, 1), "0.20"), "prijs_type": soort}
            for soort in ("variabel", "dynamisch")
            for m in (1, 2)
        ]
        _scd2_bulk_upsert(conn, tarief_afname, rijen)

        per_type: dict[str, list] = {}
        for v, t, _, soort in self._historiek(conn):
            per_type.setdefault(soort, []).append((v, t))

        assert per_type == {
            "variabel": [
                (date(2026, 1, 1), date(2026, 1, 31)),
                (date(2026, 2, 1), None),
            ],
            "dynamisch": [
                (date(2026, 1, 1), date(2026, 1, 31)),
                (date(2026, 2, 1), None),
            ],
        }
