"""Een dump van de referentiedata, om een verse databank mee te vullen.

Twee doelen die er hetzelfde uitzien maar niet samengevoegd mogen worden:

- **De zaaddump** (`tests/fixturen/databank/`, in git). Klein genoeg om mee te
  committen, groot genoeg om een factuur mee te berekenen. Ze bestaat om de
  integratietests in CI te laten draaien: 52 tests die de databank nodig hebben
  en daarom nooit meedraaiden — precies de klasse tests die de lege
  prijskolommen gevonden zou hebben.
- **De distributiedump** (release-asset, niet in git). Met marktcurves en
  verbruiksprofielen erbij, voor een verse installatie die meteen alles kan.

Samenvoegen is de val: de curves zijn 70 MB en de profielen 374 MB, tegenover
~7 MB voor al de rest. Eén dump die beide doelen dient maakt de repo zwaar en
CI traag.

**Het is een selectie, geen anonimisering.** De gebruikersfamilie — `gebruiker`,
`aansluitingspunt` (EAN), `meter`, `verbruiksopgave`, `simulatie` — staat niet
in de lijst hieronder en komt er dus niet in. Dat is een sterkere garantie dan
scrubben: er valt niets te vergeten wat er niet in gaat.

**Alleen data, geen schema.** Het schema komt uit Alembic, dat de bron van
waarheid is. Daardoor toetst het inlezen meteen of de migraties op de dump
passen — een dump die ouder is dan de code valt zo op in plaats van stil een
kolom te missen.
"""
from __future__ import annotations

import gzip
import json
import logging
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import sqlalchemy as sa

LOG = logging.getLogger(__name__)


class DumpError(RuntimeError):
    pass


# De referentiefamilie: publiek van nature. De volgorde is de laadvolgorde —
# een tabel staat na de tabellen waar haar foreign keys naar wijzen.
REFERENTIE_TABELLEN: tuple[str, ...] = (
    "data_version",
    "leverancier",
    "energie_product",
    "tarief_afname",
    "tarief_injectie",
    "netbeheerder",
    "netbeheerder_tarief",
    "gemeente",
    "nettarief_transport",
    "overheidsheffing_accijns_schijf",
    "overheidsheffing_energiefonds",
    "overheidsheffing_btw",
    "vtest_contract",
    "vtest_scrape_run",
    "vtest_postcode_prijs",
)

# Groot en niet nodig om een factuur te berekenen: curves alleen voor dynamische
# contracten, profielen alleen om verbruik te schatten zonder meetdata.
ZWARE_TABELLEN: tuple[str, ...] = (
    "marktcurve",
    "verbruiksprofiel_waarde",
)


def _pg_dump_argumenten(dsn: str, tabellen: tuple[str, ...]) -> tuple[list[str], dict]:
    url = sa.engine.make_url(dsn)
    argumenten = [
        "pg_dump",
        "--data-only",
        "--no-owner",
        "--no-privileges",
        "-h", str(url.host),
        "-p", str(url.port or 5432),
        "-U", str(url.username),
        "-d", str(url.database),
    ]
    for tabel in tabellen:
        argumenten += ["-t", tabel]
    omgeving = {"PGPASSWORD": url.password or ""}
    return argumenten, omgeving


def maak_dump(
    conn: sa.Connection,
    dsn: str,
    doel: Path,
    *,
    met_zware_tabellen: bool = False,
) -> dict:
    """Schrijf een gzip-dump van de referentiedata plus een manifest.

    Het manifest draagt de Alembic-revisie, de rijaantallen en de actieve
    dataversie. Zonder die herkomst is een dump een bestand zonder betekenis:
    je weet niet bij welke code hij hoort en niet waaruit hij gemaakt is.
    """
    if shutil.which("pg_dump") is None:
        raise DumpError(
            "pg_dump niet gevonden. Installeer de PostgreSQL-cliënttools "
            "(postgresql-client) om een dump te maken."
        )

    tabellen = REFERENTIE_TABELLEN + (ZWARE_TABELLEN if met_zware_tabellen else ())
    doel = Path(doel)
    doel.parent.mkdir(parents=True, exist_ok=True)

    argumenten, omgeving = _pg_dump_argumenten(dsn, tabellen)
    import os

    proces = subprocess.run(  # noqa: S603 - vaste argumenten, geen shell
        argumenten,
        capture_output=True,
        env={**os.environ, **omgeving},
        check=False,
    )
    if proces.returncode != 0:
        raise DumpError(
            "pg_dump mislukte: " + proces.stderr.decode("utf-8", "replace")[:400]
        )

    with gzip.open(doel, "wb") as fh:
        fh.write(proces.stdout)

    revisie = conn.execute(sa.text("select version_num from alembic_version")).scalar()
    actief = conn.execute(sa.text(
        "select version_id from data_version where geactiveerd_op is not null"
    )).scalar()
    aantallen = {
        tabel: conn.execute(sa.text(f"select count(*) from {tabel}")).scalar()  # noqa: S608
        for tabel in tabellen
    }

    manifest = {
        "gemaakt_op": datetime.now(tz=timezone.utc).isoformat(),
        # De Alembic-revisie waarbij deze dump hoort. Het inlezen draait
        # `alembic upgrade head`; is de dump ouder, dan moeten de migraties er
        # nog overheen — en dat toetst meteen of ze dat kunnen.
        "alembic_revisie": revisie,
        "actieve_dataversie": actief,
        "met_zware_tabellen": met_zware_tabellen,
        "rijen": aantallen,
        "bestand": doel.name,
        "bytes": doel.stat().st_size,
    }
    (doel.parent / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return manifest


def lees_dump(dsn: str, bron: Path) -> None:
    """Laad een dump in een databank waarop de migraties al gedraaid hebben.

    Het schema wordt niet meegeleverd, dus `alembic upgrade head` hoort ervóór.
    De tabellen worden eerst leeggemaakt: een dump inlezen bovenop bestaande
    rijen zou dubbels geven waar geen unieke sleutel op staat.
    """
    if shutil.which("psql") is None:
        raise DumpError("psql niet gevonden (postgresql-client).")

    import os

    url = sa.engine.make_url(dsn)
    bron = Path(bron)
    if not bron.is_file():
        raise DumpError(f"Dump niet gevonden: {bron}")

    tabellen = ", ".join(REFERENTIE_TABELLEN + ZWARE_TABELLEN)
    argumenten = [
        "psql", "-v", "ON_ERROR_STOP=1", "-q",
        "-h", str(url.host), "-p", str(url.port or 5432),
        "-U", str(url.username), "-d", str(url.database),
    ]
    omgeving = {**os.environ, "PGPASSWORD": url.password or ""}

    leeg = subprocess.run(  # noqa: S603
        [*argumenten, "-c", f"TRUNCATE {tabellen} RESTART IDENTITY CASCADE"],
        capture_output=True, env=omgeving, check=False,
    )
    if leeg.returncode != 0:
        raise DumpError(
            "Leegmaken mislukte: " + leeg.stderr.decode("utf-8", "replace")[:400]
        )

    with gzip.open(bron, "rb") as fh:
        inhoud = fh.read()
    laden = subprocess.run(  # noqa: S603
        argumenten, input=inhoud, capture_output=True, env=omgeving, check=False,
    )
    if laden.returncode != 0:
        raise DumpError(
            "Inlezen mislukte: " + laden.stderr.decode("utf-8", "replace")[:400]
        )
