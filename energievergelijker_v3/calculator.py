from __future__ import annotations
from decimal import Decimal
from typing import Optional
import pandas as pd
from .constants import D
from .models import Cost, Product, Profile
from .repository import DataRepository

class Calculator:
    def __init__(self, repo: DataRepository, vat=D("0.06"), levies_eur_kwh=D("0"), energy_fund_eur_year=D("0")):
        self.repo=repo; self.vat=vat; self.levies_rate=levies_eur_kwh; self.energy_fund=energy_fund_eur_year

    def grid_cost(self,p:Profile)->Decimal:
        _,code=self.repo.dnb_for(p.postcode,p.gemeente)
        kind="ELEK_LS_DIGI" if p.meter=="digitaal" else ("ELEK_LS_ANA_PRO" if p.omvormer_kva>0 else "ELEK_LS_ANA")
        rows=self.repo.dnb[(self.repo.dnb.Netbeheerder==code)&(self.repo.dnb.Klanttype==kind)&(self.repo.dnb.Contracttype=="Afname")]
        def val(detail,unit=None,tarifftype=None):
            q=rows[rows.Tariefdetail.str.casefold().eq(detail.casefold())]
            if unit:q=q[q.Tariefnotering==unit]
            if tarifftype:q=q[q.Tarieftype.str.casefold().eq(tarifftype.casefold())]
            return D(str(q.iloc[0].Prijs_num)) if not q.empty else D("0")
        normal=val("kWh-tarief","EUR/kW","Tarieven voor netgebruik") or val("Vaste term","EUR/kWh","Tarieven voor netgebruik")
        odv_n=val("kWh-tarief normaal","EUR/kWh"); odv_x=val("kWh-tarief exclusief nacht","EUR/kWh")
        toe=val("Tarieven voor de toeslagen","EUR/kWh"); data=val("Laagspanningnet","EUR/jaar")
        volume=p.afname_dag_kwh*(normal+odv_n+toe)+p.afname_nacht_kwh*(normal+odv_x+toe)
        if p.meter=="digitaal":
            rate=val("Gemiddelde maandpiek","EUR/kW/jaar")
            peaks=p.maandpieken_kw or tuple([p.geschatte_maandpiek_kw]*12)
            capacity=sum((max(x,D("2.5"))*rate/D("12") for x in peaks),D("0"))
            maximum=val("Maximumtarief","EUR/kWh")*p.afname_kwh
            capacity_plus_volume=min(capacity+volume,maximum) if maximum>0 else capacity+volume
            minimum=D("2.5")*rate
            grid=max(capacity_plus_volume,minimum)+data
        else:
            fixed=val("Vaste term","EUR/jaar","Tarieven voor netgebruik")
            pros=val("Aanvullend capaciteitstarief voor prosumenten met terugdraaiende teller","EUR/kW/jaar")*p.omvormer_kva
            grid=fixed+volume+data+pros
        return grid

    @staticmethod
    def formula_ct(f: dict[str,Any], overrides: Optional[dict[str,Decimal]]=None) -> Decimal:
        overrides=overrides or {}; total=f.get("z") or D("0")
        for coeff,letter in zip("abcd","ABCD"):
            x=overrides.get(f.get(f"name_{letter}")) or f.get(letter)
            if x is not None: total += (f.get(coeff) or D("0"))*x
        return total

    def supplier_cost(self, product:Product,p:Profile, market:Optional[pd.DataFrame]=None, intervals:Optional[pd.DataFrame]=None)->tuple[Decimal,list[str]]:
        warnings=[]; total=p.afname_kwh; fixed=product.components.get("fixed_fee",D("0"))
        extras=(product.components.get("green",D("0"))+product.components.get("wkk",D("0")))/D("100")*total
        if product.kind.startswith("vast"):
            d=product.components.get("day",product.components.get("single")); n=product.components.get("night",d)
            if d is None: raise ValueError("Vast product mist afnameprijs")
            return p.afname_dag_kwh*d/D("100")+p.afname_nacht_kwh*(n or d)/D("100")+fixed+extras,warnings
        if product.kind.startswith("variabel"):
            fd=product.formulas.get("day",product.formulas.get("single")); fn=product.formulas.get("night",fd)
            if not fd: raise ValueError("Variabel product mist formule")
            # supplied VNR/laatst gekende indexwaarden zijn authoritative; ENTSO-E raw gemiddelde is niet gelijk aan RLP-gewogen indices
            d=self.formula_ct(fd); n=self.formula_ct(fn or fd)
            if not any(fd.get(letter) is not None and (fd.get(coeff) or D("0")) != 0 for coeff, letter in zip("abcd", "ABCD")):
                fallback=product.components.get("day",product.components.get("single"))
                if fallback is None: raise ValueError("Variabele formule mist indexwaarde en berekende prijs")
                d=fallback; warnings.append("Variabele prijs gebruikt de aangeleverde berekende Prijs omdat de indexwaarde ontbreekt.")
            if fn and not any(fn.get(letter) is not None and (fn.get(coeff) or D("0")) != 0 for coeff, letter in zip("abcd", "ABCD")):
                n=product.components.get("night",d)
            return p.afname_dag_kwh*d/D("100")+p.afname_nacht_kwh*n/D("100")+fixed+extras,warnings
        if product.kind.startswith("dynamisch"):
            f=product.formulas.get("dynamic")
            if not f: raise ValueError("Dynamisch product mist formule")
            if market is None or market.empty: raise ValueError("Geen ENTSO-E marktprijzen voor dynamisch product")
            if intervals is None or intervals.empty:
                warnings.append("Dynamisch tarief benaderd met vlak verbruiksprofiel; laad kwartierdata voor een exacte berekening.")
                w=total/D(str(len(market))); usage=pd.DataFrame({"timestamp":market.timestamp,"afname_kwh":float(w)})
            else:
                usage=intervals[["timestamp","afname_kwh"]].copy()
            m=market[["timestamp","price_eur_mwh"]].copy().sort_values("timestamp")
            u=usage.sort_values("timestamp")
            # Match kwartierverbruik aan uurprijs; PT15M-prijzen matchen rechtstreeks.
            resolution=m.timestamp.diff().dropna().median()
            if resolution>=pd.Timedelta(minutes=60):
                u["market_ts"]=u.timestamp.dt.floor("h")
            else:u["market_ts"]=u.timestamp.dt.floor("15min")
            merged=u.merge(m,left_on="market_ts",right_on="timestamp",how="inner",suffixes=("_usage","_market"))
            if merged.empty: raise ValueError("Verbruik en marktprijzen overlappen niet")
            a=f.get("a") or D("0"); z=f.get("z") or D("0")
            # a * EUR/MWh + z geeft ct/kWh volgens de VNR-formules in de masterdata.
            energy=sum((D(str(r.afname_kwh))*((a*D(str(r.price_eur_mwh))+z)/D("100")) for r in merged.itertuples()),D("0"))
            return energy+fixed+extras,warnings
        raise ValueError(f"Onbekend tarieftype: {product.kind}")

    def calculate(self,product:Product,p:Profile,market=None,intervals=None,inject_product:Optional[Product]=None)->Cost:
        supplier,warnings=self.supplier_cost(product,p,market,intervals)
        grid=self.grid_cost(p); levies=self.levies_rate*p.afname_kwh+self.energy_fund
        credit=D("0")
        if p.injectie_kwh>0:
            if inject_product is None: warnings.append("Injectie niet verrekend: geen terugleveringsproduct gekoppeld.")
            else:
                # vaste/variabele injectie op dezelfde componentlogica, zonder nettarieven
                ip=Profile(p.postcode,p.gemeente,p.segment,p.meter,p.injectie_dag_kwh,p.injectie_nacht_kwh)
                credit,_=self.supplier_cost(inject_product,ip,market,intervals)
        taxable=supplier+grid+levies-credit
        vat=max(taxable,D("0"))*self.vat
        return Cost(supplier,grid,levies,credit,vat,warnings)
