from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import Iterable
from urllib.parse import unquote, urljoin, urlparse

from typing import Protocol
import requests
from bs4 import BeautifulSoup

from energie_vlaanderen.settings import Settings

import logging

LOG = logging.getLogger(__name__)

class SourceDiscoveryError(RuntimeError):
    """De officiële bronlinks konden niet eenduidig worden gevonden."""


@dataclass(frozen=True)
class PageLink:
    text: str
    url: str

    @property
    def decoded_url(self) -> str:
        return unquote(self.url)

    @property
    def filename(self) -> str:
        return PurePosixPath(unquote(urlparse(self.url).path)).name

    @property
    def search_text(self) -> str:
        return (
            f"{self.text} {self.filename}"
            .casefold()
        )


@dataclass(frozen=True)
class SourceArtifact:
    kind: str
    page_url: str
    url: str
    filename: str
    discovered_at: datetime

    def as_dict(self) -> dict[str, str]:
        return {
            "kind": self.kind,
            "page_url": self.page_url,
            "url": self.url,
            "filename": self.filename,
            "discovered_at": self.discovered_at.isoformat(),
        }


class VnrSourceScraper:
    """
    Ontdek officiële XLSX-bronnen op de website van
    de Vlaamse Nutsregulator.

    Deze klasse downloadt de werkboeken nog niet.
    """

    def __init__(
        self,
        settings: Settings,
        *,
        session: requests.Session | None = None,
    ):
        self.settings = settings
        self.session = session or requests.Session()

        self.session.headers.update(
            {
                "User-Agent": settings.user_agent,
                "Accept": (
                    "text/html,application/xhtml+xml,"
                    "application/xml;q=0.9,*/*;q=0.8"
                ),
            }
        )

    def discover(
        self,
        year: int,
    ) -> dict[str, SourceArtifact]:
        if year < 2000 or year > 2100:
            raise SourceDiscoveryError(
                f"Ongeldig jaar voor bronontdekking: {year}"
            )

        vtest_links = self.links_from_page(
            self.settings.vtest_page_url
        )

        tariff_links = self.links_from_page(
            self.settings.tariff_page_url
        )

        return {
            "vtest": self._select_one(
                links=vtest_links,
                page_url=self.settings.vtest_page_url,
                kind="vtest",
                required_patterns=(
                    r"v-test",
                    r"data",
                    r"\.xlsx(?:$|\?)",
                ),
                excluded_patterns=(
                    r"energieprijscurves",
                ),
            ),
            "energy_curves": self._select_one(
                links=vtest_links,
                page_url=self.settings.vtest_page_url,
                kind="energy_curves",
                required_patterns=(
                    r"energieprijscurves",
                    r"\.xlsx(?:$|\?)",
                ),
            ),
            "electricity_tariffs": self._select_one(
                links=tariff_links,
                page_url=self.settings.tariff_page_url,
                kind="electricity_tariffs",
                required_patterns=(
                    r"distributienettarieven",
                    r"elektriciteit",
                    rf"\b{year}\b",
                    r"\.xlsx(?:$|\?)",
                ),
            ),
            "gas_tariffs": self._select_one(
                links=tariff_links,
                page_url=self.settings.tariff_page_url,
                kind="gas_tariffs",
                required_patterns=(
                    r"distributienettarieven",
                    r"aardgas",
                    rf"\b{year}\b",
                    r"\.xlsx(?:$|\?)",
                ),
                excluded_patterns=(
                    r"enexis",
                ),
            ),
        }

    def links_from_page(
            self,
            page_url: str,
        ) -> list:
        try:
            response = self.session.get(
                page_url,
                timeout=self.settings.request_timeout_seconds
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise SourceDiscoveryError(
                f"Bronpagina kon niet worden opgehaald: "
                f"{page_url}: {exc}"
            ) from exc

        links = self.parse_links(
            html=response.text,
            page_url=page_url,
        )

        LOG.debug(
            "%d toegelaten XLSX-links gevonden op %s",
            len(links),
            page_url,
        )

        if not links:
            raise SourceDiscoveryError(
                f"Geen XLSX-links gevonden op {page_url}"
            )

        return links

    def parse_links(
        self,
        *,
        html: str,
        page_url: str,
    ) -> list[PageLink]:
        soup = BeautifulSoup(
            html,
            "html.parser",
        )

        result: list[PageLink] = []
        seen: set[str] = set()

        for anchor in soup.select("a[href]"):
            raw_href = str(anchor.get("href", "")).strip()

            if not raw_href:
                continue

            url = urljoin(
                page_url,
                raw_href,
            )

            if not self._is_allowed_xlsx_url(url):
                continue

            if url in seen:
                continue

            seen.add(url)

            text = " ".join(
                anchor.get_text(
                    " ",
                    strip=True,
                ).split()
            )

            result.append(
                PageLink(
                    text=text,
                    url=url,
                )
            )

        return result

    def _is_allowed_xlsx_url(
        self,
        url: str,
    ) -> bool:
        parsed = urlparse(url)

        if parsed.scheme not in {"https", "http"}:
            return False

        host = (
            parsed.hostname.casefold()
            if parsed.hostname
            else ""
        )

        allowed_hosts = {
            allowed.casefold()
            for allowed
            in self.settings.allowed_download_hosts
        }

        if host not in allowed_hosts:
            return False

        decoded_path = unquote(
            parsed.path
        ).casefold()

        return decoded_path.endswith(".xlsx")

    def _select_one(
        self,
        *,
        links: Iterable[PageLink],
        page_url: str,
        kind: str,
        required_patterns: tuple[str, ...],
        excluded_patterns: tuple[str, ...] = (),
    ) -> SourceArtifact:
        matches: list[PageLink] = []

        for link in links:
            haystack = link.search_text

            if not all(
                re.search(pattern, haystack)
                for pattern in required_patterns
            ):
                continue

            if any(
                re.search(pattern, haystack)
                for pattern in excluded_patterns
            ):
                continue

            matches.append(link)

        LOG.debug(
            "%d kandidaten gevonden voor bron %s",
            len(matches),
            kind,
        )

        if not matches:
            raise SourceDiscoveryError(
                f"Geen geschikte bron gevonden voor {kind} "
                f"op {page_url}"
            )

        if len(matches) > 1:
            candidates = "\n".join(
                f"  - {link.text or '(geen linktekst)'}: "
                f"{link.url}"
                for link in matches
            )

            raise SourceDiscoveryError(
                f"Bron voor {kind} is niet eenduidig. "
                f"{len(matches)} kandidaten gevonden:\n"
                f"{candidates}"
            )

        selected = matches[0]

        decoded_path = unquote(
            urlparse(selected.url).path
        )

        filename = PurePosixPath(
            decoded_path
        ).name

        return SourceArtifact(
            kind=kind,
            page_url=page_url,
            url=selected.url,
            filename=filename,
            discovered_at=datetime.now(
                timezone.utc
            ),
        )