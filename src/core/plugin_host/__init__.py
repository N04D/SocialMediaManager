"""Plugin Host Framework v0.1 public core package."""

from .callbacks import (
    PluginHostCallbackDispatcher,
    PluginHostContextRegistry,
    PluginHostStateStore,
    PluginHostTransferStore,
)
from .contracts import (
    PLUGIN_HOST_CALLBACK_CONTRACT_VERSION,
    PLUGIN_HOST_CRASH_POLICY_CONTRACT_VERSION,
    PLUGIN_HOST_ENVIRONMENT_CONTRACT_VERSION,
    PLUGIN_HOST_FRAMEWORK_VERSION,
    PLUGIN_HOST_HANDSHAKE_CONTRACT_VERSION,
    PLUGIN_HOST_LIFECYCLE_CONTRACT_VERSION,
    PLUGIN_HOST_PROTOCOL_VERSION,
    PLUGIN_HOST_RESOURCE_POLICY_CONTRACT_VERSION,
)
from .environment import PluginHostEnvironmentManager
from .errors import (
    PluginHostCallbackAuthorizationError,
    PluginHostCrashLoopError,
    PluginHostEnvironmentError,
    PluginHostError,
    PluginHostFrameError,
    PluginHostHandshakeError,
    PluginHostIdentityError,
    PluginHostPermissionError,
    PluginHostProcessError,
    PluginHostProtocolError,
    PluginHostQuarantineError,
    PluginHostResourceLimitError,
    PluginHostStateError,
    PluginHostTimeoutError,
)
from .framing import decode_frame, encode_frame
from .integrity import PluginHostIntegrityService
from .models import (
    PluginHostCallContext,
    PluginHostCrashRecord,
    PluginHostEnvironmentSpec,
    PluginHostHandshake,
    PluginHostHealth,
    PluginHostIntegrityFinding,
    PluginHostProcessRecord,
    PluginHostResourcePolicy,
    PluginReady,
)
from .proxies import RemoteChannelPluginProxy, RemoteChannelRuntimeProxy
from .resources import PluginHostResourceController
from .supervisor import PluginHostProcess, PluginHostSupervisor, classify_mutation_recovery

__all__ = [
    "PLUGIN_HOST_CALLBACK_CONTRACT_VERSION",
    "PLUGIN_HOST_CRASH_POLICY_CONTRACT_VERSION",
    "PLUGIN_HOST_ENVIRONMENT_CONTRACT_VERSION",
    "PLUGIN_HOST_FRAMEWORK_VERSION",
    "PLUGIN_HOST_HANDSHAKE_CONTRACT_VERSION",
    "PLUGIN_HOST_LIFECYCLE_CONTRACT_VERSION",
    "PLUGIN_HOST_PROTOCOL_VERSION",
    "PLUGIN_HOST_RESOURCE_POLICY_CONTRACT_VERSION",
    "PluginHostCallContext",
    "PluginHostCallbackAuthorizationError",
    "PluginHostCallbackDispatcher",
    "PluginHostContextRegistry",
    "PluginHostCrashLoopError",
    "PluginHostCrashRecord",
    "PluginHostEnvironmentError",
    "PluginHostEnvironmentManager",
    "PluginHostEnvironmentSpec",
    "PluginHostError",
    "PluginHostFrameError",
    "PluginHostHandshake",
    "PluginHostHandshakeError",
    "PluginHostHealth",
    "PluginHostIdentityError",
    "PluginHostIntegrityFinding",
    "PluginHostIntegrityService",
    "PluginHostPermissionError",
    "PluginHostProcess",
    "PluginHostProcessError",
    "PluginHostProcessRecord",
    "PluginHostProtocolError",
    "PluginHostQuarantineError",
    "PluginHostResourceController",
    "PluginHostResourceLimitError",
    "PluginHostResourcePolicy",
    "PluginHostStateError",
    "PluginHostStateStore",
    "PluginHostSupervisor",
    "PluginHostTimeoutError",
    "PluginHostTransferStore",
    "PluginReady",
    "RemoteChannelPluginProxy",
    "RemoteChannelRuntimeProxy",
    "classify_mutation_recovery",
    "decode_frame",
    "encode_frame",
]
