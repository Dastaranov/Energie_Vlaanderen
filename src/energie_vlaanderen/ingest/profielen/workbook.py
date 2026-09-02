"""Parser voor de Synergrid-verbruiksprofielen (SLP-EX, RLP0N, SPP).

Drie profieltypes, twee bestandsvormen, geverifieerd door de brondata zelf
te downloaden en te lezen (zie het plan in
`docs/research/verbruiksprofielen.md` en de commit die deze module invoert):

- **Nationaal, één waardekolom** (SLP-EX, RLP0N-gas via het GOS-bestand, en
  de SPP ex-ante-sheet): één rij per tijdstip, één waarde. Geen
  netbeheerder-koppeling nodig.
- **Breed, één kolom per netbeheerder** (RLP0N-elektriciteit, "all DSOs"):
  drie headerrijen (groep/segment, netbeheerdernaam, GLN-code) gevolgd door
  één rij per tijdstip. Wordt naar lange vorm gemold, zoals
  `CurvesWorkbookParser._parse_timeseries` dat al doet voor de
  VREG-curvesheets.

RLP0N en SLP-EX zijn `.xlsb` (pyxlsb-engine); SPP is `.xlsx` (openpyxl).
Beide engines geven tijdstippen als ruw Excel-serienummer terug wanneer de
cel niet als datum opgemaakt staat — vandaar het hergebruik van
`CurvesWorkbookParser._format_ts`, die dat probleem al oplost (zie de
docstring daar voor de 40%-stille-databug die dat aan het licht bracht).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from energie_vlaanderen.ingest.curves.workbook import CurvesWorkbookParser

LOG = logging.getLogger(__name__)

_GLN_PATTERN = re.compile(r"^\d{13}$")

# Kolommen 0..5 van de brede RLP0N-elektriciteitssheet zijn tijd-id's (CET,
# Year, Month, Day, h, Min); kolom 6 is een overbodige Excel-datumserie
# ("Date"/"RLP"/"DGO" als headertekst per rij) die dezelfde informatie als
# kolom 0 herhaalt. De eigenlijke waardekolommen — één per netbeheerder —
# beginnen pas bij kolom 7, herkenbaar aan een 13-cijferige GLN-code in de
# derde headerrij.
_WIDE_TIME_COL = 0
_WIDE_HEADER_ROWS = 3
_WIDE_FIRST_VALUE_COL = 7


class ProfielenWorkbookError(RuntimeError):
    pass


def _naar_expliciete_utc_iso(tijdstip_naief: str, *, uur_verschuiving: int = 0) -> str:
    """Maak een naïeve tijdstempel ondubbelzinnig UTC, met een optionele vaste
    verschuiving voor bronkolommen die "CET" heten maar geen zomertijd voeren.

    Twee afzonderlijke problemen, één oplossing:

    1. **RLP0N labelt zijn tijdas als "CET" zonder zomertijd** — een vaste
       verschuiving van 1 uur, het hele jaar door (net als de "Date
       Time"-uitleg bij SLP-EX voor dezelfde conventie). Geverifieerd op de
       echte 2026-data: elke dag telt exact 96 (elektriciteit) resp. 24
       (gas) kwartieren/uren, ook 29 maart en 25 oktober (de Belgische
       DST-overgangen). `uur_verschuiving=1` corrigeert dat.

    2. **Een naïeve string zonder tijdzone-aanduiding is niet vanzelf UTC**
       zodra ze een `TIMESTAMP WITH TIME ZONE`-kolom in gaat: PostgreSQL
       interpreteert ze dan via de sessietijdzone (hier Europe/Brussels,
       mét zomertijd) — ook voor tijdstempels die al uit een echte
       UTC-sheet komen (SLP-EX' `ENU_UTC`, SPP's `UTC`-kolom) en dus geen
       `uur_verschuiving` nodig hebben. Zonder de expliciete `+00:00`-
       suffix hier vallen dan alsnog twee verschillende Synergrid-
       tijdstippen rond een DST-overgang op hetzelfde UTC-instant — een
       reëel opgetreden fout tijdens de eerste echte import
       (`CardinalityViolation: ON CONFLICT DO UPDATE command cannot affect
       row a second time`), niet enkel een theoretisch risico. Vandaar dat
       deze functie voor élk nationaal/breed profiel wordt aangeroepen, ook
       met `uur_verschuiving=0`.
    """
    if not tijdstip_naief:
        return tijdstip_naief
    naief = datetime.fromisoformat(tijdstip_naief)
    utc = naief - timedelta(hours=uur_verschuiving)
    return utc.isoformat() + "+00:00"


@dataclass(frozen=True)
class ProfielRow:
    tijdstip: str
    netbeheerder_gln: str | None
    netbeheerder_naam: str | None
    waarde: float | None
    source_sheet: str


@dataclass(frozen=True)
class ParsedProfielenWorkbook:
    source_path: Path
    rows: list[ProfielRow]
    warnings: list[str]


class ProfielenWorkbookParser:
    def parse_nationaal(
        self,
        path: Path,
        *,
        engine: str,
        sheet_bevat: str,
        waarde_kolom: str | None = None,
        tijdkolom_is_cet_vast: bool = False,
    ) -> ParsedProfielenWorkbook:
        """Lees een nationaal profiel: één rij per tijdstip, één waarde.

        `sheet_bevat` is een (kleine letters) substring die de gezochte
        sheet identificeert — bv. "utc" voor SLP-EX, "gos" voor RLP0N-gas,
        "ex-ante" voor SPP. Faalt hard als er niet precies één match is:
        gokken naar de juiste sheet is hier geen optie, een verkeerde keuze
        levert stil de verkeerde profielreeks op.

        `tijdkolom_is_cet_vast=True` voor sheets waarvan de tijdkolom "CET"
        heet maar — net als RLP0N-elektriciteit — een vaste verschuiving
        zonder zomertijd draagt (RLP0N-gas via het GOS-bestand). Elke
        tijdstempel krijgt hoe dan ook een expliciete UTC-markering, ook
        zonder verschuiving — zie `_naar_expliciete_utc_iso()`.
        """
        source_path = self._resolve(path)
        sheet = self._find_sheet(source_path, engine=engine, bevat=sheet_bevat)

        df = self._read_excel(source_path, engine=engine, sheet_name=sheet, header=0)
        if df.empty:
            raise ProfielenWorkbookError(f"Sheet '{sheet}' in {source_path} is leeg.")

        time_col = df.columns[0]
        if waarde_kolom is not None:
            if waarde_kolom not in df.columns:
                raise ProfielenWorkbookError(
                    f"Verwachte waardekolom {waarde_kolom!r} niet gevonden in "
                    f"sheet '{sheet}' (kolommen: {list(df.columns)})."
                )
            value_col = waarde_kolom
        else:
            # Laatste kolom is in elk van de bekende nationale sheets de
            # waardekolom (ENU, GOS_TOTU, SPPExanteBE).
            value_col = df.columns[-1]

        rows: list[ProfielRow] = []
        warnings: list[str] = []
        for _, row in df.iterrows():
            tijdstip = CurvesWorkbookParser._format_ts(row[time_col])
            if not tijdstip:
                warnings.append(f"Lege/onleesbare tijdstempel overgeslagen in sheet '{sheet}'.")
                continue
            tijdstip = _naar_expliciete_utc_iso(
                tijdstip, uur_verschuiving=1 if tijdkolom_is_cet_vast else 0
            )
            waarde = self._safe_float(row[value_col])
            rows.append(
                ProfielRow(
                    tijdstip=tijdstip,
                    netbeheerder_gln=None,
                    netbeheerder_naam=None,
                    waarde=waarde,
                    source_sheet=sheet,
                )
            )

        return ParsedProfielenWorkbook(source_path=source_path, rows=rows, warnings=warnings)

    def parse_breed_per_netbeheerder(
        self,
        path: Path,
        *,
        engine: str,
        sheet_bevat: str,
    ) -> ParsedProfielenWorkbook:
        """Lees een breed profiel (kolom per netbeheerder) en meld het naar
        lange vorm om, naar het patroon van
        `CurvesWorkbookParser._parse_timeseries`."""
        source_path = self._resolve(path)
        sheet = self._find_sheet(source_path, engine=engine, bevat=sheet_bevat)

        raw = self._read_excel(
            source_path, engine=engine, sheet_name=sheet, header=None, nrows=None
        )
        if raw.shape[0] <= _WIDE_HEADER_ROWS:
            raise ProfielenWorkbookError(f"Sheet '{sheet}' in {source_path} bevat geen datarijen.")

        gln_header = raw.iloc[_WIDE_HEADER_ROWS - 1]
        naam_header = raw.iloc[_WIDE_HEADER_ROWS - 2]
        value_cols = [
            col
            for col in range(_WIDE_FIRST_VALUE_COL, raw.shape[1])
            if _GLN_PATTERN.match(str(gln_header[col]).strip())
        ]
        if not value_cols:
            raise ProfielenWorkbookError(
                f"Geen GLN-kolommen gevonden in sheet '{sheet}' — "
                "headerstructuur is gewijzigd t.o.v. wat deze parser verwacht."
            )

        # Twee kolommen met exact dezelfde GLN-code zijn een bekende
        # eigenaardigheid van de brondata (bv. Régie de Wavre/AIEG/AIESH
        # komen in het 2026-bestand tweemaal voor). Ze zonder controle
        # samenvoegen zou bij afwijkende waarden stil de ene kolom door de
        # andere laten overschrijven — dat hoort een fout te zijn, geen
        # aanname. De validator beslist of de waarden identiek genoeg zijn
        # om te negeren; hier wordt enkel gemeld welke kolommen het treft.
        seen_glns: dict[str, list[int]] = {}
        for col in value_cols:
            gln = str(gln_header[col]).strip()
            seen_glns.setdefault(gln, []).append(col)
        warnings = [
            f"GLN {gln} komt {len(cols)}x voor in sheet '{sheet}' (kolommen {cols})."
            for gln, cols in seen_glns.items()
            if len(cols) > 1
        ]

        data = raw.iloc[_WIDE_HEADER_ROWS:].reset_index(drop=True)

        rows: list[ProfielRow] = []
        for _, row in data.iterrows():
            tijdstip_cet_vast = CurvesWorkbookParser._format_ts(row[_WIDE_TIME_COL])
            if not tijdstip_cet_vast:
                warnings.append(f"Lege/onleesbare tijdstempel overgeslagen in sheet '{sheet}'.")
                continue
            # De kolom heet "CET" maar draagt — zoals bij SLP-EX — een vaste
            # verschuiving zonder zomertijd, geen echte Europe/Brussels-tijd.
            # Expliciet naar UTC omzetten i.p.v. de naïeve string doorgeven:
            # zie _naar_expliciete_utc_iso() voor de reële import die dit
            # anders liet mislukken rond de DST-overgangen.
            tijdstip = _naar_expliciete_utc_iso(tijdstip_cet_vast, uur_verschuiving=1)
            for col in value_cols:
                gln = str(gln_header[col]).strip()
                naam = str(naam_header[col]).strip()
                waarde = self._safe_float(row[col])
                rows.append(
                    ProfielRow(
                        tijdstip=tijdstip,
                        netbeheerder_gln=gln,
                        netbeheerder_naam=naam or None,
                        waarde=waarde,
                        source_sheet=sheet,
                    )
                )

        return ParsedProfielenWorkbook(source_path=source_path, rows=rows, warnings=warnings)

    # -- helpers --------------------------------------------------------

    @staticmethod
    def _resolve(path: Path) -> Path:
        source_path = path.expanduser().resolve()
        if not source_path.is_file():
            raise ProfielenWorkbookError(f"Profielenwerkboek bestaat niet: {source_path}")
        return source_path

    @staticmethod
    def _read_excel(path: Path, *, engine: str, **kwargs: Any) -> pd.DataFrame:
        try:
            return pd.read_excel(path, engine=engine, **kwargs)
        except ImportError as exc:
            raise ProfielenWorkbookError(
                f"Werkboek {path} kan niet gelezen worden: engine {engine!r} "
                f"ontbreekt. Installeer met 'pip install -e \".[profielen]\"'. ({exc})"
            ) from exc
        except Exception as exc:
            raise ProfielenWorkbookError(f"Werkboek {path} kan niet gelezen worden: {exc}") from exc

    @classmethod
    def _find_sheet(cls, path: Path, *, engine: str, bevat: str) -> str:
        try:
            workbook = pd.ExcelFile(path, engine=engine)
        except ImportError as exc:
            raise ProfielenWorkbookError(
                f"Werkboek {path} kan niet geopend worden: engine {engine!r} "
                f"ontbreekt. Installeer met 'pip install -e \".[profielen]\"'. ({exc})"
            ) from exc
        except Exception as exc:
            raise ProfielenWorkbookError(f"Werkboek {path} kan niet geopend worden: {exc}") from exc

        if len(workbook.sheet_names) == 1:
            return workbook.sheet_names[0]

        matches = [s for s in workbook.sheet_names if bevat.casefold() in s.casefold()]
        if len(matches) == 1:
            return matches[0]
        if not matches:
            raise ProfielenWorkbookError(
                f"Geen sheet gevonden die '{bevat}' bevat in {path}. "
                f"Beschikbare sheets: {workbook.sheet_names}"
            )
        raise ProfielenWorkbookError(
            f"Meerdere sheets bevatten '{bevat}' in {path}: {matches}. "
            "Niet eenduidig — geef een specifiekere zoekterm mee."
        )

    @staticmethod
    def _safe_float(val: Any) -> float | None:
        if val is None or pd.isna(val):
            return None
        try:
            return float(val)
        except (TypeError, ValueError):
            return None
