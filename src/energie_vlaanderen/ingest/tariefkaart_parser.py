"""De feitelijke gegevens uit een tariefkaart halen.

WAAROM
------
Het archief bewaart de kaarten; dit leest ze. Wat erin staat is precies wat de
V-test-export niet geeft: de **bevroren** formule van een lopend contract. De
export levert per maand de kaart die op dat moment verkocht wordt, en die twee
lopen uiteen — op een echte Eneco-afrekening 11,74 EUR per jaar aan vaste
vergoeding, en bij ENGIE "Direct Online" ook de indexcoëfficiënt (0,0954
tegenover 0,0996).

DRIE SCHRIJFWIJZEN, EN DAT IS ALLES
-----------------------------------
Achtentwintig leveranciers, achtentwintig opmaken — maar de formule zelf komt
in drie vormen voor, en meer zijn het er niet:

    A   0,102 X BELPEX-RLP-M + 3,001      coëfficiënt eerst   (Eneco, Ebem)
    B   Belpex * 1,168 + 16,90            index eerst         (Bolt, OCTA+)
    C   -1,5470 + (0,0449 x EPEXDAM)      constante eerst     (ENGIE)

DE EENHEID IS HET GEVAARLIJKE DEEL
----------------------------------
`0,102 x BELPEX-RLP-M + 3,001` levert €cent/kWh, `Belpex * 1,168 + 16,90`
levert €/MWh. Dat is een factor tien, en op een kaart staat het er soms alleen
in de kolomkop of in een voetnoot bij. Een formule zonder herkende eenheid
wordt daarom **niet genormaliseerd** maar ruw doorgegeven met `eenheid = ""`:
een verkeerd omgerekend getal is erger dan een onomgerekend getal, want het
eerste ziet er plausibel uit.

Hetzelfde voor btw. Eneco drukt `(...) X 1,06` af — de kaart is inclusief 6%,
de databank exclusief. Dat staat als vlag naast de waarde en wordt niet stil
weggedeeld.

WAT DIT NIET DOET
-----------------
Beslissen. De parser levert kandidaten met hun ruwe regel erbij; wat ervan
klopt, blijkt uit de toets tegen `tarief_afname` — daar staan dezelfde
coëfficiënten voor de maand van de kaart. Waar ze overeenkomen is de lezing
bevestigd; waar ze verschillen is er iets te onderzoeken. Dat oordeel hoort
niet in een regex.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Optional

# De indexnamen zoals ze op kaarten voorkomen. Bewust een woordenlijst en geen
# "elk hoofdlettergroepje": zonder anker matcht een regex vrolijk op "BTW" of
# "MWh" en levert een formule op die niet bestaat.
INDEXWOORDEN = (
    "belpex", "epex", "endex", "ztp", "ttf", "zeebrugge", "apx", "icis",
)
_INDEX = r"[A-Za-z0-9][A-Za-z0-9\s.\-_/']{0,38}?"

_GETAL = r"-?\d{1,3}(?:[.,]\d{1,6})?"

# A: coëfficiënt, index, constante — met of zonder maalteken.
_VORM_A = re.compile(
    rf"(?P<a>{_GETAL})\s*[xX*×·]?\s*(?P<index>{_INDEX})\s*(?P<teken>[+\-–])\s*(?P<z>{_GETAL})"
)
# B: index, coëfficiënt, constante.
_VORM_B = re.compile(
    rf"(?P<index>{_INDEX})\s*[xX*×·]\s*(?P<a>{_GETAL})\s*(?P<teken>[+\-–])\s*(?P<z>{_GETAL})"
)
# C: constante eerst, formule tussen haakjes.
_VORM_C = re.compile(
    rf"(?P<z>{_GETAL})\s*(?P<teken>[+\-–])\s*\(\s*(?P<a>{_GETAL})\s*[xX*×·]\s*(?P<index>{_INDEX})\s*\)"
)

_EENHEDEN = (
    (re.compile(r"€\s*cent\s*/\s*kwh|c€\s*/\s*kwh|€cent/kwh|cent\s*/\s*kwh", re.I), "ct/kWh"),
    (re.compile(r"€\s*/\s*mwh|eur\s*/\s*mwh", re.I), "EUR/MWh"),
    (re.compile(r"€\s*/\s*kwh|eur\s*/\s*kwh", re.I), "EUR/kWh"),
)
_BTW_INCL = re.compile(r"incl\w*\.?\s*(?:6\s*%\s*)?btw|inclusief\s+6?\s*%?\s*btw|[x×]\s*1[.,]06", re.I)
_BTW_EXCL = re.compile(r"ex(?:cl)?\w*\.?\s*btw|exclusief\s+btw", re.I)

_REGISTERS = (
    (re.compile(r"uitsluitend\s+nacht|exclusief\s+nacht|excl\.?\s*nacht", re.I), "exclusief_nacht"),
    (re.compile(r"injectie|terugleve", re.I), "injectie"),
    (re.compile(r"\bnacht\b|\bdal\b", re.I), "nacht"),
    (re.compile(r"\bdag\b|\bpiek\b", re.I), "dag"),
    (re.compile(r"enkelvoudig|enkele\s+teller|mono", re.I), "enkelvoudig"),
)

_MAANDEN = {
    "januari": 1, "februari": 2, "maart": 3, "april": 4, "mei": 5, "juni": 6,
    "juli": 7, "augustus": 8, "september": 9, "oktober": 10, "november": 11,
    "december": 12,
}
_KAARTMAAND = re.compile(
    r"tariefkaart\s+(?:van\s+)?(" + "|".join(_MAANDEN) + r")\s+(20\d{2})", re.I
)


@dataclass
class Formule:
    """Eén prijsformule zoals ze op de kaart staat."""

    a: Decimal
    index_naam: str
    z: Decimal
    eenheid: str
    btw: str          # "incl" | "excl" | "" (onbekend)
    register: str     # "" wanneer niet af te leiden
    vorm: str         # A, B of C
    regel: str        # de ruwe regel, zodat elk cijfer terug te vinden is

    def as_dict(self) -> dict:
        return {
            "a": str(self.a), "index_naam": self.index_naam, "z": str(self.z),
            "eenheid": self.eenheid, "btw": self.btw, "register": self.register,
            "vorm": self.vorm, "regel": self.regel,
        }


@dataclass
class Kaartinhoud:
    kaartmaand: str = ""
    vaste_vergoeding: list[dict] = field(default_factory=list)
    formules: list[Formule] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "kaartmaand": self.kaartmaand,
            "vaste_vergoeding": self.vaste_vergoeding,
            "formules": [f.as_dict() for f in self.formules],
        }


def _decimaal(tekst: str) -> Optional[Decimal]:
    try:
        return Decimal(tekst.replace(".", "").replace(",", ".")
                       if tekst.count(",") == 1 and "." in tekst
                       else tekst.replace(",", "."))
    except (InvalidOperation, AttributeError):
        return None


def _eenheid_van(regel: str, omgeving: str) -> str:
    """De eenheid uit de regel zelf, anders uit de omliggende tekst.

    De regel eerst: een kolomkop verderop kan over een andere kolom gaan.
    """
    for bron in (regel, omgeving):
        for patroon, naam in _EENHEDEN:
            if patroon.search(bron):
                return naam
    return ""


def _btw_van(regel: str, omgeving: str) -> str:
    for bron in (regel, omgeving):
        if _BTW_INCL.search(bron):
            return "incl"
        if _BTW_EXCL.search(bron):
            return "excl"
    return ""


def _register_van(regel: str) -> str:
    for patroon, naam in _REGISTERS:
        if patroon.search(regel):
            return naam
    return ""


def _lijkt_index(tekst: str) -> bool:
    return any(woord in tekst.casefold() for woord in INDEXWOORDEN)


def parse_kaart(tekst: str, *, omgevingsregels: int = 8) -> Kaartinhoud:
    """Lees een tariefkaart (de tekstlaag van de PDF) uit.

    `omgevingsregels` bepaalt hoeveel regels eromheen meetellen voor de eenheid
    en de btw-vlag: die staan zelden op dezelfde regel als de formule zelf maar
    bijna altijd in de kolomkop erboven. Acht regels, want `pdftotext -layout`
    houdt een tabel breed en zet de kop een heel eind boven de cel.
    """
    inhoud = Kaartinhoud()

    maand = _KAARTMAAND.search(tekst)
    if maand:
        inhoud.kaartmaand = f"{maand.group(2)}-{_MAANDEN[maand.group(1).casefold()]:02d}"

    # Twee wegen naar de vaste vergoeding, want ze staat op twee manieren op de
    # kaarten. Soms als "22,83€/jaar" op één regel; soms als kolomkop
    # "VASTE VERGOEDING (€/jaar)" met het bedrag een paar regels lager in een
    # tabel. Alleen de eerste zoeken levert bij Eneco de administratiekost van
    # het energiedelen op (124,63 €/jaar) in plaats van de 65,00 die gevraagd
    # was — een bedrag dat er staat, maar niet dít bedrag.
    for match in re.finditer(
        r"(\d{1,3}(?:[.,]\d{1,4})?)\s*(?:€|EUR)\s*/\s*(?:jaar|an|year)", tekst, re.I
    ):
        waarde = _decimaal(match.group(1))
        if waarde is None:
            continue
        regel = _regel_rond(tekst, match.start())
        inhoud.vaste_vergoeding.append({
            "waarde": str(waarde), "btw": _btw_van(regel, tekst[:2000]),
            "herkomst": "naast €/jaar", "regel": regel,
        })
    # Onder de kop staan meerdere getallen naast elkaar — bij Eneco het
    # verbruikstarief (17,67) én de vaste vergoeding (65,00), want
    # `pdftotext -layout` houdt de kolommen naast elkaar maar niet uit elkaar.
    # Er wordt daarom niet één getal gekozen maar een handvol *kandidaten*
    # doorgegeven. Welke het is, blijkt uit de toets tegen `tarief_afname`;
    # hier gokken zou een bedrag opleveren dat er staat maar iets anders
    # betekent.
    for match in re.finditer(r"vaste\s+vergoeding", tekst, re.I):
        venster = tekst[match.end():match.end() + 900]
        for getal in list(re.finditer(r"(?<![\d,.])(\d{1,3}[.,]\d{2})(?![\d.,])", venster))[:6]:
            waarde = _decimaal(getal.group(1))
            if waarde is None or any(
                v["waarde"] == str(waarde) for v in inhoud.vaste_vergoeding
            ):
                continue
            inhoud.vaste_vergoeding.append({
                "waarde": str(waarde),
                "btw": _btw_van(venster[:300], tekst[:2000]),
                "herkomst": "kandidaat onder de kop 'vaste vergoeding'",
                "regel": _regel_rond(tekst, match.end() + getal.start()),
            })

    regels = tekst.splitlines()
    for nummer, regel in enumerate(regels):
        if not _lijkt_index(regel):
            continue
        omgeving = "\n".join(
            regels[max(0, nummer - omgevingsregels):nummer + omgevingsregels + 1]
        )
        for vorm, patroon in (("C", _VORM_C), ("B", _VORM_B), ("A", _VORM_A)):
            gevonden = False
            for match in patroon.finditer(regel):
                index_naam = " ".join(match.group("index").split()).strip(" .-_")
                if not _lijkt_index(index_naam):
                    continue
                a, z = _decimaal(match.group("a")), _decimaal(match.group("z"))
                if a is None or z is None or a == 0:
                    continue
                if match.group("teken") in "-–":
                    z = -z
                inhoud.formules.append(Formule(
                    a=a, index_naam=index_naam, z=z,
                    eenheid=_eenheid_van(regel, omgeving),
                    btw=_btw_van(regel, omgeving),
                    register=_register_van(regel) or _register_van(omgeving),
                    vorm=vorm, regel=" ".join(regel.split())[:200],
                ))
                gevonden = True
            # De vormen sluiten elkaar uit binnen één regel: C herkent wat B en
            # A ook half zouden matchen, en dan zou dezelfde formule er drie
            # keer in staan.
            if gevonden:
                break

    return inhoud


def _regel_rond(tekst: str, positie: int) -> str:
    begin = tekst.rfind("\n", 0, positie) + 1
    einde = tekst.find("\n", positie)
    return " ".join(tekst[begin:einde if einde > 0 else len(tekst)].split())[:200]


def lees_pdf(pad) -> str:
    """De tekstlaag van een PDF, via pdftotext.

    `-layout` en niet de leesvolgorde: een tariefkaart is een tabel, en zonder
    layout belanden de coëfficiënt en zijn kolomkop tientallen regels uit
    elkaar.
    """
    import subprocess

    uitslag = subprocess.run(  # noqa: S603 - vaste argumenten, geen shell
        ["pdftotext", "-layout", str(pad), "-"],
        capture_output=True, text=True,
    )
    if uitslag.returncode != 0:
        raise RuntimeError(f"pdftotext mislukte op {pad}: {uitslag.stderr[:200]}")
    return uitslag.stdout
