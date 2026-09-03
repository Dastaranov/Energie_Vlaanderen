from __future__ import annotations

import logging
import time

LOG = logging.getLogger(__name__)

VTEST_URL = "https://www.vtest.be/"

_COOKIE_SELECTORS = (
    "#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll",
    "#onetrust-accept-btn-handler",
    "button.cookie-accept",
    "button[id*='allow']",
)

_POSTCODE_SELECTORS = (
    "#PostalcodesInput input",
    "input[placeholder*='Postcode']",
    "input[placeholder*='postcode']",
    "input[name*='post']",
)

_SUBMIT_KEYWORDS = ("vergelijk", "zoeken", "toon", "bereken", "result", "start", "v-test")
# Bij segment "onderneming" (na tab2) toont de site twee knoppen die allebei
# op _SUBMIT_KEYWORDS matchen: "Sla op in mijn profiel en doe de V-test®"
# (opent een profiel-aanmaakflow, blokkeert de resultaten) en "Sla deze stap
# over en doe de V-test®" (de eigenlijke doorgaan-knop). De eerste wordt
# expliciet uitgesloten.
_SUBMIT_EXCLUDE_KEYWORDS = ("sla op",)


class VTestDownloadError(RuntimeError):
    pass


class VTestHtmlDownloader:
    """Haalt de volledige V-test resultatenpagina op via Selenium.

    Port van Vl-Tarief-Sym/_archive/download_vtest_html_v2.py.
    Vereist: pip install -e ".[scrape]" (selenium>=4.0).
    """

    def download(
        self,
        postcode: str = "9000",
        segment: str = "woning",
        energy: str = "elektriciteit",
        kwh_elektriciteit: int = 15000,
        kwh_gas: int = 10000,
        headless: bool = True,
        browser: str = "firefox",
        timeout: int = 60,
        force_eigen_verbruik: bool = False,
        injectie_kwh: int = 0,
        omvormer_kva: float | None = None,
        contractdetails: dict[str, str] | None = None,
        reeds_gekend: set[str] | None = None,
    ) -> str:
        """Navigeer naar vtest.be, vul het formulier in en retourneer de volledige HTML.

        `segment`: "woning" (= "Mijn woning", standaard — zelfde waarde als
        `Segment` in de bulk-export en `Profile.segment`) of "onderneming"
        (= "Mijn onderneming"). `energy`: "elektriciteit" of "gas" — de
        checkboxes staan standaard beide aan, de niet-gekozene wordt uitgevinkt.

        `kwh_elektriciteit`/`kwh_gas`: representatief jaarverbruik, enkel
        gebruikt voor segment "onderneming" — daar is "Ik ken mijn verbruik
        niet" uitgeschakeld en moet een verbruik ingevuld worden. Bevestigd
        met Gert: 15.000 kWh elektriciteit / 10.000 kWh gas als vast
        representatief KMO-profiel — de exacte waarde is hier niet kritiek,
        enkel bepalend voor welke prijs vtest.be per contract berekent.

        `contractdetails`: geef een dict mee om de tariefkaart- en
        voorwaardenlinks te laten verzamelen. Die staan niet op de
        resultatenpagina — vtest.be laadt ze pas bij een klik op "Meer
        details" — dus ze zijn niet uit een HTML-dump te halen. De dict wordt
        gevuld met contract-id -> {tariefkaart, voorwaarden, leverancier}.
        `reeds_gekend` slaat contracten over die al opgehaald zijn; over een
        volledige matrix scheelt dat honderden kliks, want dezelfde contracten
        komen bij elke postcode terug.

        `injectie_kwh`/`omvormer_kva`: jaarlijkse teruglevering en
        omvormervermogen. Groter dan nul zet `HasSolarPanels` aan, waardoor
        vtest.be de injectievelden toont en een injectievergoeding meerekent.
        Nul (standaard) houdt het formulier zoals het voor de tariefkalibratie
        nodig is: geen zonnepanelen, zodat de factuur enkel van het verbruik
        afhangt.

        `force_eigen_verbruik`: forceer tab2 ("Ik ken mijn verbruik") ook voor
        segment "woning". Nodig voor de kalibratieruns
        (`ingest.vtest.calibration`), die de heffingen- en nettariefformules
        terugrekenen door hetzelfde postcode-profiel bij verschillende
        verbruiken op te vragen. Bij normale refine-runs blijft dit False,
        zodat vtest.be zijn eigen schattingsprofiel gebruikt.
        """
        try:
            from selenium import webdriver
            from selenium.common.exceptions import NoSuchElementException
            from selenium.webdriver.chrome.options import Options as ChromeOptions
            from selenium.webdriver.firefox.options import Options as FirefoxOptions
            from selenium.webdriver.common.by import By
            from selenium.webdriver.common.keys import Keys
            from selenium.webdriver.support import expected_conditions as EC
            from selenium.webdriver.support.ui import WebDriverWait
        except ImportError as exc:
            raise VTestDownloadError(
                "selenium is niet geïnstalleerd. Voer 'pip install -e \".[scrape]\"' uit."
            ) from exc

        driver = self._setup_driver(browser, headless)
        try:
            from selenium.webdriver.common.by import By
            from selenium.webdriver.common.keys import Keys
            from selenium.webdriver.support import expected_conditions as EC
            from selenium.webdriver.support.ui import WebDriverWait

            LOG.info("Navigeren naar %s ...", VTEST_URL)
            driver.get(VTEST_URL)

            # Cookies accepteren
            try:
                WebDriverWait(driver, 5).until(
                    lambda d: d.execute_script("return document.readyState") == "complete"
                )
                time.sleep(1.0)
                for sel in _COOKIE_SELECTORS:
                    try:
                        btn = driver.find_element(By.CSS_SELECTOR, sel)
                        if btn.is_displayed():
                            btn.click()
                            LOG.debug("Cookies geaccepteerd via %s", sel)
                            break
                    except Exception:
                        pass
            except Exception:
                pass

            time.sleep(0.6)

            # Postcode trigger
            try:
                triggers = driver.find_elements(
                    By.XPATH, "//button[contains(., 'Selecteer een postcode')]"
                )
                if triggers and triggers[0].is_displayed():
                    triggers[0].click()
                    time.sleep(0.5)
            except Exception:
                pass

            # Postcode invoeren — het onderliggende <select id="PostalCode">
            # heeft interne id-waarden i.p.v. de postcode zelf
            # (<option value="7758">1500 - Halle</option>), dus typen+Enter
            # kan de verkeerde gemeente selecteren. We klikken daarom
            # expliciet op de juiste <a>-optie in de opengeklapte lijst.
            postcode_field = None
            for css in _POSTCODE_SELECTORS:
                els = driver.find_elements(By.CSS_SELECTOR, css)
                for el in els:
                    if el.is_displayed():
                        postcode_field = el
                        break
                if postcode_field:
                    break

            if postcode_field:
                postcode_field.clear()
                postcode_field.send_keys(postcode)
                time.sleep(1.0)

                gekozen = False
                try:
                    opts = driver.find_elements(
                        By.XPATH,
                        "//div[@id='PostalcodesInput']"
                        f"//a[starts-with(normalize-space(.), '{postcode}')]",
                    )
                    if opts:
                        label = opts[0].text.strip()
                        driver.execute_script("arguments[0].click();", opts[0])
                        gekozen = True
                        LOG.info("Postcode %s geselecteerd (%s).", postcode, label)
                except Exception as exc:
                    LOG.warning("Postcode-optie klikken mislukt: %s", exc)

                if not gekozen:
                    LOG.warning(
                        "Geen exacte postcode-optie gevonden voor %s; "
                        "resultaat kan een verkeerde gemeente betreffen.",
                        postcode,
                    )
                time.sleep(1.0)
            else:
                LOG.warning("Postcode-invoerveld niet gevonden.")

            # Klantsegment: "Mijn woning" (woning) of
            # "Mijn onderneming" (onderneming) — standaard staat woning aan.
            segment_id = "PropertyTypeCommercial" if segment == "onderneming" else "PropertyTypeDomicile"
            try:
                el = driver.find_element(By.ID, segment_id)
                if not el.is_selected():
                    driver.execute_script("arguments[0].click();", el)
                LOG.info("Klantsegment ingesteld op %s.", segment)
            except Exception as exc:
                LOG.warning("Klantsegment (%s) instellen mislukt: %s", segment_id, exc)

            # Energietype: beide checkboxes staan standaard aan; vink de
            # ongewenste uit.
            gewenst_id = "EnergyTypeElectricity" if energy == "elektriciteit" else "EnergyTypeGas"
            ongewenst_id = "EnergyTypeGas" if energy == "elektriciteit" else "EnergyTypeElectricity"
            try:
                gewenst = driver.find_element(By.ID, gewenst_id)
                if not gewenst.is_selected():
                    driver.execute_script("arguments[0].click();", gewenst)
                ongewenst = driver.find_element(By.ID, ongewenst_id)
                if ongewenst.is_selected():
                    driver.execute_script("arguments[0].click();", ongewenst)
            except Exception as exc:
                LOG.warning("Energietype (%s) instellen mislukt: %s", energy, exc)

            # Verplichte stap "Ken je je verbruik?" — zonder deze keuze
            # blijft de submitknop onzichtbaar. "Ik ken mijn verbruik niet"
            # (tab1) gebruikt VREG's eigen schattingsprofiel, maar is
            # uitgeschakeld voor segment "onderneming" ("Voor een onderneming
            # moet je het verbruik invullen.") — daar kiezen we tab2
            # ("Ik ken mijn verbruik") en vullen we het representatieve
            # jaarverbruik in.
            try:
                tab1 = driver.find_element(By.ID, "tab1")
                if tab1.get_property("disabled") or force_eigen_verbruik:
                    LOG.info(
                        "Eigen verbruik invullen voor segment '%s' "
                        "(%s kWh elek, %s kWh gas).",
                        segment, kwh_elektriciteit, kwh_gas,
                    )
                    tab2 = driver.find_element(By.ID, "tab2")
                    driver.execute_script("arguments[0].click();", tab2)
                    time.sleep(0.5)
                    # Enkelvoudige digitale meter, geen zonnepanelen, geen
                    # gekend aansluitvermogen — zo hangt de factuur enkel van
                    # UsageDay/UsageGas af. Dat is wat de kalibratie nodig
                    # heeft om de heffingen- en nettariefformules te isoleren;
                    # voor "onderneming" was dit al impliciet het geval.
                    for radio_id in ("KnownMeterDigital", "KnownMeterCountSimple"):
                        try:
                            el = driver.find_element(By.ID, radio_id)
                            if not el.is_selected():
                                driver.execute_script("arguments[0].click();", el)
                        except NoSuchElementException:
                            pass
                    # `HasSolarPanels` blijft standaard uit: dan hangt de
                    # factuur enkel van UsageDay/UsageGas af, wat de kalibratie
                    # van de heffingen- en nettariefformules isoleert. Wordt er
                    # wél een injectievolume gevraagd, dan moet het vinkje juist
                    # aan — pas dan toont vtest.be de velden InjectionDay,
                    # KnowsInverterPower en InverterPower, en pas dan rekent hij
                    # een injectievergoeding mee.
                    wil_injectie = injectie_kwh > 0 and energy == "elektriciteit"
                    # Volgorde telt: `KnowsCapacityElectricity` eerst, dan pas
                    # `HasSolarPanels`. Andersom hertekent het uitvinken het
                    # paneel nádat de zonnepaneelvelden verschenen zijn, waardoor
                    # `InverterPower` kortstondig onzichtbaar is. De invulcode
                    # slaat onzichtbare velden over, het verplichte veld bleef
                    # leeg, en vtest.be gaf dan gewoon geen resultaten terug.
                    for check_id, gewenst in (
                        ("KnowsCapacityElectricity", False),
                        ("HasSolarPanels", wil_injectie),
                    ):
                        try:
                            el = driver.find_element(By.ID, check_id)
                            if el.is_selected() != gewenst:
                                driver.execute_script("arguments[0].click();", el)
                        except NoSuchElementException:
                            pass
                    time.sleep(0.3)

                    if wil_injectie:
                        # Wachten tot het paneel klaar is met hertekenen in
                        # plaats van een vaste sleep: een te korte pauze laat
                        # `InverterPower` leeg en dat faalt pas veel later, bij
                        # het uitblijven van resultaten.
                        for _ in range(20):
                            try:
                                if driver.find_element(By.ID, "InverterPower").is_displayed():
                                    break
                            except NoSuchElementException:
                                pass
                            time.sleep(0.25)
                        else:
                            LOG.warning(
                                "InverterPower werd niet zichtbaar; vtest.be zal "
                                "de submit weigeren."
                            )

                    if wil_injectie and not omvormer_kva:
                        # `InverterPower` verschijnt zodra HasSolarPanels aan
                        # staat en is dan verplicht. Zonder waarde weigert
                        # vtest.be te submitten met "Dit is een verplicht veld!"
                        # en verschijnen er simpelweg geen resultaten — een
                        # foutbeeld dat er uitziet als een onbereikbare site.
                        raise VTestDownloadError(
                            "Een injectievolume opgeven vereist ook een "
                            "omvormervermogen (omvormer_kva): vtest.be maakt "
                            "het veld InverterPower verplicht zodra er "
                            "zonnepanelen aangevinkt zijn."
                        )
                    # De verbruikvelden hangen aan een invoermasker dat de
                    # duizendtalpunten zet ("1.000"). Dat masker slikt
                    # send_keys-toetsaanslagen: het veld blijft leeg en
                    # vtest.be weigert dan te submitten met "Dit is een
                    # verplicht veld!". Waarde rechtstreeks zetten en de
                    # input/change/blur-events zelf vuren werkt wel.
                    velden = [("UsageDay", kwh_elektriciteit), ("UsageGas", kwh_gas)]
                    if wil_injectie:
                        # `KnowsInverterPower` wordt bewust niet aangeklikt: dat
                        # vinkje verbergt het invoerveld in plaats van het te
                        # tonen, en dan blijft de verplichte waarde leeg.
                        velden.append(("InjectionDay", injectie_kwh))
                        velden.append(("InverterPower", omvormer_kva))
                    for veld_id, waarde in velden:
                        try:
                            veld = driver.find_element(By.ID, veld_id)
                        except NoSuchElementException as exc:
                            LOG.warning("Verbruikveld %s niet gevonden: %s", veld_id, exc)
                            continue
                        if not veld.is_displayed():
                            # Hoort bij het niet-gekozen energietype.
                            continue
                        driver.execute_script(
                            "arguments[0].value = arguments[1];"
                            "arguments[0].dispatchEvent(new Event('input', {bubbles:true}));"
                            "arguments[0].dispatchEvent(new Event('change', {bubbles:true}));"
                            "arguments[0].dispatchEvent(new Event('blur', {bubbles:true}));",
                            veld,
                            str(waarde),
                        )
                        if not driver.find_element(By.ID, veld_id).get_attribute("value"):
                            LOG.warning(
                                "Verbruikveld %s bleef leeg na invullen (%s) — "
                                "vtest.be zal de submit weigeren.",
                                veld_id, waarde,
                            )
                    # Wat er werkelijk ingediend wordt. Zonder deze regel is een
                    # geweigerd formulier alleen zichtbaar als "geen resultaten".
                    # Defensief: het paneel kan al aan het hertekenen zijn.
                    ingevuld = driver.execute_script(
                        "return Array.from(document.querySelectorAll('input[type=text]'))"
                        ".filter(e => e.offsetParent !== null)"
                        ".map(e => e.id + '=' + e.value).join(', ');"
                    )
                    LOG.info("Ingevulde velden: %s", ingevuld or "(geen zichtbare)")
                elif not tab1.is_selected():
                    driver.execute_script("arguments[0].click();", tab1)
            except NoSuchElementException as exc:
                LOG.warning("Verbruik-stap mislukt: %s", exc)
            time.sleep(0.5)

            # Submit-knop zoeken, klikken en wachten — in één lus.
            #
            # vtest.be hertekent het formulierpaneel nadat de laatste waarde
            # ingevuld is (het klapt dicht). Een knopreferentie die vóór dat
            # hertekenen gevonden werd is daarna stale: de klik gooit dan een
            # `StaleElementReferenceException`, of erger, hij "lukt" maar gaat
            # verloren omdat het element niet meer in de DOM zit. Er verschijnt
            # dan nooit een resultaat, en dat foutbeeld is niet te onderscheiden
            # van een onbereikbare site.
            #
            # Klikken en wachten zijn daarom niet gescheiden: na elke klik
            # wachten we een stuk, en verschijnt er niets, dan zoeken we de knop
            # opnieuw op en klikken we nog eens. Het totale geduld blijft
            # `timeout`.
            from selenium.common.exceptions import StaleElementReferenceException

            def _zoek_startknop():
                zichtbaar = None
                onzichtbaar = None
                for kandidaat in driver.find_elements(
                    By.CSS_SELECTOR, "button, input[type='submit'], a.btn, [role='button']"
                ):
                    tekst = (
                        (kandidaat.get_attribute("textContent") or "")
                        + " "
                        + (kandidaat.get_attribute("value") or "")
                    ).strip().lower()
                    if any(kw in tekst for kw in _SUBMIT_EXCLUDE_KEYWORDS):
                        continue
                    if any(kw in tekst for kw in _SUBMIT_KEYWORDS):
                        if kandidaat.is_displayed() and kandidaat.is_enabled():
                            return kandidaat
                        if onzichtbaar is None:
                            onzichtbaar = kandidaat
                return zichtbaar or onzichtbaar

            LOG.info("Startknop zoeken en op resultaten wachten (max %ds) ...", timeout)
            # Hoogstens drie klikken, en pas opnieuw na een ruime wachttijd.
            # Blijven klikken is geen betere strategie: de startknop hoort bij
            # een paneel dat open- en dichtklapt, dus een tweede klik kan het
            # formulier juist weer sluiten. Drie pogingen dekt het geval waarin
            # de eerste klik in een hertekening verloren ging.
            MAX_KLIKKEN = 3
            gestart = time.monotonic()
            gevonden = False
            pogingen = 0
            while time.monotonic() - gestart < timeout and pogingen < MAX_KLIKKEN:
                try:
                    btn = _zoek_startknop()
                    if btn is not None:
                        pogingen += 1
                        driver.execute_script(
                            "arguments[0].scrollIntoView({block:'center'});", btn
                        )
                        time.sleep(0.3)
                        try:
                            btn.click()
                        except Exception:
                            driver.execute_script("arguments[0].click();", btn)
                        LOG.debug("Startknop geklikt (poging %d).", pogingen)
                except StaleElementReferenceException:
                    # Het paneel hertekende juist nu; volgende ronde opnieuw.
                    pass
                except Exception as exc:
                    LOG.debug("Startknop klikken mislukte: %s", exc)

                # Ruim wachten voordat we een tweede keer klikken: de
                # resultatenlijst laadt lui en heeft op een trage verbinding
                # tientallen seconden nodig.
                geduld = max(10.0, (timeout - (time.monotonic() - gestart)) / 2)
                verstreken = 0.0
                while verstreken < geduld:
                    if driver.find_elements(By.CLASS_NAME, "resultitem"):
                        gevonden = True
                        break
                    time.sleep(0.5)
                    verstreken += 0.5
                if gevonden:
                    break

            if not gevonden:
                # vtest.be weigert stil te submitten wanneer een veld ontbreekt
                # of ongeldig is: er verschijnt dan een validatiemelding in de
                # pagina en verder niets. Zonder die tekst mee te geven ziet elk
                # formulierprobleem eruit als "site onbereikbaar".
                meldingen: list[str] = []
                try:
                    tekst = driver.execute_script("return document.body.innerText") or ""
                    for regel in tekst.split("\n"):
                        regel = regel.strip()
                        if regel and any(
                            woord in regel.lower()
                            for woord in ("verplicht", "ongeldig", "gelieve", "moet je")
                        ):
                            meldingen.append(regel[:160])
                except Exception:
                    pass
                if meldingen:
                    raise VTestDownloadError(
                        f"vtest.be toonde geen resultaten na {timeout}s ondanks "
                        f"{pogingen} klik(ken); het formulier is waarschijnlijk "
                        "geweigerd. Meldingen op de pagina: "
                        + " | ".join(dict.fromkeys(meldingen))[:600]
                    )
                raise VTestDownloadError(
                    f"Geen resultaten verschenen na {timeout}s ({pogingen} "
                    "klik(ken) op de startknop). Controleer of vtest.be "
                    "bereikbaar is."
                )
            LOG.info("Resultaten geladen na %d klik(ken).", pogingen)

            # Alle resultaten in beeld scrollen.
            #
            # De lijst laadt lui bij. Met drie ronden geduld van één seconde
            # stopte het scrollen soms al na de eerste 20 resultaten: bij de
            # matrixrun van 2026-09-01 leverden zeven van de acht
            # onderneming/elektriciteit-combinaties er precies 20 op, tegenover
            # 97 bij de combinatie die los gedraaid was. Het aantal
            # combinaties dat "geslaagd" heette bleef 32.
            #
            # Meer geduld (60 rondes van 1,5s i.p.v. 50×1s) loste dit niet op:
            # een volledige matrixrun op 2026-09-02 met dezelfde code gaf
            # opnieuw exact 20 (elektriciteit) resp. 10 (gas) producten op
            # alle onderneming-combinaties, headless Chrome. Vier onafhankelijke
            # losse runs met Firefox — headless én zichtbaar, verschillende
            # postcodes — haalden telkens de volle lijst binnen (82/54). Geen
            # timingprobleem dus, maar headless Chrome die de lazy-load voor
            # segment onderneming structureel niet volledig triggert. Vandaar
            # firefox als standaard `--browser` (cli/groups.py), niet chrome.
            last_count = 0
            stable_rounds = 0
            for _ in range(60):
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(1.5)
                for sel in ("button.load-more", "button.more", "button[aria-label*='meer']"):
                    try:
                        for load_btn in driver.find_elements(By.CSS_SELECTOR, sel):
                            if load_btn.is_displayed():
                                load_btn.click()
                                time.sleep(1)
                    except Exception:
                        pass
                count = len(driver.find_elements(By.CLASS_NAME, "resultitem"))
                if count > last_count:
                    LOG.debug("Items: %d", count)
                    last_count = count
                    stable_rounds = 0
                else:
                    stable_rounds += 1
                    if stable_rounds >= 5:
                        break

            LOG.info("HTML-dump klaar (%d resultaten).", last_count)

            if contractdetails is not None:
                self._verzamel_contractdetails(
                    driver, contractdetails, reeds_gekend or set()
                )

            return driver.page_source

        finally:
            driver.quit()

    @staticmethod
    def _verzamel_contractdetails(
        driver: object,
        verzameling: dict[str, str],
        reeds_gekend: set[str],
    ) -> None:
        """Open per contract het detailpaneel en bewaar de ruwe HTML ervan.

        De datums, de doelgroep, de looptijd, de prijszekerheid en de links
        naar de tariefkaart en de algemene voorwaarden staan niet op de
        resultatenpagina; die draagt daarvoor alleen `href="#"` en
        `javascript:void(0)`. vtest.be haalt het detailpaneel per contract op
        via een POST naar /VTest/GetContractDetails, en dat endpoint heeft de
        zoekopdracht in de sessie nodig — losstaand aanroepen geeft een 500.
        De klik in de lopende sessie is daarmee de enige weg.

        Wat hier bewaard wordt is de **volledige** innerHTML van het paneel,
        niet een selectie eruit. Ontleden gebeurt achteraf door
        `VTestProductParser`, zodat een extra veld een herparse kost en geen
        nieuwe scrape van een half uur.

        Contracten die al verzameld zijn worden overgeslagen: de details zijn
        producteigenschappen en verschillen niet per postcode.
        """
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait

        knoppen = driver.find_elements(By.CSS_SELECTOR, "button.toContractDetails")
        te_doen = [
            k for k in knoppen
            if (k.get_attribute("data-contractid") or "")
            and k.get_attribute("data-contractid") not in reeds_gekend
            and k.get_attribute("data-contractid") not in verzameling
        ]
        LOG.info(
            "Contractdetails: %d van %d contracten nog op te halen.",
            len(te_doen), len(knoppen),
        )

        for index, knop in enumerate(te_doen, start=1):
            contract_id = knop.get_attribute("data-contractid")
            try:
                driver.execute_script(
                    "arguments[0].scrollIntoView({block:'center'});", knop
                )
                driver.execute_script("arguments[0].click();", knop)
                # Wachten op het paneel van dít contract, niet op "paneel niet
                # leeg": bij een klik die niet aankomt blijft de vorige inhoud
                # staan, en dan zouden de details van het vorige contract stil
                # aan dit contract gehangen worden.
                doel = f"#contractDetailsModal #contractdetail-{contract_id}"
                WebDriverWait(driver, 30).until(
                    lambda d, sel=doel: d.find_elements(By.CSS_SELECTOR, sel)
                )
                modal = driver.find_element(By.ID, "contractDetailsModal")
                verzameling[contract_id] = modal.get_attribute("innerHTML") or ""
            except Exception as exc:
                # Eén onbereikbaar detailpaneel mag de hele run niet kosten;
                # het ontbrekende contract blijft zichtbaar doordat het niet
                # in de verzameling staat.
                LOG.warning(
                    "Contractdetails voor %s niet opgehaald: %s", contract_id, exc
                )
            finally:
                VTestHtmlDownloader._sluit_modal(driver)

            if index % 25 == 0:
                LOG.info("Contractdetails: %d/%d ...", index, len(te_doen))

    @staticmethod
    def _sluit_modal(driver: object) -> None:
        from selenium.webdriver.common.by import By

        for sel in (
            "#contractDetailsModal .btn-close",
            "#contractDetailsModal [data-bs-dismiss='modal']",
        ):
            try:
                for knop in driver.find_elements(By.CSS_SELECTOR, sel):
                    if knop.is_displayed():
                        driver.execute_script("arguments[0].click();", knop)
                        return
            except Exception:
                pass
        # Terugval: het paneel leegmaken zodat de volgende wacht op nieuwe inhoud.
        try:
            driver.execute_script(
                "var m=document.getElementById('contractDetailsModal');"
                "if(m){m.innerHTML='';}"
            )
        except Exception:
            pass

    @staticmethod
    def _setup_driver(browser: str, headless: bool) -> object:
        from selenium import webdriver

        # Anti-bot: echte User-Agent gebruiken in plaats van standaard Selenium User-Agent
        REAL_USER_AGENT = (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )

        if browser == "firefox":
            from selenium.webdriver.firefox.options import Options
            opts = Options()
            if headless:
                opts.add_argument("--headless")
            opts.add_argument(f"user-agent={REAL_USER_AGENT}")
            opts.set_preference("dom.webdriver.enabled", False)
            opts.set_preference("useAutomationExtension", False)
            return webdriver.Firefox(options=opts)

        from selenium.webdriver.chrome.options import Options
        opts = Options()
        if headless:
            opts.add_argument("--headless=new")
        opts.add_argument("--window-size=1440,1200")
        opts.add_argument("--lang=nl-BE")
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        # Anti-bot protectie
        opts.add_argument(f"user-agent={REAL_USER_AGENT}")
        opts.add_argument("--disable-blink-features=AutomationControlled")
        opts.add_experimental_option("excludeSwitches", ["enable-automation"])
        opts.add_experimental_option("useAutomationExtension", False)
        return webdriver.Chrome(options=opts)
