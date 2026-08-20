from __future__ import annotations
import json, os, urllib.parse, urllib.request
import xml.etree.ElementTree as ET
from datetime import date, datetime, time as dt_time, timedelta
from pathlib import Path
from typing import Optional
import pandas as pd
from .constants import BE_DOMAIN, LOCAL_TZ, UTC

class EntsoeMarketData:
    BASE_URL="https://web-api.tp.entsoe.eu/api"
    def __init__(self, cache: Path, api_key: Optional[str]=None):
        self.cache=cache; self.api_key=api_key or os.getenv("ENTSOE_API_KEY")

    def load(self, start: datetime, end: datetime, allow_api=True) -> pd.DataFrame:
        frames=[]; store={}
        if self.cache.exists(): store=json.loads(self.cache.read_text(encoding="utf-8"))
        start_local=self._aware(start).astimezone(LOCAL_TZ).date(); end_utc=self._aware(end)
        last=(end_utc-timedelta(microseconds=1)).astimezone(LOCAL_TZ).date(); day=start_local
        changed=False
        while day<=last:
            key=f"day:{BE_DOMAIN}:{day.isoformat()}"; rows=store.get(key)
            if rows is None and allow_api and self.api_key:
                rows=self._fetch_day(day); store[key]=rows; changed=True
            if rows: frames.append(pd.DataFrame(rows))
            day += timedelta(days=1)
        if changed:
            self.cache.parent.mkdir(parents=True,exist_ok=True); self.cache.write_text(json.dumps(store,indent=2),encoding="utf-8")
        if not frames:return pd.DataFrame(columns=["timestamp","price_eur_mwh"])
        df=pd.concat(frames,ignore_index=True); df["timestamp"]=pd.to_datetime(df["timestamp"],utc=True)
        if "price" in df and "price_eur_mwh" not in df: df["price_eur_mwh"]=df["price"]
        s,e=self._aware(start),self._aware(end)
        return df[(df.timestamp>=s)&(df.timestamp<e)].sort_values("timestamp").drop_duplicates("timestamp")

    @staticmethod
    def _aware(x): return x.replace(tzinfo=LOCAL_TZ).astimezone(UTC) if x.tzinfo is None else x.astimezone(UTC)
    def _fetch_day(self, day: date) -> list[dict]:
        if not self.api_key: raise ValueError("ENTSO-E API-key ontbreekt")
        ls=datetime.combine(day,dt_time.min,tzinfo=LOCAL_TZ); le=ls+timedelta(days=1)
        params={"securityToken":self.api_key,"documentType":"A44","in_Domain":BE_DOMAIN,"out_Domain":BE_DOMAIN,
                "periodStart":ls.astimezone(UTC).strftime("%Y%m%d%H%M"),"periodEnd":le.astimezone(UTC).strftime("%Y%m%d%H%M")}
        req=urllib.request.Request(self.BASE_URL+"?"+urllib.parse.urlencode(params),headers={"User-Agent":"EnergieVergelijker/2"})
        with urllib.request.urlopen(req,timeout=60) as resp: xml=resp.read()
        root=ET.fromstring(xml); ns={"n":root.tag.split("}")[0].strip("{")} if "}" in root.tag else {}
        pref="n:" if ns else ""; out=[]
        for period in root.findall(f".//{pref}Period",ns):
            start=pd.Timestamp(period.findtext(f"{pref}timeInterval/{pref}start",namespaces=ns)); res=period.findtext(f"{pref}resolution",namespaces=ns)
            step=pd.Timedelta(minutes=15 if res=="PT15M" else 60)
            for point in period.findall(f"{pref}Point",ns):
                pos=int(point.findtext(f"{pref}position",namespaces=ns)); price=float(point.findtext(f"{pref}price.amount",namespaces=ns))
                out.append({"timestamp":(start+(pos-1)*step).isoformat().replace("+00:00","Z"),"price_eur_mwh":price})
        return out
