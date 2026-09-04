"""Tests voor de tweede marktdatabron en de terugval erop.

Aanleiding: op 2026-08-31 serveerde ENTSO-E's Transparency Platform een
onderhoudspagina terwijl de Belgische markt gewoon doordraaide en dezelfde
prijzen elders wél beschikbaar waren. Eén bron betekende dat de rekentool
stilviel op data die er was.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from energie_vlaanderen.market.energy_charts import (
    EnergyChartsError,
    EnergyChartsMarketData,
)
from energie_vlaanderen.market.entsoe import EntsoeMarketData


pytestmark = pytest.mark.bronnen


def _antwoord(punten: list[tuple[int, float | None]], eenheid: str = "EUR / MWh") -> dict:
    return {
        "unix_seconds": [t for t, _ in punten],
        "price": [p for _, p in punten],
        "unit": eenheid,
    }


class _NepUrlopen:
    """Vervangt urllib.request.urlopen met een vast antwoord."""

    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.aangeroepen_url: str | None = None

    def __call__(self, req, timeout=None):  # noqa: ARG002
        self.aangeroepen_url = req.full_url
        return self

    def read(self) -> bytes:
        return json.dumps(self.payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _uur(datum: str) -> int:
    return int(
        datetime.fromisoformat(datum).replace(tzinfo=timezone.utc).timestamp()
    )


class TestEnergyCharts:
    def test_zet_punten_om_naar_rijen_met_herkomst(self, monkeypatch):
        payload = _antwoord([
            (_uur("2026-08-20T00:00"), 100.5),
            (_uur("2026-08-20T01:00"), 98.0),
        ])
        nep = _NepUrlopen(payload)
        monkeypatch.setattr("urllib.request.urlopen", nep)

        rijen = EnergyChartsMarketData().fetch_period(
            datetime(2026, 8, 20, tzinfo=timezone.utc),
            datetime(2026, 8, 21, tzinfo=timezone.utc),
        )

        assert rijen == [
            {
                "timestamp": "2026-08-20T00:00:00Z",
                "price_eur_mwh": 100.5,
                "source": "energy-charts.info",
            },
            {
                "timestamp": "2026-08-20T01:00:00Z",
                "price_eur_mwh": 98.0,
                "source": "energy-charts.info",
            },
        ]

    def test_snijdt_punten_buiten_de_periode_weg(self, monkeypatch):
        """De API werkt met hele dagen; wij vragen ruimer op en snijden bij."""
        payload = _antwoord([
            (_uur("2026-08-19T23:00"), 1.0),
            (_uur("2026-08-20T00:00"), 2.0),
            (_uur("2026-08-21T00:00"), 3.0),
        ])
        monkeypatch.setattr("urllib.request.urlopen", _NepUrlopen(payload))

        rijen = EnergyChartsMarketData().fetch_period(
            datetime(2026, 8, 20, tzinfo=timezone.utc),
            datetime(2026, 8, 21, tzinfo=timezone.utc),
        )

        assert [r["price_eur_mwh"] for r in rijen] == [2.0]

    def test_slaat_lege_prijzen_over(self, monkeypatch):
        payload = _antwoord([
            (_uur("2026-08-20T00:00"), None),
            (_uur("2026-08-20T01:00"), 50.0),
        ])
        monkeypatch.setattr("urllib.request.urlopen", _NepUrlopen(payload))

        rijen = EnergyChartsMarketData().fetch_period(
            datetime(2026, 8, 20, tzinfo=timezone.utc),
            datetime(2026, 8, 21, tzinfo=timezone.utc),
        )

        assert [r["price_eur_mwh"] for r in rijen] == [50.0]

    def test_verkeerde_eenheid_stopt_de_verwerking(self, monkeypatch):
        """Een prijs in ct/kWh doorlaten zou pas op de eindfactuur opvallen."""
        payload = _antwoord([(_uur("2026-08-20T00:00"), 10.0)], eenheid="ct / kWh")
        monkeypatch.setattr("urllib.request.urlopen", _NepUrlopen(payload))

        with pytest.raises(EnergyChartsError, match="ct / kWh"):
            EnergyChartsMarketData().fetch_period(
                datetime(2026, 8, 20, tzinfo=timezone.utc),
                datetime(2026, 8, 21, tzinfo=timezone.utc),
            )

    def test_ongelijke_lijstlengtes_stoppen_de_verwerking(self, monkeypatch):
        payload = {
            "unix_seconds": [_uur("2026-08-20T00:00"), _uur("2026-08-20T01:00")],
            "price": [10.0],
            "unit": "EUR / MWh",
        }
        monkeypatch.setattr("urllib.request.urlopen", _NepUrlopen(payload))

        with pytest.raises(EnergyChartsError, match="tijdstippen"):
            EnergyChartsMarketData().fetch_period(
                datetime(2026, 8, 20, tzinfo=timezone.utc),
                datetime(2026, 8, 21, tzinfo=timezone.utc),
            )

    def test_biedzone_staat_in_de_aanvraag(self, monkeypatch):
        nep = _NepUrlopen(_antwoord([(_uur("2026-08-20T00:00"), 1.0)]))
        monkeypatch.setattr("urllib.request.urlopen", nep)

        EnergyChartsMarketData().fetch_period(
            datetime(2026, 8, 20, tzinfo=timezone.utc),
            datetime(2026, 8, 21, tzinfo=timezone.utc),
        )

        assert "bzn=BE" in nep.aangeroepen_url


class _NepTerugval:
    def __init__(self) -> None:
        self.aangeroepen = False

    def fetch_period(self, start_utc, end_utc):  # noqa: ARG002
        self.aangeroepen = True
        return [
            {
                "timestamp": "2026-08-20T00:00:00Z",
                "price_eur_mwh": 42.0,
                "source": "energy-charts.info",
            }
        ]


class TestTerugval:
    def _client(self, tmp_path: Path, terugval, allow_fallback: bool = True):
        return EntsoeMarketData(
            cache=tmp_path / "cache.json",
            api_key="test",
            fallback=terugval,
            allow_fallback=allow_fallback,
        )

    def test_terugval_wordt_gebruikt_als_entsoe_faalt(self, tmp_path, monkeypatch):
        terugval = _NepTerugval()
        client = self._client(tmp_path, terugval)
        monkeypatch.setattr(
            client,
            "_fetch_period",
            lambda *a, **k: (_ for _ in ()).throw(OSError("503")),
        )

        df = client.load(
            datetime(2026, 8, 20, tzinfo=timezone.utc),
            datetime(2026, 8, 21, tzinfo=timezone.utc),
        )

        assert terugval.aangeroepen
        assert list(df.price_eur_mwh) == [42.0]

    def test_herkomst_wordt_bewaard(self, tmp_path, monkeypatch):
        """Zonder provenance is niet meer te zien welke prijs waar vandaan komt."""
        client = self._client(tmp_path, _NepTerugval())
        monkeypatch.setattr(
            client,
            "_fetch_period",
            lambda *a, **k: (_ for _ in ()).throw(OSError("503")),
        )

        client.load(
            datetime(2026, 8, 20, tzinfo=timezone.utc),
            datetime(2026, 8, 21, tzinfo=timezone.utc),
        )

        opgeslagen = json.loads((tmp_path / "cache.json").read_text())
        (rijen,) = opgeslagen.values()
        assert rijen[0]["source"] == "energy-charts.info"

    def test_terugval_kan_uitgezet_worden(self, tmp_path, monkeypatch):
        """Wie enkel de officiële publicatie wil, mag hard falen."""
        terugval = _NepTerugval()
        client = self._client(tmp_path, terugval, allow_fallback=False)
        monkeypatch.setattr(
            client,
            "_fetch_period",
            lambda *a, **k: (_ for _ in ()).throw(OSError("503")),
        )

        with pytest.raises(OSError):
            client.load(
                datetime(2026, 8, 20, tzinfo=timezone.utc),
                datetime(2026, 8, 21, tzinfo=timezone.utc),
            )
        assert not terugval.aangeroepen
