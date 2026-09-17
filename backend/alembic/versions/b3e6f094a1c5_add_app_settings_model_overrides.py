"""add app_settings.model_overrides (runtime per-task model selection)

Revision ID: b3e6f094a1c5
Revises: a7d1c93e6f28
Create Date: 2026-09-15 00:00:00.000000

Client follow-up: the admin wanted to switch which model handles tender/
library extraction (e.g. off Haiku onto a different one) and the Evidence
Library's grounded Ask, without editing .env and restarting the backend -
the same runtime-override pattern app_settings already has for the
Anthropic API key and per-model pricing (see e2a7c4f18b95). Nullable, no
backfill: a NULL/empty row means "use the config.py defaults for both
tasks", which is already what every deployment does today, so this is a
pure addition with no behaviour change until an admin visits Settings.

See app/models/app_setting.py's model_overrides column and
app/services/app_settings.py's MODEL_TASKS / get_effective_model for how a
saved value here is read.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'b3e6f094a1c5'
down_revision: Union[str, None] = 'a7d1c93e6f28'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('app_settings', sa.Column('model_overrides', sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column('app_settings', 'model_overrides')
