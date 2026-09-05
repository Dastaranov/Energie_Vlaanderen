"""Eén contract, één maand, één kost.

`bereken_kost()` is het rekenkundige tegenhangertje van `catalogus.py`: het
zoekt het `Product` op dat bij een leverancier/productnaam-combinatie hoort
en geeft het aan `Calculator.calculate()` — dezelfde rekenengine die
`gebruikers/berekening.py` gebruikt, hier alleen zonder de knip- en
dossierlaag daarboven. Voor een volledig dossier (contractwissels,
tariefkaartbevriezing, jaarwissels) is dat pakket het juiste startpunt; dit
hier is de kortste weg van "leverancier + product + verbruik" naar een
bedrag, bedoeld om simulaties op te bouwen.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from energie_vlaanderen.domain.models import Cost, Product, Profile
from energie_vlaanderen.utility.normalizer import leverancier_sleutel

if TYPE_CHECKING:
    from energie_vlaanderen.simulatie.context import SimulatieContext

# `SimulatieProfiel` is bewust een alias en geen eigen dataclass: het domein
# heeft al een `Profile` met precies de velden (postcode, verbruik, meter,
# maandpieken, ...) die `Calculator` verwacht. Een tweede vorm ernaast zou
# twee wegen naar dezelfde invoer scheppen — exact wat CLAUDE.md bij de
# CSV-lezer als fout aanwijst.
SimulatieProfiel = Profile


class BerekeningError(RuntimeError):
    """Het product voor deze leverancier/maand-combinatie is niet te vinden."""


def zoek_product(
    ctx: "SimulatieContext",
    *,
    leverancier: str,
    product_naam: str,
    jaar: int,
    maand: int,
    segment: str,
    energie: str = "elektriciteit",
    richting: str = "afname",
    prijs_type: Optional[str] = None,
) -> Product:
    """Eén `Product` uit de productenlijst van deze maand.

    Anders dan `Kostberekening.zoek_product()` in `gebruikers/berekening.py`
    volgt dit geen bevroren tariefkaart — het leest gewoon de snapshot van
    `jaar`/`maand`, wat voor een simulatie (in plaats van het naspelen van
    een bestaand contract) het juiste gedrag is: je wil weten wat dít
    product in díé maand kostte, niet wat een klant er ooit voor tekende.

    `prijs_type` ("vast", "variabel" of "dynamisch") ontbindt het geval waar
    dezelfde productnaam in meerdere smaken bestaat — "Bolt Variabel" staat
    bijvoorbeeld zowel als `variabel` als `dynamisch` in de export.
    """
    kandidaten = ctx.repo.products(jaar, maand, segment, energy=energie, direction=richting)
    if not kandidaten:
        raise BerekeningError(
            f"Geen productdata voor {jaar}-{maand:02d} ({segment}, "
            f"{energie.casefold()}, {richting.casefold()})."
        )

    gezocht_lev = leverancier_sleutel(leverancier)
    gezocht_naam = product_naam.casefold().strip()
    treffers = [
        p for p in kandidaten
        if leverancier_sleutel(p.supplier) == gezocht_lev
        and p.name.casefold().strip() == gezocht_naam
    ]
    if prijs_type:
        op_type = [p for p in treffers if p.kind.casefold().startswith(prijs_type.casefold())]
        if op_type:
            treffers = op_type

    if not treffers:
        van_leverancier = sorted({p.name for p in kandidaten if leverancier_sleutel(p.supplier) == gezocht_lev})
        raise BerekeningError(
            f"Product {product_naam!r} van {leverancier!r} niet gevonden voor "
            f"{jaar}-{maand:02d}. "
            + (
                f"Producten van deze leverancier die maand: {', '.join(van_leverancier)}."
                if van_leverancier
                else f"Deze leverancier heeft geen producten in {jaar}-{maand:02d}."
            )
        )
    if len(treffers) > 1:
        smaken = sorted({t.kind for t in treffers})
        raise BerekeningError(
            f"Product {product_naam!r} van {leverancier!r} bestaat in "
            f"{jaar}-{maand:02d} in meerdere varianten ({', '.join(smaken)}); "
            "geef `prijs_type` mee om te kiezen."
        )
    return treffers[0]


def bereken_kost(
    ctx: "SimulatieContext",
    *,
    leverancier: str,
    product_naam: str,
    jaar: int,
    maand: int,
    profiel: Profile,
    energie: str = "elektriciteit",
    prijs_type: Optional[str] = None,
    injectie_leverancier: Optional[str] = None,
    injectie_product_naam: Optional[str] = None,
    injectie_prijs_type: Optional[str] = None,
    sta_tariefjaarverschil: bool = False,
) -> Cost:
    """Reken één contract door voor `profiel` — met de productsnapshot van
    `jaar`/`maand` en de nettarieven van `ctx.tariefjaar`.

    `profiel` draagt **jaarvolumes**: `grid_cost()` schaalt het
    capaciteitstarief, de vaste term, het databeheer en de wettelijke
    ondergrens over 365 dagen, en de accijnsschijven in `Calculator._levies()`
    zijn progressief over het jaarverbruik (zie CLAUDE.md "Reken op
    jaarbasis en schaal daarna naar dagen"). Wie hier maandvolumes ingeeft,
    krijgt een volledig jaar aan vaste kosten over één maand verbruik — de
    fout uit `gebruikers/berekening.py` in nieuwe vorm.

    `jaar` moet gelijk zijn aan `ctx.tariefjaar`, tenzij
    `sta_tariefjaarverschil=True` expliciet meegegeven wordt. Zonder die
    toets zou een aanroep met `jaar=2025` op een context met
    `tariefjaar=2026` een leverancierskost van 2025 combineren met
    nettarieven van 2026 — twee regimes door elkaar, en het resultaat ziet
    er plausibel uit. Precies dit toetst `Kostberekening` per deelperiode in
    `gebruikers/berekening.py`; hier gebeurt het in het klein, want deze
    functie kent geen deelperiodes.

    Geeft `injectie_leverancier`/`injectie_product_naam` mee zodra `profiel`
    injectievolumes draagt — zonder terugleveringsproduct waarschuwt
    `Calculator.calculate()` en blijft het injectiekrediet op 0, wat de
    kost te hoog zou laten uitkomen zonder dat er iets faalt (zie CLAUDE.md
    "Geen injectieproduct is geen injectievergoeding van nul").

    `energie="gas"` wordt door de catalogus wel geleverd maar door
    `Calculator.calculate()` geweigerd: alleen elektriciteit-laagspanning is
    vandaag doorgerekend (zie CLAUDE.md, `Calculator`-sectie).
    """
    if jaar != ctx.tariefjaar and not sta_tariefjaarverschil:
        raise BerekeningError(
            f"jaar={jaar} wijkt af van de nettarieven van deze context "
            f"(tariefjaar={ctx.tariefjaar}). Open een simulatie met "
            f"tariefjaar={jaar}, of geef sta_tariefjaarverschil=True mee als "
            "dat bewust is."
        )

    product = zoek_product(
        ctx, leverancier=leverancier, product_naam=product_naam, jaar=jaar,
        maand=maand, segment=profiel.segment, energie=energie,
        richting="afname", prijs_type=prijs_type,
    )

    inject_product: Optional[Product] = None
    if injectie_leverancier and injectie_product_naam:
        inject_product = zoek_product(
            ctx, leverancier=injectie_leverancier, product_naam=injectie_product_naam,
            jaar=jaar, maand=maand, segment=profiel.segment, energie=energie,
            richting="injectie", prijs_type=injectie_prijs_type,
        )

    return ctx.calculator.calculate(product, profiel, inject_product=inject_product)
