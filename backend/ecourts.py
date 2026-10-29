"""
eCourts (District Courts, v6) client -- reproduces the browser's request flow.

DESIGN NOTES (the "why" the assignment asks for)
------------------------------------------------
* The portal is a server-rendered PHP app driven by jQuery AJAX. Every call is
  POST ?p=<module>/<action> with form-encoded data and returns JSON that wraps
  an HTML fragment. Three things must be replicated for a call to be accepted:
    1. the session cookie (set on the first GET of the home page),
    2. `app_token`: a rolling CSRF-style token. Each JSON response returns a
       fresh one and the NEXT request must send that one, so Session.post()
       always stores the latest token. Reusing a stale token is the #1 cause of
       "invalid request" errors.
    3. a captcha value that belongs to THIS cookie session.
* CAPTCHA: I deliberately do NOT auto-solve it (no OCR / solver service). The
  captcha is the portal's access control; bypassing it is against the spirit
  of the site and brittle. Instead the captcha image is fetched inside the
  same session and shown to a human in the frontend; the typed value is sent
  back. Trade-off: one human step per search, but robust and above board.
* Because the captcha is tied to the cookie jar, the backend keeps one
  `Session` per browser user (see app.py) between "show captcha" and "search".
* Endpoint names/field names are kept in ONE place (ROUTES / payload dicts) so
  that if the portal renames something there is a single line to fix.
  >>> VERIFY each against DevTools > Network before submitting. <<<
"""
import random
import re
import time

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

BASE = "https://services.ecourts.gov.in/ecourtindia_v6/"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

ROUTES = {
    "districts": "casestatus/fillDistrict",
    "complexes": "casestatus/fillcomplex",
    "establishments": "casestatus/fillCourtEstablishment",
    "case_types": "casestatus/fillCaseType",
    "by_cnr": "cnr_status/searchByCNR",
    "by_case_no": "casestatus/submitCaseNo",
    "history": "home/viewHistory",
}
CAPTCHA_PATH = "vendor/securimage/securimage_show.php"


class EcourtsError(Exception):
    """Portal-level failure (bad captcha, no record, blocked, schema change)."""


def parse_options(html: str):
    """<option value=x>label</option> -> [{'value','label'}], skipping the
    empty 'Select ...' placeholder."""
    soup = BeautifulSoup(html or "", "html.parser")
    return [{"value": o.get("value", ""), "label": o.get_text(strip=True)}
            for o in soup.find_all("option") if o.get("value", "").strip()]


def _first_html(js: dict) -> str:
    """The portal wraps its HTML under a different key per endpoint
    (dist_list, complex_list, data_list ...). Rather than hard-code every key,
    take the first string value that looks like HTML. Trade-off: slightly
    magical, but survives key renames."""
    for k, v in js.items():
        if k != "app_token" and isinstance(v, str) and "<" in v:
            return v
    return ""


class Session:
    def __init__(self):
        self.http = requests.Session()
        # Retry transient gateway errors. The portal is slow/flaky under load.
        # We retry on 502/503/504 only: those fail before the app consumes the
        # single-use captcha, so a retry cannot burn it.
        retry = Retry(total=3, backoff_factor=1.0,
                      status_forcelist=[502, 503, 504], allowed_methods=None)
        self.http.mount("https://", HTTPAdapter(max_retries=retry))
        self.http.headers.update({
            "User-Agent": UA,
            "Referer": BASE,
            "Origin": "https://services.ecourts.gov.in",
            "X-Requested-With": "XMLHttpRequest",
        })
        self.app_token = ""
        self.states_html = ""
        self.created = time.time()

    # -- low level ---------------------------------------------------------
    def bootstrap(self):
        """GET the home page: sets the cookie, gives the first app_token and
        the (static) list of states."""
        r = self.http.get(BASE, timeout=30)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        tok = soup.find("input", {"id": "app_token"})
        self.app_token = tok.get("value", "") if tok else ""
        sel = soup.find("select", {"id": "sess_state_code"})
        self.states_html = str(sel) if sel else ""
        if not self.states_html:
            # Edge case: maintenance / WAF page instead of the real app.
            raise EcourtsError("eCourts home page did not load as expected "
                               "(maintenance or blocked).")

    def post(self, route: str, data: dict):
        payload = {**data, "ajax_req": "true", "app_token": self.app_token}
        r = self.http.post(f"{BASE}?p={route}", data=payload, timeout=45)
        r.raise_for_status()
        try:
            js = r.json()
        except ValueError:
            raise EcourtsError("Portal returned non-JSON (session expired or "
                               "request rejected).")
        # Rolling token: always keep the newest one.
        if js.get("app_token"):
            self.app_token = js["app_token"]
        # User-facing problems (wrong captcha, no record) come inside a 200.
        err = js.get("errormsg") or js.get("error")
        if err:
            raise EcourtsError(re.sub("<[^>]+>", "", str(err)).strip())
        return js

    def captcha_png(self) -> bytes:
        r = self.http.get(f"{BASE}{CAPTCHA_PATH}",
                          params={"t": random.random()}, timeout=30)
        r.raise_for_status()
        if "image" not in r.headers.get("Content-Type", ""):
            raise EcourtsError("Captcha endpoint did not return an image.")
        return r.content

    # -- cascading dropdowns ----------------------------------------------
    def states(self):
        return parse_options(self.states_html)

    def districts(self, state):
        return parse_options(_first_html(
            self.post(ROUTES["districts"], {"state_code": state})))

    def complexes(self, state, dist):
        # option values look like "<complex_code>@<est codes>@<flag>"; the raw
        # value is passed through so the frontend stays dumb.
        return parse_options(_first_html(self.post(
            ROUTES["complexes"], {"state_code": state, "dist_code": dist})))

    def establishments(self, state, dist, complex_code):
        return parse_options(_first_html(self.post(
            ROUTES["establishments"],
            {"state_code": state, "dist_code": dist,
             "court_complex_code": complex_code.split("@")[0]})))

    def case_types(self, state, dist, complex_code, est):
        return parse_options(_first_html(self.post(
            ROUTES["case_types"],
            {"state_code": state, "dist_code": dist,
             "court_complex_code": complex_code.split("@")[0],
             "est_code": est})))

    # -- searches ----------------------------------------------------------
    def search_cnr(self, cnr: str, captcha: str) -> str:
        js = self.post(ROUTES["by_cnr"],
                       {"cnr_number": cnr, "fcaptcha_code": captcha})
        html = _first_html(js)
        if not html:
            raise EcourtsError("No case found for this CNR.")
        return html

    def search_case_number(self, f: dict, captcha: str, limit: int = 5):
        """Case-number search returns a LIST of matches (a number can exist in
        several establishments / old+new numbering); for each we call
        viewHistory to fetch the full case page. `limit` stops a very wide
        result set from hammering the portal."""
        complex_code = f["complex_code"].split("@")[0]
        js = self.post(ROUTES["by_case_no"], {
            "court_code": f["est_code"], "state_code": f["state_code"],
            "dist_code": f["dist_code"], "court_complex_code": complex_code,
            "est_code": f["est_code"], "case_type": f["case_type"],
            "case_no": f["case_no"], "rgyear": f["year"],
            "caseNoType": "new", "displayOldCaseNo": "NO",
            "captcha": captcha,
        })
        html = _first_html(js)
        # The "View" buttons carry the args for
        # viewHistory(case_no, cino, court_code, hearing_date, ...)
        calls = re.findall(r"viewHistory\(([^)]*)\)", html)
        if not calls:
            raise EcourtsError("No matching case for these details.")
        pages = []
        for raw in calls[:limit]:
            a = [x.strip().strip("'\"") for x in raw.split(",")]
            h = self.post(ROUTES["history"], {
                "court_code": a[2] if len(a) > 2 else f["est_code"],
                "state_code": f["state_code"], "dist_code": f["dist_code"],
                "court_complex_code": complex_code,
                "case_no": a[0], "cino": a[1],
                "hearing_date": a[3] if len(a) > 3 else "",
                "search_flag": "CScaseNumber", "search_by": "CScaseNumber",
            })
            pages.append(_first_html(h))
        return pages
