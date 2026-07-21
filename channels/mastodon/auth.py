from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

import channel_store

from .client import MastodonApiClient
from .errors import MastodonOAuthExpiredError, MastodonOAuthStateError, MastodonScopeError
from .instance import DEFAULT_SCOPES
from .models import MastodonAccountState, MastodonOAuthFlowState
from .storage import (
    MastodonAccountRepository,
    MastodonAppRepository,
    MastodonOAuthFlowRepository,
    MastodonSecretStore,
    append_audit,
    append_event,
)


class MastodonOAuthService:
    def __init__(
        self,
        *,
        transport,
        account_repository: MastodonAccountRepository,
        app_repository: MastodonAppRepository,
        flow_repository: MastodonOAuthFlowRepository,
        secret_store: MastodonSecretStore,
        application_name: str = "SocialMediaManager",
    ) -> None:
        self.transport = transport
        self.account_repository = account_repository
        self.app_repository = app_repository
        self.flow_repository = flow_repository
        self.secret_store = secret_store
        self.application_name = application_name

    def start_connect(
        self,
        *,
        workspace_id: str,
        channel_account_id: str,
        instance_origin: str,
        redirect_uri: str,
        scopes: list[str] | None = None,
        force_login: bool = False,
    ) -> dict[str, str]:
        scope_set = sorted(scopes or DEFAULT_SCOPES)
        app = self.app_repository.find(
            instance_origin=instance_origin,
            redirect_uri=redirect_uri,
            scopes=scope_set,
            application_name=self.application_name,
        )
        if app is None:
            client = MastodonApiClient(origin=instance_origin, transport=self.transport)
            registered = client.create_app(
                client_name=self.application_name,
                redirect_uris=redirect_uri,
                scopes=scope_set,
                website="",
            )
            client_id_ref, _ = self.secret_store.put(
                str(registered.get("client_id") or ""), purpose="mastodon.client_id"
            )
            client_secret_ref, _ = self.secret_store.put(
                str(registered.get("client_secret") or ""), purpose="mastodon.client_secret"
            )
            from .models import MastodonAppRegistration

            app = MastodonAppRegistration(
                id=f"mastodon_app_{secrets.token_hex(8)}",
                instance_origin=instance_origin,
                redirect_uri=redirect_uri,
                scopes=scope_set,
                application_name=self.application_name,
                client_id_secret_ref=client_id_ref,
                client_secret_ref=client_secret_ref,
                created_at=channel_store.now_iso(),
                last_verified_at=channel_store.now_iso(),
            )
            self.app_repository.save(app)
        state = secrets.token_urlsafe(32)
        verifier = secrets.token_urlsafe(64)
        challenge = pkce_s256(verifier)
        state_ref, _ = self.secret_store.put(state, purpose="mastodon.oauth_state")
        verifier_ref, _ = self.secret_store.put(verifier, purpose="mastodon.pkce_verifier")
        now = datetime.now(UTC)
        flow = MastodonOAuthFlowState(
            id=f"mastodon_oauth_{secrets.token_hex(8)}",
            workspace_id=workspace_id,
            channel_account_id=channel_account_id,
            instance_origin=instance_origin,
            redirect_uri=redirect_uri,
            scope_set=scope_set,
            state_secret_ref=state_ref,
            verifier_secret_ref=verifier_ref,
            challenge=challenge,
            app_registration_id=app.id,
            created_at=now.isoformat(timespec="seconds"),
            expires_at=(now + timedelta(minutes=15)).isoformat(timespec="seconds"),
        )
        self.flow_repository.save(flow)
        params = {
            "response_type": "code",
            "client_id": self.secret_store.get(app.client_id_secret_ref),
            "redirect_uri": redirect_uri,
            "scope": " ".join(scope_set),
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
        if force_login:
            params["force_login"] = "true"
        append_event(
            "channel.mastodon.oauth.started",
            workspace_id=workspace_id,
            account_id=channel_account_id,
            metadata={"instance_origin": instance_origin},
        )
        append_audit("oauth.start", workspace_id=workspace_id, account_id=channel_account_id)
        return {"authorization_url": f"{instance_origin}/oauth/authorize?{urlencode(params)}", "flow_id": flow.id}

    def complete_connect(
        self, *, code: str, state: str, workspace_id: str, channel_account_id: str
    ) -> MastodonAccountState:
        flow = next(
            (
                item
                for item in self.flow_repository.list_all()
                if item.channel_account_id == channel_account_id
                and item.workspace_id == workspace_id
                and not item.consumed_at
            ),
            None,
        )
        if flow is None:
            raise MastodonOAuthStateError("mastodon.oauth.flow_missing", "OAuth flow was not found.")
        expected_state = self.secret_store.get(flow.state_secret_ref)
        if not hmac.compare_digest(expected_state, state):
            raise MastodonOAuthStateError("mastodon.oauth.state_mismatch", "OAuth state did not match.")
        expires_at = datetime.fromisoformat(flow.expires_at).astimezone(UTC)
        if expires_at <= datetime.now(UTC):
            raise MastodonOAuthExpiredError("mastodon.oauth.expired", "OAuth flow expired.")
        app = self.app_repository.get(flow.app_registration_id)
        if app is None:
            raise MastodonOAuthStateError("mastodon.oauth.app_missing", "OAuth app registration was not found.")
        client_id = self.secret_store.get(app.client_id_secret_ref)
        client_secret = self.secret_store.get(app.client_secret_ref)
        verifier = self.secret_store.get(flow.verifier_secret_ref)
        client = MastodonApiClient(origin=flow.instance_origin, transport=self.transport)
        token = client.exchange_token(
            {
                "grant_type": "authorization_code",
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": flow.redirect_uri,
                "code": code,
                "scope": " ".join(flow.scope_set),
                "code_verifier": verifier,
            }
        )
        access_token = str(token.get("access_token") or "")
        returned_scope = sorted(str(token.get("scope") or " ".join(flow.scope_set)).split())
        required = set(flow.scope_set)
        if not required <= set(returned_scope):
            raise MastodonScopeError("mastodon.oauth.insufficient_scope", "Mastodon token lacks required scopes.")
        account = MastodonApiClient(
            origin=flow.instance_origin, transport=self.transport, access_token=access_token
        ).verify_credentials()
        token_ref, token_version = self.secret_store.put(access_token, purpose="mastodon.access_token")
        current = self.account_repository.get(channel_account_id) or MastodonAccountState(
            channel_account_id=channel_account_id,
            workspace_id=workspace_id,
            instance_origin=flow.instance_origin,
            instance_host=flow.instance_origin.removeprefix("https://").removeprefix("http://"),
            created_at=channel_store.now_iso(),
        )
        current.workspace_id = workspace_id
        current.instance_origin = flow.instance_origin
        current.instance_host = flow.instance_origin.removeprefix("https://").removeprefix("http://")
        current.remote_account_id = str(account.get("id") or "")
        current.acct = str(account.get("acct") or account.get("username") or "")
        current.username = str(account.get("username") or "")
        current.display_name = str(account.get("display_name") or "")
        current.profile_url = str(account.get("url") or "")
        current.connection_status = "connected"
        current.scope_set = returned_scope
        current.connected_at = current.connected_at or channel_store.now_iso()
        current.last_verified_at = channel_store.now_iso()
        current.token_secret_ref = token_ref
        current.token_secret_version = token_version
        current.revoked_local = False
        current.safe_error_code = ""
        current.updated_at = channel_store.now_iso()
        self.account_repository.save(current)
        flow.consumed_at = channel_store.now_iso()
        self.flow_repository.save(flow)
        self.secret_store.revoke(flow.state_secret_ref)
        self.secret_store.revoke(flow.verifier_secret_ref)
        append_event(
            "channel.mastodon.connected",
            workspace_id=workspace_id,
            account_id=channel_account_id,
            metadata={"instance_origin": flow.instance_origin, "remote_account_id": current.remote_account_id},
        )
        append_audit("oauth.complete", workspace_id=workspace_id, account_id=channel_account_id)
        return current


def pkce_s256(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
