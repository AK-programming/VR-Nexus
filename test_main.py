import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, AsyncMock
from main import app
from section_2_2_chunking import chunk_text_by_tokens, detect_section_boundaries

client = TestClient(app)


def test_ingest_invalid_file_type():
    """Test that non-PDF files are correctly rejected with a 400 error."""
    files = {"file": ("document.docx", b"fake docx data", "application/msword")}
    response = client.post("/tender", files=files)

    assert response.status_code == 400
    assert response.json() == {"detail": "PDF required"}


def test_extract_no_chunks_found():
    """Test that requesting extraction for a non-existent tender ID returns a 404."""
    response = client.post("/extract/99999")

    assert response.status_code == 404
    assert response.json() == {"detail": "No chunks found"}


def test_chunking_logic_tokens():
    """Test that the token-based sliding window properly chunks text."""
    sample_text = "This is a test sentence for the chunking logic. " * 100
    chunks = chunk_text_by_tokens(sample_text, max_tokens=50, overlap_tokens=10)

    assert len(chunks) > 1
    assert isinstance(chunks[0], str)


def test_section_boundary_detection():
    """Test that section patterns are correctly identified in page text."""
    mock_pages = [
        {"page_no": 1, "text": "Specific Procurement Notice for the project..."},
        {"page_no": 2, "text": "Instructions to Proposers go here..."}
    ]
    processed_pages = detect_section_boundaries(mock_pages)

    assert processed_pages[0]["section"] == "SPN"
    assert processed_pages[1]["section"] == "Instructions to Proposers"


@patch("main._get_or_run_extraction", new_callable=AsyncMock)
def test_export_excel_endpoint(mock_get_extraction):
    """Test that the Excel export endpoint successfully streams an .xlsx file."""
    mock_get_extraction.return_value = {
        "master_table": [{
            "page": "1",
            "section_name": "Test Section",
            "responsibility": "Vendor",
            "reference_number": "Req-001",
            "clause_requirement_description": "Must provide testing framework",
            "mandatory": "Yes",
            "evaluation_impact": "Pass/Fail",
            "dpl": "N/A",
            "prime": "N/A",
            "the_t": "N/A",
            "joint_responsibility": "N/A",
            "evidence_document_required": "Testing Plan",
            "remarks": "None"
        }],
        "total_unique_requirements": 1,
        "manual_review_flags": 0,
        "review_data": []
    }

    response = client.get("/export/excel/1")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    assert "attachment; filename=tender_1_requirements.xlsx" in response.headers["content-disposition"]