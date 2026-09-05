"""Het herbruikbare hart van `gebruiker bereken`: dossier + venster -> resultaat.

Geëxtraheerd uit `cli/gebruikers.py::run_gebruiker_bereken`, dat tot nu toe de
opzoeklogica (heffingen/transport/nettarieven/markt/metingen laden,
`Kostberekening` bouwen, per aansluitingspunt doorrekenen) en de tekst-/
JSON-weergave in één functie verweefde. Elke "wat als"-scenario (zie
`energie_vlaanderen.scenario`) heeft exact dezelfde opzoeklogica nodig als een
echte berekening — die staat hier dus precies één keer, niet twee keer zoals
CLAUDE.md bij de CSV-lezer als voorbeeld van een fout aanwijst ("De
CSV-lezer staat niet meer in `src/`").

De CLI-handler is hierdoor een dunne laag geworden: opzet via `bereken_dossier()`,
daarna tonen. Deze module drukt zelf niets af en kent geen `argparse.Namespace`
— alleen domeinobjecten in, domeinobjecten uit, zodat zowel de CLI als een
scenario (met een hypothetisch dossier of een gesimuleerde meetreeks) er
hetzelfde pad doorheen lopen.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Optional

import pandas as pd

from energie_vlaanderen.gebruikers.berekening import Berekening, BerekeningError, Kostberekening
from energie_vlaanderen.gebruikers.models import (
    Aansluitingspunt,
    EnergieType,
    GebruikersError,
)
from energie_vlaanderen.gebruikers.toml_io import Dossier
from energie_vlaanderen.heffingen.repository import HeffingenRepository
from energie_vlaanderen.nettarieven.transport import (
    TransportTariefError,
    TransportTariefRepository,
)
from energie_vlaanderen.settings import Settings
from energie_vlaanderen.utility.constants import D

import logging

LOG = logging.getLogger(__name__)


class OrchestratieError(GebruikersError):
    """Het dossier kon niet doorgerekend worden — vóór er per punt gerekend wordt."""


@dataclass(frozen=True)
class DossierResultaat:
    """Eén doorgerekend dossier.

    `resultaten` bevat alleen de punten die lukten; `mislukt` de reden waarom
    een ander punt dat niet deed. Een fout op het ene aansluitingspunt laat het
    andere niet vervallen — zie CLAUDE.md "Een fout op het ene punt laat het
    andere niet vervallen".
    """

    resultaten: tuple[tuple[Aansluitingspunt, Berekening], ...]
    mislukt: tuple[tuple[str, str], ...]
    dataversie: Optional[str]
    nettarieven_jaren: tuple[int, ...]
    metingen: Optional[pd.DataFrame]
    meetreeks: Optional[object]
    meetwaarschuwingen: tuple[str, ...]
    markt: Optional[pd.DataFrame]

    @property
    def totalen(self) -> dict[str, Decimal]:
        if not self.resultaten:
            return {}
        return {
            sleutel: sum((r.totalen[sleutel] for _, r in self.resultaten), D("0"))
            for sleutel in self.resultaten[0][1].totalen
        }

    @property
    def exactheidsklasse(self):
        from energie_vlaanderen.gebruikers.models import Exactheidsklasse
        if not self.resultaten:
            return Exactheidsklasse.SCENARIO
        return Exactheidsklasse.zwakste([r.exactheidsklasse for _, r in self.resultaten])


def laad_metingen(dossier: Dossier) -> tuple[Optional[object], tuple[str, ...]]:
    """De meetreeks uit het Fluvius-bestand van het dossier, plus haar waarschuwingen.

    De waarschuwingen komen mee omdat ze over de *kwaliteit* van het resultaat
    gaan: hoeveel intervallen Fluvius geschat heeft, hoeveel er ontbreken, of er
    onderbrekingen zijn. Ze verzwijgen zou een reeks met gaten laten doorgaan
    voor een volledige meting.
    """
    if dossier.fluvius_csv is None or not dossier.fluvius_csv.is_file():
        return None, ()
    from energie_vlaanderen.metering.fluvius_csv import (
        FluviusDataError,
        FluviusIntervals,
    )

    try:
        reeks = FluviusIntervals.read(dossier.fluvius_csv)
    except FluviusDataError as exc:
        return None, (str(exc),)
    if reeks.intervallen.empty:
        return None, ("Het meetbestand bevat geen bruikbare intervallen.",)
    return reeks, reeks.waarschuwingen


def laad_markt(settings: Settings, van: date, tot: date) -> Optional[pd.DataFrame]:
    """Day-ahead prijzen uit de lokale cache, zonder de API te bevragen.

    `allow_api=False`: een berekening mag niet stilzwijgend een netwerkoproep
    doen en dan minutenlang hangen. Wie verse prijzen wil, draait eerst
    `energievergelijker market sync --start --end`.
    """
    from datetime import datetime

    from energie_vlaanderen.data.paths import DataPaths
    from energie_vlaanderen.market.entsoe import EntsoeMarketData

    cache = DataPaths.from_settings(settings).market / "entsoe_cache.json"
    if not cache.is_file():
        return None
    try:
        df = EntsoeMarketData(cache=cache).load(
            datetime(van.year, van.month, van.day),
            datetime(tot.year, tot.month, tot.day),
            allow_api=False,
        )
    except Exception:
        # Een ontbrekende of onbruikbare cache is geen fout: enkel dynamische
        # producten hebben marktprijzen nodig, en die melden het zelf wanneer
        # ze ontbreken.
        return None
    return None if df.empty else df


def nettarieven_uit_databank(conn) -> dict:
    """Eén repository per tariefjaar dat de databank draagt.

    De nettarieven worden per kalenderjaar vastgesteld, maar een afrekening
    loopt zelden gelijk met het kalenderjaar. Anders dan bij de bestandsweg
    hoeft hier niet naar versiemappen gezocht te worden: `netbeheerder_tarief`
    draagt de jaargangen naast elkaar.
    """
    import sqlalchemy as sa

    from energie_vlaanderen.data.db_repository import DbDataRepository

    jaren = [
        int(r[0]) for r in conn.execute(sa.text(
            "select distinct extract(year from geldig_van)::int "
            "from netbeheerder_tarief order by 1"
        ))
    ]
    return {jaar: DbDataRepository(conn, tariefjaar=jaar) for jaar in jaren}


def bereken_dossier(
    dossier: Dossier,
    *,
    conn,
    settings: Settings,
    van: date,
    tot: date,
    versie: Optional[str] = None,
    metingen_override: Optional[pd.DataFrame] = None,
    meetwaarschuwingen_override: tuple[str, ...] = (),
    gebruik_metingen: bool = True,
) -> DossierResultaat:
    """Rekent `dossier` door over `[van, tot)`, aansluitingspunt per punt.

    `metingen_override` is de haak voor een "wat als"-scenario dat een
    gesimuleerde reeks wil laten doorrekenen in plaats van de Fluvius-meting
    van het dossier zelf (bv. `scenario.BatterijScenario`, dat de meetreeks na
    batterijdispatch meegeeft). Zonder override valt dit terug op het bestaande
    gedrag: `laad_metingen(dossier)`, of geen metingen als `gebruik_metingen`
    op `False` staat (het CLI-equivalent van `--geen-metingen`).

    Elektriciteit en aardgas worden **apart** doorgerekend: twee EAN's, twee
    contracten, twee tariefwerelden. Ze in één bedrag persen zou de herkomst
    van elke post laten verdwijnen.
    """
    from energie_vlaanderen.gebruikers.schatting import gasaandeel_uit_rlp0

    try:
        heffingen = HeffingenRepository.load(settings.project_root / "config" / "heffingen")
    except OSError as exc:
        raise OrchestratieError(str(exc)) from exc

    # Het vervoerstarief van Fluxys staat in geen VREG-werkboek en komt uit
    # config/nettarieven/. Zonder dat tarief weigert een gasberekening liever
    # dan er ongeveer 25 EUR per jaar naast te zitten.
    try:
        transport = TransportTariefRepository.load(
            settings.project_root / "config" / "nettarieven"
        )
    except (OSError, TransportTariefError) as exc:
        transport = None
        LOG.warning("Vervoerstarief niet geladen, gas kan niet gerekend worden: %s", exc)

    punten = [
        punt for punt in dossier.aansluitingspunten
        if punt.energie_type in (EnergieType.ELEKTRICITEIT, EnergieType.GAS)
    ]
    if not punten:
        raise OrchestratieError(
            f"Geen elektriciteits- of aardgasaansluiting in {dossier.bron}. "
            "Zonder aansluitingspunt is er geen netbeheerder en dus geen nettarief."
        )

    if versie:
        getoonde_versie = versie
    else:
        import sqlalchemy as sa
        getoonde_versie = conn.execute(sa.text(
            "select version_id from data_version where status = 'active' "
            "order by geactiveerd_op desc nulls last limit 1"
        )).scalar()

    from energie_vlaanderen.data.db_repository import DbDataRepositoryError

    try:
        nettarieven = nettarieven_uit_databank(conn)
    except DbDataRepositoryError as exc:
        raise OrchestratieError(str(exc)) from exc
    if not nettarieven:
        raise OrchestratieError(
            "Geen nettarieven in de databank. Laad ze met "
            "`energievergelijker db import --version <id>`."
        )
    repo = nettarieven[max(nettarieven)]

    omvormer_kva = next(
        (a.omvormer_kva for a in dossier.assets if a.omvormer_kva is not None),
        None,
    )

    meetreeks = None
    if metingen_override is not None:
        metingen = metingen_override
        meetwaarschuwingen = meetwaarschuwingen_override
    elif gebruik_metingen:
        meetreeks, meetwaarschuwingen = laad_metingen(dossier)
        metingen = meetreeks.intervallen if meetreeks is not None else None
    else:
        metingen = None
        meetwaarschuwingen = ()

    markt = laad_markt(settings, van, tot)

    def _gasverdeler(v, t):
        return gasaandeel_uit_rlp0(conn, v, t)

    rekenaar = Kostberekening(
        repo, heffingen,
        segment=str(dossier.gebruiker.segment),
        nettarieven_per_jaar=nettarieven,
        transport=transport,
        gasverdeler=_gasverdeler,
    )

    # Per aansluitingspunt één resultaat. Een fout op het ene punt laat het
    # andere niet vervallen: wie gas én elektriciteit heeft en waarvan alleen
    # het gascontract ontbreekt, hoort de elektriciteitskost gewoon te zien —
    # mét de melding waarom gas ontbreekt, want dan is het totaal onvolledig.
    resultaten: list[tuple[Aansluitingspunt, Berekening]] = []
    mislukt: list[tuple[str, str]] = []
    for punt in punten:
        try:
            resultaten.append((punt, rekenaar.bereken(
                punt,
                dossier.meter_van(punt),
                dossier.contracten_van(punt),
                dossier.opgaven_van(punt),
                van,
                tot,
                omvormer_kva=omvormer_kva or 0,
                extra_aannames=dossier.aannames,
                markt=markt,
                # De Fluvius-export in het dossier (of een override) is de
                # elektriciteitsreeks; ze aan een gaspunt meegeven zou
                # elektriciteitskwartieren als gasvolume laten doorgaan.
                metingen=(
                    metingen
                    if punt.energie_type is EnergieType.ELEKTRICITEIT
                    else None
                ),
            )))
        except (BerekeningError, GebruikersError) as exc:
            mislukt.append((str(punt.energie_type), str(exc)))

    if not resultaten:
        redenen = "; ".join(f"{soort}: {melding}" for soort, melding in mislukt)
        raise OrchestratieError(
            f"Geen enkel aansluitingspunt kon doorgerekend worden. {redenen}"
        )

    return DossierResultaat(
        resultaten=tuple(resultaten),
        mislukt=tuple(mislukt),
        dataversie=getoonde_versie,
        nettarieven_jaren=tuple(sorted(nettarieven)),
        metingen=metingen,
        meetreeks=meetreeks,
        meetwaarschuwingen=tuple(meetwaarschuwingen),
        markt=markt,
    )
