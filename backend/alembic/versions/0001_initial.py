"""Initial Evidence Library schema (WBS 6.1)

Revision ID: 0001
Revises:

Creates the WBS 1.1.2 / 1.1.3 tables (`documents`, `document_images`,
`chunks`) plus Section 6's own `index_jobs`. The 1.1.x table and column names
are reproduced exactly — this migration is what makes a Section 6 deployment
schema-compatible with the shared model, so Stage 3 matching can read the
chunks this pipeline writes.

`users` is WBS 1.2 and not built here, so `documents.uploaded_by` is created as
a plain nullable UUID with no foreign key. 1.2 adds the constraint later.
"""
from collections.abc import Sequence

import pgvector.sqlalchemy
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.config import settings

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EMBEDDING_DIM = settings.EMBEDDING_DIM


def upgrade() -> None:
    # pgvector must exist before any Vector column is created.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # Values are the enum *names* (CASE_STUDY, not case_study): SQLAlchemy's
    # Enum() persists names by default, and WBS 1.1.2's migration was generated
    # that way, so the stored labels have to match or the two schemas diverge.
    #
    # create_type=False is essential: the types are created explicitly below, and
    # without it SQLAlchemy re-emits CREATE TYPE from each table's before_create
    # hook — unguarded — and the migration collides with itself on a clean database.
    document_category = postgresql.ENUM(
        "CASE_STUDY", "METHODOLOGY", "COMPANY_DOCUMENT",
        name="document_category", create_type=False,
    )
    document_file_type = postgresql.ENUM(
        "PDF", "DOCX", "PPTX", "IMAGE", name="document_file_type", create_type=False
    )
    document_training_status = postgresql.ENUM(
        "QUEUED", "PARSING", "TAGGING", "EMBEDDING", "INDEXED", "FAILED",
        name="document_training_status", create_type=False,
    )
    job_stage = postgresql.ENUM(
        "queued", "parsing", "tagging", "embedding", "complete", "failed",
        name="job_stage", create_type=False,
    )

    bind = op.get_bind()
    document_category.create(bind, checkfirst=True)
    document_file_type.create(bind, checkfirst=True)
    document_training_status.create(bind, checkfirst=True)
    job_stage.create(bind, checkfirst=True)

    # ---- documents (WBS 1.1.2) --------------------------------------------
    op.create_table(
        "documents",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column("category", document_category, nullable=False),
        sa.Column("title", sa.String(500), nullable=False, server_default=""),
        sa.Column("original_filename", sa.String(500), nullable=False),
        sa.Column("file_path", sa.String(1000), nullable=False),
        sa.Column("file_type", document_file_type, nullable=False),
        # Unique here though 1.1.2 leaves it open: it is the LIB-UI-06 hard
        # duplicate block and the LIB-IDX-07 skip-if-indexed key.
        sa.Column("file_hash", sa.String(128), nullable=False),
        # LIB-UI-03 / LIB-IDX-06 metadata
        sa.Column("client", sa.String(255), nullable=True, server_default=""),
        sa.Column("sector", sa.String(255), nullable=True, server_default=""),
        sa.Column("service_line", sa.String(255), nullable=True, server_default=""),
        sa.Column("geography", sa.String(255), nullable=True, server_default=""),
        sa.Column("keywords", postgresql.ARRAY(sa.String()), nullable=True),
        sa.Column(
            "training_status", document_training_status, nullable=False, server_default="QUEUED"
        ),
        sa.Column("training_error", sa.String(2000), nullable=True, server_default=""),
        # No FK — `users` is WBS 1.2 and does not exist in this deployment.
        sa.Column("uploaded_by", sa.UUID(as_uuid=True), nullable=True),
        # Section 6 additions
        sa.Column("doc_type", sa.String(128), server_default=""),
        sa.Column("auto_tagged_fields", sa.JSON(), server_default="[]"),
        sa.Column("page_count", sa.Integer(), server_default="0"),
        sa.Column("chunk_count", sa.Integer(), server_default="0"),
        sa.Column("indexed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("file_hash", name="uq_documents_file_hash"),
    )
    op.create_index("ix_documents_category", "documents", ["category"])
    op.create_index("ix_documents_file_hash", "documents", ["file_hash"])
    op.create_index("ix_documents_training_status", "documents", ["training_status"])

    # ---- document_images (WBS 1.1.2, LIB-IDX-02) --------------------------
    op.create_table(
        "document_images",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column("document_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("file_path", sa.String(1000), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("caption", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_document_images_document_id", "document_images", ["document_id"])

    # ---- chunks (WBS 1.1.3, LIB-IDX-05) -----------------------------------
    op.create_table(
        "chunks",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column("document_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("token_count", sa.Integer(), server_default="0"),
        sa.Column("section_name", sa.String(255), server_default=""),
        sa.Column("page_number", sa.Integer(), server_default="0"),
        sa.Column("embedding", pgvector.sqlalchemy.Vector(EMBEDDING_DIM), nullable=True),
        # Section 6 additions
        sa.Column("category", document_category, nullable=False),
        sa.Column("phase", sa.String(255), server_default=""),
        sa.Column("image_paths", sa.JSON(), server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        # CASCADE is what makes a single-document reindex safe: its chunks go,
        # every other document's stay (LIB-IDX-07).
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("document_id", "chunk_index", name="uq_chunk_per_doc"),
    )
    op.create_index("ix_chunks_document_id", "chunks", ["document_id"])
    op.create_index("ix_chunks_category", "chunks", ["category"])

    # HNSW for cosine similarity. 768 dims is well under pgvector's 2000-dim
    # index ceiling; a 3072-dim model would exceed it and need halfvec instead.
    op.execute(
        "CREATE INDEX ix_chunks_embedding_hnsw "
        "ON chunks USING hnsw (embedding vector_cosine_ops)"
    )

    # ---- index_jobs (Section 6 — LIB-UI-04/05) ----------------------------
    op.create_table(
        "index_jobs",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column("document_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("stage", job_stage, nullable=False, server_default="queued"),
        sa.Column("progress", sa.Integer(), server_default="0"),
        sa.Column("message", sa.Text(), server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_index_jobs_document_id", "index_jobs", ["document_id"])


def downgrade() -> None:
    op.drop_table("index_jobs")
    op.execute("DROP INDEX IF EXISTS ix_chunks_embedding_hnsw")
    op.drop_table("chunks")
    op.drop_table("document_images")
    op.drop_table("documents")

    bind = op.get_bind()
    sa.Enum(name="job_stage").drop(bind, checkfirst=True)
    sa.Enum(name="document_training_status").drop(bind, checkfirst=True)
    sa.Enum(name="document_file_type").drop(bind, checkfirst=True)
    sa.Enum(name="document_category").drop(bind, checkfirst=True)
