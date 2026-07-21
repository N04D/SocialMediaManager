"""Read-only doctor placeholder."""

from plugin_sdk.fixtures import PluginDoctorCheck


def run():
    return [PluginDoctorCheck("WARN", "not_configured", "Plugin is generated and not configured.")]
