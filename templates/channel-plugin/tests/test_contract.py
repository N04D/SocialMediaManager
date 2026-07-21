from plugin_sdk.compatibility import build_compatibility_report


def test_manifest_compatible():
    report = build_compatibility_report(".")
    assert report.compatible, report.to_json()
