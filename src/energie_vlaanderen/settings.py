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

DEFAULT_ALLOWED_DOWNLOAD_HOSTS = (
    "assets.vlaamsenutsregulator.be",
)

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

    allowed_download_hosts: tuple[str, ...] = (
        DEFAULT_ALLOWED_DOWNLOAD_HOSTS
    )

    request_timeout_seconds: float = 60.0
    max_download_bytes: int = 50 * 1024 * 1024
    download_chunk_bytes: int = 1024 * 1024

    user_agent: str = "EnergieVergelijker/3.0"

    @classmethod
    def load(
        cls,
        *,
        project_root: Path | None = None,
        environ: Mapping[str, str] | None = None,
    ) -> "Settings":
        env = os.environ if environ is None else environ

        root = (
            project_root.expanduser().resolve()
            if project_root is not None
            else discover_project_root()
        )

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

        max_download_text = env.get(
            "ENERGIEVERGELIJKER_MAX_DOWNLOAD_BYTES",
            str(50 * 1024 * 1024),
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
            request_timeout_seconds=timeout,
            max_download_bytes=max_download_bytes,
        )

    def with_data_root(self, data_root: Path) -> "Settings":
        return replace(
            self,
            data_root=data_root.expanduser().resolve(),
        )