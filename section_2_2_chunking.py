# section_2_2_chunking.py

import re
import tiktoken


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


def chunk_text_by_tokens(text: str, max_tokens: int = 2000) -> list:
    """Handles WBS 2.2.2: Splits text by strict token limits."""
    encoding = tiktoken.get_encoding("cl100k_base")
    tokens = encoding.encode(text)

    chunks = []
    for i in range(0, len(tokens), max_tokens):
        chunk_tokens = tokens[i:i + max_tokens]
        chunks.append(encoding.decode(chunk_tokens))
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