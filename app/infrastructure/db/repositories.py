from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import Select, select
from sqlalchemy.orm import Session, selectinload

from app.domain.models import (
    FeatureValue,
    MarketplaceMeta,
    MarketplacePatch,
    MarketplaceSnapshot,
    PersistedProductPatch,
    PersistedProductSnapshot,
    ProductAggregate,
    ProductIdentity,
    ProductPatch,
    ProductPatchStatus,
    ProductSnapshot,
    ProductWorkflowStatus,
)
from app.infrastructure.db.models import (
    ProductMarketplaceFeatureRecord,
    ProductMarketplaceRecord,
    ProductPatchRecord,
    ProductRecord,
    ProductSnapshotRecord,
    TaskRecord,
)
from app.infrastructure.db.session import session_scope


class ProductRepository:
    """Persist and resolve stable product identity rows independently from snapshots."""

    def get_record_id_by_pid(self, pid: str) -> int | None:
        """Return the database identifier for one product pid when present."""
        with session_scope() as session:
            statement = select(ProductRecord.id).where(ProductRecord.pid == pid)
            return session.scalar(statement)

    def get_or_create_from_snapshot(self, session: Session, snapshot: ProductSnapshot) -> ProductRecord:
        """Find or create the product identity row associated with one snapshot."""
        statement = select(ProductRecord).where(ProductRecord.pid == snapshot.pid)
        product_record = session.scalar(statement)
        if product_record is None:
            product_record = ProductRecord(
                article=snapshot.article,
                pid=snapshot.pid,
                external_product_id=snapshot.product_id,
                offer_id=snapshot.offer_id,
            )
            session.add(product_record)
            session.flush()
        else:
            product_record.article = snapshot.article
            product_record.offer_id = snapshot.offer_id
            product_record.external_product_id = snapshot.product_id
        return product_record


class TaskRepository:
    """Persist workflow task records for read/save operations."""

    def start_task(
        self,
        *,
        task_id: str,
        task_type: str,
        article: str | None = None,
        pid: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> int:
        """Create a task entry in running state and return its database identifier."""
        with session_scope() as session:
            record = TaskRecord(
                task_id=task_id,
                task_type=task_type,
                status="running",
                article=article,
                pid=pid,
                details=details or {},
            )
            session.add(record)
            session.flush()
            return record.id

    def complete_task(
        self,
        task_record_id: int,
        *,
        product_record_id: int | None = None,
        pid: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Mark a task as completed and store its final metadata."""
        with session_scope() as session:
            record = session.get(TaskRecord, task_record_id)
            if record is None:
                return

            record.status = "completed"
            record.product_id = product_record_id
            record.pid = pid or record.pid
            if details:
                record.details = {**record.details, **details}
            record.finished_at = datetime.now(timezone.utc)

    def fail_task(
        self,
        task_record_id: int,
        *,
        error_message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Mark a task as failed without interrupting the original exception flow."""
        with session_scope() as session:
            record = session.get(TaskRecord, task_record_id)
            if record is None:
                return

            record.status = "failed"
            record.error_message = error_message
            if details:
                record.details = {**record.details, **details}
            record.finished_at = datetime.now(timezone.utc)


class SnapshotRepository:
    """Persist normalized snapshots and rebuild them back into domain models."""

    def __init__(self, product_repository: ProductRepository | None = None) -> None:
        """Store the product repository used to resolve product identity rows."""
        self._product_repository = product_repository or ProductRepository()

    def save_snapshot(
        self,
        snapshot: ProductSnapshot,
        *,
        raw_modal_html: str = "",
        task_record_id: int | None = None,
    ) -> tuple[int, ProductSnapshot]:
        """Store a snapshot across normalized tables and return the reloaded domain model."""
        with session_scope() as session:
            product_record = self._product_repository.get_or_create_from_snapshot(session, snapshot)
            snapshot_record = ProductSnapshotRecord(
                product_id=product_record.id,
                task_id=task_record_id,
                article=snapshot.article,
                pid=snapshot.pid,
                external_product_id=snapshot.product_id,
                offer_id=snapshot.offer_id,
                csrf_save_token=snapshot.csrf_save_token,
                basic_fields=dict(snapshot.basic_fields),
                flags=dict(snapshot.flags),
                raw_snapshot=self._serialize_snapshot(snapshot),
                raw_modal_html=raw_modal_html,
            )
            session.add(snapshot_record)
            session.flush()

            for marketplace_snapshot in snapshot.marketplaces.values():
                marketplace_record = ProductMarketplaceRecord(
                    snapshot_id=snapshot_record.id,
                    market_id=marketplace_snapshot.market_id,
                    market_cat_id=marketplace_snapshot.market_cat_id,
                    market_cat_name=marketplace_snapshot.market_cat_name,
                    meta=asdict(marketplace_snapshot.meta),
                    fields=dict(marketplace_snapshot.fields),
                    extinfo=dict(marketplace_snapshot.extinfo),
                    raw_product_features=marketplace_snapshot.raw_product_features,
                    raw_category_features=marketplace_snapshot.raw_category_features,
                )
                session.add(marketplace_record)
                session.flush()

                feature_names = sorted(
                    set(marketplace_snapshot.current_features.keys())
                    | set(marketplace_snapshot.allowed_features.keys())
                )
                for feature_name in feature_names:
                    current_feature = marketplace_snapshot.current_features.get(feature_name)
                    allowed_feature = marketplace_snapshot.allowed_features.get(feature_name)
                    session.add(
                        ProductMarketplaceFeatureRecord(
                            marketplace_id=marketplace_record.id,
                            feature_name=feature_name,
                            current_values=list(current_feature.values if current_feature else []),
                            allowed_values=list(allowed_feature.options if allowed_feature else []),
                            facet=bool((allowed_feature or current_feature).facet) if (allowed_feature or current_feature) else False,
                            required=bool(allowed_feature.required) if allowed_feature else False,
                            raw_current=dict(current_feature.raw) if current_feature and current_feature.raw else {},
                            raw_allowed=dict(allowed_feature.raw) if allowed_feature and allowed_feature.raw else {},
                        )
                    )

            product_record.latest_snapshot_id = snapshot_record.id
            session.flush()

            snapshot_record_id = snapshot_record.id
            product_record_id = product_record.id

        persisted_snapshot = self.get_snapshot_by_id(snapshot_record_id)
        assert persisted_snapshot is not None
        return product_record_id, persisted_snapshot

    def get_snapshot_by_id(self, snapshot_record_id: int) -> ProductSnapshot | None:
        """Load one persisted snapshot and map it back into a domain object."""
        with session_scope() as session:
            statement = self._snapshot_select().where(ProductSnapshotRecord.id == snapshot_record_id)
            snapshot_record = session.scalar(statement)
            if snapshot_record is None:
                return None
            return self._to_domain(snapshot_record)

    def get_latest_snapshot(
        self,
        *,
        article: str | None = None,
        pid: str | None = None,
    ) -> ProductSnapshot | None:
        """Load the latest snapshot for a given article or pid."""
        if article is None and pid is None:
            raise ValueError("Either article or pid must be provided.")

        with session_scope() as session:
            statement = self._snapshot_select().order_by(ProductSnapshotRecord.id.desc())
            if article is not None:
                statement = statement.where(ProductSnapshotRecord.article == article)
            if pid is not None:
                statement = statement.where(ProductSnapshotRecord.pid == pid)

            snapshot_record = session.scalars(statement).first()
            if snapshot_record is None:
                return None
            return self._to_domain(snapshot_record)

    def get_product_record_id_by_pid(self, pid: str) -> int | None:
        """Resolve the database product id for a known FOKS pid."""
        return self._product_repository.get_record_id_by_pid(pid)

    def _snapshot_select(self) -> Select[tuple[ProductSnapshotRecord]]:
        """Build a reusable select statement with all relationships needed for domain mapping."""
        return (
            select(ProductSnapshotRecord)
            .options(
                selectinload(ProductSnapshotRecord.marketplaces).selectinload(ProductMarketplaceRecord.features),
            )
        )

    def _to_domain(self, snapshot_record: ProductSnapshotRecord) -> ProductSnapshot:
        """Map ORM snapshot records into the public domain snapshot model."""
        marketplaces: dict[str, MarketplaceSnapshot] = {}
        for marketplace_record in snapshot_record.marketplaces:
            current_features: dict[str, FeatureValue] = {}
            allowed_features: dict[str, FeatureValue] = {}

            for feature_record in marketplace_record.features:
                if feature_record.current_values or feature_record.raw_current:
                    current_features[feature_record.feature_name] = FeatureValue(
                        name=feature_record.feature_name,
                        values=list(feature_record.current_values),
                        facet=feature_record.facet,
                        required=feature_record.required,
                        options=list(feature_record.allowed_values),
                        raw=dict(feature_record.raw_current or {}),
                    )

                if feature_record.allowed_values or feature_record.raw_allowed or feature_record.required or feature_record.facet:
                    allowed_features[feature_record.feature_name] = FeatureValue(
                        name=feature_record.feature_name,
                        values=[],
                        facet=feature_record.facet,
                        required=feature_record.required,
                        options=list(feature_record.allowed_values),
                        raw=dict(feature_record.raw_allowed or {}),
                    )

            marketplaces[marketplace_record.market_id] = MarketplaceSnapshot(
                market_id=marketplace_record.market_id,
                meta=MarketplaceMeta(**dict(marketplace_record.meta or {})),
                market_cat_id=marketplace_record.market_cat_id,
                market_cat_name=marketplace_record.market_cat_name,
                fields=dict(marketplace_record.fields or {}),
                current_features=current_features,
                allowed_features=allowed_features,
                raw_product_features=marketplace_record.raw_product_features,
                raw_category_features=marketplace_record.raw_category_features,
                extinfo=dict(marketplace_record.extinfo or {}),
            )

        return ProductSnapshot(
            article=snapshot_record.article,
            pid=snapshot_record.pid,
            product_id=snapshot_record.external_product_id,
            offer_id=snapshot_record.offer_id,
            csrf_save_token=snapshot_record.csrf_save_token,
            basic_fields=dict(snapshot_record.basic_fields or {}),
            flags=dict(snapshot_record.flags or {}),
            marketplaces=marketplaces,
        )

    def _serialize_snapshot(self, snapshot: ProductSnapshot) -> dict[str, Any]:
        """Build a JSON-serializable representation of the snapshot for raw storage."""
        return {
            "article": snapshot.article,
            "pid": snapshot.pid,
            "product_id": snapshot.product_id,
            "offer_id": snapshot.offer_id,
            "csrf_save_token": snapshot.csrf_save_token,
            "basic_fields": snapshot.basic_fields,
            "flags": snapshot.flags,
            "marketplaces": {
                market_id: {
                    "market_id": market_snapshot.market_id,
                    "meta": asdict(market_snapshot.meta),
                    "market_cat_id": market_snapshot.market_cat_id,
                    "market_cat_name": market_snapshot.market_cat_name,
                    "fields": market_snapshot.fields,
                    "current_features": {
                        feature_name: asdict(feature)
                        for feature_name, feature in market_snapshot.current_features.items()
                    },
                    "allowed_features": {
                        feature_name: asdict(feature)
                        for feature_name, feature in market_snapshot.allowed_features.items()
                    },
                    "extinfo": market_snapshot.extinfo,
                    "raw_product_features": market_snapshot.raw_product_features,
                    "raw_category_features": market_snapshot.raw_category_features,
                }
                for market_id, market_snapshot in snapshot.marketplaces.items()
            },
        }


class ProductAggregateRepository:
    """Load the API-facing aggregate from the latest persisted product state."""

    DRAFT_WORKFLOW_STATUSES = ("draft", "approved", "saved", "failed", "verification_failed")
    SAVE_WORKFLOW_STATUSES = ("saved", "failed", "verification_failed")

    def __init__(
        self,
        product_repository: ProductRepository | None = None,
        snapshot_repository: SnapshotRepository | None = None,
    ) -> None:
        """Store helper repositories used to map ORM rows into domain objects."""
        self._product_repository = product_repository or ProductRepository()
        self._snapshot_repository = snapshot_repository or SnapshotRepository(product_repository=self._product_repository)

    def get_latest_aggregate_by_article(self, article: str) -> ProductAggregate | None:
        """Load the latest persisted aggregate for one article."""
        with session_scope() as session:
            statement = (
                select(ProductRecord.id)
                .join(
                    ProductSnapshotRecord,
                    ProductSnapshotRecord.id == ProductRecord.latest_snapshot_id,
                )
                .where(ProductRecord.article == article)
                .order_by(ProductSnapshotRecord.id.desc(), ProductRecord.id.desc())
            )
            product_record_id = session.scalar(statement)
            if product_record_id is None:
                return None
            return self._load_aggregate(session, product_record_id)

    def get_latest_aggregate_by_id(self, product_record_id: int) -> ProductAggregate | None:
        """Load the latest persisted aggregate for one internal product id."""
        with session_scope() as session:
            return self._load_aggregate(session, product_record_id)

    def _load_aggregate(self, session: Session, product_record_id: int) -> ProductAggregate | None:
        """Compose identity, snapshot, marketplaces, and workflow state into one view model."""
        product_record = session.get(ProductRecord, product_record_id)
        if product_record is None or product_record.latest_snapshot_id is None:
            return None

        snapshot_statement = self._snapshot_repository._snapshot_select().where(
            ProductSnapshotRecord.id == product_record.latest_snapshot_id
        )
        snapshot_record = session.scalar(snapshot_statement)
        if snapshot_record is None:
            return None

        snapshot = self._snapshot_repository._to_domain(snapshot_record)
        draft_patch_record = self._get_latest_patch_record(
            session=session,
            product_record_id=product_record.id,
            statuses=self.DRAFT_WORKFLOW_STATUSES,
        )
        save_patch_record = self._get_latest_patch_record(
            session=session,
            product_record_id=product_record.id,
            statuses=self.SAVE_WORKFLOW_STATUSES,
        )
        draft_status = self._to_patch_status(draft_patch_record)
        save_status = self._to_patch_status(save_patch_record)

        return ProductAggregate(
            identity=ProductIdentity(
                id=product_record.id,
                article=product_record.article,
                pid=product_record.pid,
                external_product_id=product_record.external_product_id,
                offer_id=product_record.offer_id,
                latest_snapshot_id=product_record.latest_snapshot_id,
                created_at=product_record.created_at,
                updated_at=product_record.updated_at,
            ),
            latest_snapshot=PersistedProductSnapshot(
                id=snapshot_record.id,
                article=snapshot_record.article,
                pid=snapshot_record.pid,
                product_id=snapshot_record.external_product_id,
                offer_id=snapshot_record.offer_id,
                task_id=snapshot_record.task_id,
                basic_fields=dict(snapshot_record.basic_fields or {}),
                flags=dict(snapshot_record.flags or {}),
                captured_at=snapshot_record.created_at,
                updated_at=snapshot_record.updated_at,
            ),
            marketplaces=dict(snapshot.marketplaces),
            workflow=ProductWorkflowStatus(
                draft=draft_status,
                save=save_status,
            ),
        )

    def _get_latest_patch_record(
        self,
        *,
        session: Session,
        product_record_id: int,
        statuses: tuple[str, ...],
    ) -> ProductPatchRecord | None:
        """Load the newest patch row for one product within a workflow status subset."""
        return session.scalars(
            select(ProductPatchRecord)
            .where(
                ProductPatchRecord.product_id == product_record_id,
                ProductPatchRecord.status.in_(statuses),
            )
            .order_by(ProductPatchRecord.id.desc())
        ).first()

    def _to_patch_status(self, patch_record: ProductPatchRecord | None) -> ProductPatchStatus | None:
        """Convert one patch row into the API-facing workflow status model."""
        if patch_record is None:
            return None

        return ProductPatchStatus(
            patch_id=patch_record.id,
            status=patch_record.status,
            base_snapshot_id=patch_record.base_snapshot_id,
            task_id=patch_record.task_id,
            save_url=patch_record.save_url,
            validation_warnings=list(patch_record.validation_warnings or []),
            validation_errors=list(patch_record.validation_errors or []),
            diff_summary=dict(patch_record.diff_summary or {}),
            created_by=patch_record.created_by or "",
            approved_at=patch_record.approved_at,
            approved_by=patch_record.approved_by or "",
            save_result=dict(patch_record.save_result or {}),
            created_at=patch_record.created_at,
            updated_at=patch_record.updated_at,
        )


class PatchRepository:
    """Persist generated product patches and outgoing save payloads."""

    def save_patch(
        self,
        *,
        product_record_id: int,
        patch: ProductPatch,
        article: str,
        pid: str,
        base_snapshot_id: int | None = None,
        status: str = "built",
        created_by: str | None = None,
        save_url: str,
        headers: dict[str, Any],
        payload: dict[str, Any],
        validation_warnings: list[str] | None = None,
        validation_errors: list[str] | None = None,
        diff_summary: dict[str, Any] | None = None,
        approved_at: datetime | None = None,
        approved_by: str | None = None,
        save_result: dict[str, Any] | None = None,
        task_record_id: int | None = None,
    ) -> int:
        """Store one generated patch entry for later inspection or replay."""
        with session_scope() as session:
            record = ProductPatchRecord(
                product_id=product_record_id,
                task_id=task_record_id,
                article=article,
                pid=pid,
                base_snapshot_id=base_snapshot_id,
                offer_id=patch.offer_id,
                status=status,
                created_by=created_by,
                save_url=save_url,
                headers=headers,
                payload=payload,
                basic_fields=patch.basic_fields,
                flags=patch.flags,
                marketplace_patches=self._serialize_marketplace_patches(patch.marketplace_patches),
                validation_warnings=list(validation_warnings or []),
                validation_errors=list(validation_errors or []),
                diff_summary=dict(diff_summary or {}),
                approved_at=approved_at,
                approved_by=approved_by,
                save_result=dict(save_result or {}),
            )
            session.add(record)
            session.flush()
            return record.id

    def get_patch_by_id(self, patch_id: int) -> PersistedProductPatch | None:
        """Load one persisted patch record and map it back into a domain object."""
        with session_scope() as session:
            record = session.get(ProductPatchRecord, patch_id)
            if record is None:
                return None
            return self._to_domain(record)

    def update_patch(
        self,
        patch_id: int,
        *,
        status: str | None = None,
        created_by: str | None = None,
        save_url: str | None = None,
        headers: dict[str, Any] | None = None,
        payload: dict[str, Any] | None = None,
        validation_warnings: list[str] | None = None,
        validation_errors: list[str] | None = None,
        diff_summary: dict[str, Any] | None = None,
        approved_at: datetime | None = None,
        approved_by: str | None = None,
        save_result: dict[str, Any] | None = None,
        task_record_id: int | None = None,
    ) -> PersistedProductPatch | None:
        """Update one patch lifecycle record and return its refreshed domain representation."""
        with session_scope() as session:
            record = session.get(ProductPatchRecord, patch_id)
            if record is None:
                return None

            if status is not None:
                record.status = status
            if created_by is not None:
                record.created_by = created_by
            if save_url is not None:
                record.save_url = save_url
            if headers is not None:
                record.headers = headers
            if payload is not None:
                record.payload = payload
            if validation_warnings is not None:
                record.validation_warnings = list(validation_warnings)
            if validation_errors is not None:
                record.validation_errors = list(validation_errors)
            if diff_summary is not None:
                record.diff_summary = dict(diff_summary)
            if approved_at is not None:
                record.approved_at = approved_at
            if approved_by is not None:
                record.approved_by = approved_by
            if save_result is not None:
                record.save_result = dict(save_result)
            if task_record_id is not None:
                record.task_id = task_record_id
            session.flush()
            session.refresh(record)
            return self._to_domain(record)

    def _serialize_marketplace_patches(
        self,
        marketplace_patches: dict[str, MarketplacePatch],
    ) -> dict[str, Any]:
        """Convert marketplace patch dataclasses into JSON-ready dictionaries."""
        return {
            market_id: {
                "market_id": patch.market_id,
                "market_cat_id": patch.market_cat_id,
                "market_cat_name": patch.market_cat_name,
                "fields": patch.fields,
                "feature_values": {
                    feature_name: asdict(feature_value)
                    for feature_name, feature_value in patch.feature_values.items()
                },
                "extinfo": patch.extinfo,
            }
            for market_id, patch in marketplace_patches.items()
        }

    def _deserialize_marketplace_patches(self, payload: dict[str, Any]) -> dict[str, MarketplacePatch]:
        """Convert JSON patch payloads back into marketplace patch dataclasses."""
        marketplace_patches: dict[str, MarketplacePatch] = {}
        for market_id, patch_payload in (payload or {}).items():
            feature_values = {
                feature_name: FeatureValue(
                    name=feature_payload.get("name", feature_name),
                    values=list(feature_payload.get("values", [])),
                    facet=bool(feature_payload.get("facet", False)),
                    required=bool(feature_payload.get("required", False)),
                    options=list(feature_payload.get("options", [])),
                    raw=dict(feature_payload.get("raw", {})),
                )
                for feature_name, feature_payload in dict(patch_payload.get("feature_values", {})).items()
            }
            marketplace_patches[market_id] = MarketplacePatch(
                market_id=patch_payload.get("market_id", market_id),
                market_cat_id=patch_payload.get("market_cat_id"),
                market_cat_name=patch_payload.get("market_cat_name"),
                fields=dict(patch_payload.get("fields", {})),
                feature_values=feature_values,
                extinfo=dict(patch_payload.get("extinfo", {})),
            )
        return marketplace_patches

    def _to_domain(self, record: ProductPatchRecord) -> PersistedProductPatch:
        """Map one ORM patch row into the public domain patch lifecycle model."""
        patch = ProductPatch(
            product_id=str((record.payload or {}).get("id") or getattr(record.product, "external_product_id", "") or ""),
            offer_id=record.offer_id,
            basic_fields=dict(record.basic_fields or {}),
            flags=dict(record.flags or {}),
            marketplace_patches=self._deserialize_marketplace_patches(record.marketplace_patches or {}),
        )

        return PersistedProductPatch(
            patch_id=record.id,
            product_record_id=record.product_id,
            article=record.article,
            pid=record.pid,
            status=record.status,
            patch=patch,
            base_snapshot_id=record.base_snapshot_id,
            task_id=record.task_id,
            created_by=record.created_by or "",
            save_url=record.save_url,
            headers=dict(record.headers or {}),
            payload=dict(record.payload or {}),
            validation_warnings=list(record.validation_warnings or []),
            validation_errors=list(record.validation_errors or []),
            diff_summary=dict(record.diff_summary or {}),
            approved_at=record.approved_at,
            approved_by=record.approved_by or "",
            save_result=dict(record.save_result or {}),
            created_at=record.created_at,
            updated_at=record.updated_at,
        )
