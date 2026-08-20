from pathlib import Path
import pandas as pd

def validate_excel_against_csv(xlsx:Path,csv_path:Path,energy:str)->dict:
    """Leest officiële VNR Excel en voert sanity checks uit tegen genormaliseerde CSV."""
    sheets=pd.ExcelFile(xlsx,engine="openpyxl").sheet_names
    raw=pd.read_excel(xlsx,sheet_name=0,header=None,engine="openpyxl")
    flat=" ".join(raw.astype(str).fillna("").values.ravel())
    required=["2026","Exclusief btw"]
    if energy=="elektriciteit": required += ["Capaciteitstarief","Digitale meter"]
    else: required += ["AARDGAS","Proportionele term"]
    missing=[x for x in required if x.casefold() not in flat.casefold()]
    cdf=pd.read_csv(csv_path,sep=";",dtype=str,encoding="utf-8-sig")
    return {"workbook":xlsx.name,"sheets":len(sheets),"csv_rows":len(cdf),"missing_markers":missing,"ok":not missing and len(cdf)>0}
