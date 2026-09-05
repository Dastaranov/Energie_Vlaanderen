""""Wat als ik batterijen bijplaats, wat doet dat met mijn verbruik?"

Anders dan `AnderContractScenario` verandert dit scenario niet enkel het
dossier maar ook het *volume*: een batterij verschuift wanneer energie van het
net komt, niet hoeveel er in totaal verbruikt wordt. Daarom overschrijft
`BatterijScenario.voer_uit()` de generieke `Scenario.voer_uit()` in plaats van
enkel `pas_toe()` in te vullen — `bereken_dossier()` neemt de gesimuleerde
meetreeks als apart argument (`metingen_override`), niet als deel van het
dossier.

De verbruiksdrijver is bij voorkeur de Fluvius-kwartiermeting van het dossier
(`Exactheidsklasse.EXACT`); zonder meting valt dit terug op het Synergrid
SLP-EX-profiel, geschaald naar het opgegeven jaarverbruik
(`Exactheidsklasse.GESCHAT`, met een `Aanname` die dat zegt). De
productiedrijver komt uit een bestaande PV-asset in het dossier (via
`gebruikers.schatting.productie_uit_kwp` op het SPP-profiel) — zonder PV heeft
de batterij niets om van te laden, en dat wordt als waarschuwing gemeld, niet
stil aanvaard.

**Prijsarbitrage (`prijsarbitrage=True`) is alleen zinvol op een dynamisch
contract.** `calculation.dispatch.simuleer_batterij_dispatch()` rekent met de
ruwe Belpex-prijs, geen retailformule — dat is veilig zolang de retailprijs
een stijgende functie van Belpex is (elk dynamisch product in deze masterdata
is dat: `a x Belpex + z` met `a > 0`), want dan verandert een prijsranking
niet door de omzetting. Op een vast of variabel contract betaalt de klant
sowieso hetzelfde tarief per kWh ongeacht het uur; batterijcycli daarop laten
sturen door Belpex kost dan enkel conversieverlies zonder enige besparing.
Deze klasse toetst dat daarom zelf: staat het contract voor de gevraagde
periode niet op `Contracttype.DYNAMISCH`, dan wordt arbitrage uitgeschakeld
met een waarschuwing in plaats van stil een zinloos resultaat te tonen.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal
from typing import Optional
from uuid import uuid4

import pandas as pd

from energie_vlaanderen.calculation.batterySpec import Battery
from energie_vlaanderen.calculation.dispatch import simuleer_batterij_dispatch
from energie_vlaanderen.gebruikers.models import (
    Aanname,
    AssetType,
    Contracttype,
    EnergieType,
    InstallatieAsset,
    Topologie,
)
from energie_vlaanderen.gebruikers.orchestratie import bereken_dossier, laad_markt
from energie_vlaanderen.gebruikers.toml_io import Dossier
from energie_vlaanderen.hardware.repository import BatterijRepository
from energie_vlaanderen.scenario.basis import Scenario, ScenarioResultaat
from energie_vlaanderen.scenario.reeksen import dag_nacht_masker, productiereeks, verbruiksreeks, verdeel_dag_nacht
from energie_vlaanderen.settings import Settings


def contract_is_overal_dynamisch(dossier: Dossier, punt, van: date, tot: date) -> bool:
    """Dekt `[van, tot)` volledig met `Contracttype.DYNAMISCH`-contracten?

    Geen contract voor een deel van het venster telt hier als "niet
    dynamisch": arbitrage zou dan voor dat stuk tegen een onbekend (mogelijk
    niet-dynamisch) tarief draaien.
    """
    contracten = sorted(dossier.contracten_van(punt), key=lambda c: c.geldig_van)
    cursor = van
    for contract in contracten:
        if contract.geldig_van > cursor:
            return False  # gat vóór dit contract
        if contract.geldig_tot is not None and contract.geldig_tot <= cursor:
            continue  # dit contract ligt al helemaal vóór het venster
        if contract.contracttype is not Contracttype.DYNAMISCH:
            return False
        cursor = contract.geldig_tot if contract.geldig_tot is not None else tot
        if cursor >= tot:
            return True
    return cursor >= tot


@dataclass
class BatterijScenario(Scenario):
    """Voegt een batterij toe aan het elektriciteitsaansluitingspunt en
    simuleert haar dispatch over het berekende venster.

    `jaarverbruik_kwh` is enkel nodig als het dossier geen Fluvius-meting
    heeft — dan schaalt het SLP-EX-profiel ernaar. Met een meting wordt dit
    genegeerd (de meting draagt haar eigen volume).

    `prijsarbitrage=True` laat de batterij ook laden/ontladen op basis van de
    Belpex-dagprijs (zie de moduledocstring) — enkel toegepast als het
    elektriciteitscontract voor de hele periode dynamisch is.
    """

    merk: str
    model: str
    topologie: Topologie = Topologie.DC_GEKOPPELD
    jaarverbruik_kwh: Optional[Decimal] = None
    prijsarbitrage: bool = False
    hardware_config_dir: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.naam:
            self.naam = f"Batterij: {self.merk} {self.model}"
        if not self.omschrijving:
            self.omschrijving = (
                f"Wat als er een {self.merk} {self.model}-batterij "
                f"({self.topologie}) bijkomt op de elektriciteitsaansluiting?"
                + (" met prijsarbitrage" if self.prijsarbitrage else "")
            )

    def pas_toe(self, dossier: Dossier) -> Dossier:
        """Voegt de batterij-asset toe aan het dossier.

        Bestaat vooral zodat `ScenarioResultaat`/`voer_uit()` een consistent
        gewijzigd dossier kunnen tonen; de eigenlijke kostimpact zit in de
        meetreeks die `voer_uit()` hieronder apart opbouwt, niet in deze
        assetwijziging op zich (`Kostberekening` leest geen volumes uit
        `dossier.assets`).
        """
        punt = dossier.punt(EnergieType.ELEKTRICITEIT)
        if punt is None:
            raise ValueError("Dit dossier heeft geen elektriciteitsaansluiting.")

        asset = InstallatieAsset(
            aansluitingspunt_id=punt.id, type=AssetType.BATTERIJ,
            merk=self.merk, model=self.model, topologie=self.topologie,
            id=uuid4(),
        )
        return replace(dossier, assets=dossier.assets + (asset,))

    def simuleer_metingen(
        self,
        basis_dossier: Dossier,
        *,
        conn,
        settings: Settings,
        van: date,
        tot: date,
        basislijn,
        marktprijzen_override: Optional[pd.DataFrame] = None,
    ) -> tuple[pd.DataFrame, tuple[Aanname, ...], tuple[str, ...]]:
        """De dispatch-aangepaste meetreeks, los van welk contract erop komt.

        Dit is precies het deel van `voer_uit()` dat **niet** van het
        elektriciteitscontract afhangt: de fysieke dispatch (zelfconsumptie,
        en bij prijsarbitrage de Belpex-drempels) reageert op verbruik,
        productie en marktprijs, nooit op de retailformule van een specifiek
        product. Apart getrokken zodat `scenario.optimaliseer` deze dure
        simulatie **één keer** kan draaien en daarna elk kandidaat-contract
        goedkoop tegen dezelfde reeks kan prijzen, in plaats van de dispatch
        per kandidaat te herhalen.

        `marktprijzen_override` omzeilt bewust de dynamisch-contracttoets
        hieronder: `scenario.optimaliseer` wil de arbitragedispatch precies
        één keer berekenen (ze hangt toch niet af van wélk dynamisch product
        het uiteindelijk wordt, enkel van de ruwe Belpex-prijs) en nadien op
        elk dynamisch kandidaat-contract toepassen — de toets zelf gebeurt
        daar per kandidaat, niet hier.
        """
        gewijzigd_dossier = self.pas_toe(basis_dossier)
        punt = basis_dossier.punt(EnergieType.ELEKTRICITEIT)

        verbruik, verbruik_aanname = verbruiksreeks(
            basis_dossier, basislijn, conn=conn, van=van, tot=tot,
            jaarverbruik_kwh=self.jaarverbruik_kwh,
        )
        productie, productie_waarschuwing = productiereeks(
            gewijzigd_dossier, punt, basislijn, conn=conn, jaar=van.year, van=van, tot=tot,
        )

        config_dir = (
            settings.project_root / "config" / "hardware" / "batterijen"
            if self.hardware_config_dir is None else self.hardware_config_dir
        )
        spec = BatterijRepository.load(config_dir).batterij(self.merk, self.model)
        batterij = Battery.from_masterdata(spec)

        marktprijzen = None
        arbitrage_aanname = None
        arbitrage_waarschuwing = None
        if marktprijzen_override is not None:
            marktprijzen = marktprijzen_override
        elif self.prijsarbitrage:
            if contract_is_overal_dynamisch(gewijzigd_dossier, punt, van, tot):
                marktprijzen = laad_markt(settings, van, tot)
                if marktprijzen is None or marktprijzen.empty:
                    arbitrage_waarschuwing = (
                        "Prijsarbitrage gevraagd, maar geen marktprijzen in de lokale "
                        "cache voor deze periode — enkel zelfconsumptie toegepast. "
                        "Vul aan met `energievergelijker market sync --start --end`."
                    )
                else:
                    arbitrage_aanname = Aanname(
                        veld="batterijscenario_prijsarbitrage",
                        waarde="dagvenster koop-/verkoopdrempel op Belpex",
                        bron="Belpex day-ahead (ENTSO-E/energy-charts), lokale cache",
                        geverifieerd=False,
                        beinvloedt_bedrag=True,
                        motivering=(
                            "Naast zelfconsumptie laadt/ontlaadt de batterij ook op "
                            "basis van de dagelijkse Belpex-prijs (zie "
                            "`calculation.dispatch._arbitragedrempels()`): een "
                            "dagvooruitzicht-heuristiek met perfecte kennis van de "
                            "prijzen van die dag, geen optimale meerdaagse "
                            "strategie en geen rekening met batterijslijtage door "
                            "de extra cycli."
                        ),
                    )
            else:
                arbitrage_waarschuwing = (
                    "Prijsarbitrage gevraagd, maar het elektriciteitscontract is "
                    "niet (overal) dynamisch voor deze periode — arbitrage tegen "
                    "Belpex heeft dan geen effect op de rekening en is "
                    "uitgeschakeld; enkel zelfconsumptie toegepast."
                )

        dispatch = simuleer_batterij_dispatch(
            batterij, verbruik, productie, topologie=self.topologie, marktprijzen=marktprijzen,
        )

        # Het dag/nacht-register van elk interval overnemen van de echte
        # meting (er zelf een schema voor verzinnen zou een aanname zijn die
        # dit project nergens anders maakt) — zie `reeksen.dag_nacht_masker()`.
        masker = dag_nacht_masker(basislijn.metingen)
        afname_dn, afname_waarschuwing = verdeel_dag_nacht(
            dispatch[["tijdstip", "afname_kwh"]].rename(columns={"afname_kwh": "kwh"}),
            masker, "afname",
        )
        injectie_dn, injectie_waarschuwing = verdeel_dag_nacht(
            dispatch[["tijdstip", "injectie_kwh"]].rename(columns={"injectie_kwh": "kwh"}),
            masker, "injectie",
        )
        gesimuleerde_metingen = afname_dn.merge(injectie_dn, on="tijdstip")

        extra_aannames = tuple(
            a for a in (verbruik_aanname, arbitrage_aanname) if a is not None
        )
        extra_warnings = tuple(
            w for w in (
                productie_waarschuwing, afname_waarschuwing, injectie_waarschuwing,
                arbitrage_waarschuwing,
            )
            if w is not None
        )
        return gesimuleerde_metingen, extra_aannames, extra_warnings

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
        gesimuleerde_metingen, extra_aannames, extra_warnings = self.simuleer_metingen(
            basis_dossier, conn=conn, settings=settings, van=van, tot=tot, basislijn=basislijn,
        )

        scenario_resultaat = bereken_dossier(
            gewijzigd_dossier, conn=conn, settings=settings, van=van, tot=tot,
            metingen_override=gesimuleerde_metingen,
        )

        resultaat = self._verpak(basislijn, scenario_resultaat)
        return replace(
            resultaat,
            aannames=resultaat.aannames + extra_aannames,
            warnings=resultaat.warnings + extra_warnings,
        )
