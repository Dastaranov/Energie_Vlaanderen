"""CLI-handlers voor de groep `gebruiker`.

Zelfde vorm als de andere handlers: signatuur `(args, settings) -> int`, nooit
zelf `Settings.load()` aanroepen, exitcode 0 bij succes en 2 bij een verwachte
fout (ontbrekend bestand, onvolledig dossier, geen tariefdata voor de gevraagde
periode). Alles wat daarbuiten valt is een bug en mag gewoon opgooien.
"""

from __future__ import annotations

import argparse
import logging
from datetime import date
from pathlib import Path

from energie_vlaanderen.cli.helpers import fail
from energie_vlaanderen.cli.output import emit, print_kv
from energie_vlaanderen.gebruikers.models import (
    EnergieType,
    Exactheidsklasse,
    GebruikersError,
)
from energie_vlaanderen.gebruikers.toml_io import Dossier, lees_dossier
from energie_vlaanderen.gebruikers.validation import controleer_dossier
from energie_vlaanderen.settings import Settings
from energie_vlaanderen.utility.constants import D
from energie_vlaanderen.utility.normalizer import money

LOG = logging.getLogger(__name__)


def _pad(args: argparse.Namespace, settings: Settings) -> Path:
    return Path(getattr(args, "toml", None) or settings.project_root / "gebruiker.toml")


def _register(settings: Settings, conn=None):
    """Het postcode->netbeheerderregister.

    **Met een databankverbinding komt het uit `gemeente`**, niet uit
    `DnbPerGemeente.csv`. Dat is geen detail: de netbeheerder bepaalt wélke
    nettarieven gelden, dus de koppeling postcode->netbeheerder zit midden in
    de berekening. Ze uit een CSV halen terwijl de tarieven uit de databank
    komen, is precies de tweede weg naar hetzelfde antwoord die uiteen kan
    lopen -- en het bleek ook zo te zijn: een spoorloop over `gebruiker
    bereken` liet zien dat dit het enige pipelinebestand was dat nog gelezen
    werd.

    Zonder verbinding (`gebruiker toon`, `gebruiker controleer`) blijft het CSV
    over. Die twee rekenen niets uit; ze lezen en toetsen een dossier, en horen
    te werken zonder databank. Ontbreekt ook het CSV, dan blijft de
    netbeheerdercode leeg en meldt `gebruiker controleer` dat als
    waarschuwing -- hard stoppen zou het inlezen van een dossier afhankelijk
    maken van een dataset die er voor het inlezen zelf niet toe doet.
    """
    if conn is not None:
        from energie_vlaanderen.data.db_repository import (
            DbDataRepositoryError,
            netbeheerders_uit_databank,
        )

        try:
            return netbeheerders_uit_databank(conn)
        except DbDataRepositoryError:
            return None

    from energie_vlaanderen.nettarieven.netbeheerder import (
        NetbeheerderError,
        NetbeheerderRegister,
        standaard_gemeente_csv,
    )

    try:
        return NetbeheerderRegister.load(standaard_gemeente_csv(settings.data_root))
    except NetbeheerderError:
        return None


def _lees(args: argparse.Namespace, settings: Settings, conn=None) -> Dossier:
    return lees_dossier(
        _pad(args, settings),
        project_root=settings.project_root,
        netbeheerders=_register(settings, conn),
    )


def run_gebruiker_toon(args: argparse.Namespace, settings: Settings) -> int:
    """Toont wat er in `gebruiker.toml` staat, als domeinobjecten."""
    try:
        dossier = _lees(args, settings)
    except GebruikersError as exc:
        return fail("%s", exc)

    json_obj = {
        "bron": str(dossier.bron),
        "segment": str(dossier.gebruiker.segment),
        "aansluitingspunten": [
            {
                "energie_type": str(p.energie_type),
                "postcode": p.postcode,
                "gemeente": p.gemeente,
                "netbeheerder_code": p.netbeheerder_code,
                # De EAN wordt bewust niet meegegeven: hij is gevoelig
                # (Manifest §5.2) en hoort niet in een uitvoer die makkelijk in
                # een log of een ticket belandt.
                "ean_bekend": p.ean_code is not None,
            }
            for p in dossier.aansluitingspunten
        ],
        "meters": [
            {
                "meterregime": str(m.meterregime),
                "registerschema": str(m.registerschema),
                "terugdraaiend": m.terugdraaiend,
                "geschatte_maandpiek_kw": str(m.geschatte_maandpiek_kw),
                "minimum_maandpiek_kw": str(m.minimum_maandpiek_kw),
            }
            for m in dossier.meters
        ],
        "installaties": [
            {
                "type": str(a.type),
                "merk": a.merk,
                "model": a.model,
                "kwp": str(a.kwp) if a.kwp is not None else None,
                "topologie": str(a.topologie) if a.topologie else None,
            }
            for a in dossier.assets
        ],
        "contracten": [
            {
                "leverancier": c.leverancier,
                "product": c.product,
                "type": str(c.contracttype),
                "van": c.geldig_van.isoformat(),
                "tot": c.geldig_tot.isoformat() if c.geldig_tot else None,
                "tariefkaart_van": (
                    c.tariefkaart_geldig_van.isoformat()
                    if c.tariefkaart_geldig_van
                    else None
                ),
            }
            for c in dossier.contracten
        ],
        "verbruiksopgaven": [
            {
                "van": o.periode_van.isoformat(),
                "tot": o.periode_tot.isoformat(),
                "afname_kwh": str(o.afname_kwh),
                "injectie_kwh": str(o.injectie_kwh),
                "bron": str(o.bron),
                "exactheidsklasse": str(o.exactheidsklasse),
            }
            for o in dossier.verbruiksopgaven
        ],
        "aannames": [
            {
                "veld": a.veld,
                "waarde": a.waarde,
                "bron": a.bron,
                "geverifieerd": a.geverifieerd,
            }
            for a in dossier.aannames
        ],
    }

    def _text() -> None:
        print_kv("Bron", dossier.bron)
        print_kv("Segment", dossier.gebruiker.segment)
        print()
        for punt in dossier.aansluitingspunten:
            meter = dossier.meter_van(punt)
            ean = "bekend" if punt.ean_code else "niet opgegeven"
            print(
                f"  {punt.energie_type}: {punt.postcode} {punt.gemeente} "
                f"(netbeheerder {punt.netbeheerder_code or '?'}, EAN {ean})"
            )
            if meter is not None:
                print(
                    f"      meter {meter.meterregime}/{meter.registerschema}"
                    f"{', terugdraaiend' if meter.terugdraaiend else ''}, "
                    f"maandpiek {meter.geschatte_maandpiek_kw} kW "
                    f"(ondergrens {meter.minimum_maandpiek_kw} kW)"
                )
            for contract in dossier.contracten_van(punt):
                tot = contract.geldig_tot.isoformat() if contract.geldig_tot else "lopend"
                print(
                    f"      contract {contract.geldig_van}..{tot}: "
                    f"{contract.leverancier} — {contract.product} ({contract.contracttype})"
                )
            for opgave in dossier.opgaven_van(punt):
                print(
                    f"      verbruik {opgave.periode_van}..{opgave.periode_tot}: "
                    f"{opgave.afname_kwh} kWh afname, {opgave.injectie_kwh} kWh injectie "
                    f"[{opgave.exactheidsklasse}]"
                )
        for asset in dossier.assets:
            print(
                f"  installatie {asset.type}: {asset.merk} {asset.model} "
                f"kWp={asset.kwp} topologie={asset.topologie}"
            )
        if dossier.aannames:
            print()
            print("  Ingevuld wat niet opgegeven was:")
            for aanname in dossier.aannames:
                merk = "geverifieerd" if aanname.geverifieerd else "NIET geverifieerd"
                print(f"    - {aanname.veld} = {aanname.waarde}  [{merk}] {aanname.bron}")

    emit(args, text_fn=_text, json_obj=json_obj)
    return 0


def run_gebruiker_controleer(args: argparse.Namespace, settings: Settings) -> int:
    """Toetst het dossier structureel; exitcode 2 zodra er een fout in zit."""
    try:
        dossier = _lees(args, settings)
    except GebruikersError as exc:
        return fail("%s", exc)

    hardware = None
    if getattr(args, "hardware", False):
        from energie_vlaanderen.hardware.repository import (
            BatterijRepository,
            OmvormerRepository,
        )

        config = settings.project_root / "config" / "hardware"
        hardware = (
            BatterijRepository.load(config / "batterijen"),
            OmvormerRepository.load(config / "omvormers"),
        )

    bevindingen = controleer_dossier(dossier, hardware=hardware)
    fouten = [b for b in bevindingen if b.ernst == "fout"]

    def _text() -> None:
        if not bevindingen:
            print("Geen bevindingen.")
            return
        for bevinding in bevindingen:
            print(f"[{bevinding.ernst:13s}] {bevinding.onderwerp}: {bevinding.bericht}")
        print()
        print(
            f"{len(fouten)} fout(en), "
            f"{sum(1 for b in bevindingen if b.ernst == 'waarschuwing')} waarschuwing(en)."
        )

    emit(
        args,
        text_fn=_text,
        json_obj={
            "bron": str(dossier.bron),
            "bevindingen": [
                {"ernst": b.ernst, "onderwerp": b.onderwerp, "bericht": b.bericht}
                for b in bevindingen
            ],
            "fouten": len(fouten),
        },
    )
    return 2 if fouten else 0


def _laad_metingen(dossier: Dossier):
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


def _laad_markt(settings: Settings, van: date, tot: date):
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


def _nettarieven_uit_databank(conn) -> dict:
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


def run_gebruiker_bereken(args: argparse.Namespace, settings: Settings) -> int:
    """Rekent het dossier door over `[--van, --tot)`, aansluitingspunt per punt.

    Elektriciteit en aardgas worden **apart** doorgerekend en apart getoond.
    Het zijn twee EAN's, twee contracten en twee tariefwerelden; ze in één
    bedrag persen laat de herkomst van elke post verdwijnen. Wie alleen gas
    heeft, rekent alleen gas door — dat is geen uitzondering maar een gewoon
    dossier.
    """
    from energie_vlaanderen.gebruikers.berekening import BerekeningError, Kostberekening
    from energie_vlaanderen.gebruikers.schatting import gasaandeel_uit_rlp0
    from energie_vlaanderen.heffingen.repository import HeffingenRepository
    from energie_vlaanderen.nettarieven.transport import (
        TransportTariefError,
        TransportTariefRepository,
    )

    import sqlalchemy as sa

    from energie_vlaanderen.data.db_repository import (
        DbDataRepository,  # noqa: F401 - via _nettarieven_uit_databank
        DbDataRepositoryError,
    )
    from energie_vlaanderen.infrastructure.db.connection import get_engine

    try:
        heffingen = HeffingenRepository.load(settings.project_root / "config" / "heffingen")
    except OSError as exc:
        return fail("%s", exc)

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

    # De databank gaat vóór het dossier open, en niet andersom. Het dossier
    # heeft het postcode->netbeheerderregister nodig om een aansluitingspunt aan
    # een netbeheerder te hangen, en dat register hoort uit `gemeente` te komen
    # — de netbeheerder bepaalt immers welke nettarieven gelden.
    db_engine = get_engine(settings.project_root)
    try:
        db_conn = db_engine.connect()
    except Exception as exc:
        return fail("Geen verbinding met de databank: %s", exc)

    try:
        dossier = _lees(args, settings, db_conn)
    except GebruikersError as exc:
        db_conn.close()
        db_engine.dispose()
        return fail("%s", exc)

    punten = [
        punt for punt in dossier.aansluitingspunten
        if punt.energie_type in (EnergieType.ELEKTRICITEIT, EnergieType.GAS)
    ]
    if not punten:
        db_conn.close()
        db_engine.dispose()
        return fail(
            "Geen elektriciteits- of aardgasaansluiting in %s. Zonder "
            "aansluitingspunt is er geen netbeheerder en dus geen nettarief.",
            dossier.bron,
        )

    versie = getattr(args, "version", None)

    # De getoonde dataversie komt uit de databank, niet van de schijf.
    # `current_data_dir()` stond hier en faalt zodra `data/current.txt`
    # ontbreekt — dat maakte een lokale dataset een voorwaarde voor een
    # berekening die verder volledig uit de databank komt.
    if versie:
        getoonde_versie = versie
    else:
        getoonde_versie = db_conn.execute(sa.text(
            "select version_id from data_version where status = 'active' "
            "order by geactiveerd_op desc nulls last limit 1"
        )).scalar()

    try:
        nettarieven = _nettarieven_uit_databank(db_conn)
    except DbDataRepositoryError as exc:
        db_conn.close()
        db_engine.dispose()
        return fail("%s", exc)
    if not nettarieven:
        db_conn.close()
        db_engine.dispose()
        return fail(
            "Geen nettarieven in de databank. Laad ze met "
            "`energievergelijker db import --version <id>`."
        )
    repo = nettarieven[max(nettarieven)]

    omvormer_kva = next(
        (a.omvormer_kva for a in dossier.assets if a.omvormer_kva is not None),
        None,
    )
    meetreeks, meetwaarschuwingen = (
        (None, ()) if getattr(args, "geen_metingen", False) else _laad_metingen(dossier)
    )
    metingen = meetreeks.intervallen if meetreeks is not None else None
    markt = _laad_markt(settings, args.van, args.tot)

    def _gasverdeler(van, tot):
        return gasaandeel_uit_rlp0(db_conn, van, tot)

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
    resultaten: list[tuple] = []
    mislukt: list[tuple[str, str]] = []
    try:
        for punt in punten:
            try:
                resultaten.append((punt, rekenaar.bereken(
                    punt,
                    dossier.meter_van(punt),
                    dossier.contracten_van(punt),
                    dossier.opgaven_van(punt),
                    args.van,
                    args.tot,
                    omvormer_kva=omvormer_kva or 0,
                    extra_aannames=dossier.aannames,
                    markt=markt,
                    # De Fluvius-export in het dossier is de elektriciteitsreeks;
                    # ze aan een gaspunt meegeven zou elektriciteitskwartieren
                    # als gasvolume laten doorgaan.
                    metingen=(
                        metingen
                        if punt.energie_type is EnergieType.ELEKTRICITEIT
                        else None
                    ),
                )))
            except (BerekeningError, GebruikersError) as exc:
                mislukt.append((str(punt.energie_type), str(exc)))
    finally:
        db_conn.close()
        db_engine.dispose()

    if not resultaten:
        for soort, melding in mislukt:
            LOG.error("%s: %s", soort, melding)
        return fail("Geen enkel aansluitingspunt kon doorgerekend worden.")

    totalen = {
        sleutel: sum((r.totalen[sleutel] for _, r in resultaten), D("0"))
        for sleutel in resultaten[0][1].totalen
    }

    def _regelblok(punt, resultaat) -> None:
        deel = resultaat.totalen
        print()
        adres = f"{punt.postcode} {punt.gemeente or ''}".strip()
        print(f"  == {str(punt.energie_type).upper()}  ({adres})")
        for regel in resultaat.regels:
            print(
                f"  {regel.periode.van} .. {regel.periode.tot} "
                f"({regel.periode.dagen:3d} d)  {regel.leverancier} — {regel.product_naam}"
            )
            print(
                f"      leverancier {regel.kost.supplier:9.2f}  net {regel.kost.grid:8.2f}  "
                f"heffingen {regel.kost.levies:8.2f}  btw {regel.kost.vat:7.2f}  "
                f"totaal {regel.kost.total:9.2f}"
            )
            print(f"      geknipt door: {', '.join(regel.periode.redenen)}")
        print(
            f"      subtotaal {deel['totaal']:.2f} EUR   "
            f"(leverancier {deel['supplier']:.2f} + net {deel['grid']:.2f} + "
            f"heffingen {deel['levies']:.2f} + btw {deel['vat']:.2f}"
            + (f" - injectie {deel['injection_credit']:.2f}" if deel["injection_credit"] else "")
            + ")"
        )

    def _text() -> None:
        eerste = resultaten[0][1]
        print_kv("Periode", f"{eerste.van} .. {eerste.tot}")
        print_kv(
            "Dataversie",
            (getoonde_versie or "(geen actieve versie)") + "  [databank]",
        )
        print_kv(
            "Meetdata",
            (
                f"{len(metingen)} intervallen, {meetreeks.resolutie}"
                + (f", {meetreeks.geschatte_intervallen} geschat" if meetreeks.geschatte_intervallen else "")
                if meetreeks is not None
                else "geen (pro rata verdeeld)"
            ),
        )
        if nettarieven:
            print_kv("Nettarieven", ", ".join(str(j) for j in sorted(nettarieven)))
        print_kv(
            "Marktprijzen",
            f"{len(markt)} punten" if markt is not None else "geen (enkel voor dynamische producten nodig)",
        )
        print_kv(
            "Exactheid",
            Exactheidsklasse.zwakste([r.exactheidsklasse for _, r in resultaten]),
        )

        for punt, resultaat in resultaten:
            _regelblok(punt, resultaat)

        print()
        print(
            f"  TOTAAL {totalen['totaal']:.2f} EUR   "
            f"(leverancier {totalen['supplier']:.2f} + net {totalen['grid']:.2f} + "
            f"heffingen {totalen['levies']:.2f} + btw {totalen['vat']:.2f}"
            + (
                f" - injectie {totalen['injection_credit']:.2f}"
                if totalen["injection_credit"]
                else ""
            )
            + ")"
        )
        if len(resultaten) > 1:
            print(
                "    = " + " + ".join(
                    f"{str(punt.energie_type)} {r.totalen['totaal']:.2f}"
                    for punt, r in resultaten
                )
            )

        alle_aannames = [a for _, r in resultaten for a in r.aannames]
        if alle_aannames:
            print()
            print("  Dit bedrag steunt op:")
            for aanname in alle_aannames:
                merk = "geverifieerd" if aanname.geverifieerd else "NIET geverifieerd"
                print(f"    - {aanname.veld} = {aanname.waarde}  [{merk}] {aanname.bron}")
        alle_warnings = tuple(meetwaarschuwingen) + tuple(
            w for _, r in resultaten for w in r.warnings
        )
        for waarschuwing in dict.fromkeys(alle_warnings):
            print(f"  ! {waarschuwing}")
        # Een punt dat niet doorgerekend kon worden verdwijnt niet stil: het
        # totaal hierboven is dan onvolledig, en dat hoort erbij te staan.
        for soort, melding in mislukt:
            print(f"  ! {soort} niet doorgerekend: {melding}")

    emit(
        args,
        text_fn=_text,
        json_obj={
            "van": args.van.isoformat(),
            "tot": args.tot.isoformat(),
            "dataversie": getoonde_versie,
            "meetintervallen": 0 if metingen is None else len(metingen),
            "marktpunten": 0 if markt is None else len(markt),
            "exactheidsklasse": str(
                Exactheidsklasse.zwakste([r.exactheidsklasse for _, r in resultaten])
            ),
            # Afronden gebeurt hier en niet eerder: Manifest §7 wil dat de
            # berekening met volle precisie doorrekent en pas op een duidelijk
            # bepaald facturatiemoment afrondt. Dat moment is de uitvoer.
            "totalen": {k: str(money(v)) for k, v in totalen.items()},
            # Per energiedrager, want dat is hoe een factuur ze ook toont.
            "per_energiedrager": [
                {
                    "energie_type": str(punt.energie_type),
                    "postcode": punt.postcode,
                    "gemeente": punt.gemeente,
                    "exactheidsklasse": str(resultaat.exactheidsklasse),
                    "totalen": {k: str(money(v)) for k, v in resultaat.totalen.items()},
                    "regels": [
                        {
                            "van": r.periode.van.isoformat(),
                            "tot": r.periode.tot.isoformat(),
                            "dagen": r.periode.dagen,
                            "leverancier": r.leverancier,
                            "product": r.product_naam,
                            "redenen": list(r.periode.redenen),
                            "supplier_eur": str(money(r.kost.supplier)),
                            "grid_eur": str(money(r.kost.grid)),
                            "levies_eur": str(money(r.kost.levies)),
                            "vat_eur": str(money(r.kost.vat)),
                            "totaal_eur": str(money(r.kost.total)),
                        }
                        for r in resultaat.regels
                    ],
                    "aannames": [
                        {
                            "veld": a.veld,
                            "waarde": a.waarde,
                            "bron": a.bron,
                            "geverifieerd": a.geverifieerd,
                        }
                        for a in resultaat.aannames
                    ],
                    "warnings": list(resultaat.warnings),
                }
                for punt, resultaat in resultaten
            ],
            "niet_doorgerekend": [
                {"energie_type": soort, "reden": melding} for soort, melding in mislukt
            ],
        },
    )
    return 0
def datum(waarde: str) -> date:
    """argparse-type voor een ISO-datum, met een leesbare foutmelding."""
    try:
        return date.fromisoformat(waarde)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"'{waarde}' is geen datum in de vorm JJJJ-MM-DD."
        ) from exc
