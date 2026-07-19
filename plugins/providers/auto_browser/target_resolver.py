from __future__ import annotations

from src.core.browser import BrowserInteractionError, BrowserTarget

from .errors import AutoBrowserStaleElementError, AutoBrowserTargetNotFoundError
from .models import AutoBrowserElement


class AutoBrowserTargetResolver:
    def resolve(self, observation: dict, target: BrowserTarget) -> AutoBrowserElement:
        matches = self.matches(observation, target)
        if not matches:
            raise AutoBrowserTargetNotFoundError("Target was not found.")
        if target.index >= len(matches):
            raise AutoBrowserTargetNotFoundError("Target index was not found.")
        if len(matches) > 1 and target.index == 0 and not target.exact:
            raise BrowserInteractionError(
                "browser_interaction.ambiguous_target",
                "Browser target matched multiple elements.",
                {"match_count": len(matches)},
            )
        return matches[target.index]

    def matches(self, observation: dict, target: BrowserTarget) -> list[AutoBrowserElement]:
        raw_elements = (
            observation.get("elements")
            or observation.get("interactive_elements")
            or observation.get("interactables")
            or []
        )
        elements = [self._element(item) for item in raw_elements if isinstance(item, dict)]
        if target.require_visible:
            elements = [element for element in elements if element.visible]

        strategies = [
            lambda e: bool(
                target.role
                and target.accessible_name
                and self._eq(e.role, target.role, target.exact)
                and self._eq(e.name, target.accessible_name, target.exact)
            ),
            lambda e: bool(target.label and self._eq(e.label, target.label, target.exact)),
            lambda e: bool(target.test_id and self._eq(e.test_id, target.test_id, target.exact)),
            lambda e: bool(target.placeholder and self._eq(e.placeholder, target.placeholder, target.exact)),
            lambda e: bool(target.title and self._eq(e.title, target.title, target.exact)),
            lambda e: bool(target.alt_text and self._eq(e.alt_text, target.alt_text, target.exact)),
            lambda e: bool(target.text and self._eq(e.text, target.text, target.exact)),
            lambda e: bool(
                target.stable_attribute
                and str(e.attributes.get(target.stable_attribute, ""))
                and (
                    not target.stable_attribute_value
                    or self._eq(
                        str(e.attributes.get(target.stable_attribute, "")), target.stable_attribute_value, target.exact
                    )
                )
            ),
            lambda e: bool(target.css and e.attributes.get("css") == target.css),
            lambda e: bool(target.xpath and e.attributes.get("xpath") == target.xpath),
        ]
        for strategy in strategies:
            matches = [element for element in elements if strategy(element)]
            if matches:
                return matches
        return []

    def resolve_retryable(self, observation: dict, target: BrowserTarget) -> AutoBrowserElement:
        try:
            return self.resolve(observation, target)
        except AutoBrowserStaleElementError:
            return self.resolve(observation, target)

    @staticmethod
    def _eq(actual: str, expected: str, exact: bool) -> bool:
        actual_norm = " ".join(str(actual or "").strip().split()).lower()
        expected_norm = " ".join(str(expected or "").strip().split()).lower()
        if exact:
            return actual_norm == expected_norm
        return expected_norm in actual_norm

    @staticmethod
    def _element(payload: dict) -> AutoBrowserElement:
        attrs = payload.get("attributes") or {}
        return AutoBrowserElement(
            element_id=str(payload.get("element_id") or payload.get("id") or payload.get("ref") or ""),
            role=str(payload.get("role") or ""),
            name=str(
                payload.get("name")
                or payload.get("accessible_name")
                or payload.get("aria_label")
                or payload.get("label")
                or ""
            ),
            text=str(payload.get("text") or payload.get("inner_text") or ""),
            label=str(payload.get("label") or ""),
            test_id=str(payload.get("test_id") or payload.get("data-testid") or attrs.get("data-testid") or ""),
            placeholder=str(payload.get("placeholder") or attrs.get("placeholder") or ""),
            title=str(payload.get("title") or attrs.get("title") or ""),
            alt_text=str(payload.get("alt_text") or attrs.get("alt") or ""),
            attributes={**dict(attrs), "css": str(payload.get("selector_hint") or attrs.get("css") or "")},
            visible=bool(payload.get("visible", True)),
            enabled=bool(payload.get("enabled", not bool(payload.get("disabled", False)))),
        )
