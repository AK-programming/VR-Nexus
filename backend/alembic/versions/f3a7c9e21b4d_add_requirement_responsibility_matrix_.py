"""add requirement responsibility matrix columns

Revision ID: f3a7c9e21b4d
Revises: 0b55a5033c01
Create Date: 2026-08-19 00:00:00.000000

The Requirement model (app/models/requirement.py) has carried these five
columns since Task 3.1's extraction schema was wired in, but no migration
was ever generated for them - they were only ever created in databases
where someone ran `alembic revision --autogenerate` locally and it happened
to pick them up alongside other changes. This migration exists standalone
so `alembic upgrade head` alone is enough to bring any database in sync
with the model, without depending on that having already happened.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'f3a7c9e21b4d'
down_revision: Union[str, None] = '0b55a5033c01'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('requirements', sa.Column('responsibility', sa.String(length=500), nullable=True))
    op.add_column('requirements', sa.Column('dpl', sa.String(length=255), nullable=True))
    op.add_column('requirements', sa.Column('prime', sa.String(length=255), nullable=True))
    op.add_column('requirements', sa.Column('the_t', sa.String(length=255), nullable=True))
    op.add_column('requirements', sa.Column('joint_responsibility', sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column('requirements', 'joint_responsibility')
    op.drop_column('requirements', 'the_t')
    op.drop_column('requirements', 'prime')
    op.drop_column('requirements', 'dpl')
    op.drop_column('requirements', 'responsibility')
