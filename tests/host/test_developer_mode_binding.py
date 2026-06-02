"""Verifies the _dauntless_host module exposes a developer_mode attribute.

The attribute is set at PYBIND11_MODULE init from
dauntless::is_developer_mode(). When pytest loads the .so standalone (no
host_main.cc), the underlying bool defaults to False.
"""


def test_developer_mode_attribute_exists():
    import _dauntless_host
    assert hasattr(_dauntless_host, "developer_mode")


def test_developer_mode_default_is_false():
    import _dauntless_host
    assert _dauntless_host.developer_mode is False


def test_developer_mode_is_python_writable_for_tests():
    """Python tests monkey-patch the attribute to exercise enabled paths.

    The C++ getter is irrelevant in this scenario; only the Python attr
    matters because engine/dev_mode.py reads via getattr().
    """
    import _dauntless_host
    original = _dauntless_host.developer_mode
    try:
        _dauntless_host.developer_mode = True
        assert _dauntless_host.developer_mode is True
    finally:
        _dauntless_host.developer_mode = original
