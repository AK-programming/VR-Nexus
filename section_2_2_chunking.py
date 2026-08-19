# section_2_2_chunking.py

import re
import tiktoken

# Loaded once at import time instead of on every chunk_text_by_tokens() call.
_ENCODING = tiktoken.get_encoding("cl100k_base")


def detect_section_boundaries(page_data: list) -> list:
    """Handles WBS 2.2.1: Detects sections like SPN, PDS, etc."""
    section_patterns = {
        "SPN": r"(?i)\b(Specific Procurement Notice|SPN)\b",
        "Instructions to Proposers": r"(?i)\bInstructions\s+to\s+Proposers\b",
        "PDS": r"(?i)\b(Proposal Data Sheet|PDS)\b",
        "Evaluation Criteria": r"(?i)\bEvaluation\s+(and\s+Qualification\s+)?Criteria\b",
        "Section VII": r"(?i)\bSection\s+VII\b",
        "Annexes": r"(?i)\bAnnex(?:es)?\b"
    }

    current_section = "General/Front Matter"
    for page in page_data:
        for section_name, pattern in section_patterns.items():
            if re.search(pattern, page["text"]):
                current_section = section_name
                break
        page["section"] = current_section
    return page_data


def chunk_text_by_tokens(text: str, max_tokens: int = 2000, overlap_tokens: int = 200) -> list:
    """Handles WBS 2.2.2 & 2.2.3: Splits text into chunks with a 200-token sliding overlap."""
    if not text or not text.strip():
        return []

    tokens = _ENCODING.encode(text)
    if not tokens:
        return []

    chunks = []
    # Step forward by (max_tokens - overlap_tokens) to create the sliding window
    step_size = max_tokens - overlap_tokens

    # Ensure step_size is positive to avoid infinite loops
    if step_size <= 0:
        step_size = max_tokens

    for i in range(0, len(tokens), step_size):
        chunk_tokens = tokens[i:i + max_tokens]
        chunks.append(_ENCODING.decode(chunk_tokens))
    return chunks


def generate_mock_embedding(text: str) -> list:
    """Handles WBS 2.2.4: Vector embedding generation."""
    return [0.015, -0.022, 0.089]


def group_pages_by_section(page_data: list) -> list:
    """Groups consecutive pages belonging to the same section before chunking."""
    section_groups = []
    current_group = None

    for page in page_data:
        if current_group is None or current_group["section"] != page["section"]:
            if current_group is not None:
                section_groups.append(current_group)

            current_group = {
                "section": page["section"],
                "text": page["text"],
                "start_page": page["page_no"],
                "end_page": page["page_no"],
                "tender_id": page["tender_id"]
            }
        else:
            current_group["text"] += "\n" + page["text"]
            current_group["end_page"] = page["page_no"]

    if current_group is not None:
        section_groups.append(current_group)

    return section_groups