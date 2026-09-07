"""add tender run_generation and celery_task_id

Revision ID: 7c1e4a92f6b3
Revises: a2e9f4c11d63
Create Date: 2026-09-07 00:00:00.000000

Backs the cancel/reprocess race fix in tasks/tender_pipeline.py: every write a
worker makes back onto its tender row is now conditioned on run_generation
still matching the value the worker captured when it started, so a stale
worker (one that hasn't yet noticed a Stop, or that a Retry has already moved
the tender on to a new attempt) can no longer silently overwrite the current
state. celery_task_id lets Cancel send a hard revoke on top of that
cooperative check.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '7c1e4a92f6b3'
down_revision: Union[str, None] = 'a2e9f4c11d63'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'tenders',
        sa.Column('run_generation', sa.Integer(), nullable=False, server_default='0'),
    )
    op.add_column(
        'tenders',
        sa.Column('celery_task_id', sa.String(length=255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('tenders', 'celery_task_id')
    op.drop_column('tenders', 'run_generation')
