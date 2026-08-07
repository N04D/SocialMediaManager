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


def get_sidebar_css() -> str:
    return """
    .sidebar { width: var(--sidebar-width, 268px); background: linear-gradient(180deg, rgba(12, 12, 14, 0.98), rgba(7, 7, 8, 0.94)); border-right: 1px solid rgba(113, 113, 122, 0.20); padding: 14px 12px; position: sticky; top: 0; height: 100vh; overflow-y: auto; transition: width 0.2s ease; z-index: 20; flex-shrink: 0; }
    .sidebar-top { display: flex; justify-content: flex-end; align-items: center; gap: 10px; margin-bottom: 16px; }
    .sidebar-toggle { border: 1px solid rgba(113, 113, 122, 0.22); border-radius: var(--radius, 8px); background: rgba(31, 31, 35, 0.78); color: var(--text, #f4f4f5); width: 34px; height: 34px; cursor: pointer; font-size: 12px; transition: background 0.2s ease, border-color 0.2s ease, transform 0.2s ease; }
    .sidebar-toggle:hover { background: rgba(39, 39, 42, 0.92); border-color: rgba(161, 161, 170, 0.24); transform: translateY(-1px); }
    .sidebar-nav { display: grid; gap: 2px; }
    .sidebar-nav a, .sidebar-link { color: var(--muted, #a1a1aa); text-decoration: none; min-height: 36px; padding: 6px 8px; border-radius: var(--radius, 8px); border: 1px solid transparent; font-weight: 600; font-size: 13px; display: flex; align-items: center; gap: 8px; transition: background 0.2s ease, color 0.2s ease, border-color 0.2s ease; }
    .sidebar-nav a:hover, .sidebar-link:hover { background: rgba(244, 244, 245, .08); border-color: rgba(113, 113, 122, .24); color: #ffffff; }
    .sidebar-nav a.active, .sidebar-link.active { background: rgba(63, 63, 70, 0.78); color: #ffffff; border-color: rgba(161, 161, 170, 0.35); box-shadow: inset 3px 0 0 #f4f4f5; font-weight: 700; }
    .sidebar-nav a.active:hover, .sidebar-link.active:hover { background: rgba(82, 82, 91, 0.90); color: #ffffff; border-color: rgba(212, 212, 216, 0.45); }
    .sidebar-icon { width: 24px; height: 24px; border-radius: var(--radius, 8px); background: rgba(244, 244, 245, 0.07); display: inline-flex; align-items: center; justify-content: center; font-weight: 700; flex-shrink: 0; color: currentColor; }
    .sidebar-icon svg { width: 14px; height: 14px; fill: none; stroke: currentColor; stroke-width: 1.8; stroke-linecap: round; stroke-linejoin: round; }
    .sidebar-fallback { font-size: 10px; letter-spacing: 0.04em; font-weight: 700; }
    .sidebar-label { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; font-size: 13px; font-weight: 600; }

    .sidebar-group { margin-top: 10px; padding-top: 10px; border-top: 1px solid rgba(113, 113, 122, 0.20); }
    .sidebar-group-title { font-size: 10px; font-weight: 700; letter-spacing: 0.08em; text-transform: uppercase; color: var(--muted, #a1a1aa); padding: 2px 8px 6px 8px; opacity: 0.8; }
    .sidebar-accordion { margin-bottom: 2px; border: 0 !important; padding: 0 !important; background: transparent !important; box-shadow: none !important; }
    .sidebar-accordion summary.sidebar-accordion-header { list-style: none; cursor: pointer; color: var(--muted, #a1a1aa); min-height: 36px; padding: 6px 8px; border-radius: var(--radius, 8px); border: 1px solid transparent; font-weight: 600; font-size: 13px; display: flex; align-items: center; gap: 8px; user-select: none; transition: background 0.2s ease, color 0.2s ease; }
    .sidebar-accordion summary.sidebar-accordion-header::-webkit-details-marker { display: none; }
    .sidebar-accordion summary.sidebar-accordion-header:hover { background: rgba(244, 244, 245, .08); color: #ffffff; }
    .sidebar-accordion[open] > summary.sidebar-accordion-header { color: #ffffff; font-weight: 700; }
    .sidebar-chevron { margin-left: auto; font-size: 9px; transition: transform 0.2s ease; opacity: 0.7; }
    .sidebar-accordion[open] .sidebar-chevron { transform: rotate(180deg); }
    .sidebar-subnav { display: grid; gap: 2px; padding-left: 10px; margin-top: 2px; border-left: 1.5px solid rgba(113, 113, 122, 0.22); margin-left: 12px; }
    .sidebar-subnav .sidebar-link.sublink { min-height: 34px; padding: 4px 8px; font-size: 12.5px; font-weight: 500; }
    .sidebar-subnav .sidebar-link.sublink.active { font-weight: 700; background: rgba(63, 63, 70, 0.78); color: #ffffff; border-color: rgba(161, 161, 170, 0.35); }

    body.sidebar-collapsed .sidebar { width: var(--sidebar-collapsed-width, 76px); }
    body.sidebar-collapsed .sidebar-label { display: none; }
    body.sidebar-collapsed .sidebar-top { justify-content: center; }
    body.sidebar-collapsed .brand { display: none; }
    body.sidebar-collapsed .workspace { display: none; }
    body.sidebar-collapsed .sidebar-group-title { display: none; }
    body.sidebar-collapsed .sidebar-chevron { display: none; }
    body.sidebar-collapsed .sidebar-nav a { justify-content: center; padding-left: 0; padding-right: 0; }
    body.sidebar-collapsed .sidebar-accordion summary.sidebar-accordion-header { justify-content: center; padding-left: 0; padding-right: 0; }
    """


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
