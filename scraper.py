"""
MeterMind scraper — requests only, no Playwright/browser needed.

Step 1: POST to _getInfoByServiceAddress  -> verify account
Step 2: POST to _getInfoByAccountNumber   -> get full bill details
"""

import re
import logging
import requests
from datetime import datetime
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

BASE_URL = "https://pay.baltimorecity.gov/water"
ADDR_API = "https://pay.baltimorecity.gov/water/_getInfoByServiceAddress"
ACCT_API = "https://pay.baltimorecity.gov/water/_getInfoByAccountNumber"
TIMEOUT  = 20


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
    try:
        r = session.get(BASE_URL, timeout=TIMEOUT)
        soup = BeautifulSoup(r.text, "html.parser")
        inp = soup.find("input", {"name": "__RequestVerificationToken"})
        return inp["value"] if inp else ""
    except Exception as e:
        log.error(f"get_csrf_token error: {e}")
        return ""


def _post(session, url, token, data):
    data["__RequestVerificationToken"] = token
    return session.post(
        url, data=data,
        headers={
            "Referer": BASE_URL,
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "application/json, text/html, */*; q=0.01",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "RequestVerificationToken": token,
        },
        timeout=TIMEOUT,
    )


def _money(val):
    try:
        return float(str(val).replace("$", "").replace(",", "").strip())
    except Exception:
        return 0.0


def scrape_bill_details(session, token, account_number):
    try:
        r = _post(session, ACCT_API, token, {"AccountNumber": account_number})
        if r.status_code != 200:
            log.error(f"Bill detail HTTP {r.status_code} for {account_number}")
            return None

        body = r.text
        ct   = r.headers.get("Content-Type", "")

        # Try JSON
        if "json" in ct or body.strip().startswith(("{", "[")):
            try:
                import json
                data = json.loads(body)
                if isinstance(data, list) and data:
                    data = data[0]
                if isinstance(data, dict):
                    def g(*keys):
                        for k in keys:
                            v = data.get(k)
                            if v is not None:
                                return str(v).strip()
                        return ""
                    return {
                        "service_address":   g("serviceAddress", "ServiceAddress"),
                        "current_bill":      _money(g("currentBill", "CurrentBill", "currentBillAmount")),
                        "previous_balance":  _money(g("previousBalance", "PreviousBalance")),
                        "penalty_date":      g("penaltyDate", "PenaltyDate"),
                        "current_read_date": g("currentReadDate", "CurrentReadDate"),
                        "current_bill_date": g("currentBillDate", "CurrentBillDate"),
                        "last_pay_date":     g("lastPayDate", "LastPayDate"),
                        "last_pay_amount":   _money(g("lastPayAmount", "LastPayAmount")),
                    }
            except Exception:
                pass

        # Fall back to HTML parsing
        soup = BeautifulSoup(body, "html.parser")
        text = soup.get_text(separator="\n")

        def parse_after(label):
            m = re.search(re.escape(label) + r"[\s\n]*([\$\-0-9a-zA-Z/., ]+)", text)
            return m.group(1).strip() if m else ""

        raw_lpd = parse_after("Last Pay Date")
        last_pay_date = raw_lpd if (len(raw_lpd) == 10 and raw_lpd[2] == "/" and raw_lpd[5] == "/") else ""

        return {
            "service_address":   parse_after("Service Address"),
            "current_bill":      _money(parse_after("Current Bill Amount") or parse_after("Current Bill")),
            "previous_balance":  _money(parse_after("Previous Balance")),
            "penalty_date":      parse_after("Penalty Date"),
            "current_read_date": parse_after("Current Read Date"),
            "current_bill_date": parse_after("Current Bill Date"),
            "last_pay_date":     last_pay_date,
            "last_pay_amount":   _money(parse_after("Last Pay Amount")),
        }

    except Exception as e:
        log.error(f"scrape_bill_details error for {account_number}: {e}")
        return None


def verify_address(session, token, service_address):
    try:
        r = _post(session, ADDR_API, token, {
            "ServiceAddress": service_address.rstrip(".").strip()
        })
        if r.status_code != 200:
            return None, None
        body = r.text
        ct   = r.headers.get("Content-Type", "")
        if "json" in ct or body.strip().startswith(("[", "{")):
            import json
            items = json.loads(body)
            if not isinstance(items, list):
                items = [items]
            for item in items:
                acct = str(item.get("accountNumber", item.get("AccountNumber", ""))).strip()
                svc  = str(item.get("serviceAddress", item.get("ServiceAddress", ""))).strip()
                if acct and re.match(r"^\d{8,12}$", acct):
                    return acct, svc
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


def scrape_property(prop, session, token):
    log.info(f"Scraping: {prop.service_address} ({prop.account_number})")
    details = scrape_bill_details(session, token, prop.account_number)
    if not details:
        return None
    details["last_scraped_at"] = datetime.utcnow()
    details["scrape_status"]   = "ok"
    return details
