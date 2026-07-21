from plugin_sdk.compatibility import scan_forbidden_imports, scan_secrets


def test_security_scans_clean():
    assert scan_forbidden_imports(".") == []
    assert scan_secrets(".") == []
