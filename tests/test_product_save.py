from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.application.services.product_aggregate import GetProductAggregateService
from app.application.services.product_preview import PreviewProductPatchService
from app.application.services.product_save import ApplyProductPatchService, SaveProductPatchService
from app.domain.models import FeatureValue, MarketplaceMeta, MarketplaceSnapshot, ProductSnapshot
from app.infrastructure.db import (
    PatchRepository,
    ProductAggregateRepository,
    ProductRepository,
    SnapshotRepository,
    TaskRepository,
    configure_database,
    upgrade_database,
)
from app.infrastructure.settings import get_settings


class FakeSaveSession:
    """Capture outgoing save payloads without talking to a real FOKS environment."""

    saved_requests: list[dict[str, object]] = []

    def __init__(self, base_url: str, username: str, password: str) -> None:
        """Store constructor inputs to mimic the real session interface."""
        self.base_url = base_url
        self.username = username
        self.password = password

    def build_json_headers(self, csrf_token: str, referer_path: str = "/c/products") -> dict[str, str]:
        """Return request headers in the same shape as the real session helper."""
        return {
            "X-CSRF-TOKEN": csrf_token,
            "Referer": f"{self.base_url}{referer_path}",
        }

    def post_json(self, path: str, json_body: dict[str, object], csrf_token: str) -> dict[str, object]:
        """Record the outgoing save request and return a fake success response."""
        request_payload = {
            "path": path,
            "json_body": json_body,
            "csrf_token": csrf_token,
        }
        self.saved_requests.append(request_payload)
        return {"ok": True, "saved": True}


class FakeRefreshService:
    """Persist a post-save snapshot and return the refreshed aggregate for verification tests."""

    def __init__(
        self,
        *,
        snapshot_repository: SnapshotRepository,
        aggregate_repository: ProductAggregateRepository,
        refreshed_snapshot: ProductSnapshot,
    ) -> None:
        """Store the repositories and snapshot shape used for refresh simulation."""
        self._snapshot_repository = snapshot_repository
        self._aggregate_repository = aggregate_repository
        self._refreshed_snapshot = refreshed_snapshot

    def refresh(
        self,
        *,
        base_url: str,
        username: str,
        password: str,
        article: str,
        mids: list[str] | None = None,
    ):
        """Persist the prepared post-save snapshot and return the latest aggregate."""
        self._snapshot_repository.save_snapshot(self._refreshed_snapshot)
        aggregate = self._aggregate_repository.get_latest_aggregate_by_article(article)
        assert aggregate is not None
        return aggregate


class FlakyRefreshService:
    """Fail once after the save POST, then allow a retry to complete verification."""

    def __init__(
        self,
        *,
        snapshot_repository: SnapshotRepository,
        aggregate_repository: ProductAggregateRepository,
        refreshed_snapshot: ProductSnapshot,
        failures_before_success: int = 1,
    ) -> None:
        """Store the repositories together with a configurable number of transient failures."""
        self._snapshot_repository = snapshot_repository
        self._aggregate_repository = aggregate_repository
        self._refreshed_snapshot = refreshed_snapshot
        self._failures_before_success = failures_before_success

    def refresh(
        self,
        *,
        base_url: str,
        username: str,
        password: str,
        article: str,
        mids: list[str] | None = None,
    ):
        """Raise a transient error before eventually persisting the refreshed snapshot."""
        if self._failures_before_success > 0:
            self._failures_before_success -= 1
            raise RuntimeError("Transient refresh failure after save")

        self._snapshot_repository.save_snapshot(self._refreshed_snapshot)
        aggregate = self._aggregate_repository.get_latest_aggregate_by_article(article)
        assert aggregate is not None
        return aggregate


class ProductSaveTests(unittest.TestCase):
    """Cover patch application, save execution, and safe-save verification."""

    def setUp(self) -> None:
        """Seed an isolated database with one persisted aggregate and draft patch."""
        self._temp_dir = tempfile.TemporaryDirectory()
        self._database_url = f"sqlite:///{Path(self._temp_dir.name) / 'test.db'}"
        configure_database(url=self._database_url, force=True)
        upgrade_database(url=self._database_url)

        self._product_repository = ProductRepository()
        self._snapshot_repository = SnapshotRepository(product_repository=self._product_repository)
        self._patch_repository = PatchRepository()
        self._task_repository = TaskRepository()
        self._aggregate_repository = ProductAggregateRepository(
            product_repository=self._product_repository,
            snapshot_repository=self._snapshot_repository,
        )
        self._aggregate_service = GetProductAggregateService(
            aggregate_repository=self._aggregate_repository,
        )

        _, self._base_snapshot = self._snapshot_repository.save_snapshot(
            ProductSnapshot(
                article="ART-777",
                pid="bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
                product_id="prod-1",
                offer_id="offer-1",
                csrf_save_token="csrf-123",
                basic_fields={"name": "Demo product"},
                marketplaces={
                    "prom": MarketplaceSnapshot(
                        market_id="prom",
                        meta=MarketplaceMeta(marketid="prom", catid="cat-prom"),
                        market_cat_id="cat-prom",
                        market_cat_name="Prom category",
                        fields={
                            "nameExt": "Old title",
                            "descriptionExtRu": "<p>Old description</p>",
                        },
                        current_features={
                            "Color": FeatureValue(name="Color", values=["Black"]),
                        },
                        allowed_features={
                            "Color": FeatureValue(name="Color", options=["Black", "White"], required=True),
                        },
                    ),
                    "rozetka": MarketplaceSnapshot(
                        market_id="rozetka",
                        meta=MarketplaceMeta(marketid="rozetka", catid="cat-roz"),
                        market_cat_id="cat-roz",
                        market_cat_name="Rozetka category",
                        fields={"nameExtUa": "Old title ua"},
                        current_features={},
                        allowed_features={},
                    ),
                },
            )
        )

    def tearDown(self) -> None:
        """Restore the default database configuration after each test."""
        settings = get_settings()
        configure_database(
            url=settings.sqlalchemy_database_url,
            echo=settings.db_echo,
            force=True,
        )
        self._temp_dir.cleanup()
        FakeSaveSession.saved_requests.clear()

    def test_save_service_applies_patch_and_marks_it_saved(self) -> None:
        """Saving a persisted draft should approve it, post the payload, and verify the refresh result."""
        preview_service = PreviewProductPatchService(
            aggregate_service=self._aggregate_service,
            patch_repository=self._patch_repository,
            task_repository=self._task_repository,
            patch_generator=None,
        )
        persisted_patch = preview_service.preview(
            article="ART-777",
            created_by="draft.user",
            raw_draft={
                "product_id": "prod-1",
                "offer_id": "offer-1",
                "marketplace_patches": [
                    {
                        "market_id": "prom",
                        "fields": {"nameExt": "Saved title"},
                        "feature_values": [{"name": "Color", "values": ["White"]}],
                    }
                ],
            },
        )

        refreshed_snapshot = ApplyProductPatchService().apply(
            snapshot=self._base_snapshot,
            patch=persisted_patch.patch,
        )
        save_service = SaveProductPatchService(
            aggregate_service=self._aggregate_service,
            refresh_service=FakeRefreshService(
                snapshot_repository=self._snapshot_repository,
                aggregate_repository=self._aggregate_repository,
                refreshed_snapshot=refreshed_snapshot,
            ),
            snapshot_repository=self._snapshot_repository,
            patch_repository=self._patch_repository,
            task_repository=self._task_repository,
            session_factory=FakeSaveSession,
        )

        saved_patch = save_service.save(
            patch_id=persisted_patch.patch_id,
            base_url="https://my.foks.biz",
            username="user",
            password="pass",
            approved_by="qa.user",
        )

        self.assertEqual(saved_patch.status, "saved")
        self.assertEqual(saved_patch.created_by, "draft.user")
        self.assertEqual(saved_patch.approved_by, "qa.user")
        self.assertEqual(saved_patch.save_result["audit"]["created_by"], "draft.user")
        self.assertEqual(saved_patch.save_result["audit"]["approved_by"], "qa.user")
        self.assertEqual(saved_patch.save_result["audit"]["base_snapshot_id"], persisted_patch.base_snapshot_id)
        self.assertEqual(saved_patch.save_result["audit"]["diff_summary"]["change_count"], 2)
        self.assertEqual(saved_patch.save_result["verification"]["status"], "ok")
        self.assertEqual(saved_patch.save_result["verification"]["mismatch_count"], 0)
        self.assertEqual(FakeSaveSession.saved_requests[0]["path"], "/c/products/save")
        self.assertEqual(
            FakeSaveSession.saved_requests[0]["json_body"]["nameExt"]["prom"],
            "Saved title",
        )
        self.assertEqual(
            FakeSaveSession.saved_requests[0]["json_body"]["featureValues"]["prom"],
            ["White"],
        )

    def test_save_service_rejects_stale_patch(self) -> None:
        """Saving should fail when a newer persisted snapshot already exists for the same product."""
        preview_service = PreviewProductPatchService(
            aggregate_service=self._aggregate_service,
            patch_repository=self._patch_repository,
            task_repository=self._task_repository,
            patch_generator=None,
        )
        persisted_patch = preview_service.preview(
            article="ART-777",
            raw_draft={
                "product_id": "prod-1",
                "offer_id": "offer-1",
                "marketplace_patches": [
                    {
                        "market_id": "prom",
                        "fields": {"nameExt": "Saved title"},
                    }
                ],
            },
        )
        self._snapshot_repository.save_snapshot(
            ProductSnapshot(
                article="ART-777",
                pid="bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
                product_id="prod-1",
                offer_id="offer-1",
                csrf_save_token="csrf-456",
                basic_fields={"name": "Demo product"},
                marketplaces=self._base_snapshot.marketplaces,
            )
        )
        save_service = SaveProductPatchService(
            aggregate_service=self._aggregate_service,
            refresh_service=FakeRefreshService(
                snapshot_repository=self._snapshot_repository,
                aggregate_repository=self._aggregate_repository,
                refreshed_snapshot=self._base_snapshot,
            ),
            snapshot_repository=self._snapshot_repository,
            patch_repository=self._patch_repository,
            task_repository=self._task_repository,
            session_factory=FakeSaveSession,
        )

        with self.assertRaisesRegex(ValueError, "stale snapshot"):
            save_service.save(
                patch_id=persisted_patch.patch_id,
                base_url="https://my.foks.biz",
                username="user",
                password="pass",
            )

    def test_save_service_marks_verification_mismatch_as_retryable(self) -> None:
        """A post-save verification mismatch should remain retryable instead of becoming terminal."""
        preview_service = PreviewProductPatchService(
            aggregate_service=self._aggregate_service,
            patch_repository=self._patch_repository,
            task_repository=self._task_repository,
            patch_generator=None,
        )
        persisted_patch = preview_service.preview(
            article="ART-777",
            created_by="draft.user",
            raw_draft={
                "product_id": "prod-1",
                "offer_id": "offer-1",
                "marketplace_patches": [
                    {
                        "market_id": "prom",
                        "fields": {"nameExt": "Saved title"},
                    }
                ],
            },
        )

        save_service = SaveProductPatchService(
            aggregate_service=self._aggregate_service,
            refresh_service=FakeRefreshService(
                snapshot_repository=self._snapshot_repository,
                aggregate_repository=self._aggregate_repository,
                refreshed_snapshot=self._base_snapshot,
            ),
            snapshot_repository=self._snapshot_repository,
            patch_repository=self._patch_repository,
            task_repository=self._task_repository,
            session_factory=FakeSaveSession,
        )

        verification_failed_patch = save_service.save(
            patch_id=persisted_patch.patch_id,
            base_url="https://my.foks.biz",
            username="user",
            password="pass",
            approved_by="qa.user",
        )

        self.assertEqual(verification_failed_patch.status, "verification_failed")
        self.assertEqual(verification_failed_patch.approved_by, "qa.user")
        self.assertEqual(
            verification_failed_patch.save_result["verification"]["status"],
            "mismatch",
        )

        refreshed_snapshot = ApplyProductPatchService().apply(
            snapshot=self._base_snapshot,
            patch=persisted_patch.patch,
        )
        retry_service = SaveProductPatchService(
            aggregate_service=self._aggregate_service,
            refresh_service=FakeRefreshService(
                snapshot_repository=self._snapshot_repository,
                aggregate_repository=self._aggregate_repository,
                refreshed_snapshot=refreshed_snapshot,
            ),
            snapshot_repository=self._snapshot_repository,
            patch_repository=self._patch_repository,
            task_repository=self._task_repository,
            session_factory=FakeSaveSession,
        )

        retried_patch = retry_service.save(
            patch_id=persisted_patch.patch_id,
            base_url="https://my.foks.biz",
            username="user",
            password="pass",
        )

        self.assertEqual(retried_patch.status, "saved")
        self.assertEqual(retried_patch.approved_by, "qa.user")

    def test_save_service_preserves_approval_metadata_on_retry_after_refresh_error(self) -> None:
        """Retrying after a post-save refresh failure should keep the original approval audit."""
        preview_service = PreviewProductPatchService(
            aggregate_service=self._aggregate_service,
            patch_repository=self._patch_repository,
            task_repository=self._task_repository,
            patch_generator=None,
        )
        persisted_patch = preview_service.preview(
            article="ART-777",
            created_by="draft.user",
            raw_draft={
                "product_id": "prod-1",
                "offer_id": "offer-1",
                "marketplace_patches": [
                    {
                        "market_id": "prom",
                        "fields": {"nameExt": "Saved title"},
                    }
                ],
            },
        )

        refreshed_snapshot = ApplyProductPatchService().apply(
            snapshot=self._base_snapshot,
            patch=persisted_patch.patch,
        )
        save_service = SaveProductPatchService(
            aggregate_service=self._aggregate_service,
            refresh_service=FlakyRefreshService(
                snapshot_repository=self._snapshot_repository,
                aggregate_repository=self._aggregate_repository,
                refreshed_snapshot=refreshed_snapshot,
            ),
            snapshot_repository=self._snapshot_repository,
            patch_repository=self._patch_repository,
            task_repository=self._task_repository,
            session_factory=FakeSaveSession,
        )

        with self.assertRaisesRegex(RuntimeError, "Transient refresh failure after save"):
            save_service.save(
                patch_id=persisted_patch.patch_id,
                base_url="https://my.foks.biz",
                username="user",
                password="pass",
                approved_by="qa.user",
            )

        failed_patch = self._patch_repository.get_patch_by_id(persisted_patch.patch_id)
        assert failed_patch is not None
        first_approved_at = failed_patch.approved_at
        self.assertEqual(failed_patch.status, "verification_failed")
        self.assertEqual(failed_patch.approved_by, "qa.user")
        self.assertEqual(failed_patch.save_result["verification"]["status"], "error")
        self.assertEqual(failed_patch.save_result["response"]["ok"], True)

        retried_patch = save_service.save(
            patch_id=persisted_patch.patch_id,
            base_url="https://my.foks.biz",
            username="user",
            password="pass",
        )

        self.assertEqual(retried_patch.status, "saved")
        self.assertEqual(retried_patch.approved_by, "qa.user")
        self.assertEqual(retried_patch.approved_at, first_approved_at)


if __name__ == "__main__":
    unittest.main()
