"""add users.email_verified_at (email verification)

Revision ID: a7d1c93e6f28
Revises: f4b8e21a7c36
Create Date: 2026-09-15 00:00:00.000000

Client request: catch a mistyped or made-up email at signup by actually
requiring the address to receive mail, not just look like one. Adds a single
nullable timestamp - NULL means unverified, set means "verified at this
time" (see app/models/user.py's own comment on the column, and register()/
login()/verify_email() in app/api/routes/auth.py for how it's set and
enforced).

Every account that already exists is backfilled to verified using its own
created_at, not the migration's run time - these accounts were created and
used successfully under the old rules, and this feature exists to gate NEW
signups, not to retroactively lock out the whole existing roster the moment
this migration runs.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a7d1c93e6f28'
down_revision: Union[str, None] = 'f4b8e21a7c36'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'users',
        sa.Column('email_verified_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.execute("UPDATE users SET email_verified_at = created_at WHERE email_verified_at IS NULL")


def downgrade() -> None:
    op.drop_column('users', 'email_verified_at')
