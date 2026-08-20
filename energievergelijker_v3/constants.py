from decimal import Decimal
from zoneinfo import ZoneInfo

D = Decimal
CENT = D("0.01")
LOCAL_TZ = ZoneInfo("Europe/Brussels")
UTC = ZoneInfo("UTC")
BE_DOMAIN = "10YBE----------2"
DNB_CODES = {
    "Fluvius Antwerpen": "FA", "Fluvius Halle-Vilvoorde": "FHV",
    "Fluvius Imewo": "FI", "Fluvius Kempen": "FK", "Fluvius Limburg": "FL",
    "Fluvius Midden-Vlaanderen": "FMV", "Fluvius West": "FW",
    "Fluvius Zenne-Dijle": "FZD",
}
MONTHS = {"jan":1,"feb":2,"mrt":3,"mar":3,"apr":4,"mei":5,"jun":6,
          "jul":7,"aug":8,"sep":9,"okt":10,"nov":11,"dec":12}
