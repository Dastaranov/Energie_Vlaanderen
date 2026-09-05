""""Wat als ik een warmtepomp plaats?"

Voegt een warmtepomp-asset toe aan het elektriciteitsaansluitingspunt, telt
haar elektrisch verbruik op bij het bestaande verbruik
(`calculation.dispatch.simuleer_warmtepomp_profiel`, op het RLP0-gasprofiel
als seizoensproxy — zie die functie's docstring voor de precieze aanname), en
kan optioneel het gasverbruik van een bestaand gasaansluitingspunt op nul
zetten (`vervangt_gas=True`): een warmtepomp die de gasverwarming vervangt,
laat dat gasvolume niet zowel in de oude als de nieuwe berekening meetellen.

**Een bestaande PV-installatie blijft ongemoeid** — zie de gelijkaardige
toelichting in `scenario.elektrische_wagen`.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal
from typing import Optional
from uuid import uuid4

import pandas as pd

from energie_vlaanderen.calculation.dispatch import simuleer_warmtepomp_profiel
from energie_vlaanderen.calculation.warmtepompSpec import Warmtepomp
from energie_vlaanderen.gebruikers.models import AssetType, EnergieType, InstallatieAsset
from energie_vlaanderen.gebruikers.orchestratie import bereken_dossier
from energie_vlaanderen.gebruikers.schatting import (
    dichtstbijzijnd_beschikbaar_jaar,
    gewichten_uit_databank,
)
from energie_vlaanderen.gebruikers.toml_io import Dossier
from energie_vlaanderen.hardware.repository import WarmtepompRepository
from energie_vlaanderen.scenario.basis import Scenario, ScenarioResultaat
from energie_vlaanderen.scenario.reeksen import (
    binnen_venster,
    dag_nacht_masker,
    productiereeks,
    verbruiksreeks,
    verdeel_dag_nacht,
)
from energie_vlaanderen.settings import Settings
from energie_vlaanderen.utility.constants import D


@dataclass
class WarmtepompScenario(Scenario):
    """Voegt een warmtepomp toe en telt haar elektrisch verbruik op bij het
    bestaande verbruik van het elektriciteitsaansluitingspunt.

    `vervangt_gas=True` zet het gasverbruik van het gasaansluitingspunt (als
    dat er is) op nul voor de volledige periode — de warmtepomp neemt de
    volledige verwarming over. `False` (standaard) laat het gasverbruik
    ongemoeid: bruikbaar om enkel de meerkost van de warmtepomp te tonen
    zonder aan te nemen dat ze meteen de enige warmtebron wordt.
    """

    merk: str
    model: str
    warmtevraag_kwh_jaar: Decimal
    vervangt_gas: bool = False
    jaarverbruik_kwh: Optional[Decimal] = None
    hardware_config_dir: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.naam:
            self.naam = f"Warmtepomp: {self.merk} {self.model}"
        if not self.omschrijving:
            self.omschrijving = (
                f"Wat als er een {self.merk} {self.model}-warmtepomp bijkomt "
                f"({self.warmtevraag_kwh_jaar} kWh warmtevraag/jaar"
                + (", vervangt het gascontract" if self.vervangt_gas else "")
                + ")?"
            )

    def pas_toe(self, dossier: Dossier) -> Dossier:
        elek_punt = dossier.punt(EnergieType.ELEKTRICITEIT)
        if elek_punt is None:
            raise ValueError("Dit dossier heeft geen elektriciteitsaansluiting.")

        asset = InstallatieAsset(
            aansluitingspunt_id=elek_punt.id, type=AssetType.WARMTEPOMP,
            merk=self.merk, model=self.model, id=uuid4(),
        )
        assets = dossier.assets + (asset,)

        verbruiksopgaven = dossier.verbruiksopgaven
        if self.vervangt_gas:
            gas_punt = dossier.punt(EnergieType.GAS)
            if gas_punt is not None:
                verbruiksopgaven = tuple(
                    replace(
                        o, afname_dag_kwh=D("0"), afname_nacht_kwh=D("0"),
                        afname_exclusief_nacht_kwh=D("0"),
                    )
                    if o.aansluitingspunt_id == gas_punt.id else o
                    for o in verbruiksopgaven
                )

        return replace(dossier, assets=assets, verbruiksopgaven=verbruiksopgaven)

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
            settings.project_root / "config" / "hardware" / "warmtepompen"
            if self.hardware_config_dir is None else self.hardware_config_dir
        )
        spec = WarmtepompRepository.load(config_dir).warmtepomp(self.merk, self.model)
        wp = Warmtepomp.from_masterdata(spec)

        jaar_profiel, _ = dichtstbijzijnd_beschikbaar_jaar(conn, "rlp0n", "gas", van.year)
        gasgewichten = gewichten_uit_databank(conn, "rlp0n", jaar_profiel, "gas")
        verbruiksprofiel, wp_aanname = simuleer_warmtepomp_profiel(
            wp, warmtevraag_kwh_jaar=self.warmtevraag_kwh_jaar, profielgewichten=gasgewichten,
        )
        # Het RLP0-gasprofiel (en dus `verbruiksprofiel`) beslaat het hele
        # jaar; enkel het gevraagde venster is hier relevant.
        verbruiksprofiel = binnen_venster(verbruiksprofiel, van, tot)

        samen = pd.merge(
            verbruik.rename(columns={"kwh": "verbruik_kwh"}),
            verbruiksprofiel.rename(columns={"kwh": "wp_kwh"}),
            on="tijdstip", how="outer",
        ).fillna(0.0).sort_values("tijdstip")
        samen["afname_kwh"] = samen["verbruik_kwh"] + samen["wp_kwh"]

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
        extra_aannames = tuple(a for a in (verbruik_aanname, wp_aanname) if a is not None)
        extra_warnings = tuple(
            w for w in (afname_waarschuwing, injectie_waarschuwing) if w is not None
        )
        return replace(
            resultaat,
            aannames=resultaat.aannames + extra_aannames,
            warnings=resultaat.warnings + extra_warnings,
        )
