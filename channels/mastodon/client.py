from __future__ import annotations

from typing import Any

from .errors import MastodonResponseValidationError


class MastodonApiClient:
    def __init__(self, *, origin: str, transport, access_token: str = ""):
        self.origin = origin
        self.transport = transport
        self.access_token = access_token

    def create_app(
        self, *, client_name: str, redirect_uris: str, scopes: list[str], website: str = ""
    ) -> dict[str, Any]:
        payload, _meta = self.transport.post_form(
            self.origin,
            "/api/v1/apps",
            {
                "client_name": client_name,
                "redirect_uris": redirect_uris,
                "scopes": " ".join(sorted(scopes)),
                "website": website,
            },
        )
        return _object(payload, "mastodon.app_response")

    def exchange_token(self, data: dict[str, Any]) -> dict[str, Any]:
        payload, _meta = self.transport.post_form(self.origin, "/oauth/token", data)
        return _object(payload, "mastodon.token_response")

    def revoke_token(self, *, client_id: str, client_secret: str, token: str) -> bool:
        self.transport.post_form(
            self.origin,
            "/oauth/revoke",
            {"client_id": client_id, "client_secret": client_secret, "token": token},
        )
        return True

    def verify_credentials(self) -> dict[str, Any]:
        payload, _meta = self.transport.get_json(
            self.origin, "/api/v1/accounts/verify_credentials", access_token=self.access_token
        )
        account = _object(payload, "mastodon.verify_credentials")
        if not str(account.get("id") or ""):
            raise MastodonResponseValidationError(
                "mastodon.account_missing_id", "Account verification response missed an ID."
            )
        return account

    def upload_media(self, *, data: bytes, filename: str, mime_type: str, description: str = "") -> dict[str, Any]:
        payload, _meta = self.transport.post_multipart(
            self.origin,
            "/api/v2/media",
            fields={"description": description} if description else {},
            files={"file": (filename, data, mime_type)},
            access_token=self.access_token,
        )
        return _object(payload, "mastodon.media_response")

    def get_media(self, media_id: str) -> dict[str, Any]:
        payload, _meta = self.transport.get_json(
            self.origin, f"/api/v1/media/{media_id}", access_token=self.access_token
        )
        return _object(payload, "mastodon.media_response")

    def delete_media(self, media_id: str) -> dict[str, Any]:
        payload, _meta = self.transport.delete(self.origin, f"/api/v1/media/{media_id}", access_token=self.access_token)
        return _object(payload, "mastodon.media_delete")

    def create_status(
        self,
        *,
        status: str,
        media_ids: list[str],
        visibility: str,
        sensitive: bool = False,
        spoiler_text: str = "",
        language: str = "",
        idempotency_key: str = "",
    ) -> dict[str, Any]:
        data: dict[str, Any] = {
            "status": status,
            "visibility": visibility,
            "sensitive": "true" if sensitive else "false",
        }
        for index, media_id in enumerate(media_ids):
            data[f"media_ids[{index}]"] = media_id
        if spoiler_text:
            data["spoiler_text"] = spoiler_text
        if language:
            data["language"] = language
        payload, _meta = self.transport.post_form(
            self.origin,
            "/api/v1/statuses",
            data,
            access_token=self.access_token,
            headers={"Idempotency-Key": idempotency_key} if idempotency_key else {},
        )
        return _object(payload, "mastodon.status_response")

    def get_status(self, status_id: str) -> dict[str, Any]:
        payload, _meta = self.transport.get_json(
            self.origin, f"/api/v1/statuses/{status_id}", access_token=self.access_token
        )
        return _object(payload, "mastodon.status_response")


def _object(payload: Any, code: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise MastodonResponseValidationError(code, "Mastodon response was not an object.")
    return payload
