"""add tenders.section_triage

Revision ID: e7c3a95d1f42
Revises: d4f1b82e6a07
Create Date: 2026-09-16 00:00:00.000000

Stage A page triage: which page spans of a tender were judged worth extracting
from, and whether that judgement was acted on. Shape is

    {"applied": bool, "reason": str,
     "spans": [{"page_start": int, "page_end": int, "kind": str, "label": str}]}

owned by app/services/section_triage.py.

Persisted rather than recomputed because it is audit material, not a cache. On
one 125-page reference RFP, 43.5% of the extracted rows came from post-award
contract clauses and another 5.1% from table-of-contents lines, and neither of
the two analyst-authored trackers we compared against contains a single row from
those sections. Extraction now skips those page spans, which is a large saving
and also a claim that has to be inspectable: the workbook's "Excluded sections"
sheet is built from this column, so a reviewer can see exactly which pages were
skipped and why, and disagree.

Nullable with no backfill. A tender analysed before triage existed reads back as
"not applied", which is identical to never having run it, so every existing
tender's output is unchanged.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'e7c3a95d1f42'
down_revision: Union[str, None] = 'd4f1b82e6a07'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('tenders', sa.Column('section_triage', sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column('tenders', 'section_triage')
