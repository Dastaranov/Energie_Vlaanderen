""""Wat als ik zonnepanelen bijplaats?"

Zelfde soort scenario als `BatterijScenario`: het voegt een PV-asset toe en
levert een productiereeks als injectiecorrectie op de bestaande
verbruiksreeks. Zonder batterij gaat elk productieoverschot rechtstreeks naar
injectie — `simuleer_batterij_dispatch` met een batterij die geen enkele kWh
kan vasthouden (max_capacity=0) zou hetzelfde resultaat geven, maar dat is een
omweg; hier gebeurt het rechtstreeks.

**De nieuwe panelen komen bovenop wat er al staat, niet in de plaats ervan.**
Heeft het dossier al een Fluvius-meting (die een eventuele bestaande
PV-installatie al netto verrekent, zie `scenario.reeksen`), dan telt deze
klasse de opbrengst van de nieuwe panelen bovenop die bestaande meting op.
Zonder meting maar wel met een bestaande PV-asset in het dossier komt de
bestaande opbrengst uit een eigen SPP-synthese (via `scenario.reeksen.productiereeks`),
en de nieuwe panelen erbovenop uit een tweede, aparte `productie_uit_kwp()`.
Dat onderscheid is niet cosmetisch: `productiereeks()` op het *gewijzigde*
dossier zou de zonet toegevoegde asset zelf ook als "bestaand" meetellen en de
nieuwe panelen zo dubbel tellen. Vandaar dat beide oproepen hieronder
`basis_dossier` gebruiken (vóór `pas_toe()`), nooit het gewijzigde dossier.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal
from typing import Optional
from uuid import uuid4

import pandas as pd

from energie_vlaanderen.gebruikers.models import Aanname, AssetType, EnergieType, InstallatieAsset
from energie_vlaanderen.gebruikers.orchestratie import bereken_dossier
from energie_vlaanderen.gebruikers.toml_io import Dossier
from energie_vlaanderen.scenario.basis import Scenario, ScenarioResultaat
from energie_vlaanderen.scenario.reeksen import (
    binnen_venster,
    dag_nacht_masker,
    productiereeks,
    verbruiksreeks,
    verdeel_dag_nacht,
)
from energie_vlaanderen.settings import Settings


@dataclass
class ZonnepaneelScenario(Scenario):
    """Voegt `aantal_panelen x piekvermogen` kWp zonnepanelen toe aan het
    elektriciteitsaansluitingspunt.

    `merk`/`model` zijn hier louter documentair (voor `pas_toe()`'s
    dossierweergave) — de kostimpact hangt enkel af van `kwp`, via het
    SPP-profiel. Combineer met `BatterijScenario` (via twee opeenvolgende
    `voer_uit()`-aanroepen op hetzelfde gewijzigde dossier) om zelfconsumptie
    én opslag samen te simuleren.
    """

    kwp: Decimal
    merk: str = ""
    model: str = ""
    omvormer_kva: Optional[Decimal] = None
    jaarverbruik_kwh: Optional[Decimal] = None

    def __post_init__(self) -> None:
        if not self.naam:
            self.naam = f"Zonnepanelen: {self.kwp} kWp"
        if not self.omschrijving:
            self.omschrijving = f"Wat als er {self.kwp} kWp zonnepanelen bijkomt?"

    def pas_toe(self, dossier: Dossier) -> Dossier:
        punt = dossier.punt(EnergieType.ELEKTRICITEIT)
        if punt is None:
            raise ValueError("Dit dossier heeft geen elektriciteitsaansluiting.")

        asset = InstallatieAsset(
            aansluitingspunt_id=punt.id, type=AssetType.PV,
            merk=self.merk, model=self.model, kwp=self.kwp,
            omvormer_kva=self.omvormer_kva, id=uuid4(),
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
        from energie_vlaanderen.gebruikers.schatting import (
            dichtstbijzijnd_beschikbaar_jaar,
            gewichten_uit_databank,
            productie_uit_kwp,
        )

        if basislijn is None:
            basislijn = bereken_dossier(basis_dossier, conn=conn, settings=settings, van=van, tot=tot)

        gewijzigd_dossier = self.pas_toe(basis_dossier)
        punt = basis_dossier.punt(EnergieType.ELEKTRICITEIT)

        verbruik, verbruik_aanname = verbruiksreeks(
            basis_dossier, basislijn, conn=conn, van=van, tot=tot,
            jaarverbruik_kwh=self.jaarverbruik_kwh,
        )
        # Bestaande productie (metingen, of een reeds bestaande PV-asset) op
        # `basis_dossier` — nooit op het gewijzigde dossier, dat zou de net
        # toegevoegde asset zelf als "bestaand" meetellen. De waarschuwing die
        # `productiereeks()` geeft bij een lege reeks ("geen zonnepanelen, de
        # batterij heeft niets om van te laden") slaat hier niet op: geen
        # bestaande productie is precies het normale startpunt van dit
        # scenario, geen probleem om te melden.
        bestaande_productie, _ = productiereeks(
            basis_dossier, punt, basislijn, conn=conn, jaar=van.year, van=van, tot=tot,
        )

        jaar_profiel, ander_jaar = dichtstbijzijnd_beschikbaar_jaar(conn, "spp", "", van.year)
        gewichten = gewichten_uit_databank(conn, "spp", jaar_profiel)
        nieuwe_productie = binnen_venster(productie_uit_kwp(self.kwp, gewichten), van, tot)
        spp_aanname = Aanname(
            veld="zonnepaneelscenario_productie",
            waarde=f"SPP {jaar_profiel}, {self.kwp} kWp",
            bron="Synergrid SPP-profiel, uit de databank",
            geverifieerd=not ander_jaar,
            beinvloedt_bedrag=True,
            motivering=(
                f"Opbrengst van de nieuwe {self.kwp} kWp geschat uit het "
                f"SPP-profiel van {jaar_profiel}"
                + (
                    f" (aangevraagd voor {van.year}, dat jaar staat niet in de "
                    "databank; de seizoensvorm herhaalt zich, maar dit is een "
                    "aanname)"
                    if ander_jaar else ""
                )
                + "."
            ),
        )

        productie = pd.merge(
            bestaande_productie.rename(columns={"kwh": "bestaand_kwh"}),
            nieuwe_productie.rename(columns={"kwh": "nieuw_kwh"}),
            on="tijdstip", how="outer",
        ).fillna(0.0)
        productie["kwh"] = productie["bestaand_kwh"] + productie["nieuw_kwh"]

        samen = pd.merge(
            verbruik.rename(columns={"kwh": "verbruik_kwh"}),
            productie[["tijdstip", "kwh"]].rename(columns={"kwh": "productie_kwh"}),
            on="tijdstip", how="outer",
        ).fillna(0.0).sort_values("tijdstip")
        samen["afname_kwh"] = (samen["verbruik_kwh"] - samen["productie_kwh"]).clip(lower=0.0)
        samen["injectie_kwh"] = (samen["productie_kwh"] - samen["verbruik_kwh"]).clip(lower=0.0)

        # Het dag/nacht-register overnemen van de echte meting — zie
        # `reeksen.dag_nacht_masker()`. Zonder meting (louter profielgebaseerd)
        # is er geen dag/nacht-informatie en komt alles in het dagslot, met
        # een waarschuwing.
        masker = dag_nacht_masker(basislijn.metingen)
        afname_dn, afname_waarschuwing = verdeel_dag_nacht(
            samen[["tijdstip", "afname_kwh"]].rename(columns={"afname_kwh": "kwh"}),
            masker, "afname",
        )
        injectie_dn, injectie_waarschuwing = verdeel_dag_nacht(
            samen[["tijdstip", "injectie_kwh"]].rename(columns={"injectie_kwh": "kwh"}),
            masker, "injectie",
        )
        gesimuleerde_metingen = afname_dn.merge(injectie_dn, on="tijdstip")

        scenario_resultaat = bereken_dossier(
            gewijzigd_dossier, conn=conn, settings=settings, van=van, tot=tot,
            metingen_override=gesimuleerde_metingen,
        )

        resultaat = self._verpak(basislijn, scenario_resultaat)
        extra_aannames = tuple(a for a in (verbruik_aanname, spp_aanname) if a is not None)
        extra_warnings = tuple(
            w for w in (afname_waarschuwing, injectie_waarschuwing) if w is not None
        )
        return replace(
            resultaat,
            aannames=resultaat.aannames + extra_aannames,
            warnings=resultaat.warnings + extra_warnings,
        )
