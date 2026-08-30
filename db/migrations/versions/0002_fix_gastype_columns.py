"""Fix gastype kolommen: CHAR(1) → VARCHAR(20)

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-30
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("gemeente", "gastype_oud", type_=sa.String(20), existing_type=sa.CHAR(1))
    op.alter_column("gemeente", "gastype_nieuw", type_=sa.String(20), existing_type=sa.CHAR(1))


def downgrade() -> None:
    op.alter_column("gemeente", "gastype_oud", type_=sa.CHAR(1), existing_type=sa.String(20))
    op.alter_column("gemeente", "gastype_nieuw", type_=sa.CHAR(1), existing_type=sa.String(20))
