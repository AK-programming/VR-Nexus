"""Add the responsibility-matrix columns the Requirement model already declared.

THE BUG THIS FIXES. `app/models/requirement.py` has declared `responsibility`,
`dpl`, `prime`, `the_t` and `joint_responsibility` since the Stage 2 extraction
work, but no migration ever created them — they exist in Python and not in
Postgres. Every tender run therefore died the moment it touched the requirements
table, with:

    (psycopg.errors.UndefinedColumn) column "responsibility" of relation
    "requirements" does not exist

on the INSERT during extraction, and the same on the SELECT during merging. The
model, the extraction writer, the Excel tracker's "Responsibility" / "DPL" /
"PRIME" / "The Tulepaak" / "Joint Responsibility" columns and the API schema were
all already reading and writing these five fields; only the table was missing
them, which is why the failure looked like a code bug and was a schema gap.

Guarded with an inspector rather than a bare add_column: a database created by
`Base.metadata.create_all` (as some of the archival prototypes did) already has
these columns, and this migration has to be safe to run against both that and a
database built purely from this migration chain.

Revision ID: f1a6c07d3e58
Revises: d7b2e4c88a19
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f1a6c07d3e58"
down_revision: Union[str, None] = "d7b2e4c88a19"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


#: Exactly the model's declarations, in the model's order.
COLUMNS: list[sa.Column] = [
    sa.Column("responsibility", sa.String(length=500), nullable=True),
    sa.Column("dpl", sa.String(length=255), nullable=True),
    sa.Column("prime", sa.String(length=255), nullable=True),
    sa.Column("the_t", sa.String(length=255), nullable=True),
    sa.Column("joint_responsibility", sa.String(length=255), nullable=True),
]


def _existing() -> set[str]:
    inspector = sa.inspect(op.get_bind())
    return {column["name"] for column in inspector.get_columns("requirements")}


def upgrade() -> None:
    present = _existing()
    for column in COLUMNS:
        if column.name not in present:
            op.add_column("requirements", column)


def downgrade() -> None:
    present = _existing()
    for column in reversed(COLUMNS):
        if column.name in present:
            op.drop_column("requirements", column.name)
