"""Fake provider observations for deterministic staging certification."""

from __future__ import annotations


class FakeStagingProvider:
    def __init__(self) -> None:
        self.visible = False
        self.events: list[dict[str, str]] = []

    def add_browser_event(self, event: dict[str, object]) -> None:
        props = {str(key): str(value) for key, value in dict(event.get("props", {})).items()}
        self.events.append({"event_name": str(event.get("name", "")), **props})

    def make_visible(self) -> None:
        self.visible = True

    def observations(self, run_id: str) -> list[dict[str, str]]:
        if not self.visible:
            return []
        return [event for event in self.events if event.get("smm_synthetic_run_id") == run_id]


__all__ = ["FakeStagingProvider"]
