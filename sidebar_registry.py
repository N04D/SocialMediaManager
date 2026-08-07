from __future__ import annotations

import html
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class PluginMenuItem:
    id: str
    label: str
    href: str
    icon: str
    fallback: str
    status: str = "stable"


@dataclass
class PluginMenuCategory:
    id: str
    label: str
    icon: str
    fallback: str
    items: list[PluginMenuItem] = field(default_factory=list)


def get_plugin_menu_categories() -> list[PluginMenuCategory]:
    # 1. Dynamically scan channel plugins
    channel_items: list[PluginMenuItem] = []
    try:
        from channel_registry import scan_channel_registry
        entries = scan_channel_registry()
        for entry in entries:
            p_id = entry.id
            manifest = entry.manifest or {}
            p_name = manifest.get("name") or p_id.replace("_", " ").title()

            if p_id == "linkedin":
                href = "/linkedin"
            elif p_id == "markdown_website":
                href = "/setup"
            else:
                href = f"/channels/{p_id}"

            icon_key = p_id if p_id in {"linkedin", "substack", "youtube", "instagram", "x", "mastodon", "blog"} else "channels"
            channel_items.append(
                PluginMenuItem(
                    id=p_id,
                    label=p_name,
                    href=href,
                    icon=icon_key,
                    fallback=p_id[:2].upper(),
                    status=manifest.get("status", "stable"),
                )
            )
    except Exception:
        channel_items = [
            PluginMenuItem("linkedin", "LinkedIn", "/linkedin", "linkedin", "LI"),
            PluginMenuItem("markdown_website", "Markdown Website", "/setup", "config", "MW"),
            PluginMenuItem("substack", "Substack", "/channels/substack", "channels", "SS"),
            PluginMenuItem("youtube", "YouTube", "/channels/youtube", "media", "YT"),
            PluginMenuItem("instagram", "Instagram", "/channels/instagram", "media", "IG"),
            PluginMenuItem("x", "X (Twitter)", "/channels/x", "channels", "X"),
            PluginMenuItem("mastodon", "Mastodon", "/channels/mastodon", "channels", "MA"),
            PluginMenuItem("blog", "Blog", "/channels/blog", "editor", "BL"),
        ]

    # 2. Media Plugins
    media_items = [
        PluginMenuItem("image-generator", "Image Generator", "/plugins/media/image-generator", "media", "IG"),
        PluginMenuItem("video-renderer", "Video Renderer", "/plugins/media/video-renderer", "media", "VR"),
        PluginMenuItem("audio-transcriber", "Audio Transcriber", "/plugins/media/audio-transcriber", "media", "AT"),
    ]

    # 3. E-commerce Plugins
    ecommerce_items = [
        PluginMenuItem("shopify", "Shopify Store", "/plugins/ecommerce/shopify", "config", "SH"),
        PluginMenuItem("woocommerce", "WooCommerce", "/plugins/ecommerce/woocommerce", "config", "WC"),
        PluginMenuItem("products", "Products Catalog", "/plugins/ecommerce/products", "config", "PR"),
    ]

    # 4. AI & Skills Plugins
    ai_items = [
        PluginMenuItem("ai-prompts", "AI Prompt Config", "/channels", "channels", "AI"),
        PluginMenuItem("derivative-skills", "Derivative Skills", "/plugins/ai/skills", "editor", "SK"),
    ]

    return [
        PluginMenuCategory("channels", "Channel Plugins", "channels", "CH", channel_items),
        PluginMenuCategory("media", "Media Plugins", "media", "ME", media_items),
        PluginMenuCategory("ecommerce", "E-commerce Plugins", "config", "EC", ecommerce_items),
        PluginMenuCategory("ai_skills", "AI & Skills", "channels", "AI", ai_items),
    ]


def render_modular_sidebar(active_route: str, render_icon_func: Callable[[str, str], str]) -> str:
    top_nav = [
        ("/home", "home", "Home", "HM"),
        ("/editor", "editor", "Editor", "ED"),
        ("/drafts", "drafts", "Drafts", "DR"),
        ("/setup", "config", "Website Setup", "SU"),
        ("/analytics", "stats", "Analytics", "AN"),
    ]

    top_html = []
    for route, icon, label, fb in top_nav:
        is_active = " active" if active_route == route else ""
        top_html.append(
            f'<a class="sidebar-link{is_active}" href="{route}">'
            f'<span class="sidebar-icon">{render_icon_func(icon, fb)}</span>'
            f'<span class="sidebar-label">{html.escape(label)}</span></a>'
        )

    categories = get_plugin_menu_categories()
    group_html = []

    for cat in categories:
        has_active = any(
            item.href == active_route or (item.href != "/" and active_route.startswith(item.href))
            for item in cat.items
        )
        open_attr = " open" if (has_active or cat.id == "channels") else ""

        items_html = []
        for item in cat.items:
            is_active = " active" if active_route == item.href else ""
            items_html.append(
                f'<a class="sidebar-link sublink{is_active}" href="{item.href}">'
                f'<span class="sidebar-icon">{render_icon_func(item.icon, item.fallback)}</span>'
                f'<span class="sidebar-label">{html.escape(item.label)}</span></a>'
            )

        group_html.append(f"""
        <details class="sidebar-accordion"{open_attr}>
          <summary class="sidebar-accordion-header">
            <span class="sidebar-icon">{render_icon_func(cat.icon, cat.fallback)}</span>
            <span class="sidebar-label">{html.escape(cat.label)}</span>
            <span class="sidebar-chevron">▼</span>
          </summary>
          <div class="sidebar-subnav">
            {"".join(items_html)}
          </div>
        </details>
        """)

    settings_active = " active" if active_route in {"/settings", "/config"} else ""
    settings_html = (
        f'<a class="sidebar-link{settings_active}" href="/settings">'
        f'<span class="sidebar-icon">{render_icon_func("config", "SE")}</span>'
        f'<span class="sidebar-label">Settings</span></a>'
    )

    return f"""
      <aside class="sidebar" id="sidebar">
        <div class="sidebar-top">
          <div class="brand">SocialMediaManager</div>
          <button class="sidebar-toggle" id="sidebar-toggle" type="button" aria-label="Toggle navigation"><span aria-hidden="true">|||</span></button>
        </div>
        <nav class="sidebar-nav" aria-label="Primary navigation">
          {"".join(top_html)}
          <div class="sidebar-group">
            <div class="sidebar-group-title">Plugins & Skills</div>
            {"".join(group_html)}
          </div>
          {settings_html}
        </nav>
      </aside>
    """
