from __future__ import annotations
import csv, io, json, logging, re, time, urllib.parse, urllib.request
from pathlib import Path
from typing import Any, Iterable
LOG = logging.getLogger(__name__)

class VTestScraper:
    """Best-effort scraper. Bewaart HTML en parseert contractkaarten; selectorwijzigingen geven een duidelijke fout."""
    URL="https://www.vtest.be/"
    def snapshot(self,out:Path,postcode:str,headless=True)->Path:
        from selenium import webdriver
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        opts=webdriver.ChromeOptions()
        if headless:opts.add_argument("--headless=new")
        opts.add_argument("--window-size=1600,1400"); opts.add_argument("--no-sandbox")
        driver=webdriver.Chrome(options=opts)
        try:
            driver.get(self.URL); wait=WebDriverWait(driver,30)
            # Cookie banners
            for sel in ["#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll","#onetrust-accept-btn-handler"]:
                try: driver.find_element(By.CSS_SELECTOR,sel).click(); break
                except Exception: pass
            # vtest requires a multi-step profile; fill postal select where present, then click visible compare button.
            driver.execute_script("""const p=arguments[0],s=document.querySelector('#PostalCode');if(s){let o=[...s.options].find(x=>x.textContent.trim().startsWith(p+' - ')||x.value===p);if(o){s.value=o.value;s.dispatchEvent(new Event('change',{bubbles:true}));}}""",postcode)
            for _ in range(6):
                buttons=driver.find_elements(By.CSS_SELECTOR,"button.submitform:not(.submitformupload),button[type=submit]")
                visible=[b for b in buttons if b.is_displayed() and b.is_enabled()]
                if visible:
                    driver.execute_script("arguments[0].click()",visible[0]); time.sleep(2)
                if driver.find_elements(By.CSS_SELECTOR,"div.resultitem[data-contractid]"):break
            wait.until(lambda d: len(d.find_elements(By.CSS_SELECTOR,"div.resultitem[data-contractid]"))>0)
            out.parent.mkdir(parents=True,exist_ok=True); out.write_text(driver.page_source,encoding="utf-8")
            return out
        finally: driver.quit()

    @staticmethod
    def parse(path:Path)->list[dict]:
        from bs4 import BeautifulSoup
        soup=BeautifulSoup(path.read_text(encoding="utf-8",errors="replace"),"lxml"); out=[]
        for el in soup.select("div.resultitem[data-contractid]"):
            text=norm(el.get_text(" "))
            supplier=norm((el.select_one(".supplier-name") or el.select_one(".resultitemlogo img") or {}).get("alt","") if hasattr((el.select_one(".supplier-name") or el.select_one(".resultitemlogo img") or {}),"get") else "")
            product=norm((el.select_one("h3,h4")).get_text(" ") if el.select_one("h3,h4") else "")
            price=el.select_one("[data-price]")
            out.append({"id":el.get("data-contractid"),"supplier":supplier,"product":product,"display_price":price.get("data-price") if price else None,"text":text})
        if not out: raise ValueError("Geen V-test resultaatkaarten gevonden; controleer snapshot/selectors")
        return out
