"""Het tariefkaartarchief: wat er bewaard wordt en wat er geweigerd wordt.

De kaart is het enige stuk van een lopend contract dat niet retroactief te
herstellen is. De index valt uit de day-ahead historiek altijd nog terug te
rekenen; een PDF die de leverancier vervangt is weg. Wat dit archief bewaart
moet dus kloppen, en wat het niet kan bewaren moet luid mislukken in plaats van
stil iets anders neer te zetten.
"""

from __future__ import annotations

import json

import pytest

from energie_vlaanderen.ingest.tariefkaarten import (
    Kaartbron,
    TariefkaartArchief,
    TariefkaartError,
)

pytestmark = pytest.mark.bronnen


class _Antwoord:
    """Een requests-antwoord, genoeg ervan voor `haal_op`."""

    def __init__(self, inhoud: bytes, *, url: str, content_type="application/pdf"):
        self._inhoud = inhoud
        self.url = url
        self.headers = {"Content-Type": content_type}

    @property
    def content(self) -> bytes:
        return self._inhoud

    @property
    def text(self) -> str:
        return self._inhoud.decode("utf-8", "replace")

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def raise_for_status(self):
        return None

    def iter_content(self, chunk_size=1):
        for i in range(0, len(self._inhoud), chunk_size):
            yield self._inhoud[i:i + chunk_size]


@pytest.fixture
def antwoorden(monkeypatch):
    """Bepaalt per URL wat de server teruggeeft."""
    tabel: dict[str, _Antwoord] = {}

    def nep_get(url, **kw):
        if url not in tabel:
            raise AssertionError(f"onverwachte URL: {url}")
        return tabel[url]

    import requests
    monkeypatch.setattr(requests, "get", nep_get)
    return tabel


def _bron(vreg_id="A1", url="https://voorbeeld.be/kaart.pdf", leverancier="Test"):
    return Kaartbron(vreg_id=vreg_id, leverancier=leverancier, product="P",
                     energie_type="elektriciteit", url=url)


def _archief(tmp_path):
    return TariefkaartArchief(tmp_path / "archief", pauze=0)


class TestWatErBewaardWordt:
    def test_dezelfde_inhoud_wordt_een_keer_bewaard(self, tmp_path, antwoorden):
        """Leveranciers delen één kaart over meerdere producten.

        Mega heeft 51 contracten en lang niet 51 kaarten. Op URL bewaren zou
        hetzelfde document tientallen keren wegschrijven; op inhoud niet.
        """
        pdf = b"%PDF-1.4 dezelfde inhoud"
        for n in (1, 2, 3):
            antwoorden[f"https://x.be/{n}.pdf"] = _Antwoord(pdf, url=f"https://x.be/{n}.pdf")
        archief = _archief(tmp_path)
        rapport = archief.archiveer(
            [_bron(f"A{n}", f"https://x.be/{n}.pdf") for n in (1, 2, 3)]
        )
        assert rapport.nieuw == 3
        bestanden = list((archief.wortel / "documenten").rglob("*.pdf"))
        assert len(bestanden) == 1, "dezelfde inhoud hoort één keer op schijf te staan"

    def test_een_gewijzigde_kaart_laat_de_oude_staan(self, tmp_path, antwoorden):
        """Dat is de hele bedoeling: de oude versie mag niet overschreven worden.

        Inhoudsgeadresseerd betekent dat een nieuwe versie vanzelf een nieuw pad
        krijgt. Het register moet daarnaast bijhouden wanneer de oude gold,
        anders weet je wel dát er twee zijn maar niet welke wanneer.
        """
        url = "https://x.be/kaart.pdf"
        archief = _archief(tmp_path)

        antwoorden[url] = _Antwoord(b"%PDF-1.4 versie een", url=url)
        archief.archiveer([_bron(url=url)])

        antwoorden[url] = _Antwoord(b"%PDF-1.4 versie twee", url=url)
        rapport = archief.archiveer([_bron(url=url)])

        assert rapport.gewijzigd == 1
        assert len(list((archief.wortel / "documenten").rglob("*.pdf"))) == 2
        (kaart,) = archief.lees_register()["kaarten"]
        assert len(kaart["eerdere_versies"]) == 1
        oud = kaart["eerdere_versies"][0]
        assert oud["sha256"] != kaart["sha256"]
        assert (archief.wortel / oud["bestand"]).is_file()

    def test_een_ongewijzigde_kaart_levert_geen_tweede_waarneming(
        self, tmp_path, antwoorden
    ):
        url = "https://x.be/kaart.pdf"
        antwoorden[url] = _Antwoord(b"%PDF-1.4 zelfde", url=url)
        archief = _archief(tmp_path)
        archief.archiveer([_bron(url=url)])
        rapport = archief.archiveer([_bron(url=url)])
        assert (rapport.ongewijzigd, rapport.nieuw, rapport.gewijzigd) == (1, 0, 0)
        (kaart,) = archief.lees_register()["kaarten"]
        assert kaart["eerdere_versies"] == []
        assert kaart["laatst_gezien_op"] >= kaart["eerst_gezien_op"]


class TestWatErGeweigerdWordt:
    def test_html_wordt_niet_als_kaart_bewaard(self, tmp_path, antwoorden):
        """De stille fout die dit archief onbruikbaar zou maken.

        Een leverancier die zijn kaart achter een aanmeldpagina zet levert
        gewoon HTTP 200 met HTML. Op de bestandsnaam toetsen (`.pdf`) helpt
        niet — de URL eindigt wél op .pdf. Er wordt daarom op de
        PDF-signatuur getoetst.
        """
        url = "https://x.be/kaart.pdf"
        antwoorden[url] = _Antwoord(
            b"<!doctype html><html>Meld u aan om verder te gaan</html>",
            url=url, content_type="text/html",
        )
        archief = _archief(tmp_path)
        rapport = archief.archiveer([_bron(url=url)])
        assert rapport.mislukt == 1
        assert rapport.nieuw == 0
        assert not list((archief.wortel / "documenten").rglob("*.pdf"))
        assert "geen PDF" in rapport.fouten[0]["reden"]

    def test_een_pdf_met_een_bom_ervoor_wordt_wel_aanvaard(self, tmp_path, antwoorden):
        """De valse afwijzing die 35 geldige kaarten kostte.

        Luminus levert zijn tariefkaarten met een UTF-8 BOM vóór de PDF-kop:
        `\xef\xbb\xbf%PDF-1.4`. Een toets op byte 0 noemde dat "geen PDF",
        terwijl het een leesbare kaart van 214 kB is — pdfinfo en pdftotext
        halen er zonder morren de tariefkaart van Luminus BasicFix Online uit.
        ISO 32000-1 §7.5.2 laat de kop binnen de eerste 1024 bytes toe.

        Dat de offset bewaard blijft is geen sierlijkheid: een BOM voor een PDF
        is een eigenaardigheid van die leverancier en je wil hem kunnen
        terugvinden zonder elk bestand opnieuw te openen.
        """
        url = "https://x.be/bom.pdf"
        antwoorden[url] = _Antwoord(b"\xef\xbb\xbf%PDF-1.4 echte kaart", url=url)
        archief = _archief(tmp_path)
        rapport = archief.archiveer([_bron(url=url)])
        assert rapport.nieuw == 1
        (kaart,) = archief.lees_register()["kaarten"]
        assert kaart["kop_offset"] == 3
        assert (archief.wortel / kaart["bestand"]).is_file()

    def test_een_pdf_kop_voorbij_de_grens_telt_niet(self, tmp_path, antwoorden):
        """Anders zou elke HTML-pagina die het woord %PDF- noemt erdoor komen."""
        url = "https://x.be/ver.pdf"
        antwoorden[url] = _Antwoord(b"x" * 2000 + b"%PDF-1.4", url=url)
        archief = _archief(tmp_path)
        assert archief.archiveer([_bron(url=url)]).mislukt == 1

    def test_een_te_grote_kaart_wordt_afgebroken(self, tmp_path, antwoorden):
        url = "https://x.be/groot.pdf"
        antwoorden[url] = _Antwoord(b"%PDF-1.4" + b"x" * 5000, url=url)
        archief = TariefkaartArchief(tmp_path / "a", pauze=0, max_bytes=1000)
        rapport = archief.archiveer([_bron(url=url)])
        assert rapport.mislukt == 1
        assert not list((archief.wortel / "documenten").rglob("*.pdf"))

    def test_geen_https(self, tmp_path):
        archief = _archief(tmp_path)
        with pytest.raises(TariefkaartError, match="geen HTTPS"):
            archief.haal_op("http://x.be/kaart.pdf")

    def test_een_omleiding_naar_http_wordt_geweigerd(self, tmp_path, antwoorden):
        """De eindbestemming is wat we werkelijk downloaden."""
        url = "https://x.be/kaart.pdf"
        antwoorden[url] = _Antwoord(b"%PDF-1.4 ok", url="http://elders.be/kaart.pdf")
        archief = _archief(tmp_path)
        rapport = archief.archiveer([_bron(url=url)])
        assert rapport.mislukt == 1
        assert "omleiding" in rapport.fouten[0]["reden"]

    def test_een_lege_kaart(self, tmp_path, antwoorden):
        url = "https://x.be/leeg.pdf"
        antwoorden[url] = _Antwoord(b"", url=url)
        archief = _archief(tmp_path)
        assert archief.archiveer([_bron(url=url)]).mislukt == 1


class TestHetRegister:
    def test_een_beschadigd_register_wordt_niet_stil_overschreven(self, tmp_path):
        """Stil op leeg terugvallen zou elke kaart opnieuw als "nieuw"
        aanmerken en de eerste-waarnemingsdatum wissen — het enige gegeven dat
        dit archief onderscheidt van een map met PDF's."""
        archief = _archief(tmp_path)
        archief.wortel.mkdir(parents=True)
        archief.register_pad.write_text("{dit is geen json", encoding="utf-8")
        with pytest.raises(TariefkaartError, match="onleesbaar"):
            archief.lees_register()

    def test_fouten_van_andere_leveranciers_blijven_staan(self, tmp_path, antwoorden):
        """Een run met `--leverancier` raakt maar een deel van de bronnen.

        De fouten van de rest laten vallen zou het register laten beweren dat
        er niets meer misgaat.
        """
        stuk, goed = "https://x.be/stuk.pdf", "https://x.be/goed.pdf"
        antwoorden[stuk] = _Antwoord(b"<html>", url=stuk, content_type="text/html")
        antwoorden[goed] = _Antwoord(b"%PDF-1.4 ok", url=goed)
        archief = _archief(tmp_path)
        archief.archiveer([_bron("A1", stuk, leverancier="Stuk")])
        archief.archiveer([_bron("A2", goed, leverancier="Goed")])
        fouten = archief.lees_register()["fouten"]
        assert [f["vreg_id"] for f in fouten] == ["A1"]

    def test_een_opgeloste_fout_verdwijnt(self, tmp_path, antwoorden):
        url = "https://x.be/kaart.pdf"
        archief = _archief(tmp_path)
        antwoorden[url] = _Antwoord(b"<html>", url=url, content_type="text/html")
        archief.archiveer([_bron(url=url)])
        assert archief.lees_register()["fouten"]
        antwoorden[url] = _Antwoord(b"%PDF-1.4 nu wel", url=url)
        archief.archiveer([_bron(url=url)])
        assert archief.lees_register()["fouten"] == []

    def test_een_afgebroken_run_verliest_zijn_waarnemingen_niet(
        self, tmp_path, antwoorden
    ):
        """Het register wordt tussentijds weggeschreven, niet alleen op het einde.

        Dit zijn 350 verzoeken naar evenveel externe sites en het duurt
        minuten. Wordt zo'n run afgebroken — en dat gebeurde — dan stonden de
        documenten wél op schijf maar was er geen enkele waarneming bewaard, en
        telde de volgende run ze allemaal opnieuw als "nieuw". Daarmee is de
        eerste-waarnemingsdatum weg, en dat is nu net wat dit archief
        onderscheidt van een map met PDF's.
        """
        urls = [f"https://x.be/{n}.pdf" for n in range(6)]
        for n, u in enumerate(urls):
            antwoorden[u] = _Antwoord(f"%PDF-1.4 kaart {n}".encode(), url=u)

        archief = TariefkaartArchief(tmp_path / "a", pauze=0, bewaar_om=2)
        gestopt = RuntimeError("verbinding verbroken")

        def struikel(nummer, totaal, bron):
            if nummer == 5:
                raise gestopt

        with pytest.raises(RuntimeError):
            archief.archiveer(
                [_bron(f"A{n}", u) for n, u in enumerate(urls)], voortgang=struikel
            )

        # Vier gelukt vóór de onderbreking, tot de laatste bewaarpunt: minstens
        # de eerste vier staan in het register.
        bewaard = archief.lees_register()["kaarten"]
        assert len(bewaard) >= 4, f"maar {len(bewaard)} waarnemingen bewaard"

    def test_het_register_is_geldige_json_met_de_verwachte_velden(
        self, tmp_path, antwoorden
    ):
        url = "https://x.be/kaart.pdf"
        antwoorden[url] = _Antwoord(b"%PDF-1.4 ok", url=url)
        archief = _archief(tmp_path)
        archief.archiveer([_bron(url=url)])
        register = json.loads(archief.register_pad.read_text(encoding="utf-8"))
        (kaart,) = register["kaarten"]
        for veld in ("vreg_id", "leverancier", "product", "energie_type", "url",
                     "sha256", "bytes", "content_type", "bestand",
                     "eerst_gezien_op", "laatst_gezien_op"):
            assert veld in kaart, veld
        assert (archief.wortel / kaart["bestand"]).is_file()


class TestDeLandingspagina:
    """83 van de 351 links wijzen niet naar een PDF maar naar een overzicht.

    De kaart staat daar wél op, maar achter een eigen route: Odoo levert hem
    als `/web/content/xx.product.group.tariff.card/1772/file` met ankertekst
    "Tariefkaart_Flow_EL", Energy Knights als
    `/website/getCurrentTariffchart/agilioronline/nl`. In beide gevallen zegt
    de bestandsnaam niets en de omgeving alles.
    """

    OVERZICHT = b"""<!doctype html><html><body>
      <a href="/web/content/x/1770/file">Tariefkaart_Dynamic_EL</a>
      <a href="/web/content/x/1771/file">Tariefkaart_Variabel_Gas</a>
      <a href="/web/content/x/1772/file">Tariefkaart_Flow_EL</a>
      <a href="/web/content/x/1773/file">Tariefkaart_Flow_Gas</a>
      <a href="/over-ons">Over ons</a>
    </body></html>"""

    def _opzet(self, antwoorden, tmp_path, product, energie="elektriciteit"):
        landing = "https://x.be/products"
        antwoorden[landing] = _Antwoord(
            self.OVERZICHT, url=landing, content_type="text/html"
        )
        bron = Kaartbron(vreg_id="A1", leverancier="T", product=product,
                         energie_type=energie, url=landing)
        return _archief(tmp_path), bron, landing

    def test_de_kaart_wordt_op_de_overzichtspagina_gevonden(self, tmp_path, antwoorden):
        archief, bron, _ = self._opzet(antwoorden, tmp_path, "Flow")
        antwoorden["https://x.be/web/content/x/1772/file"] = _Antwoord(
            b"%PDF-1.4 Flow elektriciteit", url="https://x.be/web/content/x/1772/file"
        )
        rapport = archief.archiveer([bron])
        assert rapport.nieuw == 1
        (kaart,) = archief.lees_register()["kaarten"]
        assert kaart["via_landingspagina"] is True
        # De herkomst blijft zichtbaar: de VREG-link én wat we werkelijk
        # gedownload hebben. Alleen het laatste bewaren zou de link uit de
        # databank onvindbaar maken; alleen het eerste zou liegen.
        assert kaart["url"] == "https://x.be/products"
        assert kaart["document_url"].endswith("/1772/file")

    def test_gas_en_elektriciteit_worden_niet_verwisseld(self, tmp_path, antwoorden):
        """"Flow" bestaat in beide energievormen op dezelfde pagina.

        Dezelfde fout als `zoek_product()` die vastzat op "Elektriciteit": een
        gascontract kreeg de elektriciteitsprijs, drie keer te veel, zonder
        foutmelding.
        """
        archief, bron, _ = self._opzet(antwoorden, tmp_path, "Flow", energie="gas")
        antwoorden["https://x.be/web/content/x/1773/file"] = _Antwoord(
            b"%PDF-1.4 Flow gas", url="https://x.be/web/content/x/1773/file"
        )
        assert archief.archiveer([bron]).nieuw == 1
        (kaart,) = archief.lees_register()["kaarten"]
        assert kaart["document_url"].endswith("/1773/file")

    def test_bij_twijfel_wordt_er_niets_gekozen(self, tmp_path, antwoorden):
        """Een verkeerde kaart is erger dan een ontbrekende.

        Het archief bestaat om een contract exact na te rekenen; een gokje
        levert een bedrag op dat klopt op de verkeerde formule, en niets faalt.
        """
        archief, bron, _ = self._opzet(antwoorden, tmp_path, "Tariefkaart")
        rapport = archief.archiveer([bron])
        assert rapport.mislukt == 1
        assert rapport.nieuw == 0

    def test_de_overwogen_links_staan_in_het_foutenregister(self, tmp_path, antwoorden):
        """Zodat het uitzoekwerk per leverancier een opzoeking is."""
        archief, bron, _ = self._opzet(antwoorden, tmp_path, "Tariefkaart")
        archief.archiveer([bron])
        (fout,) = archief.lees_register()["fouten"]
        labels = [k["label"] for k in fout["kandidaten"]]
        assert "Tariefkaart_Flow_EL" in labels

    def test_de_pagina_wordt_een_keer_opgehaald(self, tmp_path, antwoorden, monkeypatch):
        """16 contracten van dezelfde leverancier delen één overzichtspagina."""
        archief, bron, landing = self._opzet(antwoorden, tmp_path, "Flow")
        antwoorden["https://x.be/web/content/x/1772/file"] = _Antwoord(
            b"%PDF-1.4 Flow", url="https://x.be/web/content/x/1772/file"
        )
        tellen = {"n": 0}
        origineel = archief.haal_html
        monkeypatch.setattr(
            archief, "haal_html",
            lambda u: (tellen.__setitem__("n", tellen["n"] + 1), origineel(u))[1],
        )
        bronnen = [
            Kaartbron(vreg_id=f"A{i}", leverancier="T", product="Flow",
                      energie_type="elektriciteit", url=landing)
            for i in range(4)
        ]
        archief.archiveer(bronnen)
        assert tellen["n"] == 1

    def test_een_historiekkaart_telt_niet_als_de_huidige(self, tmp_path, antwoorden):
        """Aspiravi zet 21 maandkaarten op één pagina.

        Die horen in een archief thuis, maar niet als "de kaart van dit
        contract vandaag".
        """
        landing = "https://x.be/tariefkaarten"
        antwoorden[landing] = _Antwoord(
            b"""<!doctype html><html><body>
              <a href="/History_Eco-Plus-flex_augustus-22.pdf">Eco Plus flex augustus 22</a>
              <a href="/History_Eco-Plus-flex_december-22.pdf">Eco Plus flex december 22</a>
            </body></html>""",
            url=landing, content_type="text/html",
        )
        archief = _archief(tmp_path)
        bron = Kaartbron(vreg_id="A1", leverancier="T", product="Eco Plus flex",
                         energie_type="elektriciteit", url=landing)
        assert archief.archiveer([bron]).mislukt == 1


class TestDeDrieRegelsDieDeRestOplosten:
    """Uit het foutenregister afgelezen, niet per leverancier uitgezocht.

    De resolver bewaart bij elke mislukking de overwogen links. Daaruit bleken
    drie patronen die niets met één leverancier te maken hebben — en dus als
    regel horen en niet als uitzondering.
    """

    def test_ng_telt_als_gas(self, tmp_path, antwoorden):
        """`_NG` is "natural gas".

        De Energy Together-sites labelen `Tariefkaart_APEX Online_NG` naast
        `_EL`. Zonder deze herkenning bleven bij een elektriciteitscontract
        beide over en werd er niets gekozen — terwijl de juiste er letterlijk
        tussen stond.
        """
        landing = "https://x.be/products"
        antwoorden[landing] = _Antwoord(
            b"""<html><body>
              <a href="/c/1760/file">Tariefkaart_APEX Online_EL</a>
              <a href="/c/1761/file">Tariefkaart_APEX Online_NG</a>
            </body></html>""", url=landing, content_type="text/html")
        antwoorden["https://x.be/c/1760/file"] = _Antwoord(
            b"%PDF-1.4 elek", url="https://x.be/c/1760/file")
        archief = _archief(tmp_path)
        bron = Kaartbron(vreg_id="A1", leverancier="T", product="APEX Online",
                         energie_type="elektriciteit", url=landing)
        assert archief.archiveer([bron]).nieuw == 1
        assert archief.lees_register()["kaarten"][0]["document_url"].endswith("1760/file")

    def test_een_exacte_naam_wint_van_een_deelstring(self, tmp_path, antwoorden):
        """"PRIME" zit ook in "PRIME Plus", "Flex" in "FlexPro".

        Zonder deze regel leveren die twee kandidaten op en wordt er niets
        gekozen, terwijl de juiste eenduidig aanwijsbaar is.
        """
        landing = "https://x.be/products"
        antwoorden[landing] = _Antwoord(
            b"""<html><body>
              <a href="/c/1752/file">Tariefkaart_PRIME Plus_EL</a>
              <a href="/c/1758/file">Tariefkaart_PRIME_EL</a>
            </body></html>""", url=landing, content_type="text/html")
        antwoorden["https://x.be/c/1758/file"] = _Antwoord(
            b"%PDF-1.4 prime", url="https://x.be/c/1758/file")
        archief = _archief(tmp_path)
        bron = Kaartbron(vreg_id="A1", leverancier="T", product="PRIME",
                         energie_type="elektriciteit", url=landing)
        assert archief.archiveer([bron]).nieuw == 1
        assert archief.lees_register()["kaarten"][0]["document_url"].endswith("1758/file")

    def test_gelijke_kandidaten_zijn_geen_dubbelzinnigheid(self, tmp_path, antwoorden):
        """Twee id's, één kaart.

        De Energy Together-sites dragen dezelfde kaart onder twee id's met
        dezelfde ankertekst. Op naam is dat niet te scheiden en kiezen zou een
        gok zijn — maar zodra ze byte voor byte gelijk zijn, ís er niets te
        kiezen. Dat is geen versoepeling van de regel maar de toepassing ervan.
        """
        landing = "https://x.be/products"
        antwoorden[landing] = _Antwoord(
            b"""<html><body>
              <a href="/c/1751/file">Tariefkaart_NOVA_NG</a>
              <a href="/c/1757/file">Tariefkaart_NOVA_NG</a>
            </body></html>""", url=landing, content_type="text/html")
        for i in ("1751", "1757"):
            antwoorden[f"https://x.be/c/{i}/file"] = _Antwoord(
                b"%PDF-1.4 een en dezelfde kaart", url=f"https://x.be/c/{i}/file")
        archief = _archief(tmp_path)
        bron = Kaartbron(vreg_id="A1", leverancier="T", product="NOVA",
                         energie_type="gas", url=landing)
        assert archief.archiveer([bron]).nieuw == 1
        assert len(list((archief.wortel / "documenten").rglob("*.pdf"))) == 1

    def test_verschillende_kandidaten_blijven_een_fout(self, tmp_path, antwoorden):
        """De keerzijde, en ze is de reden dat de vorige regel mag bestaan."""
        landing = "https://x.be/products"
        antwoorden[landing] = _Antwoord(
            b"""<html><body>
              <a href="/c/1/file">Tariefkaart_NOVA_NG</a>
              <a href="/c/2/file">Tariefkaart_NOVA_NG</a>
            </body></html>""", url=landing, content_type="text/html")
        antwoorden["https://x.be/c/1/file"] = _Antwoord(
            b"%PDF-1.4 kaart een", url="https://x.be/c/1/file")
        antwoorden["https://x.be/c/2/file"] = _Antwoord(
            b"%PDF-1.4 kaart twee, anders", url="https://x.be/c/2/file")
        archief = _archief(tmp_path)
        bron = Kaartbron(vreg_id="A1", leverancier="T", product="NOVA",
                         energie_type="gas", url=landing)
        assert archief.archiveer([bron]).mislukt == 1
