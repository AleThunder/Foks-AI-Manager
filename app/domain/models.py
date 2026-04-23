from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(slots=True)
class MarketplaceMeta:
    """Store marketplace-specific metadata extracted from the modal HTML."""
    marketid: str
    catid: str = ""
    custcatid: str = ""


@dataclass(slots=True)
class FeatureValue:
    """Represent one marketplace feature together with current values and allowed schema metadata."""
    name: str
    values: list[str] = field(default_factory=list)
    facet: bool = False
    required: bool = False
    options: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class SearchProductCandidate:
    """Represent one candidate product found on the search results page."""
    pid: str
    title: str = ""
    snippet: str = ""
    href: str = ""
    position: int = 0


@dataclass(slots=True)
class ModalParseResult:
    """Hold the normalized result of parsing a product modal form."""
    product_id: str
    offer_id: str
    csrf_save_token: str
    basic_fields: dict[str, Any] = field(default_factory=dict)
    flags: dict[str, bool] = field(default_factory=dict)
    marketplace_fields: dict[str, dict[str, Any]] = field(default_factory=dict)
    market_cat_ids: dict[str, str] = field(default_factory=dict)
    market_cat_names: dict[str, str] = field(default_factory=dict)
    marketplaces_meta: dict[str, MarketplaceMeta] = field(default_factory=dict)
    extinfo_by_market: dict[str, dict[str, Any]] = field(default_factory=dict)

    def to_form_fields(self) -> dict[str, Any]:
        """Flatten the normalized modal structure back into the form-like shape used by payload building."""
        fields = dict(self.basic_fields)
        fields.update(self.flags)

        for market_id, market_fields in self.marketplace_fields.items():
            for field_name, value in market_fields.items():
                fields[f"{field_name}['{market_id}']"] = value

        return fields

    def get_marketplace_values(self, field_name: str) -> dict[str, Any]:
        """Return one marketplace field across all marketplaces as a simple mapping."""
        return {
            market_id: market_fields[field_name]
            for market_id, market_fields in self.marketplace_fields.items()
            if field_name in market_fields
        }


@dataclass(slots=True)
class MarketplaceSnapshot:
    """Store the full marketplace-specific state of a product as it exists in FOKS."""
    market_id: str
    meta: MarketplaceMeta
    market_cat_id: str = ""
    market_cat_name: str = ""
    fields: dict[str, Any] = field(default_factory=dict)
    current_features: dict[str, FeatureValue] = field(default_factory=dict)
    allowed_features: dict[str, FeatureValue] = field(default_factory=dict)
    raw_product_features: Any | None = None
    raw_category_features: Any | None = None
    extinfo: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ProductSnapshot:
    """Represent the full product snapshot returned by the read flow."""
    article: str
    pid: str
    product_id: str
    offer_id: str
    csrf_save_token: str
    basic_fields: dict[str, Any] = field(default_factory=dict)
    flags: dict[str, bool] = field(default_factory=dict)
    marketplaces: dict[str, MarketplaceSnapshot] = field(default_factory=dict)

    def to_modal_parse_result(self) -> ModalParseResult:
        """Convert the snapshot back into the normalized modal view used by payload building."""
        marketplace_fields = {
            market_id: dict(snapshot.fields)
            for market_id, snapshot in self.marketplaces.items()
        }
        market_cat_ids = {
            market_id: snapshot.market_cat_id
            for market_id, snapshot in self.marketplaces.items()
            if snapshot.market_cat_id
        }
        market_cat_names = {
            market_id: snapshot.market_cat_name
            for market_id, snapshot in self.marketplaces.items()
            if snapshot.market_cat_name
        }
        marketplaces_meta = {
            market_id: snapshot.meta
            for market_id, snapshot in self.marketplaces.items()
        }
        extinfo_by_market = {
            market_id: snapshot.extinfo
            for market_id, snapshot in self.marketplaces.items()
            if snapshot.extinfo
        }

        return ModalParseResult(
            product_id=self.product_id,
            offer_id=self.offer_id,
            csrf_save_token=self.csrf_save_token,
            basic_fields=dict(self.basic_fields),
            flags=dict(self.flags),
            marketplace_fields=marketplace_fields,
            market_cat_ids=market_cat_ids,
            market_cat_names=market_cat_names,
            marketplaces_meta=marketplaces_meta,
            extinfo_by_market=extinfo_by_market,
        )


@dataclass(slots=True)
class MarketplacePatch:
    """Describe marketplace-scoped changes that should be applied to a product."""
    market_id: str
    market_cat_id: str | None = None
    market_cat_name: str | None = None
    fields: dict[str, Any] = field(default_factory=dict)
    feature_values: dict[str, FeatureValue] = field(default_factory=dict)
    extinfo: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ProductPatch:
    """Describe top-level and marketplace-level updates prepared for a product."""
    product_id: str
    offer_id: str = ""
    basic_fields: dict[str, Any] = field(default_factory=dict)
    flags: dict[str, bool] = field(default_factory=dict)
    marketplace_patches: dict[str, MarketplacePatch] = field(default_factory=dict)


@dataclass(slots=True)
class ProductIdentity:
    """Describe the stable persisted identity of a product inside the local database."""
    id: int
    article: str
    pid: str
    external_product_id: str
    offer_id: str
    latest_snapshot_id: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(slots=True)
class PersistedProductSnapshot:
    """Describe the latest persisted snapshot metadata returned by the public API."""
    id: int
    article: str
    pid: str
    product_id: str
    offer_id: str
    task_id: int | None = None
    basic_fields: dict[str, Any] = field(default_factory=dict)
    flags: dict[str, bool] = field(default_factory=dict)
    captured_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(slots=True)
class ProductPatchStatus:
    """Describe the latest persisted patch/draft lifecycle state for a product."""
    patch_id: int
    status: str
    base_snapshot_id: int | None = None
    task_id: int | None = None
    created_by: str = ""
    save_url: str = ""
    validation_warnings: list[str] = field(default_factory=list)
    validation_errors: list[str] = field(default_factory=list)
    diff_summary: dict[str, Any] = field(default_factory=dict)
    approved_at: datetime | None = None
    approved_by: str = ""
    save_result: dict[str, Any] = field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(slots=True)
class ProductWorkflowStatus:
    """Group the latest draft and save statuses exposed by the aggregate read model."""
    draft: ProductPatchStatus | None = None
    save: ProductPatchStatus | None = None


@dataclass(slots=True)
class ProductAggregate:
    """Represent the API-facing aggregate composed from identity, snapshot, and workflow state."""
    identity: ProductIdentity
    latest_snapshot: PersistedProductSnapshot | None = None
    marketplaces: dict[str, MarketplaceSnapshot] = field(default_factory=dict)
    workflow: ProductWorkflowStatus = field(default_factory=ProductWorkflowStatus)


@dataclass(slots=True)
class PersistedProductPatch:
    """Represent one persisted patch record together with lifecycle metadata and normalized content."""
    patch_id: int
    product_record_id: int
    article: str
    pid: str
    status: str
    patch: ProductPatch
    base_snapshot_id: int | None = None
    task_id: int | None = None
    created_by: str = ""
    save_url: str = ""
    headers: dict[str, Any] = field(default_factory=dict)
    payload: dict[str, Any] = field(default_factory=dict)
    validation_warnings: list[str] = field(default_factory=list)
    validation_errors: list[str] = field(default_factory=list)
    diff_summary: dict[str, Any] = field(default_factory=dict)
    approved_at: datetime | None = None
    approved_by: str = ""
    save_result: dict[str, Any] = field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None
