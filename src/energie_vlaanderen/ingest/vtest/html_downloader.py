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
        headless: bool = True,
        browser: str = "chrome",
        timeout: int = 60,
    ) -> str:
        """Navigeer naar vtest.be, vul het formulier in en retourneer de volledige HTML."""
        try:
            from selenium import webdriver
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

            # Postcode invoeren
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
                postcode_field.send_keys(Keys.ENTER)
                time.sleep(1.0)

                try:
                    opts = driver.find_elements(By.XPATH, f"//*[contains(text(), '{postcode}')]")
                    if opts:
                        opts[0].click()
                        time.sleep(1.0)
                except Exception:
                    pass

                LOG.info("Postcode %s ingevuld.", postcode)
            else:
                LOG.warning("Postcode-invoerveld niet gevonden.")

            # Elektriciteit-tab selecteren
            try:
                el = driver.find_element(By.ID, "EnergyTypeElectricity")
                if not el.is_selected():
                    el.click()
            except Exception:
                pass

            # Submit-knop zoeken en klikken
            btn = None
            invisible = None
            for candidate in driver.find_elements(
                By.CSS_SELECTOR, "button, input[type='submit'], a.btn, [role='button']"
            ):
                text = (
                    (candidate.get_attribute("textContent") or "")
                    + " "
                    + (candidate.get_attribute("value") or "")
                ).strip().lower()
                if any(kw in text for kw in _SUBMIT_KEYWORDS):
                    if candidate.is_displayed() and candidate.is_enabled():
                        btn = candidate
                        break
                    elif not invisible:
                        invisible = candidate

            if not btn:
                btn = invisible

            if btn:
                driver.execute_script("arguments[0].scrollIntoView({block:'center'});", btn)
                time.sleep(0.5)
                try:
                    btn.click()
                except Exception:
                    driver.execute_script("arguments[0].click();", btn)
                LOG.info("Startknop geklikt.")
            else:
                LOG.warning("Geen startknop gevonden.")

            # Wachten op resultaten
            LOG.info("Wachten op resultaten (max %ds) ...", timeout)
            try:
                WebDriverWait(driver, timeout).until(
                    EC.presence_of_element_located((By.CLASS_NAME, "resultitem"))
                )
                LOG.info("Resultaten geladen.")
            except Exception as exc:
                raise VTestDownloadError(
                    f"Geen resultaten verschenen na {timeout}s. "
                    "Controleer of vtest.be bereikbaar is."
                ) from exc

            # Alle resultaten in beeld scrollen
            last_count = 0
            stable_rounds = 0
            for _ in range(50):
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(1)
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
                    if stable_rounds >= 3:
                        break

            LOG.info("HTML-dump klaar (%d resultaten).", last_count)
            return driver.page_source

        finally:
            driver.quit()

    @staticmethod
    def _setup_driver(browser: str, headless: bool) -> object:
        from selenium import webdriver

        if browser == "firefox":
            from selenium.webdriver.firefox.options import Options
            opts = Options()
            if headless:
                opts.add_argument("--headless")
            return webdriver.Firefox(options=opts)

        from selenium.webdriver.chrome.options import Options
        opts = Options()
        if headless:
            opts.add_argument("--headless=new")
        opts.add_argument("--window-size=1440,1200")
        opts.add_argument("--lang=nl-BE")
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        return webdriver.Chrome(options=opts)
