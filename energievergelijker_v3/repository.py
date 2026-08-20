from __future__ import annotations
from decimal import Decimal
from pathlib import Path
from typing import Optional
import pandas as pd
from .constants import D, DNB_CODES, MONTHS
from .models import Product
from .normalizer import dec, norm
from .parser import PRODUCT_SCHEMA, RobustCsvParser

class DataRepositoryError(RuntimeError):
    pass

class DataRepository:
    REQUIRED_FILES = (
        "DnbPerGemeente.csv",
        "DNB_ELEK_2026.csv",
        "master_vast_2026.csv",
        "master_var_dyn_2026.csv",
    )

    def __init__(self, root: Path):
        self.root = Path(root).expanduser().resolve()

        missing = [
            filename
            for filename in self.REQUIRED_FILES
            if not (self.root / filename).is_file()
        ]

        if missing:
            formatted = "\n".join(
                f"  - {filename}"
                for filename in missing
            )

            raise DataRepositoryError(
                f"Datamap is onvolledig: {self.root}\n"
                f"Ontbrekende bestanden:\n{formatted}\n"
                "Voer eerst de updater uit of geef een geldige "
                "datamap door."
            )

        generic = RobustCsvParser(strict=True)
        products = RobustCsvParser(
            schema=PRODUCT_SCHEMA,
            strict=True,
        )

        self.municipal = generic.read(
            self.root / "DnbPerGemeente.csv"
        )

        self.dnb = generic.read(
            self.root / "DNB_ELEK_2026.csv"
        )

        self.dnb["Prijs_num"] = self.dnb["Prijs"].map(
            lambda value: float(dec(value, D("0")))
        )

        self.fixed = products.read(
            self.root / "master_vast_2026.csv"
        )

        self.variable = products.read(
            self.root / "master_var_dyn_2026.csv"
        )

    def dnb_for(self, postcode: str, gemeente: str = "") -> tuple[str, str]:
        rows = self.municipal[self.municipal["Postcode"].astype(str).str.strip() == str(postcode).strip()]
        if gemeente:
            exact = rows[rows["Gemeente"].fillna("").str.casefold() == gemeente.casefold()]
            if not exact.empty: rows = exact
        values = rows["DNB Elektriciteit"].dropna().unique().tolist()
        if len(values) != 1:
            raise ValueError(f"Postcode {postcode} is ontbrekend of niet eenduidig; geef ook gemeente op. Kandidaten: {values}")
        name = values[0]
        if name not in DNB_CODES: raise ValueError(f"Onbekende DNB: {name}")
        return name, DNB_CODES[name]

    @staticmethod
    def _component_key(label: str) -> str:
        x = norm(label).casefold()
        if "vaste vergoeding" in x: return "fixed_fee"
        if "groene stroom" in x: return "green"
        if "wkk" in x: return "wkk"
        if "dynamisch tarief" in x: return "dynamic"
        if "tweevoudige" in x and ("nacht" in x or "dal" in x): return "night"
        if "tweevoudige" in x and ("dag" in x or "piek" in x): return "day"
        if "uitsluitend nacht" in x: return "exclusive_night"
        if "enkelvoudige" in x: return "single"
        return x

    def products(self, year: int, month: int, segment: str, energy="Elektriciteit", direction="Afname") -> list[Product]:
        out: list[Product] = []
        f = self.fixed.copy(); f["M"] = f["Maand"].fillna("").str.lower().map(MONTHS)
        f = f[(f["Jaar"].astype(str)==str(year)) & (f["M"]==month) &
              (f["Segment"].fillna("").str.casefold()==segment.casefold()) &
              (f["Energietype"].fillna("").str.casefold()==energy.casefold()) &
              (f["Contracttype"].fillna("").str.casefold()==direction.casefold())]
        type_col = "Vast/variabel/dynamisch" if "Vast/variabel/dynamisch" in f.columns else "Variabel/Dynamisch"
        for keys, g in f.groupby(["Handelsnaam", "Productnaam", type_col], dropna=False):
            p = Product(year,month,segment,energy,direction,norm(keys[0]),norm(keys[1]),norm(keys[2]).lower(),source="master_vast_2026.csv")
            for _, r in g.iterrows():
                value = dec(r.get("Prijs"))
                if value is not None: p.components[self._component_key(r.get("Prijsonderdeel"))] = value
            out.append(p)
        vdf=self.variable.copy(); vdf["M"]=vdf["Maand"].fillna("").str.lower().map(MONTHS)
        vdf=vdf[(vdf["Jaar"].astype(str)==str(year)) & (vdf["M"]==month) &
                (vdf["Segment"].fillna("").str.casefold()==segment.casefold()) &
                (vdf["Energietype"].fillna("").str.casefold()==energy.casefold()) &
                (vdf["Contracttype"].fillna("").str.casefold()==direction.casefold())]
        for keys,g in vdf.groupby(["Handelsnaam","Productnaam","Variabel/Dynamisch"], dropna=False):
            p=Product(year,month,segment,energy,direction,norm(keys[0]),norm(keys[1]),norm(keys[2]).lower(),source="master_var_dyn_2026.csv")
            for _,r in g.iterrows():
                k=self._component_key(r.get("Prijsonderdeel")); price=dec(r.get("Prijs"))
                if price is not None: p.components[k]=price
                if k in {"single","day","night","exclusive_night","dynamic"}:
                    formula={x:dec(r.get(x),D("0")) for x in "abcdz"}
                    for letter in "ABCD":
                        formula[letter]=self._index_value(r,letter)
                        formula[f"name_{letter}"]=norm(r.get(f"Indexatieparameter {letter} (a.A + b.B + c.C + d.D + z)"))
                    p.formulas[k]=formula
            # Sommige dynamische producten staan in de bron onder het generieke
            # prijsonderdeel "Enkelvoudige meter dagtarief". Canonicaliseer dit
            # zodat de calculator niet afhankelijk is van de leverancierslabel.
            if p.kind.startswith("dynamisch") and "dynamic" not in p.formulas and "single" in p.formulas:
                p.formulas["dynamic"] = p.formulas["single"]
                if "single" in p.components and "dynamic" not in p.components:
                    p.components["dynamic"] = p.components["single"]
            out.append(p)
        return out

    @staticmethod
    def _index_value(row: pd.Series, letter: str) -> Optional[Decimal]:
        prefixes = (f"Waarde {letter} (€/MWh)", f"Waarde {letter} (�/MWh)")
        preferred = ("VNR waarde", "laatst gekende waarde")
        columns = [c for c in row.index if any(c.startswith(prefix) for prefix in prefixes)]
        columns.sort(key=lambda c: next((i for i,p in enumerate(preferred) if p in c), len(preferred)))
        for column in columns:
            value = dec(row.get(column))
            if value is not None: return value
        return None
