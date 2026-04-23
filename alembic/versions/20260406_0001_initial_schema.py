"""Initial application schema."""

from __future__ import annotations

from collections.abc import Iterable

from alembic import op
import sqlalchemy as sa


revision = "20260406_0001"
down_revision = None
branch_labels = None
depends_on = None

APP_TABLES = (
    "products",
    "tasks",
    "product_snapshots",
    "product_marketplaces",
    "product_marketplace_features",
    "product_patches",
)


def _dialect_name() -> str:
    """Return the current database dialect name used by the running migration."""
    return op.get_bind().dialect.name


def _now() -> sa.TextClause:
    """Return a portable current timestamp default for migration-created columns."""
    return sa.text("CURRENT_TIMESTAMP")


def _columns(table_name: str) -> set[str]:
    """Load the current column set for one table from the bound connection."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return {column["name"] for column in inspector.get_columns(table_name)}


def _has_table(table_name: str) -> bool:
    """Check whether the target table already exists in the current database."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return inspector.has_table(table_name)


def _existing_indexes(table_name: str) -> set[str]:
    """Return the currently defined index names for one table."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return {index["name"] for index in inspector.get_indexes(table_name)}


def _create_products_table() -> None:
    """Create the root products table before dependent snapshot and patch tables."""
    op.create_table(
        "products",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("article", sa.String(length=255), nullable=False),
        sa.Column("pid", sa.String(length=64), nullable=False),
        sa.Column("external_product_id", sa.String(length=64), nullable=False),
        sa.Column("offer_id", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("latest_snapshot_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=_now()),
        sa.UniqueConstraint("pid", name="uq_products_pid"),
    )
    op.create_index("ix_products_article", "products", ["article"])
    op.create_index("ix_products_pid", "products", ["pid"], unique=True)
    op.create_index("ix_products_external_product_id", "products", ["external_product_id"])


def _create_tasks_table() -> None:
    """Create the workflow task table used by read/save orchestration."""
    op.create_table(
        "tasks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("task_id", sa.String(length=64), nullable=False),
        sa.Column("task_type", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("article", sa.String(length=255), nullable=True),
        sa.Column("pid", sa.String(length=64), nullable=True),
        sa.Column("product_id", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("details", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=_now()),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_tasks_task_id", "tasks", ["task_id"])
    op.create_index("ix_tasks_task_type", "tasks", ["task_type"])
    op.create_index("ix_tasks_status", "tasks", ["status"])


def _create_product_snapshots_table() -> None:
    """Create the normalized snapshot table that stores one read result."""
    op.create_table(
        "product_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=True),
        sa.Column("article", sa.String(length=255), nullable=False),
        sa.Column("pid", sa.String(length=64), nullable=False),
        sa.Column("external_product_id", sa.String(length=64), nullable=False),
        sa.Column("offer_id", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("csrf_save_token", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("basic_fields", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("flags", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("raw_snapshot", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("raw_modal_html", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=_now()),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_product_snapshots_product_id", "product_snapshots", ["product_id"])
    op.create_index("ix_product_snapshots_task_id", "product_snapshots", ["task_id"])
    op.create_index("ix_product_snapshots_article", "product_snapshots", ["article"])
    op.create_index("ix_product_snapshots_pid", "product_snapshots", ["pid"])
    op.create_index("ix_product_snapshots_external_product_id", "product_snapshots", ["external_product_id"])
    if _dialect_name() != "sqlite":
        op.create_foreign_key(
            "fk_products_latest_snapshot_id_product_snapshots",
            "products",
            "product_snapshots",
            ["latest_snapshot_id"],
            ["id"],
            ondelete="SET NULL",
        )


def _create_product_marketplaces_table() -> None:
    """Create the table that stores marketplace-specific snapshot sections."""
    op.create_table(
        "product_marketplaces",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("snapshot_id", sa.Integer(), nullable=False),
        sa.Column("market_id", sa.String(length=64), nullable=False),
        sa.Column("market_cat_id", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("market_cat_name", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("meta", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("fields", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("extinfo", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("raw_product_features", sa.JSON(), nullable=True),
        sa.Column("raw_category_features", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=_now()),
        sa.ForeignKeyConstraint(["snapshot_id"], ["product_snapshots.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("snapshot_id", "market_id", name="uq_product_marketplaces_snapshot_market"),
    )
    op.create_index("ix_product_marketplaces_snapshot_id", "product_marketplaces", ["snapshot_id"])
    op.create_index("ix_product_marketplaces_market_id", "product_marketplaces", ["market_id"])


def _create_product_marketplace_features_table() -> None:
    """Create the table that stores allowed and current feature values per marketplace."""
    op.create_table(
        "product_marketplace_features",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("marketplace_id", sa.Integer(), nullable=False),
        sa.Column("feature_name", sa.String(length=255), nullable=False),
        sa.Column("current_values", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("allowed_values", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("facet", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("required", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("raw_current", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("raw_allowed", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=_now()),
        sa.ForeignKeyConstraint(["marketplace_id"], ["product_marketplaces.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "marketplace_id",
            "feature_name",
            name="uq_product_marketplace_features_marketplace_feature",
        ),
    )
    op.create_index("ix_product_marketplace_features_marketplace_id", "product_marketplace_features", ["marketplace_id"])
    op.create_index("ix_product_marketplace_features_feature_name", "product_marketplace_features", ["feature_name"])


def _create_product_patches_table() -> None:
    """Create the table that stores generated save payloads and normalized patches."""
    op.create_table(
        "product_patches",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=True),
        sa.Column("article", sa.String(length=255), nullable=False),
        sa.Column("pid", sa.String(length=64), nullable=False),
        sa.Column("offer_id", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="built"),
        sa.Column("save_url", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("headers", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("payload", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("basic_fields", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("flags", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("marketplace_patches", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=_now()),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_product_patches_product_id", "product_patches", ["product_id"])
    op.create_index("ix_product_patches_task_id", "product_patches", ["task_id"])
    op.create_index("ix_product_patches_article", "product_patches", ["article"])
    op.create_index("ix_product_patches_pid", "product_patches", ["pid"])


def _create_schema_from_scratch() -> None:
    """Create the full application schema for a clean database."""
    _create_products_table()
    _create_tasks_table()
    _create_product_snapshots_table()
    _create_product_marketplaces_table()
    _create_product_marketplace_features_table()
    _create_product_patches_table()


def _create_missing_indexes(table_name: str, expected_indexes: Iterable[tuple[str, list[str], bool]]) -> None:
    """Create any indexes that are missing when upgrading a pre-existing schema."""
    existing_indexes = _existing_indexes(table_name)
    for index_name, columns, unique in expected_indexes:
        if index_name not in existing_indexes:
            op.create_index(index_name, table_name, columns, unique=unique)


def _drop_index_if_exists(table_name: str, index_name: str) -> None:
    """Drop a legacy index when it is no longer needed after schema normalization."""
    if index_name in _existing_indexes(table_name):
        op.drop_index(index_name, table_name=table_name)


def _upgrade_preexisting_schema() -> None:
    """Adapt the pre-Alembic schema created by `create_all()` to the migration-managed layout."""
    if "foks_product_id" in _columns("products") and "external_product_id" not in _columns("products"):
        op.alter_column(
            "products",
            "foks_product_id",
            new_column_name="external_product_id",
            existing_type=sa.String(length=64),
            existing_nullable=False,
        )

    if "foks_product_id" in _columns("product_snapshots") and "external_product_id" not in _columns("product_snapshots"):
        op.alter_column(
            "product_snapshots",
            "foks_product_id",
            new_column_name="external_product_id",
            existing_type=sa.String(length=64),
            existing_nullable=False,
        )

    _create_missing_indexes(
        "products",
        (
            ("ix_products_article", ["article"], False),
            ("ix_products_pid", ["pid"], True),
            ("ix_products_external_product_id", ["external_product_id"], False),
        ),
    )
    _create_missing_indexes(
        "product_snapshots",
        (
            ("ix_product_snapshots_product_id", ["product_id"], False),
            ("ix_product_snapshots_task_id", ["task_id"], False),
            ("ix_product_snapshots_article", ["article"], False),
            ("ix_product_snapshots_pid", ["pid"], False),
            ("ix_product_snapshots_external_product_id", ["external_product_id"], False),
        ),
    )
    _create_missing_indexes(
        "product_patches",
        (
            ("ix_product_patches_product_id", ["product_id"], False),
            ("ix_product_patches_task_id", ["task_id"], False),
            ("ix_product_patches_article", ["article"], False),
            ("ix_product_patches_pid", ["pid"], False),
        ),
    )
    _drop_index_if_exists("products", "ix_products_foks_product_id")
    _drop_index_if_exists("product_snapshots", "ix_product_snapshots_foks_product_id")


def upgrade() -> None:
    """Create the initial schema or adapt the legacy bootstrap schema to it."""
    if not _has_table("products"):
        _create_schema_from_scratch()
        return

    _upgrade_preexisting_schema()


def downgrade() -> None:
    """Drop the application schema created by the initial migration."""
    for table_name in reversed(APP_TABLES):
        if _has_table(table_name):
            op.drop_table(table_name)
