import pytest
from backend import drafts
from backend.parser import parse_case
from backend.ecourts import parse_options

SAMPLE = """
<table class="case_details_table"><tr><td>Case Type</td><td>: CS (COMM)</td></tr>
<tr><td>CNR Number</td><td>DLST010000012024</td></tr></table>
<table class="case_status_table"><tr><td>Next Hearing Date</td><td>: 12th Nov 2026</td></tr></table>
<span class="Petitioner_Advocate_table">1) PUNJAB NATIONAL BANK<br>Advocate- A Kumar</span>
<span class="Respondent_Advocate_table">1) SUNIL KUMAR</span>
<table class="history_table"><tr><th>Judge</th><th>Hearing Date</th></tr><tr><td>J1</td><td>01-01-2025</td></tr></table>
<table class="order_table"><tr><th>Order Number</th><th>Order Date</th><th>Details</th></tr>
<tr><td>1</td><td>01-01-2025</td><td><a onclick="displayPdf('home/display_pdf&filename=x.pdf')">Order</a></td></tr></table>
"""

def test_parse_case():
    c = parse_case(SAMPLE)
    assert c["title"] == "PUNJAB NATIONAL BANK vs SUNIL KUMAR"
    assert c["petitioners"][0]["advocate"] == "A Kumar"
    assert c["status"]["Next Hearing Date"] == "12th Nov 2026"
    assert c["orders"][0]["links"][0]["url"].endswith("filename=x.pdf")

def test_parse_empty_is_safe():
    assert parse_case("")["orders"] == []

def test_options_skip_placeholder():
    assert parse_options("<option value=''>Select</option><option value='1'>A</option>") == [{"value": "1", "label": "A"}]

@pytest.mark.parametrize("t", list(drafts.TEMPLATES))
def test_every_template_renders(t):
    out = drafts.generate(t, {"court": "District Judge", "petitioner_name": "a", "respondent_name": "b", "facts": "one\n\n two "})
    assert "1. one" in out["text"] and "2. two" in out["text"]

def test_missing_fields_reported_together():
    with pytest.raises(ValueError) as e:
        drafts.generate("plaint", {"court": "  "})
    assert "petitioner_name" in str(e.value) and "facts" in str(e.value)
