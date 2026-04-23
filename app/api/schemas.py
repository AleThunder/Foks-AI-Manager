from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, model_validator

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
    ProductWorkflowStatus,
)


class BuildPayloadRequest(BaseModel):
    """Describe the input payload for building a FOKS save request."""
    article: str = Field(min_length=1)
    mids: list[str] | None = None
    base_url: str | None = None
    username: str | None = None
    password: str | None = None
    payload_only: bool = False


class BuildPayloadResponse(BaseModel):
    """Wrap the generated save request or raw payload returned by the API."""
    data: dict[str, Any]


class RefreshProductRequest(BaseModel):
    """Describe the input payload for refreshing one product snapshot from FOKS."""
    article: str = Field(min_length=1)
    mids: list[str] | None = None
    base_url: str | None = None
    username: str | None = None
    password: str | None = None


class MarketplaceMetaResponse(BaseModel):
    """Expose stable marketplace metadata in the public aggregate."""
    marketid: str
    catid: str = ""
    custcatid: str = ""

    @classmethod
    def from_domain(cls, meta: MarketplaceMeta) -> "MarketplaceMetaResponse":
        """Convert one domain marketplace meta object into the response schema."""
        return cls(
            marketid=meta.marketid,
            catid=meta.catid,
            custcatid=meta.custcatid,
        )


class FeatureValueResponse(BaseModel):
    """Expose normalized feature values without raw FOKS-specific payload noise."""
    name: str
    values: list[str] = Field(default_factory=list)
    facet: bool = False
    required: bool = False
    options: list[str] = Field(default_factory=list)

    @classmethod
    def from_domain(cls, feature: FeatureValue) -> "FeatureValueResponse":
        """Convert one domain feature value into the response schema."""
        return cls(
            name=feature.name,
            values=list(feature.values),
            facet=feature.facet,
            required=feature.required,
            options=list(feature.options),
        )


class MarketplaceAggregateResponse(BaseModel):
    """Expose the normalized latest state for one marketplace."""
    market_id: str
    meta: MarketplaceMetaResponse
    market_cat_id: str = ""
    market_cat_name: str = ""
    fields: dict[str, Any] = Field(default_factory=dict)
    current_features: dict[str, FeatureValueResponse] = Field(default_factory=dict)
    allowed_features: dict[str, FeatureValueResponse] = Field(default_factory=dict)
    extinfo: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_domain(cls, marketplace: MarketplaceSnapshot) -> "MarketplaceAggregateResponse":
        """Convert one domain marketplace snapshot into the public aggregate schema."""
        return cls(
            market_id=marketplace.market_id,
            meta=MarketplaceMetaResponse.from_domain(marketplace.meta),
            market_cat_id=marketplace.market_cat_id,
            market_cat_name=marketplace.market_cat_name,
            fields=dict(marketplace.fields),
            current_features={
                feature_name: FeatureValueResponse.from_domain(feature)
                for feature_name, feature in marketplace.current_features.items()
            },
            allowed_features={
                feature_name: FeatureValueResponse.from_domain(feature)
                for feature_name, feature in marketplace.allowed_features.items()
            },
            extinfo=dict(marketplace.extinfo),
        )


class ProductIdentityResponse(BaseModel):
    """Expose the stable local product identity."""
    id: int
    article: str
    pid: str
    external_product_id: str
    offer_id: str
    latest_snapshot_id: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @classmethod
    def from_domain(cls, identity: ProductIdentity) -> "ProductIdentityResponse":
        """Convert one domain product identity into the response schema."""
        return cls(
            id=identity.id,
            article=identity.article,
            pid=identity.pid,
            external_product_id=identity.external_product_id,
            offer_id=identity.offer_id,
            latest_snapshot_id=identity.latest_snapshot_id,
            created_at=identity.created_at,
            updated_at=identity.updated_at,
        )


class ProductSnapshotAggregateResponse(BaseModel):
    """Expose metadata and normalized top-level fields for the latest snapshot."""
    id: int
    article: str
    pid: str
    product_id: str
    offer_id: str
    task_id: int | None = None
    basic_fields: dict[str, Any] = Field(default_factory=dict)
    flags: dict[str, bool] = Field(default_factory=dict)
    captured_at: datetime | None = None
    updated_at: datetime | None = None

    @classmethod
    def from_domain(cls, snapshot: PersistedProductSnapshot) -> "ProductSnapshotAggregateResponse":
        """Convert one persisted snapshot view into the public response schema."""
        return cls(
            id=snapshot.id,
            article=snapshot.article,
            pid=snapshot.pid,
            product_id=snapshot.product_id,
            offer_id=snapshot.offer_id,
            task_id=snapshot.task_id,
            basic_fields=dict(snapshot.basic_fields),
            flags=dict(snapshot.flags),
            captured_at=snapshot.captured_at,
            updated_at=snapshot.updated_at,
        )


class ProductPatchStatusResponse(BaseModel):
    """Expose the latest persisted draft/save status for a product."""
    patch_id: int
    status: str
    base_snapshot_id: int | None = None
    task_id: int | None = None
    save_url: str = ""
    validation_warnings: list[str] = Field(default_factory=list)
    validation_errors: list[str] = Field(default_factory=list)
    diff_summary: dict[str, Any] = Field(default_factory=dict)
    approved_at: datetime | None = None
    approved_by: str = ""
    save_result: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @classmethod
    def from_domain(cls, status: ProductPatchStatus) -> "ProductPatchStatusResponse":
        """Convert one patch status view into the response schema."""
        return cls(
            patch_id=status.patch_id,
            status=status.status,
            base_snapshot_id=status.base_snapshot_id,
            task_id=status.task_id,
            save_url=status.save_url,
            validation_warnings=list(status.validation_warnings),
            validation_errors=list(status.validation_errors),
            diff_summary=dict(status.diff_summary),
            approved_at=status.approved_at,
            approved_by=status.approved_by,
            save_result=dict(status.save_result),
            created_at=status.created_at,
            updated_at=status.updated_at,
        )


class ProductWorkflowStatusResponse(BaseModel):
    """Expose the latest draft/save lifecycle info in a stable shape."""
    draft: ProductPatchStatusResponse | None = None
    save: ProductPatchStatusResponse | None = None

    @classmethod
    def from_domain(cls, workflow: ProductWorkflowStatus) -> "ProductWorkflowStatusResponse":
        """Convert one domain workflow status bundle into the response schema."""
        return cls(
            draft=ProductPatchStatusResponse.from_domain(workflow.draft) if workflow.draft else None,
            save=ProductPatchStatusResponse.from_domain(workflow.save) if workflow.save else None,
        )


class ProductAggregateResponse(BaseModel):
    """Expose the persisted product aggregate consumed by the frontend and services."""
    identity: ProductIdentityResponse
    latest_snapshot: ProductSnapshotAggregateResponse | None = None
    marketplaces: dict[str, MarketplaceAggregateResponse] = Field(default_factory=dict)
    workflow: ProductWorkflowStatusResponse = Field(default_factory=ProductWorkflowStatusResponse)

    @classmethod
    def from_domain(cls, aggregate: ProductAggregate) -> "ProductAggregateResponse":
        """Convert one domain aggregate into the public API response schema."""
        return cls(
            identity=ProductIdentityResponse.from_domain(aggregate.identity),
            latest_snapshot=(
                ProductSnapshotAggregateResponse.from_domain(aggregate.latest_snapshot)
                if aggregate.latest_snapshot
                else None
            ),
            marketplaces={
                market_id: MarketplaceAggregateResponse.from_domain(marketplace)
                for market_id, marketplace in aggregate.marketplaces.items()
            },
            workflow=ProductWorkflowStatusResponse.from_domain(aggregate.workflow),
        )


class ProductAggregateEnvelope(BaseModel):
    """Wrap the normalized product aggregate returned by the public API."""
    data: ProductAggregateResponse


class FeaturePatchInput(BaseModel):
    """Accept one feature update in a normalized draft request."""
    name: str
    values: list[Any] = Field(default_factory=list)


class MarketplacePatchDraftInput(BaseModel):
    """Accept one marketplace patch in a manual preview request."""
    market_id: str
    fields: dict[str, Any] = Field(default_factory=dict)
    feature_values: list[FeaturePatchInput] = Field(default_factory=list)


class ProductPatchDraftInput(BaseModel):
    """Accept a normalized draft payload that will be validated before preview/save."""
    product_id: str
    offer_id: str | None = None
    basic_fields: dict[str, Any] = Field(default_factory=dict)
    flags: dict[str, Any] = Field(default_factory=dict)
    marketplace_patches: list[MarketplacePatchDraftInput] = Field(default_factory=list)


class PreviewPatchRequest(BaseModel):
    """Describe the input payload for previewing an AI-generated or manual normalized draft."""
    article: str | None = None
    product_id: int | None = None
    instructions: str | None = None
    draft: ProductPatchDraftInput | None = None

    @model_validator(mode="after")
    def validate_identity_selector(self) -> "PreviewPatchRequest":
        """Require exactly one product selector so preview reads one persisted aggregate."""
        if bool(self.article) == bool(self.product_id):
            raise ValueError("Provide exactly one of article or product_id.")
        return self


class MarketplacePatchResponse(BaseModel):
    """Expose one normalized persisted marketplace patch."""
    market_id: str
    market_cat_id: str | None = None
    market_cat_name: str | None = None
    fields: dict[str, Any] = Field(default_factory=dict)
    feature_values: dict[str, FeatureValueResponse] = Field(default_factory=dict)
    extinfo: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_domain(cls, patch: MarketplacePatch) -> "MarketplacePatchResponse":
        """Convert one domain marketplace patch into the response schema."""
        return cls(
            market_id=patch.market_id,
            market_cat_id=patch.market_cat_id,
            market_cat_name=patch.market_cat_name,
            fields=dict(patch.fields),
            feature_values={
                feature_name: FeatureValueResponse.from_domain(feature_value)
                for feature_name, feature_value in patch.feature_values.items()
            },
            extinfo=dict(patch.extinfo),
        )


class ProductPatchResponse(BaseModel):
    """Expose one normalized persisted product patch."""
    product_id: str
    offer_id: str = ""
    basic_fields: dict[str, Any] = Field(default_factory=dict)
    flags: dict[str, Any] = Field(default_factory=dict)
    marketplace_patches: dict[str, MarketplacePatchResponse] = Field(default_factory=dict)

    @classmethod
    def from_domain(cls, patch: ProductPatch) -> "ProductPatchResponse":
        """Convert one domain product patch into the response schema."""
        return cls(
            product_id=patch.product_id,
            offer_id=patch.offer_id,
            basic_fields=dict(patch.basic_fields),
            flags=dict(patch.flags),
            marketplace_patches={
                market_id: MarketplacePatchResponse.from_domain(marketplace_patch)
                for market_id, marketplace_patch in patch.marketplace_patches.items()
            },
        )


class PersistedProductPatchResponse(BaseModel):
    """Expose the persisted draft/patch lifecycle state returned by preview APIs."""
    patch_id: int
    product_record_id: int
    article: str
    pid: str
    status: str
    base_snapshot_id: int | None = None
    task_id: int | None = None
    save_url: str = ""
    validation_warnings: list[str] = Field(default_factory=list)
    validation_errors: list[str] = Field(default_factory=list)
    diff_summary: dict[str, Any] = Field(default_factory=dict)
    approved_at: datetime | None = None
    approved_by: str = ""
    save_result: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None
    patch: ProductPatchResponse

    @classmethod
    def from_domain(cls, persisted_patch: PersistedProductPatch) -> "PersistedProductPatchResponse":
        """Convert one persisted domain patch into the response schema."""
        return cls(
            patch_id=persisted_patch.patch_id,
            product_record_id=persisted_patch.product_record_id,
            article=persisted_patch.article,
            pid=persisted_patch.pid,
            status=persisted_patch.status,
            base_snapshot_id=persisted_patch.base_snapshot_id,
            task_id=persisted_patch.task_id,
            save_url=persisted_patch.save_url,
            validation_warnings=list(persisted_patch.validation_warnings),
            validation_errors=list(persisted_patch.validation_errors),
            diff_summary=dict(persisted_patch.diff_summary),
            approved_at=persisted_patch.approved_at,
            approved_by=persisted_patch.approved_by,
            save_result=dict(persisted_patch.save_result),
            created_at=persisted_patch.created_at,
            updated_at=persisted_patch.updated_at,
            patch=ProductPatchResponse.from_domain(persisted_patch.patch),
        )


class PersistedProductPatchEnvelope(BaseModel):
    """Wrap one persisted patch/draft response returned by preview APIs."""
    data: PersistedProductPatchResponse
