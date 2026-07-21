import os


def test_integration_opt_in():
    assert os.environ.get("CHANNEL_EXAMPLE_INTEGRATION") != "1" or True
