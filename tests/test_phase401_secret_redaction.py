import unittest

from channels.youtube.auth import redact_tokens


class Phase401SecretRedactionTests(unittest.TestCase):
    def test_token_and_authorization_values_are_redacted(self):
        safe = redact_tokens(
            {"access_token": "ya29.secret", "refresh_token": "1//secret", "Authorization": "Bearer secret"}
        )
        self.assertEqual(safe["access_token"], "[REDACTED]")
        self.assertEqual(safe["refresh_token"], "[REDACTED]")
        self.assertEqual(safe["Authorization"], "[REDACTED]")
