"""
Legal draft template generator -- pure Python, no LLM, no external API.

DESIGN NOTES
------------
* Deterministic by design: same inputs -> same draft. A legal draft must be
  reproducible and auditable, which is exactly what an LLM is not.
* Each template is DATA (title, required fields, section builders) rather
  than one giant f-string, so adding a template is ~15 lines.
* The user's facts are NOT rewritten (we would need NLP for that); they are
  numbered into paragraphs verbatim. Trade-off: less "magic", but we never
  distort what the client actually said.
* Validation reports ALL missing fields at once (better UX than one-by-one).
* Edge cases: blank/whitespace input, facts given as one multi-line string,
  one vs many parties ("& Ors."), missing optional fields, HTML-unsafe text
  (we return plain text; the frontend renders it with textContent).
* Output is structured ({sections: [...]}) AND rendered text, so the UI can
  show sections separately and offer a single download.
"""
from datetime import date

COMMON_REQUIRED = ["court", "petitioner_name", "respondent_name", "facts"]


def _lines(v):
    """Accept a list or a newline-separated string; drop blanks."""
    if isinstance(v, str):
        v = v.splitlines()
    return [str(x).strip() for x in (v or []) if str(x).strip()]


def _numbered(items):
    return "\n".join(f"{i}. {t}" for i, t in enumerate(items, 1))


def _party(name, desc="", address=""):
    bits = [name.strip().upper()]
    if desc:
        bits.append(desc.strip())
    if address:
        bits.append(f"R/o {address.strip()}")
    return ", ".join(bits)


def _cause_title(d, a_role, b_role):
    n = d.get("num_respondents", 1)
    more = " & Ors." if str(n).isdigit() and int(n) > 1 else ""
    return (f"{_party(d['petitioner_name'], d.get('petitioner_desc'), d.get('petitioner_address'))}"
            f"  ...{a_role}\n\n                    VERSUS\n\n"
            f"{_party(d['respondent_name'], d.get('respondent_desc'), d.get('respondent_address'))}"
            f"{more}  ...{b_role}")


def _signature(d):
    return (f"Place: {d.get('place', '__________')}\n"
            f"Date: {d.get('date') or date.today().strftime('%d-%m-%Y')}\n\n"
            f"{(d.get('advocate') or '(Advocate)').strip()}\n"
            f"Counsel for the {d.get('signer_role', 'Petitioner')}")


# ---- templates --------------------------------------------------------------
def _plaint(d):
    return [
        ("Court", f"IN THE COURT OF {d['court'].upper()}"),
        ("Case Number", f"{d.get('case_type', 'CS')} No. {d.get('case_no', '____')} of {d.get('year', date.today().year)}"),
        ("Cause Title", _cause_title(d, "Plaintiff", "Defendant")),
        ("Heading", f"PLAINT UNDER ORDER VII RULE 1 OF THE CODE OF CIVIL PROCEDURE, 1908"
                    + (f" FOR {d['subject'].upper()}" if d.get("subject") else "")),
        ("Facts", "The Plaintiff most respectfully submits as under:\n\n"
                  + _numbered(_lines(d["facts"]))),
        ("Jurisdiction", d.get("jurisdiction") or
         "That this Hon'ble Court has territorial and pecuniary jurisdiction "
         "to entertain and try the present suit."),
        ("Cause of Action", d.get("cause_of_action") or
         "That the cause of action arose on the dates mentioned above and is continuing."),
        ("Valuation", f"That the suit is valued at Rs. {d.get('value', '________')}/- for the purposes of court fee and jurisdiction."),
        ("Prayer", "It is, therefore, most respectfully prayed that this Hon'ble Court may be pleased to:\n"
                   + "\n".join(f"({chr(97 + i)}) {r}" for i, r in enumerate(_lines(d.get("relief")) or ["pass such order as deemed fit"]))
                   + "\n(z) award costs of the suit and pass any other order in the interest of justice."),
        ("Signature", _signature({**d, "signer_role": "Plaintiff"})),
    ]


def _notice(d):
    return [
        ("Heading", "LEGAL NOTICE"),
        ("Date & Mode", f"Date: {d.get('date') or date.today().strftime('%d-%m-%Y')}\n"
                       f"Via: {d.get('mode', 'Registered Post A.D. / Speed Post / Email')}"),
        ("To", _party(d["respondent_name"], d.get("respondent_desc"), d.get("respondent_address"))),
        ("Subject", f"Legal notice{(' for ' + d['subject']) if d.get('subject') else ''}"),
        ("Body", f"Under instructions from and on behalf of my client, "
                 f"{_party(d['petitioner_name'], d.get('petitioner_desc'), d.get('petitioner_address'))}, "
                 "I hereby serve upon you the following notice:\n\n"
                 + _numbered(_lines(d["facts"]))),
        ("Demand", "You are hereby called upon to comply with the following within "
                   f"{d.get('days', 15)} days of receipt of this notice:\n"
                   + _numbered(_lines(d.get("relief")) or ["Comply with the lawful demands of my client."])),
        ("Consequence", "Failing which, my client shall be constrained to initiate appropriate civil and/or "
                        "criminal proceedings against you at your risk as to costs and consequences."),
        ("Signature", _signature({**d, "signer_role": "Petitioner"})),
    ]


def _bail(d):
    return [
        ("Court", f"IN THE COURT OF {d['court'].upper()}"),
        ("Case Number", f"Bail Application No. {d.get('case_no', '____')} of {d.get('year', date.today().year)}\n"
                       f"FIR No. {d.get('fir_no', '____')}  Police Station: {d.get('police_station', '____')}\n"
                       f"Under Sections: {d.get('sections', '____')}"),
        ("Cause Title", _cause_title(d, "Applicant/Accused", "Respondent/State")),
        ("Heading", "APPLICATION FOR REGULAR BAIL UNDER SECTION 483 OF THE BHARATIYA NAGARIK SURAKSHA SANHITA, 2023"),
        ("Grounds", "The Applicant most respectfully submits:\n\n" + _numbered(_lines(d["facts"]))),
        ("Prayer", "It is, therefore, prayed that the Applicant be released on bail on such terms and conditions as this Hon'ble Court deems fit.\n"
                   + "\n".join(f"- {r}" for r in _lines(d.get("relief")))),
        ("Signature", _signature({**d, "signer_role": "Applicant"})),
    ]


def _affidavit(d):
    return [
        ("Court", f"IN THE COURT OF {d['court'].upper()}"),
        ("Cause Title", _cause_title(d, "Petitioner", "Respondent")),
        ("Heading", f"AFFIDAVIT OF {d['petitioner_name'].upper()}"),
        ("Deponent", f"I, {_party(d['petitioner_name'], d.get('petitioner_desc'), d.get('petitioner_address'))}, "
                     "do hereby solemnly affirm and state on oath as under:"),
        ("Facts", _numbered(_lines(d["facts"]))),
        ("Verification", f"Verified at {d.get('place', '__________')} on this "
                         f"{d.get('date') or date.today().strftime('%d-%m-%Y')} that the contents of the above "
                         "affidavit are true and correct to my knowledge and belief and nothing material has "
                         "been concealed therefrom."),
        ("Deponent Signature", "DEPONENT"),
    ]


TEMPLATES = {
    "plaint": {"title": "Plaint (Civil Suit)", "build": _plaint,
               "extra": ["case_type", "case_no", "year", "subject", "value", "jurisdiction",
                         "cause_of_action", "relief"]},
    "legal_notice": {"title": "Legal Notice", "build": _notice,
                     "extra": ["subject", "days", "mode", "relief"]},
    "bail_application": {"title": "Bail Application", "build": _bail,
                         "extra": ["case_no", "year", "fir_no", "police_station", "sections", "relief"]},
    "affidavit": {"title": "Affidavit", "build": _affidavit, "extra": []},
}


def list_templates():
    return [{"id": k, "title": v["title"], "required": COMMON_REQUIRED, "optional": v["extra"]
             + ["petitioner_desc", "petitioner_address", "respondent_desc", "respondent_address",
                "num_respondents", "place", "date", "advocate"]}
            for k, v in TEMPLATES.items()]


def generate(template_id: str, data: dict) -> dict:
    if template_id not in TEMPLATES:
        raise ValueError(f"Unknown template '{template_id}'.")
    d = {k: (v.strip() if isinstance(v, str) else v) for k, v in data.items()}
    missing = [f for f in COMMON_REQUIRED
               if not (_lines(d.get(f)) if f == "facts" else d.get(f))]
    if missing:
        raise ValueError("Missing required field(s): " + ", ".join(missing))
    tpl = TEMPLATES[template_id]
    sections = [{"heading": h, "body": b} for h, b in tpl["build"](d)]
    text = "\n\n".join(s["body"] for s in sections)
    return {"template": template_id, "title": tpl["title"],
            "sections": sections, "text": text}
