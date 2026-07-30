"""Contract versions for alpha onboarding v0.1."""

ALPHA_ONBOARDING_FRAMEWORK_VERSION = "0.1.0"
ALPHA_ONBOARDING_SESSION_CONTRACT_VERSION = "1.0"
ALPHA_ONBOARDING_STEP_CONTRACT_VERSION = "1.0"
ALPHA_SETUP_READINESS_CONTRACT_VERSION = "1.0"
ALPHA_FIRST_PUBLICATION_CONTRACT_VERSION = "1.0"
ALPHA_GUIDED_RECOVERY_CONTRACT_VERSION = "1.0"
ALPHA_DEMO_MODE_CONTRACT_VERSION = "1.0"


def contract_payload() -> dict[str, str]:
    return {
        "alpha_onboarding_framework_version": ALPHA_ONBOARDING_FRAMEWORK_VERSION,
        "alpha_onboarding_session_contract_version": ALPHA_ONBOARDING_SESSION_CONTRACT_VERSION,
        "alpha_onboarding_step_contract_version": ALPHA_ONBOARDING_STEP_CONTRACT_VERSION,
        "alpha_setup_readiness_contract_version": ALPHA_SETUP_READINESS_CONTRACT_VERSION,
        "alpha_first_publication_contract_version": ALPHA_FIRST_PUBLICATION_CONTRACT_VERSION,
        "alpha_guided_recovery_contract_version": ALPHA_GUIDED_RECOVERY_CONTRACT_VERSION,
        "alpha_demo_mode_contract_version": ALPHA_DEMO_MODE_CONTRACT_VERSION,
    }
