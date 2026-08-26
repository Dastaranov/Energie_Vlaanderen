from __future__ import annotations

from dataclasses import dataclass

from ...src.energie_vlaanderen.data.repository import DataRepository
from ...src.energie_vlaanderen.metering.fluvius_csv import (
    UsageProfile,
)
from .user_config import UserConfig


@dataclass(frozen=True)
class ResolvedProfile:
    config: UserConfig
    dnb_name: str
    dnb_code: str
    usage: UsageProfile


class ProfileService:
    def __init__(
        self,
        repository: DataRepository,
        usage_reader: FluviusUsageReader | None = None,
    ):
        self.repository = repository

        self.usage_reader = (
            usage_reader
            if usage_reader is not None
            else FluviusUsageReader()
        )

    def build(
        self,
        config: UserConfig,
    ) -> ResolvedProfile:
        dnb_name, dnb_code = self.repository.dnb_for(
            config.user.postcode,
            config.user.gemeente,
        )

        usage = self.usage_reader.read(
            config.consumption.fluvius_csv
        )

        return ResolvedProfile(
            config=config,
            dnb_name=dnb_name,
            dnb_code=dnb_code,
            usage=usage,
        )