"""De ZIP-container wordt begrensd uitgepakt, niet blind.

De downloadlimiet begrenst wat er binnenkomt — gecomprimeerd. `testzip()`, dat
hier stond, pakte daarna elk lid volledig uit zonder bovengrens. Een bestand
van 1 MiB dat uitpakt tot 1 GiB kwam er ongehinderd doorheen: gemeten duurde
`testzip()` daar 4,86 s en ging 1 GiB door het geheugen, waar de begrensde
controle hem in 0,00 s afwijst op de compressieratio.

Dat vergt een gecompromitteerde bron — VREG en Synergrid staan op een
toegelaten lijst, over HTTPS — maar het is een grens die er hoort te staan,
en de bron is niet van ons.

De getallen in de fixtures hieronder zijn geen metingen maar constructies: ze
zijn zo gekozen dat ze precies één grens overschrijden.
"""
from __future__ import annotations

import struct
import zipfile
from pathlib import Path

import pytest

from energie_vlaanderen.ingest.zip_guard import (
    MAX_LEDEN,
    ZipBegrenzingOverschreden,
    controleer_zip_begrensd,
)

pytestmark = pytest.mark.bronnen


def _controleer(pad: Path) -> None:
    with zipfile.ZipFile(pad) as archief:
        controleer_zip_begrensd(pad, archief)


class TestGrenzen:
    def test_een_zipbom_wordt_afgewezen_op_de_ratio(self, tmp_path):
        """1 GiB nullen comprimeert tot ongeveer 1 MiB: ratio ~1000:1."""
        pad = tmp_path / "bom.xlsx"
        with zipfile.ZipFile(pad, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("[Content_Types].xml", b"\0" * (64 * 1024**2))
        with pytest.raises(ZipBegrenzingOverschreden, match="compressieratio"):
            _controleer(pad)

    def test_te_veel_leden_wordt_afgewezen(self, tmp_path):
        pad = tmp_path / "veel.xlsx"
        with zipfile.ZipFile(pad, "w") as z:
            for i in range(MAX_LEDEN + 1):
                z.writestr(f"lid{i}", b"x")
        with pytest.raises(ZipBegrenzingOverschreden, match="meer dan de toegestane"):
            _controleer(pad)

    def test_gewone_inhoud_gaat_gewoon_door(self, tmp_path):
        """De vorm van een echt werkboek: een handvol slecht comprimeerbare
        XML-leden. Zonder deze test zou een te strenge grens onopgemerkt elke
        download blokkeren."""
        pad = tmp_path / "gewoon.xlsx"
        with zipfile.ZipFile(pad, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("[Content_Types].xml", b"<Types>" + bytes(range(256)) * 40)
            z.writestr("xl/workbook.xml", b"<workbook>" + bytes(range(256)) * 400)
        _controleer(pad)

    def test_kleine_leden_ontsnappen_aan_de_ratiotoets(self, tmp_path):
        """Een paar honderd bytes XML comprimeert routineus 50:1 of meer. Op de
        ratio alleen zou dat een geldig werkboek afwijzen; daarom telt de ratio
        pas boven 1 KiB gecomprimeerd."""
        pad = tmp_path / "klein.xlsx"
        with zipfile.ZipFile(pad, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("xl/workbook.xml", b"a" * 100_000)   # ~400:1, maar klein
        _controleer(pad)


class TestGelogenMetadata:
    """De uitgepakte grootte in de centrale directory is een bewering.

    Ze kan niet gebruikt worden om de grens te omzeilen: `zipfile` levert nooit
    meer bytes dan er aangekondigd zijn, stopt daar, en vergelijkt de CRC. Een
    te lage opgave komt dus als `BadZipFile` naar buiten — wat de aanroepers al
    afhandelen — en niet als een stille overschrijding.
    """

    def test_een_verlaagde_grootte_valt_op_de_crc(self, tmp_path):
        pad = tmp_path / "leugen.xlsx"
        with zipfile.ZipFile(pad, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("xl/workbook.xml", b"\0" * (16 * 1024**2))

        ruw = bytearray(pad.read_bytes())
        # Centrale directory: PK\x01\x02, uitgepakte grootte op offset 24.
        i = ruw.rfind(b"PK\x01\x02")
        struct.pack_into("<I", ruw, i + 24, 1024)
        pad.write_bytes(bytes(ruw))

        with pytest.raises(zipfile.BadZipFile, match="CRC"):
            _controleer(pad)


class TestBeschadigdLid:
    def test_een_kapot_lid_wordt_gemeld(self, tmp_path):
        """Wat `testzip()` deed, doet de blokgewijze lezing ook: de CRC toetsen."""
        pad = tmp_path / "stuk.xlsx"
        with zipfile.ZipFile(pad, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("xl/workbook.xml", bytes(range(256)) * 500)

        ruw = bytearray(pad.read_bytes())
        ruw[200] ^= 0xFF          # midden in de gecomprimeerde stroom
        pad.write_bytes(bytes(ruw))

        with pytest.raises(zipfile.BadZipFile):
            _controleer(pad)
