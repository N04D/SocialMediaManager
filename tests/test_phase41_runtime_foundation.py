from __future__ import annotations

import json
import unittest

from runtime_foundation_mappings import phase41_component_manifests, phase41_runtime_registry, phase41_sample_installs
from src.core.plugins.manifest import PluginManifest
from src.core.plugins.registry import PluginRegistry
from src.core.runtime import (
    CapabilityDescriptor,
    CapabilityMode,
    CapabilityResolutionError,
    CapabilityResolver,
    ComponentBinding,
    ComponentManifest,
    EventEnvelope,
    EventSource,
    Install,
    LegacyCapabilityAdapter,
    RuntimeRegistry,
    RuntimeValidationError,
)


class Phase41EventEnvelopeTests(unittest.TestCase):
    def test_event_can_be_created_with_platform_payload(self) -> None:
        event = EventEnvelope(
            event_type="linkedin.comment.created",
            source=EventSource(
                component="linkedin-comments-browser", install="linkedin-don-personal", provider="linkedin"
            ),
            workspace_id="local",
            account_id="don-personal",
            entity_ref="urn:li:comment:1",
            external_event_id="comment-1",
            correlation_id="corr-1",
            causation_id="evt-parent",
            trace_id="trace-1",
            idempotency_key="linkedin:comment-1",
            payload={"comment": {"text": "hello", "author": "person-1"}},
            metadata={"received_by": "test"},
        )

        self.assertTrue(event.event_id.startswith("evt_"))
        self.assertEqual(event.correlation_id, "corr-1")
        self.assertEqual(event.causation_id, "evt-parent")
        self.assertEqual(event.payload["comment"]["text"], "hello")

    def test_event_type_is_validated(self) -> None:
        with self.assertRaises(RuntimeValidationError):
            EventEnvelope(event_type="LinkedIn Comment", source=EventSource(provider="linkedin"))

    def test_unique_event_ids_are_generated(self) -> None:
        left = EventEnvelope(event_type="youtube.video.published", source=EventSource(provider="youtube"))
        right = EventEnvelope(event_type="youtube.video.published", source=EventSource(provider="youtube"))
        self.assertNotEqual(left.event_id, right.event_id)

    def test_secret_shaped_payload_keys_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            EventEnvelope(
                event_type="github.file.changed",
                source=EventSource(provider="github"),
                payload={"api_token": "do-not-store"},
            )

    def test_serialization_is_deterministic(self) -> None:
        event = EventEnvelope(
            event_id="evt_fixed",
            event_type="calendar.event.created",
            source=EventSource(provider="calendar"),
            occurred_at="2026-08-09T10:00:00+00:00",
            received_at="2026-08-09T10:00:01+00:00",
            payload={"b": 2, "a": 1},
        )

        serialized = event.to_json()
        restored = EventEnvelope.from_json(serialized)

        self.assertEqual(serialized, restored.to_json())
        self.assertEqual(list(json.loads(serialized)["payload"].keys()), ["a", "b"])


class Phase41CapabilityTests(unittest.TestCase):
    def test_valid_namespaced_ids_and_modes(self) -> None:
        descriptor = CapabilityDescriptor("thirdparty.custom.action", "1.0.0", CapabilityMode.EVENT.value)
        self.assertEqual(descriptor.capability_id, "thirdparty.custom.action")
        self.assertEqual(descriptor.mode, "event")

    def test_invalid_format_rejected(self) -> None:
        with self.assertRaises(RuntimeValidationError):
            CapabilityDescriptor("not namespaced", "1.0.0", CapabilityMode.READ.value)

    def test_invalid_mode_rejected(self) -> None:
        with self.assertRaises(ValueError):
            CapabilityDescriptor("linkedin.comment.reply", "1.0.0", "mutate")


class Phase41ComponentTests(unittest.TestCase):
    def test_component_can_provide_multiple_capabilities(self) -> None:
        component = ComponentManifest(
            component_id="linkedin-comments-browser",
            provider="linkedin",
            version="0.1.0",
            sdk_version="runtime-contracts-0.1",
            capabilities=(
                CapabilityDescriptor("linkedin.comment.read", "0.1.0", "read"),
                CapabilityDescriptor("linkedin.comment.reply", "0.1.0", "write"),
            ),
        )

        self.assertTrue(component.supports("linkedin.comment.read"))
        self.assertTrue(component.supports("linkedin.comment.reply"))

    def test_two_components_can_provide_same_capability(self) -> None:
        registry = RuntimeRegistry()
        for component_id in ["linkedin-comments-browser", "linkedin-comments-api"]:
            registry.register_component(
                ComponentManifest(
                    component_id=component_id,
                    provider="linkedin",
                    version="0.1.0",
                    sdk_version="runtime-contracts-0.1",
                    capabilities=(CapabilityDescriptor("linkedin.comment.read", "0.1.0", "read"),),
                )
            )

        self.assertEqual(
            [component.component_id for component in registry.components_for("linkedin.comment.read")],
            ["linkedin-comments-api", "linkedin-comments-browser"],
        )

    def test_manifest_serialization_preserves_versions(self) -> None:
        component = phase41_component_manifests()[0]
        restored = ComponentManifest.from_dict(component.to_dict())

        self.assertEqual(restored.version, component.version)
        self.assertEqual(restored.sdk_version, component.sdk_version)
        self.assertEqual(restored.to_dict(), component.to_dict())


class Phase41InstallResolverTests(unittest.TestCase):
    def test_capability_resolves_to_bound_component(self) -> None:
        registry = RuntimeRegistry()
        component = ComponentManifest(
            component_id="linkedin-comments-browser",
            provider="linkedin",
            version="0.1.0",
            sdk_version="runtime-contracts-0.1",
            capabilities=(CapabilityDescriptor("linkedin.comment.reply", "0.1.0", "write"),),
        )
        install = Install(
            install_id="linkedin-don-personal",
            workspace_id="local",
            provider="linkedin",
            account_ref="don",
            component_bindings={"linkedin.comment.reply": ComponentBinding(component.component_id)},
            secret_refs=("linkedin-session-ref",),
        )
        registry.register_component(component)
        registry.register_install(install)

        resolved = CapabilityResolver(registry).resolve(
            install_id="linkedin-don-personal", capability="linkedin.comment.reply"
        )

        self.assertEqual(resolved.component.component_id, "linkedin-comments-browser")
        self.assertEqual(resolved.install.secret_refs, ("linkedin-session-ref",))
        self.assertNotIn("secret_value", resolved.install.to_dict())

    def test_missing_binding_is_controlled_error(self) -> None:
        registry = phase41_runtime_registry()
        with self.assertRaises(CapabilityResolutionError) as raised:
            CapabilityResolver(registry).resolve(install_id="linkedin-don-personal", capability="youtube.video.publish")
        self.assertEqual(raised.exception.code, "runtime.capability_binding_missing")

    def test_disabled_install_cannot_resolve(self) -> None:
        registry = RuntimeRegistry()
        component = ComponentManifest(
            component_id="calendar-local",
            provider="calendar",
            version="0.1.0",
            sdk_version="runtime-contracts-0.1",
            capabilities=(CapabilityDescriptor("calendar.event.read", "0.1.0", "read"),),
        )
        registry.register_component(component)
        registry.register_install(
            Install(
                install_id="calendar-disabled",
                workspace_id="local",
                provider="calendar",
                account_ref="publication",
                component_bindings={"calendar.event.read": ComponentBinding("calendar-local")},
                enabled=False,
            )
        )

        with self.assertRaises(CapabilityResolutionError) as raised:
            CapabilityResolver(registry).resolve(install_id="calendar-disabled", capability="calendar.event.read")
        self.assertEqual(raised.exception.code, "runtime.install_disabled")

    def test_multiple_installs_same_provider_resolve_independently(self) -> None:
        registry = RuntimeRegistry()
        for component_id in ["linkedin-browser-a", "linkedin-browser-b"]:
            registry.register_component(
                ComponentManifest(
                    component_id=component_id,
                    provider="linkedin",
                    version="0.1.0",
                    sdk_version="runtime-contracts-0.1",
                    capabilities=(CapabilityDescriptor("linkedin.post.create", "0.1.0", "write"),),
                )
            )
        registry.register_install(
            Install(
                install_id="linkedin-personal",
                workspace_id="local",
                provider="linkedin",
                account_ref="personal",
                component_bindings={"linkedin.post.create": ComponentBinding("linkedin-browser-a")},
            )
        )
        registry.register_install(
            Install(
                install_id="linkedin-company",
                workspace_id="local",
                provider="linkedin",
                account_ref="company",
                component_bindings={"linkedin.post.create": ComponentBinding("linkedin-browser-b")},
            )
        )

        resolver = CapabilityResolver(registry)

        self.assertEqual(
            resolver.resolve(install_id="linkedin-personal", capability="linkedin.post.create").component.component_id,
            "linkedin-browser-a",
        )
        self.assertEqual(
            resolver.resolve(install_id="linkedin-company", capability="linkedin.post.create").component.component_id,
            "linkedin-browser-b",
        )

    def test_phase41_sample_registry_has_no_hardcoded_provider_switch(self) -> None:
        registry = phase41_runtime_registry()
        resolved = CapabilityResolver(registry).resolve(
            install_id="youtube-don-main-channel", capability="youtube.video.publish"
        )
        self.assertEqual(resolved.component.component_id, "youtube-upload-channel")


class Phase41CompatibilityTests(unittest.TestCase):
    def test_existing_plugin_registry_still_accepts_legacy_manifest(self) -> None:
        manifest = PluginManifest.from_dict(
            {
                "id": "channel.linkedin",
                "name": "LinkedIn",
                "version": "0.1.0",
                "plugin_api_version": 1,
                "type": "channel",
                "entrypoint": "channels.linkedin",
                "capabilities": ["channel.publish.text", "channel.metrics.collect"],
            }
        )
        registry = PluginRegistry()

        registry.register(manifest)

        self.assertEqual(registry.require_provider_for("channel.publish.text").id, "channel.linkedin")

    def test_legacy_adapter_describes_capabilities_without_mutating_plugin_manifest(self) -> None:
        manifest = PluginManifest.from_dict(
            {
                "id": "channel.linkedin",
                "name": "LinkedIn",
                "version": "0.1.0",
                "plugin_api_version": 1,
                "type": "channel",
                "entrypoint": "channels.linkedin",
                "capabilities": ["channel.publish.text", "channel.metrics.collect", "channel.linkedin"],
            }
        )

        component = LegacyCapabilityAdapter().component_for_plugin(
            manifest,
            component_id="linkedin-legacy-adapter",
            provider="linkedin",
        )

        self.assertEqual(manifest.capabilities, ("channel.publish.text", "channel.metrics.collect", "channel.linkedin"))
        self.assertEqual(
            [capability.capability_id for capability in component.capabilities],
            ["linkedin.content.text.publish", "linkedin.analytics.metrics.read"],
        )

    def test_phase41_inventory_only_contains_expected_existing_domains(self) -> None:
        providers = {component.provider for component in phase41_component_manifests()}
        install_ids = {install.install_id for install in phase41_sample_installs()}

        self.assertEqual(providers, {"linkedin", "youtube", "github", "calendar"})
        self.assertIn("linkedin-don-personal", install_ids)
        self.assertFalse(
            any(
                capability.capability_id == "linkedin.comment.reply"
                for component in phase41_component_manifests()
                for capability in component.capabilities
            )
        )


if __name__ == "__main__":
    unittest.main()
