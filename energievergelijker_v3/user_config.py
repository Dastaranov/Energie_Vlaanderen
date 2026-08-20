from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Literal, Mapping

try:
    import tomllib
except ModuleNotFoundError as exc:
    raise RuntimeError(
        "TOML-configuratie vereist Python 3.11 of hoger."
    ) from exc


class ConfigError(ValueError):
    """De gebruikersconfiguratie ontbreekt of bevat ongeldige gegevens."""


ContractType = Literal["vast", "variabel", "dynamisch"]
MissingDataPolicy = Literal["fout", "waarschuwen", "aanvullen"]
Resolution = Literal["kwartier", "uur", "dag"]


@dataclass(frozen=True)
class User:
    postcode: str
    gemeente: str
    segment: str = "Woning"


@dataclass(frozen=True)
class Connection:
    electricity: bool = True
    gas: bool = False
    meter: str = "digitaal"
    solar_panels: bool = False
    inverter_kva: float = 0.0


@dataclass(frozen=True)
class Consumption:
    fluvius_csv: Path
    missing_data: MissingDataPolicy = "waarschuwen"
    resolution: Resolution = "kwartier"


@dataclass(frozen=True)
class CurrentContract:
    supplier: str
    product: str
    kind: ContractType
    start_date: date


@dataclass(frozen=True)
class Analysis:
    history_from: date
    comparison_months: int = 12
    compare_fixed: bool = True
    compare_variable: bool = True
    compare_dynamic: bool = True
    include_injection: bool = True


@dataclass(frozen=True)
class Output:
    directory: Path
    top_count: int = 20
    csv: bool = True


@dataclass(frozen=True)
class UserConfig:
    source: Path
    project_root: Path
    user: User
    connection: Connection
    consumption: Consumption
    electricity_contract: CurrentContract | None
    analysis: Analysis
    output: Output


def _section(
    data: Mapping[str, Any],
    name: str,
    *,
    required: bool = True,
) -> Mapping[str, Any]:
    value = data.get(name)

    if value is None:
        if required:
            raise ConfigError(
                f"Verplichte sectie [{name}] ontbreekt."
            )
        return {}

    if not isinstance(value, Mapping):
        raise ConfigError(
            f"[{name}] moet een TOML-sectie zijn."
        )

    return value


def _required_string(
    data: Mapping[str, Any],
    key: str,
    section: str,
) -> str:
    value = data.get(key)

    if not isinstance(value, str) or not value.strip():
        raise ConfigError(
            f"[{section}].{key} is verplicht "
            "en moet tekst bevatten."
        )

    return value.strip()


def _boolean(
    data: Mapping[str, Any],
    key: str,
    default: bool,
    section: str,
) -> bool:
    value = data.get(key, default)

    if not isinstance(value, bool):
        raise ConfigError(
            f"[{section}].{key} moet true of false zijn."
        )

    return value


def _integer(
    data: Mapping[str, Any],
    key: str,
    default: int,
    section: str,
    *,
    minimum: int = 0,
) -> int:
    value = data.get(key, default)

    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(
            f"[{section}].{key} moet een geheel getal zijn."
        )

    if value < minimum:
        raise ConfigError(
            f"[{section}].{key} moet minstens {minimum} zijn."
        )

    return value


def _number(
    data: Mapping[str, Any],
    key: str,
    default: float,
    section: str,
    *,
    minimum: float = 0.0,
) -> float:
    value = data.get(key, default)

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(
            f"[{section}].{key} moet een getal zijn."
        )

    result = float(value)

    if result < minimum:
        raise ConfigError(
            f"[{section}].{key} moet minstens {minimum} zijn."
        )

    return result


def _date_value(
    data: Mapping[str, Any],
    key: str,
    section: str,
) -> date:
    value = data.get(key)

    if isinstance(value, date):
        return value

    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise ConfigError(
                f"[{section}].{key} moet YYYY-MM-DD zijn."
            ) from exc

    raise ConfigError(
        f"[{section}].{key} is verplicht "
        "en moet een datum zijn."
    )


def _path_value(
    value: str,
    project_root: Path,
) -> Path:
    path = Path(value).expanduser()

    if not path.is_absolute():
        path = project_root / path

    return path.resolve()


def load_user_config(
    path: Path | str,
    *,
    project_root: Path | None = None,
) -> UserConfig:
    source = Path(path).expanduser().resolve()

    if not source.is_file():
        raise ConfigError(
            f"Configuratiebestand bestaat niet: {source}"
        )

    if project_root is None:
        project_root = source.parent
    else:
        project_root = Path(project_root).expanduser().resolve()

    try:
        with source.open("rb") as handle:
            raw = tomllib.load(handle)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(
            f"Ongeldige TOML in {source.name}: {exc}"
        ) from exc

    user_raw = _section(raw, "gebruiker")
    connection_raw = _section(raw, "aansluiting")
    consumption_raw = _section(raw, "verbruik")
    analysis_raw = _section(raw, "analyse")
    output_raw = _section(raw, "uitvoer", required=False)

    postcode = _required_string(
        user_raw,
        "postcode",
        "gebruiker",
    )

    if not postcode.isdigit() or len(postcode) != 4:
        raise ConfigError(
            "[gebruiker].postcode moet uit vier cijfers bestaan."
        )

    user = User(
        postcode=postcode,
        gemeente=_required_string(
            user_raw,
            "gemeente",
            "gebruiker",
        ),
        segment=str(
            user_raw.get("segment", "Woning")
        ).strip(),
    )

    meter = str(
        connection_raw.get("meter", "digitaal")
    ).strip().casefold()

    if meter not in {"digitaal", "analoog"}:
        raise ConfigError(
            "[aansluiting].meter moet "
            "'digitaal' of 'analoog' zijn."
        )

    connection = Connection(
        electricity=_boolean(
            connection_raw,
            "elektriciteit",
            True,
            "aansluiting",
        ),
        gas=_boolean(
            connection_raw,
            "gas",
            False,
            "aansluiting",
        ),
        meter=meter,
        solar_panels=_boolean(
            connection_raw,
            "zonnepanelen",
            False,
            "aansluiting",
        ),
        inverter_kva=_number(
            connection_raw,
            "omvormer_kva",
            0.0,
            "aansluiting",
        ),
    )

    missing_data = str(
        consumption_raw.get(
            "ontbrekende_data",
            "waarschuwen",
        )
    ).strip().casefold()

    if missing_data not in {
        "fout",
        "waarschuwen",
        "aanvullen",
    }:
        raise ConfigError(
            "[verbruik].ontbrekende_data moet "
            "'fout', 'waarschuwen' of 'aanvullen' zijn."
        )

    resolution = str(
        consumption_raw.get(
            "resolutie",
            "kwartier",
        )
    ).strip().casefold()

    if resolution not in {"kwartier", "uur", "dag"}:
        raise ConfigError(
            "[verbruik].resolutie moet "
            "'kwartier', 'uur' of 'dag' zijn."
        )

    consumption = Consumption(
        fluvius_csv=_path_value(
            _required_string(
                consumption_raw,
                "fluvius_csv",
                "verbruik",
            ),
            project_root,
        ),
        missing_data=missing_data,
        resolution=resolution,
    )

    contract: CurrentContract | None = None
    contracts_raw = raw.get("huidig_contract", {})

    if isinstance(contracts_raw, Mapping):
        electricity_raw = contracts_raw.get("elektriciteit")

        if electricity_raw is not None:
            if not isinstance(electricity_raw, Mapping):
                raise ConfigError(
                    "[huidig_contract.elektriciteit] "
                    "moet een TOML-sectie zijn."
                )

            kind = _required_string(
                electricity_raw,
                "type",
                "huidig_contract.elektriciteit",
            ).casefold()

            if kind not in {
                "vast",
                "variabel",
                "dynamisch",
            }:
                raise ConfigError(
                    "[huidig_contract.elektriciteit].type "
                    "moet 'vast', 'variabel' of "
                    "'dynamisch' zijn."
                )

            contract = CurrentContract(
                supplier=_required_string(
                    electricity_raw,
                    "leverancier",
                    "huidig_contract.elektriciteit",
                ),
                product=_required_string(
                    electricity_raw,
                    "product",
                    "huidig_contract.elektriciteit",
                ),
                kind=kind,
                start_date=_date_value(
                    electricity_raw,
                    "startdatum",
                    "huidig_contract.elektriciteit",
                ),
            )

    analysis = Analysis(
        history_from=_date_value(
            analysis_raw,
            "historiek_vanaf",
            "analyse",
        ),
        comparison_months=_integer(
            analysis_raw,
            "vergelijkingsperiode_maanden",
            12,
            "analyse",
            minimum=1,
        ),
        compare_fixed=_boolean(
            analysis_raw,
            "vergelijk_vast",
            True,
            "analyse",
        ),
        compare_variable=_boolean(
            analysis_raw,
            "vergelijk_variabel",
            True,
            "analyse",
        ),
        compare_dynamic=_boolean(
            analysis_raw,
            "vergelijk_dynamisch",
            True,
            "analyse",
        ),
        include_injection=_boolean(
            analysis_raw,
            "inclusief_injectie",
            True,
            "analyse",
        ),
    )

    output = Output(
        directory=_path_value(
            str(output_raw.get("map", "output")),
            project_root,
        ),
        top_count=_integer(
            output_raw,
            "top_aantal",
            20,
            "uitvoer",
        ),
        csv=_boolean(
            output_raw,
            "csv",
            True,
            "uitvoer",
        ),
    )

    if not connection.electricity and not connection.gas:
        raise ConfigError(
            "Minstens elektriciteit of gas moet actief zijn."
        )

    if (
        analysis.compare_dynamic
        and connection.electricity
        and meter != "digitaal"
    ):
        raise ConfigError(
            "Een dynamische vergelijking vereist "
            "een digitale elektriciteitsmeter."
        )

    return UserConfig(
        source=source,
        project_root=project_root,
        user=user,
        connection=connection,
        consumption=consumption,
        electricity_contract=contract,
        analysis=analysis,
        output=output,
    )