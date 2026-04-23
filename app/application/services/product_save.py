from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any

from app.application.ports import PatchRepositoryPort, SnapshotRepositoryPort, TaskRepositoryPort
from app.application.services.product_aggregate import GetProductAggregateService, RefreshProductAggregateService
from app.domain.models import FeatureValue, MarketplaceSnapshot, PersistedProductPatch, ProductPatch, ProductSnapshot
from app.domain.services.payload_builder import SavePayloadBuilder
from app.infrastructure.foks.session import FoksSession
from app.infrastructure.logging import get_logger, get_task_id


class ApplyProductPatchService:
    """Apply one validated normalized patch to a persisted snapshot-derived model."""

    def apply(self, *, snapshot: ProductSnapshot, patch: ProductPatch) -> ProductSnapshot:
        """Return a new snapshot view that includes all validated patch changes."""
        updated_marketplaces = {
            market_id: self._apply_marketplace_patch(
                marketplace=snapshot.marketplaces[market_id],
                patch=patch.marketplace_patches.get(market_id),
            )
            for market_id in snapshot.marketplaces
        }

        return ProductSnapshot(
            article=snapshot.article,
            pid=snapshot.pid,
            product_id=patch.product_id or snapshot.product_id,
            offer_id=patch.offer_id or snapshot.offer_id,
            csrf_save_token=snapshot.csrf_save_token,
            basic_fields=dict(snapshot.basic_fields),
            flags=dict(snapshot.flags),
            marketplaces=updated_marketplaces,
        )

    def build_save_payload(self, *, snapshot: ProductSnapshot) -> dict[str, Any]:
        """Build the final FOKS save payload from an already patched snapshot."""
        product_features = {
            market_id: self._build_product_feature_payload(marketplace)
            for market_id, marketplace in snapshot.marketplaces.items()
        }
        category_schemas = {
            market_id: marketplace.raw_category_features
            for market_id, marketplace in snapshot.marketplaces.items()
        }
        return SavePayloadBuilder.build(
            modal=snapshot.to_modal_parse_result(),
            product_features=product_features,
            category_schemas=category_schemas,
        )

    def _apply_marketplace_patch(
        self,
        *,
        marketplace: MarketplaceSnapshot,
        patch: Any | None,
    ) -> MarketplaceSnapshot:
        """Overlay one marketplace patch onto the snapshot marketplace state."""
        if patch is None:
            return replace(
                marketplace,
                fields=dict(marketplace.fields),
                current_features={
                    feature_name: self._clone_feature_value(feature_value)
                    for feature_name, feature_value in marketplace.current_features.items()
                },
                allowed_features={
                    feature_name: self._clone_feature_value(feature_value)
                    for feature_name, feature_value in marketplace.allowed_features.items()
                },
                extinfo=deepcopy(marketplace.extinfo),
            )

        fields = dict(marketplace.fields)
        fields.update(patch.fields)

        current_features = {
            feature_name: self._clone_feature_value(feature_value)
            for feature_name, feature_value in marketplace.current_features.items()
        }
        for feature_name, feature_value in patch.feature_values.items():
            existing_feature = current_features.get(feature_name) or marketplace.allowed_features.get(feature_name)
            current_features[feature_name] = FeatureValue(
                name=feature_name,
                values=list(feature_value.values),
                facet=bool(existing_feature.facet) if existing_feature else False,
                required=bool(existing_feature.required) if existing_feature else False,
                options=list(existing_feature.options) if existing_feature else [],
                raw=dict(existing_feature.raw) if existing_feature and existing_feature.raw else {},
            )

        return MarketplaceSnapshot(
            market_id=marketplace.market_id,
            meta=marketplace.meta,
            market_cat_id=patch.market_cat_id or marketplace.market_cat_id,
            market_cat_name=patch.market_cat_name or marketplace.market_cat_name,
            fields=fields,
            current_features=current_features,
            allowed_features={
                feature_name: self._clone_feature_value(feature_value)
                for feature_name, feature_value in marketplace.allowed_features.items()
            },
            raw_product_features=self._build_product_feature_payload_from_map(current_features),
            raw_category_features=deepcopy(marketplace.raw_category_features),
            extinfo=deepcopy(patch.extinfo or marketplace.extinfo),
        )

    def _build_product_feature_payload(self, marketplace: MarketplaceSnapshot) -> dict[str, list[str]]:
        """Convert one marketplace's current features into the payload format used by the save builder."""
        return self._build_product_feature_payload_from_map(marketplace.current_features)

    def _build_product_feature_payload_from_map(
        self,
        features: dict[str, FeatureValue],
    ) -> dict[str, list[str]]:
        """Serialize current feature values into a stable name-to-values mapping."""
        return {
            feature_name: list(feature_value.values)
            for feature_name, feature_value in features.items()
        }

    def _clone_feature_value(self, feature_value: FeatureValue) -> FeatureValue:
        """Create a detached copy of one feature value dataclass."""
        return FeatureValue(
            name=feature_value.name,
            values=list(feature_value.values),
            facet=feature_value.facet,
            required=feature_value.required,
            options=list(feature_value.options),
            raw=dict(feature_value.raw),
        )


class SaveProductPatchService:
    """Approve, execute, and verify saving one persisted draft patch through FOKS."""

    def __init__(
        self,
        *,
        aggregate_service: GetProductAggregateService,
        refresh_service: RefreshProductAggregateService,
        snapshot_repository: SnapshotRepositoryPort,
        patch_repository: PatchRepositoryPort,
        task_repository: TaskRepositoryPort,
        apply_patch_service: ApplyProductPatchService | None = None,
        session_factory: type[FoksSession] = FoksSession,
    ) -> None:
        """Prepare collaborators needed for persisted draft save orchestration."""
        self._aggregate_service = aggregate_service
        self._refresh_service = refresh_service
        self._snapshot_repository = snapshot_repository
        self._patch_repository = patch_repository
        self._task_repository = task_repository
        self._apply_patch_service = apply_patch_service or ApplyProductPatchService()
        self._session_factory = session_factory
        self._save_logger = get_logger("app.integration.foks.save")

    def save(
        self,
        *,
        patch_id: int,
        base_url: str,
        username: str,
        password: str,
        approved_by: str = "",
        mids: list[str] | None = None,
    ) -> PersistedProductPatch:
        """Save one persisted draft patch, refresh the product, and persist verification metadata."""
        persisted_patch = self._patch_repository.get_patch_by_id(patch_id)
        if persisted_patch is None:
            raise LookupError(f"Persisted patch '{patch_id}' was not found.")
        if persisted_patch.status not in {"draft", "approved"}:
            raise ValueError("Only draft or approved patches can be saved.")
        if persisted_patch.validation_errors:
            raise ValueError("Patch contains validation errors and cannot be saved.")
        if persisted_patch.base_snapshot_id is None:
            raise ValueError("Patch is missing base_snapshot_id and cannot be safely saved.")

        aggregate = self._aggregate_service.get_by_id(product_id=persisted_patch.product_record_id)
        if aggregate is None or aggregate.latest_snapshot is None:
            raise LookupError(f"Persisted aggregate for patch '{patch_id}' was not found.")
        if aggregate.latest_snapshot.id != persisted_patch.base_snapshot_id:
            raise ValueError(
                "Patch was generated from a stale snapshot. Refresh the product and generate a new preview."
            )

        base_snapshot = self._snapshot_repository.get_snapshot_by_id(persisted_patch.base_snapshot_id)
        if base_snapshot is None:
            raise LookupError(f"Base snapshot '{persisted_patch.base_snapshot_id}' was not found.")

        task_record_id = self._task_repository.start_task(
            task_id=get_task_id(),
            task_type="save_patch",
            article=persisted_patch.article,
            pid=persisted_patch.pid,
            details={
                "patch_id": patch_id,
                "base_snapshot_id": persisted_patch.base_snapshot_id,
            },
        )

        try:
            session = self._session_factory(
                base_url=base_url,
                username=username,
                password=password,
            )
            patched_snapshot = self._apply_patch_service.apply(
                snapshot=base_snapshot,
                patch=persisted_patch.patch,
            )
            payload = self._apply_patch_service.build_save_payload(snapshot=patched_snapshot)
            headers = session.build_json_headers(csrf_token=patched_snapshot.csrf_save_token)
            approved_at = datetime.now(timezone.utc)

            self._patch_repository.update_patch(
                patch_id,
                status="approved",
                approved_at=approved_at,
                approved_by=approved_by,
                save_url="/c/products/save",
                headers=headers,
                payload=payload,
                task_record_id=task_record_id,
                save_result={
                    "pre_save_snapshot_id": persisted_patch.base_snapshot_id,
                    "audit": self._build_audit(
                        persisted_patch=persisted_patch,
                        approved_by=approved_by,
                        post_save_snapshot_id=None,
                    ),
                    "verification": {"status": "pending"},
                },
            )

            self._save_logger.info(
                "foks_save_request_started",
                extra={
                    "event": "foks_save_request_started",
                    "article": persisted_patch.article,
                    "pid": persisted_patch.pid,
                    "patch_id": patch_id,
                    "change_count": persisted_patch.diff_summary.get("change_count", 0),
                },
            )
            response_payload = session.post_json(
                "/c/products/save",
                json_body=payload,
                csrf_token=patched_snapshot.csrf_save_token,
            )
            self._save_logger.info(
                "foks_save_request_completed",
                extra={
                    "event": "foks_save_request_completed",
                    "article": persisted_patch.article,
                    "pid": persisted_patch.pid,
                    "patch_id": patch_id,
                    "response_type": type(response_payload).__name__,
                },
            )

            refreshed_aggregate = self._refresh_service.refresh(
                base_url=base_url,
                username=username,
                password=password,
                article=persisted_patch.article,
                mids=mids,
            )
            verification = self._build_verification(
                base_aggregate=aggregate,
                refreshed_aggregate=refreshed_aggregate,
                persisted_patch=persisted_patch,
            )
            final_status = "saved" if verification["status"] == "ok" else "failed"
            updated_patch = self._patch_repository.update_patch(
                patch_id,
                status=final_status,
                save_result={
                    "pre_save_snapshot_id": persisted_patch.base_snapshot_id,
                    "post_save_snapshot_id": (
                        refreshed_aggregate.latest_snapshot.id if refreshed_aggregate.latest_snapshot else None
                    ),
                    "audit": self._build_audit(
                        persisted_patch=persisted_patch,
                        approved_by=approved_by,
                        post_save_snapshot_id=(
                            refreshed_aggregate.latest_snapshot.id if refreshed_aggregate.latest_snapshot else None
                        ),
                    ),
                    "response": response_payload,
                    "verification": verification,
                },
            )
            self._task_repository.complete_task(
                task_record_id,
                product_record_id=persisted_patch.product_record_id,
                pid=persisted_patch.pid,
                details={
                    "patch_id": patch_id,
                    "status": final_status,
                    "verification_status": verification["status"],
                    "mismatch_count": verification["mismatch_count"],
                },
            )
            assert updated_patch is not None
            return updated_patch
        except Exception as exc:
            self._patch_repository.update_patch(
                patch_id,
                status="failed",
                save_result={
                    "pre_save_snapshot_id": persisted_patch.base_snapshot_id,
                    "audit": self._build_audit(
                        persisted_patch=persisted_patch,
                        approved_by=approved_by,
                        post_save_snapshot_id=None,
                    ),
                    "error": str(exc),
                },
            )
            self._task_repository.fail_task(
                task_record_id,
                error_message=str(exc),
                details={"patch_id": patch_id},
            )
            raise

    def _build_verification(
        self,
        *,
        base_aggregate: Any,
        refreshed_aggregate: Any,
        persisted_patch: PersistedProductPatch,
    ) -> dict[str, Any]:
        """Compare expected patch changes with the refreshed persisted aggregate."""
        mismatches: list[dict[str, Any]] = []
        matched_change_count = 0

        for market_id, marketplace_changes in persisted_patch.diff_summary.get("marketplaces", {}).items():
            base_marketplace = base_aggregate.marketplaces.get(market_id)
            refreshed_marketplace = refreshed_aggregate.marketplaces.get(market_id)
            if base_marketplace is None or refreshed_marketplace is None:
                mismatches.append(
                    {
                        "market_id": market_id,
                        "type": "marketplace_missing",
                        "expected": "marketplace to be present after refresh",
                    }
                )
                continue

            for field_change in marketplace_changes.get("field_changes", []):
                actual_value = str(refreshed_marketplace.fields.get(field_change["field"], "") or "")
                if actual_value == field_change["after"]:
                    matched_change_count += 1
                    continue
                mismatches.append(
                    {
                        "market_id": market_id,
                        "type": "field",
                        "name": field_change["field"],
                        "before": str(base_marketplace.fields.get(field_change["field"], "") or ""),
                        "expected": field_change["after"],
                        "actual": actual_value,
                    }
                )

            for feature_change in marketplace_changes.get("feature_changes", []):
                actual_values = list(
                    refreshed_marketplace.current_features.get(
                        feature_change["feature"],
                        FeatureValue(name=feature_change["feature"]),
                    ).values
                )
                if actual_values == list(feature_change["after"]):
                    matched_change_count += 1
                    continue
                mismatches.append(
                    {
                        "market_id": market_id,
                        "type": "feature",
                        "name": feature_change["feature"],
                        "before": list(
                            base_marketplace.current_features.get(
                                feature_change["feature"],
                                FeatureValue(name=feature_change["feature"]),
                            ).values
                        ),
                        "expected": list(feature_change["after"]),
                        "actual": actual_values,
                    }
                )

        return {
            "status": "ok" if not mismatches else "mismatch",
            "expected_change_count": persisted_patch.diff_summary.get("change_count", 0),
            "matched_change_count": matched_change_count,
            "mismatch_count": len(mismatches),
            "mismatches": mismatches,
        }

    def _build_audit(
        self,
        *,
        persisted_patch: PersistedProductPatch,
        approved_by: str,
        post_save_snapshot_id: int | None,
    ) -> dict[str, Any]:
        """Build a compact audit record that explains who changed what and from which snapshot."""
        return {
            "patch_id": persisted_patch.patch_id,
            "product_record_id": persisted_patch.product_record_id,
            "article": persisted_patch.article,
            "pid": persisted_patch.pid,
            "created_by": persisted_patch.created_by,
            "approved_by": approved_by,
            "base_snapshot_id": persisted_patch.base_snapshot_id,
            "post_save_snapshot_id": post_save_snapshot_id,
            "diff_summary": persisted_patch.diff_summary,
        }
