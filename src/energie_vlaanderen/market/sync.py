from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from energie_vlaanderen.data.paths import DataPaths
from energie_vlaanderen.market.entsoe import EntsoeMarketData
from energie_vlaanderen.settings import Settings

LOG = logging.getLogger(__name__)


class MarketSyncError(RuntimeError):
    pass


@dataclass(frozen=True)
class MarketSyncResult:
    cache_path: Path
    start_date: datetime
    end_date: datetime
    records_loaded: int
    processed_at: datetime


class MarketSyncManager:
    def __init__(self, settings: Settings, api_key: str | None = None) -> None:
        self.settings = settings
        paths = DataPaths.from_settings(settings)
        paths.ensure()
        # Gebruik het centrale datapad
        self.cache_path = paths.market / "entsoe_cache.json"
        self.api_key = api_key

    def sync_period(
        self,
        start: datetime,
        end: datetime,
        *,
        allow_api: bool = True,
    ) -> MarketSyncResult:
        """
        Synchroniseer een volledige periode en werk de lokale ENTSO-E cache bij.
        """
        market_client = EntsoeMarketData(cache=self.cache_path, api_key=self.api_key)

        LOG.info("Start synchronisatie marktprijzen van %s tot %s", start.isoformat(), end.isoformat())

        try:
            df = market_client.load(start=start, end=end, allow_api=allow_api)
        except Exception as exc:
            raise MarketSyncError(f"Fout bij ophalen van ENTSO-E marktprijzen: {exc}") from exc

        record_count = len(df)
        LOG.info("Synchronisatie voltooid. %d datapunten beschikbaar in de cache.", record_count)

        return MarketSyncResult(
            cache_path=self.cache_path,
            start_date=start,
            end_date=end,
            records_loaded=record_count,
            processed_at=datetime.now(timezone.utc),
        )