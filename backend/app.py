"""
FastAPI app: JSON API for both tasks + serves the static frontend.

Design notes
* One FastAPI service serves API and UI -> one deployment, no CORS to manage.
* eCourts sessions (cookie jar + app_token + captcha) live in an in-memory
  dict keyed by a random id the browser holds. Trade-off: simple, but state is
  lost on restart and does not scale past ONE worker. Fine for this scope;
  production would use Redis. TTL + size cap prevent unbounded memory growth.
* Blocking `requests` calls run in FastAPI's threadpool because these are
  plain `def` endpoints (async def + requests would block the event loop).
"""
import base64
import re
import threading
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import drafts
from .ecourts import EcourtsError, Session
from .parser import parse_case

app = FastAPI(title="Legal Suite")

SESSIONS: dict[str, Session] = {}
LOCK = threading.Lock()
TTL, MAX_SESSIONS = 600, 200

CNR_RE = re.compile(r"^[A-Z]{4}\d{12}$")  # 4 letters + 12 digits = 16 chars


def get_session(sid: str) -> Session:
    with LOCK:
        now = time.time()
        for k in [k for k, s in SESSIONS.items() if now - s.created > TTL]:
            del SESSIONS[k]
        s = SESSIONS.get(sid)
    if not s:
        raise HTTPException(410, "Session expired - reload the captcha.")
    return s


def portal(fn):
    """Run a portal call and map failures to clean HTTP errors."""
    try:
        return fn()
    except EcourtsError as e:
        raise HTTPException(422, str(e))       # user-fixable (captcha, no record)
    except Exception as e:                      # network / portal down
        raise HTTPException(502, f"eCourts portal error: {e}")


# ---- Task 1 -----------------------------------------------------------------
@app.post("/api/session")
def new_session():
    """Start a portal session and return its captcha."""
    s = Session()
    portal(s.bootstrap)
    with LOCK:
        if len(SESSIONS) >= MAX_SESSIONS:
            raise HTTPException(503, "Busy, try again shortly.")
        sid = uuid.uuid4().hex
        SESSIONS[sid] = s
    png = portal(s.captcha_png)
    return {"sid": sid, "states": s.states(),
            "captcha": "data:image/png;base64," + base64.b64encode(png).decode()}


@app.get("/api/captcha/{sid}")
def captcha(sid: str):
    png = portal(get_session(sid).captcha_png)
    return {"captcha": "data:image/png;base64," + base64.b64encode(png).decode()}


@app.get("/api/options/{sid}")
def options(sid: str, level: str, state: str = "", dist: str = "",
            complex: str = "", est: str = ""):
    s = get_session(sid)
    table = {
        "districts": lambda: s.districts(state),
        "complexes": lambda: s.complexes(state, dist),
        "establishments": lambda: s.establishments(state, dist, complex),
        "case_types": lambda: s.case_types(state, dist, complex, est),
    }
    if level not in table:
        raise HTTPException(400, "bad level")
    return portal(table[level])


class CnrReq(BaseModel):
    sid: str
    cnr: str
    captcha: str = Field(min_length=1)


@app.post("/api/search/cnr")
def search_cnr(req: CnrReq):
    cnr = req.cnr.strip().upper()
    if not CNR_RE.match(cnr):  # fail fast: don't burn a captcha on bad input
        raise HTTPException(422, "CNR must be 16 characters: 4 letters + 12 digits.")
    html = portal(lambda: get_session(req.sid).search_cnr(cnr, req.captcha.strip()))
    case = parse_case(html)
    case["cnr"] = cnr
    return case


class CaseReq(BaseModel):
    sid: str
    captcha: str = Field(min_length=1)
    state_code: str
    dist_code: str
    complex_code: str
    est_code: str
    case_type: str
    case_no: str
    year: str


@app.post("/api/search/case")
def search_case(req: CaseReq):
    if not (req.case_no.strip().isdigit() and re.fullmatch(r"\d{4}", req.year.strip())):
        raise HTTPException(422, "Case number must be numeric and year 4 digits.")
    f = req.model_dump()
    pages = portal(lambda: get_session(req.sid).search_case_number(f, req.captcha.strip()))
    return {"results": [parse_case(p) for p in pages]}


# ---- Task 2 -----------------------------------------------------------------
@app.get("/api/templates")
def templates():
    return drafts.list_templates()


@app.post("/api/draft/{template_id}")
def draft(template_id: str, data: dict):
    try:
        return drafts.generate(template_id, data)
    except ValueError as e:
        raise HTTPException(422, str(e))


@app.get("/healthz")
def health():
    return {"ok": True}


# Mounted last so /api/* routes win over the catch-all static mount.
app.mount("/", StaticFiles(directory=Path(__file__).parent.parent / "static", html=True))
