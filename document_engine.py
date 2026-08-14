"""
Document extraction + cross-checking.

Reads uploaded hospital bills (PDF or image) and extracts text -- via
native PDF text extraction (pypdf, always available) or OCR (pytesseract,
only if the Tesseract binary is installed on the host). The extracted
bill total is then cross-checked against the claimed amount, so the
document agent has real evidence instead of trusting a typed "yes".

Degrades gracefully: if OCR isn't available, PDF text extraction is
still attempted and the report says so explicitly rather than failing
silently or fabricating a result.
"""

import io
import re
import shutil

try:
    from pypdf import PdfReader
    PYPDF_AVAILABLE = True
except ImportError:
    PYPDF_AVAILABLE = False

try:
    import pytesseract
    from PIL import Image
    PIL_AVAILABLE = True
    TESSERACT_AVAILABLE = shutil.which("tesseract") is not None
except ImportError:
    PIL_AVAILABLE = False
    TESSERACT_AVAILABLE = False

AMOUNT_PATTERN = re.compile(
    r"(?:Rs\.?|INR|₹)\s?([0-9]{1,3}(?:,[0-9]{2,3})*(?:\.[0-9]{1,2})?|[0-9]+(?:\.[0-9]{1,2})?)",
    re.IGNORECASE,
)

TOTAL_KEYWORDS = re.compile(
    r"(grand\s*total|net\s*amount|total\s*amount|total\s*payable|amount\s*payable|bill\s*total)",
    re.IGNORECASE,
)


def extraction_capabilities() -> dict:
    return {
        "pdf_text_extraction": PYPDF_AVAILABLE,
        "image_ocr": PIL_AVAILABLE and TESSERACT_AVAILABLE,
        "ocr_dependency_installed": PIL_AVAILABLE,
        "tesseract_binary_found": TESSERACT_AVAILABLE,
    }


def extract_text(file_bytes: bytes, filename: str) -> dict:
    """
    Returns {"text": str, "method": str, "note": str}
    method is one of: "pdf_text", "ocr", "unsupported", "failed"
    """
    ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""

    if ext == "pdf":
        if not PYPDF_AVAILABLE:
            return {"text": "", "method": "failed", "note": "pypdf not installed -- cannot read PDF."}
        try:
            reader = PdfReader(io.BytesIO(file_bytes))
            text = "\n".join((page.extract_text() or "") for page in reader.pages)
            if text.strip():
                return {"text": text, "method": "pdf_text", "note": "Extracted native PDF text."}
            # Scanned PDF with no embedded text -- would need OCR on rendered pages,
            # which requires poppler (pdf2image) in addition to Tesseract.
            return {
                "text": "",
                "method": "unsupported",
                "note": "PDF has no embedded text (likely a scanned image) and page-level OCR "
                        "is not configured in this environment.",
            }
        except Exception as e:
            return {"text": "", "method": "failed", "note": f"Could not parse PDF: {e}"}

    if ext in ("png", "jpg", "jpeg"):
        if not PIL_AVAILABLE:
            return {"text": "", "method": "failed", "note": "Pillow/pytesseract not installed -- cannot OCR image."}
        if not TESSERACT_AVAILABLE:
            return {
                "text": "",
                "method": "unsupported",
                "note": "Tesseract OCR engine is not installed on this host, so the image "
                        "could not be read. Install Tesseract to enable image OCR.",
            }
        try:
            image = Image.open(io.BytesIO(file_bytes))
            text = pytesseract.image_to_string(image)
            return {"text": text, "method": "ocr", "note": "Extracted text via OCR."}
        except Exception as e:
            return {"text": "", "method": "failed", "note": f"OCR failed: {e}"}

    return {"text": "", "method": "unsupported", "note": f"Unsupported file type: .{ext}"}


def find_amounts(text: str) -> list:
    """All currency-like amounts found in the text, as floats."""
    amounts = []
    for match in AMOUNT_PATTERN.finditer(text):
        raw = match.group(1).replace(",", "")
        try:
            amounts.append(float(raw))
        except ValueError:
            continue
    return amounts


def find_bill_total(text: str) -> float:
    """
    Best-effort: look for an amount near a 'total'-style keyword first;
    fall back to the largest amount found anywhere in the text.
    """
    for line in text.splitlines():
        if TOTAL_KEYWORDS.search(line):
            amounts = find_amounts(line)
            if amounts:
                return max(amounts)

    amounts = find_amounts(text)
    return max(amounts) if amounts else None


def verify_bill(file_bytes: bytes, filename: str, claimed_amount: float, tolerance_pct: float = 5.0) -> dict:
    """
    Cross-checks an uploaded bill against the claimed amount.
    tolerance_pct: acceptable discrepancy before flagging a mismatch.
    """
    extraction = extract_text(file_bytes, filename)
    text = extraction["text"]

    if not text.strip():
        return {
            "extraction_method": extraction["method"],
            "note": extraction["note"],
            "bill_total_found": None,
            "claimed_amount": claimed_amount,
            "verified": False,
            "discrepancy_pct": None,
            "status": "COULD NOT VERIFY",
        }

    bill_total = find_bill_total(text)
    if bill_total is None:
        return {
            "extraction_method": extraction["method"],
            "note": "Text extracted but no currency amount could be located.",
            "bill_total_found": None,
            "claimed_amount": claimed_amount,
            "verified": False,
            "discrepancy_pct": None,
            "status": "COULD NOT VERIFY",
        }

    discrepancy_pct = abs(bill_total - claimed_amount) / claimed_amount * 100 if claimed_amount else None
    verified = discrepancy_pct is not None and discrepancy_pct <= tolerance_pct

    return {
        "extraction_method": extraction["method"],
        "note": extraction["note"],
        "bill_total_found": bill_total,
        "claimed_amount": claimed_amount,
        "verified": verified,
        "discrepancy_pct": discrepancy_pct,
        "status": "MATCH" if verified else "MISMATCH",
    }
