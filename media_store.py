from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

import channel_store
from channel_storage import locked_json_store
from src.core.media import MediaAsset, MediaStatus, MediaVariant


def media_assets_path() -> Path:
    return channel_store.STUDIO_DATA_DIR / "media_assets.json"


def media_variants_path() -> Path:
    return channel_store.STUDIO_DATA_DIR / "media_variants.json"


def legacy_media_mappings_path() -> Path:
    return channel_store.STUDIO_DATA_DIR / "legacy_media_path_mappings.json"


def _list_store(path: Path):
    channel_store.ensure_channel_store_dirs()
    return locked_json_store(path, default_factory=list, expect_type=list, lock_dir=channel_store.LOCKS_DIR)


def _dict_store(path: Path):
    channel_store.ensure_channel_store_dirs()
    return locked_json_store(path, default_factory=dict, expect_type=dict, lock_dir=channel_store.LOCKS_DIR)


def _load_records(path: Path, cls):
    with _list_store(path) as store:
        payload = store.read()
    records = []
    for item in payload:
        if isinstance(item, dict):
            try:
                records.append(cls(**item))
            except TypeError:
                continue
    return records


def _save_records(path: Path, records: list[Any]) -> None:
    with _list_store(path) as store:
        store.write([asdict(record) for record in records])


def save_media_asset(asset: MediaAsset) -> MediaAsset:
    records = list_media_assets()
    for index, record in enumerate(records):
        if record.id == asset.id:
            records[index] = asset
            _save_records(media_assets_path(), records)
            return asset
    records.append(asset)
    _save_records(media_assets_path(), records)
    return asset


def get_media_asset(asset_id: str) -> MediaAsset | None:
    return next((asset for asset in list_media_assets() if asset.id == asset_id), None)


def list_media_assets(*, workspace_id: str = "") -> list[MediaAsset]:
    records = _load_records(media_assets_path(), MediaAsset)
    if workspace_id:
        records = [record for record in records if record.workspace_id == workspace_id]
    return records


def find_media_asset_by_checksum(workspace_id: str, checksum: str) -> MediaAsset | None:
    return next(
        (
            asset
            for asset in list_media_assets(workspace_id=workspace_id)
            if asset.checksum == checksum and asset.status != MediaStatus.DELETED.value
        ),
        None,
    )


def save_media_variant(variant: MediaVariant) -> MediaVariant:
    records = list_media_variants()
    for index, record in enumerate(records):
        if record.id == variant.id:
            records[index] = variant
            _save_records(media_variants_path(), records)
            return variant
    records.append(variant)
    _save_records(media_variants_path(), records)
    return variant


def list_media_variants(*, asset_id: str = "") -> list[MediaVariant]:
    records = _load_records(media_variants_path(), MediaVariant)
    if asset_id:
        records = [record for record in records if record.asset_id == asset_id]
    return records


def get_legacy_media_mapping(path: Path) -> str:
    with _dict_store(legacy_media_mappings_path()) as store:
        payload = store.read()
    return str(payload.get(str(path.resolve())) or "")


def save_legacy_media_mapping(path: Path, asset_id: str) -> None:
    with _dict_store(legacy_media_mappings_path()) as store:
        payload = store.read()
        payload[str(path.resolve())] = asset_id
        store.write(payload)
