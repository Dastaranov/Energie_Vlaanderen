from __future__ import annotations
from datetime import date
from decimal import Decimal
from typing import Optional
import pandas as pd
from energie_vlaanderen.utility.constants import D
from energie_vlaanderen.domain.models import Cost, Product, Profile
from energie_vlaanderen.data.bron import TariefBron
from energie_vlaanderen.heffingen.repository import HeffingenRepository
from typing import Any

class Calculator:
    def __init__(self, repo: TariefBron, vat=D("0.06"), heffingen: Optional[HeffingenRepository] = None):
        self.repo=repo; self.vat=vat; self.heffingen=heffingen

    def grid_cost(self,p:Profile,dagen:int=365)->Decimal:
        """De netkost voor `dagen` dagen met de volumes uit `p`.

        Nettarieven mengen twee soorten grootheden, en die schalen niet
        hetzelfde. Het volumetrische deel volgt de kWh in `p`. Het
        capaciteitstarief, het databeheer, de vaste term van de analoge
        categorie en de wettelijke ondergrens zijn *jaar*bedragen: die worden
        met `dagen/365` verdeeld.

        Dat onderscheid kwam uit een echte eindafrekening. Die rekende over 310
        gemeten dagen een capaciteitstarief van 311,23 EUR aan — precies
        7,409 kW x (190/365 x 49,042629 + 120/365 x 50,123982), dus het
        jaarbedrag naar rato van de dagen. Wie in plaats daarvan door de
        meetperiode deelt, rekent 365/310 = 1,177 keer te veel op elke vaste
        post.
        """
        _,code=self.repo.dnb_for(p.postcode,p.gemeente)
        kind="ELEK_LS_DIGI" if p.meter=="digitaal" else ("ELEK_LS_ANA_PRO" if p.omvormer_kva>0 else "ELEK_LS_ANA")
        rows=self.repo.dnb[(self.repo.dnb.Netbeheerder==code)&(self.repo.dnb.Klanttype==kind)&(self.repo.dnb.Contracttype=="Afname")]
        # Manifest §12: een ontbrekend verplicht tarief stopt de berekening. Zonder
        # deze controle geeft elke lookup hieronder D("0") terug en komt er een
        # netkost van 0,00 EUR uit — een bedrag dat er plausibel uitziet en
        # nergens op slaat. Dat gebeurde echt: het VREG-werkboek van 2024 parseert
        # met de huidige parser maar 4 van de 8 netbeheerders en kent geen
        # ELEK_LS_DIGI, waardoor een digitale meter in Aalst stilzwijgend gratis
        # op het net zat.
        if rows.empty:
            beschikbaar_type = sorted(
                self.repo.dnb[self.repo.dnb.Netbeheerder==code].Klanttype.dropna().unique()
            )
            beschikbaar_nb = sorted(self.repo.dnb.Netbeheerder.dropna().unique())
            raise ValueError(
                f"Geen nettarieven voor netbeheerder {code} en klanttype {kind}. "
                + (
                    f"Voor {code} bestaan wel: {', '.join(beschikbaar_type)}."
                    if beschikbaar_type
                    else f"Netbeheerder {code} komt niet voor; wel: {', '.join(beschikbaar_nb)}."
                )
            )
        def val(detail,unit=None,tarifftype=None,bevat=None,verplicht=False):
            q=rows[rows.Tariefdetail.str.casefold().eq(detail.casefold())]
            if unit:q=q[q.Tariefnotering==unit]
            if tarifftype:q=q[q.Tarieftype.str.casefold().eq(tarifftype.casefold())]
            # `bevat` matcht op een deelstring van het tarieftype. Het werkboek
            # schrijft "Tarieven voor het netgebruik"; een exacte match op
            # "Tarieven voor netgebruik" mist dat, en een gemiste match geeft
            # hier stil D("0") in plaats van een fout.
            if bevat:q=q[q.Tarieftype.str.casefold().str.contains(bevat.casefold(),na=False)]
            if q.empty:
                # Manifest §12: een ontbrekend verplicht tarief stopt de
                # berekening. Een tarief dat er *is* en 0 bedraagt is iets
                # anders dan een tarief dat ontbreekt — vandaar dat hier op de
                # afwezigheid van de rij getoetst wordt en niet op de waarde.
                if verplicht:
                    raise ValueError(
                        f"Nettarief ontbreekt voor {code}/{kind}: {detail!r}"
                        + (f" ({unit})" if unit else "")
                        + ". Zonder dat tarief zou de netkost stil te laag "
                        "uitvallen."
                    )
                return D("0")
            return D(str(q.iloc[0].Prijs_num))
        # Het volumetrische distributienettarief. Deze lookup zocht op notering
        # "EUR/kW" en tarieftype "Tarieven voor netgebruik", terwijl het
        # werkboek "EUR/kWh" en "Tarieven voor het netgebruik" schrijft — beide
        # filters misten, dus stond de term stil op nul. Bij FMV 2026 en
        # 3.000 kWh scheelde dat 74,62 EUR per jaar op de netkost, zonder
        # foutmelding. Eén lookup volstaat voor digitaal (0,024864 EUR/kWh) en
        # analoog (0,057772 EUR/kWh): `rows` is al op klanttype gefilterd.
        normal=val("kWh-tarief","EUR/kWh",bevat="netgebruik")
        odv_n=val("kWh-tarief normaal","EUR/kWh"); odv_x=val("kWh-tarief exclusief nacht","EUR/kWh")
        toe=val("Tarieven voor de toeslagen","EUR/kWh"); data=val("Laagspanningnet","EUR/jaar")
        # Het lagere "exclusief nacht"-ODV-tarief geldt alleen voor dát register.
        # Bij een tweevoudige meter krijgen piek- én daluren het normale tarief:
        # "dal" is geen exclusief-nachtaansluiting. Dit stond eerder op
        # `afname_nacht_kwh`, waardoor elk dalverbruik het lagere tarief kreeg —
        # op een echte afrekening 35 EUR per jaar te weinig netkost.
        volume=(
            (p.afname_dag_kwh+p.afname_nacht_kwh)*(normal+odv_n+toe)
            +p.afname_exclusief_nacht_kwh*(normal+odv_x+toe)
        )
        jaardeel=D(dagen)/D("365")
        data=data*jaardeel
        if p.meter=="digitaal":
            # Bij een digitale meter is het capaciteitstarief de grootste post
            # van de netkost; ontbreekt het, dan klopt er niets van het bedrag.
            rate=val("Gemiddelde maandpiek","EUR/kW/jaar",verplicht=True)
            peaks=p.maandpieken_kw or tuple([p.geschatte_maandpiek_kw]*12)
            floor=p.minimum_maandpiek_kw
            capacity=sum((max(x,floor)*rate/D("12") for x in peaks),D("0"))*jaardeel
            maximum=val("Maximumtarief","EUR/kWh")*p.afname_kwh
            capacity_plus_volume=min(capacity+volume,maximum) if maximum>0 else capacity+volume
            minimum=floor*rate*jaardeel
            grid=max(capacity_plus_volume,minimum)+data
        else:
            # Zelfde tarieftype-mismatch als hierboven: de vaste term van de
            # analoge klantcategorie (125,31 EUR/jaar bij FMV 2026) viel weg.
            fixed=val("Vaste term","EUR/jaar",bevat="netgebruik",verplicht=True)*jaardeel
            pros=val("Aanvullend capaciteitstarief voor prosumenten met terugdraaiende teller","EUR/kW/jaar")*p.omvormer_kva*jaardeel
            grid=fixed+volume+data+pros
        return grid

    @staticmethod
    def _index(f: dict[str,Any], letter: str) -> dict[str,Any]:
        """De indexparameter `letter` uit een formule, of een leeg record.

        `DataRepository.products()` schrijft `formula["index_A"] = {"name": ...,
        "value": ...}`; deze klasse las eerder `f.get("A")` en `f.get("name_A")`.
        Die sleutels bestonden niet, dus zag de guard in `supplier_cost()` nooit
        een indexwaarde en viel *elk* variabel product terug op de door VREG
        meegeleverde berekende prijs — met waarschuwing, maar zonder dat de
        formule ooit gerekend heeft.
        """
        waarde=f.get(f"index_{letter}")
        return waarde if isinstance(waarde,dict) else {}

    @classmethod
    def heeft_indexwaarde(cls, f: dict[str,Any]) -> bool:
        """Is deze formule met haar eigen indexwaarden door te rekenen?"""
        return any(
            cls._index(f,letter).get("value") is not None
            and (f.get(coeff) or D("0")) != 0
            for coeff,letter in zip("abcd","ABCD")
        )

    @classmethod
    def formula_ct(cls, f: dict[str,Any], overrides: Optional[dict[str,Decimal]]=None) -> Decimal:
        overrides=overrides or {}; total=f.get("z") or D("0")
        for coeff,letter in zip("abcd","ABCD"):
            index=cls._index(f,letter)
            if not index: continue
            x=overrides.get(index.get("name")) or index.get("value")
            if x is not None: total += (f.get(coeff) or D("0"))*x
        return total

    def supplier_cost(self, product:Product,p:Profile, market:Optional[pd.DataFrame]=None,
                      intervals:Optional[pd.DataFrame]=None, *,
                      sta_vlak_profiel:bool=True)->tuple[Decimal,list[str]]:
        """De leverancierskost van één product voor dit profiel.

        `sta_vlak_profiel=False` weigert de terugval op een vlak lastprofiel bij
        een dynamisch product. Voor afname is dat vlakke profiel een grove maar
        bruikbare benadering (Manifest §9: "uitsluitend voor demonstratie"); voor
        *injectie* is het onzin. Zonneproductie is nul bij nacht en piekt rond de
        middag, precies wanneer de marktprijs het laagst is — een vlakke spreiding
        waardeert die kWh tegen het daggemiddelde en overschat de opbrengst
        systematisch. Liever stoppen dan een plausibel ogend, te hoog bedrag.
        """
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
            if not self.heeft_indexwaarde(fd):
                fallback=product.components.get("day",product.components.get("single"))
                if fallback is None: raise ValueError("Variabele formule mist indexwaarde en berekende prijs")
                d=fallback; warnings.append("Variabele prijs gebruikt de aangeleverde berekende Prijs omdat de indexwaarde ontbreekt.")
            if fn and not self.heeft_indexwaarde(fn):
                n=product.components.get("night",d)
            return p.afname_dag_kwh*d/D("100")+p.afname_nacht_kwh*n/D("100")+fixed+extras,warnings
        if product.kind.startswith("dynamisch"):
            f=product.formulas.get("dynamic")
            if not f: raise ValueError("Dynamisch product mist formule")
            if market is None or market.empty: raise ValueError("Geen ENTSO-E marktprijzen voor dynamisch product")
            if intervals is None or intervals.empty:
                if not sta_vlak_profiel:
                    raise ValueError(
                        "Een dynamisch product vereist hier een echte "
                        "kwartierreeks; een vlak profiel is geen benadering "
                        "maar een systematische afwijking."
                    )
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
            # Een inner join laat elk interval vallen waarvoor geen prijs bestaat.
            # Dat is stil gratis verbruik: Manifest §12 zegt dat een ontbrekende
            # marktprijs een interval niet stilzwijgend mag laten verdwijnen.
            # We meten daarom het volume vóór en na de koppeling.
            aangeboden=D(str(u.afname_kwh.sum())); gekoppeld=D(str(merged.afname_kwh.sum()))
            if aangeboden>0 and (aangeboden-gekoppeld)/aangeboden>D("0.0001"):
                ontbreekt=len(u)-len(merged)
                raise ValueError(
                    f"Voor {ontbreekt} van de {len(u)} intervallen is er geen "
                    f"marktprijs ({gekoppeld:.3f} van {aangeboden:.3f} kWh gedekt). "
                    "Die energie zou anders gratis zijn; vul de prijsreeks aan "
                    "met `energievergelijker market sync --start --end`."
                )
            a=f.get("a") or D("0"); z=f.get("z") or D("0")
            # a * EUR/MWh + z geeft ct/kWh volgens de VNR-formules in de masterdata.
            energy=sum((D(str(r.afname_kwh))*((a*D(str(r.price_eur_mwh))+z)/D("100")) for r in merged.itertuples()),D("0"))
            return energy+fixed+extras,warnings
        raise ValueError(f"Onbekend tarieftype: {product.kind}")

    def levies_gesplitst(self,p:Profile,jaar:int,maand:int)->tuple[Decimal,Decimal]:
        """Splits de heffingen in wat met het verbruik meeschaalt en wat met de tijd.

        De accijns en de bijdrage op de energie volgen de kWh, en hun schijven
        zijn progressief over het *jaar*verbruik — die moeten dus op het
        volledige opgavevolume berekend worden en daarna naar het volumeaandeel
        van de deelperiode. Het energiefonds is een vast bedrag per maand en
        volgt de kalender, niet het verbruik.

        Ze samen teruggeven zou een van beide verkeerd verdelen zodra de
        meetperiode geen volledig jaar beslaat — en dat is bij een afrekening
        eerder regel dan uitzondering.
        """
        if self.heffingen is None:
            raise ValueError(
                "Calculator vereist een HeffingenRepository "
                "(zie energie_vlaanderen.heffingen.HeffingenRepository.load) "
                "— heffingen worden niet stilzwijgend op 0 gezet."
            )
        if p.segment=="Woning":
            accijns_categorie,fonds_categorie="niet_zakelijk","residentieel"
        else:
            accijns_categorie,fonds_categorie="zakelijk_laagspanning","niet_residentieel"
        bijzondere_accijns,energiebijdrage=self.heffingen.bereken_accijns_en_energiebijdrage(
            "elektriciteit",accijns_categorie,p.afname_kwh,date(jaar,maand,1))
        energiefonds=self.heffingen.energiefonds_per_jaar("laag",fonds_categorie,jaar)
        return bijzondere_accijns+energiebijdrage, energiefonds

    def levies(self,p:Profile,jaar:int,maand:int)->Decimal:
        """Publieke ingang op de heffingenberekening.

        Bestaat omdat een oproeper die per deelperiode rekent de heffingen apart
        nodig heeft: ze zijn een *jaar*grootheid (progressieve schijven over het
        jaarverbruik, energiefonds per maand) en worden naar dagen geschaald,
        terwijl de energiekost bij een dynamisch product per interval berekend
        wordt. `calculate()` kan die twee niet uit elkaar houden.
        """
        return self._levies(p,jaar,maand)

    def _levies(self,p:Profile,jaar:int,maand:int)->Decimal:
        # Manifest §12: "Ontbrekend verplicht tarief: berekening stoppen" —
        # geen stille 0 meer zoals in de oude, altijd-op-nul-staande
        # levies_eur_kwh/energy_fund_eur_year-constructorparameters.
        if self.heffingen is None:
            raise ValueError(
                "Calculator.calculate() vereist een HeffingenRepository "
                "(zie energie_vlaanderen.heffingen.HeffingenRepository.load) "
                "— heffingen worden niet stilzwijgend op 0 gezet."
            )
        # Enkel laagspanning is vandaag aan de Calculator gekoppeld (Fase 2-
        # scope); MS/HS-heffingendata bestaat wel al in config/heffingen/.
        if p.segment=="Woning":
            accijns_categorie,fonds_categorie="niet_zakelijk","residentieel"
        else:
            accijns_categorie,fonds_categorie="zakelijk_laagspanning","niet_residentieel"
        # De bijzondere accijns wijzigde binnen 2026 (46,00 i.p.v. 47,4811
        # EUR/MWh vanaf 01/08), dus het jaar alleen volstaat niet: we nemen de
        # eerste dag van de productmaand als peildatum.
        bijzondere_accijns,energiebijdrage=self.heffingen.bereken_accijns_en_energiebijdrage(
            "elektriciteit",accijns_categorie,p.afname_kwh,date(jaar,maand,1))
        energiefonds=self.heffingen.energiefonds_per_jaar("laag",fonds_categorie,jaar)
        return bijzondere_accijns+energiebijdrage+energiefonds

    def calculate(self,product:Product,p:Profile,market=None,intervals=None,
                  inject_product:Optional[Product]=None,injectie_intervals=None)->Cost:
        if product.energy.lower() not in ("elektriciteit","electricity"):
            # De heffingen op aardgas staan sinds de kalibratie van
            # 2026-08-31 wél in config/heffingen/. Wat nog ontbreekt is de
            # netzijde: grid_cost() rekent met elektriciteitstariefdetails
            # (capaciteitstarief, ODV), terwijl aardgas een vaste term plus
            # proportionele term per tariefgroep (GAS_T1..T6) kent, en die
            # groep hangt af van het jaarverbruik.
            raise ValueError(
                f"Kostberekening voor energievorm '{product.energy}' is nog "
                "niet ondersteund: de heffingen zijn beschikbaar, maar "
                "grid_cost() dekt enkel elektriciteit-laagspanning."
            )
        supplier,warnings=self.supplier_cost(product,p,market,intervals)
        grid=self.grid_cost(p); levies=self._levies(p,product.year,product.month)
        credit=D("0")
        if p.injectie_kwh>0:
            if inject_product is None: warnings.append("Injectie niet verrekend: geen terugleveringsproduct gekoppeld.")
            else:
                # vaste/variabele injectie op dezelfde componentlogica, zonder nettarieven
                # Keyword-argumenten, niet positioneel: de injectievolumes gaan
                # bewust in de afname-slots (injectieprijzen volgen dezelfde
                # componentlogica), maar positioneel zou een nieuw veld vóór
                # `afname_dag_kwh` dat stil verkeerd binden.
                ip=Profile(postcode=p.postcode,gemeente=p.gemeente,segment=p.segment,
                           meter=p.meter,afname_dag_kwh=p.injectie_dag_kwh,
                           afname_nacht_kwh=p.injectie_nacht_kwh)
                # `injectie_intervals`, niet `intervals`. Hier stond de
                # afnamereeks, waardoor een dynamisch injectieproduct het
                # *verbruik* tegen de injectieprijs waardeerde. Voor een vast of
                # variabel product viel dat niet op (die gebruiken enkel de
                # jaartotalen uit `ip`), maar verbruik en injectie hebben
                # tegengestelde dagprofielen: 's nachts verbruik en geen zon,
                # 's middags zon en weinig verbruik.
                credit,inj_warnings=self.supplier_cost(
                    inject_product,ip,market,injectie_intervals,sta_vlak_profiel=False)
                warnings.extend(inj_warnings)
        # De injectievergoeding valt búiten de btw-basis en wordt er niet van
        # afgetrokken. Ze is vrijgesteld onder Beslissing ET 131.616/2 van
        # 25-10-2019 — een echte eindafrekening zet haar in een aparte
        # vrijstellingsregel naast de 6%-basis, niet erin.
        #
        # Dit stond eerder als `taxable = supplier + grid + levies - credit`,
        # wat de btw-basis verlaagde. `docs/price_model_low_voltage.md` §9.1
        # schreef nóg iets anders voor (`T - injectieprijs x kWh x 1,06`, dus
        # het krediet zelf met btw verhoogd). Geen van beide klopte; Manifest
        # §14 noemde dit een openstaande validatie en de factuur beslist ze.
        taxable=supplier+grid+levies
        vat=max(taxable,D("0"))*self.vat
        return Cost(supplier,grid,levies,credit,vat,warnings)
