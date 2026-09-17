"""add llm_usage_events (API Usage tracking)

Revision ID: b6e1f3a9c247
Revises: a8d2f6c913e7
Create Date: 2026-09-10 00:00:00.000000

Creates the one table the whole API Usage feature is built on: one row per
Anthropic API call, everywhere this app makes one (tender extraction, tender
metadata, library auto-tagging, the Evidence Library's grounded Ask - see
app/models/enums.py's UsagePurpose for the full list). Written by
app/services/usage_tracking.record_usage(); read by the admin-only
/api/admin/usage/* routes and by GET /api/tenders/{id}/usage.

Retention decision from the client review: keep every call forever, so this
migration adds no pruning job and no TTL - just the table and its indexes.
Everything queried by a date range (created_at) or grouped by (model,
purpose, user_id) is indexed; tender_id/document_id are indexed too since
the per-tender usage endpoint filters on tender_id directly.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers, used by Alembic.
revision: str = 'b6e1f3a9c247'
down_revision: Union[str, None] = 'a8d2f6c913e7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    usage_purpose = sa.Enum(
        'tender_extraction', 'tender_metadata', 'library_tagging', 'library_ask',
        name='usage_purpose',
    )

    op.create_table(
        'llm_usage_events',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column(
            'created_at', sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.Column('model', sa.String(length=128), nullable=False),
        sa.Column('purpose', usage_purpose, nullable=False),
        sa.Column('input_tokens', sa.Integer(), nullable=False),
        sa.Column('output_tokens', sa.Integer(), nullable=False),
        sa.Column('estimated_cost_usd', sa.Numeric(10, 6), nullable=False),
        sa.Column('latency_ms', sa.Integer(), nullable=False),
        sa.Column('tender_id', UUID(as_uuid=True), nullable=True),
        sa.Column('document_id', UUID(as_uuid=True), nullable=True),
        sa.Column('user_id', UUID(as_uuid=True), nullable=True),
        sa.ForeignKeyConstraint(['tender_id'], ['tenders.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['document_id'], ['documents.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
    )

    op.create_index('ix_llm_usage_events_created_at', 'llm_usage_events', ['created_at'])
    op.create_index('ix_llm_usage_events_model', 'llm_usage_events', ['model'])
    op.create_index('ix_llm_usage_events_purpose', 'llm_usage_events', ['purpose'])
    op.create_index('ix_llm_usage_events_tender_id', 'llm_usage_events', ['tender_id'])
    op.create_index('ix_llm_usage_events_document_id', 'llm_usage_events', ['document_id'])
    op.create_index('ix_llm_usage_events_user_id', 'llm_usage_events', ['user_id'])


def downgrade() -> None:
    op.drop_index('ix_llm_usage_events_user_id', table_name='llm_usage_events')
    op.drop_index('ix_llm_usage_events_document_id', table_name='llm_usage_events')
    op.drop_index('ix_llm_usage_events_tender_id', table_name='llm_usage_events')
    op.drop_index('ix_llm_usage_events_purpose', table_name='llm_usage_events')
    op.drop_index('ix_llm_usage_events_model', table_name='llm_usage_events')
    op.drop_index('ix_llm_usage_events_created_at', table_name='llm_usage_events')
    op.drop_table('llm_usage_events')

    usage_purpose = sa.Enum(name='usage_purpose')
    usage_purpose.drop(op.get_bind(), checkfirst=True)
