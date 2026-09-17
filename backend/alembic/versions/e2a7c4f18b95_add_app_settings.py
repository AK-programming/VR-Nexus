"""add app_settings (runtime API key + pricing overrides)

Revision ID: e2a7c4f18b95
Revises: b6e1f3a9c247
Create Date: 2026-09-15 00:00:00.000000

Adds the single-row app_settings table app/models/app_setting.py describes.
No seed row is inserted here - app/services/app_settings.py creates it
lazily on first read/write (get-or-create), so a fresh deploy with no admin
having touched Settings yet has zero rows and every effective-value lookup
falls straight through to the .env-sourced config.py defaults.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers, used by Alembic.
revision: str = 'e2a7c4f18b95'
down_revision: Union[str, None] = 'b6e1f3a9c247'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'app_settings',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column(
            'created_at', sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.Column(
            'updated_at', sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.Column('anthropic_api_key_encrypted', sa.Text(), nullable=True),
        sa.Column('pricing_overrides', sa.JSON(), nullable=True),
        sa.Column('last_pricing_refresh_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_pricing_refresh_result', sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table('app_settings')
