from __future__ import annotations

MEDIA_FRAMEWORK_VERSION = "0.3.0"
MEDIA_STORAGE_PROVIDER_CONTRACT_VERSION = "1.0"
MEDIA_ASSET_CONTRACT_VERSION = "1.0"
MEDIA_REFERENCE_CONTRACT_VERSION = "1.0"
MEDIA_PLUGIN_CONTRACT_VERSION = "1.0"
MEDIA_INSPECTION_CONTRACT_VERSION = "1.0"
MEDIA_PROCESSING_CONTRACT_VERSION = "1.0"
MEDIA_REQUIREMENT_CONTRACT_VERSION = "1.0"
MEDIA_LIBRARY_CONTRACT_VERSION = "1.0"
MEDIA_RELATION_CONTRACT_VERSION = "1.0"
MEDIA_USAGE_CONTRACT_VERSION = "1.0"
MEDIA_RETENTION_CONTRACT_VERSION = "1.0"

MEDIA_STORAGE_CAPABILITIES = (
    "media.storage",
    "media.storage.store",
    "media.storage.read",
    "media.storage.materialize",
    "media.storage.delete",
)

MEDIA_PROCESSING_CAPABILITIES = (
    "media.image.inspect",
    "media.image.processing.basic",
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
        "media_inspection_contract_version": MEDIA_INSPECTION_CONTRACT_VERSION,
        "media_processing_contract_version": MEDIA_PROCESSING_CONTRACT_VERSION,
        "media_requirement_contract_version": MEDIA_REQUIREMENT_CONTRACT_VERSION,
        "media_library_contract_version": MEDIA_LIBRARY_CONTRACT_VERSION,
        "media_relation_contract_version": MEDIA_RELATION_CONTRACT_VERSION,
        "media_usage_contract_version": MEDIA_USAGE_CONTRACT_VERSION,
        "media_retention_contract_version": MEDIA_RETENTION_CONTRACT_VERSION,
        "contract_compatibility": media_storage_contract_compatibility(implemented_storage_version),
    }
