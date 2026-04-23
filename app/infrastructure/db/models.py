from __future__ import annotations

from typing import Any

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.db.base import Base, TimestampMixin


class ProductRecord(TimestampMixin, Base):
    """Persist the stable identity of a product across snapshots and patches."""

    __tablename__ = "products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    article: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    pid: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    external_product_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    offer_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    latest_snapshot_id: Mapped[int | None] = mapped_column(
        ForeignKey("product_snapshots.id", ondelete="SET NULL"),
        nullable=True,
    )

    snapshots: Mapped[list["ProductSnapshotRecord"]] = relationship(
        back_populates="product",
        foreign_keys="ProductSnapshotRecord.product_id",
        cascade="all, delete-orphan",
    )
    patches: Mapped[list["ProductPatchRecord"]] = relationship(
        back_populates="product",
        cascade="all, delete-orphan",
    )


class TaskRecord(TimestampMixin, Base):
    """Store execution attempts for read/save workflows."""

    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    task_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    article: Mapped[str | None] = mapped_column(String(255), nullable=True)
    pid: Mapped[str | None] = mapped_column(String(64), nullable=True)
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id", ondelete="SET NULL"), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    snapshots: Mapped[list["ProductSnapshotRecord"]] = relationship(back_populates="task")
    patches: Mapped[list["ProductPatchRecord"]] = relationship(back_populates="task")


class ProductSnapshotRecord(TimestampMixin, Base):
    """Persist one full product snapshot together with its raw modal representation."""

    __tablename__ = "product_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True)
    task_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True, index=True)
    article: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    pid: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    external_product_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    offer_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    csrf_save_token: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    basic_fields: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    flags: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    raw_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    raw_modal_html: Mapped[str] = mapped_column(Text, nullable=False, default="")

    product: Mapped[ProductRecord] = relationship(back_populates="snapshots", foreign_keys=[product_id])
    task: Mapped[TaskRecord | None] = relationship(back_populates="snapshots")
    marketplaces: Mapped[list["ProductMarketplaceRecord"]] = relationship(
        back_populates="snapshot",
        cascade="all, delete-orphan",
    )


class ProductMarketplaceRecord(TimestampMixin, Base):
    """Persist marketplace-specific parts of a product snapshot."""

    __tablename__ = "product_marketplaces"
    __table_args__ = (
        UniqueConstraint("snapshot_id", "market_id", name="uq_product_marketplaces_snapshot_market"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("product_snapshots.id", ondelete="CASCADE"), nullable=False, index=True)
    market_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    market_cat_id: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    market_cat_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    meta: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    fields: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    extinfo: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    raw_product_features: Mapped[Any] = mapped_column(JSON, nullable=True)
    raw_category_features: Mapped[Any] = mapped_column(JSON, nullable=True)

    snapshot: Mapped[ProductSnapshotRecord] = relationship(back_populates="marketplaces")
    features: Mapped[list["ProductMarketplaceFeatureRecord"]] = relationship(
        back_populates="marketplace",
        cascade="all, delete-orphan",
    )


class ProductMarketplaceFeatureRecord(TimestampMixin, Base):
    """Persist normalized feature values allowed/current for one marketplace snapshot."""

    __tablename__ = "product_marketplace_features"
    __table_args__ = (
        UniqueConstraint("marketplace_id", "feature_name", name="uq_product_marketplace_features_marketplace_feature"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    marketplace_id: Mapped[int] = mapped_column(ForeignKey("product_marketplaces.id", ondelete="CASCADE"), nullable=False, index=True)
    feature_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    current_values: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    allowed_values: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    facet: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    raw_current: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    raw_allowed: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    marketplace: Mapped[ProductMarketplaceRecord] = relationship(back_populates="features")


class ProductPatchRecord(TimestampMixin, Base):
    """Persist generated patch/save payload data for later inspection or replay."""

    __tablename__ = "product_patches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True)
    task_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True, index=True)
    article: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    pid: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    base_snapshot_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    offer_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="built")
    created_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    save_url: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    headers: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    basic_fields: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    flags: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    marketplace_patches: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    validation_warnings: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    validation_errors: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    diff_summary: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    save_result: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    product: Mapped[ProductRecord] = relationship(back_populates="patches")
    task: Mapped[TaskRecord | None] = relationship(back_populates="patches")
