"""Herkomst van een scenarioresultaat: met welke code, welke databankversie en
welk dossier is dit tot stand gekomen.

Het doel is expliciet reproduceerbaarheid en vergelijkbaarheid, niet enkel
archivering: gegeven `data_version_id` + `code_commit` + `dossier_snapshot`
(zie `gebruikers.repository.GebruikersRepository.bewaar_simulatie()`) is een
resultaat exact na te rekenen zonder de kwartierdata zelf te bewaren — de
databankversie legt de tarieven vast, de commit de rekenregels, en het
dossier het uitgangspunt. Wat *niet* meereist is de meting zelf
(`fluvius_csv`) of de lokale bestandspaden: die horen niet in een
databankrij, en de meting verandert toch niet aan wélke berekening erop
toegepast werd.

`dossier_snapshot()` laat bewust twee dingen weg die Manifest §5.2/§5.3
expliciet gevoelig noemen: `Persoonsgegevens` (naam/adres/e-mail) en de
EAN-code van elk aansluitingspunt. Geen van beide is nodig om de berekening
zelf te reproduceren — postcode/gemeente sturen de tariefselectie, de EAN
identificeert enkel de fysieke aansluiting.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import subprocess
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any, Optional
from uuid import UUID

from energie_vlaanderen.gebruikers.toml_io import Dossier


def huidige_commit(project_root: Path) -> tuple[Optional[str], bool]:
    """(commit_sha, dirty) van de git-werkboom op `project_root`.

    Geeft `(None, False)` terug buiten een git-repo, zonder `git` op het pad,
    of bij eender welke andere fout: herkomst vastleggen mag een berekening
    nooit laten mislukken, enkel de herkomst onvolledig laten — dezelfde regel
    als `laad_metingen()`/`laad_markt()` elders in dit pakket bij een
    ontbrekende optionele bron.
    """
    try:
        sha = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=project_root,
            capture_output=True, text=True, timeout=5, check=True,
        ).stdout.strip()
        status = subprocess.run(
            ["git", "status", "--porcelain"], cwd=project_root,
            capture_output=True, text=True, timeout=5, check=True,
        ).stdout
        return sha, bool(status.strip())
    except Exception:
        return None, False


def _naar_jsonbaar(waarde: Any) -> Any:
    """Zet één waarde recursief om naar iets dat `json.dumps` aankan.

    Generiek over elke `dataclass` in `gebruikers.models` in plaats van per
    klasse een eigen serialisator te schrijven (het patroon dat
    `scenario.opslag` wél hanteert, omdat dat bestand een leesbaar
    JSON/YAML-exportformaat voor mensen bouwt — hier gaat het om een
    databankveld dat enkel zichzelf terug moet geven via `laad()`-achtige
    code, dus telt volledigheid zwaarder dan leesbaarheid).
    """
    if waarde is None or isinstance(waarde, (str, int, float, bool)):
        return waarde
    if isinstance(waarde, Enum):
        return str(waarde.value)
    if isinstance(waarde, Decimal):
        return str(waarde)
    if isinstance(waarde, (datetime, date)):
        return waarde.isoformat()
    if isinstance(waarde, UUID):
        return str(waarde)
    if isinstance(waarde, Path):
        # Een lokaal bestandspad is niet overdraagbaar tussen machines en
        # hoort niet in een reproduceerbare snapshot — enkel of het er was.
        return None
    if dataclasses.is_dataclass(waarde) and not isinstance(waarde, type):
        return {f.name: _naar_jsonbaar(getattr(waarde, f.name)) for f in dataclasses.fields(waarde)}
    if isinstance(waarde, (list, tuple, set, frozenset)):
        return [_naar_jsonbaar(v) for v in waarde]
    if isinstance(waarde, dict):
        return {str(k): _naar_jsonbaar(v) for k, v in waarde.items()}
    return str(waarde)


def dossier_snapshot(dossier: Dossier) -> dict[str, Any]:
    """Het dossier als plat, JSON-vriendelijk dict — zonder persoonsgegevens,
    EAN-codes of lokale bestandspaden.

    `persoonsgegevens` en `bron` (het pad naar `gebruiker.toml`) worden
    volledig weggelaten; `fluvius_csv` wordt herleid tot een boolean (was er
    een meting, niet welk bestand). `ean_code` wordt per aansluitingspunt op
    `None` gezet in plaats van het veld te schrappen, zodat de vorm van een
    `Aansluitingspunt` herkenbaar blijft.
    """
    return {
        "gebruiker": _naar_jsonbaar(dossier.gebruiker),
        "aansluitingspunten": [
            {**_naar_jsonbaar(punt), "ean_code": None} for punt in dossier.aansluitingspunten
        ],
        "meters": [_naar_jsonbaar(m) for m in dossier.meters],
        "assets": [_naar_jsonbaar(a) for a in dossier.assets],
        "contracten": [_naar_jsonbaar(c) for c in dossier.contracten],
        "verbruiksopgaven": [_naar_jsonbaar(v) for v in dossier.verbruiksopgaven],
        "aannames": [_naar_jsonbaar(a) for a in dossier.aannames],
        "heeft_fluvius_meting": dossier.fluvius_csv is not None,
    }


def scenario_parameters(scenario: Any) -> dict[str, Any]:
    """De constructor-argumenten van een `Scenario`, als plat dict.

    `Scenario` zelf is geen dataclass (enkel de subklassen zijn dat), dus
    `naam`/`omschrijving` — de twee velden die de basisklasse toevoegt via
    gewone class-attributen, niet via `@dataclass`-velden — horen niet bij
    `dataclasses.fields()` van een subklasse en verschijnen hier dus terecht
    niet: die twee staan al apart in `simulatie.scenario_naam`.
    """
    return {f.name: _naar_jsonbaar(getattr(scenario, f.name)) for f in dataclasses.fields(scenario)}


def dossier_hash(snapshot: dict[str, Any]) -> str:
    """sha256 van een canonieke JSON-vorm van `snapshot`.

    Twee simulaties met exact hetzelfde dossier krijgen dezelfde hash — te
    gebruiken om te groeperen of om te herkennen dat een dossier tussen twee
    runs veranderd is — zonder de hele snapshot cel voor cel te vergelijken.
    """
    canoniek = json.dumps(snapshot, sort_keys=True, ensure_ascii=True, default=str)
    return hashlib.sha256(canoniek.encode("utf-8")).hexdigest()
