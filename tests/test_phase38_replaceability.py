from __future__ import annotations

import unittest

from plugins.transformations.video_repurpose.clip_intelligence import ClipSignalResult, FusionConfig
from tests.phase38_support import Phase38Harness, rank_with_replacement_signal


class Phase38ReplaceabilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.harness = Phase38Harness()
        self.addCleanup(self.harness.close)

    def test_hook_detector_can_be_replaced_without_rendering_or_other_analyzers(self) -> None:
        candidates = self.harness.baseline_candidates()
        target = candidates[-1]
        replacement = ClipSignalResult(
            signal_id="clip.signal.hook",
            candidate_id=target.candidate_id,
            start_time=target.start_time,
            end_time=target.end_time,
            score=1.0,
            reason="External hook scorer preferred this opening",
            provenance={"plugin_id": "plugin.future_hook"},
        )
        ranked = rank_with_replacement_signal(self.harness.plugin, candidates, replacement)
        self.assertEqual(ranked[0].candidate.candidate_id, target.candidate_id)
        self.assertEqual(ranked[0].signal_contributions["clip.signal.hook"], 1.0)

    def test_multiple_producers_contract_uses_same_signal_id(self) -> None:
        config = FusionConfig(hook_weight=1.0, semantic_weight=0.0)
        self.assertIn("clip.signal.hook", config.weights())

    def test_capability_registry_discovers_clip_signal_family(self) -> None:
        registry = self.harness.runtime.registry
        producers = registry.producers_for("clip.signal.hook")
        self.assertTrue(any(plugin.id == "plugin.video_repurpose" for plugin in producers))
        family_payload = registry.capabilities_by_family(enabled_only=True)
        transformation_caps = {entry["capability"] for entry in family_payload.get("transformations", [])}
        self.assertIn("clip.signal.hook", transformation_caps)
