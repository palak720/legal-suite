# Legal Suite: eCourts case scraper + legal draft generator

Two tools in one small web app:

1. **District Court case scraper**: look up a case on the eCourts services portal by **CNR number** or by **State / District / Court Complex / Establishment / Case Type / Case Number / Year**, and get the result as structured JSON (also rendered in the UI).
2. **Legal draft generator**: produces structured legal drafts (plaint, legal notice, bail application, affidavit) from form inputs. Pure Python: **no LLM, no external API**.

**Live app:** `< https://legal-suite.onrender.com>`
**Repo:** `<https://github.com/palak720/legal-suite>`

---

## Current status (please read)

| Part | Status |
|---|---|
| Draft generator (Task 2) | Complete and tested. Works live. |
| Frontend (both tasks) | Complete. |
| Parser (case page HTML to JSON) | Complete, unit-tested on a sample page. |
| eCourts request flow (Task 1) | Implemented from observed browser traffic; **see "Findings" and "Known limitations" below.** |

> EDIT THIS BLOCK to match your real result. If CNR search works end to end for you, say so and delete the caveat. If it does not, keep the honest explanation below.

---

## Quick start

```bash
git clone <repo-url> && cd legal-suite
python -m venv .venv
# Windows: .venv\Scripts\activate    Mac/Linux: source .venv/bin/activate
pip install -r requirements.txt
uvicorn backend.app:app --reload --port 8000
```

Open http://localhost:8000.

Run the tests (no network needed):

```bash
python -m pytest -q
```

## Deploy (Render)

New Web Service, connect the repo, then:

* Build command: `pip install -r requirements.txt`
* Start command: `uvicorn backend.app:app --host 0.0.0.0 --port $PORT --workers 1`

A `render.yaml` is included. Keep `--workers 1`: scraper sessions are held in process memory.

---

## Project layout

```
backend/
  app.py       FastAPI app: JSON API + serves the frontend
  ecourts.py   eCourts client (session, token, captcha, searches)
  parser.py    case-page HTML -> structured JSON
  drafts.py    rule-based draft templates
static/
  index.html   single-page UI (case search + draft generator)
tests/
  test_core.py parser, option parsing and draft tests
```

One service serves both the API and the UI, so there is a single deployment and no CORS setup.

---

## Task 1: How the eCourts flow works

The portal is a PHP app driven by jQuery AJAX. Each call is a `POST ?p=<module>/<action>` with form-encoded data; the reply is JSON wrapping an HTML fragment.

### Findings (from DevTools and the portal's own JavaScript)

* **CNR search request** (copied from the Network tab):
  `POST /ecourtindia_v6/?p=cnr_status/searchByCNR/` (note the trailing slash)
  Form fields: `cino`, `fcaptcha_code`, `ajax_req=true`, `app_token`.
  Content type `application/x-www-form-urlencoded`.
* **`app_token` is a rolling token.** `js/components.js` writes `result.app_token` from every AJAX response into a hidden `#app_token` field, and the next request sends it. The client therefore always keeps the newest token. An empty or stale token produces the portal's generic "Invalid Request" page.
* **The token is empty in the page HTML.** `js/common_header.js` calls `casestatus/getCaptcha` on page load (`refreshCaptcha('onload')`); that is the first AJAX call.
* **Captcha:** an image served from `vendor/securimage/securimage_show.php`, tied to the session cookie (`SERVICES_SESSID`).
* **Dropdown cascade** (from `common_header.js`): `casestatus/fillDistrict`, `casestatus/fillcomplex`, `casestatus/fillCourtEstablishment`, `casestatus/fillCaseType` (with `search_type=c_no`). Replies carry `status`, and the HTML under `dist_list`, `complex_list`, `establishment_list`, `casetype_list`.
* Complex dropdown values look like `code@establishment-codes@flag`; only the first part is sent as `court_complex_code`.

### Design decisions and trade-offs

* **Captcha is solved by the human user, not automated.** The captcha is the portal's access control. I did not add OCR or a solving service: it would be brittle and goes against the spirit of the site. The captcha image is fetched inside the same server-side session and shown in the UI; the typed value is sent back. Cost: one manual step per search.
* **Server-side session store** (`app.py`): the token and captcha are bound to a cookie jar, so the backend keeps one session per browser user, with a TTL and a size cap. Simple, but in-memory, so it needs a single worker (Redis would be the production answer).
* **Tolerant response handling:** the portal puts its HTML under different JSON keys per endpoint, so the client takes the