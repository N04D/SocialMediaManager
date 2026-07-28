from __future__ import annotations

import tempfile
import threading
import unittest
from pathlib import Path

from integrations.website_analytics.fake_provider import FakeWebsiteAnalyticsHttpFacade
from integrations.website_analytics.fixtures import plausible_success_response
from integrations.website_analytics.scenarios import event_mappings_payload, plausible_account_payload
from src.core.website_analytics.provider import InMemorySafeHttpFacade
from src.core.website_analytics.service import WebsiteAnalyticsService
from src.core.website_analytics.worker import WebsiteAnalyticsSyncWorker
from src.providers.analytics.plausible.queries import PLAUSIBLE_ENDPOINT


class WebsiteAnalyticsSyncPhase25Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "owned.sqlite3"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def service(self, facade=None) -> WebsiteAnalyticsService:
        return WebsiteAnalyticsService(database_path=self.db, http_facade=facade or FakeWebsiteAnalyticsHttpFacade())

    def test_syncstate_cursor_watermark_duplicate_and_correction(self) -> None:
        service = self.service()
        service.create_account(plausible_account_payload())
        service.put_mappings("analytics-account-plausible", event_mappings_payload())
        first = service.sync("analytics-account-plausible")
        second = service.sync("analytics-account-plausible")
        self.assertEqual(first["status"], "completed")
        self.assertTrue(all(item["status"] == "duplicate" for item in second["observations"]))
        changed = self.service(InMemorySafeHttpFacade({PLAUSIBLE_ENDPOINT: plausible_success_response(pageviews=8)}))
        correction = changed.sync("analytics-account-plausible")
        self.assertGreaterEqual(correction["corrections"], 1)
        states = changed.sync_status("analytics-account-plausible")["sync_states"]
        self.assertEqual(states[0]["status"], "completed")
        self.assertTrue(states[0]["high_watermark"])

    def test_two_workers_claim_without_duplicate_observations(self) -> None:
        service = self.service()
        service.create_account(plausible_account_payload())
        workers = [WebsiteAnalyticsSyncWorker(self.service(), worker_id=f"sync-worker-{index}") for index in range(2)]
        threads = [threading.Thread(target=worker.run_once) for worker in workers]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=5)
        stats = [worker.stats for worker in workers]
        self.assertEqual(sum(item.claimed for item in stats), 1)
        self.assertEqual(sum(item.completed for item in stats), 1)
        duplicate = self.service().sync("analytics-account-plausible")
        self.assertTrue(all(item["status"] == "duplicate" for item in duplicate["observations"]))


if __name__ == "__main__":
    unittest.main()
