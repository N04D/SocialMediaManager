"""Fake browser-side provider endpoint collector."""


class FakeProviderEndpoint:
    def __init__(self) -> None:
        self.events: list[dict] = []

    def capture(self, payload: dict) -> None:
        self.events.append(payload)

    @property
    def writes(self) -> int:
        return len(self.events)


__all__ = ["FakeProviderEndpoint"]
