from __future__ import annotations

import logging
from urllib.parse import urlparse, unquote

import requests

from energie_vlaanderen.ingest.sources import (
    PageLink,
    SourceArtifact,
    SourceDiscoveryError,
    VnrSourceScraper,
)
from energie_vlaanderen.settings import Settings

LOG = logging.getLogger(__name__)

# Bestandsextensies die van Synergrid aanvaard worden. RLP0N en SLP-EX zijn
# .xlsb (Excel Binary Workbook) — enkel SPP is .xlsx. VnrSourceScraper staat
# alleen .xlsx toe, dus deze scraper herbruikt zoveel mogelijk van die klasse
# maar overschrijft de linkfilter.
ALLOWED_EXTENSIONS = (".xlsx", ".xlsb")


class SynergridSourceScraper(VnrSourceScraper):
    """
    Ontdek de officiële verbruiksprofielen (SLP-EX, RLP0N, SPP) op de
    documentcentrumpagina van Synergrid.

    De pagina groepeert bestanden per jaar zonder vast URL-patroon — 2026
    staat onder een `/SLP-RLP-SPP/2026/`-submap, oudere jaren grotendeels
    direct onder `/images/downloads/`. Er wordt daarom net als bij
    `VnrSourceScraper` van de links op de pagina zelf vertrokken, nooit van
    een sjabloon-URL.

    Downloadt de werkboeken nog niet — enkel `discover()`.
    """

    def __init__(
        self,
        settings: Settings,
        *,
        session: requests.Session | None = None,
    ):
        super().__init__(settings, session=session)

    def discover(self, year: int) -> dict[str, SourceArtifact]:
        if year < 2000 or year > 2100:
            raise SourceDiscoveryError(
                f"Ongeldig jaar voor bronontdekking: {year}"
            )

        page_url = self.settings.synergrid_profielen_page_url
        links = self.links_from_page(page_url)

        return {
            "slp_ex": self._select_one(
                links=links,
                page_url=page_url,
                kind="slp_ex",
                required_patterns=(
                    r"slp[\s_-]*ex",
                    rf"\b{year}\b",
                ),
                excluded_patterns=(
                    r"parameter",
                ),
            ),
            "rlp0n_elektriciteit": self._select_one(
                links=links,
                page_url=page_url,
                kind="rlp0n_elektriciteit",
                required_patterns=(
                    r"rlp0n",
                    r"electricity",
                    r"all[\s-]*dsos",
                    rf"\b{year}\b",
                ),
                excluded_patterns=(
                    r"parameter",
                ),
            ),
            "rlp0n_gas": self._select_one(
                links=links,
                page_url=page_url,
                kind="rlp0n_gas",
                required_patterns=(
                    r"rlp0n",
                    r"gas",
                    r"gos",
                    rf"\b{year}\b",
                ),
                excluded_patterns=(
                    r"parameter",
                ),
            ),
            "spp": self._select_one(
                links=links,
                page_url=page_url,
                kind="spp",
                required_patterns=(
                    r"spp",
                    r"ex[\s_-]*ante",
                    rf"\b{year}\b",
                ),
                excluded_patterns=(),
            ),
        }

    def parse_links(
        self,
        *,
        html: str,
        page_url: str,
    ) -> list[PageLink]:
        """Zelfde als de VREG-variant, maar .xlsb wordt ook toegelaten."""
        from bs4 import BeautifulSoup
        from urllib.parse import urljoin

        soup = BeautifulSoup(html, "html.parser")

        result: list[PageLink] = []
        seen: set[str] = set()

        for anchor in soup.select("a[href]"):
            raw_href = str(anchor.get("href", "")).strip()
            if not raw_href:
                continue

            url = urljoin(page_url, raw_href)

            if not self._is_allowed_download_url(url):
                continue

            if url in seen:
                continue
            seen.add(url)

            text = " ".join(anchor.get_text(" ", strip=True).split())
            result.append(PageLink(text=text, url=url))

        return result

    def _is_allowed_download_url(self, url: str) -> bool:
        parsed = urlparse(url)

        if parsed.scheme not in {"https", "http"}:
            return False

        host = parsed.hostname.casefold() if parsed.hostname else ""
        allowed_hosts = {
            allowed.casefold() for allowed in self.settings.allowed_download_hosts
        }

        if host not in allowed_hosts:
            return False

        decoded_path = unquote(parsed.path).casefold()
        return decoded_path.endswith(ALLOWED_EXTENSIONS)
