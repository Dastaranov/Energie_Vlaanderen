"""Begrensde integriteitscontrole op een gedownload ZIP-werkboek.

De downloadlimiet begrenst het bestand zoals het binnenkomt — *gecomprimeerd*.
`ZipFile.testzip()` pakt daarna elk lid volledig uit zonder enige bovengrens.
Een klein maar sterk comprimeerbaar bestand kan zo geheugen, CPU of schijf
opeten: 50 MiB aan nullen wordt na decompressie tientallen gigabytes.

Dat vergt een gecompromitteerde of vervangen bron — de hosts staan op een
toegelaten lijst en het verkeer loopt over HTTPS — maar de controle is goedkoop
en de bron is niet van ons.

Twee lagen, met een duidelijke taakverdeling:

1. **De metadata is de begrenzing.** Aantal leden, totale en grootste
   uitgepakte grootte, compressieratio — allemaal uit de centrale directory,
   zonder één byte te decomprimeren. Hier wordt een bom afgewezen.
2. **Daarna pas de integriteit.** Elk lid wordt in blokken uitgelezen zodat
   `zipfile` de CRC toetst; dat is wat `testzip()` deed, alleen zonder ooit een
   heel lid in het geheugen te zetten.

Dat de metadata kan liegen is geen gat in die volgorde. `zipfile` levert nooit
meer bytes dan de centrale directory aankondigt — het stopt daar en vergelijkt
de CRC. Een opgave die te laag is, komt dus als `BadZipFile` naar buiten en
niet als een stille overschrijding; een opgave die te hoog is, wordt in laag 1
al geweigerd. Een eigen byteteller in laag 2 zou daardoor nooit afgaan, en een
controle die niet kan vuren is geen controle.
"""
from __future__ import annotations

import zipfile
from pathlib import Path

# Ruim boven het grootste bestand dat we in het echt zien (het Synergrid
# SPP-werkboek is ~50 MiB gecomprimeerd en pakt uit tot enkele honderden MiB),
# en ver onder wat een machine in de problemen brengt.
MAX_LEDEN = 5_000
MAX_UITGEPAKT_TOTAAL = 2 * 1024**3        # 2 GiB over alle leden samen
MAX_UITGEPAKT_PER_LID = 1024**3           # 1 GiB voor één lid
MAX_RATIO = 200                           # uitgepakt / gecomprimeerd

_BLOK = 1024 * 1024


class ZipBegrenzingOverschreden(Exception):
    """De container is technisch geldig maar buiten de gestelde grenzen."""


def controleer_zip_begrensd(pad: Path, archief: zipfile.ZipFile) -> None:
    """Toets de container op grootte en integriteit, met bovengrenzen.

    Werpt `ZipBegrenzingOverschreden` als een grens geraakt wordt en
    `zipfile.BadZipFile` als een lid beschadigd is — dezelfde uitzondering die
    `testzip()` en `ZipFile` zelf gebruiken, zodat de bestaande afhandeling
    blijft werken.
    """
    leden = archief.infolist()
    if len(leden) > MAX_LEDEN:
        raise ZipBegrenzingOverschreden(
            f"bevat {len(leden)} leden, meer dan de toegestane {MAX_LEDEN}"
        )

    # --- laag 1: wat de metadata beweert ---------------------------------
    aangekondigd = sum(lid.file_size for lid in leden)
    if aangekondigd > MAX_UITGEPAKT_TOTAAL:
        raise ZipBegrenzingOverschreden(
            f"kondigt {aangekondigd / 1024**3:.1f} GiB uitgepakt aan, meer dan "
            f"de toegestane {MAX_UITGEPAKT_TOTAAL / 1024**3:.0f} GiB"
        )
    for lid in leden:
        if lid.file_size > MAX_UITGEPAKT_PER_LID:
            raise ZipBegrenzingOverschreden(
                f"lid {lid.filename!r} kondigt {lid.file_size / 1024**3:.1f} GiB aan"
            )
        # Een ratio is pas zinvol bij een lid van enige omvang: een paar honderd
        # bytes XML comprimeert routineus tot een handvol bytes.
        if lid.compress_size > 1024 and lid.file_size / lid.compress_size > MAX_RATIO:
            raise ZipBegrenzingOverschreden(
                f"lid {lid.filename!r} heeft een compressieratio van "
                f"{lid.file_size / lid.compress_size:.0f}:1"
            )

    # --- laag 2: de integriteit, blok voor blok --------------------------
    # Vervangt `testzip()`. Tot het einde lezen laat `zipfile` de CRC toetsen;
    # in blokken lezen houdt het geheugengebruik vlak, ook bij een lid van
    # honderden megabytes. De omvang is hierboven al begrensd.
    for lid in leden:
        with archief.open(lid, "r") as fh:
            while fh.read(_BLOK):
                pass
