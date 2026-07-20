from __future__ import annotations

MEDIA_FRAMEWORK_VERSION = "0.1.0"
MEDIA_STORAGE_PROVIDER_CONTRACT_VERSION = "1.0"
MEDIA_ASSET_CONTRACT_VERSION = "1.0"
MEDIA_REFERENCE_CONTRACT_VERSION = "1.0"
MEDIA_PLUGIN_CONTRACT_VERSION = "1.0"

MEDIA_STORAGE_CAPABILITIES = (
    "media.storage",
    "media.storage.store",
    "media.storage.read",
    "media.storage.materialize",
    "media.storage.delete",
)


def media_contract_major(version: str) -> str:
    return str(version).split(".", maxsplit=1)[0]


def media_storage_contract_compatibility(
    implemented: str, required: str = MEDIA_STORAGE_PROVIDER_CONTRACT_VERSION
) -> str:
    if not implemented:
        return "incompatible"
    if media_contract_major(implemented) != media_contract_major(required):
        return "incompatible"
    if implemented == required:
        return "compatible"
    return "compatible_with_warnings"


def media_contract_payload(
    *, implemented_storage_version: str = MEDIA_STORAGE_PROVIDER_CONTRACT_VERSION
) -> dict[str, str]:
    return {
        "media_framework_version": MEDIA_FRAMEWORK_VERSION,
        "media_storage_provider_contract_version": implemented_storage_version,
        "required_media_storage_provider_contract_version": MEDIA_STORAGE_PROVIDER_CONTRACT_VERSION,
        "media_asset_contract_version": MEDIA_ASSET_CONTRACT_VERSION,
        "media_reference_contract_version": MEDIA_REFERENCE_CONTRACT_VERSION,
        "media_plugin_contract_version": MEDIA_PLUGIN_CONTRACT_VERSION,
        "contract_compatibility": media_storage_contract_compatibility(implemented_storage_version),
    }
