"""
MeterMind scraper
-----------------
Step 1: Verify account via the fast REST API  (no browser)
Step 2: Pull full bill details via Playwright  (only when needed)
"""

import re
import time
import logging
import requests
from datetime import datetime
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

BASE_URL = "https://pay.baltimorecity.gov/water"
API_URL  = "https://pay.baltimorecity.gov/water/_getInfoByServiceAddress"
TIMEOUT  = 15


# ── Shared requests session ────────────────────────────────────────────────────

def make_session():
    s = requests.Session()
    s.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    })
    return s


def get_csrf_token(session):
    r = session.get(BASE_URL, timeout=TIMEOUT)
    soup = BeautifulSoup(r.text, "html.parser")
    inp = soup.find("input", {"name": "__RequestVerificationToken"})
    return inp["value"] if inp else ""


# ── Step 1: Verify address via API (fast, no browser) ────────────────────────

def verify_address(session, token, service_address):
    """
    Returns (account_number, canonical_service_address) or (None, None).
    Uses the portal's AJAX endpoint — no Playwright needed.
    """
    try:
        r = session.post(
            API_URL,
            data={
                "ServiceAddress": service_address.rstrip(".").strip(),
                "__RequestVerificationToken": token,
            },
            headers={
                "Referer": BASE_URL,
                "X-Requested-With": "XMLHttpRequest",
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                "RequestVerificationToken": token,
            },
            timeout=TIMEOUT,
        )
        if r.status_code != 200:
            return None, None

        body = r.text
        ct   = r.headers.get("Content-Type", "")

        # JSON response
        if "json" in ct or body.strip().startswith(("[", "{")):
            import json
            data = json.loads(body)
            items = data if isinstance(data, list) else [data]
            for item in items:
                acct = str(item.get("accountNumber", item.get("AccountNumber", ""))).strip()
                svc  = str(item.get("serviceAddress", item.get("ServiceAddress", ""))).strip()
                if acct and re.match(r"^\d{8,12}$", acct):
                    return acct, svc

        # HTML table response
        soup = BeautifulSoup(body, "html.parser")
        for table in soup.find_all("table"):
            headers = [th.get_text(strip=True).lower() for th in table.find_all("th")]
            if not any("account" in h for h in headers):
                continue
            ai = next((i for i, h in enumerate(headers) if "account" in h), 0)
            si = next((i for i, h in enumerate(headers) if "address" in h), 1)
            for tr in table.find_all("tr")[1:]:
                cells = [td.get_text(strip=True) for td in tr.find_all("td")]
                acct = cells[ai] if ai < len(cells) else ""
                svc  = cells[si] if si < len(cells) else ""
                if acct and re.match(r"^\d{8,12}$", acct):
                    return acct, svc

    except Exception as e:
        log.error(f"verify_address error: {e}")

    return None, None


# ── Step 2: Full bill details via Playwright ──────────────────────────────────

def scrape_bill_details(account_number):
    """
    Navigates to the bill detail page for an account number.
    Returns a dict with all bill fields, or None on failure.
    """
    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page    = browser.new_page()

            try:
                page.goto(BASE_URL, timeout=30000)
                page.wait_for_timeout(1000)

                # Fill account number and submit
                acct_input = page.locator("input#accountNumber")
                acct_input.fill(account_number)

                # Get fresh CSRF token from the page
                token = page.evaluate(
                    "document.querySelector('input[name=__RequestVerificationToken]')?.value || ''"
                )

                # Submit via the form
                page.locator("#accountNumberForm button[type=submit]").click()
                page.wait_for_timeout(4000)

                body_text = page.inner_text("body")

                def parse_after(label, text):
                    pattern = re.escape(label) + r"[\s\n]*([\$\-0-9a-zA-Z/., ]+)"
                    m = re.search(pattern, text)
                    return m.group(1).strip() if m else ""

                def money(val):
                    try:
                        return float(str(val).replace("$", "").replace(",", "").strip())
                    except Exception:
                        return 0.0

                raw_last_pay_date = parse_after("Last Pay Date", body_text)
                last_pay_date = (
                    raw_last_pay_date
                    if (len(raw_last_pay_date) == 10
                        and raw_last_pay_date[2] == "/"
                        and raw_last_pay_date[5] == "/")
                    else ""
                )

                return {
                    "service_address":   parse_after("Service Address",   body_text),
                    "current_bill":      money(parse_after("Current Bill Amount", body_text) or parse_after("Current Bill", body_text)),
                    "previous_balance":  money(parse_after("Previous Balance",  body_text)),
                    "penalty_date":      parse_after("Penalty Date",      body_text),
                    "current_read_date": parse_after("Current Read Date", body_text),
                    "current_bill_date": parse_after("Current Bill Date", body_text),
                    "last_pay_date":     last_pay_date,
                    "last_pay_amount":   money(parse_after("Last Pay Amount", body_text)),
                }

            except PWTimeout:
                log.error(f"Playwright timeout for account {account_number}")
                return None
            except Exception as e:
                log.error(f"Playwright error for {account_number}: {e}")
                return None
            finally:
                browser.close()

    except ImportError:
        log.error("Playwright not installed. Run: pip install playwright && playwright install chromium")
        return None


# ── Combined scrape for one property ─────────────────────────────────────────

def scrape_property(prop, session, token):
    """
    Full scrape for a Property model instance.
    Returns a dict of updated fields, or None on failure.
    """
    log.info(f"Scraping: {prop.service_address} ({prop.account_number})")

    # Step 1: quick API verify (optional — confirms account is still active)
    # We skip this if we already have a confirmed account number
    # and go straight to bill details to save API calls

    # Step 2: Playwright for bill details
    details = scrape_bill_details(prop.account_number)
    if not details:
        return None

    details["last_scraped_at"] = datetime.utcnow()
    details["scrape_status"]   = "ok"
    return details
