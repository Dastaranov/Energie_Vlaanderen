"""Structurele controle op een gebruikersdossier.

Zelfde vorm als `heffingen/validation.py` en `hardware/validation.py`: een lijst
`Bevinding` met ernst "fout", "waarschuwing" of "info", zonder netwerk en zonder
databank. Wat hier getoetst wordt is of het dossier *intern klopt* — of er
gerekend kán worden en waarop dat resultaat dan steunt. Of de bedragen kloppen
is een andere vraag, en die beantwoordt de kalibratie tegen vtest.be.

De belangrijkste regel: elke niet-geverifieerde aanname is een waarschuwing. Ze
tegenhouden zou het rekenen onmogelijk maken (veel gebruikers weten hun EAN of
paneelvermogen niet), maar ze verzwijgen zou een geschat bedrag als een gemeten
bedrag laten doorgaan.
"""

from __future__ import annotations


from energie_vlaanderen.gebruikers.models import (
    AssetType,
    EnergieType,
    Exactheidsklasse,
    Meterregime,
)
from energie_vlaanderen.gebruikers.toml_io import Dossier
from energie_vlaanderen.heffingen.validation import Bevinding


def controleer_dossier(dossier: Dossier, *, hardware=None) -> list[Bevinding]:
    """Toets één dossier. `hardware` is een optioneel `(batterij, omvormer)`-paar."""
    bevindingen: list[Bevinding] = []
    bevindingen.extend(_controleer_aannames(dossier))
    bevindingen.extend(_controleer_aansluitingen(dossier))
    bevindingen.extend(_controleer_contracten(dossier))
    bevindingen.extend(_controleer_verbruik(dossier))
    if hardware is not None:
        bevindingen.extend(_controleer_hardware(dossier, *hardware))
    return bevindingen


def _controleer_aannames(dossier: Dossier) -> list[Bevinding]:
    uit: list[Bevinding] = []
    for aanname in dossier.aannames:
        ernst = "info" if aanname.geverifieerd else "waarschuwing"
        uit.append(
            Bevinding(
                ernst=ernst,
                onderwerp=f"aanname/{aanname.veld}",
                bericht=(
                    f"{aanname.veld} = {aanname.waarde} "
                    f"({'geverifieerd' if aanname.geverifieerd else 'niet geverifieerd'}, "
                    f"bron: {aanname.bron})."
                ),
            )
        )
    return uit


def _controleer_aansluitingen(dossier: Dossier) -> list[Bevinding]:
    uit: list[Bevinding] = []
    if not dossier.aansluitingspunten:
        uit.append(
            Bevinding("fout", "aansluiting", "Het dossier heeft geen enkel aansluitingspunt.")
        )
        return uit

    per_type: dict[EnergieType, int] = {}
    for punt in dossier.aansluitingspunten:
        per_type[punt.energie_type] = per_type.get(punt.energie_type, 0) + 1
        if not punt.netbeheerder_code:
            uit.append(
                Bevinding(
                    "waarschuwing",
                    f"aansluiting/{punt.energie_type}",
                    "Geen netbeheerdercode opgelost. Zonder netbeheerder is er "
                    "geen nettarief; de berekening zoekt hem later alsnog op.",
                )
            )
        if punt.aansluitingsvermogen_kva is None:
            uit.append(
                Bevinding(
                    "info",
                    f"aansluiting/{punt.energie_type}",
                    "Aansluitingsvermogen (kVA) niet opgegeven. Niet nodig voor "
                    "de factuurberekening, wel om te toetsen of een batterij of "
                    "laadpaal binnen de aansluiting past.",
                )
            )
    for energie_type, aantal in per_type.items():
        if aantal > 1:
            uit.append(
                Bevinding(
                    "fout",
                    f"aansluiting/{energie_type}",
                    f"{aantal} aansluitingspunten voor {energie_type}. Eén EAN "
                    "per energiedrager per adres; meerdere punten horen bij "
                    "meerdere adressen.",
                )
            )

    elek = dossier.punt(EnergieType.ELEKTRICITEIT)
    if elek is not None and dossier.meter_van(elek) is None:
        uit.append(
            Bevinding(
                "fout",
                "meter",
                "Het elektriciteitspunt heeft geen meter. Zonder meetregime is "
                "de nettariefcategorie (digitaal/analoog/prosument) niet te kiezen.",
            )
        )

    heeft_pv = any(a.type is AssetType.PV for a in dossier.assets)
    meters = [dossier.meter_van(p) for p in dossier.aansluitingspunten]
    for meter in meters:
        if meter is None:
            continue
        if heeft_pv and meter.meterregime is Meterregime.KLASSIEK and not meter.terugdraaiend:
            uit.append(
                Bevinding(
                    "waarschuwing",
                    "meter/prosument",
                    "Klassieke meter met zonnepanelen maar niet als "
                    "terugdraaiend gemarkeerd. Het prosumententarief wordt dan "
                    "niet aangerekend; controleer of dat klopt.",
                )
            )
    return uit


def _controleer_contracten(dossier: Dossier) -> list[Bevinding]:
    uit: list[Bevinding] = []
    for punt in dossier.aansluitingspunten:
        contracten = sorted(dossier.contracten_van(punt), key=lambda c: c.geldig_van)
        if not contracten:
            uit.append(
                Bevinding(
                    "waarschuwing",
                    f"contract/{punt.energie_type}",
                    "Geen leveringscontract. Er valt dan niets door te rekenen "
                    "voor deze energiedrager.",
                )
            )
            continue
        for vorige, volgende in zip(contracten, contracten[1:]):
            if vorige.geldig_tot is None:
                uit.append(
                    Bevinding(
                        "fout",
                        f"contract/{punt.energie_type}",
                        f"'{vorige.product}' van {vorige.leverancier} heeft geen "
                        f"einddatum maar wordt gevolgd door '{volgende.product}' "
                        f"vanaf {volgende.geldig_van}. Twee contracten die "
                        "tegelijk lopen geven een dubbele of willekeurige prijs.",
                    )
                )
            elif vorige.geldig_tot > volgende.geldig_van:
                uit.append(
                    Bevinding(
                        "fout",
                        f"contract/{punt.energie_type}",
                        f"Contracten overlappen tussen {volgende.geldig_van} en "
                        f"{vorige.geldig_tot}.",
                    )
                )
            elif vorige.geldig_tot < volgende.geldig_van:
                uit.append(
                    Bevinding(
                        "waarschuwing",
                        f"contract/{punt.energie_type}",
                        f"Gat in de contracthistoriek van {vorige.geldig_tot} tot "
                        f"{volgende.geldig_van}. Over die dagen kan niet gerekend "
                        "worden.",
                    )
                )
        for contract in contracten:
            # "Onbekend" is de plaatshouder die in het voorbeeldbestand staat.
            # Hij ziet eruit als een ingevuld contract maar is tegen geen enkel
            # product uit de V-test-data te koppelen, dus de berekening zou pas
            # bij het rekenen stuklopen in plaats van hier.
            for veld, waarde in (("leverancier", contract.leverancier), ("product", contract.product)):
                if waarde.strip().casefold() in ("", "onbekend"):
                    uit.append(
                        Bevinding(
                            "fout",
                            f"contract/{punt.energie_type}",
                            f"Contract vanaf {contract.geldig_van} heeft geen "
                            f"echte {veld} ({waarde!r}). Zonder leverancier en "
                            "productnaam is er geen tariefkaart op te zoeken.",
                        )
                    )
            if contract.prijs_bevriest and contract.tariefkaart_geldig_van is None:
                uit.append(
                    Bevinding(
                        "waarschuwing",
                        f"contract/{punt.energie_type}",
                        f"'{contract.product}' is een {contract.contracttype}-"
                        "contract zonder tariefkaart_van. De startdatum wordt "
                        "dan als bevriezingsdatum gebruikt; klopt dat niet, dan "
                        "rekent de historiek met de verkeerde tariefkaart.",
                    )
                )
    return uit


def _controleer_verbruik(dossier: Dossier) -> list[Bevinding]:
    uit: list[Bevinding] = []
    if dossier.fluvius_csv is not None and not dossier.fluvius_csv.is_file():
        uit.append(
            Bevinding(
                "fout",
                "verbruik/meetbestand",
                f"[verbruik].fluvius_csv wijst naar {dossier.fluvius_csv}, dat "
                "niet bestaat. Een pad naar een ontbrekend bestand leest als "
                "'er is meetdata' terwijl die er niet is.",
            )
        )
    for punt in dossier.aansluitingspunten:
        opgaven = dossier.opgaven_van(punt)
        heeft_meetdata = dossier.fluvius_csv is not None and dossier.fluvius_csv.is_file()
        if not opgaven:
            if punt.energie_type is EnergieType.ELEKTRICITEIT and not heeft_meetdata:
                uit.append(
                    Bevinding(
                        "fout",
                        f"verbruik/{punt.energie_type}",
                        "Geen jaarverbruik en geen meetbestand. Postcode plus een "
                        "verbruikscijfer is het minimum om te kunnen rekenen.",
                    )
                )
            continue
        for opgave in opgaven:
            if opgave.exactheidsklasse is not Exactheidsklasse.EXACT:
                uit.append(
                    Bevinding(
                        "info",
                        f"verbruik/{punt.energie_type}",
                        f"Opgave {opgave.periode_van}..{opgave.periode_tot} is "
                        f"'{opgave.bron}' en dus {opgave.exactheidsklasse}; elk "
                        "bedrag dat erop steunt erft die klasse.",
                    )
                )
            if opgave.afname_kwh <= 0:
                uit.append(
                    Bevinding(
                        "fout",
                        f"verbruik/{punt.energie_type}",
                        f"Opgave {opgave.periode_van}..{opgave.periode_tot} heeft "
                        "geen afname. Een nulverbruik is geen ontbrekend verbruik.",
                    )
                )
    return uit


def _controleer_hardware(dossier: Dossier, batterijen, omvormers) -> list[Bevinding]:
    uit: list[Bevinding] = []
    for asset in dossier.assets:
        if asset.type is AssetType.BATTERIJ and asset.merk and asset.model:
            try:
                batterijen.batterij(asset.merk, asset.model)
            except Exception as exc:
                uit.append(
                    Bevinding(
                        "fout",
                        "installatie/batterij",
                        f"{asset.merk} {asset.model}: {exc}",
                    )
                )
        if asset.omvormer_merk and asset.omvormer_model:
            try:
                omvormers.omvormer(asset.omvormer_merk, asset.omvormer_model)
            except Exception as exc:
                uit.append(
                    Bevinding(
                        "fout",
                        "installatie/omvormer",
                        f"{asset.omvormer_merk} {asset.omvormer_model}: {exc}",
                    )
                )
        if asset.type is AssetType.GASTOESTEL:
            # Geen harde fout: een gastoestel zonder deze velden telt vandaag
            # nog niet mee in de berekening (het gasverbruik komt uit
            # [[verbruiksopgave]], niet uit dit toestel — zie CLAUDE.md
            # "Uitbreiding dossiermodel"). De ontbrekende data is straks wel
            # nodig zodra een warmtevraagmodel het toestel wél gebruikt, dus
            # ze mag niet stil onopgemerkt blijven.
            if asset.vermogen_kw is None:
                uit.append(
                    Bevinding(
                        "waarschuwing",
                        "installatie/gastoestel",
                        f"Gastoestel {asset.model or '(zonder naam)'} heeft geen vermogen_kw.",
                    )
                )
            if not asset.doel:
                uit.append(
                    Bevinding(
                        "waarschuwing",
                        "installatie/gastoestel",
                        f"Gastoestel {asset.model or '(zonder naam)'} heeft geen doel "
                        "(ruimteverwarming/warm_water/beide).",
                    )
                )
    return uit
