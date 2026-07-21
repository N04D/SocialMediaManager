from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from collections.abc import Callable
from dataclasses import asdict, fields
from pathlib import Path
from typing import Any, TypeVar

import channel_store
from channel_storage import locked_json_store

from .models import (
    MastodonAccountState,
    MastodonAppRegistration,
    MastodonInstanceSnapshot,
    MastodonOAuthFlowState,
    MastodonRemoteMediaUpload,
    MastodonRequirementsSnapshot,
)

T = TypeVar("T")


def _path(name: str) -> Path:
    return channel_store.STUDIO_DATA_DIR / name


def _list_store(path: Path):
    return locked_json_store(path, default_factory=list, expect_type=list, lock_dir=channel_store.LOCKS_DIR)


def _dict_store(path: Path):
    return locked_json_store(path, default_factory=dict, expect_type=dict, lock_dir=channel_store.LOCKS_DIR)


def _fields(cls: type) -> set[str]:
    return {field.name for field in fields(cls)}


def _load_records(path: Path, cls: type[T]) -> list[T]:  # noqa: UP047
    with _list_store(path) as store:
        payload = store.read()
    allowed = _fields(cls)
    records: list[T] = []
    for item in payload:
        if isinstance(item, dict):
            try:
                records.append(cls(**{key: value for key, value in item.items() if key in allowed}))
            except TypeError:
                continue
    return records


def _mutate(path: Path, cls: type[T], mutator: Callable[[list[T]], tuple[bool, Any]]) -> Any:  # noqa: UP047
    with _list_store(path) as store:
        payload = store.read()
        allowed = _fields(cls)
        records: list[T] = []
        for item in payload:
            if isinstance(item, dict):
                try:
                    records.append(cls(**{key: value for key, value in item.items() if key in allowed}))
                except TypeError:
                    continue
        changed, result = mutator(records)
        if changed:
            store.write([asdict(record) for record in records])
        return result


def _upsert[T](records: list[T], record: T, key: str) -> None:
    value = getattr(record, key)
    for index, existing in enumerate(records):
        if getattr(existing, key) == value:
            records[index] = record
            return
    records.append(record)


def canonical_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def checksum(payload: Any) -> str:
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def accounts_path() -> Path:
    return _path("mastodon_accounts.json")


def instances_path() -> Path:
    return _path("mastodon_instance_snapshots.json")


def requirements_path() -> Path:
    return _path("mastodon_requirements_snapshots.json")


def apps_path() -> Path:
    return _path("mastodon_app_registrations.json")


def flows_path() -> Path:
    return _path("mastodon_oauth_flows.json")


def secrets_path() -> Path:
    return _path("mastodon_secret_store.json")


def remote_media_path() -> Path:
    return _path("mastodon_remote_media_uploads.json")


def events_path() -> Path:
    return _path("mastodon_events.json")


def audit_path() -> Path:
    return _path("mastodon_audit.json")


class MastodonSecretStore:
    def __init__(self, *, namespace: str = "mastodon") -> None:
        self.namespace = namespace
        key = os.environ.get("SOCIALMEDIAMANAGER_SECRET_KEY") or "local-development-secret"
        self._key = hashlib.sha256(key.encode("utf-8")).digest()

    def put(self, value: str, *, purpose: str) -> tuple[str, int]:
        ref = f"secret_{self.namespace}_{os.urandom(12).hex()}"
        nonce = os.urandom(16)
        data = value.encode("utf-8")
        mask = hashlib.sha256(self._key + nonce).digest()
        encrypted = bytes(byte ^ mask[index % len(mask)] for index, byte in enumerate(data))
        mac = hmac.new(self._key, nonce + encrypted, hashlib.sha256).hexdigest()
        record = {
            "version": 1,
            "purpose": purpose,
            "nonce": base64.urlsafe_b64encode(nonce).decode("ascii"),
            "ciphertext": base64.urlsafe_b64encode(encrypted).decode("ascii"),
            "mac": mac,
            "created_at": channel_store.now_iso(),
            "revoked_at": "",
        }
        with _dict_store(secrets_path()) as store:
            payload = store.read()
            payload[ref] = record
            store.write(payload)
        return ref, 1

    def get(self, ref: str) -> str:
        with _dict_store(secrets_path()) as store:
            payload = store.read()
        record = payload.get(ref)
        if not isinstance(record, dict) or record.get("revoked_at"):
            raise KeyError(ref)
        nonce = base64.urlsafe_b64decode(str(record["nonce"]).encode("ascii"))
        encrypted = base64.urlsafe_b64decode(str(record["ciphertext"]).encode("ascii"))
        mac = hmac.new(self._key, nonce + encrypted, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(mac, str(record.get("mac") or "")):
            raise KeyError(ref)
        mask = hashlib.sha256(self._key + nonce).digest()
        data = bytes(byte ^ mask[index % len(mask)] for index, byte in enumerate(encrypted))
        return data.decode("utf-8")

    def revoke(self, ref: str) -> None:
        with _dict_store(secrets_path()) as store:
            payload = store.read()
            if isinstance(payload.get(ref), dict):
                payload[ref]["revoked_at"] = channel_store.now_iso()
            store.write(payload)


class _Repo:
    cls: type
    key: str = "id"

    def path(self) -> Path:
        raise NotImplementedError

    def list_all(self) -> list[Any]:
        return _load_records(self.path(), self.cls)

    def get(self, record_id: str):
        return next((item for item in self.list_all() if getattr(item, self.key) == record_id), None)

    def save(self, record):
        return _mutate(self.path(), self.cls, lambda records: (_upsert(records, record, self.key) or True, record))


class MastodonAccountRepository(_Repo):
    cls = MastodonAccountState

    def path(self) -> Path:
        return accounts_path()

    key = "channel_account_id"

    def list_by_workspace(self, workspace_id: str) -> list[MastodonAccountState]:
        return [item for item in self.list_all() if not workspace_id or item.workspace_id == workspace_id]


class MastodonInstanceRepository(_Repo):
    cls = MastodonInstanceSnapshot

    def path(self) -> Path:
        return instances_path()

    key = "id"

    def latest_for_origin(self, origin: str) -> MastodonInstanceSnapshot | None:
        matches = [item for item in self.list_all() if item.origin == origin]
        return sorted(matches, key=lambda item: (item.discovered_at, item.id))[-1] if matches else None


class MastodonRequirementsRepository(_Repo):
    cls = MastodonRequirementsSnapshot

    def path(self) -> Path:
        return requirements_path()

    key = "id"

    def latest_for_account(self, account_id: str) -> MastodonRequirementsSnapshot | None:
        matches = [item for item in self.list_all() if item.channel_account_id == account_id]
        return sorted(matches, key=lambda item: (item.discovered_at, item.id))[-1] if matches else None


class MastodonAppRepository(_Repo):
    cls = MastodonAppRegistration

    def path(self) -> Path:
        return apps_path()

    key = "id"

    def find(self, *, instance_origin: str, redirect_uri: str, scopes: list[str], application_name: str):
        wanted = sorted(scopes)
        return next(
            (
                item
                for item in self.list_all()
                if item.instance_origin == instance_origin
                and item.redirect_uri == redirect_uri
                and sorted(item.scopes) == wanted
                and item.application_name == application_name
            ),
            None,
        )


class MastodonOAuthFlowRepository(_Repo):
    cls = MastodonOAuthFlowState

    def path(self) -> Path:
        return flows_path()

    key = "id"


class MastodonRemoteMediaRepository(_Repo):
    cls = MastodonRemoteMediaUpload

    def path(self) -> Path:
        return remote_media_path()

    key = "attachment_id"


def append_event(
    action: str, *, workspace_id: str = "", account_id: str = "", metadata: dict[str, Any] | None = None
) -> None:
    with _list_store(events_path()) as store:
        records = store.read()
        records.append(
            {
                "id": f"mastodon_event_{os.urandom(8).hex()}",
                "action": action,
                "workspace_id": workspace_id,
                "channel_account_id": account_id,
                "metadata": _safe_metadata(metadata or {}),
                "created_at": channel_store.now_iso(),
            }
        )
        store.write(records[-500:])


def append_audit(
    action: str,
    *,
    workspace_id: str = "",
    account_id: str = "",
    actor: str = "",
    result: str = "ok",
    safe_error_code: str = "",
    metadata: dict[str, Any] | None = None,
) -> None:
    with _list_store(audit_path()) as store:
        records = store.read()
        records.append(
            {
                "id": f"mastodon_audit_{os.urandom(8).hex()}",
                "action": action,
                "workspace_id": workspace_id,
                "channel_account_id": account_id,
                "actor": actor,
                "result": result,
                "safe_error_code": safe_error_code,
                "metadata": _safe_metadata(metadata or {}),
                "created_at": channel_store.now_iso(),
            }
        )
        store.write(records[-500:])


def _safe_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    blocked = ("token", "secret", "code", "verifier", "authorization", "path", "storage")
    safe = {}
    for key, value in metadata.items():
        lowered = str(key).lower()
        if any(item in lowered for item in blocked):
            continue
        if isinstance(value, dict):
            safe[str(key)] = _safe_metadata(value)
        elif isinstance(value, list):
            safe[str(key)] = [str(item)[:200] for item in value if not isinstance(item, dict)]
        elif isinstance(value, (str, int, float, bool)) or value is None:
            safe[str(key)] = value
    return safe
