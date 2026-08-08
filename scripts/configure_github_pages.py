#!/usr/bin/env python3
"""Configure GitHub Pages settings for N04D/website.

Run from the repository root:
    python3 scripts/configure_github_pages.py
"""

from __future__ import annotations

import shutil
import time
from pathlib import Path

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Locator, Page, TimeoutError, sync_playwright

REPOSITORY_URL = "https://github.com/N04D/website"
PAGES_SETTINGS_URL = f"{REPOSITORY_URL}/settings/pages"
ACTIONS_URL = f"{REPOSITORY_URL}/actions"
CUSTOM_DOMAIN = "donberghuijs.nl"
PROFILE_DIR = Path("github_pages_session")


def log(message: str) -> None:
    print(f"[github-pages] {message}", flush=True)


def chromium_executable() -> str | None:
    for candidate in (
        shutil.which("chromium"),
        shutil.which("chromium-browser"),
        shutil.which("google-chrome"),
        shutil.which("google-chrome-stable"),
        "/snap/bin/chromium",
    ):
        if candidate:
            return candidate
    return None


def first_visible(page: Page, selectors: list[str], *, timeout_ms: int = 1_500) -> Locator | None:
    for selector in selectors:
        locator = page.locator(selector).first
        try:
            locator.wait_for(state="visible", timeout=timeout_ms)
            return locator
        except (PlaywrightError, TimeoutError):
            continue
    return None


def wait_for_login(page: Page) -> None:
    log(f"Navigating to {PAGES_SETTINGS_URL}")
    page.goto(PAGES_SETTINGS_URL, wait_until="domcontentloaded")

    deadline = time.monotonic() + 300
    while time.monotonic() < deadline:
        current = page.url
        if "/login" in current or "/sessions/" in current:
            log("GitHub vraagt om inloggen/2FA. Rond dit af in het geopende browservenster.")
            page.wait_for_timeout(5_000)
            continue

        if page.locator("text=Settings").first.is_visible(timeout=1_000):
            log("Ingelogd en repository settings zijn bereikbaar.")
            return

        if page.locator("text=Page not found").first.is_visible(timeout=500):
            raise RuntimeError(
                "GitHub toont 'Page not found'. Controleer of je account toegang heeft tot de repository settings."
            )

        page.wait_for_timeout(2_000)

    raise TimeoutError("Login/settings-pagina werd niet binnen 5 minuten bereikbaar.")


def select_option_if_needed(select: Locator, value_or_label: str, label: str) -> bool:
    current_value = select.input_value(timeout=2_000)
    current_label = select.locator("option:checked").inner_text(timeout=2_000).strip()
    if current_value == value_or_label or current_label == value_or_label:
        log(f"{label} staat al op {value_or_label!r}.")
        return False

    try:
        select.select_option(value=value_or_label)
    except (PlaywrightError, TimeoutError):
        select.select_option(label=value_or_label)
    log(f"{label} ingesteld op {value_or_label!r}.")
    return True


def save_nearest_form(control: Locator, action: str) -> None:
    button = control.locator(
        "xpath=ancestor::form[1]//button[normalize-space()='Save' or contains(normalize-space(), 'Save')]"
    ).first
    if not button.count():
        button = control.locator(
            "xpath=ancestor::*[self::section or self::div][1]//button[normalize-space()='Save' or contains(normalize-space(), 'Save')]"
        ).first
    if not button.count():
        raise RuntimeError(f"Kon geen Save-knop vinden voor {action}.")

    if button.is_disabled(timeout=1_000):
        log(f"Save-knop voor {action} is uitgeschakeld; waarschijnlijk geen wijziging nodig.")
        return

    button.click()
    log(f"Save geklikt voor {action}.")
    page = control.page
    page.wait_for_load_state("domcontentloaded")
    page.wait_for_timeout(2_500)


def ensure_deploy_from_branch(page: Page) -> None:
    log("Stap A: Build and deployment bron controleren.")

    changed = False
    source_select = first_visible(
        page,
        [
            "select[name='pages_source']",
            "select[name='source']",
            "select[aria-label='Source']",
        ],
    )

    if source_select:
        options = [item.strip() for item in source_select.locator("option").all_inner_texts()]
        deploy_label = next((option for option in options if "Deploy from a branch" in option), None)
        if deploy_label:
            changed = select_option_if_needed(source_select, deploy_label, "Source") or changed
        else:
            log("Source-select gevonden, maar optie 'Deploy from a branch' niet herkend.")
    else:
        source_button = first_visible(
            page,
            [
                "button:has-text('GitHub Actions')",
                "button:has-text('Deploy from a branch')",
                "[role='button']:has-text('GitHub Actions')",
                "[role='button']:has-text('Deploy from a branch')",
            ],
        )
        if source_button and "Deploy from a branch" not in source_button.inner_text(timeout=2_000):
            source_button.click()
            option = first_visible(
                page, ["text=Deploy from a branch", "[role='menuitemradio']:has-text('Deploy from a branch')"]
            )
            if not option:
                raise RuntimeError("Kon de optie 'Deploy from a branch' niet openen/selecteren.")
            option.click()
            log("Source ingesteld op 'Deploy from a branch'.")
            changed = True
        elif source_button:
            log("Source staat al op 'Deploy from a branch'.")
        else:
            log("Geen expliciete Source-control gevonden; ik ga door naar branch/root controle.")

    branch_select = first_visible(
        page,
        [
            "select[name='branch']",
            "select[name='source[branch]']",
            "select[aria-label='Branch']",
            "#pages_source_branch",
        ],
    )
    if not branch_select:
        branch_select = page.locator("select").filter(has=page.locator("option", has_text="main")).first
        if not branch_select.count():
            raise RuntimeError("Kon de Branch-select niet vinden.")
    changed = select_option_if_needed(branch_select, "main", "Branch") or changed

    folder_select = first_visible(
        page,
        [
            "select[name='folder']",
            "select[name='source[path]']",
            "select[aria-label='Folder']",
            "#pages_source_path",
        ],
    )
    if not folder_select:
        folder_select = page.locator("select").filter(has=page.locator("option", has_text="/ (root)")).first
    if folder_select.count():
        options = [item.strip() for item in folder_select.locator("option").all_inner_texts()]
        root_label = next(
            (option for option in options if option in {"/ (root)", "/"} or "root" in option.lower()), "/ (root)"
        )
        changed = select_option_if_needed(folder_select, root_label, "Folder") or changed
    else:
        log("Folder-select niet gevonden; GitHub toont mogelijk geen mapkeuze voor deze repo.")

    if changed:
        save_nearest_form(branch_select, "Build and deployment")
    else:
        log("Build and deployment stond al correct.")


def set_custom_domain(page: Page) -> None:
    log("Stap B: Custom domain instellen.")
    domain_input = page.locator('input[name="user_site[custom_domain]"]').first
    domain_input.wait_for(state="visible", timeout=30_000)

    current = domain_input.input_value(timeout=2_000).strip()
    if current == CUSTOM_DOMAIN:
        log(f"Custom domain staat al op {CUSTOM_DOMAIN}.")
    else:
        domain_input.fill(CUSTOM_DOMAIN)
        save_nearest_form(domain_input, "Custom domain")

    log("Wachten op DNS-check verwerking/status.")
    page.wait_for_timeout(8_000)
    status_text = first_visible(
        page,
        [
            "text=/DNS|Certificate|TLS|verified|checking|Check again/i",
            "[data-testid*='pages']:has-text('DNS')",
        ],
        timeout_ms=4_000,
    )
    if status_text:
        log("GitHub Pages domeinstatus: " + " ".join(status_text.inner_text(timeout=2_000).split()))


def enforce_https(page: Page) -> None:
    log("Stap C: Enforce HTTPS controleren.")
    checkbox = first_visible(
        page,
        [
            "input[type='checkbox'][name='user_site[https_enforced]']",
            "input[type='checkbox'][aria-label='Enforce HTTPS']",
            "label:has-text('Enforce HTTPS') input[type='checkbox']",
        ],
        timeout_ms=5_000,
    )
    if not checkbox:
        log("Enforce HTTPS checkbox is nog niet aanwezig. Waarschijnlijk loopt DNS/TLS-verificatie nog.")
        return

    if checkbox.is_disabled(timeout=1_000):
        log("Enforce HTTPS is zichtbaar maar geblokkeerd. GitHub wacht waarschijnlijk nog op DNS/TLS-checks.")
        return

    if checkbox.is_checked(timeout=1_000):
        log("Enforce HTTPS is al ingeschakeld.")
        return

    checkbox.check()
    log("Enforce HTTPS ingeschakeld.")
    page.wait_for_timeout(3_000)


def report_actions_status(page: Page) -> None:
    log("Stap D: Actions status controleren.")
    page.goto(ACTIONS_URL, wait_until="domcontentloaded")
    try:
        page.wait_for_load_state("networkidle", timeout=30_000)
    except TimeoutError:
        log("Actions-pagina bleef netwerkactiviteit houden; ik lees de zichtbare status alsnog uit.")

    workflow = first_visible(
        page,
        [
            "a:has-text('pages-build-deployment')",
            "text=pages-build-deployment",
            "text=/pages build and deployment/i",
        ],
        timeout_ms=20_000,
    )
    if not workflow:
        log("Geen pages-build-deployment workflow zichtbaar op de Actions-pagina.")
        return

    row = workflow.locator("xpath=ancestor::*[self::li or self::div][contains(., 'pages')][1]").first
    status_source = row if row.count() else workflow
    status = " ".join(status_source.inner_text(timeout=5_000).split())
    log(f"Uiteindelijke Actions status: {status}")


def main() -> int:
    executable = chromium_executable()
    launch_kwargs = {"headless": False}
    if executable:
        launch_kwargs["executable_path"] = executable

    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            **launch_kwargs,
        )
        page = context.pages[0] if context.pages else context.new_page()
        page.set_default_timeout(20_000)

        try:
            wait_for_login(page)
            ensure_deploy_from_branch(page)
            set_custom_domain(page)
            enforce_https(page)
            report_actions_status(page)
            log("Klaar.")
            return 0
        finally:
            context.close()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        log(f"FOUT: {exc}")
        raise
