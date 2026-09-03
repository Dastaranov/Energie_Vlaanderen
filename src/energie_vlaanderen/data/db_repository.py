"""De rekenengine gevoed uit de databank in plaats van uit CSV-bestanden.

De regel: **de berekening komt uit de code, de data uit de databank.** De
CSV-bestanden zijn een hulpmiddel om de databank te vullen; ze zijn geen bron
voor een berekening.

`DbDataRepository` biedt hetzelfde oppervlak als `DataRepository` — `products()`,
`dnb`, `dnb_for()`, `netbeheerders`, `tariefjaar` — zodat `Calculator` en
`Kostberekening` ongewijzigd blijven. Dat is de kern van de scheiding: wisselt de
bron, dan verandert er niets aan de rekenregels.

Drie dingen waarin de databank verschilt van de CSV-weg, en waarom het hier
opgelost wordt en niet in de rekenengine:

- **Schrijfwijze.** Het CSV schrijft `Afname`/`Injectie` en `Elektriciteit`, de
  databank `afname`/`injectie` en `elektriciteit` (migratie 0020). `Calculator`
  vergelijkt letterlijk op `Contracttype == "Afname"`, dus de vertaling gebeurt
  hier, op de grens.
- **Lange versus brede vorm.** Het CSV heeft één rij per component; de databank
  één rij per meterregister met de componenten als kolommen. `Product` verwacht
  de lange vorm, dus die wordt hier teruggebouwd.
- **Historiek.** Een versiemap draagt één momentopname; `tarief_afname` draagt
  maandelijkse SCD2 sinds januari 2025. Een berekening over april 2026 kan dus
  uit de databank wél en uit een enkele versiemap niet.

Eén bekend verschil met de CSV-weg, bewust en gedocumenteerd: producten waarvan
de bron alleen `fixed_fee_single`/`_double`/`_exclusive_night` levert en geen
algemene `fixed_fee`. `Calculator.supplier_cost()` leest alleen `fixed_fee` en
rekent voor die producten via het CSV dus géén vaste vergoeding aan. Uit de
databank komt hier wél een bedrag, want daar staat de vergoeding op de rij van
het metertype. Dat is correcter, maar het is een verschil; zie
`docs/plan databank als bron.md`.
"""
from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal
from typing import Any

import pandas as pd
import sqlalchemy as sa

from energie_vlaanderen.domain.models import Product
from energie_vlaanderen.nettarieven.netbeheerder import NetbeheerderRegister

LOG = logging.getLogger(__name__)


class DbDataRepositoryError(RuntimeError):
    pass


# De kolomnamen die `Calculator.grid_cost()` op `repo.dnb` verwacht. Ze komen
# uit het VREG-werkboek en zijn in de databank anders genoemd; de vertaling
# staat hier zodat de rekenengine niets van de databank hoeft te weten.
_DNB_KOLOMMEN = {
    "netbeheerder_code": "Netbeheerder",
    "klanttype": "Klanttype",
    "contract_richting": "Contracttype",
    "tarieftype": "Tarieftype",
    "tariefdetail": "Tariefdetail",
    "tariefnotering": "Tariefnotering",
    "prijs": "Prijs_num",
}

# De componentkolommen die voor het hele product gelden (niet per register).
_GEDEELDE_COMPONENTEN = {
    "groene_stroom_kwh": "green",
    "wkk_kwh": "wkk",
    "energiebijdrage_kwh": "bijdrage op de energie",
}


class DbDataRepository:
    """Leest producten, tarieven en netbeheerders uit PostgreSQL."""

    def __init__(self, conn: sa.Connection, *, tariefjaar: int) -> None:
        self.conn = conn
        self._tariefjaar = int(tariefjaar)
        self._dnb: pd.DataFrame | None = None
        self._netbeheerders: NetbeheerderRegister | None = None

    # -- nettarieven --------------------------------------------------------

    @property
    def tariefjaar(self) -> int:
        return self._tariefjaar

    @property
    def dnb(self) -> pd.DataFrame:
        """De nettarieven van dit tariefjaar, in de vorm die `Calculator` leest.

        VREG stelt de distributienettarieven per kalenderjaar vast, dus een
        tariefjaar begint op 1 januari. Er wordt op `geldig_van` gefilterd en
        niet op een geldigheidsinterval: de tabel draagt meerdere jaargangen, en
        "geldig op datum X" zou bij een jaargrens twee jaargangen kunnen
        teruggeven.
        """
        if self._dnb is not None:
            return self._dnb

        kolommen = list(_DNB_KOLOMMEN)
        rijen = self.conn.execute(
            sa.text(
                f"select {', '.join(kolommen)} from netbeheerder_tarief "  # noqa: S608
                "where geldig_van = :van"
            ),
            {"van": date(self._tariefjaar, 1, 1)},
        ).mappings().all()

        if not rijen:
            beschikbaar = sorted(
                str(r[0])[:4] for r in self.conn.execute(
                    sa.text("select distinct geldig_van from netbeheerder_tarief "
                            "order by geldig_van")
                )
            )
            raise DbDataRepositoryError(
                f"Geen nettarieven voor tariefjaar {self._tariefjaar} in de "
                f"databank. Beschikbaar: {', '.join(beschikbaar) or 'geen'}. "
                "Zonder nettarieven zou de netkost stil op nul uitkomen."
            )

        frame = pd.DataFrame([dict(r) for r in rijen]).rename(columns=_DNB_KOLOMMEN)
        # `Calculator` vergelijkt letterlijk op "Afname"; de databank schrijft
        # sinds migratie 0020 kleine letters.
        frame["Contracttype"] = frame["Contracttype"].str.capitalize()
        self._dnb = frame
        return frame

    # -- netbeheerders ------------------------------------------------------

    @property
    def netbeheerders(self) -> NetbeheerderRegister:
        """Postcode → netbeheerder, uit `gemeente` en `netbeheerder`.

        De tabel `gemeente` draagt de netbeheerder als code ("FK"), het register
        werkt met de naam ("Fluvius Kempen"); vandaar de join. De opzoeklogica
        zelf — inclusief de weigering om bij postcode 2387 te gokken — wordt
        hergebruikt en niet nagebouwd.
        """
        if self._netbeheerders is not None:
            return self._netbeheerders

        rijen = self.conn.execute(sa.text("""
            select g.postcode, g.naam,
                   ne.naam as dnb_elek,
                   ng.naam as dnb_gas
              from gemeente g
              left join netbeheerder ne on ne.code = g.dnb_elektriciteit
              left join netbeheerder ng on ng.code = g.dnb_gas
        """)).all()
        if not rijen:
            raise DbDataRepositoryError(
                "De tabel `gemeente` is leeg; zonder postcode-naar-netbeheerder "
                "is het nettarief niet te bepalen."
            )
        self._netbeheerders = NetbeheerderRegister.uit_rijen(
            ((str(p), str(n or ""), e, g) for p, n, e, g in rijen),
            herkomst="databank:gemeente",
        )
        return self._netbeheerders

    def dnb_for(
        self,
        postcode: str,
        gemeente: str = "",
        energie_type: str = "elektriciteit",
    ) -> tuple[str, str]:
        return self.netbeheerders.dnb_for(postcode, gemeente, energie_type)

    # -- producten ----------------------------------------------------------

    def products(
        self,
        year: int,
        month: int,
        segment: str,
        *,
        energy: str = "elektriciteit",
        direction: str = "afname",
    ) -> list[Product]:
        """De producten van één maand, opgebouwd uit de tariefhistoriek.

        `year`/`month` kiezen de maandsnapshot. Dat is wat een herberekening van
        april 2026 mogelijk maakt: de databank draagt elke maand apart, terwijl
        een versiemap er maar één bevat.

        Er wordt op `geldig_van` gefilterd en niet op het geldigheidsinterval.
        Een product dat in maart 2025 voor het laatst aangeboden werd, houdt zijn
        laatste rij open staan (`geldig_tot IS NULL`) — dat is correcte SCD2,
        maar op interval zoeken zou dat product ook in 2028 nog teruggeven.
        """
        richting = (direction or "afname").casefold()
        if richting.startswith("inj"):
            tabel = "tarief_injectie"
        elif richting.startswith("afn") or richting in ("consumption", "afname"):
            tabel = "tarief_afname"
        else:
            raise DbDataRepositoryError(
                f"Onbekende richting {direction!r}; verwacht afname of injectie."
            )

        rijen = self.conn.execute(
            sa.text(f"""
                select l.naam as leverancier, p.product_naam, p.segment,
                       p.energie_type, t.prijs_type, t.meter_type,
                       t.energieprijs_kwh, t.vaste_vergoeding_jaar,
                       t.groene_stroom_kwh, t.wkk_kwh, t.energiebijdrage_kwh,
                       t.param_a, t.param_b, t.param_c, t.param_d, t.param_z,
                       t.index_naam_a, t.index_naam_b, t.index_naam_c, t.index_naam_d,
                       t.index_waarde_a, t.index_waarde_b, t.index_waarde_c,
                       t.index_waarde_d, t.bron_bestand
                  from {tabel} t
                  join energie_product p on p.id = t.product_id
                  join leverancier l on l.id = p.leverancier_id
                 where t.geldig_van = :van
                   and lower(p.segment) = :segment
                   and lower(p.energie_type) = :energie
            """),  # noqa: S608 - tabelnaam uit een gesloten verzameling
            {
                "van": date(int(year), int(month), 1),
                "segment": (segment or "").casefold(),
                "energie": (energy or "").casefold(),
            },
        ).mappings().all()

        per_product: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
        for rij in rijen:
            sleutel = (rij["leverancier"], rij["product_naam"], rij["prijs_type"])
            per_product.setdefault(sleutel, []).append(dict(rij))

        producten: list[Product] = []
        for (leverancier, naam, prijs_type), groep in per_product.items():
            producten.append(self._bouw_product(
                groep, year=int(year), month=int(month), segment=segment,
                energy=energy, direction=direction,
                leverancier=leverancier, naam=naam, prijs_type=prijs_type,
            ))
        return producten

    @staticmethod
    def _bouw_product(
        groep: list[dict[str, Any]],
        *,
        year: int, month: int, segment: str, energy: str, direction: str,
        leverancier: str, naam: str, prijs_type: str,
    ) -> Product:
        components: dict[str, Decimal] = {}
        formulas: dict[str, dict] = {}

        for rij in groep:
            register = rij["meter_type"]

            prijs = rij["energieprijs_kwh"]
            if prijs is not None:
                components[register] = Decimal(str(prijs))

            formule: dict[str, Any] = {}
            for letter in ("a", "b", "c", "d", "z"):
                waarde = rij[f"param_{letter}"]
                if waarde is not None:
                    formule[letter] = Decimal(str(waarde))
            for letter in ("a", "b", "c", "d"):
                index_naam = rij[f"index_naam_{letter}"]
                if not index_naam:
                    continue
                index_waarde = rij[f"index_waarde_{letter}"]
                formule[f"index_{letter.upper()}"] = {
                    "name": str(index_naam),
                    "value": (
                        Decimal(str(index_waarde)) if index_waarde is not None else None
                    ),
                }
            if formule:
                formulas[register] = formule

        # De gedeelde componenten staan op elke rij van de groep; de eerste rij
        # die ze draagt volstaat.
        for rij in groep:
            for kolom, component in _GEDEELDE_COMPONENTEN.items():
                waarde = rij[kolom]
                if component not in components and waarde is not None:
                    components[component] = Decimal(str(waarde))

        # De vaste vergoeding hangt aan het metertype (`fixed_fee_single` naast
        # `fixed_fee_double`). `Calculator` leest maar één sleutel, dus de rij
        # van het enkelvoudige register is de juiste keuze: dat is het tarief
        # dat een aansluiting zonder dag/nachtmeter betaalt.
        vaste = next(
            (r["vaste_vergoeding_jaar"] for r in groep
             if r["meter_type"] == "single" and r["vaste_vergoeding_jaar"] is not None),
            None,
        )
        if vaste is None:
            vaste = next(
                (r["vaste_vergoeding_jaar"] for r in groep
                 if r["vaste_vergoeding_jaar"] is not None),
                None,
            )
        if vaste is not None:
            components["fixed_fee"] = Decimal(str(vaste))

        return Product(
            year=year,
            month=month,
            segment=str(segment),
            energy=str(energy),
            direction=str(direction),
            supplier=str(leverancier),
            name=str(naam),
            kind=str(prijs_type),
            components=components,
            formulas=formulas,
            source=str(groep[0].get("bron_bestand") or "databank"),
        )
