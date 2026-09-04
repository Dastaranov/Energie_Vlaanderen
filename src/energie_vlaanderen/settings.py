from __future__ import annotations

import os
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Mapping


DEFAULT_VTEST_PAGE = (
    "https://www.vlaamsenutsregulator.be/"
    "cijfers/v-test-data-en-energieprijscurves"
)

DEFAULT_TARIFF_PAGE = (
    "https://www.vlaamsenutsregulator.be/"
    "elektriciteit-en-aardgas/nettarieven/"
    "hoeveel-bedragen-de-distributienettarieven"
)

DEFAULT_SYNERGRID_PROFIELEN_PAGE = (
    "https://www.synergrid.be/nl/documentencentrum/"
    "statistieken-gegevens/profielen-slp-spp-rlp"
)

# 50 MiB liet nauwelijks marge voor het SPP-productieprofiel van Synergrid
# (~49,7 MiB voor 2026) — een volgend jaar met meer netbeheerders of meer
# historiek kwam er zo overheen. 100 MiB geeft ademruimte zonder de eigenlijke
# bescherming (een oneindige of foute download) te verzwakken.
#
# Eén constante, en geen tweede getal in `Settings.load()`: die stond op 50 MiB
# terwijl de dataclass 100 MiB zei, en `load()` is de weg die de CLI gebruikt.
# De gedocumenteerde limiet gold dus nergens.
DEFAULT_MAX_DOWNLOAD_BYTES = 100 * 1024 * 1024

DEFAULT_ALLOWED_DOWNLOAD_HOSTS = (
    "assets.vlaamsenutsregulator.be",
    "www.synergrid.be",
)


def _read_dotenv(path: Path) -> dict[str, str]:
    """Lees een `.env`-bestand: `SLEUTEL=waarde` per regel.

    Bewust minimaal — geen `export`-prefixen, geen variabele-interpolatie,
    geen meerregelige waarden. Dat dekt wat dit project in `.env` zet
    (ENTSOE_API_KEY en databankcredentials) en houdt de afhankelijkheid op
    nul. Een onleesbaar of ontbrekend bestand levert een lege dict: `.env`
    is optioneel, alles kan ook als echte omgevingsvariabele gezet worden.
    """
    try:
        inhoud = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return {}

    waarden: dict[str, str] = {}
    for regel in inhoud.splitlines():
        regel = regel.strip()
        if not regel or regel.startswith("#") or "=" not in regel:
            continue
        sleutel, _, waarde = regel.partition("=")
        sleutel = sleutel.strip()
        if not sleutel:
            continue
        waarde = waarde.strip()
        if len(waarde) >= 2 and waarde[0] == waarde[-1] and waarde[0] in "\"'":
            waarde = waarde[1:-1]
        waarden[sleutel] = waarde
    return waarden


def discover_project_root(start: Path | None = None) -> Path:
    """
    Zoek vanaf `start` omhoog naar de map met pyproject.toml.

    Dit maakt de toepassing onafhankelijk van de actieve werkdirectory.
    """

    current = (
        start.expanduser().resolve()
        if start is not None
        else Path.cwd().resolve()
    )

    if current.is_file():
        current = current.parent

    for candidate in (current, *current.parents):
        if (candidate / "pyproject.toml").is_file():
            return candidate

    raise RuntimeError(
        "Projectroot kon niet worden bepaald. "
        "Geen pyproject.toml gevonden."
    )


@dataclass(frozen=True)
class Settings:
    project_root: Path
    data_root: Path

    vtest_page_url: str = DEFAULT_VTEST_PAGE
    tariff_page_url: str = DEFAULT_TARIFF_PAGE
    synergrid_profielen_page_url: str = DEFAULT_SYNERGRID_PROFIELEN_PAGE

    allowed_download_hosts: tuple[str, ...] = (
        DEFAULT_ALLOWED_DOWNLOAD_HOSTS
    )

    request_timeout_seconds: float = 60.0
    max_download_bytes: int = DEFAULT_MAX_DOWNLOAD_BYTES
    download_chunk_bytes: int = 1024 * 1024

    user_agent: str = "EnergieVergelijker/3.0"

    @classmethod
    def load(
        cls,
        *,
        project_root: Path | None = None,
        environ: Mapping[str, str] | None = None,
    ) -> "Settings":
        root = (
            project_root.expanduser().resolve()
            if project_root is not None
            else discover_project_root()
        )

        if environ is None:
            # `.env` in de projectwortel is de gedocumenteerde plek voor
            # ENTSOE_API_KEY en de databankcredentials (README/CLAUDE.md).
            # Zonder deze stap staan die daar wel, maar ziet niets ze: er werd
            # enkel os.environ gelezen, zodat `market sync` altijd afketste op
            # "API-key ontbreekt" tenzij je de sleutel zelf exporteerde.
            #
            # We zetten ze in os.environ en niet enkel in een lokale dict,
            # want de consumenten (market/entsoe.py, infrastructure/db) lezen
            # os.getenv rechtstreeks. Reeds gezette variabelen blijven staan:
            # een expliciete export hoort `.env` te overrulen.
            for sleutel, waarde in _read_dotenv(root / ".env").items():
                os.environ.setdefault(sleutel, waarde)
            env = os.environ
        else:
            env = environ

        configured_data_root = env.get(
            "ENERGIEVERGELIJKER_DATA_DIR"
        )

        data_root = (
            Path(configured_data_root).expanduser().resolve()
            if configured_data_root
            else root / "data"
        )

        timeout_text = env.get(
            "ENERGIEVERGELIJKER_REQUEST_TIMEOUT",
            "60",
        )

        try:
            timeout = float(timeout_text)
        except ValueError as exc:
            raise ValueError(
                "ENERGIEVERGELIJKER_REQUEST_TIMEOUT "
                "moet een getal zijn."
            ) from exc

        if timeout <= 0:
            raise ValueError(
                "ENERGIEVERGELIJKER_REQUEST_TIMEOUT "
                "moet groter zijn dan nul."
            )

        vtest_page_url = env.get(
            "ENERGIEVERGELIJKER_VTEST_PAGE_URL",
            DEFAULT_VTEST_PAGE,
        )

        tariff_page_url = env.get(
            "ENERGIEVERGELIJKER_TARIFF_PAGE_URL",
            DEFAULT_TARIFF_PAGE,
        )

        synergrid_profielen_page_url = env.get(
            "ENERGIEVERGELIJKER_SYNERGRID_PROFIELEN_PAGE_URL",
            DEFAULT_SYNERGRID_PROFIELEN_PAGE,
        )

        max_download_text = env.get(
            "ENERGIEVERGELIJKER_MAX_DOWNLOAD_BYTES",
            str(DEFAULT_MAX_DOWNLOAD_BYTES),
        )

        try:
            max_download_bytes = int(max_download_text)
        except ValueError as exc:
            raise ValueError(
                "ENERGIEVERGELIJKER_MAX_DOWNLOAD_BYTES "
                "moet een geheel getal zijn."
            ) from exc

        if max_download_bytes <= 0:
            raise ValueError(
                "ENERGIEVERGELIJKER_MAX_DOWNLOAD_BYTES "
                "moet groter zijn dan nul."
            )

        return cls(
            project_root=root,
            data_root=data_root,
            vtest_page_url=vtest_page_url,
            tariff_page_url=tariff_page_url,
            synergrid_profielen_page_url=synergrid_profielen_page_url,
            request_timeout_seconds=timeout,
            max_download_bytes=max_download_bytes,
        )

    def with_data_root(self, data_root: Path) -> "Settings":
        return replace(
            self,
            data_root=data_root.expanduser().resolve(),
        )