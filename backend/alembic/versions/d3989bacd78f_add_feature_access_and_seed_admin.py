"""add feature_access and seed the admin account

Revision ID: d3989bacd78f
Revises: 7c1e4a92f6b3
Create Date: 2026-09-08 00:00:00.000000

Client review meeting result: an admin role with complete access, plus a
Users admin page where an admin grants each ordinary account one section
at a time (Documents, AI Assistant, Tender Analysis, Tender Tools - see
app/models/enums.py's FeatureKey). This migration does two things:

1. Adds users.feature_access - a Postgres text array, NOT NULL, default
   empty - the list of FeatureKey values a USER row has been granted. An
   ADMIN row never consults it: require_feature (app/api/deps.py) always
   admits an admin regardless of this list, which is why the seeded admin
   below is inserted with it left empty rather than populated.

2. Seeds the one admin account requested at that meeting. The INSERT is
   idempotent (checked by email first, so re-running this migration, or
   running it against a database where someone already registered that
   exact email, is a no-op rather than an error or a duplicate row).

The password hash below is bcrypt - passlib's bcrypt scheme, the same one
app/core/security.py's hash_password() uses for every other account -
computed once, out of band, for the exact password given at that meeting.
Nothing about the plaintext survives in this file or ends up in Postgres;
a bcrypt hash cannot be reversed back to it, which is the entire point of
committing the hash here instead of hashing a literal password at migrate
time.
"""
import uuid
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ENUM, UUID

# revision identifiers, used by Alembic.
revision: str = 'd3989bacd78f'
down_revision: Union[str, None] = '7c1e4a92f6b3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_ADMIN_EMAIL = "ibrahim.r@dplit.com"
_ADMIN_PASSWORD_HASH = "$2b$12$5jz3Caw0NuWWyxQ5PPbpJeq/Hr55OM5uiSeAA81FUsMjhP1D8wpJi"


def upgrade() -> None:
    op.add_column(
        'users',
        sa.Column(
            'feature_access',
            sa.ARRAY(sa.String(length=50)),
            nullable=False,
            server_default='{}',
        ),
    )

    # A lightweight table/column set for the INSERT below - not the real
    # mapped model, so it carries no relationships. `role` is declared with
    # create_type=False so SQLAlchemy binds it as the existing user_role
    # enum (matching the real column) instead of re-creating the type. The
    # labels are the UserRole *member names* (ADMIN/USER), not .value
    # ("admin"/"user") - that's what app/models/user.py's plain
    # Enum(UserRole, ...) stores, since it sets no values_callable.
    users = sa.table(
        'users',
        sa.column('id', UUID(as_uuid=True)),
        sa.column('name', sa.String),
        sa.column('email', sa.String),
        sa.column('password_hash', sa.String),
        sa.column('role', ENUM('ADMIN', 'USER', name='user_role', create_type=False)),
        sa.column('is_active', sa.Boolean),
        sa.column('failed_login_attempts', sa.Integer),
        sa.column('feature_access', sa.ARRAY(sa.String(length=50))),
        sa.column('created_at', sa.DateTime(timezone=True)),
        sa.column('updated_at', sa.DateTime(timezone=True)),
    )

    bind = op.get_bind()
    already_exists = bind.execute(
        sa.text("SELECT 1 FROM users WHERE email = :email"), {"email": _ADMIN_EMAIL}
    ).first()

    if already_exists is None:
        bind.execute(
            users.insert().values(
                id=uuid.uuid4(),
                name="Admin",
                email=_ADMIN_EMAIL,
                password_hash=_ADMIN_PASSWORD_HASH,
                role="ADMIN",
                is_active=True,
                failed_login_attempts=0,
                feature_access=[],
                created_at=sa.func.now(),
                updated_at=sa.func.now(),
            )
        )


def downgrade() -> None:
    # Only the exact seeded account, and only while it is still an admin -
    # if someone changed its role or reused the row for something else in
    # the meantime, this downgrade should not delete a row it no longer
    # recognises.
    op.execute(
        sa.text(
            "DELETE FROM users WHERE email = :email AND role = 'ADMIN'"
        ).bindparams(email=_ADMIN_EMAIL)
    )
    op.drop_column('users', 'feature_access')
