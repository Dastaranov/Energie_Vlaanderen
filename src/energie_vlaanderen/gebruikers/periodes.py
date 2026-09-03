"""Snijdt een berekeningsvenster op elke grens van elke tijdas.

Het probleem dat deze module oplost: "een contract is altijd voor een periode"
is niet één tijdas maar drie, en ze schuiven onafhankelijk van elkaar.

1. **Contractgeldigheid** — van/tot per aansluitingspunt. Een leverancierswissel
   halverwege het jaar knipt het venster.
2. **De tariefkaart binnen dat contract** — een vast contract volgt de actuele
   tariefkaart níet; de prijs bevriest bij ondertekening
   (`Leveringscontract.prijs_bevriest`). Een variabel of dynamisch contract
   volgt wel een formule per indexatieperiode.
3. **De gereguleerde componenten** — heffingen (`geldig_vanaf`), nettarieven per
   tariefjaar, btw. Die trekken zich van het contract niets aan: de bijzondere
   accijns wijzigde op 01/08/2026 midden in elk lopend contract.

`Calculator` kan dit niet zelf: `Profile` draagt jaartotalen en `_levies()` neemt
één peildatum. In plaats van de rekenengine te herschrijven zetten we deze
snijder ervóór — reken per deelperiode, tel op. Dat is ook de volgorde van
Manifest §10 (stap 2: "selecteer product-, net-, heffings- en btw-versies op
geldigheidsdatum").

Alle periodes zijn half-open `[van, tot)`. Een grens op 01/08 hoort bij de
periode die op 01/08 begint, nooit bij allebei.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Iterable, Optional, Sequence

from energie_vlaanderen.gebruikers.models import (
    GebruikersError,
    Leveringscontract,
)
from energie_vlaanderen.utility.constants import D


@dataclass(frozen=True)
class Tijdasgrens:
    """Eén datum waarop iets verandert, met de reden erbij.

    De reden is geen versiering: ze komt terecht in het resultaat, zodat een
    lezer ziet wáárom een jaar in vier stukken uiteenviel in plaats van te
    moeten raden.
    """

    datum: date
    reden: str


@dataclass(frozen=True)
class Deelperiode:
    """Een stuk van het berekeningsvenster waarbinnen niets verandert."""

    van: date
    tot: date
    contract: Optional[Leveringscontract]
    redenen: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.tot <= self.van:
            raise GebruikersError(
                f"Deelperiode {self.van}..{self.tot} loopt niet vooruit."
            )

    @property
    def dagen(self) -> int:
        return (self.tot - self.van).days

    def aandeel_van(self, totaal_dagen: int) -> Decimal:
        """Het deel van een groter venster dat deze periode beslaat.

        Uitgedrukt in dagen, niet in maanden: maanden zijn ongelijk lang en een
        contractwissel valt zelden op een maandgrens. Dit is een *pro rata
        temporis*-verdeling en dus zelf een aanname — wie een profiel heeft,
        verdeelt beter met `schatting.verdeel_over_periodes()`.
        """
        if totaal_dagen <= 0:
            raise GebruikersError("Een venster van nul dagen heeft geen aandeel.")
        return D(self.dagen) / D(totaal_dagen)


def contractgrenzen(contracten: Iterable[Leveringscontract]) -> list[Tijdasgrens]:
    grenzen: list[Tijdasgrens] = []
    for contract in contracten:
        etiket = f"{contract.leverancier} — {contract.product}"
        grenzen.append(Tijdasgrens(contract.geldig_van, f"contract begint: {etiket}"))
        if contract.geldig_tot is not None:
            grenzen.append(Tijdasgrens(contract.geldig_tot, f"contract eindigt: {etiket}"))
    return grenzen


def heffingengrenzen(heffingen, energievorm: str = "elektriciteit") -> list[Tijdasgrens]:
    """Elke ingangsdatum van een accijnsregime, energiefondsjaar en btw-tarief.

    Neemt een `HeffingenRepository` maar typt hem niet: dat zou een importcyclus
    maken met een module die niets van gebruikers hoeft te weten.
    """
    grenzen: list[Tijdasgrens] = []

    tabel = heffingen.accijns_tabellen().get(energievorm)
    if tabel is not None:
        for schijf in tabel.schijven:
            grenzen.append(
                Tijdasgrens(
                    schijf.geldig_vanaf,
                    f"accijnsregime {energievorm}/{schijf.klantcategorie}",
                )
            )

    for tarief in heffingen.energiefonds_tarieven():
        grenzen.append(
            Tijdasgrens(date(tarief.jaar, 1, 1), f"energiefonds {tarief.jaar}")
        )

    for tarief in heffingen.btw_tarieven():
        # `BtwTarief.geldig_vanaf` is tekst in de masterdata, geen date. Een
        # onleesbare waarde stil overslaan zou een tariefwissel onzichtbaar
        # maken, dus dat melden we via een harde fout.
        ruw = str(tarief.geldig_vanaf).strip()
        if not ruw:
            continue
        try:
            grenzen.append(
                Tijdasgrens(date.fromisoformat(ruw), f"btw {tarief.component}")
            )
        except ValueError as exc:
            raise GebruikersError(
                f"Btw-tarief '{tarief.component}' heeft een onleesbare "
                f"ingangsdatum '{ruw}'; verwacht JJJJ-MM-DD."
            ) from exc

    return grenzen


def tariefjaargrenzen(van: date, tot: date) -> list[Tijdasgrens]:
    """1 januari van elk jaar in het venster.

    De nettarieven worden per tariefjaar goedgekeurd en gepubliceerd; een
    berekening over een jaarwissel gebruikt dus twee tariefwerkboeken. Zie
    `docs/jaarwissel 2026-2027.md`.
    """
    return [
        Tijdasgrens(date(jaar, 1, 1), f"tariefjaar {jaar}")
        for jaar in range(van.year, tot.year + 1)
    ]


def indexatiegrenzen(
    contracten: Iterable[Leveringscontract], van: date, tot: date
) -> list[Tijdasgrens]:
    """Elke maandwissel waarop een niet-bevroren contract loopt.

    Een variabel of dynamisch contract volgt een indexatieformule die per
    periode een andere waarde aanneemt; de V-test-export levert die als
    maandsnapshot (20 maanden, januari 2025 tot en met augustus 2026). Zonder
    deze grenzen zou één maandprijs over de hele contractduur uitgesmeerd
    worden: een variabel contract dat op 1 augustus begint en tot het jaareinde
    loopt, kreeg dan vijf maanden lang de augustusindex.

    Voor een vast contract is er niets te knippen — daar ligt de prijs juist
    stil, en `tariefkaartgrenzen()` legt vast wélke kaart geldt.
    """
    lopend = [c for c in contracten if not c.prijs_bevriest]
    if not lopend:
        return []

    grenzen: list[Tijdasgrens] = []
    jaar, maand = van.year, van.month
    while True:
        moment = date(jaar, maand, 1)
        if moment >= tot:
            break
        if moment > van and any(
            c.geldig_van <= moment and (c.geldig_tot is None or moment < c.geldig_tot)
            for c in lopend
        ):
            grenzen.append(
                Tijdasgrens(moment, f"indexatieperiode {moment:%Y-%m}")
            )
        maand += 1
        if maand > 12:
            jaar, maand = jaar + 1, 1
    return grenzen


def tariefkaartgrenzen(contracten: Iterable[Leveringscontract]) -> list[Tijdasgrens]:
    """De bevriezingsdatum van elke vaste tariefkaart."""
    grenzen: list[Tijdasgrens] = []
    for contract in contracten:
        if not contract.prijs_bevriest:
            continue
        peil = contract.peil_tariefkaart()
        grenzen.append(
            Tijdasgrens(peil, f"bevroren tariefkaart: {contract.product}")
        )
    return grenzen


def _contract_op(
    contracten: Sequence[Leveringscontract], moment: date
) -> Optional[Leveringscontract]:
    """Het contract dat op `moment` loopt.

    Overlappen er twee, dan is dat een gegevensfout en geen keuze die deze
    functie mag maken — stil de eerste nemen zou een verkeerde prijs geven
    zonder dat iemand het merkt.
    """
    lopend = [
        contract
        for contract in contracten
        if contract.geldig_van <= moment
        and (contract.geldig_tot is None or moment < contract.geldig_tot)
    ]
    if len(lopend) > 1:
        namen = ", ".join(f"{c.leverancier}/{c.product}" for c in lopend)
        raise GebruikersError(
            f"Op {moment} lopen {len(lopend)} contracten tegelijk ({namen}). "
            "Eén aansluitingspunt heeft op elk moment één leveringscontract; "
            "corrigeer de geldigheidsperiodes."
        )
    return lopend[0] if lopend else None


def snijd(
    van: date,
    tot: date,
    contracten: Sequence[Leveringscontract],
    extra_grenzen: Iterable[Tijdasgrens] = (),
) -> list[Deelperiode]:
    """Knip `[van, tot)` op elke grens die erbinnen valt.

    Een deelperiode zonder contract krijgt `contract=None` in plaats van
    overgeslagen te worden. Een gat in de contracthistoriek is informatie: het
    betekent dat er over die dagen niet gerekend kan worden, en dat hoort de
    oproeper te zien in plaats van een stilzwijgend te laag totaal te krijgen.
    """
    if tot <= van:
        raise GebruikersError(
            f"Het berekeningsvenster [{van}, {tot}) loopt niet vooruit."
        )

    alle = list(contractgrenzen(contracten))
    alle.extend(tariefkaartgrenzen(contracten))
    alle.extend(indexatiegrenzen(contracten, van, tot))
    alle.extend(tariefjaargrenzen(van, tot))
    alle.extend(extra_grenzen)

    redenen_per_datum: dict[date, list[str]] = {}
    for grens in alle:
        if van < grens.datum < tot:
            redenen_per_datum.setdefault(grens.datum, []).append(grens.reden)

    knippunten = [van, *sorted(redenen_per_datum), tot]

    periodes: list[Deelperiode] = []
    for begin, einde in zip(knippunten, knippunten[1:]):
        if einde <= begin:
            continue
        periodes.append(
            Deelperiode(
                van=begin,
                tot=einde,
                contract=_contract_op(contracten, begin),
                redenen=tuple(sorted(redenen_per_datum.get(begin, ["venstergrens"]))),
            )
        )
    return periodes


def gaten(periodes: Sequence[Deelperiode]) -> list[Deelperiode]:
    """De deelperiodes zonder contract — expliciet op te vragen, niet te negeren."""
    return [periode for periode in periodes if periode.contract is None]
