"""Metadata attribute extraction (LIB-IDX-06).

Extracts Document Type, Client, Sector, Service Line, Geography and Keywords.
Heuristics run first; the LLM is asked only about fields still blank afterwards.

Precedence is strict: uploader-supplied > heuristic > LLM. A value the user
typed is never overwritten, and `auto_tagged_fields` records which fields the
machine filled so a reviewer can tell them apart.
"""
import logging
import re
from collections import Counter
from dataclasses import dataclass, field

from app.services import llm

logger = logging.getLogger(__name__)

METADATA_FIELDS = ("doc_type", "client", "sector", "service_line", "geography", "keywords")

SECTOR_KEYWORDS: dict[str, tuple[str, ...]] = {
    "Healthcare": ("hospital", "clinic", "patient", "medical", "health", "pharma"),
    "Education": ("school", "university", "student", "curriculum", "education", "campus"),
    "Government": ("ministry", "government", "public sector", "municipal", "federal", "provincial"),
    "Financial Services": ("bank", "insurance", "fintech", "payment", "lending", "treasury"),
    "Energy": ("energy", "power", "grid", "solar", "renewable", "electricity", "utility"),
    "Agriculture": ("agriculture", "farming", "crop", "irrigation", "livestock", "mandi"),
    "Telecom": ("telecom", "network operator", "broadband", "cellular", "5g"),
    "Transport & Logistics": ("logistics", "fleet", "transport", "shipping", "supply chain"),
    "Water & Sanitation": ("water", "sanitation", "wastewater", "sewerage", "hygiene"),
    "Retail": ("retail", "e-commerce", "storefront", "merchant", "pos"),
}

SERVICE_LINE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "Software Development": ("web application", "mobile app", "software development", "portal", "platform"),
    "Data & Analytics": ("dashboard", "analytics", "business intelligence", "data warehouse", "reporting"),
    "AI & Machine Learning": ("machine learning", "artificial intelligence", "llm", "predictive model", "computer vision"),
    "IoT & Embedded": ("iot", "sensor", "embedded", "telemetry", "scada"),
    "Cloud & DevOps": ("cloud migration", "kubernetes", "devops", "ci/cd", "aws", "azure"),
    "GIS & Remote Sensing": ("gis", "geospatial", "satellite", "remote sensing", "mapping"),
    "Consulting & Advisory": ("advisory", "consulting", "feasibility", "assessment", "strategy"),
    "Monitoring & Evaluation": ("monitoring", "evaluation", "m&e", "baseline survey", "impact assessment"),
}

GEOGRAPHIES: tuple[str, ...] = (
    "Pakistan", "Punjab", "Sindh", "Balochistan", "Khyber Pakhtunkhwa", "Gilgit-Baltistan",
    "Lahore", "Karachi", "Islamabad", "Peshawar", "Quetta", "Multan", "Faisalabad",
    "Afghanistan", "Bangladesh", "India", "Nepal", "Sri Lanka",
    "United Arab Emirates", "Dubai", "Abu Dhabi", "Saudi Arabia", "Qatar", "Oman", "Kuwait",
    "Kenya", "Nigeria", "Ghana", "Tanzania", "Uganda", "Ethiopia", "South Africa",
    "United Kingdom", "United States", "Canada", "Australia", "Germany", "Netherlands",
    "Global", "Regional", "Asia", "Africa", "Middle East", "Europe",
)

DOC_TYPE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "Certificate": ("certificate", "certified", "iso ", "accreditation", "certification"),
    "Registration": ("registration", "incorporation", "registered office", "ntn", "chamber of commerce"),
    "Tax Filing": ("tax", "return", "fbr", "sales tax", "income tax", "withholding"),
    "Financial Statement": ("balance sheet", "profit and loss", "audited", "financial statement"),
    "Company Profile": ("company profile", "about us", "our company", "corporate profile"),
    "Case Study": ("case study", "challenge", "solution", "results", "outcome"),
    "Methodology": ("methodology", "approach", "phase", "framework", "workplan"),
}

CLIENT_LABEL_RE = re.compile(
    r"^\s*(?:client|customer|for|prepared\s+for|submitted\s+to)\s*[:\-–]\s*(.+)$",
    re.IGNORECASE | re.MULTILINE,
)
SECTOR_LABEL_RE = re.compile(
    r"^\s*(?:sector|industry|domain)\s*[:\-–]\s*(.+)$", re.IGNORECASE | re.MULTILINE
)

STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "from", "was", "were", "are", "our", "their",
    "has", "have", "had", "will", "would", "which", "into", "also", "been", "more", "than",
    "its", "his", "her", "such", "these", "those", "there", "where", "when", "what",
    "all", "any", "can", "could", "should", "may", "might", "must", "not", "but", "you",
    "your", "who", "how", "why", "each", "other", "some", "over", "under", "between",
    "through", "during", "before", "after", "above", "below", "further", "then", "once",
    "here", "both", "few", "most", "own", "same", "too", "very", "just", "only", "about",
}


@dataclass
class ExtractedMetadata:
    doc_type: str = ""
    client: str = ""
    sector: str = ""
    service_line: str = ""
    geography: str = ""
    keywords: list[str] = field(default_factory=list)
    auto_tagged_fields: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "doc_type": self.doc_type,
            "client": self.client,
            "sector": self.sector,
            "service_line": self.service_line,
            "geography": self.geography,
            "keywords": self.keywords,
            "auto_tagged_fields": self.auto_tagged_fields,
        }


def _match_keyword_map(text: str, mapping: dict[str, tuple[str, ...]]) -> str:
    """Return the label with the most keyword hits, or ""."""
    lowered = text.lower()
    scores = {
        label: sum(lowered.count(kw) for kw in keywords)
        for label, keywords in mapping.items()
    }
    best = max(scores, key=scores.get, default="")
    return best if best and scores[best] > 0 else ""


def _find_labelled(text: str, pattern: re.Pattern) -> str:
    match = pattern.search(text)
    if not match:
        return ""
    value = match.group(1).strip()
    value = re.split(r"\s{2,}|\||;", value)[0].strip(" .,-–")
    # A "label:" line that runs on is probably prose, not a field value.
    return value[:200] if 1 < len(value) <= 200 else ""


def _client_from_filename(filename: str) -> str:
    """Filenames like 'ACME Corp - Water Portal.pdf' put the client first."""
    stem = re.sub(r"\.[^.]+$", "", filename)
    stem = re.sub(r"[_]+", " ", stem)
    for sep in (" - ", " – ", " — "):
        if sep in stem:
            candidate = stem.split(sep)[0].strip()
            if 2 < len(candidate) <= 80:
                return candidate
    return ""


def _extract_geography(text: str) -> str:
    """First geography mentioned, longest-name-first so 'Khyber Pakhtunkhwa'
    beats a bare 'Pakistan' appearing later."""
    lowered = text.lower()
    found: list[tuple[int, str]] = []
    for place in sorted(GEOGRAPHIES, key=len, reverse=True):
        idx = lowered.find(place.lower())
        if idx != -1:
            found.append((idx, place))
    if not found:
        return ""
    found.sort(key=lambda pair: pair[0])
    return found[0][1]


def _extract_keywords(text: str, limit: int = 12) -> list[str]:
    words = re.findall(r"\b[a-z][a-z\-]{3,}\b", text.lower())
    counts = Counter(w for w in words if w not in STOPWORDS and len(w) > 3)
    return [word for word, _ in counts.most_common(limit)]


def extract_heuristic(text: str, filename: str, category: str) -> ExtractedMetadata:
    """Rules-only pass. Cheap, offline, deterministic."""
    sample = text[:20000]

    meta = ExtractedMetadata()
    meta.client = _find_labelled(sample, CLIENT_LABEL_RE) or _client_from_filename(filename)
    meta.sector = _find_labelled(sample, SECTOR_LABEL_RE) or _match_keyword_map(sample, SECTOR_KEYWORDS)
    meta.service_line = _match_keyword_map(sample, SERVICE_LINE_KEYWORDS)
    meta.geography = _extract_geography(sample)
    meta.keywords = _extract_keywords(sample)

    meta.doc_type = _match_keyword_map(sample, DOC_TYPE_KEYWORDS)
    if not meta.doc_type:
        # Category is a reasonable default document type.
        meta.doc_type = {
            "case_study": "Case Study",
            "methodology": "Methodology",
            "company_document": "Company Document",
        }.get(category, "")

    return meta


def _llm_fill(text: str, filename: str, category: str, missing: list[str]) -> dict:
    """Ask the LLM only about fields still blank."""
    if not missing or not llm.is_available():
        return {}

    prompt = (
        f"Extract metadata from this {category.replace('_', ' ')} document.\n"
        f"Filename: {filename}\n\n"
        f"Return a JSON object with exactly these keys: {', '.join(missing)}\n"
        "Rules:\n"
        "- Use \"\" for any field not stated or inferable from the text.\n"
        "- 'keywords' must be an array of 5-12 short topical terms.\n"
        "- 'client' is the organisation the work was done for.\n"
        "- 'service_line' is the type of work delivered (e.g. Software Development, "
        "Data & Analytics, Consulting & Advisory).\n"
        "- Do not guess. An empty string is better than an invention.\n\n"
        f"Document text:\n{text[:6000]}"
    )

    result = llm.complete_json(
        prompt,
        system="You extract structured metadata from business documents. Reply with JSON only.",
    )
    return result if isinstance(result, dict) else {}


def extract(
    text: str,
    filename: str,
    category: str,
    user_supplied: dict | None = None,
    use_llm: bool = True,
) -> ExtractedMetadata:
    """Full LIB-IDX-06 extraction with precedence applied.

    `user_supplied` values win outright. Heuristics fill what remains. The LLM is
    consulted only for fields still blank after both, and only when `use_llm`.
    """
    supplied = {k: (v or "").strip() if isinstance(v, str) else v
                for k, v in (user_supplied or {}).items()}

    meta = extract_heuristic(text, filename, category)
    auto_tagged: list[str] = []

    # Heuristic values count as auto-tagged — the uploader did not type them.
    for field_name in METADATA_FIELDS:
        if not supplied.get(field_name) and getattr(meta, field_name):
            auto_tagged.append(field_name)

    # User values override everything.
    for field_name in METADATA_FIELDS:
        value = supplied.get(field_name)
        if not value:
            continue
        if field_name == "keywords":
            parsed = (
                [k.strip() for k in value.split(",") if k.strip()]
                if isinstance(value, str) else list(value)
            )
            if parsed:
                meta.keywords = parsed
        else:
            setattr(meta, field_name, value)

    if use_llm:
        missing = [
            f for f in METADATA_FIELDS
            if not (meta.keywords if f == "keywords" else getattr(meta, f))
        ]
        if missing:
            filled = _llm_fill(text, filename, category, missing)
            for field_name in missing:
                value = filled.get(field_name)
                if not value:
                    continue
                if field_name == "keywords":
                    if isinstance(value, list) and value:
                        meta.keywords = [str(k).strip() for k in value if str(k).strip()][:12]
                        auto_tagged.append(field_name)
                elif isinstance(value, str) and value.strip():
                    setattr(meta, field_name, value.strip()[:200])
                    auto_tagged.append(field_name)

    meta.auto_tagged_fields = sorted(set(auto_tagged))
    return meta
