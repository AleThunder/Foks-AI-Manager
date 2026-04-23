"""Add AI patch lifecycle metadata columns."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260419_0002"
down_revision = "20260406_0001"
branch_labels = None
depends_on = None


def _columns(table_name: str) -> set[str]:
    """Load the current column set for one table from the bound connection."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return {column["name"] for column in inspector.get_columns(table_name)}


def _existing_indexes(table_name: str) -> set[str]:
    """Return the currently defined index names for one table."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return {index["name"] for index in inspector.get_indexes(table_name)}


def upgrade() -> None:
    """Extend product patch records with lifecycle metadata required by the AI pipeline."""
    columns = _columns("product_patches")

    if "base_snapshot_id" not in columns:
        op.add_column("product_patches", sa.Column("base_snapshot_id", sa.Integer(), nullable=True))
    if "validation_warnings" not in columns:
        op.add_column(
            "product_patches",
            sa.Column("validation_warnings", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        )
    if "validation_errors" not in columns:
        op.add_column(
            "product_patches",
            sa.Column("validation_errors", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        )
    if "diff_summary" not in columns:
        op.add_column(
            "product_patches",
            sa.Column("diff_summary", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        )
    if "approved_at" not in columns:
        op.add_column("product_patches", sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True))
    if "approved_by" not in columns:
        op.add_column("product_patches", sa.Column("approved_by", sa.String(length=255), nullable=True))
    if "save_result" not in columns:
        op.add_column(
            "product_patches",
            sa.Column("save_result", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        )

    if "ix_product_patches_base_snapshot_id" not in _existing_indexes("product_patches"):
        op.create_index("ix_product_patches_base_snapshot_id", "product_patches", ["base_snapshot_id"])


def downgrade() -> None:
    """Drop the AI patch lifecycle metadata columns."""
    if "ix_product_patches_base_snapshot_id" in _existing_indexes("product_patches"):
        op.drop_index("ix_product_patches_base_snapshot_id", table_name="product_patches")

    columns = _columns("product_patches")
    for column_name in (
        "save_result",
        "approved_by",
        "approved_at",
        "diff_summary",
        "validation_errors",
        "validation_warnings",
        "base_snapshot_id",
    ):
        if column_name in columns:
            op.drop_column("product_patches", column_name)
