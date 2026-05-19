"""Verify _dauntless_host exposes input-related bindings."""


def test_keys_submodule_exists():
    import _dauntless_host
    assert hasattr(_dauntless_host, "keys")


def test_key_constants_exist_and_are_distinct():
    import _dauntless_host
    k = _dauntless_host.keys
    names = ["KEY_W", "KEY_S", "KEY_A", "KEY_D", "KEY_Q", "KEY_E", "KEY_R",
             "KEY_0", "KEY_1", "KEY_2", "KEY_3", "KEY_4",
             "KEY_5", "KEY_6", "KEY_7", "KEY_8", "KEY_9"]
    values = []
    for name in names:
        v = getattr(k, name)
        assert isinstance(v, int), f"{name} not an int: {type(v)}"
        values.append(v)
    assert len(set(values)) == len(values), "key constants are not distinct"


def test_key_state_false_when_no_window_focus():
    import os
    import _dauntless_host
    os.environ["OPEN_STBC_HOST_HEADLESS"] = "1"
    try:
        _dauntless_host.init(64, 64, "key-state-test")
    except RuntimeError as e:
        import pytest
        pytest.skip(f"no GL context: {e}")
    try:
        # Hidden offscreen window never gets focus -> all keys read RELEASE.
        for name in ("KEY_W", "KEY_S", "KEY_A", "KEY_D", "KEY_R"):
            code = getattr(_dauntless_host.keys, name)
            assert _dauntless_host.key_state(code) is False, f"{name} reads pressed"
    finally:
        _dauntless_host.shutdown()


def test_key_pressed_returns_false_when_not_held():
    import os
    import _dauntless_host
    os.environ["OPEN_STBC_HOST_HEADLESS"] = "1"
    try:
        _dauntless_host.init(64, 64, "key-pressed-test")
    except RuntimeError as e:
        import pytest
        pytest.skip(f"no GL context: {e}")
    try:
        # Without focus, no rising edges fire across multiple frames.
        for _ in range(3):
            assert _dauntless_host.key_pressed(_dauntless_host.keys.KEY_W) is False
            _dauntless_host.frame()
    finally:
        _dauntless_host.shutdown()


def test_key_bindings_require_init():
    import _dauntless_host
    import pytest
    # key_state must throw if init wasn't called (no window to query).
    with pytest.raises(RuntimeError):
        _dauntless_host.key_state(_dauntless_host.keys.KEY_W)
    with pytest.raises(RuntimeError):
        _dauntless_host.key_pressed(_dauntless_host.keys.KEY_W)
