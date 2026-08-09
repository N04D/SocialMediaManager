from __future__ import annotations

from dataclasses import dataclass, field

from .components import ComponentManifest
from .errors import CapabilityResolutionError
from .identifiers import validate_namespaced_id
from .installs import Install


@dataclass(frozen=True)
class CapabilityResolution:
    install: Install
    capability_id: str
    component: ComponentManifest


@dataclass
class RuntimeRegistry:
    components: dict[str, ComponentManifest] = field(default_factory=dict)
    installs: dict[str, Install] = field(default_factory=dict)

    def register_component(self, manifest: ComponentManifest) -> ComponentManifest:
        self.components[manifest.component_id] = manifest
        return manifest

    def register_install(self, install: Install) -> Install:
        self.installs[install.install_id] = install
        return install

    def components_for(self, capability_id: str) -> list[ComponentManifest]:
        validate_namespaced_id(capability_id, field_name="capability_id")
        return sorted(
            [component for component in self.components.values() if component.supports(capability_id)],
            key=lambda item: item.component_id,
        )


class CapabilityResolver:
    def __init__(self, registry: RuntimeRegistry) -> None:
        self.registry = registry

    def resolve(self, *, install_id: str, capability: str) -> CapabilityResolution:
        capability_id = validate_namespaced_id(capability, field_name="capability")
        install = self.registry.installs.get(install_id)
        if install is None:
            raise CapabilityResolutionError(
                "runtime.install_missing",
                "Install is not registered.",
                {"install_id": install_id},
            )
        if not install.enabled:
            raise CapabilityResolutionError(
                "runtime.install_disabled",
                "Disabled install cannot resolve capabilities.",
                {"install_id": install_id},
            )
        binding = install.binding_for(capability_id)
        if binding is None:
            raise CapabilityResolutionError(
                "runtime.capability_binding_missing",
                "Install does not bind the requested capability.",
                {"install_id": install_id, "capability": capability_id},
            )
        component = self.registry.components.get(binding.component)
        if component is None:
            raise CapabilityResolutionError(
                "runtime.component_missing",
                "Bound component is not registered.",
                {"install_id": install_id, "capability": capability_id, "component": binding.component},
            )
        if not component.supports(capability_id):
            raise CapabilityResolutionError(
                "runtime.component_capability_missing",
                "Bound component does not advertise the requested capability.",
                {"install_id": install_id, "capability": capability_id, "component": component.component_id},
            )
        return CapabilityResolution(install=install, capability_id=capability_id, component=component)
