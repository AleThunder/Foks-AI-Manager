from __future__ import annotations

from app.application.ports import SnapshotRepositoryPort, TaskRepositoryPort
from app.domain.models import MarketplaceMeta, MarketplaceSnapshot, ProductSnapshot
from app.infrastructure.foks.category_feature_loader import CategoryFeatureLoader
from app.infrastructure.foks.modal_parser import ModalParser
from app.infrastructure.foks.product_feature_loader import ProductFeatureLoader
from app.infrastructure.foks.search_service import ProductSearchService
from app.infrastructure.foks.session import FoksSession
from app.infrastructure.logging import get_logger, get_task_id


class GetProductByArticleService:
    """Read a product from FOKS and return a fully assembled domain snapshot."""

    def __init__(
        self,
        *,
        snapshot_repository: SnapshotRepositoryPort,
        task_repository: TaskRepositoryPort,
        session_factory: type[FoksSession] = FoksSession,
    ) -> None:
        """Store the collaborators required to read and persist one product snapshot."""
        self._session_factory = session_factory
        self._read_logger = get_logger("app.integration.foks.read")
        self._snapshot_repository = snapshot_repository
        self._task_repository = task_repository

    def get_product_by_article(
        self,
        *,
        base_url: str,
        username: str,
        password: str,
        article: str,
        mids: list[str] | None = None,
    ) -> ProductSnapshot:
        """Execute the full read chain: search, pid resolution, modal parsing and feature fetch."""
        task_record_id = self._task_repository.start_task(
            task_id=get_task_id(),
            task_type="read_product",
            article=article,
        )
        self._read_logger.info(
            "product_read_started",
            extra={"event": "product_read_started", "article": article},
        )
        try:
            session = self._session_factory(
                base_url=base_url,
                username=username,
                password=password,
            )

            search_service = ProductSearchService(session=session)
            product_feature_loader = ProductFeatureLoader(session=session)
            category_feature_loader = CategoryFeatureLoader(session=session)
            pid = search_service.find_pid_by_article(article)
            modal_html = session.get_html("/c/products/productModal", params={"pid": pid})
            modal = ModalParser.parse(modal_html)

            use_mids = mids or sorted(
                set(modal.market_cat_ids.keys()) | set(modal.marketplaces_meta.keys())
            )
            marketplaces: dict[str, MarketplaceSnapshot] = {}

            for mid in use_mids:
                meta = modal.marketplaces_meta.get(mid) or MarketplaceMeta(marketid=mid)
                # Category data can come either from explicit form fields or embedded marketplace metadata.
                catid = modal.market_cat_ids.get(mid) or meta.catid
                catname = modal.market_cat_names.get(mid, "")

                try:
                    filled_features_raw, current_features = product_feature_loader.load(
                        product_id=modal.product_id,
                        mid=mid,
                    )
                except Exception:
                    self._read_logger.exception(
                        "product_features_fetch_failed",
                        extra={
                            "event": "product_features_fetch_failed",
                            "article": article,
                            "product_id": modal.product_id,
                            "market_id": mid,
                        },
                    )
                    filled_features_raw = {}
                    current_features = {}

                category_schema_raw = None
                allowed_features = {}
                if catid:
                    # Missing schema should not fail the whole read flow; payload building can continue without it.
                    try:
                        category_schema_raw, allowed_features = category_feature_loader.load(
                            mid=mid,
                            market_category_id=catid,
                        )
                    except Exception:
                        self._read_logger.exception(
                            "category_schema_fetch_failed",
                            extra={
                                "event": "category_schema_fetch_failed",
                                "article": article,
                                "market_id": mid,
                                "market_category_id": catid,
                            },
                        )

                marketplaces[mid] = MarketplaceSnapshot(
                    market_id=mid,
                    meta=meta,
                    market_cat_id=catid,
                    market_cat_name=catname,
                    fields=dict(modal.marketplace_fields.get(mid, {})),
                    current_features=current_features,
                    allowed_features=allowed_features,
                    raw_product_features=filled_features_raw,
                    raw_category_features=category_schema_raw,
                    extinfo=dict(modal.extinfo_by_market.get(mid, {})),
                )

            snapshot = ProductSnapshot(
                article=article,
                pid=pid,
                product_id=modal.product_id,
                offer_id=modal.offer_id,
                csrf_save_token=modal.csrf_save_token,
                basic_fields=dict(modal.basic_fields),
                flags=dict(modal.flags),
                marketplaces=marketplaces,
            )
            product_record_id, persisted_snapshot = self._snapshot_repository.save_snapshot(
                snapshot,
                raw_modal_html=modal_html,
                task_record_id=task_record_id,
            )
            self._task_repository.complete_task(
                task_record_id,
                product_record_id=product_record_id,
                pid=persisted_snapshot.pid,
                details={"marketplace_count": len(persisted_snapshot.marketplaces)},
            )
            self._read_logger.info(
                "product_read_completed",
                extra={
                    "event": "product_read_completed",
                    "article": article,
                    "pid": persisted_snapshot.pid,
                    "marketplace_count": len(persisted_snapshot.marketplaces),
                },
            )
            return persisted_snapshot
        except Exception as exc:
            self._task_repository.fail_task(
                task_record_id,
                error_message=str(exc),
                details={"article": article},
            )
            raise
