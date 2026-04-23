"""Add draft author metadata to product patches."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260423_0003"
down_revision = "20260419_0002"
branch_labels = None
depends_on = None


def _columns(table_name: str) -> set[str]:
    """Load the current column set for one table from the bound connection."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return {column["name"] for column in inspector.get_columns(table_name)}


def upgrade() -> None:
    """Add the user identifier that created a draft patch."""
    if "created_by" not in _columns("product_patches"):
        op.add_column("product_patches", sa.Column("created_by", sa.String(length=255), nullable=True))


def downgrade() -> None:
    """Remove the draft author metadata column."""
    if "created_by" in _columns("product_patches"):
        op.drop_column("product_patches", "created_by")
