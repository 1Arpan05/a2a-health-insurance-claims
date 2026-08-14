"""
Tests for document_engine.py: currency-amount parsing, bill-total
detection, and end-to-end PDF extraction + cross-check. No LLM calls
and no mocking -- this is deterministic parsing logic, tested against
real generated PDF bytes (via reportlab, a dev-only test dependency;
see requirements-dev.txt).
"""

import io

import pytest

from document_engine import (
    extract_text,
    extraction_capabilities,
    find_amounts,
    find_bill_total,
    verify_bill,
)

reportlab_canvas = pytest.importorskip("reportlab.pdfgen.canvas")


def _make_pdf(lines: list) -> bytes:
    """Generates a real single-page PDF with the given lines of text."""
    buf = io.BytesIO()
    c = reportlab_canvas.Canvas(buf)
    y = 750
    for line in lines:
        c.drawString(100, y, line)
        y -= 30
    c.save()
    return buf.getvalue()


# --------------------------------------------------------------------- find_amounts
def test_find_amounts_parses_rs_prefix():
    assert find_amounts("Room Charges: Rs. 40,000") == [40000.0]


def test_find_amounts_parses_rupee_symbol():
    assert find_amounts("Total: ₹250,000") == [250000.0]


def test_find_amounts_parses_inr_prefix():
    assert find_amounts("Amount: INR 1,500.50") == [1500.50]


def test_find_amounts_handles_multiple_amounts_in_text():
    text = "Room: Rs. 10,000\nSurgery: Rs. 50,000\nTotal: Rs. 60,000"
    assert find_amounts(text) == [10000.0, 50000.0, 60000.0]


def test_find_amounts_returns_empty_list_for_no_currency():
    assert find_amounts("Patient Name: John Doe, Age: 45") == []


def test_find_amounts_ignores_plain_numbers_without_currency_marker():
    # "45" here has no Rs/INR/₹ prefix, so it should not be picked up
    assert find_amounts("Age: 45, Room Number: 302") == []


# --------------------------------------------------------------------- find_bill_total
def test_find_bill_total_prioritizes_total_keyword_line():
    text = "Room Charges: Rs. 10,000\nMedication: Rs. 5,000\nGrand Total: Rs. 60,000"
    assert find_bill_total(text) == 60000.0


def test_find_bill_total_falls_back_to_largest_amount_when_no_keyword():
    text = "Room Charges: Rs. 10,000\nSurgery: Rs. 180,000\nMedication: Rs. 5,000"
    assert find_bill_total(text) == 180000.0


def test_find_bill_total_returns_none_when_no_amounts():
    assert find_bill_total("No currency amounts here.") is None


@pytest.mark.parametrize("keyword", ["Net Amount", "Total Amount", "Total Payable", "Amount Payable", "Bill Total"])
def test_find_bill_total_recognizes_all_total_keyword_variants(keyword):
    text = f"Room Charges: Rs. 10,000\n{keyword}: Rs. 99,000"
    assert find_bill_total(text) == 99000.0


# --------------------------------------------------------------------- extraction_capabilities
def test_extraction_capabilities_reports_pdf_support():
    caps = extraction_capabilities()
    assert caps["pdf_text_extraction"] is True  # pypdf is a hard runtime dependency
    assert "image_ocr" in caps
    assert "tesseract_binary_found" in caps


# --------------------------------------------------------------------- extract_text (real PDFs)
def test_extract_text_reads_real_pdf_with_embedded_text():
    pdf_bytes = _make_pdf(["Fortis Hospital - Final Bill", "Grand Total: Rs. 250,000"])
    result = extract_text(pdf_bytes, "bill.pdf")
    assert result["method"] == "pdf_text"
    assert "250,000" in result["text"] or "250000" in result["text"].replace(",", "")


def test_extract_text_unsupported_file_type():
    result = extract_text(b"irrelevant bytes", "notes.txt")
    assert result["method"] == "unsupported"


def test_extract_text_handles_corrupt_pdf_gracefully():
    result = extract_text(b"this is not a real pdf", "fake.pdf")
    assert result["method"] == "failed"
    assert result["text"] == ""


# --------------------------------------------------------------------- verify_bill (end-to-end)
def test_verify_bill_match_within_tolerance():
    pdf_bytes = _make_pdf(["Hospital Bill", "Grand Total: Rs. 250,000"])
    result = verify_bill(pdf_bytes, "bill.pdf", claimed_amount=250000)
    assert result["status"] == "MATCH"
    assert result["verified"] is True
    assert result["bill_total_found"] == 250000.0
    assert result["discrepancy_pct"] == 0.0


def test_verify_bill_mismatch_beyond_tolerance():
    pdf_bytes = _make_pdf(["Hospital Bill", "Grand Total: Rs. 60,000"])
    result = verify_bill(pdf_bytes, "bill.pdf", claimed_amount=80000)
    assert result["status"] == "MISMATCH"
    assert result["verified"] is False
    assert result["bill_total_found"] == 60000.0
    assert result["discrepancy_pct"] == pytest.approx(25.0)


def test_verify_bill_within_tolerance_band_still_matches():
    # 4% discrepancy is within the default 5% tolerance
    pdf_bytes = _make_pdf(["Hospital Bill", "Grand Total: Rs. 96,000"])
    result = verify_bill(pdf_bytes, "bill.pdf", claimed_amount=100000)
    assert result["status"] == "MATCH"
    assert result["discrepancy_pct"] == pytest.approx(4.0)


def test_verify_bill_no_amount_found_could_not_verify():
    pdf_bytes = _make_pdf(["Just some hospital letterhead text with no amounts."])
    result = verify_bill(pdf_bytes, "bill.pdf", claimed_amount=50000)
    assert result["status"] == "COULD NOT VERIFY"
    assert result["bill_total_found"] is None


def test_verify_bill_corrupt_file_could_not_verify():
    result = verify_bill(b"not a real pdf", "bill.pdf", claimed_amount=50000)
    assert result["status"] == "COULD NOT VERIFY"
    assert result["extraction_method"] == "failed"
