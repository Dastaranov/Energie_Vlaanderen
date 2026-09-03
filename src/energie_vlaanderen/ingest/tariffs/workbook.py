from __future__ import annotations
import logging
from dataclasses import dataclass, field
from pathlib import Path
import pandas as pd
from energie_vlaanderen.utility.normalizer import clean_text, nullify

LOG = logging.getLogger(__name__)

class TariffWorkbookError(RuntimeError):
    pass

SKIP_SHEET_MARKERS = frozenset({"Overzicht", "Per DNB"})

# Header staat normaal op Excel-rij 5 (0-indexed 4), behalve bij de "* ELEK
# Injectie"-sheets: daar staat de échte kop op Excel-rij 3 (0-indexed 2). Met
# header=4 werd voor die sheets de eerste datarij ("Tarief voor het
# netgebruik") als kop verbruikt en zo stil weggegooid.
HEADER_ROW_DEFAULT = 4          # Excel rij 5 — Afname-sheets, GAS Injectie
HEADER_ROW_ELEK_INJECTIE = 2    # Excel rij 3 — enkel "* ELEK Injectie"

# Excel-rij 4 (0-indexed 3) draagt de spanningsgroep boven de kolommen:
# "Laagspanningsnet", "≤1 kV", "TRANS LS", "LS", ... De rij daaronder — die
# pandas als kolomnaam gebruikt — draagt de meetsoort: "piekmeting",
# "analoge meter", "klassieke meter", "prosumenten met terugdraaiende teller".
# Samen identificeren die twee een kolom, en dát is betrouwbaarder dan een vaste
# kolomindex.
GROEP_ROW = 3

# Meetsoort -> klanttype, binnen een laagspanningsgroep. De bewoording wisselt
# per jaargang: 2024 schrijft "klassieke meter" waar 2025/2026 "analoge meter"
# schrijven, en "terugdraaiende teller" tegenover "terugdraaiende meter".
_LS_MEETSOORT = (
    ("prosument", "ELEK_LS_ANA_PRO"),
    ("terugdraaiende", "ELEK_LS_ANA_PRO"),
    ("analoge meter", "ELEK_LS_ANA"),
    ("klassieke meter", "ELEK_LS_ANA"),
    ("piekmeting", "ELEK_LS_DIGI"),
)

@dataclass(frozen=True)
class ParsedTariffSheet:
    sheet_name: str
    rows: int
    columns: tuple[str, ...]
    source_rows: tuple[int, ...]
    # Kolomindex -> klanttype, afgeleid uit de koppen van dit blad. Leeg wanneer
    # er niets herkend werd; de normalizer valt dan terug op de vaste indices.
    kolomkaart: dict[int, str] = field(default_factory=dict)

@dataclass(frozen=True)
class ParsedTariffWorkbook:
    source_path: Path
    afname: pd.DataFrame
    injectie: pd.DataFrame
    sheets: tuple[ParsedTariffSheet, ...]
    warnings: tuple[str, ...]

    def kolomkaarten(self) -> dict[str, dict[int, str]]:
        """Per werkblad de kolomindex -> klanttype-kaart uit de koppen."""
        return {s.sheet_name: s.kolomkaart for s in self.sheets if s.kolomkaart}

class TariffWorkbookParser:
    def parse(self, path: Path, energy_type: str = "electricity") -> ParsedTariffWorkbook:
        source_path = path.expanduser().resolve()
        if not source_path.is_file():
            raise TariffWorkbookError(f"Tarievenwerkboek bestaat niet: {source_path}")

        sheet_filter = "ELEK" if energy_type == "electricity" else "GAS"
        workbook = pd.ExcelFile(source_path, engine="openpyxl")

        afname_frames: list[pd.DataFrame] = []
        injectie_frames: list[pd.DataFrame] = []
        parsed_sheets: list[ParsedTariffSheet] = []
        warnings: list[str] = []

        for sheet_name in workbook.sheet_names:
            if sheet_filter not in sheet_name or any(m in sheet_name for m in SKIP_SHEET_MARKERS):
                continue

            is_elek_injectie = "ELEK" in sheet_name and "Injectie" in sheet_name
            header_row = HEADER_ROW_ELEK_INJECTIE if is_elek_injectie else HEADER_ROW_DEFAULT

            frame = pd.read_excel(source_path, sheet_name=sheet_name, header=header_row, dtype=object, engine="openpyxl")
            frame = frame.dropna(how="all").copy()

            if frame.empty:
                warnings.append(f"Werkblad {sheet_name!r} bevat geen data.")
                continue

            kolomkaart = (
                self._ls_kolommen(source_path, sheet_name, frame.columns)
                if (not is_elek_injectie and "ELEK" in sheet_name and "Afname" in sheet_name)
                else {}
            )
            if not kolomkaart and "ELEK" in sheet_name and "Afname" in sheet_name:
                warnings.append(
                    f"Werkblad {sheet_name!r}: geen laagspanningskolommen herkend "
                    "in de koppen; de vaste kolomindeling wordt gebruikt."
                )

            frame["source_sheet"] = sheet_name
            # DataFrame index 0 correspondeert met de Excel-rij net na de header
            # (Excel-rijnummer = header_row + 2, 1-indexed: header op rij header_row+1).
            frame["source_row"] = frame.index + header_row + 2

            parsed_sheets.append(ParsedTariffSheet(
                sheet_name=sheet_name,
                rows=len(frame),
                columns=tuple(frame.columns),
                source_rows=tuple(int(v) for v in frame["source_row"].tolist()),
                kolomkaart=kolomkaart,
            ))

            if "Afname" in sheet_name:
                afname_frames.append(frame)
            elif "Injectie" in sheet_name:
                injectie_frames.append(frame)

        afname_result = pd.concat(afname_frames, ignore_index=True) if afname_frames else pd.DataFrame()
        injectie_result = pd.concat(injectie_frames, ignore_index=True) if injectie_frames else pd.DataFrame()

        return ParsedTariffWorkbook(
            source_path=source_path,
            afname=afname_result,
            injectie=injectie_result,
            sheets=tuple(parsed_sheets),
            warnings=tuple(warnings),
        )

    @staticmethod
    def _ls_kolommen(
        source_path: Path, sheet_name: str, kolommen
    ) -> dict[int, str]:
        """Welke kolommen dragen de laagspanningstarieven, volgens de koppen?

        De vaste kolomindeling die hier eerder gebruikt werd, klopt alleen voor
        de jaargangen 2025 en 2026. Het werkboek van 2024 heeft één kolom méér
        (de hoogspanning is er anders ingedeeld) en schuift de
        laagspanningskolommen van 13/14/15 naar 14/15/16 op. Met de vaste
        indeling werd de *piekmeting* van 2024 als "analoge meter" gelabeld en
        de klassieke meter als "prosument" — geen ontbrekende data maar
        verkeerd gelabelde data, en dat is erger.

        Twee koprijen samen identificeren een kolom: de spanningsgroep
        ("Laagspanningsnet", "LS") en de meetsoort ("piekmeting", "analoge
        meter"). De groep is nodig omdat 2024 twéé kolommen "piekmeting" heeft:
        één onder "TRANS LS" en één onder "LS".
        """
        try:
            groepen = pd.read_excel(
                source_path, sheet_name=sheet_name, header=None,
                skiprows=GROEP_ROW, nrows=1, dtype=object, engine="openpyxl",
            )
        except Exception as exc:  # pragma: no cover - defensief
            LOG.warning("Koprij van %s niet leesbaar: %s", sheet_name, exc)
            return {}

        rij = groepen.iloc[0] if not groepen.empty else pd.Series(dtype=object)
        # Een spanningsgroep staat één keer boven een blok kolommen; naar rechts
        # doorvullen geeft elke kolom haar groep.
        huidige = ""
        groep_per_kolom: list[str] = []
        for i in range(len(kolommen)):
            waarde = clean_text(rij.iloc[i]) if i < len(rij) else ""
            if waarde:
                huidige = waarde
            groep_per_kolom.append(huidige)

        kaart: dict[int, str] = {}
        for index, naam in enumerate(kolommen):
            groep = groep_per_kolom[index].casefold()
            # "TRANS LS" is het transformatorniveau, geen gewone
            # laagspanningsaansluiting — die kolom hoort hier niet bij.
            laagspanning = ("laagspanning" in groep or groep.strip() == "ls") and "trans" not in groep
            if not laagspanning:
                continue
            tekst = clean_text(naam).casefold()
            for stukje, klanttype in _LS_MEETSOORT:
                if stukje in tekst:
                    kaart[index] = klanttype
                    break

        # Alleen bruikbaar wanneer de drie laagspanningscategorieën er alle
        # drie in zitten; een halve kaart zou stil rijen laten vallen.
        if set(kaart.values()) != {"ELEK_LS_DIGI", "ELEK_LS_ANA", "ELEK_LS_ANA_PRO"}:
            return {}
        return kaart
