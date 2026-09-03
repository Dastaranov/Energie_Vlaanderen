from __future__ import annotations

import json
import logging
import os
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, time as dt_time
from pathlib import Path
from typing import Optional
import pandas as pd

from energie_vlaanderen.market.energy_charts import (
    BRON as energy_charts_bron,
    EnergyChartsMarketData,
)
from energie_vlaanderen.utility.constants import BE_DOMAIN, LOCAL_TZ, UTC


LOG = logging.getLogger(__name__)

BRON = "entsoe"


class EntsoeMarketData:
    BASE_URL = "https://web-api.tp.entsoe.eu/api"

    def __init__(
        self,
        cache: Path,
        api_key: Optional[str] = None,
        fallback: "EnergyChartsMarketData | None" = None,
        allow_fallback: bool = True,
    ):
        self.cache = cache
        self.api_key = api_key or os.getenv("ENTSOE_API_KEY")
        # ENTSO-E's Transparency Platform is een rapporteringsplatform en staat
        # los van de markt: het kan in onderhoud zijn terwijl de prijzen wel
        # degelijk bestaan. Zonder terugvalpad valt de rekentool dan stil op
        # data die publiek beschikbaar is.
        self.fallback = fallback or EnergyChartsMarketData()
        self.allow_fallback = allow_fallback

    def load(self, start: datetime, end: datetime, allow_api: bool = True) -> pd.DataFrame:
        store = {}
        if self.cache.exists():
            try:
                store = json.loads(self.cache.read_text(encoding="utf-8"))
            except Exception:
                store = {}

        s_utc = self._aware(start)
        e_utc = self._aware(end)

        # Check of we de data al lokaal hebben opgeslagen in de cache
        cache_key = f"period:{BE_DOMAIN}:{s_utc.isoformat()}:{e_utc.isoformat()}"
        rows = store.get(cache_key)

        if rows is None:
            # De cachesleutel is de volledige periodestring, dus een ander
            # datumbereik miste hem altijd — ook wanneer de gevraagde dagen er
            # allang in zaten. Wie in januari een halfjaar ophaalde en daarna
            # één maand opvroeg, kreeg een lege reeks terug of haalde alles
            # opnieuw op. Daarom eerst kijken of de al opgeslagen periodes het
            # gevraagde venster dekken.
            rows = self._uit_cache(store, s_utc, e_utc)

        if rows is None and allow_api:
            if not self.api_key:
                raise ValueError(
                    "ENTSO-E API-key ontbreekt: zet ENTSOE_API_KEY in .env "
                    "of als omgevingsvariabele."
                )
            
            # Vraag de volledige periode in ÉÉN keer op bij de API!
            rows = self._fetch_met_terugval(s_utc, e_utc)
            store[cache_key] = rows
            
            self.cache.parent.mkdir(parents=True, exist_ok=True)
            self.cache.write_text(json.dumps(store, indent=2), encoding="utf-8")

        if not rows:
            return pd.DataFrame(columns=["timestamp", "price_eur_mwh"])

        df = pd.DataFrame(rows)
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        if "price" in df and "price_eur_mwh" not in df:
            df["price_eur_mwh"] = df["price"]

        return df[(df.timestamp >= s_utc) & (df.timestamp < e_utc)].sort_values("timestamp").drop_duplicates("timestamp")

    @staticmethod
    def _uit_cache(store: dict, start_utc: datetime, end_utc: datetime):
        """Bedien het venster uit al opgeslagen periodes, of geef niets terug.

        Alle gecachte rijen worden samengevoegd en ontdubbeld op tijdstip. Het
        venster geldt als gedekt wanneer er een punt op of vóór de start staat,
        een punt binnen de laatste stap vóór het einde, en er nergens een gat
        groter dan die stap zit.

        Die laatste voorwaarde is het punt: een deels gevulde cache stil
        aanvaarden zou bij een dynamisch contract de ontbrekende kwartieren
        gratis maken. Manifest §12 — een ontbrekende marktprijs mag geen
        interval stilzwijgend laten verdwijnen. Bij twijfel dus liever niets
        teruggeven en de oproeper laten beslissen.
        """
        samen: dict[str, dict] = {}
        for sleutel, rijen in store.items():
            if not sleutel.startswith("period:") or not isinstance(rijen, list):
                continue
            for rij in rijen:
                tijdstip = rij.get("timestamp")
                if tijdstip:
                    samen[tijdstip] = rij
        if not samen:
            return None

        df = pd.DataFrame(list(samen.values()))
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        df = df.sort_values("timestamp")
        binnen = df[(df.timestamp >= start_utc) & (df.timestamp < end_utc)]
        if binnen.empty:
            return None

        stap = binnen["timestamp"].diff().dropna().median()
        if pd.isna(stap) or stap <= pd.Timedelta(0):
            return None
        dekt_start = binnen["timestamp"].iloc[0] <= start_utc + stap
        dekt_einde = binnen["timestamp"].iloc[-1] >= end_utc - stap
        if not (dekt_start and dekt_einde):
            LOG.warning(
                "Marktprijscache begint op %s en eindigt op %s; dat dekt "
                "%s..%s niet. De cache wordt niet gebruikt.",
                binnen["timestamp"].iloc[0], binnen["timestamp"].iloc[-1],
                start_utc.date(), end_utc.date(),
            )
            return None

        # Gaten *binnen* het venster worden hier gemeld maar niet geweigerd. Wie
        # de reeks gebruikt voor een dynamische berekening merkt ze zelf:
        # `Calculator.supplier_cost()` vergelijkt het gekoppelde volume met het
        # aangeboden volume en stopt wanneer er energie zonder prijs overblijft.
        # Hier weigeren zou ook de gevallen blokkeren waar de gaten buiten de
        # gebruikte uren vallen.
        grootste_gat = binnen["timestamp"].diff().max()
        if grootste_gat > stap:
            ontbrekend = int((binnen["timestamp"].diff().dropna() / stap - 1).clip(lower=0).sum())
            LOG.warning(
                "Marktprijscache mist ongeveer %d intervallen tussen %s en %s "
                "(grootste gat %s bij een resolutie van %s).",
                ontbrekend, start_utc.date(), end_utc.date(), grootste_gat, stap,
            )
        return binnen.to_dict("records")

    @staticmethod
    def _aware(x: datetime) -> datetime:
        return x.replace(tzinfo=LOCAL_TZ).astimezone(UTC) if x.tzinfo is None else x.astimezone(UTC)

    def _fetch_met_terugval(
        self, start_utc: datetime, end_utc: datetime
    ) -> list[dict]:
        """Probeer ENTSO-E; val bij een storing terug op de tweede bron.

        De terugval is luidruchtig en niet stil: er wordt gewaarschuwd én elke
        rij draagt een `source`-veld, zodat achteraf na te gaan is welke
        prijzen van welk platform komen. Een stille terugval zou het verschil
        tussen "officiële publicatie" en "spiegel" onzichtbaar maken.
        """
        try:
            return self._fetch_period(start_utc, end_utc)
        except Exception as exc:
            if not self.allow_fallback:
                raise
            LOG.warning(
                "ENTSO-E onbereikbaar (%s) — terugvallen op %s. "
                "De markt zelf ligt niet stil; enkel het publicatieplatform.",
                exc, energy_charts_bron,
            )
            rijen = self.fallback.fetch_period(start_utc, end_utc)
            LOG.warning(
                "%d prijzen afkomstig van %s in plaats van ENTSO-E.",
                len(rijen), energy_charts_bron,
            )
            return rijen

    def _fetch_period(self, start_utc: datetime, end_utc: datetime) -> list[dict]:
        params = {
            "securityToken": self.api_key,
            "documentType": "A44",
            "in_Domain": BE_DOMAIN,
            "out_Domain": BE_DOMAIN,
            "periodStart": start_utc.strftime("%Y%m%d%H%M"),
            "periodEnd": end_utc.strftime("%Y%m%d%H%M"),
        }
        
        req_url = self.BASE_URL + "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(req_url, headers={"User-Agent": "EnergieVergelijker/3.0"})

        # Timeout verruimd naar 120 seconden omdat een heel jaar opvragen even kan duren
        with urllib.request.urlopen(req, timeout=120) as resp:
            xml = resp.read()

        root = ET.fromstring(xml)
        ns = {"n": root.tag.split("}")[0].strip("{")} if "}" in root.tag else {}
        pref = "n:" if ns else ""
        out = []

        for period in root.findall(f".//{pref}Period", ns):
            start_str = period.findtext(f"{pref}timeInterval/{pref}start", namespaces=ns)
            res = period.findtext(f"{pref}resolution", namespaces=ns)
            
            if not start_str:
                continue
                
            start_ts = pd.Timestamp(start_str)
            step = pd.Timedelta(minutes=15 if res == "PT15M" else 60)

            for point in period.findall(f"{pref}Point", ns):
                pos_text = point.findtext(f"{pref}position", namespaces=ns)
                price_text = point.findtext(f"{pref}price.amount", namespaces=ns)
                
                if pos_text is None or price_text is None:
                    continue
                    
                pos = int(pos_text)
                price = float(price_text)
                
                ts = start_ts + (pos - 1) * step
                out.append({
                    "timestamp": ts.isoformat().replace("+00:00", "Z"),
                    "price_eur_mwh": price,
                    "source": BRON,
                })

        return out