#!/usr/bin/env python3
"""
Contractcontrole — vergelijkt een leverancierscontract rij voor rij
tussen de staging-CSV-bestanden en de PostgreSQL-databank.

Gebruik
-------
# Willekeurig contract uit de actieve versie
python scripts/verify_contract.py

# Specifiek contract
python scripts/verify_contract.py \
    --leverancier "Luminus" \
    --product "BasicFix" \
    --jaar 2025 --maand 1 \
    --segment "Woning" \
    --energie "Elektriciteit" \
    --richting "Afname"

# Andere versie opgeven
python scripts/verify_contract.py --versie 20260829T202059Z-853a7046

Exitcode 0 = alles OK, 1 = afwijkingen gevonden, 2 = contract niet gevonden.
"""
from __future__ import annotations

import argparse
import random
import sys
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pandas as pd
import sqlalchemy as sa

# ── project importeren via src/ pad ─────────────────────────────────────────
_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
sys.path.insert(0, str(_ROOT / "src"))

from energie_vlaanderen.infrastructure.db.connection import get_engine
from energie_vlaanderen.settings import Settings

# ── constanten ───────────────────────────────────────────────────────────────
_SEP = ";"
_ENC = "utf-8-sig"
_BREEDTE = 72
_OK  = "✓"
_NOK = "✗"

# Drempel voor Decimal-vergelijking (afrondingsverschillen tot 1e-5 worden genegeerd)
_DREMPEL = Decimal("0.000001")

# Kolommen die per component vergeleken worden: (csv_naam, db_naam)
_NUM_VELDEN = [
    ("price",         "prijs"),
    ("a",             "a"),
    ("b",             "b"),
    ("c",             "c"),
    ("d",             "d"),
    ("z",             "z"),
    ("index_value_A", "index_waarde_a"),
    ("index_value_B", "index_waarde_b"),
    ("index_value_C", "index_waarde_c"),
    ("index_value_D", "index_waarde_d"),
]

_TXT_VELDEN = [
    ("component_label", "component_label"),
    ("index_name_A",    "index_naam_a"),
    ("index_name_B",    "index_naam_b"),
    ("index_name_C",    "index_naam_c"),
    ("index_name_D",    "index_naam_d"),
]

# ── hulpfuncties ─────────────────────────────────────────────────────────────

def _dec(waarde) -> Decimal | None:
    """Zet een CSV-waarde (met eventuele komma als decimaalscheider) om naar Decimal."""
    if waarde is None:
        return None
    s = str(waarde).strip().replace(",", ".")
    if s in ("", "nan", "None"):
        return None
    try:
        return Decimal(s)
    except InvalidOperation:
        return None


def _str(waarde) -> str | None:
    s = str(waarde).strip() if waarde is not None else ""
    return s if s and s != "nan" else None


def _gelijk_dec(a: Decimal | None, b: Decimal | None) -> bool:
    if a is None and b is None:
        return True
    if a is None or b is None:
        # 0 en None zijn functioneel gelijk (formule-coëfficiënt afwezig)
        nul = Decimal("0")
        if (a is None and b == nul) or (b is None and a == nul):
            return True
        return False
    return abs(a - b) <= _drempel_voor(a, b)


def _drempel_voor(a: Decimal, b: Decimal) -> Decimal:
    # Relatieve drempel: 0,0001 % van de grootste waarde
    grootte = max(abs(a), abs(b), Decimal("1"))
    return grootte * Decimal("0.000001")


def _gelijk_txt(a: str | None, b: str | None) -> bool:
    return (a or "").strip() == (b or "").strip()


def _lijn(char: str = "─", breedte: int = _BREEDTE) -> str:
    return char * breedte


def _kop(tekst: str) -> str:
    return f"\n─── {tekst} {'─' * max(0, _BREEDTE - len(tekst) - 5)}"


# ── dataklassen ──────────────────────────────────────────────────────────────

@dataclass
class ComponentRij:
    component_code: str
    component_label: str | None
    prijs: Decimal | None
    a: Decimal | None
    b: Decimal | None
    c: Decimal | None
    d: Decimal | None
    z: Decimal | None
    index_naam_a: str | None
    index_naam_b: str | None
    index_naam_c: str | None
    index_naam_d: str | None
    index_waarde_a: Decimal | None
    index_waarde_b: Decimal | None
    index_waarde_c: Decimal | None
    index_waarde_d: Decimal | None
    # Alleen in DB:
    eenheid: str | None = None
    btw_code: str | None = None


@dataclass
class ContractSleutel:
    leverancier: str
    product: str
    jaar: int
    maand: int
    segment: str
    energie_type: str
    contract_richting: str
    bron_type: str
    version_id: str


# ── CSV ophalen ───────────────────────────────────────────────────────────────

def _laad_csv_versie(version_id: str, settings: Settings) -> tuple[Path, Path]:
    staging = settings.data_root / "staging" / version_id / "vtest"
    vast    = staging / "master_vast.csv"
    var_dyn = staging / "master_var_dyn.csv"
    if not vast.is_file() or not var_dyn.is_file():
        sys.exit(f"CSV-bestanden niet gevonden in {staging}")
    return vast, var_dyn


def _lees_csv(vast: Path, var_dyn: Path) -> pd.DataFrame:
    frames = []
    for p in (vast, var_dyn):
        df = pd.read_csv(p, sep=_SEP, dtype=str, encoding=_ENC).fillna("")
        frames.append(df)
    return pd.concat(frames, ignore_index=True)


def _filter_csv(df: pd.DataFrame, sleutel: ContractSleutel) -> pd.DataFrame:
    mask = (
        (df["supplier"] == sleutel.leverancier)
        & (df["product"]  == sleutel.product)
        & (df["year"].apply(lambda v: int(v) if v else 0) == sleutel.jaar)
        & (df["month"].apply(lambda v: int(v) if v else 0) == sleutel.maand)
        & (df["segment"]   == sleutel.segment)
        & (df["energy"]    == sleutel.energie_type)
        & (df["direction"] == sleutel.contract_richting)
    )
    return df[mask].copy()


def _csv_naar_componenten(frame: pd.DataFrame) -> list[ComponentRij]:
    out = []
    for _, r in frame.iterrows():
        out.append(ComponentRij(
            component_code  = _str(r.get("component")) or "",
            component_label = _str(r.get("component_label")),
            prijs           = _dec(r.get("price")),
            a               = _dec(r.get("a")),
            b               = _dec(r.get("b")),
            c               = _dec(r.get("c")),
            d               = _dec(r.get("d")),
            z               = _dec(r.get("z")),
            index_naam_a    = _str(r.get("index_name_A")),
            index_naam_b    = _str(r.get("index_name_B")),
            index_naam_c    = _str(r.get("index_name_C")),
            index_naam_d    = _str(r.get("index_name_D")),
            index_waarde_a  = _dec(r.get("index_value_A")),
            index_waarde_b  = _dec(r.get("index_value_B")),
            index_waarde_c  = _dec(r.get("index_value_C")),
            index_waarde_d  = _dec(r.get("index_value_D")),
        ))
    return out


# ── DB ophalen ────────────────────────────────────────────────────────────────

def _haal_db_contract(engine: sa.Engine, sleutel: ContractSleutel) -> list[ComponentRij]:
    query = sa.text("""
        SELECT
            pc.component_code,
            pc.component_label,
            pc.eenheid,
            pc.btw_code,
            pc.prijs,
            pc.a, pc.b, pc.c, pc.d, pc.z,
            pc.index_naam_a, pc.index_naam_b, pc.index_naam_c, pc.index_naam_d,
            pc.index_waarde_a, pc.index_waarde_b, pc.index_waarde_c, pc.index_waarde_d
        FROM leverancier_product lp
        JOIN product_component pc ON pc.leverancier_product_id = lp.id
        WHERE lp.version_id       = :versie
          AND lp.leverancier      = :leverancier
          AND lp.product          = :product
          AND lp.jaar             = :jaar
          AND lp.maand            = :maand
          AND lp.segment          = :segment
          AND lp.energie_type     = :energie
          AND lp.contract_richting = :richting
        ORDER BY pc.id
    """)
    with engine.connect() as conn:
        rows = conn.execute(query, {
            "versie":      sleutel.version_id,
            "leverancier": sleutel.leverancier,
            "product":     sleutel.product,
            "jaar":        sleutel.jaar,
            "maand":       sleutel.maand,
            "segment":     sleutel.segment,
            "energie":     sleutel.energie_type,
            "richting":    sleutel.contract_richting,
        }).fetchall()

    return [
        ComponentRij(
            component_code  = r.component_code,
            component_label = r.component_label,
            eenheid         = r.eenheid,
            btw_code        = r.btw_code,
            prijs           = Decimal(str(r.prijs))  if r.prijs  is not None else None,
            a               = Decimal(str(r.a))      if r.a      is not None else None,
            b               = Decimal(str(r.b))      if r.b      is not None else None,
            c               = Decimal(str(r.c))      if r.c      is not None else None,
            d               = Decimal(str(r.d))      if r.d      is not None else None,
            z               = Decimal(str(r.z))      if r.z      is not None else None,
            index_naam_a    = r.index_naam_a,
            index_naam_b    = r.index_naam_b,
            index_naam_c    = r.index_naam_c,
            index_naam_d    = r.index_naam_d,
            index_waarde_a  = Decimal(str(r.index_waarde_a)) if r.index_waarde_a is not None else None,
            index_waarde_b  = Decimal(str(r.index_waarde_b)) if r.index_waarde_b is not None else None,
            index_waarde_c  = Decimal(str(r.index_waarde_c)) if r.index_waarde_c is not None else None,
            index_waarde_d  = Decimal(str(r.index_waarde_d)) if r.index_waarde_d is not None else None,
        )
        for r in rows
    ]


# ── willekeurig contract kiezen ───────────────────────────────────────────────

def _kies_willekeurig(engine: sa.Engine, version_id: str) -> tuple[str, str, int, int, str, str, str, str]:
    query = sa.text("""
        SELECT leverancier, product, jaar, maand, segment, energie_type, contract_richting, bron_type
        FROM leverancier_product
        WHERE version_id = :versie
        ORDER BY random()
        LIMIT 1
    """)
    with engine.connect() as conn:
        row = conn.execute(query, {"versie": version_id}).fetchone()
    if not row:
        sys.exit(f"Geen contracts gevonden voor versie {version_id!r}.")
    return row.leverancier, row.product, row.jaar, row.maand, row.segment, row.energie_type, row.contract_richting, row.bron_type


def _actieve_versie(engine: sa.Engine) -> str:
    query = sa.text("""
        SELECT version_id FROM data_version
        WHERE geimporteerd_op IS NOT NULL
        ORDER BY geimporteerd_op DESC
        LIMIT 1
    """)
    with engine.connect() as conn:
        row = conn.execute(query).fetchone()
    if not row:
        sys.exit("Geen geïmporteerde versie gevonden in de databank.")
    return row.version_id


# ── vergelijking ──────────────────────────────────────────────────────────────

@dataclass
class VeldResultaat:
    veld: str
    csv_waarde: str
    db_waarde: str
    ok: bool


@dataclass
class ComponentResultaat:
    code: str
    label: str | None
    eenheid: str | None
    btw_code: str | None
    velden: list[VeldResultaat]
    alleen_in_csv: bool = False
    alleen_in_db: bool = False

    @property
    def ok(self) -> bool:
        return not self.alleen_in_csv and not self.alleen_in_db and all(v.ok for v in self.velden)


def _vergelijk(csv_comps: list[ComponentRij], db_comps: list[ComponentRij]) -> list[ComponentResultaat]:
    resultaten: list[ComponentResultaat] = []

    csv_index = {c.component_code: c for c in csv_comps}
    db_index  = {c.component_code: c for c in db_comps}

    alle_codes = list(csv_index.keys())
    for code in db_index:
        if code not in csv_index:
            alle_codes.append(code)

    for code in alle_codes:
        csv_r = csv_index.get(code)
        db_r  = db_index.get(code)

        if csv_r is None:
            resultaten.append(ComponentResultaat(
                code=code, label=db_r.component_label,
                eenheid=db_r.eenheid, btw_code=db_r.btw_code,
                velden=[], alleen_in_db=True,
            ))
            continue
        if db_r is None:
            resultaten.append(ComponentResultaat(
                code=code, label=csv_r.component_label,
                eenheid=None, btw_code=None,
                velden=[], alleen_in_csv=True,
            ))
            continue

        velden: list[VeldResultaat] = []

        # Numerieke velden
        for csv_naam, db_naam in _NUM_VELDEN:
            csv_val = getattr(csv_r, db_naam)
            db_val  = getattr(db_r,  db_naam)
            ok = _gelijk_dec(csv_val, db_val)
            if not ok or (csv_val is not None and csv_val != Decimal("0")):
                velden.append(VeldResultaat(
                    veld      = db_naam,
                    csv_waarde= _fmt_dec(csv_val),
                    db_waarde = _fmt_dec(db_val),
                    ok        = ok,
                ))

        # Tekstvelden
        for csv_naam, db_naam in _TXT_VELDEN:
            csv_val = getattr(csv_r, db_naam)
            db_val  = getattr(db_r,  db_naam)
            ok = _gelijk_txt(csv_val, db_val)
            if not ok or csv_val:
                velden.append(VeldResultaat(
                    veld      = db_naam,
                    csv_waarde= csv_val or "",
                    db_waarde = db_val  or "",
                    ok        = ok,
                ))

        resultaten.append(ComponentResultaat(
            code     = code,
            label    = db_r.component_label or csv_r.component_label,
            eenheid  = db_r.eenheid,
            btw_code = db_r.btw_code,
            velden   = velden,
        ))

    return resultaten


def _fmt_dec(v: Decimal | None, breedte: int = 10) -> str:
    if v is None:
        return "—"
    s = f"{v:.6f}".rstrip("0").rstrip(".")
    return s.rjust(breedte)


# ── rapport afdrukken ────────────────────────────────────────────────────────

def _druk_rapport(
    sleutel: ContractSleutel,
    resultaten: list[ComponentResultaat],
    csv_teller: int,
    db_teller: int,
) -> int:
    """Druk het rapport af en geef de exitcode terug (0 = ok, 1 = fouten)."""

    afwijkingen = sum(1 for r in resultaten if not r.ok)
    status_totaal = _OK if afwijkingen == 0 else _NOK

    print()
    print("╔" + "═" * (_BREEDTE - 2) + "╗")
    print(f"║  CONTRACTCONTROLE  ·  CSV ↔ Databank{' ' * (_BREEDTE - 38)}║")
    print("╚" + "═" * (_BREEDTE - 2) + "╝")
    print()
    print(f"  Contract   : {sleutel.leverancier} / {sleutel.product}")
    print(f"  Energie    : {sleutel.energie_type} · {sleutel.contract_richting}")
    print(f"  Segment    : {sleutel.segment}")
    print(f"  Type       : {sleutel.bron_type}")
    print(f"  Periode    : {sleutel.jaar}-{sleutel.maand:02d}")
    print(f"  Versie     : {sleutel.version_id}")
    print(f"  Componenten: {csv_teller} in CSV  ·  {db_teller} in DB")

    print(_kop("COMPONENTEN"))
    print()

    for comp in resultaten:
        vlag = _OK if comp.ok else _NOK
        eenheid  = comp.eenheid  or "?"
        btw_code = comp.btw_code or "?"

        if comp.alleen_in_csv:
            print(f"  {_NOK}  {comp.code:<22}  → alleen in CSV, niet in DB")
            continue
        if comp.alleen_in_db:
            print(f"  {_NOK}  {comp.code:<22}  → alleen in DB, niet in CSV")
            continue

        # Koptitel van de component
        label_kort = (comp.label or "")[:35]
        print(f"  {vlag}  {comp.code:<22}  {label_kort}")
        print(f"     Eenheid: {eenheid:<12}  BTW: {btw_code}")

        for v in comp.velden:
            vlag_v = _OK if v.ok else _NOK
            print(f"       {vlag_v} {v.veld:<18} CSV: {v.csv_waarde:<14}  DB: {v.db_waarde:<14}", end="")
            if not v.ok:
                print(f"  ← AFWIJKING")
            else:
                print()

        if not comp.velden:
            print("       (geen vergelijkbare velden met waarden)")
        print()

    print(_lijn())
    print(f"  Componenten : {len(resultaten)} vergeleken  ({csv_teller} CSV / {db_teller} DB)")
    print(f"  Afwijkingen : {afwijkingen}")
    print(f"  Status      : {status_totaal}  {'ALLES OK' if afwijkingen == 0 else 'CONTROLEER DE AFWIJKINGEN HIERBOVEN'}")
    print(_lijn())
    print()

    return 0 if afwijkingen == 0 else 1


# ── main ──────────────────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Vergelijkt een energiecontract rij voor rij tussen CSV en DB.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--leverancier", help="Leveranciersnaam (exact)")
    p.add_argument("--product",     help="Productnaam (exact)")
    p.add_argument("--jaar",    type=int, default=None)
    p.add_argument("--maand",   type=int, default=None)
    p.add_argument("--segment", default=None, help='bv. "Woning" of "Onderneming"')
    p.add_argument("--energie", default=None, help='bv. "Elektriciteit" of "Gas"')
    p.add_argument("--richting", default=None, help='"Afname" of "Injectie"')
    p.add_argument("--versie", default=None, help="version_id (standaard: meest recent geïmporteerd)")
    return p.parse_args()


def main() -> None:
    args = _parse_args()
    settings = Settings.load()
    engine = get_engine(settings.project_root)

    # Versie bepalen
    version_id = args.versie or _actieve_versie(engine)

    # Contract bepalen
    willekeurig = not any([args.leverancier, args.product, args.jaar, args.maand, args.segment])
    if willekeurig:
        lev, prod, jaar, maand, seg, energie, richting, bron_type = _kies_willekeurig(engine, version_id)
    else:
        if not args.leverancier or not args.product:
            sys.exit("Geef --leverancier en --product op, of gebruik geen argumenten voor een willekeurig contract.")
        lev     = args.leverancier
        prod    = args.product
        jaar    = args.jaar    or 2025
        maand   = args.maand   or 1
        seg     = args.segment or "Woning"
        energie = args.energie or "Elektriciteit"
        richting = args.richting or "Afname"

        # bron_type opzoeken in DB
        with engine.connect() as conn:
            row = conn.execute(sa.text("""
                SELECT bron_type FROM leverancier_product
                WHERE version_id=:v AND leverancier=:l AND product=:p
                  AND jaar=:j AND maand=:m AND segment=:s
                  AND energie_type=:e AND contract_richting=:r
                LIMIT 1
            """), {"v": version_id, "l": lev, "p": prod, "j": jaar, "m": maand,
                   "s": seg, "e": energie, "r": richting}).fetchone()
        bron_type = row.bron_type if row else "onbekend"

    sleutel = ContractSleutel(
        leverancier=lev, product=prod, jaar=jaar, maand=maand,
        segment=seg, energie_type=energie, contract_richting=richting,
        bron_type=bron_type, version_id=version_id,
    )

    # Data laden
    vast, var_dyn = _laad_csv_versie(version_id, settings)
    alle_csv = _lees_csv(vast, var_dyn)
    csv_frame = _filter_csv(alle_csv, sleutel)

    if csv_frame.empty:
        print(f"\n{_NOK}  Contract niet gevonden in CSV-bestanden.", file=sys.stderr)
        print(f"   Leverancier : {lev}", file=sys.stderr)
        print(f"   Product     : {prod}", file=sys.stderr)
        sys.exit(2)

    csv_comps = _csv_naar_componenten(csv_frame)
    db_comps  = _haal_db_contract(engine, sleutel)

    if not db_comps:
        print(f"\n{_NOK}  Contract niet gevonden in de databank.", file=sys.stderr)
        sys.exit(2)

    resultaten = _vergelijk(csv_comps, db_comps)
    exitcode = _druk_rapport(sleutel, resultaten, len(csv_comps), len(db_comps))
    sys.exit(exitcode)


if __name__ == "__main__":
    main()
