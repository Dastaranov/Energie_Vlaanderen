"""Toetst of de databank bevat wat een berekening nodig heeft.

Deze controle bestaat omdat 681 tests een lege kolom over 25.937 rijen niet
vonden. De reden is structureel: 644 tests raken de databank helemaal niet, en
de 37 die dat wél doen schrijven eerst hun eigen CSV van één tot drie rijen,
importeren die in een teruggerolde transactie en toetsen dan díé rijen. Geen
enkele test keek ooit naar de werkelijk geïmporteerde dataset.

Daardoor bleef `energieprijs_kwh` — de grootste post van elke factuur — op alle
tariefrijen leeg zonder dat er iets faalde. De import meldde netjes "25.937
tarief-snapshots".

Wat hier getoetst wordt is dus niet de code maar de **inhoud**: bevat de
databank, zoals ze er nu bij staat, genoeg om een factuur mee te berekenen? Dat
is een vraag die alleen tegen de echte data te beantwoorden is, en ze hoort bij
de pipeline te horen en niet alleen bij pytest — een integratietest die in CI
overgeslagen wordt, kan jarenlang niet draaien zonder dat iemand het merkt.
"""
from __future__ import annotations

from dataclasses import dataclass

import sqlalchemy as sa


@dataclass(frozen=True)
class Bevinding:
    tabel: str
    regel: str
    melding: str
    # Een fout betekent: de import is stuk. Een waarschuwing betekent: de bron
    # levert het niet. Dat onderscheid is nodig omdat een poort die permanent
    # rood staat, wordt uitgezet — en dan mist ze ook de dag dat er echt iets
    # breekt. Zeven producten waarvoor VREG geen energiecomponent publiceert
    # horen de publicatie van een verder gezonde dataset niet tegen te houden.
    ernst: str = "fout"


@dataclass(frozen=True)
class DatabankRapport:
    bevindingen: tuple[Bevinding, ...]

    @property
    def fouten(self) -> tuple[Bevinding, ...]:
        return tuple(b for b in self.bevindingen if b.ernst == "fout")

    @property
    def waarschuwingen(self) -> tuple[Bevinding, ...]:
        return tuple(b for b in self.bevindingen if b.ernst != "fout")

    @property
    def geslaagd(self) -> bool:
        return not self.fouten

    def geslaagd_streng(self) -> bool:
        return not self.bevindingen


# Kolommen die over de hele tabel nooit allemaal leeg mogen zijn. Niet "geen
# enkele NULL": een tarief dat niet bestaat hoort NULL te zijn. Maar een kolom
# die op élke rij leeg is, betekent dat de import haar nooit gevuld heeft.
_NOOIT_HELEMAAL_LEEG: dict[str, tuple[str, ...]] = {
    "tarief_afname": ("energieprijs_kwh", "vaste_vergoeding_jaar",
                      "index_naam_a", "index_waarde_a"),
    "tarief_injectie": ("energieprijs_kwh", "index_naam_a", "index_waarde_a"),
    "netbeheerder_tarief": ("prijs", "geldig_tot"),
    "energie_product": ("vreg_id", "tariefkaart_url"),
    "vtest_contract": ("datum_intekenen_van", "link_tariefkaart", "geldig_van"),
    "marktcurve": ("waarde", "tijdstip"),
}

# Tabellen die een schrijfwijze van de energievorm dragen. Lopen die uiteen,
# dan levert een join tussen twee van deze tabellen stil nul rijen op.
_ENERGIE_TYPE_TABELLEN = (
    "energie_product", "netbeheerder_tarief", "marktcurve",
)


class DatabankAudit:
    """Controleert de inhoud van de databank tegen wat een berekening vraagt."""

    def __init__(self, conn: sa.Connection) -> None:
        self.conn = conn

    def run(self) -> DatabankRapport:
        bevindingen: list[Bevinding] = []
        bevindingen += self._lege_kolommen()
        bevindingen += self._tarieven_zijn_bruikbaar()
        bevindingen += self._energievorm_is_consistent()
        return DatabankRapport(bevindingen=tuple(bevindingen))

    # -- 1. kolommen die nooit helemaal leeg mogen zijn --------------------

    def _lege_kolommen(self) -> list[Bevinding]:
        gevonden: list[Bevinding] = []
        for tabel, kolommen in _NOOIT_HELEMAAL_LEEG.items():
            if not self._tabel_bestaat(tabel):
                continue
            totaal = self.conn.execute(
                sa.text(f"select count(*) from {tabel}")  # noqa: S608 - vaste namen
            ).scalar() or 0
            if totaal == 0:
                continue
            for kolom in kolommen:
                if not self._kolom_bestaat(tabel, kolom):
                    continue
                gevuld = self.conn.execute(
                    sa.text(f"select count({kolom}) from {tabel}")  # noqa: S608
                ).scalar() or 0
                if gevuld == 0:
                    gevonden.append(Bevinding(
                        tabel=tabel,
                        regel="kolom volledig leeg",
                        melding=(
                            f"{tabel}.{kolom} is leeg op alle {totaal} rijen. "
                            "Dat is geen ontbrekend tarief maar een import die "
                            "de kolom nooit vult."
                        ),
                    ))
        return gevonden

    # -- 2. is er per product-maand iets om mee te rekenen? ----------------

    def _tarieven_zijn_bruikbaar(self) -> list[Bevinding]:
        """Elke product-maand moet minstens één bruikbaar register hebben.

        Bruikbaar = er staat een energieprijs, óf er staat een formule met een
        indexwaarde om in te vullen. Per rij toetsen zou te streng zijn: de
        import maakt voor elke groep ook een `single`-rij aan wanneer de bron
        dat register niet kent, en die hoort leeg te blijven.
        """
        gevonden: list[Bevinding] = []
        for tabel in ("tarief_afname", "tarief_injectie"):
            if not self._tabel_bestaat(tabel):
                continue
            onbruikbaar = self.conn.execute(sa.text(f"""
                select count(*) from (
                    select product_id, geldig_van, prijs_type
                    from {tabel}
                    group by 1, 2, 3
                    having count(energieprijs_kwh) = 0
                       and count(index_waarde_a) = 0
                ) x
            """)).scalar() or 0  # noqa: S608 - vaste tabelnamen
            totaal = self.conn.execute(sa.text(f"""
                select count(*) from (
                    select product_id, geldig_van, prijs_type
                    from {tabel} group by 1, 2, 3
                ) x
            """)).scalar() or 0  # noqa: S608
            if totaal and onbruikbaar:
                # Alles onbruikbaar betekent dat de import de prijzen niet
                # wegschrijft — dat is een fout in de code. Een handvol
                # onbruikbare product-maanden betekent dat de V-test-export
                # voor die producten geen energiecomponent publiceert; dan
                # staat er alleen groene stroom, WKK en een vaste vergoeding
                # in de bron. Dat valt niet met code op te lossen.
                alles = onbruikbaar == totaal
                gevonden.append(Bevinding(
                    tabel=tabel,
                    regel="geen prijs en geen formule",
                    ernst="fout" if alles else "waarschuwing",
                    melding=(
                        f"{onbruikbaar} van de {totaal} product-maanden dragen "
                        "noch een energieprijs noch een indexwaarde. "
                        + ("De import vult de prijzen niet."
                           if alles else
                           "Voor die producten publiceert de bron geen "
                           "energiecomponent; ze zijn niet door te rekenen.")
                    ),
                ))
        return gevonden

    # -- 3. één schrijfwijze voor de energievorm ---------------------------

    def _energievorm_is_consistent(self) -> list[Bevinding]:
        per_tabel: dict[str, set[str]] = {}
        for tabel in _ENERGIE_TYPE_TABELLEN:
            if not self._tabel_bestaat(tabel) or not self._kolom_bestaat(tabel, "energie_type"):
                continue
            waarden = {
                str(r[0]) for r in self.conn.execute(
                    sa.text(f"select distinct energie_type from {tabel} "  # noqa: S608
                            "where energie_type is not null and energie_type <> ''")
                )
            }
            if waarden:
                per_tabel[tabel] = waarden

        alle = set().union(*per_tabel.values()) if per_tabel else set()
        # Twee schrijfwijzen van hetzelfde woord: "Elektriciteit" naast
        # "elektriciteit". Een join op deze kolom geeft dan stil nul rijen.
        genormaliseerd: dict[str, set[str]] = {}
        for waarde in alle:
            genormaliseerd.setdefault(waarde.casefold(), set()).add(waarde)

        gevonden: list[Bevinding] = []
        for sleutel, schrijfwijzen in sorted(genormaliseerd.items()):
            if len(schrijfwijzen) > 1:
                waar = {t: sorted(v & schrijfwijzen) for t, v in per_tabel.items()
                        if v & schrijfwijzen}
                gevonden.append(Bevinding(
                    tabel=", ".join(sorted(waar)),
                    regel="energie_type niet eenduidig",
                    melding=(
                        f"'{sleutel}' staat in meerdere schrijfwijzen "
                        f"({sorted(schrijfwijzen)}): {waar}. Een join tussen "
                        "deze tabellen levert stil nul rijen op."
                    ),
                ))
        return gevonden

    # -- hulpjes ------------------------------------------------------------

    def _tabel_bestaat(self, tabel: str) -> bool:
        return bool(self.conn.execute(
            sa.text("select 1 from information_schema.tables "
                    "where table_schema='public' and table_name=:t"),
            {"t": tabel},
        ).scalar())

    def _kolom_bestaat(self, tabel: str, kolom: str) -> bool:
        return bool(self.conn.execute(
            sa.text("select 1 from information_schema.columns "
                    "where table_schema='public' and table_name=:t and column_name=:c"),
            {"t": tabel, "c": kolom},
        ).scalar())
