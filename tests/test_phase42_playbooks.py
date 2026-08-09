from __future__ import annotations

import json
import unittest
from dataclasses import replace
from pathlib import Path

from runtime_foundation_mappings import phase41_runtime_registry
from src.core.runtime import (
    CapabilityDescriptor,
    CapabilityMode,
    CapabilityReportEntry,
    ComponentBinding,
    ComponentManifest,
    DeploymentValidationError,
    Install,
    PlaybookDefinition,
    PlaybookDeployment,
    PlaybookEdge,
    PlaybookNode,
    PlaybookValidationError,
    RequirementBinding,
    capability_report,
    compile_execution_plan,
    validate_deployment,
    validate_playbook,
)

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "playbooks"


def fixture_playbook() -> PlaybookDefinition:
    return PlaybookDefinition.from_dict(
        json.loads((FIXTURE_DIR / "portable_event_to_capabilities.json").read_text(encoding="utf-8"))
    )


def fixture_deployment() -> PlaybookDeployment:
    return PlaybookDeployment.from_dict(json.loads((FIXTURE_DIR / "deployment_local.json").read_text(encoding="utf-8")))


def simple_playbook() -> PlaybookDefinition:
    return PlaybookDefinition(
        playbook_id="example.simple",
        version="1.0.0",
        schema_version="1.0",
        name="Simple",
        requirements={"writer": {"capabilities": ["github.file.write"]}},
        nodes=(
            PlaybookNode("trigger", "trigger", {"event_type": "github.file.changed"}),
            PlaybookNode("write", "capability", {"requirement": "writer", "capability": "github.file.write"}),
        ),
        edges=(PlaybookEdge("trigger", "write"),),
    )


class Phase42PlaybookValidationTests(unittest.TestCase):
    def test_valid_playbook_and_serialization_roundtrip(self) -> None:
        playbook = fixture_playbook()

        validate_playbook(playbook)
        restored = PlaybookDefinition.from_json(playbook.to_json())

        self.assertEqual(restored.to_json(), playbook.to_json())
        self.assertNotIn("install_id", playbook.to_json())

    def test_duplicate_node_rejected(self) -> None:
        playbook = simple_playbook()
        invalid = replace(playbook, nodes=(*playbook.nodes, PlaybookNode("write", "approval")))

        with self.assertRaises(PlaybookValidationError) as raised:
            validate_playbook(invalid)
        self.assertEqual(raised.exception.code, "playbook.duplicate_node")

    def test_missing_node_in_edge_rejected(self) -> None:
        invalid = replace(simple_playbook(), edges=(PlaybookEdge("trigger", "missing"),))

        with self.assertRaises(PlaybookValidationError) as raised:
            validate_playbook(invalid)
        self.assertEqual(raised.exception.code, "playbook.edge_node_missing")

    def test_self_edge_rejected(self) -> None:
        invalid = replace(simple_playbook(), edges=(PlaybookEdge("trigger", "trigger"),))

        with self.assertRaises(PlaybookValidationError) as raised:
            validate_playbook(invalid)
        self.assertEqual(raised.exception.code, "playbook.self_edge")

    def test_cycle_rejected(self) -> None:
        invalid = replace(simple_playbook(), edges=(PlaybookEdge("trigger", "write"), PlaybookEdge("write", "trigger")))

        with self.assertRaises(PlaybookValidationError) as raised:
            validate_playbook(invalid)
        self.assertEqual(raised.exception.code, "playbook.cycle")

    def test_no_trigger_rejected(self) -> None:
        invalid = replace(
            simple_playbook(),
            nodes=(PlaybookNode("write", "capability", {"requirement": "writer", "capability": "github.file.write"}),),
        )

        with self.assertRaises(PlaybookValidationError) as raised:
            validate_playbook(invalid)
        self.assertEqual(raised.exception.code, "playbook.trigger_missing")

    def test_unknown_requirement_rejected(self) -> None:
        invalid = replace(
            simple_playbook(),
            nodes=(
                PlaybookNode("trigger", "trigger", {"event_type": "github.file.changed"}),
                PlaybookNode("write", "capability", {"requirement": "unknown", "capability": "github.file.write"}),
            ),
        )

        with self.assertRaises(PlaybookValidationError) as raised:
            validate_playbook(invalid)
        self.assertEqual(raised.exception.code, "playbook.requirement_unknown")

    def test_capability_not_declared_in_requirement_rejected(self) -> None:
        invalid = replace(
            simple_playbook(),
            nodes=(
                PlaybookNode("trigger", "trigger", {"event_type": "github.file.changed"}),
                PlaybookNode("write", "capability", {"requirement": "writer", "capability": "github.file.read"}),
            ),
        )

        with self.assertRaises(PlaybookValidationError) as raised:
            validate_playbook(invalid)
        self.assertEqual(raised.exception.code, "playbook.capability_not_declared")

    def test_schema_version_handling(self) -> None:
        with self.assertRaises(PlaybookValidationError) as raised:
            replace(simple_playbook(), schema_version="99.0")
        self.assertEqual(raised.exception.code, "playbook.schema_version_unsupported")

    def test_unknown_plain_node_kind_rejected_but_namespaced_kind_allowed(self) -> None:
        with self.assertRaises(PlaybookValidationError):
            PlaybookNode("mystery", "mystery", {})

        node = PlaybookNode("custom", "thirdparty.custom", {})
        self.assertEqual(node.kind, "thirdparty.custom")

    def test_playbook_definition_rejects_install_ids_and_secrets(self) -> None:
        with self.assertRaises(PlaybookValidationError):
            PlaybookNode("bad", "trigger", {"install_id": "linkedin-don-personal"})
        with self.assertRaises(PlaybookValidationError):
            PlaybookNode("bad", "trigger", {"token": "secret-value"})


class Phase42DeploymentAndPlanTests(unittest.TestCase):
    def test_requirements_bound_and_same_install_can_fulfill_multiple_slots(self) -> None:
        playbook = PlaybookDefinition(
            playbook_id="example.same_install",
            version="1.0.0",
            schema_version="1.0",
            name="Same Install",
            requirements={
                "reader": {"capabilities": ["linkedin.post.read"]},
                "analytics": {"capabilities": ["linkedin.analytics.read"]},
            },
            nodes=(PlaybookNode("trigger", "trigger", {"event_type": "linkedin.post.created"}),),
        )
        deployment = PlaybookDeployment(
            deployment_id="same-install",
            playbook_id=playbook.playbook_id,
            playbook_version=playbook.version,
            workspace_id="local",
            requirement_bindings={
                "reader": RequirementBinding("linkedin-don-personal"),
                "analytics": RequirementBinding("linkedin-don-personal"),
            },
        )

        result = validate_deployment(playbook, deployment, phase41_runtime_registry())

        self.assertTrue(result.ok)
        self.assertEqual({entry.install_id for entry in result.entries}, {"linkedin-don-personal"})

    def test_same_playbook_different_deployments_compile_differently(self) -> None:
        playbook = simple_playbook()
        registry = phase41_runtime_registry()
        alt_component = ComponentManifest(
            component_id="github-markdown-website-alt",
            provider="github",
            version="0.1.0",
            sdk_version="runtime-contracts-0.1",
            capabilities=(CapabilityDescriptor("github.file.write", "0.1.0", CapabilityMode.WRITE.value),),
        )
        registry.register_component(alt_component)
        registry.register_install(
            Install(
                install_id="github-alt-website",
                workspace_id="local",
                provider="github",
                account_ref="alt",
                component_bindings={"github.file.write": ComponentBinding("github-markdown-website-alt")},
            )
        )
        first = PlaybookDeployment(
            "deploy-a",
            playbook.playbook_id,
            playbook.version,
            "local",
            {"writer": RequirementBinding("github-don-website")},
        )
        second = replace(
            first, deployment_id="deploy-b", requirement_bindings={"writer": RequirementBinding("github-alt-website")}
        )

        first_plan = compile_execution_plan(playbook, first, registry)
        second_plan = compile_execution_plan(playbook, second, registry)

        self.assertNotEqual(first_plan.to_json(), second_plan.to_json())
        self.assertIn("github-markdown-website", first_plan.to_json())
        self.assertIn("github-markdown-website-alt", second_plan.to_json())
        self.assertNotIn("install_id", playbook.to_json())

    def test_missing_binding_disabled_install_and_missing_capability_report(self) -> None:
        playbook = simple_playbook()
        registry = phase41_runtime_registry()

        missing_binding = PlaybookDeployment("missing", playbook.playbook_id, playbook.version, "local", {})
        report = capability_report(playbook, missing_binding, registry)
        self.assertFalse(report.ok)
        self.assertEqual(report.failures()[0].error_code, "MISSING_BINDING")

        disabled_install = replace(registry.installs["github-don-website"], enabled=False)
        registry.register_install(disabled_install)
        disabled = PlaybookDeployment(
            "disabled",
            playbook.playbook_id,
            playbook.version,
            "local",
            {"writer": RequirementBinding("github-don-website")},
        )
        with self.assertRaises(DeploymentValidationError) as raised:
            validate_deployment(playbook, disabled, registry)
        self.assertEqual(raised.exception.code, "INSTALL_DISABLED")

        registry = phase41_runtime_registry()
        wrong = PlaybookDeployment(
            "wrong",
            playbook.playbook_id,
            playbook.version,
            "local",
            {"writer": RequirementBinding("linkedin-don-personal")},
        )
        with self.assertRaises(DeploymentValidationError) as raised:
            validate_deployment(playbook, wrong, registry)
        self.assertEqual(raised.exception.code, "MISSING_CAPABILITY")

    def test_successful_resolution_and_structured_report_entries(self) -> None:
        playbook = fixture_playbook()
        deployment = fixture_deployment()

        report = validate_deployment(playbook, deployment, phase41_runtime_registry())

        self.assertTrue(report.ok)
        self.assertTrue(all(isinstance(entry, CapabilityReportEntry) for entry in report.entries))
        self.assertEqual(
            {(entry.requirement, entry.capability, entry.install_id) for entry in report.entries},
            {
                ("social_source", "linkedin.post.read", "linkedin-don-personal"),
                ("website_writer", "github.file.write", "github-don-website"),
            },
        )

    def test_execution_plan_is_deterministic_resolved_and_side_effect_free(self) -> None:
        playbook = fixture_playbook()
        deployment = fixture_deployment()
        registry = phase41_runtime_registry()
        before = registry.components.copy(), registry.installs.copy(), playbook.to_json()

        left = compile_execution_plan(playbook, deployment, registry)
        right = compile_execution_plan(playbook, deployment, registry)

        self.assertEqual(left.to_json(), right.to_json())
        self.assertIn("linkedin-browser-channel", left.to_json())
        self.assertIn("github-markdown-website", left.to_json())
        self.assertEqual(before, (registry.components.copy(), registry.installs.copy(), playbook.to_json()))

    def test_deployment_rejects_secret_values(self) -> None:
        playbook = simple_playbook()
        with self.assertRaises(DeploymentValidationError):
            PlaybookDeployment(
                "bad",
                playbook.playbook_id,
                playbook.version,
                "local",
                {"writer": RequirementBinding("github-don-website")},
                config={"api_" + "key": "redacted-placeholder"},
            )

    def test_no_platform_switch_statements_in_compiler(self) -> None:
        source = Path("src/core/runtime/plans.py").read_text(encoding="utf-8")
        self.assertNotIn("if linkedin", source.lower())
        self.assertNotIn("if youtube", source.lower())


if __name__ == "__main__":
    unittest.main()
