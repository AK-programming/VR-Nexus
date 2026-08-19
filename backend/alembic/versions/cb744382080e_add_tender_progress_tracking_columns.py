"""add tender progress tracking columns

Revision ID: cb744382080e
Revises: 97d1f63e027d
Create Date: 2026-08-07 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'cb744382080e'
down_revision: Union[str, None] = '97d1f63e027d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('tenders', sa.Column('progress_percent', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('tenders', sa.Column('progress_message', sa.String(length=500), nullable=True))


def downgrade() -> None:
    op.drop_column('tenders', 'progress_message')
    op.drop_column('tenders', 'progress_percent')