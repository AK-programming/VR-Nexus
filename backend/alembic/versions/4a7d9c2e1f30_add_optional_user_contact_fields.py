"""add optional phone and company fields to users

Revision ID: 4a7d9c2e1f30
Revises: 0b55a5033c01
Create Date: 2026-08-20

This is the head of the chain. The frontend register form posts phone_number
and company, both optional, which is why these columns are nullable.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "4a7d9c2e1f30"
down_revision: Union[str, None] = "0b55a5033c01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("phone_number", sa.String(length=32), nullable=True))
    op.add_column("users", sa.Column("company", sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "company")
    op.drop_column("users", "phone_number")
