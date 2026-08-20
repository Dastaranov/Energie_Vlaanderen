from __future__ import annotations
import argparse, json, logging, os
from datetime import datetime
from decimal import Decimal
from pathlib import Path
import sys
import pandas as pd
from .constants import D
from .models import Profile
from .normalizer import money
from .repository import DataRepository
from .calculator import Calculator
from .intervals import FluviusIntervals
from .market import EntsoeMarketData
from .validation import validate_excel_against_csv
from .config import Settings
from .paths import DataPaths, DataPathsError

LOG = logging.getLogger("energievergelijker")

def show_paths() -> int:
    settings = Settings.load()
    paths = DataPaths.from_settings(settings)
    paths.ensure()

    print(f"Projectroot : {settings.project_root}")
    print(f"Dataroot    : {paths.root}")
    print(f"Raw         : {paths.raw}")
    print(f"Staging     : {paths.staging}")
    print(f"Versions    : {paths.versions}")
    print(f"Failed      : {paths.failed}")

    try:
        print(f"Current     : {paths.current_data_dir()}")
    except DataPathsError:
        print("Current     : nog niet ingesteld")

    return 0

def main()->int:
    if len(sys.argv) == 2 and sys.argv[1] == "paths":
        return show_paths()
    ap=argparse.ArgumentParser(description="EnergieVergelijker v2")
    ap.add_argument("--data",type=Path,default=Path(".")); ap.add_argument("--postcode",required=True); ap.add_argument("--gemeente",default="")
    ap.add_argument("--segment",default="Woning"); ap.add_argument("--year",type=int,default=2026); ap.add_argument("--month",type=int,default=datetime.now().month)
    ap.add_argument("--dag",type=Decimal,default=D("2000")); ap.add_argument("--nacht",type=Decimal,default=D("1500")); ap.add_argument("--piek",type=Decimal,default=D("4"))
    ap.add_argument("--meter",choices=["digitaal","analoog"],default="digitaal"); ap.add_argument("--omvormer-kva",type=Decimal,default=D("0"))
    ap.add_argument("--kwartier-csv",type=Path); ap.add_argument("--entsoe-cache",type=Path); ap.add_argument("--api-key")
    ap.add_argument("--levies-eur-kwh",type=Decimal,default=D("0"),help="Federale/regionale heffingen buiten DNB, excl. btw")
    ap.add_argument("--energy-fund-eur-year",type=Decimal,default=D("0")); ap.add_argument("--top",type=int,default=20); ap.add_argument("--csv",type=Path)
    ap.add_argument("--validate-sources",action="store_true")
    args=ap.parse_args(); logging.basicConfig(level=logging.INFO,format="%(levelname)s %(message)s")
    repo=DataRepository(args.data)
    if args.validate_sources:
        checks=[validate_excel_against_csv(args.data/"Distributienettarieven elektriciteit 2026.xlsx",args.data/"DNB_ELEK_2026.csv","elektriciteit"),
                validate_excel_against_csv(args.data/"Distributienettarieven aardgas 2026.xlsx",args.data/"DNB_GAS_2026.csv","gas")]
        print(json.dumps(checks,ensure_ascii=False,indent=2)); return 0 if all(x["ok"] for x in checks) else 2
    p=Profile(args.postcode,args.gemeente,args.segment,args.meter,args.dag,args.nacht,omvormer_kva=args.omvormer_kva,geschatte_maandpiek_kw=args.piek,kwartier_csv=args.kwartier_csv)
    products=repo.products(args.year,args.month,args.segment)
    intervals=FluviusIntervals.read(args.kwartier_csv) if args.kwartier_csv else None
    market=None
    if any(x.kind.startswith("dynamisch") for x in products):
        cache=args.entsoe_cache or args.data/"entsoe_day_ahead_prices.json"
        md=EntsoeMarketData(cache,args.api_key)
        if intervals is not None and not intervals.empty:
            start=intervals.timestamp.min().to_pydatetime(); end=(intervals.timestamp.max()+pd.Timedelta(minutes=15)).to_pydatetime()
        else:
            start=datetime(args.year,args.month,1); end=datetime(args.year+(args.month==12),(args.month%12)+1,1)
        market=md.load(start,end,allow_api=bool(args.api_key or os.getenv("ENTSOE_API_KEY")))
    calc=Calculator(repo,levies_eur_kwh=args.levies_eur_kwh,energy_fund_eur_year=args.energy_fund_eur_year)
    rows=[]
    for product in products:
        try:
            c=calc.calculate(product,p,market,intervals)
            rows.append({"leverancier":product.supplier,"product":product.name,"type":product.kind,"energiekost_excl_btw":float(money(c.supplier)),
                         "nettarief_excl_btw":float(money(c.grid)),"heffingen_excl_btw":float(money(c.levies)),"btw":float(money(c.vat)),"totaal_incl_btw":float(money(c.total)),"waarschuwingen":" | ".join(c.warnings),"bron":product.source})
        except Exception as e: LOG.warning("%s - %s overgeslagen: %s",product.supplier,product.name,e)
    result=pd.DataFrame(rows).sort_values("totaal_incl_btw") if rows else pd.DataFrame()
    print(result.head(args.top).to_string(index=False))
    if args.csv: result.to_csv(args.csv,sep=";",index=False,encoding="utf-8-sig",decimal=",")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
