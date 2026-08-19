"""add tender_chunks table and tender progress fields

Revision ID: b2c9a41f7e3d
Revises: cb744382080e
Create Date: 2026-08-11 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

import pgvector.sqlalchemy


# revision identifiers, used by Alembic.
revision: str = 'b2c9a41f7e3d'
down_revision: Union[str, None] = 'cb744382080e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- Task 2.2: TenderChunk table ---
    op.create_table(
        'tender_chunks',
        sa.Column('tender_id', sa.UUID(), nullable=False),
        sa.Column('chunk_index', sa.Integer(), nullable=False),
        sa.Column('section', sa.String(length=255), nullable=False),
        sa.Column('page_start', sa.Integer(), nullable=False),
        sa.Column('page_end', sa.Integer(), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('token_count', sa.Integer(), nullable=False),
        sa.Column('overlap_tokens', sa.Integer(), nullable=False),
        sa.Column('embedding', pgvector.sqlalchemy.Vector(768), nullable=True),
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['tender_id'], ['tenders.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_tender_chunks_tender_id'), 'tender_chunks', ['tender_id'], unique=False)

    # --- Task 7.1: extracted_requirements_count field on Tender ---
    # (progress_percent / progress_message were already added by cb744382080e)
    op.add_column(
        'tenders',
        sa.Column('extracted_requirements_count', sa.Integer(), nullable=False, server_default='0'),
    )
    # server_default was only needed to backfill existing rows; drop it so
    # future inserts go through the model's Python-side default instead.
    op.alter_column('tenders', 'extracted_requirements_count', server_default=None)


def downgrade() -> None:
    op.drop_column('tenders', 'extracted_requirements_count')
    op.drop_index(op.f('ix_tender_chunks_tender_id'), table_name='tender_chunks')
    op.drop_table('tender_chunks')