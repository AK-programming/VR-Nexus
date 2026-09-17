"""add app_settings openai/gemini api key columns

Revision ID: c9a2d5f7b813
Revises: b3e6f094a1c5
Create Date: 2026-09-15 00:00:00.000000

Client follow-up: "if the user will change the api to gemini or openai etc
they will enter their api key and select the model" - each provider gets
its own Fernet-encrypted key column, same pattern as the existing
anthropic_api_key_encrypted (see app/models/app_setting.py and
app/services/app_settings.py's PROVIDERS / get_effective_api_key).
Nullable, no backfill: NULL means "no override, fall back to that
provider's .env key", exactly like the Anthropic column already works, so
this is a pure addition with no behaviour change until an admin enters a
key for one of the new providers.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'c9a2d5f7b813'
down_revision: Union[str, None] = 'b3e6f094a1c5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('app_settings', sa.Column('openai_api_key_encrypted', sa.Text(), nullable=True))
    op.add_column('app_settings', sa.Column('gemini_api_key_encrypted', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('app_settings', 'gemini_api_key_encrypted')
    op.drop_column('app_settings', 'openai_api_key_encrypted')
