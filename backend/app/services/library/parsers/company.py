"""Company document parsing (LIB-IDX-04) — single-purpose whole-file indexing.

Certificates, registrations and tax filings are short and serve one purpose
each. Splitting an ISO certificate into sections would produce chunks like
"Scope of certification" divorced from the certificate number, which is worse
for retrieval than keeping the document whole. So there is deliberately no
section splitting here — the whole document is one logical unit, and the
chunker only intervenes if the text exceeds one window.

What this parser adds instead is *classification*: which kind of company
document is it, and what identifiers does it carry (certificate number, validity
dates, issuing authority). Those land on the document row, where Stage 3 can
filter on them.
"""
from __future__ import annotations

import logging
import re

from app.models.enums import DocumentCategory
from app.services.library import llm
from app.services.library.parsers import base
from app.services.library.parsers.base import ParseResult, RawDoc

logger = logging.getLogger(__name__)

# doc_type value -> keywords, weighted by how decisive each phrase is.
DOC_TYPE_PATTERNS: dict[str, tuple[tuple[str, int], ...]] = {
    "Certificate": (
        ("certificate of", 4), ("is hereby certified", 4), ("certificate no", 4),
        ("iso 9001", 3), ("iso/iec", 3), ("accreditation", 3), ("certification body", 3),
        ("certificate", 2), ("certified", 1),
    ),
    "Registration": (
        ("certificate of registration", 5), ("certificate of incorporation", 5),
        ("registration certificate", 4), ("national tax number", 4),
        ("chamber of commerce", 3), ("secp", 3),
        ("incorporation", 2), ("registration no", 2), ("registered office", 2),
        ("registration", 1),
    ),
    "Tax Filing": (
        ("income tax return", 5), ("sales tax return", 5), ("withholding statement", 4),
        ("tax year", 3), ("fbr", 3), ("taxpayer", 2), ("tax return", 3),
        ("filed", 1), ("tax", 1),
    ),
    "Financial Statement": (
        ("balance sheet", 4), ("profit and loss", 4), ("statement of financial position", 5),
        ("auditor's report", 4), ("audited financial", 4), ("cash flow statement", 4),
        ("financial statement", 3),
    ),
    "Company Profile": (
        ("company profile", 5), ("corporate profile", 5), ("about us", 3),
        ("our services", 2), ("our clients", 2), ("years of experience", 2),
    ),
    "Bank Statement": (
        ("bank statement", 5), ("account statement", 4), ("statement of account", 4),
        ("closing balance", 3), ("opening balance", 3),
    ),
    "Licence": (
        ("licence", 3), ("license no", 4), ("licensing authority", 4),
        ("permit", 2), ("authorised to operate", 3),
    ),
}

IDENTIFIER_PATTERNS: dict[str, re.Pattern] = {
    "certificate_number": re.compile(
        r"(?:certificate|cert\.?|registration|licen[cs]e|permit)\s*(?:no|number|#)\s*[:.\-]?\s*"
        r"([A-Z0-9][A-Z0-9\-/ ]{2,30}?)(?:\s|$)",
        re.IGNORECASE,
    ),
    "ntn": re.compile(r"\bNTN\s*[:.\-]?\s*(\d{6,9}-?\d?)\b", re.IGNORECASE),
    "issued_on": re.compile(
        r"(?:date\s+of\s+issue|issued\s+on|issue\s+date)\s*[:.\-]?\s*"
        r"([0-9]{1,2}[-/\s][A-Za-z0-9]{2,9}[-/\s][0-9]{2,4})",
        re.IGNORECASE,
    ),
    "valid_until": re.compile(
        r"(?:valid\s+(?:un)?til|expiry\s+date|expires\s+on|date\s+of\s+expiry)\s*[:.\-]?\s*"
        r"([0-9]{1,2}[-/\s][A-Za-z0-9]{2,9}[-/\s][0-9]{2,4})",
        re.IGNORECASE,
    ),
    "issuing_authority": re.compile(
        r"(?:issued\s+by|issuing\s+authority|certification\s+body)\s*[:.\-]?\s*(.{3,80}?)(?:\n|$)",
        re.IGNORECASE,
    ),
    "tax_year": re.compile(r"\btax\s+year\s*[:.\-]?\s*((?:20)?\d{2}(?:\s*-\s*(?:20)?\d{2})?)\b", re.IGNORECASE),
}

# Below this, a keyword classification is too weak to trust and the LLM is asked
# instead. A single incidental "tax" should not label a document a Tax Filing.
MIN_CLASSIFICATION_SCORE = 3

LLM_SAMPLE_CHARS = 3000


def classify(text: str, filename: str = "") -> tuple[str, int]:
    """Return (doc_type, score). Score 0 means nothing matched."""
    haystack = f"{filename}\n{text[:8000]}".lower()

    scores: dict[str, int] = {}
    for doc_type, patterns in DOC_TYPE_PATTERNS.items():
        total = 0
        for phrase, weight in patterns:
            if phrase in haystack:
                total += weight
        if total:
            scores[doc_type] = total

    if not scores:
        return "", 0

    best = max(scores, key=lambda k: scores[k])
    return best, scores[best]


def _extract_identifiers(text: str) -> dict[str, str]:
    sample = text[:8000]
    found: dict[str, str] = {}
    for key, pattern in IDENTIFIER_PATTERNS.items():
        match = pattern.search(sample)
        if not match:
            continue
        value = match.group(1).strip(" .,:;-–")
        if value:
            found[key] = value[:80]
    return found


def _llm_classify(text: str, filename: str) -> str:
    if not llm.is_available():
        return ""

    sample = base.clean_text(text)[:LLM_SAMPLE_CHARS]
    if not sample:
        return ""

    options = ", ".join(DOC_TYPE_PATTERNS)
    prompt = (
        "Classify this company document.\n"
        f"Filename: {filename}\n\n"
        f'Return JSON: {{"doc_type": "..."}}\n'
        f"Choose one of: {options}, Other\n"
        "Use \"Other\" if none fit. Do not invent a new category.\n\n"
        f"Document text:\n{sample}"
    )

    result = llm.complete_json(
        prompt,
        system="You classify corporate compliance documents. Reply with JSON only.",
    )
    if not isinstance(result, dict):
        return ""

    value = str(result.get("doc_type") or "").strip()
    valid = set(DOC_TYPE_PATTERNS) | {"Other"}
    return value if value in valid else ""


def parse(raw: RawDoc, use_llm: bool = True) -> ParseResult:
    result = ParseResult(warnings=list(raw.warnings))
    text = base.clean_text(raw.text)

    doc_type, score = classify(text, raw.filename)
    used_llm = False

    if score < MIN_CLASSIFICATION_SCORE and use_llm:
        llm_type = _llm_classify(text, raw.filename)
        if llm_type:
            doc_type = llm_type
            used_llm = True

    if not doc_type:
        doc_type = "Company Document"
        result.warnings.append(
            "Document type could not be determined; recorded as 'Company Document'."
        )

    identifiers = _extract_identifiers(text)

    result.doc_metadata = {"doc_type": doc_type, **identifiers}
    result.used_llm = used_llm

    # No section splitting — that is the point of LIB-IDX-04.
    sections = base.whole_document_section(raw, name=doc_type)
    if not sections:
        result.warnings.append("Document contained no extractable text.")
        return result

    result.sections = sections
    return result


base.register(DocumentCategory.COMPANY_DOCUMENT, parse)
