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
    # Baarle-Hertog (2387, uitgezonderd Zondereigen) is een Belgische enclave
    # in Nederland en krijgt zijn aardgas van Enexis, niet van Fluvius. De
    # tarieven staan in een eigen werkboek ("Enexis aardgas <jaar> —
    # goedgekeurd door ACM") dat deze pipeline niet inleest.
    #
    # De code staat hier zodat de netbeheerder herkend wordt in plaats van
    # als onbekende naam door te lopen. Er zijn echter géén tarieven voor:
    # een gasberekening voor 2387 vindt niets en hoort te stoppen, niet
    # stilzwijgend een Fluvius-tarief te gebruiken.
    "Enexis Netbeheer": "ENEXIS",
}

# Netbeheerders waarvoor we wel de gemeente kennen maar niet de tarieven.
DNB_ZONDER_TARIEVEN = frozenset({"ENEXIS"})
MONTHS = {"jan":1,"feb":2,"mrt":3,"mar":3,"apr":4,"mei":5,"jun":6,
          "jul":7,"aug":8,"sep":9,"okt":10,"nov":11,"dec":12}
