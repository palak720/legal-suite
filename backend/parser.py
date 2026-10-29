"""
HTML -> structured JSON for a case page.

Design: the case page is a set of <table>s, each with a stable CSS class
(case_details_table, case_status_table, history_table ...). I parse by class
first because the portal's markup differs a little between establishments.
Every field is optional: a disposed case has no next hearing date, an old
case may have no orders, etc. -- missing sections give empty values, never
exceptions.
"""
import re
from bs4 import BeautifulSoup

BASE = "https://services.ecourts.gov.in/ecourtindia_v6/"


def _t(el) -> str:
    return re.sub(r"\s+", " ", el.get_text(" ", strip=True)).lstrip(":").strip()


def _kv(table) -> dict:
    """Label/value tables: cells alternate label, value (2 or 4 cells/row)."""
    out = {}
    for tr in table.find_all("tr"):
        cells = [_t(c) for c in tr.find_all(["td", "th"])]
        for i in range(0, len(cells) - 1, 2):
            if cells[i]:
                out[cells[i]] = cells[i + 1]
    return out


def _rows(table) -> list:
    """Header-row tables (hearing history, orders) -> list of dicts."""
    trs = table.find_all("tr")
    if not trs:
        return []
    head = [_t(c) for c in trs[0].find_all(["th", "td"])]
    rows = []
    for tr in trs[1:]:
        cells = tr.find_all("td")
        if len(cells) < 2:
            continue
        rows.append({(head[i] if i < len(head) else f"col{i}"): _t(c)
                     for i, c in enumerate(cells)})
    return rows


def _people(span) -> list:
    """'1) PUNJAB NATIONAL BANK<br>Advocate- A B' -> [{name, advocate}]."""
    lines = [l.strip() for l in span.get_text("\n").split("\n") if l.strip()]
    people = []
    for line in lines:
        if re.match(r"^\d+\)", line):
            people.append({"name": re.sub(r"^\d+\)\s*", "", line),
                           "advocate": ""})
        elif line.lower().startswith("advocate") and people:
            people[-1]["advocate"] = re.sub(r"^advocate\s*-?\s*", "", line,
                                            flags=re.I)
    return people


def _links(table) -> list:
    """Order/judgment PDF links live in onclick="displayPdf('<query>')".
    Returned as absolute URLs. Downloading the PDF still needs the live
    session, so we return the URL instead of failing silently at parse time."""
    out = []
    for a in table.find_all("a"):
        m = re.search(r"displayPdf\('([^']+)'", a.get("onclick", ""))
        if m:
            out.append({"label": _t(a), "url": f"{BASE}?p={m.group(1)}"})
    return out


def parse_case(html: str) -> dict:
    soup = BeautifulSoup(html or "", "html.parser")

    def by(cls):
        return soup.find("table", class_=re.compile(cls))

    case = {
        "case_details": _kv(by("case_details_table")) if by("case_details_table") else {},
        "status": _kv(by("case_status_table")) if by("case_status_table") else {},
        "petitioners": [], "respondents": [],
        "acts": _rows(by("acts_table")) if by("acts_table") else [],
        "hearing_history": [], "orders": [],
    }
    p = soup.find(class_=re.compile("Petitioner_Advocate_table"))
    r = soup.find(class_=re.compile("Respondent_Advocate_table"))
    case["petitioners"] = _people(p) if p else []
    case["respondents"] = _people(r) if r else []
    if by("history_table"):
        case["hearing_history"] = _rows(by("history_table"))
    for tbl in soup.find_all("table", class_=re.compile("order_table")):
        links = _links(tbl)
        rows = _rows(tbl)
        for i, row in enumerate(rows):
            row["links"] = [links[i]] if i < len(links) else []
        case["orders"] += rows
    # Convenience field matching the assignment's expected output.
    a = case["petitioners"][0]["name"] if case["petitioners"] else ""
    b = case["respondents"][0]["name"] if case["respondents"] else ""
    case["title"] = f"{a} vs {b}" if a and b else (a or b)
    return case
