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

from energie_vlaanderen.audit.golden import FieldMismatch, GoldenAuditResult


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
        bevindingen += self._plausibiliteit()
        return DatabankRapport(bevindingen=tuple(bevindingen))

    # -- 4. plausibiliteit -------------------------------------------------

    def _plausibiliteit(self) -> list[Bevinding]:
        """De regels die `audit sanity` op de gestagede CSV's toepaste.

        Ze staan hier omdat de CSV's verdwijnen, maar ook omdat ze hier meer
        waard zijn: `db audit` draait binnen de importtransactie, dus een
        onmogelijke waarde houdt de publicatie tegen in plaats van te wachten
        tot iemand `audit sanity` aanroept. Die stap kon overgeslagen worden.

        De drempels zijn ongewijzigd overgenomen; alleen de bron verschilt.
        """
        gevonden: list[Bevinding] = []

        # Een vaste vergoeding van meer dan 500 EUR/jaar bestaat niet op de
        # residentiële markt; zo'n waarde wijst op een kolomverschuiving.
        for tabel in ("tarief_afname", "tarief_injectie"):
            if not self._tabel_bestaat(tabel):
                continue
            absurd = self.conn.execute(sa.text(
                f"select count(*) from {tabel} "  # noqa: S608
                "where vaste_vergoeding_jaar > 500"
            )).scalar() or 0
            if absurd:
                gevonden.append(Bevinding(
                    tabel=tabel, regel="Max vaste vergoeding overschreden",
                    melding=(
                        f"{absurd} rij(en) met een vaste vergoeding boven 500 "
                        "EUR/jaar. Dat bestaat niet op deze markt en wijst op "
                        "een verschoven kolom."
                    ),
                ))

            # Een negatieve energieprijs kan (marktprijzen worden negatief),
            # maar niet in deze orde van grootte: dat is geen tarief meer.
            extreem = self.conn.execute(sa.text(
                f"select count(*) from {tabel} "  # noqa: S608
                "where energieprijs_kwh < -100"
            )).scalar() or 0
            if extreem:
                gevonden.append(Bevinding(
                    tabel=tabel, regel="Extreem negatieve prijs",
                    melding=f"{extreem} rij(en) met een prijs onder -100.",
                ))

        # Nettarieven zijn gereguleerd en nooit negatief.
        if self._tabel_bestaat("netbeheerder_tarief"):
            totaal = self.conn.execute(
                sa.text("select count(*) from netbeheerder_tarief")
            ).scalar() or 0
            if totaal == 0:
                gevonden.append(Bevinding(
                    tabel="netbeheerder_tarief", regel="Tariefdata ontbreekt",
                    melding=(
                        "Geen enkele nettariefrij. Zonder nettarieven komt de "
                        "netkost stil op nul uit."
                    ),
                ))
            negatief = self.conn.execute(sa.text(
                "select count(*) from netbeheerder_tarief where prijs < 0"
            )).scalar() or 0
            if negatief:
                gevonden.append(Bevinding(
                    tabel="netbeheerder_tarief", regel="Geen negatieve tarieven",
                    melding=f"{negatief} nettarief/tarieven met een negatieve prijs.",
                ))

        # Een verbruiks- of opwekprofiel is een fysieke grootheid en kan niet
        # onder nul. Marktprijzen wél — vandaar de beperking tot RLP en SPP.
        if self._tabel_bestaat("marktcurve"):
            onmogelijk = self.conn.execute(sa.text(
                "select count(*) from marktcurve "
                "where curve_type in ('RLP', 'SPP') and waarde < 0"
            )).scalar() or 0
            if onmogelijk:
                gevonden.append(Bevinding(
                    tabel="marktcurve", regel="RLP/SPP altijd positief",
                    melding=(
                        f"{onmogelijk} profielwaarde(n) onder nul. Een verbruiks- "
                        "of opwekprofiel is een fysieke grootheid; negatief kan niet."
                    ),
                ))

        return gevonden

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


# De kolomnamen van het VREG-werkboek, zoals `TariffGoldenAuditor` ze verwacht.
# De databank noemt ze anders; de vertaling staat hier zodat de audit niets van
# het databankschema hoeft te weten.
_TARIEF_KOLOMMEN = {
    "netbeheerder_code": "Netbeheerder",
    "contract_richting": "Contracttype",
    "klanttype": "Klanttype",
    "tarieftype": "Tarieftype",
    "tariefdetail": "Tariefdetail",
    "tariefnotering": "Tariefnotering",
    "prijs": "Prijs_num",
    "source_sheet": "source_sheet",
    "source_row": "source_row",
}

# Welke klanttypes in welk bestand terechtkwamen. De pipeline splitst de
# elektriciteitstarieven over drie bestanden; de databank kent die splitsing
# niet, dus voor een vergelijking per domein moet ze hier gereproduceerd worden.
_HS_MS_KLANTTYPES = frozenset(
    {"ELEK_HS1", "ELEK_HS2", "ELEK_MS1", "ELEK_MS2", "ELEK_LS_DC"}
)


def nettarieven_als_frame(
    conn: sa.Connection,
    *,
    energie_type: str,
    richting: str,
    tariefjaar: int,
):
    """De nettarieven uit de databank, in de vorm van het gestagede CSV.

    Hiermee kan `audit golden` de **databank** tegen het bronwerkboek leggen in
    plaats van het CSV. Dat is wat de controle overeind houdt wanneer de
    CSV-weg verdwijnt: het werkboek blijft de onafhankelijke bron, alleen de
    kant die ermee vergeleken wordt verhuist.

    `richting` is "afname", "injectie" of "hoogspanning". Dat laatste is geen
    richting maar een bestandsindeling: de pipeline schrijft de hoogspannings-
    en middenspanningsklanttypes apart weg, met afname én injectie samen.
    """
    import pandas as pd

    from datetime import date

    kolommen = ", ".join(_TARIEF_KOLOMMEN)
    rijen = conn.execute(
        sa.text(
            f"select {kolommen} from netbeheerder_tarief "  # noqa: S608
            "where geldig_van = :van and energie_type = :energie"
        ),
        {"van": date(int(tariefjaar), 1, 1), "energie": energie_type},
    ).mappings().all()

    frame = pd.DataFrame([dict(r) for r in rijen])
    if frame.empty:
        return frame
    frame = frame.rename(columns=_TARIEF_KOLOMMEN)

    # De databank schrijft "afname"; het werkboek en de auditor "Afname".
    frame["Contracttype"] = frame["Contracttype"].str.capitalize()

    is_hs = frame["Klanttype"].isin(_HS_MS_KLANTTYPES)
    if richting == "hoogspanning":
        return frame[is_hs].reset_index(drop=True)
    return frame[~is_hs & frame["Contracttype"].str.casefold().eq(richting)].reset_index(
        drop=True
    )


# De vaste vergoeding hangt in de bron aan een meteropstelling en in de databank
# aan de registerrij van die opstelling. Dezelfde kaart als in de importer.
_VASTE_PER_METERTYPE = {
    "fixed_fee_single": ("single",),
    "fixed_fee_double": ("day", "night"),
    "fixed_fee_exclusive_night": ("exclusive_night",),
}

_GEDEELDE_KOLOM = {
    "green": "groene_stroom_kwh",
    "wkk": "wkk_kwh",
    "bijdrage op de energie": "energiebijdrage_kwh",
}


def _dec(waarde):
    from decimal import Decimal

    if waarde is None or str(waarde).strip() in ("", "nan", "None"):
        return None
    return Decimal(str(waarde).replace(",", "."))


def vtest_tegen_werkboek(conn: sa.Connection, werkboek):
    """Leg de vtest-waarden in de databank naast het bronwerkboek.

    Anders dan bij de nettarieven is dit géén positievergelijking. De databank
    draagt de vtest-data in brede vorm — één rij per meterregister, componenten
    als kolom — terwijl het werkboek lange vorm is. De rijaantallen verschillen
    dus per definitie, en juist bij ongelijke aantallen liep de oude
    positievergelijking uit de pas: 2.220 gemelde verschillen waarvan er geen
    enkele echt was. Er wordt hier daarom op sleutel vergeleken
    (leverancier, product, maand, segment, richting, component), en wat maar aan
    één kant bestaat wordt apart geteld in plaats van als verschil gemeld.

    Twee dingen die de databank bewust niet draagt en die dus niet vergeleken
    worden: `component_label` (de menselijke omschrijving) en de bronrij per
    component. Ze staan alleen in het werkboek, en dat blijft bewaard.
    """
    from collections import defaultdict

    import pandas as pd  # noqa: F401 - via de normalizer

    from energie_vlaanderen.infrastructure.db.importer import METER_TYPES
    from energie_vlaanderen.ingest.vtest.normalizer import VTestDataNormalizer
    from energie_vlaanderen.ingest.vtest.workbook import VTestWorkbookParser
    from energie_vlaanderen.utility.normalizer import ontleed_leveranciersnaam

    ontleed = VTestWorkbookParser().parse(werkboek)
    genormaliseerd = VTestDataNormalizer().normalize(
        ontleed.fixed, ontleed.variable_dynamic
    )

    groepen = defaultdict(list)
    for frame in (genormaliseerd.fixed, genormaliseerd.variable_dynamic):
        if frame is None or frame.empty:
            continue
        for rij in frame.to_dict("records"):
            basis = (
                int(rij["year"]), int(rij["month"]), str(rij["segment"]),
                str(rij["energy"]), str(rij["direction"]),
                # Dezelfde sleutel als de importer: die voegt "Dots Energy" en
                # "Dots energy" samen tot één leverancier.
                ontleed_leveranciersnaam(rij["supplier"]).naam.casefold(),
                str(rij["product"]).casefold(), str(rij["product_type"]),
            )
            groepen[basis].append(rij)

    bron = {}
    for basis, rijen in groepen.items():
        registers = {str(r["component"]).lower() for r in rijen} & set(METER_TYPES)
        for rij in rijen:
            component = str(rij["component"]).lower()
            bron[(*basis, component)] = rij
            doelen = _VASTE_PER_METERTYPE.get(component) or (
                tuple(registers) if component == "fixed_fee" else ()
            )
            for metertype in doelen:
                bron.setdefault((*basis, f"fixed_fee@{metertype}"), rij)

    databank = {}
    for tabel, richting in (("tarief_afname", "Afname"), ("tarief_injectie", "Injectie")):
        for rij in conn.execute(sa.text(f"""
            select l.naam lev, p.product_naam prod, p.segment, p.energie_type,
                   t.prijs_type, t.meter_type, t.energieprijs_kwh,
                   t.vaste_vergoeding_jaar, t.groene_stroom_kwh, t.wkk_kwh,
                   t.energiebijdrage_kwh, t.param_a, t.param_b, t.param_c,
                   t.param_d, t.param_z, t.index_waarde_a,
                   extract(year from t.geldig_van)::int jaar,
                   extract(month from t.geldig_van)::int maand
              from {tabel} t
              join energie_product p on p.id = t.product_id
              join leverancier l on l.id = p.leverancier_id
        """)).mappings():  # noqa: S608 - vaste tabelnamen
            basis = (
                rij["jaar"], rij["maand"], rij["segment"].capitalize(),
                rij["energie_type"].capitalize(), richting,
                rij["lev"].casefold(), rij["prod"].casefold(), rij["prijs_type"],
            )
            databank[(*basis, rij["meter_type"])] = rij
            for kolom, component in _GEDEELDE_KOLOM.items():
                if rij[component] is not None:
                    databank.setdefault((*basis, kolom), rij)
            if rij["vaste_vergoeding_jaar"] is not None:
                databank[(*basis, f"fixed_fee@{rij['meter_type']}")] = rij

    gemeen = set(bron) & set(databank)
    mismatches = []
    vergelijkingen = 0
    for sleutel in sorted(gemeen):
        bron_rij, db_rij = bron[sleutel], databank[sleutel]
        component = sleutel[-1]
        if component.startswith("fixed_fee@"):
            paren = [("price", db_rij["vaste_vergoeding_jaar"])]
        elif component in METER_TYPES:
            paren = [
                ("price", db_rij["energieprijs_kwh"]),
                ("a", db_rij["param_a"]), ("b", db_rij["param_b"]),
                ("c", db_rij["param_c"]), ("d", db_rij["param_d"]),
                ("z", db_rij["param_z"]),
                ("index_value_A", db_rij["index_waarde_a"]),
            ]
        else:
            paren = [("price", db_rij[_GEDEELDE_KOLOM[component]])]

        for veld, db_waarde in paren:
            verwacht, gevonden = _dec(bron_rij.get(veld)), _dec(db_waarde)
            if verwacht is None and gevonden is None:
                continue
            vergelijkingen += 1
            if verwacht != gevonden:
                mismatches.append(FieldMismatch(
                    domain="vtest_databank",
                    source_sheet=str(bron_rij.get("source_sheet", "")),
                    source_row=None,
                    field=veld,
                    csv_value=str(gevonden),
                    xlsx_value=str(verwacht),
                    row_key=f"{sleutel[5]}/{sleutel[6]}/{sleutel[8]}",
                ))

    return GoldenAuditResult(
        version_id="",
        domain="vtest_databank",
        source_xlsx=werkboek,
        total_rows=len(gemeen),
        verified_rows=vergelijkingen,
        mismatches=tuple(mismatches),
    )
