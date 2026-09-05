""""Wat als ik een elektrische wagen aanschaf?"

Zelfde vorm als `BatterijScenario`/`ZonnepaneelScenario`: het voegt een
EV-asset toe aan het dossier én een extra afnamereeks (het laadprofiel, via
`calculation.dispatch.simuleer_ev_laadprofiel`) bovenop de bestaande
verbruiksreeks. Er is geen rijgedragprofiel in dit project — zie de
moduledocstring van `dispatch.py` voor de precieze aanname (jaarkilometrage,
vlak verdeeld over een nachtelijk laadvenster) die hier steeds als `Aanname`
meereist.

**Een bestaande PV-installatie blijft ongemoeid.** Dit scenario voegt enkel
verbruik toe; het raakt geen productie. De bestaande injectie (uit een echte
meting, of een SPP-synthese als het dossier al een PV-asset heeft) wordt dus
onveranderd overgenomen via `scenario.reeksen.productiereeks()` — ze op nul
zetten zou een bestaande zonne-installatie stil haar injectiekrediet
ontnemen.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal
from typing import Optional
from uuid import uuid4

import pandas as pd

from energie_vlaanderen.calculation.dispatch import simuleer_ev_laadprofiel
from energie_vlaanderen.calculation.elektrische_wagenSpec import ElektrischeWagen
from energie_vlaanderen.gebruikers.models import AssetType, EnergieType, InstallatieAsset
from energie_vlaanderen.gebruikers.orchestratie import bereken_dossier
from energie_vlaanderen.gebruikers.toml_io import Dossier
from energie_vlaanderen.hardware.repository import ElektrischeWagenRepository
from energie_vlaanderen.scenario.basis import Scenario, ScenarioResultaat
from energie_vlaanderen.scenario.reeksen import (
    dag_nacht_masker,
    productiereeks,
    verbruiksreeks,
    verdeel_dag_nacht,
)
from energie_vlaanderen.settings import Settings


@dataclass
class ElektrischeWagenScenario(Scenario):
    """Voegt een EV toe aan het elektriciteitsaansluitingspunt en telt haar
    laadprofiel op bij het bestaande verbruik."""

    merk: str
    model: str
    km_per_jaar: Decimal
    laadvenster: tuple[int, int] = (22, 6)
    jaarverbruik_kwh: Optional[Decimal] = None
    hardware_config_dir: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.naam:
            self.naam = f"Elektrische wagen: {self.merk} {self.model}"
        if not self.omschrijving:
            self.omschrijving = (
                f"Wat als er een {self.merk} {self.model} bijkomt, "
                f"{self.km_per_jaar} km/jaar, laadvenster {self.laadvenster}?"
            )

    def pas_toe(self, dossier: Dossier) -> Dossier:
        punt = dossier.punt(EnergieType.ELEKTRICITEIT)
        if punt is None:
            raise ValueError("Dit dossier heeft geen elektriciteitsaansluiting.")

        asset = InstallatieAsset(
            aansluitingspunt_id=punt.id, type=AssetType.EV,
            merk=self.merk, model=self.model, id=uuid4(),
        )
        return replace(dossier, assets=dossier.assets + (asset,))

    def voer_uit(
        self,
        basis_dossier: Dossier,
        *,
        conn,
        settings: Settings,
        van: date,
        tot: date,
        basislijn=None,
    ) -> ScenarioResultaat:
        if basislijn is None:
            basislijn = bereken_dossier(basis_dossier, conn=conn, settings=settings, van=van, tot=tot)

        gewijzigd_dossier = self.pas_toe(basis_dossier)
        punt = basis_dossier.punt(EnergieType.ELEKTRICITEIT)

        verbruik, verbruik_aanname = verbruiksreeks(
            basis_dossier, basislijn, conn=conn, van=van, tot=tot,
            jaarverbruik_kwh=self.jaarverbruik_kwh,
        )
        # Bestaande injectie blijft ongemoeid — zie de moduledocstring.
        injectie, _ = productiereeks(
            basis_dossier, punt, basislijn, conn=conn, jaar=van.year, van=van, tot=tot,
        )

        config_dir = (
            settings.project_root / "config" / "hardware" / "elektrische_wagens"
            if self.hardware_config_dir is None else self.hardware_config_dir
        )
        spec = ElektrischeWagenRepository.load(config_dir).elektrische_wagen(self.merk, self.model)
        ev = ElektrischeWagen.from_masterdata(spec)

        laadprofiel, laad_aanname = simuleer_ev_laadprofiel(
            ev, km_per_jaar=self.km_per_jaar, van=van, tot=tot, laadvenster=self.laadvenster,
        )

        samen = pd.merge(
            verbruik.rename(columns={"kwh": "verbruik_kwh"}),
            laadprofiel.rename(columns={"kwh": "laad_kwh"}),
            on="tijdstip", how="outer",
        ).fillna(0.0).sort_values("tijdstip")
        samen["afname_kwh"] = samen["verbruik_kwh"] + samen["laad_kwh"]

        masker = dag_nacht_masker(basislijn.metingen)
        afname_dn, afname_waarschuwing = verdeel_dag_nacht(
            samen[["tijdstip", "afname_kwh"]].rename(columns={"afname_kwh": "kwh"}),
            masker, "afname",
        )
        injectie_dn, injectie_waarschuwing = verdeel_dag_nacht(injectie, masker, "injectie")
        gesimuleerde_metingen = afname_dn.merge(injectie_dn, on="tijdstip", how="outer").fillna(0.0)

        scenario_resultaat = bereken_dossier(
            gewijzigd_dossier, conn=conn, settings=settings, van=van, tot=tot,
            metingen_override=gesimuleerde_metingen,
        )

        resultaat = self._verpak(basislijn, scenario_resultaat)
        extra_aannames = tuple(a for a in (verbruik_aanname, laad_aanname) if a is not None)
        extra_warnings = tuple(
            w for w in (afname_waarschuwing, injectie_waarschuwing) if w is not None
        )
        return replace(
            resultaat,
            aannames=resultaat.aannames + extra_aannames,
            warnings=resultaat.warnings + extra_warnings,
        )
