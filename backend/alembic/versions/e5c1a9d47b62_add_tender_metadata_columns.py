"""add tender metadata columns

Revision ID: e5c1a9d47b62
Revises: 4a7d9c2e1f30
Create Date: 2026-08-27

Top-level facts about each tender — reference/notice number, issuing authority,
sector, location, estimated value, and submission deadline. They're populated
best-effort by a single LLM pass over the opening pages during PARSING
(services/extraction.extract_tender_metadata) and are correctable by the user
via PATCH /api/tenders/{id}. All nullable: an unknown value stays null rather
than being guessed, so the column set is a pure additive extension of the
initial `tenders` table.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e5c1a9d47b62"
down_revision: Union[str, None] = "4a7d9c2e1f30"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("tenders", sa.Column("reference_id", sa.String(length=255), nullable=True))
    op.add_column("tenders", sa.Column("issuing_authority", sa.String(length=500), nullable=True))
    op.add_column("tenders", sa.Column("sector", sa.String(length=255), nullable=True))
    op.add_column("tenders", sa.Column("location", sa.String(length=255), nullable=True))
    op.add_column("tenders", sa.Column("tender_value", sa.Numeric(precision=18, scale=2), nullable=True))
    op.add_column("tenders", sa.Column("submission_deadline", sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column("tenders", "submission_deadline")
    op.drop_column("tenders", "tender_value")
    op.drop_column("tenders", "location")
    op.drop_column("tenders", "sector")
    op.drop_column("tenders", "issuing_authority")
    op.drop_column("tenders", "reference_id")
