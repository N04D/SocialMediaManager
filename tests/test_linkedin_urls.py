from __future__ import annotations

import unittest

from channels.linkedin.worker.urls import LinkedInUrlError, extract_linkedin_external_id, normalize_linkedin_post_url


class LinkedInUrlValidationTests(unittest.TestCase):
    def test_valid_linkedin_post_url_is_normalized(self) -> None:
        raw = 'http://www.linkedin.com/feed/update/urn:li:activity-12345/?tracking=foo#bar'
        self.assertEqual(normalize_linkedin_post_url(raw), 'https://www.linkedin.com/feed/update/urn:li:activity-12345')

    def test_non_linkedin_url_is_rejected(self) -> None:
        with self.assertRaises(LinkedInUrlError):
            normalize_linkedin_post_url('https://example.com/feed/update/urn:li:activity-12345')

    def test_lookalike_hostname_is_rejected(self) -> None:
        with self.assertRaises(LinkedInUrlError):
            normalize_linkedin_post_url('https://linkedin.com.evil.example/feed/update/urn:li:activity-12345')

    def test_unsupported_linkedin_path_is_rejected(self) -> None:
        with self.assertRaises(LinkedInUrlError):
            normalize_linkedin_post_url('https://www.linkedin.com/in/some-profile/')

    def test_external_id_extraction_is_deterministic(self) -> None:
        url = 'https://www.linkedin.com/feed/update/urn:li:activity-987654321/'
        self.assertEqual(extract_linkedin_external_id(url), 'activity-987654321')
