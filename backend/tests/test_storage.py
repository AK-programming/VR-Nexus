"""Upload validation, hashing and path safety."""
import uuid

import pytest

from app.models import DocumentCategory
from app.services import storage


def test_allowed_extensions_match_lib_ui_02():
    """LIB-UI-02 names PDF, DOCX, PPTX and image formats."""
    assert ".pdf" in storage.ALLOWED_EXTENSIONS
    assert ".docx" in storage.ALLOWED_EXTENSIONS
    assert ".pptx" in storage.ALLOWED_EXTENSIONS
    assert {".png", ".jpg", ".jpeg", ".tiff", ".tif"} <= set(storage.ALLOWED_EXTENSIONS)


@pytest.mark.parametrize("filename", ["notes.txt", "archive.zip", "sheet.xlsx", "script.exe", "noext"])
def test_unsupported_extensions_are_rejected(filename):
    with pytest.raises(storage.UploadRejected, match="Unsupported file type"):
        storage.validate_upload(filename, "application/octet-stream", 1024)


def test_extension_check_is_case_insensitive():
    assert storage.validate_upload("REPORT.PDF", "application/pdf", 1024) == ".pdf"


def test_empty_file_is_rejected():
    with pytest.raises(storage.UploadRejected, match="empty"):
        storage.validate_upload("doc.pdf", "application/pdf", 0)


def test_oversized_file_is_rejected():
    from app.config import settings

    too_big = settings.max_upload_bytes + 1
    with pytest.raises(storage.UploadRejected, match="limit"):
        storage.validate_upload("doc.pdf", "application/pdf", too_big)


def test_mismatched_mime_is_tolerated():
    """Browsers report Office MIME types inconsistently; the extension decides."""
    assert storage.validate_upload("deck.pptx", "application/octet-stream", 2048) == ".pptx"


def test_hash_is_stable_and_content_dependent():
    assert storage.hash_bytes(b"identical") == storage.hash_bytes(b"identical")
    assert storage.hash_bytes(b"a") != storage.hash_bytes(b"b")
    assert len(storage.hash_bytes(b"x")) == 64


def test_hash_file_matches_hash_bytes(tmp_path):
    data = b"some file content"
    path = tmp_path / "f.bin"
    path.write_bytes(data)
    assert storage.hash_file(path) == storage.hash_bytes(data)


def test_stored_filename_ignores_a_traversal_attempt(storage_dir):
    """A crafted client filename must not escape the storage directory."""
    document_id = uuid.uuid4()
    path = storage.save_upload(b"data", "../../../../etc/passwd.pdf", document_id)

    assert path.name == f"{document_id}.pdf"
    assert path.resolve().is_relative_to(storage_dir.resolve())


def test_stored_filename_uses_the_document_uuid(storage_dir):
    document_id = uuid.uuid4()
    path = storage.save_upload(b"data", "Client Report v2.pdf", document_id)

    assert path.stem == str(document_id)
    assert path.suffix == ".pdf"


def test_image_directory_is_per_document(storage_dir):
    a, b = uuid.uuid4(), uuid.uuid4()
    assert storage.images_dir(a) != storage.images_dir(b)
    assert storage.images_dir(a).is_dir()


def test_relative_path_hides_the_absolute_container_path(storage_dir):
    document_id = uuid.uuid4()
    image = storage.images_dir(document_id) / "p1_0.png"
    image.write_bytes(b"fake png")

    relative = storage.relative_path(image)
    assert relative == f"images/{document_id}/p1_0.png"
    assert str(storage_dir) not in relative


def test_deletion_is_idempotent(storage_dir):
    document_id = uuid.uuid4()
    path = storage.save_upload(b"data", "doc.pdf", document_id)
    (storage.images_dir(document_id) / "p1_0.png").write_bytes(b"img")

    storage.delete_document_files(str(path), document_id)
    assert not path.exists()

    # Calling it again must not raise.
    storage.delete_document_files(str(path), document_id)


def test_category_enum_has_exactly_the_three_library_categories():
    """LIB-IDX-01 — three categories, no more."""
    assert {c.value for c in DocumentCategory} == {
        "case_study",
        "methodology",
        "company_document",
    }


def test_unknown_category_is_not_constructible():
    with pytest.raises(ValueError):
        DocumentCategory("proposals")
