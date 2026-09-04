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
import os
import re
import shutil
import subprocess
import tempfile
import zlib
from datetime import datetime, timezone
from pathlib import Path

import sqlalchemy as sa

LOG = logging.getLogger(__name__)


class DumpError(RuntimeError):
    pass


# Blokgrootte voor het streamen van dump en restore. Groot genoeg om het aantal
# systeemaanroepen laag te houden, klein genoeg om het geheugengebruik vlak te
# houden ongeacht de dumpgrootte.
_BLOKGROOTTE = 1024 * 1024


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

# Eén stuk van een zware tabel gaat wél mee in de lichte dump.
#
# `verbruiksprofiel_waarde` telt 849.720 rijen en past niet in git — maar 8.760
# daarvan zijn het nationale RLP0N-gasprofiel, en zónder dat profiel kan er
# helemaal geen gasfactuur berekend worden: `gasaandeel_uit_rlp0()` weigert dan
# hard. Het gevolg was een CI die elke gasberekening oversloeg terwijl de
# gascode juist nieuw is. Het elektriciteitsprofiel is wat de tabel groot maakt
# (35.040 kwartieren x 24 netbeheerders) en dat blijft eruit.
LICHTE_SUBSETS: tuple[tuple[str, str], ...] = (
    ("verbruiksprofiel_waarde", "energie_type = 'gas' AND profiel_type = 'rlp0n'"),
)


def _psql_argumenten(dsn: str) -> tuple[list[str], dict]:
    url = sa.engine.make_url(dsn)
    argumenten = [
        "psql", "-v", "ON_ERROR_STOP=1", "-q", "--no-psqlrc",
        "-h", str(url.host),
        "-p", str(url.port or 5432),
        "-U", str(url.username),
        "-d", str(url.database),
    ]
    return argumenten, {"PGPASSWORD": url.password or ""}


def _schrijf_subset(fh, conn: sa.Connection, dsn: str, tabel: str, waar: str) -> int:
    """Voeg een deel van een tabel als COPY-blok aan de dump toe.

    pg_dump kan geen rijen filteren -- `-t` neemt een tabel in zijn geheel. Het
    tekstformaat dat het uitschrijft is wél gewoon dat van `COPY ... TO STDOUT`,
    dus psql levert hetzelfde blok voor een deelverzameling. De kolomlijst komt
    uit het schema en niet uit `select *`, zodat de COPY-kop en de rijen
    gegarandeerd dezelfde volgorde hebben.
    """
    kolommen = [
        r[0] for r in conn.execute(
            sa.text(
                "select column_name from information_schema.columns "
                "where table_schema = 'public' and table_name = :t "
                "order by ordinal_position"
            ),
            {"t": tabel},
        )
    ]
    if not kolommen:
        raise DumpError(f"Tabel {tabel!r} bestaat niet; subset kan niet gedumpt worden.")

    lijst = ", ".join(kolommen)
    argumenten, omgeving = _psql_argumenten(dsn)
    argumenten += [
        "-c",
        rf"\copy (SELECT {lijst} FROM {tabel} WHERE {waar}) TO STDOUT",  # noqa: S608
    ]

    fh.write(f"COPY public.{tabel} ({lijst}) FROM stdin;\n".encode())
    with tempfile.TemporaryFile() as fouten:
        proces = subprocess.Popen(  # noqa: S603 - vaste argumenten, geen shell
            argumenten, stdout=subprocess.PIPE, stderr=fouten,
            env={**os.environ, **omgeving},
        )
        shutil.copyfileobj(proces.stdout, fh, _BLOKGROOTTE)
        proces.stdout.close()
        if proces.wait() != 0:
            fouten.seek(0)
            raise DumpError(
                f"Subset van {tabel} mislukte: "
                + fouten.read().decode("utf-8", "replace")[:400]
            )
    fh.write(b"\\.\n\n")

    return conn.execute(
        sa.text(f"select count(*) from {tabel} where {waar}")  # noqa: S608
    ).scalar()


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

    # Streamend naar gzip, niet via `capture_output`. Een distributiedump met
    # marktcurves en profielen is honderden megabytes; die eerst volledig in
    # `proces.stdout` verzamelen en daarna in één keer wegschrijven zet twee
    # kopieën naast elkaar in het geheugen.
    #
    # Eerst naar een tijdelijk bestand naast het doel, dan hernoemen: een
    # afgebroken pg_dump laat anders een half bestand achter dat er als een
    # geldige dump uitziet. `os.replace` is atomair binnen dezelfde map.
    tijdelijk = doel.with_name(doel.name + ".tijdelijk")
    subsets: dict[str, int] = {}
    try:
        with tempfile.TemporaryFile() as fouten:
            with gzip.open(tijdelijk, "wb") as fh:
                proces = subprocess.Popen(  # noqa: S603 - vaste argumenten, geen shell
                    argumenten,
                    stdout=subprocess.PIPE,
                    stderr=fouten,
                    env={**os.environ, **omgeving},
                )
                # stderr gaat naar een bestand en niet naar een pipe: bij twee
                # pipes kan het proces blokkeren op een volle stderr terwijl wij
                # op stdout staan te wachten.
                shutil.copyfileobj(proces.stdout, fh, _BLOKGROOTTE)
                proces.stdout.close()
                returncode = proces.wait()
                if returncode == 0 and not met_zware_tabellen:
                    # De subsets gaan in dezelfde stroom en dus achter de
                    # pg_dump-blokken aan. `lees_dump` zet de TRUNCATE van álle
                    # betrokken tabellen vooraan, dus de volgorde binnen het
                    # bestand doet er niet toe zolang het één transactie blijft.
                    for tabel, waar in LICHTE_SUBSETS:
                        subsets[tabel] = _schrijf_subset(fh, conn, dsn, tabel, waar)
            if returncode != 0:
                fouten.seek(0)
                raise DumpError(
                    "pg_dump mislukte: "
                    + fouten.read().decode("utf-8", "replace")[:400]
                )
        os.replace(tijdelijk, doel)
    finally:
        tijdelijk.unlink(missing_ok=True)

    revisie = conn.execute(sa.text("select version_num from alembic_version")).scalar()
    actief = conn.execute(sa.text(
        "select version_id from data_version where geactiveerd_op is not null"
    )).scalar()
    aantallen = {
        tabel: conn.execute(sa.text(f"select count(*) from {tabel}")).scalar()  # noqa: S608
        for tabel in tabellen
    }
    # Een subset staat apart in het manifest en niet tussen `rijen`: dat getal
    # is het aantal rijen in de *databank*, en voor deze tabellen zit maar een
    # deel in de dump. Ze door elkaar zetten zou het manifest laten beweren dat
    # de dump 849.720 profielwaarden draagt terwijl het er 8.760 zijn.
    aantallen.update(subsets)

    manifest = {
        "gemaakt_op": datetime.now(tz=timezone.utc).isoformat(),
        # De Alembic-revisie waarbij deze dump hoort. Het inlezen draait
        # `alembic upgrade head`; is de dump ouder, dan moeten de migraties er
        # nog overheen — en dat toetst meteen of ze dat kunnen.
        "alembic_revisie": revisie,
        "actieve_dataversie": actief,
        "met_zware_tabellen": met_zware_tabellen,
        "subsets": {
            tabel: {"rijen": aantal, "waar": dict(LICHTE_SUBSETS)[tabel]}
            for tabel, aantal in subsets.items()
        },
        "rijen": aantallen,
        "bestand": doel.name,
        "bytes": doel.stat().st_size,
    }
    (doel.parent / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return manifest


_COPY_KOP = re.compile(rb"^COPY (?:public\.)?\"?([a-z_][a-z0-9_]*)\"?\s*\(", re.MULTILINE)


def _valideer_dump(bron: Path) -> set[str]:
    """Toets de gzip vóór er iets gewist wordt, en zeg welke tabellen erin staan.

    De CRC van een gzip staat aan het einde, dus dit vergt een volledige
    decompressie. Ze wordt blok voor blok weggegooid -- het gaat om de
    integriteit, niet om de inhoud.

    Er wordt ook gekeken of er werkelijk data in zit. Een geldige gzip van een
    leeg of louter uit `SET`-regels bestaand bestand zou de tabellen anders
    netjes leegmaken en daarna niets terugzetten.

    En passant worden de tabelnamen uit de COPY-koppen verzameld. `lees_dump`
    maakt alleen die tabellen leeg, en dat is geen verfijning maar een
    veiligheidsslot: een lichte dump draagt `marktcurve` niet en van
    `verbruiksprofiel_waarde` alleen het gasdeel. Wie zo'n dump op een volle
    databank inleest — een verkeerd gezette DB_HOST volstaat — wiste vroeger
    849.720 profielwaarden en 265.080 curverijen die er nooit meer uit
    terugkwamen. Nu blijft staan wat de dump niet kan teruggeven.
    """
    bytes_gelezen = 0
    tabellen: set[str] = set()
    staart = b""
    try:
        with gzip.open(bron, "rb") as fh:
            while blok := fh.read(_BLOKGROOTTE):
                bytes_gelezen += len(blok)
                # Op de blokgrens kan een COPY-kop doormidden vallen, dus de
                # staart van het vorige blok gaat mee. 512 bytes is ruim: de
                # langste kop in dit schema is die van `vtest_contract`.
                samen = staart + blok
                tabellen.update(
                    naam.decode("ascii") for naam in _COPY_KOP.findall(samen)
                )
                staart = samen[-512:]
    except (gzip.BadGzipFile, EOFError, OSError, zlib.error) as exc:
        raise DumpError(
            f"Dump is beschadigd en is niet ingelezen; de databank is ongemoeid "
            f"gebleven: {bron} ({exc})"
        ) from exc

    if bytes_gelezen == 0:
        raise DumpError(f"Dump is leeg: {bron}")
    if not tabellen:
        raise DumpError(
            f"Dump bevat geen COPY-opdrachten: {bron}. Inlezen zou "
            "de tabellen leegmaken zonder ze te vullen."
        )
    return tabellen


def lees_dump(dsn: str, bron: Path) -> None:
    """Laad een dump in een databank waarop de migraties al gedraaid hebben.

    Het schema wordt niet meegeleverd, dus `alembic upgrade head` hoort ervóór.
    De tabellen worden eerst leeggemaakt: een dump inlezen bovenop bestaande
    rijen zou dubbels geven waar geen unieke sleutel op staat.
    """
    if shutil.which("psql") is None:
        raise DumpError("psql niet gevonden (postgresql-client).")

    url = sa.engine.make_url(dsn)
    bron = Path(bron)
    if not bron.is_file():
        raise DumpError(f"Dump niet gevonden: {bron}")

    # Eerst valideren, dan pas iets aanraken. Het leegmaken gebeurde vroeger in
    # een eigen psql-aanroep -- en die commit meteen. Was de gzip stuk of liep
    # de restore vast, dan bleef de databank leeg achter: de dump was dan geen
    # herstel maar een wisser.
    aanwezig = _valideer_dump(bron)

    # Alleen leegmaken wat de dump ook weer vult. De volgorde blijft die van de
    # constanten, zodat de TRUNCATE er voorspelbaar uitziet.
    te_wissen = [t for t in REFERENTIE_TABELLEN + ZWARE_TABELLEN if t in aanwezig]
    if not te_wissen:
        raise DumpError(
            f"Dump {bron} bevat geen van de bekende tabellen "
            f"({', '.join(sorted(aanwezig))!r} gevonden). Inlezen afgebroken."
        )
    tabellen = ", ".join(te_wissen)
    argumenten = [
        # --single-transaction: leegmaken en vullen zijn samen één handeling.
        # Faalt er iets halverwege, dan rolt het geheel terug en staat de
        # databank er nog zoals ze stond.
        "psql", "-v", "ON_ERROR_STOP=1", "-q", "--single-transaction",
        "-h", str(url.host), "-p", str(url.port or 5432),
        "-U", str(url.username), "-d", str(url.database),
    ]
    omgeving = {**os.environ, "PGPASSWORD": url.password or ""}

    with tempfile.TemporaryFile() as fouten:
        proces = subprocess.Popen(  # noqa: S603 - vaste argumenten, geen shell
            argumenten,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=fouten,
            env=omgeving,
        )
        try:
            proces.stdin.write(
                f"TRUNCATE {tabellen} RESTART IDENTITY CASCADE;\n".encode()
            )
            # Streamend, zoals bij het maken: de gedecomprimeerde dump hoeft
            # nergens in zijn geheel in het geheugen te staan.
            with gzip.open(bron, "rb") as fh:
                shutil.copyfileobj(fh, proces.stdin, _BLOKGROOTTE)
        except (OSError, gzip.BadGzipFile, EOFError) as exc:
            proces.stdin.close()
            proces.wait()
            raise DumpError(f"Inlezen mislukte tijdens het streamen: {exc}") from exc
        finally:
            if not proces.stdin.closed:
                proces.stdin.close()
        returncode = proces.wait()
        if returncode != 0:
            fouten.seek(0)
            raise DumpError(
                "Inlezen mislukte (de databank is teruggerold): "
                + fouten.read().decode("utf-8", "replace")[:400]
            )
