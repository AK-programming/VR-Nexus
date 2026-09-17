"""add tenders.extraction_warnings for failed-chunk visibility

Revision ID: f1a7c9e2b504
Revises: d3989bacd78f
Create Date: 2026-09-09 00:00:00.000000

Stage 2 extraction (app/services/extraction.run_extraction) tolerates up to
MAX_ACCEPTABLE_CHUNK_FAILURE_RATE (30%) of chunks failing all their retries
without failing the whole run - each failed chunk was simply dropped, with
no record anywhere of which pages it covered. A reviewer looking at a
thinner-than-expected tracker had no way to tell "this document genuinely
has few requirements" apart from "12 pages were silently missed".

This adds a single nullable text column holding a human-readable summary
("3 of 159 chunk(s) failed extraction ... Pages that may be incomplete: 23-28,
36-40.") set by run_extraction and cleared on reprocess (see the reprocess
route in app/api/routes/tenders.py), same lifecycle as the existing
failed_stage/error_detail/failed_at failure-record columns already on this
table. Surfaced in the Excel Summary sheet, summary.json, and the tender
detail/list API responses.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'f1a7c9e2b504'
down_revision: Union[str, None] = 'd3989bacd78f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('tenders', sa.Column('extraction_warnings', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('tenders', 'extraction_warnings')
