from __future__ import annotations

from tests.phase333_support import Phase333TestCase


class MVPPublicationResultPhase333Tests(Phase333TestCase):
    def test_result_page_shows_checksum_and_evidence_ids(self) -> None:
        repo = self.init_empty_site_repo()
        with self.static_server(repo) as port:
            session_id = self.prepare_publication(repo, port)
            result = self.publish_session(session_id)
            page = self.page(f"/setup/{session_id}/result")

        self.assertIn(result["execution_request_id"], page)
        self.assertIn("Revision checksum", page)
        self.assertIn(result["checksum_bindings"]["revision"], page)
        for evidence_id in result["evidence_ids"]:
            self.assertIn(evidence_id, page)
