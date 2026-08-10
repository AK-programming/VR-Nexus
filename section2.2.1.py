import re


# 2.2.1 Section boundary detection
def detect_section_boundaries(page_data: list) -> list:
    """
    Scans the extracted page text to detect specific tender sections.
    """
    # Regex patterns for the exact sections defined in the WBS
    section_patterns = {
        "SPN": r"(?i)\b(Specific Procurement Notice|SPN)\b",
        "Instructions to Proposers": r"(?i)\bInstructions\s+to\s+Proposers\b",
        "PDS": r"(?i)\b(Proposal Data Sheet|PDS)\b",
        "Evaluation Criteria": r"(?i)\bEvaluation\s+(and\s+Qualification\s+)?Criteria\b",
        "Section VII": r"(?i)\bSection\s+VII\b",
        "Annexes": r"(?i)\bAnnex(?:es)?\b"
    }

    current_section = "General/Front Matter"  # Default starting section

    for page in page_data:
        text = page["text"]

        # Check if any of our target headings appear on this page
        for section_name, pattern in section_patterns.items():
            if re.search(pattern, text):
                current_section = section_name
                break  # Stop searching if we found a match on this page

        # Attach the detected section to the page data
        page["section"] = current_section

    return page_data
