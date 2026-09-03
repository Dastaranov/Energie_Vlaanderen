from __future__ import annotations
import logging
from dataclasses import dataclass
from typing import Any
import pandas as pd
from energie_vlaanderen.utility.constants import DNB_CODES
from energie_vlaanderen.utility.normalizer import clean_text

LOG = logging.getLogger(__name__)

class TariffNormalizationError(RuntimeError):
    pass

# Geldige DNB-afkortingen zoals ze als prefix in werkbladnamen voorkomen
# (bv. "FA ELEK Afname" -> "FA"). Afgeleid van DNB_CODES (utility/constants.py)
# zodat deze whitelist en de netbeheerder-tabel nooit uit elkaar groeien.
VALID_DNB_ABBREVIATIONS = frozenset(DNB_CODES.values())

# Gas afname: (column_index, klanttype_label)
GAS_AFNAME_COLS = [
    (3, "GAS_T1"),
    (4, "GAS_T2"),
    (5, "GAS_T3"),
    (6, "GAS_T4"),
    (7, "GAS_T5"),
    (8, "GAS_T6"),
    (9, "GAS_LD"),
    (10, "GAS_MD"),
]

# Elektriciteit afname: (column_index, klanttype_label). Kolommen 7, 10, 12
# zijn altijd-lege scheidingskolommen in de bron en komen hier niet in voor.
# De laagspanningskolommen staan hier op 13/14/15; dat klopt voor de jaargangen
# 2025 en 2026. Het werkboek van 2024 heeft één kolom méér en schuift ze naar
# 14/15/16. Daarom leidt `TariffWorkbookParser` ze per blad af uit de koppen en
# krijgt die kaart voorrang; deze lijst is de terugval en levert daarnaast de
# midden- en hoogspanningskolommen.
ELEK_AFNAME_COLS = [
    (5, "ELEK_HS1"),
    (6, "ELEK_HS2"),
    (8, "ELEK_MS1"),
    (9, "ELEK_MS2"),
    (11, "ELEK_LS_DC"),
    (13, "ELEK_LS_DIGI"),
    (14, "ELEK_LS_ANA"),
    (15, "ELEK_LS_ANA_PRO"),
]

# De niet-laagspanningskolommen uit die lijst. Ze worden alleen gebruikt wanneer
# de bladindeling overeenkomt met de bekende; bij een afwijkende indeling (2024)
# zou een vaste index ze aan het verkeerde spanningsniveau hangen.
ELEK_AFNAME_NIET_LS = [(i, k) for i, k in ELEK_AFNAME_COLS if not k.startswith("ELEK_LS_")]
ELEK_LS_STANDAARDKAART = {i: k for i, k in ELEK_AFNAME_COLS if k.startswith("ELEK_LS_") and k != "ELEK_LS_DC"}

# Elektriciteit injectie: Tariefdetail-tekst -> klanttypes waarop de prijs van
# toepassing is (fan-out). Eerste match wint.
ELEK_INJECTIE_GROUPS: list[tuple[str, tuple[str, ...]]] = [
    ("Tarief voor het netgebruik", (
        "ELEK_HS1", "ELEK_HS2", "ELEK_MS1", "ELEK_MS2", "ELEK_LS_DC",
        "ELEK_LS_DIGI", "ELEK_LS_ANA", "ELEK_LS_ANA_PRO",
    )),
    ("26-36 kV, 1-26 kV, distributiecabine", (
        "ELEK_HS1", "ELEK_HS2", "ELEK_MS1", "ELEK_MS2", "ELEK_LS_DC",
    )),
    ("Laagspanningnet", (
        "ELEK_LS_DIGI", "ELEK_LS_ANA", "ELEK_LS_ANA_PRO",
    )),
]

@dataclass(frozen=True)
class RowIssue:
    source_sheet: str
    severity: str
    message: str

@dataclass(frozen=True)
class NormalizedTariffData:
    afname: pd.DataFrame
    injectie: pd.DataFrame
    issues: tuple[RowIssue, ...]

    @property
    def errors(self) -> tuple[RowIssue, ...]:
        return tuple(i for i in self.issues if i.severity == "error")

    @property
    def warnings(self) -> tuple[RowIssue, ...]:
        return tuple(i for i in self.issues if i.severity == "warning")

class TariffDataNormalizer:
    def normalize(
        self,
        afname: pd.DataFrame,
        injectie: pd.DataFrame,
        kolomkaarten: dict[str, dict[int, str]] | None = None,
    ) -> NormalizedTariffData:
        """`kolomkaarten` geeft per werkblad de laagspanningskolommen uit de koppen.

        Ontbreekt de kaart voor een blad, dan valt de normalisatie terug op de
        vaste kolomindices. Die kloppen voor 2025 en 2026 maar niet voor 2024.
        """
        issues: list[RowIssue] = []
        norm_afname = self._normalize_frame(
            afname, direction="Afname", issues=issues, kolomkaarten=kolomkaarten or {}
        )
        norm_injectie = self._normalize_frame(
            injectie, direction="Injectie", issues=issues, kolomkaarten=kolomkaarten or {}
        )
        return NormalizedTariffData(afname=norm_afname, injectie=norm_injectie, issues=tuple(issues))

    def _normalize_frame(
        self,
        frame: pd.DataFrame,
        direction: str,
        issues: list[RowIssue],
        kolomkaarten: dict[str, dict[int, str]] | None = None,
    ) -> pd.DataFrame:
        if frame.empty:
            return pd.DataFrame()

        out = []
        # Eén waarschuwing per blad, niet één per rij.
        gemeld: set[str] = set()
        current_hoofdgroep = ""
        # Naam van de vorige tariefregel, om "of"-vervolgregels aan te hangen.
        vorige_desc = ""
        vorig_sheet = ""

        for _, row in frame.iterrows():
            source_sheet = clean_text(row.get("source_sheet", ""))
            # Context hoort niet over werkbladgrenzen heen te lekken: elk blad
            # is een eigen netbeheerder met een eigen tarievenlijst.
            if source_sheet != vorig_sheet:
                current_hoofdgroep = ""
                vorige_desc = ""
                vorig_sheet = source_sheet

            dnb_code = source_sheet.split(" ")[0] if source_sheet else ""
            dnb_mapped = dnb_code if dnb_code in VALID_DNB_ABBREVIATIONS else None

            if not dnb_mapped:
                # Stil overslaan verbergt hoeveel er wegvalt. Het werkboek van
                # 2024 draagt de tien Fluvius-entiteiten van vóór de fusie
                # (GW, INT, IVK, IVRLK, PBE, SIB naast FA/FI/FL/FW); die zes
                # bestaan sinds 2025 niet meer en staan niet in DNB_CODES. Hun
                # tarieven zijn nu niet bruikbaar, want er is ook geen
                # postcode->netbeheerder-koppeling voor die periode — maar dat
                # hoort een zichtbare bevinding te zijn, geen stilte.
                if dnb_code and dnb_code not in gemeld:
                    gemeld.add(dnb_code)
                    issues.append(RowIssue(
                        source_sheet=source_sheet,
                        severity="warning",
                        message=(
                            f"Netbeheerder {dnb_code!r} staat niet in DNB_CODES en "
                            "wordt overgeslagen. Bij oudere jaargangen zijn dit de "
                            "entiteiten van vóór de Fluvius-fusie van 2025; hun "
                            "tarieven zijn zonder historische postcodekoppeling "
                            "niet toe te wijzen."
                        ),
                    ))
                continue

            source_row_raw = row.get("source_row")
            try:
                source_row: int | None = int(source_row_raw) if source_row_raw is not None and pd.notna(source_row_raw) else None
            except (ValueError, TypeError):
                source_row = None

            is_gas = "GAS" in source_sheet

            col0 = str(row.iloc[0]).strip() if pd.notna(row.iloc[0]) else ""
            desc = str(row.iloc[1]).strip() if pd.notna(row.iloc[1]) else ""

            if col0.isdigit() and len(col0) == 1:
                current_hoofdgroep = desc.split(" *")[0].strip()

            if not desc and current_hoofdgroep:
                desc = current_hoofdgroep

            desc = desc.split(" *")[0].strip()

            # Rijen waarvan de omschrijving met "- " of "*" begint zijn voetnoten
            # in de Excel-bron — geen echte tariefregels.
            if desc.startswith("- ") or desc.startswith("*"):
                continue

            # "of" is geen tariefnaam maar een vervolgregel: het werkboek geeft
            # daarmee hetzelfde tarief in een andere eenheid.
            #
            #     Maandpiek                              EUR/kW/maand
            #     of                                     EUR/kW/jaar
            #     Tarief voor overschrijding toegang..   EUR/kW/maand
            #     of                                     EUR/kW/jaar
            #
            # Letterlijk overnemen maakte van elke "of" een aparte tariefnaam,
            # waardoor verschillende tarieven dezelfde omschrijving kregen: in
            # het hoogspanningsblad botsten daardoor 40 van de 488 sleutels.
            # We nemen de naam van de regel erboven over; de eenheid
            # (Tariefnotering) houdt de twee varianten uit elkaar.
            if desc.casefold() == "of":
                if not vorige_desc:
                    continue
                desc = vorige_desc
            else:
                vorige_desc = desc

            base_data = {
                "Netbeheerder": dnb_mapped,
                "Contracttype": direction,
                "Tarieftype": current_hoofdgroep,
                "Tariefdetail": desc,
                "source_sheet": source_sheet,
                "source_row": source_row,
            }

            if direction == "Afname":
                if is_gas:
                    if len(row) > 10:
                        unit = str(row.iloc[2]).strip() if pd.notna(row.iloc[2]) else ""
                        for col_idx, klanttype in GAS_AFNAME_COLS:
                            val = self._safe_price(row.iloc[col_idx])
                            if val is not None:
                                out.append({**base_data, "Tariefnotering": unit, "Klanttype": klanttype, "Prijs_num": val})
                else:
                    kolommen = self._elek_afname_kolommen(
                        source_sheet, (kolomkaarten or {}).get(source_sheet), gemeld
                    )
                    benodigd = max(i for i, _ in kolommen) if kolommen else 15
                    if len(row) > benodigd:
                        unit = str(row.iloc[3]).strip() if pd.notna(row.iloc[3]) else ""
                        for col_idx, klanttype in kolommen:
                            val = self._safe_price(row.iloc[col_idx])
                            if val is not None:
                                out.append({**base_data, "Tariefnotering": unit, "Klanttype": klanttype, "Prijs_num": val})

            elif direction == "Injectie":
                if is_gas:
                    if len(row) > 3:
                        val = self._safe_price(row.iloc[3])
                        unit = str(row.iloc[2]).strip() if pd.notna(row.iloc[2]) else ""
                        if val is not None:
                            out.append({**base_data, "Tariefnotering": unit, "Klanttype": "GAS_INJ", "Prijs_num": val})
                else:
                    if len(row) > 4:
                        val = self._safe_price(row.iloc[3])
                        unit = str(row.iloc[4]).strip() if pd.notna(row.iloc[4]) else ""
                        if val is not None:
                            klanttypes = self._match_elek_injectie_klanttypes(desc)
                            if klanttypes:
                                for klanttype in klanttypes:
                                    out.append({**base_data, "Tariefnotering": unit, "Klanttype": klanttype, "Prijs_num": val})
                            else:
                                issues.append(RowIssue(
                                    source_sheet=source_sheet,
                                    severity="warning",
                                    message=(
                                        f"Injectietarief {desc!r} (rij {source_row}) komt niet overeen "
                                        "met een bekende klanttype-groep en werd niet geëxporteerd."
                                    ),
                                ))

        return pd.DataFrame(out) if out else pd.DataFrame()

    @staticmethod
    def _match_elek_injectie_klanttypes(desc: str) -> tuple[str, ...]:
        for needle, klanttypes in ELEK_INJECTIE_GROUPS:
            if needle in desc:
                return klanttypes
        return ()

    @staticmethod
    def _safe_price(val: Any) -> float | None:
        try:
            if pd.isna(val) or str(val).strip() == "":
                return None
            return float(val)
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _elek_afname_kolommen(
        source_sheet: str,
        kaart: dict[int, str] | None,
        gemeld: set[str],
    ) -> list[tuple[int, str]]:
        """De te lezen kolommen voor dit afnameblad.

        Is er een uit de koppen afgeleide kaart, dan bepaalt die de
        laagspanningskolommen. De midden- en hoogspanningskolommen komen uit de
        vaste lijst, maar alleen wanneer de bladindeling overeenkomt met de
        bekende — herkenbaar aan de laagspanningskolommen die dan op 13/14/15
        staan. Wijkt de indeling af (het werkboek van 2024 heeft één kolom meer
        en een heel andere hoogspanningsindeling), dan worden MS/HS
        overgeslagen: ze op een vaste index lezen zou tarieven aan het
        verkeerde spanningsniveau hangen, en dat is erger dan ze weglaten.
        Manifest §7.2 verbiedt residentiële formules op MS/HS hoe dan ook.
        """
        if not kaart:
            return list(ELEK_AFNAME_COLS)

        kolommen = sorted(kaart.items())
        if kaart == ELEK_LS_STANDAARDKAART:
            return sorted(ELEK_AFNAME_NIET_LS + kolommen)

        if source_sheet not in gemeld:
            gemeld.add(source_sheet)
            LOG.warning(
                "Werkblad %s heeft een afwijkende kolomindeling "
                "(laagspanning op %s in plaats van %s). De laagspannings"
                "tarieven worden uit de koppen gelezen; midden- en "
                "hoogspanning worden overgeslagen omdat hun indeling niet "
                "te herkennen is.",
                source_sheet, sorted(kaart), sorted(ELEK_LS_STANDAARDKAART),
            )
        return kolommen
