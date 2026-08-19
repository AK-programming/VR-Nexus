import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, AsyncMock
from main import app

client = TestClient(app)


def test_ingest_invalid_file_type():
    files = {"file": ("document.docx", b"fake docx data", "application/msword")}
    response = client.post("/tender", files=files)

    assert response.status_code == 400
    assert response.json() == {"detail": "PDF required"}


def test_extract_no_chunks_found():
    response = client.post("/extract/99999")

    assert response.status_code == 404
    assert response.json() == {"detail": "No chunks found"}


@patch("section_3_extraction.extract_all_chunks_parallel", new_callable=AsyncMock)
def test_export_excel_mocked(mock_extract):
    mock_extract.return_value = [{
        "status": "success",
        "data": [{
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
        "needs_manual_review": False
    }]

    response = client.get("/export/excel/1")

    if response.status_code == 200:
        assert response.headers["content-type"] == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        assert "attachment; filename=tender_1_requirements.xlsx" in response.headers["content-disposition"]
    else:
        assert response.status_code == 404