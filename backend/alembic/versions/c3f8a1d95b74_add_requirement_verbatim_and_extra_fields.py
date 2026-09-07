"""add verbatim requirement fields + extra_fields

Revision ID: c3f8a1d95b74
Revises: e5c1a9d47b62
Create Date: 2026-09-02

The tracker has to reproduce what the tender actually says, and the normalised
columns cannot. Three of them quietly lose information:

  * `page_number` is an Integer, so a clause spanning "1-2" was stored as 1.
  * `is_mandatory` is a Boolean, so the WBS's own "Mandatory/Advisory flag"
    (TN-EXT-02) had nowhere to put "No/Advisory" and it became NULL.
  * `evaluation_impact` is a four-value Enum, so real tender wording such as
    "Financial / Pass-Fail", "Technical Compliance", "Schedule Compliance" or
    "Internal responsibility allocation" was flattened into one bucket or
    dropped entirely.

So each gains a verbatim twin. The normalised columns stay exactly as they are
(coverage, marks and filtering all depend on them); the *_raw columns carry the
tender's own words through to the Excel tracker unchanged.

`extra_fields` is the open end of the schema: a tender that carries a column the
fixed set does not model (a lot number, a delivery window, a weighting) has it
captured here as key -> value, and the tracker grows one spreadsheet column per
distinct key it finds. All nullable and additive - nothing existing is rewritten.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c3f8a1d95b74"
down_revision: Union[str, None] = "e5c1a9d47b62"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("requirements", sa.Column("page_label", sa.String(length=50), nullable=True))
    op.add_column("requirements", sa.Column("mandatory_raw", sa.String(length=100), nullable=True))
    op.add_column(
        "requirements", sa.Column("evaluation_impact_raw", sa.String(length=255), nullable=True)
    )
    op.add_column("requirements", sa.Column("extra_fields", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("requirements", "extra_fields")
    op.drop_column("requirements", "evaluation_impact_raw")
    op.drop_column("requirements", "mandatory_raw")
    op.drop_column("requirements", "page_label")
