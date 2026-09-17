"""add tenders.stated_technical_marks / passing_technical_score

Revision ID: d4f1b82e6a07
Revises: c9a2d5f7b813
Create Date: 2026-09-16 00:00:00.000000

What the tender itself says is on offer, kept separately from
tenders.total_marks_available, which is the SUM of the marks extraction found
per requirement. Two numbers rather than one on purpose.

A shipped tracker reported "Marks available: 222" for a tender whose own
evaluation section says 100 technical marks with 70 to pass. The sum was wrong
twice over: the scoring table appears in two places in that RFP and both copies
were counted, and the experience bands ("more than 15 years = 10, 10 to 15 = 5,
7 to 10 = 1") were added together as though one expert could earn all three
rather than exactly one of them. Every coverage percentage in the pack was
computed against 222, so all of it was wrong, and nothing in the workbook
indicated that.

Holding the stated figure independently makes the disagreement detectable: the
Summary sheet now compares the two and flags a mismatch rather than presenting
a confident wrong total (see _marks_reconciliation in
app/tasks/tender_pipeline.py). Nullable with no backfill: a tender that does
not state a total, or that was analysed before this column existed, simply
skips the check, which is the same behaviour as before this migration.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'd4f1b82e6a07'
down_revision: Union[str, None] = 'c9a2d5f7b813'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('tenders', sa.Column('stated_technical_marks', sa.Numeric(10, 2), nullable=True))
    op.add_column('tenders', sa.Column('passing_technical_score', sa.Numeric(10, 2), nullable=True))


def downgrade() -> None:
    op.drop_column('tenders', 'passing_technical_score')
    op.drop_column('tenders', 'stated_technical_marks')
