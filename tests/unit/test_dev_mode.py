"""Tests for engine.dev_mode — the Python facade over the --developer flag.

The facade reads _dauntless_host.developer_mode via getattr() so it is safe
against stale .so files (returns False) and so tests can monkey-patch the
attribute without touching the C++ side.
"""
import pytest


@pytest.fixture
def reset_dev_mode():
    """Reset the developer_mode attribute and registries around each test."""
    import _dauntless_host
    import engine.dev_mode as dev_mode
    original = getattr(_dauntless_host, "developer_mode", False)
    original_keybindings = dict(dev_mode._dev_keybindings)
    original_menu_entries = list(dev_mode._dev_pause_menu_entries)
    try:
        yield
    finally:
        _dauntless_host.developer_mode = original
        dev_mode._dev_keybindings.clear()
        dev_mode._dev_keybindings.update(original_keybindings)
        dev_mode._dev_pause_menu_entries.clear()
        dev_mode._dev_pause_menu_entries.extend(original_menu_entries)


def test_is_enabled_returns_false_when_attribute_false(reset_dev_mode):
    import _dauntless_host
    import engine.dev_mode as dev_mode
    _dauntless_host.developer_mode = False
    assert dev_mode.is_enabled() is False


def test_is_enabled_returns_true_when_attribute_true(reset_dev_mode):
    import _dauntless_host
    import engine.dev_mode as dev_mode
    _dauntless_host.developer_mode = True
    assert dev_mode.is_enabled() is True


def test_is_enabled_returns_false_when_attribute_missing(reset_dev_mode):
    """Defensive: stale .so without the attribute returns False, not raise."""
    import _dauntless_host
    import engine.dev_mode as dev_mode
    saved = _dauntless_host.developer_mode
    del _dauntless_host.developer_mode
    try:
        assert dev_mode.is_enabled() is False
    finally:
        _dauntless_host.developer_mode = saved


def test_register_and_dispatch_calls_handler_when_enabled(reset_dev_mode):
    import _dauntless_host
    import engine.dev_mode as dev_mode
    _dauntless_host.developer_mode = True
    calls: list[int] = []
    dev_mode.register_dev_keybinding(42, lambda: calls.append(1), "test key")
    handled = dev_mode.dispatch_dev_key(42)
    assert handled is True
    assert calls == [1]


def test_dispatch_skips_handler_when_disabled(reset_dev_mode):
    import _dauntless_host
    import engine.dev_mode as dev_mode
    _dauntless_host.developer_mode = False
    calls: list[int] = []
    dev_mode.register_dev_keybinding(42, lambda: calls.append(1), "test key")
    handled = dev_mode.dispatch_dev_key(42)
    assert handled is False
    assert calls == []


def test_dispatch_returns_false_for_unregistered_key(reset_dev_mode):
    import _dauntless_host
    import engine.dev_mode as dev_mode
    _dauntless_host.developer_mode = True
    handled = dev_mode.dispatch_dev_key(999)
    assert handled is False


def test_keybinding_descriptions_returns_sorted_pairs(reset_dev_mode):
    import _dauntless_host
    import engine.dev_mode as dev_mode
    _dauntless_host.developer_mode = True
    dev_mode.register_dev_keybinding(10, lambda: None, "B handler")
    dev_mode.register_dev_keybinding(5, lambda: None, "A handler")
    descriptions = dev_mode.keybinding_descriptions()
    assert descriptions == [(5, "A handler"), (10, "B handler")]


def test_dev_only_runs_when_enabled(reset_dev_mode):
    import _dauntless_host
    import engine.dev_mode as dev_mode
    _dauntless_host.developer_mode = True

    @dev_mode.dev_only
    def f(x):
        return x * 2

    assert f(3) == 6


def test_dev_only_returns_none_when_disabled(reset_dev_mode):
    import _dauntless_host
    import engine.dev_mode as dev_mode
    _dauntless_host.developer_mode = False

    @dev_mode.dev_only
    def f(x):
        return x * 2

    assert f(3) is None


def test_dev_only_preserves_kwargs(reset_dev_mode):
    import _dauntless_host
    import engine.dev_mode as dev_mode
    _dauntless_host.developer_mode = True

    @dev_mode.dev_only
    def f(a, b=10):
        return a + b

    assert f(1, b=2) == 3


def test_dev_pause_menu_entries_empty_by_default(reset_dev_mode):
    import engine.dev_mode as dev_mode
    assert dev_mode.dev_pause_menu_entries() == []


def test_register_dev_pause_menu_entry_appends(reset_dev_mode):
    import engine.dev_mode as dev_mode
    handler_a = lambda: None
    handler_b = lambda: None
    dev_mode.register_dev_pause_menu_entry("Foo", handler_a)
    dev_mode.register_dev_pause_menu_entry("Bar", handler_b)
    assert dev_mode.dev_pause_menu_entries() == [
        ("Foo", handler_a),
        ("Bar", handler_b),
    ]


def test_register_dev_pause_menu_entry_allows_duplicate_labels(reset_dev_mode):
    """Caller-controlled list; we do not de-dup on label."""
    import engine.dev_mode as dev_mode
    h1 = lambda: None
    h2 = lambda: None
    dev_mode.register_dev_pause_menu_entry("Same", h1)
    dev_mode.register_dev_pause_menu_entry("Same", h2)
    entries = dev_mode.dev_pause_menu_entries()
    assert len(entries) == 2
    assert entries[0] == ("Same", h1)
    assert entries[1] == ("Same", h2)


# ── log_swallowed ──────────────────────────────────────────────────────────
# Production parity is the whole point: when --developer is OFF, log_swallowed
# must be a pure no-op (no logging, no formatting, no I/O) so every swallowed
# exception site stays byte-for-byte identical to the bare `pass` it replaced.

def test_log_swallowed_is_noop_when_disabled(reset_dev_mode, monkeypatch):
    """Production path: dev mode off -> the logger is never touched."""
    import _dauntless_host
    import engine.dev_mode as dev_mode
    _dauntless_host.developer_mode = False

    called: list[tuple] = []
    monkeypatch.setattr(
        dev_mode._logger, "warning",
        lambda *a, **k: called.append((a, k)),
    )
    dev_mode.log_swallowed("some operation", RuntimeError("boom"))
    assert called == []


def test_log_swallowed_logs_when_enabled(reset_dev_mode, monkeypatch):
    """Dev path: context string and exception are logged at WARNING."""
    import _dauntless_host
    import engine.dev_mode as dev_mode
    _dauntless_host.developer_mode = True

    called: list[tuple] = []
    monkeypatch.setattr(
        dev_mode._logger, "warning",
        lambda *a, **k: called.append((a, k)),
    )
    exc = RuntimeError("boom")
    dev_mode.log_swallowed("destroy bridge instance", exc)
    assert len(called) == 1
    args, _kwargs = called[0]
    # context string and the exception itself are both passed through
    assert "destroy bridge instance" in args
    assert exc in args


def test_log_swallowed_never_raises_when_disabled(reset_dev_mode):
    """Defensive: must not raise even if logging would be misconfigured —
    it returns before touching the logger at all in production."""
    import _dauntless_host
    import engine.dev_mode as dev_mode
    _dauntless_host.developer_mode = False
    # No assertion needed beyond "does not raise".
    dev_mode.log_swallowed("ctx", ValueError("x"))
