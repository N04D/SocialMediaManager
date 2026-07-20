from __future__ import annotations

BROWSER_FRAMEWORK_VERSION = "1.0.0"
BROWSER_PROVIDER_CONTRACT_VERSION = "1.0"
BROWSER_SESSION_CONTRACT_VERSION = "1.0"
BROWSER_TARGET_CONTRACT_VERSION = "1.0"
BROWSER_ARTIFACT_CONTRACT_VERSION = "1.0"

REQUIRED_BROWSER_PROVIDER_METHODS = (
    "create_session",
    "close_session",
    "get_session",
    "profile_status",
    "health_check",
    "request_human_takeover",
)

REQUIRED_BROWSER_SESSION_METHODS = (
    "navigate",
    "snapshot",
    "current_url",
    "title",
    "element_exists",
    "element_visible",
    "element_enabled",
    "count",
    "text_content",
    "attribute",
    "wait_for",
    "wait_for_timeout",
    "reload",
    "go_back",
    "keyboard_press",
    "keyboard_insert_text",
    "click",
    "clear",
    "hover",
    "fill",
    "upload",
    "wait_for_load_state",
    "evaluate",
    "screenshot",
    "close",
)

OPTIONAL_BROWSER_CAPABILITIES = ("browser.auth_profile.delete",)


def contract_major(version: str) -> str:
    return str(version).split(".", maxsplit=1)[0]


def browser_contract_compatibility(implemented: str, required: str = BROWSER_PROVIDER_CONTRACT_VERSION) -> str:
    if not implemented:
        return "incompatible"
    if contract_major(implemented) != contract_major(required):
        return "incompatible"
    if implemented == required:
        return "compatible"
    return "compatible_with_warnings"


def browser_contract_payload(
    *, implemented_provider_version: str = BROWSER_PROVIDER_CONTRACT_VERSION
) -> dict[str, str]:
    return {
        "browser_framework_version": BROWSER_FRAMEWORK_VERSION,
        "browser_provider_contract_version": implemented_provider_version,
        "required_browser_provider_contract_version": BROWSER_PROVIDER_CONTRACT_VERSION,
        "browser_session_contract_version": BROWSER_SESSION_CONTRACT_VERSION,
        "browser_target_contract_version": BROWSER_TARGET_CONTRACT_VERSION,
        "browser_artifact_contract_version": BROWSER_ARTIFACT_CONTRACT_VERSION,
        "contract_compatibility": browser_contract_compatibility(implemented_provider_version),
    }
