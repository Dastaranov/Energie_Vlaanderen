"""Het archief van tariefkaarten: de documenten die leveranciers vervangen.

WAAROM DIT BESTAAT
------------------
Een variabel contract bevriest bij ondertekening zijn **formule**, niet zijn
prijs: de vaste vergoeding en de coëfficiënten liggen vast in de kaartversie
die de klant tekende, en alleen de index beweegt nog. De V-test-export levert
per maand de kaart die op dat moment *verkocht* wordt. Die twee lopen uiteen
zodra een contract een tijdje loopt, en dat is meetbaar: op een echte
Eneco-afrekening scheelde alleen al de vaste vergoeding 11,74 EUR per jaar
(61,321 in de export tegenover 49,59 op de kaart van de klant), en bij ENGIE
"Direct Online" week bovendien de indexcoëfficiënt af (0,0954 tegenover
0,0996).

Het verschil tussen die twee is niet met code te overbruggen — het is een
gegeven dat we niet hebben. En anders dan de index, die uit de day-ahead
historiek altijd nog terug te rekenen valt, is een tariefkaart **weg zodra de
leverancier hem vervangt**. Vandaag archiveren is de enige manier om een
contract van vandaag over drie jaar nog exact na te rekenen.

Sommige leveranciers houden zelf een kaartarchief bij. Dat is per leverancier
te bekijken en verandert niets aan deze module: wat hier staat is wat wij op
het moment van waarnemen zelf gezien hebben, met een hash erbij.

HOE
---
`vtest_contract.link_tariefkaart` draagt de URL — voor 351 van de 364
contracten — en die tabel heeft sinds migratie 0019 een eigen tijdas. Deze
module haalt die documenten op en legt ze **inhoudsgeadresseerd** weg: het pad
is de SHA-256 van de inhoud. Dat lost twee dingen tegelijk op. Leveranciers
delen één kaart over meerdere producten, dus hetzelfde document komt langs
meerdere URL's binnen en wordt één keer bewaard. En een kaart die *wijzigt*
krijgt vanzelf een nieuw pad, zodat de oude versie blijft staan — precies wat
een archief moet doen.

Het register (`index.json`) is geen kopie van de databank maar de waarneming:
per (contract, URL, inhoud) wanneer we hem voor het eerst en voor het laatst
zo gezien hebben. Mislukte pogingen staan er even goed in. Een leverancier die
zijn kaart achter een aanmeldpagina zet levert namelijk gewoon HTML op, en dat
stil als "kaart" bewaren zou het archief onbetrouwbaar maken zonder dat iets
faalt.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Iterable, Optional
from urllib.parse import urlparse

LOG = logging.getLogger(__name__)

PDF_MAGIC = b"%PDF-"

# De PDF-kop hoeft niet op byte 0 te staan. ISO 32000-1 §7.5.2 zet hem op de
# eerste regel, maar staat lezers toe hem binnen de eerste 1024 bytes te zoeken,
# en dat doen ze ook allemaal. Luminus levert zijn kaarten met een UTF-8 BOM
# ervoor: `\xef\xbb\xbf%PDF-1.4`. Een toets op byte 0 wees daardoor 35 geldige
# kaarten af als "geen PDF" — een echte tariefkaart van 214 kB die pdfinfo en
# pdftotext zonder morren lezen. De offset wordt bewaard, want een BOM voor een
# PDF blijft een eigenaardigheid die je wil kunnen terugvinden.
MAX_KOP_OFFSET = 1024

# Ruim boven wat een tariefkaart ooit is (de grootste die we zagen is 1,4 MB)
# en ruim onder wat een vergissing kan aanrichten. De algemene
# `max_download_bytes` van 100 MiB is voor de Synergrid-werkboeken bedoeld en
# hier veel te ruim.
MAX_KAART_BYTES = 25 * 1024 * 1024

# Eén verzoek per halve seconde. Dit zijn 350 losse leverancierssites en geen
# API; er is geen haast bij en er is geen reden om erop te hameren.
STANDAARD_PAUZE_SECONDEN = 0.5

USER_AGENT = (
    "energievergelijker/1.0 (tariefkaartarchief; "
    "https://github.com/Dastaranov/Energie_Vlaanderen)"
)


class TariefkaartError(RuntimeError):
    """Een tariefkaart kon niet veilig gearchiveerd worden."""


@dataclass(frozen=True)
class Kaartbron:
    """Eén tariefkaart-URL zoals de databank hem kent."""

    vreg_id: str
    leverancier: str
    product: str
    energie_type: str
    url: str


@dataclass
class Rapport:
    nieuw: int = 0
    ongewijzigd: int = 0
    gewijzigd: int = 0
    mislukt: int = 0
    fouten: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "nieuw": self.nieuw,
            "ongewijzigd": self.ongewijzigd,
            "gewijzigd": self.gewijzigd,
            "mislukt": self.mislukt,
            "fouten": self.fouten,
        }


def bronnen_uit_databank(conn) -> list[Kaartbron]:
    """De tariefkaart-URL's van de **lopende** contractsnapshots.

    `geldig_tot is null` is de SCD2-betekenis "dit is de huidige beschrijving".
    Een afgesloten snapshot hoort bij een kaart die we destijds al gezien
    zouden moeten hebben; hem nu alsnog ophalen zou het huidige document onder
    een oude waarneming hangen, en dat is precies de fout die dit archief moet
    voorkomen.
    """
    import sqlalchemy as sa

    rijen = conn.execute(sa.text("""
        select vreg_id, coalesce(leverancier_raw, '') as leverancier,
               coalesce(product_raw, '') as product,
               coalesce(energie_type, '') as energie_type,
               link_tariefkaart
        from vtest_contract
        where geldig_tot is null
          and coalesce(link_tariefkaart, '') <> ''
        order by leverancier_raw, product_raw, vreg_id
    """)).mappings().all()
    return [
        Kaartbron(
            vreg_id=str(r["vreg_id"]),
            leverancier=r["leverancier"],
            product=r["product"],
            energie_type=r["energie_type"],
            url=r["link_tariefkaart"],
        )
        for r in rijen
    ]


def _plat(tekst: str) -> str:
    """Alleen letters en cijfers, kleingeschreven.

    "Agilior Online" en "agilioronline" zijn dezelfde kaart; de ene staat in de
    databank, de andere in het URL-pad van de leverancier.
    """
    return re.sub(r"[^a-z0-9]", "", (tekst or "").casefold())


def _is_gasachtig(tekst: str) -> bool:
    return bool(re.search(r"\bgas\b|_gas|aardgas", tekst, re.I))


def _is_elektrischachtig(tekst: str) -> bool:
    return bool(re.search(r"_el\b|_el_|\bel\b|elek|electric", tekst, re.I))


@dataclass(frozen=True)
class Kandidaat:
    url: str
    label: str


def kandidaten_uit_pagina(html: str, basis_url: str) -> list[Kandidaat]:
    """De links op een landingspagina die een tariefkaart kunnen zijn.

    Niet elke leverancier zet de kaart achter een rechtstreekse `.pdf`-URL.
    Sommige leveren hem via een eigen route (`/web/content/...` bij Odoo,
    `/website/getCurrentTariffchart/...` bij Energy Knights), en dan zegt de
    bestandsnaam niets. De ankertekst wél — daar staat "Tariefkaart_Flow_EL".
    """
    from bs4 import BeautifulSoup
    from urllib.parse import urljoin

    soep = BeautifulSoup(html, "html.parser")
    gezien: dict[str, Kandidaat] = {}
    for anker_element in soep.find_all("a", href=True):
        href = anker_element["href"]
        label = " ".join(anker_element.get_text(" ", strip=True).split())
        if not re.search(r"\.pdf|/web/content/|tariffchart|tarief|tariff",
                         f"{href} {label}", re.I):
            continue
        volledig = urljoin(basis_url, href)
        gezien.setdefault(volledig, Kandidaat(volledig, label))
    return list(gezien.values())


def kies_kandidaat(
    kandidaten: list[Kandidaat], product: str, energie_type: str
) -> tuple[Optional[Kandidaat], list[Kandidaat]]:
    """De kaart van dít product, of niets.

    Geeft (keuze, overwogen kandidaten) terug. **Bij twijfel geen keuze**: een
    verkeerde kaart in het archief is erger dan een ontbrekende. Het archief
    bestaat om een contract exact na te rekenen, en dan is de prijs van een
    gokje een bedrag dat klopt op de verkeerde formule.

    De overwogen kandidaten reizen mee naar het foutenregister, zodat het
    uitzoekwerk per leverancier een opzoeking is en geen heronderzoek.
    """
    doel = _plat(product)
    if not doel:
        return None, kandidaten
    gas = (energie_type or "").casefold() == "gas"

    treffers = []
    for kandidaat in kandidaten:
        hooiberg = f"{kandidaat.label} {kandidaat.url}"
        if doel not in _plat(hooiberg):
            continue
        # Een historiekpagina draagt oude kaarten. Die horen in dit archief
        # thuis, maar niet als "de huidige kaart van dit contract".
        if re.search(r"histor", hooiberg, re.I):
            continue
        gasachtig = _is_gasachtig(hooiberg)
        elektrischachtig = _is_elektrischachtig(hooiberg)
        if gas and elektrischachtig and not gasachtig:
            continue
        if not gas and gasachtig and not elektrischachtig:
            continue
        treffers.append(kandidaat)

    if len(treffers) == 1:
        return treffers[0], kandidaten
    return None, treffers or kandidaten


class TariefkaartArchief:
    """Haalt tariefkaarten op en legt ze inhoudsgeadresseerd weg."""

    def __init__(
        self,
        wortel: Path,
        *,
        timeout: float = 30.0,
        max_bytes: int = MAX_KAART_BYTES,
        pauze: float = STANDAARD_PAUZE_SECONDEN,
        bewaar_om: int = 25,
    ) -> None:
        self.wortel = Path(wortel)
        self.documenten = self.wortel / "documenten"
        self.register_pad = self.wortel / "index.json"
        self.timeout = timeout
        self.max_bytes = max_bytes
        self.pauze = pauze
        self.bewaar_om = max(1, int(bewaar_om))
        # Per run: 16 contracten van dezelfde leverancier delen één
        # overzichtspagina, en die hoeft niet 16 keer opgehaald te worden.
        self._paginas: dict[str, str] = {}

    # -- register ---------------------------------------------------------

    def lees_register(self) -> dict:
        if not self.register_pad.is_file():
            return {"kaarten": [], "fouten": []}
        try:
            return json.loads(self.register_pad.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            # Niet stil op leeg terugvallen: dan zou een beschadigd register
            # het hele archief opnieuw als "nieuw" aanmerken en de historiek
            # van eerste waarneming wissen.
            raise TariefkaartError(
                f"Register {self.register_pad} is onleesbaar: {exc}. "
                "Herstel of hernoem het bestand; automatisch overschrijven zou "
                "de waarnemingshistoriek wissen."
            ) from exc

    def schrijf_register(self, register: dict) -> None:
        self.wortel.mkdir(parents=True, exist_ok=True)
        tijdelijk = self.register_pad.with_suffix(".json.tijdelijk")
        tijdelijk.write_text(
            json.dumps(register, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        os.replace(tijdelijk, self.register_pad)

    # -- ophalen ----------------------------------------------------------

    def pad_voor(self, digest: str) -> Path:
        return self.documenten / digest[:2] / f"{digest}.pdf"

    def haal_op(self, url: str) -> tuple[str, int, str, int]:
        """Download één kaart.

        Geeft (sha256, bytes, content_type, kop_offset) terug; `kop_offset` is
        waar `%PDF-` begint en is normaal 0.
        """
        import requests

        self._controleer_url(url, "tariefkaart-URL")
        with requests.get(
            url,
            timeout=self.timeout,
            stream=True,
            allow_redirects=True,
            headers={"User-Agent": USER_AGENT, "Accept": "application/pdf,*/*"},
        ) as antwoord:
            antwoord.raise_for_status()
            # Een omleiding kan op http of op een heel andere host eindigen;
            # de eindbestemming is wat we werkelijk downloaden.
            self._controleer_url(antwoord.url, "eindbestemming na omleiding")
            content_type = (antwoord.headers.get("Content-Type") or "").split(";")[0].strip()

            hasher = sha256()
            aantal = 0
            self.documenten.mkdir(parents=True, exist_ok=True)
            with NamedTemporaryFile(
                dir=self.documenten, delete=False, suffix=".deel"
            ) as tijdelijk:
                pad = Path(tijdelijk.name)
                try:
                    for blok in antwoord.iter_content(chunk_size=64 * 1024):
                        if not blok:
                            continue
                        aantal += len(blok)
                        if aantal > self.max_bytes:
                            raise TariefkaartError(
                                f"Kaart is groter dan {self.max_bytes} bytes; "
                                "afgebroken."
                            )
                        hasher.update(blok)
                        tijdelijk.write(blok)
                except BaseException:
                    pad.unlink(missing_ok=True)
                    raise

        if aantal == 0:
            pad.unlink(missing_ok=True)
            raise TariefkaartError("Kaart is leeg (0 bytes).")

        with pad.open("rb") as fh:
            kop = fh.read(MAX_KOP_OFFSET)
        offset = kop.find(PDF_MAGIC)
        if offset < 0:
            pad.unlink(missing_ok=True)
            # Meestal een aanmeld- of landingspagina. Als kaart bewaren zou het
            # archief stil onbruikbaar maken; per leverancier uit te zoeken.
            raise TariefkaartError(
                f"Antwoord is geen PDF (content-type {content_type or 'onbekend'}, "
                f"begint met {kop[:8]!r})."
            )

        digest = hasher.hexdigest()
        doel = self.pad_voor(digest)
        doel.parent.mkdir(parents=True, exist_ok=True)
        if doel.exists():
            # Zelfde inhoud, al bewaard: het tijdelijke bestand is overbodig.
            pad.unlink(missing_ok=True)
        else:
            os.replace(pad, doel)
        return digest, aantal, content_type, offset

    @staticmethod
    def _controleer_url(url: str, wat: str) -> None:
        ontleed = urlparse(url)
        if ontleed.scheme != "https":
            raise TariefkaartError(f"{wat} is geen HTTPS: {url!r}")
        if not ontleed.hostname:
            raise TariefkaartError(f"{wat} heeft geen host: {url!r}")

    def haal_html(self, url: str) -> str:
        """De landingspagina, als tekst. Alleen om er links uit te halen."""
        import requests

        self._controleer_url(url, "landingspagina-URL")
        antwoord = requests.get(
            url, timeout=self.timeout, allow_redirects=True,
            headers={"User-Agent": USER_AGENT},
        )
        antwoord.raise_for_status()
        self._controleer_url(antwoord.url, "eindbestemming na omleiding")
        if len(antwoord.content) > self.max_bytes:
            raise TariefkaartError("Landingspagina is onwaarschijnlijk groot.")
        return antwoord.text

    def _via_landingspagina(self, bron: "Kaartbron"):
        """Zoek op de landingspagina de kaart van dít product.

        Lang niet elke link in `vtest_contract.link_tariefkaart` wijst
        rechtstreeks naar een PDF: 83 van de 351 kwamen uit op een
        productoverzicht. Sommige leveranciers leveren de kaart via een eigen
        route (Odoo's `/web/content/...`, Energy Knights'
        `/website/getCurrentTariffchart/...`), en dan zegt de bestandsnaam
        niets — de ankertekst wel.

        De pagina wordt per run één keer opgehaald: 16 contracten van dezelfde
        leverancier delen één overzichtspagina.
        """
        html = self._paginas.get(bron.url)
        if html is None:
            html = self.haal_html(bron.url)
            self._paginas[bron.url] = html
        kandidaten = kandidaten_uit_pagina(html, bron.url)
        return kies_kandidaat(kandidaten, bron.product, bron.energie_type)

    # -- de lus -----------------------------------------------------------

    def archiveer(
        self,
        bronnen: Iterable[Kaartbron],
        *,
        nu: Optional[datetime] = None,
        voortgang=None,
    ) -> Rapport:
        """Haal alle bronnen op en werk het register bij.

        Ongewijzigd, gewijzigd en nieuw worden uit elkaar gehouden omdat ze
        verschillende dingen betekenen: alleen "gewijzigd" zegt dat een
        leverancier zijn kaart vervangen heeft, en dat is het signaal waar dit
        archief voor bestaat.
        """
        nu = nu or datetime.now(tz=timezone.utc)
        stempel = nu.isoformat()
        register = self.lees_register()
        # Sleutel op (contract, URL): dezelfde kaart onder een andere URL is een
        # andere waarneming, en een contract dat naar een andere URL wijst ook.
        bestaand = {
            (k["vreg_id"], k["url"]): k for k in register.get("kaarten", [])
        }
        # Mislukkingen worden bijgehouden en niet overschreven. Een run met
        # `--leverancier` raakt maar een deel van de bronnen; de fouten van de
        # rest zomaar laten vallen zou het register laten beweren dat er niets
        # meer misgaat.
        eerdere_fouten = {
            (f["vreg_id"], f["url"]): f for f in register.get("fouten", [])
        }
        rapport = Rapport()
        bronnen = list(bronnen)

        def bewaar() -> None:
            register["kaarten"] = sorted(
                bestaand.values(),
                key=lambda k: (k["leverancier"], k["product"], k["vreg_id"]),
            )
            register["fouten"] = sorted(
                eerdere_fouten.values(),
                key=lambda f: (f["leverancier"], f["product"]),
            )
            register["bijgewerkt_op"] = stempel
            self.schrijf_register(register)

        for nummer, bron in enumerate(bronnen, start=1):
            if voortgang:
                voortgang(nummer, len(bronnen), bron)
            document_url = bron.url
            via_landingspagina = False
            overwogen: list = []
            try:
                digest, bytes_, content_type, kop_offset = self.haal_op(bron.url)
            except Exception as eerste:  # noqa: BLE001
                # Geen PDF maar HTML: dan is dit vermoedelijk een
                # productoverzicht en staat de kaart er ergens op.
                keuze = None
                if isinstance(eerste, TariefkaartError) and "geen PDF" in str(eerste):
                    try:
                        keuze, overwogen = self._via_landingspagina(bron)
                    except Exception as tweede:  # noqa: BLE001
                        eerste = tweede
                if keuze is None:
                    exc = eerste
                else:
                    try:
                        digest, bytes_, content_type, kop_offset = self.haal_op(keuze.url)
                        document_url = keuze.url
                        via_landingspagina = True
                        exc = None
                    except Exception as derde:  # noqa: BLE001
                        exc = derde
            else:
                exc = None

            if exc is not None:
                rapport.mislukt += 1
                fout = {
                    "vreg_id": bron.vreg_id,
                    "leverancier": bron.leverancier,
                    "product": bron.product,
                    "energie_type": bron.energie_type,
                    "url": bron.url,
                    "reden": f"{type(exc).__name__}: {exc}",
                    # De overwogen links reizen mee: het uitzoekwerk per
                    # leverancier wordt daarmee een opzoeking en geen
                    # heronderzoek.
                    "kandidaten": [
                        {"url": k.url, "label": k.label} for k in overwogen[:12]
                    ],
                    "op": stempel,
                }
                rapport.fouten.append(fout)
                bestaande_fout = eerdere_fouten.get((bron.vreg_id, bron.url))
                fout["eerst_mislukt_op"] = (
                    bestaande_fout.get("eerst_mislukt_op", stempel)
                    if bestaande_fout else stempel
                )
                eerdere_fouten[(bron.vreg_id, bron.url)] = fout
                LOG.warning(
                    "Tariefkaart mislukt (%s %s): %s",
                    bron.leverancier, bron.product, fout["reden"],
                )
                if self.pauze:
                    time.sleep(self.pauze)
                continue

            # Gelukt: een eerdere fout op deze sleutel is niet meer waar.
            eerdere_fouten.pop((bron.vreg_id, bron.url), None)
            vorig = bestaand.get((bron.vreg_id, bron.url))
            if vorig is None:
                bestaand[(bron.vreg_id, bron.url)] = {
                    "vreg_id": bron.vreg_id,
                    "leverancier": bron.leverancier,
                    "product": bron.product,
                    "energie_type": bron.energie_type,
                    "url": bron.url,
                    "document_url": document_url,
                    "via_landingspagina": via_landingspagina,
                    "sha256": digest,
                    "bytes": bytes_,
                    "content_type": content_type,
                    "kop_offset": kop_offset,
                    "bestand": str(self.pad_voor(digest).relative_to(self.wortel)),
                    "eerst_gezien_op": stempel,
                    "laatst_gezien_op": stempel,
                    "eerdere_versies": [],
                }
                rapport.nieuw += 1
            elif vorig["sha256"] == digest:
                vorig["laatst_gezien_op"] = stempel
                vorig["document_url"] = document_url
                vorig["via_landingspagina"] = via_landingspagina
                rapport.ongewijzigd += 1
            else:
                # De leverancier heeft de kaart vervangen. De oude blijft op
                # schijf staan — inhoudsgeadresseerd, dus ze kan niet
                # overschreven zijn — en het register houdt bij wanneer ze gold.
                vorig.setdefault("eerdere_versies", []).append({
                    "sha256": vorig["sha256"],
                    "bytes": vorig["bytes"],
                    "bestand": vorig["bestand"],
                    "eerst_gezien_op": vorig["eerst_gezien_op"],
                    "laatst_gezien_op": vorig["laatst_gezien_op"],
                })
                vorig.update({
                    "document_url": document_url,
                    "via_landingspagina": via_landingspagina,
                    "sha256": digest,
                    "bytes": bytes_,
                    "content_type": content_type,
                    "kop_offset": kop_offset,
                    "bestand": str(self.pad_voor(digest).relative_to(self.wortel)),
                    "eerst_gezien_op": stempel,
                    "laatst_gezien_op": stempel,
                })
                rapport.gewijzigd += 1

            # Tussentijds wegschrijven, en niet alleen op het einde. Dit zijn
            # 350 verzoeken naar evenveel externe sites; een run die halverwege
            # afgebroken wordt had anders wél de documenten op schijf staan maar
            # geen enkele waarneming in het register — en de volgende run zou ze
            # allemaal opnieuw als "nieuw" tellen. Het register is klein en het
            # schrijven gaat atomair, dus dit kost niets.
            if nummer % self.bewaar_om == 0:
                bewaar()
            if self.pauze:
                time.sleep(self.pauze)

        bewaar()
        return rapport
