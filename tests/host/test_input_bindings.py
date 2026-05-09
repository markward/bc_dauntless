"""Verify _open_stbc_host exposes input-related bindings."""


def test_keys_submodule_exists():
    import _open_stbc_host
    assert hasattr(_open_stbc_host, "keys")


def test_key_constants_exist_and_are_distinct():
    import _open_stbc_host
    k = _open_stbc_host.keys
    names = ["KEY_W", "KEY_S", "KEY_A", "KEY_D", "KEY_Q", "KEY_E", "KEY_R",
             "KEY_0", "KEY_1", "KEY_2", "KEY_3", "KEY_4",
             "KEY_5", "KEY_6", "KEY_7", "KEY_8", "KEY_9"]
    values = []
    for name in names:
        v = getattr(k, name)
        assert isinstance(v, int), f"{name} not an int: {type(v)}"
        values.append(v)
    assert len(set(values)) == len(values), "key constants are not distinct"
