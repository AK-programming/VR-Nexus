"""add excel export customization columns

Revision ID: a8d2f6c913e7
Revises: f1a7c9e2b504
Create Date: 2026-09-09 00:10:00.000000

Client requirement (Users admin page follow-up): let the user customize the
generated Requirements tracker's columns - which ones show, what order,
what they're labelled, whether empty rows are dropped, plus their own
added blank columns - both as a reusable per-account default and as a
per-tender override (the client's own words: "different format for the
different [tenders] but may be the same tender").

Adds:
  - users.default_excel_template (JSON, nullable) - the account's saved
    default. See app/models/user.py.
  - tenders.excel_template_override (JSON, nullable) - this one tender's
    override, when it needs to differ from the account default. See
    app/models/tender.py.

Both null on every existing row: nothing changes for an account or tender
that has not opened the customizer - _assemble_folder keeps producing the
same fixed layout it always has until the user actively sets one of these.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a8d2f6c913e7'
down_revision: Union[str, None] = 'f1a7c9e2b504'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('default_excel_template', sa.JSON(), nullable=True))
    op.add_column('tenders', sa.Column('excel_template_override', sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column('tenders', 'excel_template_override')
    op.drop_column('users', 'default_excel_template')
