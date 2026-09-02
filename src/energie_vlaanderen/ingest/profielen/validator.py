"""Validatie van verbruiksprofielen: intervaltelling en de som-tot-1-eis.

`docs/manifest.md` §4.4 stelt het expliciet: "Profielgewichten moeten per
toepasselijke periode sommeren tot één." Dat is hier een harde fout, geen
waarschuwing — precies het soort eis waarbij een stil verkeerd getal
(bijvoorbeeld door een ontbrekend interval) onopgemerkt zou blijven zonder
deze controle. SPP is uitgezonderd: dat is productie per kWp geïnstalleerd
vermogen, geen verdeling van het jaarverbruik, en sommeert normaal tot de
specifieke opbrengst (orde grootte 1000 kWh/kWp/jaar), niet tot 1.
"""

from __future__ import annotations

import calendar
from collections import defaultdict
from dataclasses import dataclass

from energie_vlaanderen.ingest.profielen.workbook import ProfielRow

# Toegestane afwijking op de som-tot-1-controle. De brondata zelf is tot op
# floating-point-precisie exact (geverifieerd voor SLP-EX 2026: som =
# 0,9999999999999958, afwijking ~4e-15) — 1e-6 laat ruim marge voor
# afrondingsverschillen in de bron zonder de controle nutteloos te maken.
SOM_TOLERANTIE = 1e-6


@dataclass(frozen=True)
class ValidationIssue:
    severity: str  # "error" | "warning"
    code: str
    message: str


@dataclass(frozen=True)
class ProfielenValidationReport:
    errors: tuple[ValidationIssue, ...]
    warnings: tuple[ValidationIssue, ...]

    @property
    def valid(self) -> bool:
        return not self.errors


class ProfielenValidator:
    def validate(
        self,
        rows: list[ProfielRow],
        *,
        profiel_type: str,
        energie_type: str | None,
        jaar: int,
    ) -> ProfielenValidationReport:
        errors: list[ValidationIssue] = []
        warnings: list[ValidationIssue] = []

        if not rows:
            errors.append(ValidationIssue("error", "empty", "Geen rijen om te valideren."))
            return ProfielenValidationReport(errors=tuple(errors), warnings=tuple(warnings))

        # Dedupliceren op (tijdstip, netbeheerder): een gekende eigenaardigheid
        # van de brondata is dat enkele kleine netbeheerders dubbel als kolom
        # voorkomen (bv. Régie de Wavre/AIEG/AIESH in het 2026-bestand). Zolang
        # beide kolommen hetzelfde zeggen is dat onschadelijk; zeggen ze iets
        # anders, dan is dat een echte tegenstrijdigheid die niet stil
        # opgelost mag worden door de ene kolom de andere te laten
        # overschrijven.
        dedup: dict[tuple[str, str | None], float | None] = {}
        conflicts: set[tuple[str, str | None]] = set()
        for row in rows:
            key = (row.tijdstip, row.netbeheerder_gln)
            if key in dedup:
                eerdere = dedup[key]
                gelijk = (
                    eerdere is None
                    and row.waarde is None
                    or eerdere is not None
                    and row.waarde is not None
                    and round(eerdere, 9) == round(row.waarde, 9)
                )
                if not gelijk:
                    conflicts.add(key)
            else:
                dedup[key] = row.waarde

        for tijdstip, gln in sorted(conflicts, key=lambda k: (k[1] or "", k[0])):
            errors.append(
                ValidationIssue(
                    "error",
                    "duplicate_gln_conflict",
                    f"Netbeheerder {gln}: tegenstrijdige waarden op {tijdstip} "
                    "door dubbele GLN-kolommen in de brondata.",
                )
            )

        if conflicts:
            # Eerst deze tegenstrijdigheid oplossen — verder valideren op
            # data met een onbekende dubbele telling levert een misleidend
            # rapport op (bv. een somcontrole die toevallig toch klopt).
            return ProfielenValidationReport(errors=tuple(errors), warnings=tuple(warnings))

        by_group: dict[str | None, dict[str, float | None]] = defaultdict(dict)
        for (tijdstip, gln), waarde in dedup.items():
            by_group[gln][tijdstip] = waarde

        verwacht = self._verwacht_aantal_intervallen(profiel_type, energie_type, jaar)
        som_check = profiel_type in ("slp_ex", "rlp0n")

        for gln, tijdstippen in sorted(by_group.items(), key=lambda kv: kv[0] or ""):
            label = gln or "(nationaal)"
            aantal = len(tijdstippen)

            if verwacht is not None and aantal != verwacht:
                errors.append(
                    ValidationIssue(
                        "error",
                        "interval_count",
                        f"{label}: {aantal} intervallen voor {jaar}, {verwacht} verwacht.",
                    )
                )

            if som_check:
                waarden = [w for w in tijdstippen.values() if w is not None]
                ontbrekend = aantal - len(waarden)
                if ontbrekend:
                    warnings.append(
                        ValidationIssue(
                            "warning",
                            "missing_values",
                            f"{label}: {ontbrekend} lege waarden overgeslagen bij de somcontrole.",
                        )
                    )
                totaal = sum(waarden)
                afwijking = abs(totaal - 1.0)
                if afwijking > SOM_TOLERANTIE:
                    errors.append(
                        ValidationIssue(
                            "error",
                            "sum_not_one",
                            f"{label}: som van de profielgewichten is {totaal:.10f}, "
                            f"niet 1 (afwijking {afwijking:.2e}). Vereist door "
                            "docs/manifest.md §4.4.",
                        )
                    )

        return ProfielenValidationReport(errors=tuple(errors), warnings=tuple(warnings))

    @staticmethod
    def _verwacht_aantal_intervallen(
        profiel_type: str,
        energie_type: str | None,
        jaar: int,
    ) -> int | None:
        schrikkel = calendar.isleap(jaar)

        if profiel_type == "rlp0n" and energie_type == "gas":
            # RLP0N-gas (het GOS-bestand) is uurresolutie.
            return 8784 if schrikkel else 8760

        # SLP-EX, RLP0N-elektriciteit en SPP ex-ante zijn kwartierresolutie.
        return 35136 if schrikkel else 35040
