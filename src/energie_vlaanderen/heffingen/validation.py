"""Structurele controle op de heffingen-masterdata.

`config/heffingen/` is handgeschreven en wordt niet gescrapet, dus een typfout
komt er zonder slag of stoot in. Deze module toetst wat zonder netwerk te
toetsen valt: dat elke tarieftabel een sluitende schijvenindeling heeft, dat
regimes elkaar netjes opvolgen, en welke cijfers nog niet tegen een bron
gelegd zijn.

Wat hier *niet* gebeurt is de inhoudelijke controle — of 46,00 EUR/MWh ook
werkelijk het geldende tarief is. Dat doet `ingest.vtest.calibration` door het
uit vtest.be terug te rekenen, en `scripts/check_tarieven.py` door beide naast
elkaar te leggen.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path

from energie_vlaanderen.heffingen.models import AccijnsSchijf
from energie_vlaanderen.heffingen.repository import HeffingenRepository


@dataclass(frozen=True)
class Bevinding:
    ernst: str  # "fout" | "waarschuwing" | "info"
    onderwerp: str
    bericht: str


def _regimes(
    schijven: tuple[AccijnsSchijf, ...],
) -> dict[tuple[str, date], list[AccijnsSchijf]]:
    groepen: dict[tuple[str, date], list[AccijnsSchijf]] = defaultdict(list)
    for schijf in schijven:
        groepen[(schijf.klantcategorie, schijf.geldig_vanaf)].append(schijf)
    return groepen


def controleer_accijns(repo: HeffingenRepository) -> list[Bevinding]:
    """Toets elke accijnstabel op een sluitende schijvenindeling.

    Een regime is sluitend als de schijven bij 0 MWh beginnen, elkaar zonder
    gat of overlap opvolgen, en precies één schijf zonder bovengrens hebben.
    Een gat betekent stilzwijgend 0 EUR heffing over dat verbruik; een overlap
    betekent dubbel tellen. Beide zijn fouten die in een berekening onzichtbaar
    blijven, dus ze worden hier hard gemeld.
    """
    bevindingen: list[Bevinding] = []

    for energievorm, tabel in sorted(repo.accijns_tabellen().items()):
        if not tabel.schijven:
            bevindingen.append(
                Bevinding("fout", energievorm, "Tabel bevat geen enkele schijf.")
            )
            continue

        for (categorie, ingang), regime in sorted(
            _regimes(tabel.schijven).items(), key=lambda kv: (kv[0][0], kv[0][1])
        ):
            onderwerp = f"{energievorm}/{categorie}@{ingang.isoformat()}"
            geordend = sorted(regime, key=lambda s: s.van_mwh)

            if geordend[0].van_mwh != Decimal(0):
                bevindingen.append(
                    Bevinding(
                        "fout",
                        onderwerp,
                        f"Eerste schijf begint bij {geordend[0].van_mwh} MWh "
                        "in plaats van 0 — verbruik daaronder zou onbelast blijven.",
                    )
                )

            for vorige, volgende in zip(geordend, geordend[1:]):
                if vorige.tot_mwh is None:
                    bevindingen.append(
                        Bevinding(
                            "fout",
                            onderwerp,
                            f"Schijf vanaf {vorige.van_mwh} MWh heeft geen "
                            "bovengrens maar wordt gevolgd door een hogere schijf.",
                        )
                    )
                elif vorige.tot_mwh != volgende.van_mwh:
                    bevindingen.append(
                        Bevinding(
                            "fout",
                            onderwerp,
                            f"{'Gat' if vorige.tot_mwh < volgende.van_mwh else 'Overlap'} "
                            f"tussen {vorige.tot_mwh} en {volgende.van_mwh} MWh.",
                        )
                    )

            open_einden = [s for s in geordend if s.tot_mwh is None]
            if len(open_einden) != 1:
                bevindingen.append(
                    Bevinding(
                        "fout",
                        onderwerp,
                        f"{len(open_einden)} schijven zonder bovengrens; "
                        "er hoort er precies één te zijn.",
                    )
                )

            for schijf in geordend:
                if schijf.tot_mwh is not None and schijf.tot_mwh <= schijf.van_mwh:
                    bevindingen.append(
                        Bevinding(
                            "fout",
                            onderwerp,
                            f"Schijf {schijf.van_mwh}-{schijf.tot_mwh} MWh "
                            "heeft een bovengrens die niet boven de ondergrens ligt.",
                        )
                    )
                if schijf.bijzondere_accijns_eur_mwh < 0:
                    bevindingen.append(
                        Bevinding(
                            "fout",
                            onderwerp,
                            f"Negatieve bijzondere accijns "
                            f"({schijf.bijzondere_accijns_eur_mwh} EUR/MWh).",
                        )
                    )

            # "geverifieerd = true" zonder eigen bronvermelding is de vorm die
            # een fout geverifieerd laat lijken — dezelfde val als een test die
            # een getal vastlegt zonder te zeggen waar het vandaan komt.
            zonder_bron = [
                s for s in geordend
                if s.geverifieerd and not (s.bron or "").strip()
            ]
            for schijf in zonder_bron:
                bevindingen.append(
                    Bevinding(
                        "fout",
                        onderwerp,
                        f"Schijf vanaf {schijf.van_mwh} MWh staat op "
                        "geverifieerd = true maar vermeldt geen bron. "
                        "Noteer waartegen het cijfer gecontroleerd is.",
                    )
                )

            niet_geverifieerd = [s for s in geordend if not s.geverifieerd]
            if niet_geverifieerd:
                bevindingen.append(
                    Bevinding(
                        "waarschuwing",
                        onderwerp,
                        f"{len(niet_geverifieerd)} van {len(geordend)} schijven "
                        "zijn nog niet tegen een bron gecontroleerd "
                        "(geverifieerd = false).",
                    )
                )

    return bevindingen


def controleer_energiefonds(repo: HeffingenRepository) -> list[Bevinding]:
    """Elk (spanningsniveau, klantcategorie) hoort een aaneensluitende reeks
    jaren te hebben: een ontbrekend jaar laat `energiefonds_per_jaar` falen
    midden in een berekening in plaats van hier."""
    bevindingen: list[Bevinding] = []
    per_reeks: dict[tuple[str, str], list[int]] = defaultdict(list)
    for tarief in repo.energiefonds_tarieven():
        per_reeks[(tarief.spanningsniveau, tarief.klantcategorie)].append(tarief.jaar)

    for (niveau, categorie), jaren in sorted(per_reeks.items()):
        onderwerp = f"energiefonds/{niveau}/{categorie or '-'}"
        if len(jaren) != len(set(jaren)):
            bevindingen.append(
                Bevinding("fout", onderwerp, "Hetzelfde jaar staat er meer dan één keer in.")
            )
        ontbrekend = sorted(set(range(min(jaren), max(jaren) + 1)) - set(jaren))
        if ontbrekend:
            bevindingen.append(
                Bevinding(
                    "fout",
                    onderwerp,
                    f"Ontbrekende jaren: {', '.join(str(j) for j in ontbrekend)}.",
                )
            )

    return bevindingen


def controleer_dekking(
    repo: HeffingenRepository, op_datum: date
) -> list[Bevinding]:
    """Meld welke tabellen `op_datum` niet dekken.

    Het energiefonds loopt per kalenderjaar en is doorgaans pas laat in het
    voorgaande jaar bekend; dit maakt zichtbaar wanneer het volgende jaar
    aangevuld moet worden in plaats van dat een berekening erop stukloopt.
    """
    bevindingen: list[Bevinding] = []

    for energievorm, tabel in sorted(repo.accijns_tabellen().items()):
        for categorie in sorted({s.klantcategorie for s in tabel.schijven}):
            try:
                repo.accijns_schijven(energievorm, categorie, op_datum)
            except Exception as exc:  # HeffingenError
                bevindingen.append(
                    Bevinding("fout", f"{energievorm}/{categorie}", str(exc))
                )

    jaren = {t.jaar for t in repo.energiefonds_tarieven()}
    if op_datum.year not in jaren:
        bevindingen.append(
            Bevinding(
                "fout",
                "energiefonds",
                f"Geen tarieven voor {op_datum.year} "
                f"(wel voor {min(jaren)}-{max(jaren)}).",
            )
        )
    elif op_datum.year + 1 not in jaren:
        bevindingen.append(
            Bevinding(
                "waarschuwing",
                "energiefonds",
                f"Nog geen tarieven voor {op_datum.year + 1}; aanvullen zodra "
                "vlaanderen.be ze publiceert.",
            )
        )

    return bevindingen


def controleer_transport(config_dir: Path, op_datum: date) -> list[Bevinding]:
    """Toets de vervoerstarieven uit `config/nettarieven/`.

    Zelfde regels als bij de accijnzen: een geverifieerd cijfer moet zijn
    bron noemen, en de peildatum moet gedekt zijn. Een ontbrekend
    vervoerstarief maakt elke gasfactuur ongeveer 25 EUR per jaar te laag,
    dus dat is een fout en geen waarschuwing.
    """
    from energie_vlaanderen.nettarieven.transport import (
        TransportTariefError,
        TransportTariefRepository,
    )

    bevindingen: list[Bevinding] = []
    try:
        repo = TransportTariefRepository.load(config_dir)
    except TransportTariefError as exc:
        return [Bevinding("fout", "transport", str(exc))]

    for tarief in repo.tarieven():
        onderwerp = f"transport/{tarief.energievorm}/{tarief.klantcategorie}"
        if tarief.eur_per_kwh <= 0:
            bevindingen.append(
                Bevinding(
                    "fout",
                    onderwerp,
                    f"Tarief van {tarief.eur_per_kwh} EUR/kWh is niet positief.",
                )
            )
        if tarief.geverifieerd and not tarief.bron.strip():
            bevindingen.append(
                Bevinding(
                    "fout",
                    onderwerp,
                    "Staat op geverifieerd = true maar vermeldt geen bron.",
                )
            )
        elif not tarief.geverifieerd:
            bevindingen.append(
                Bevinding(
                    "waarschuwing",
                    onderwerp,
                    "Nog niet tegen een bron gecontroleerd (geverifieerd = false).",
                )
            )

    for energievorm, categorie in {
        (t.energievorm, t.klantcategorie) for t in repo.tarieven()
    }:
        try:
            repo.tarief(energievorm, categorie, op_datum)
        except TransportTariefError as exc:
            bevindingen.append(
                Bevinding("fout", f"transport/{energievorm}/{categorie}", str(exc))
            )

    return bevindingen


def controleer_alles(
    repo: HeffingenRepository,
    op_datum: date | None = None,
    nettarieven_dir: Path | None = None,
) -> list[Bevinding]:
    peildatum = op_datum or date.today()
    bevindingen = [
        *controleer_accijns(repo),
        *controleer_energiefonds(repo),
        *controleer_dekking(repo, peildatum),
    ]
    if nettarieven_dir is not None:
        bevindingen += controleer_transport(nettarieven_dir, peildatum)
    return bevindingen
