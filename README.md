* **Task 1** - search a District Court case by **CNR** or by **State/District/Complex/Establishment/Case type/No./Year**; returns structured JSON (details, filing/registration, parties + advocates, acts, hearing history, status, orders with PDF links) and renders it in the UI.
* **Task 2** - rule-based legal draft generator (plaint, legal notice, bail application, affidavit). Pure Python, no LLM, no external API.

One FastAPI service serves both the API and the static frontend.

## Run locally
```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn backend.app:app --reload --port 8000
# open http://localhost:8000
pytest -q          # parser + draft generator tests (no network needed)
```

## Deploy (Render, free tier)
New Web Service -> connect the repo ->
* Build: `pip install -r requirements.txt`
* Start: `uvicorn backend.app:app --host 0.0.0.0 --port $PORT --workers 1`
(Keep `--workers 1`: eCourts sessions are held in process memory.)

## How the eCourts flow is reproduced
1. `GET /ecourtindia_v6/` -> session cookie, first `app_token`, state list.
2. Captcha image fetched **inside that same session** and shown to the user.
3. Dropdown cascade: `fillDistrict` -> `fillcomplex` -> `fillCourtEstablishment` -> `fillCaseType` (POST, form-encoded, JSON-wrapped HTML).
4. Search: `cnr_status/searchByCNR` or `casestatus/submitCaseNo` (+ `home/viewHistory` per match).
5. Every response carries a fresh `app_token`; the client always sends the latest.
6. HTML is parsed into JSON by `backend/parser.py`.

**Captcha:** solved by the human user in the UI, not bypassed. Trade-off: one manual step per search, in exchange for staying within the portal's access control.

## Layout
`backend/ecourts.py` portal client - `backend/parser.py` HTML->JSON - `backend/drafts.py` templates - `backend/app.py` API - `static/index.html` UI - `tests/`.

## Known limitations
* Sessions are in-memory (single worker). Use Redis to scale.
* Portal markup varies by state; the parser is class-based and tolerant, missing sections come back empty.
* Order PDFs are returned as links; opening them may need a live session/captcha on the portal.
