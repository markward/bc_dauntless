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
    dev_mode.reset_swallowed()
    try:
        yield
    finally:
        _dauntless_host.developer_mode = original
        dev_mode._dev_keybindings.clear()
        dev_mode._dev_keybindings.update(original_keybindings)
        dev_mode._dev_pause_menu_entries.clear()
        dev_mode._dev_pause_menu_entries.extend(original_menu_entries)
        # Swallow counts are module-global; leaving them set would let one
        # test's dedupe silence another test's first-occurrence log.
        dev_mode.reset_swallowed()


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


# ── traceback + dedupe ─────────────────────────────────────────────────────
# A swallowed exception told us WHAT broke but never WHERE: a swallowed
# AttributeError inside SendActivationEvent silently killed an entire E1M1
# mission sequence (2026-07-12) and had to be reproduced by hand to locate.
# So dev mode now renders the full traceback. But there are ~88 call sites,
# some per-frame, so a traceback per occurrence would flood the console into
# uselessness: log the traceback ONCE per unique site, then count repeats.


def _raise_at(msg):
    """Produce a genuinely-raised exception, so it carries a __traceback__."""
    try:
        raise ValueError(msg)
    except ValueError as e:
        return e


def test_log_swallowed_passes_traceback_when_enabled(reset_dev_mode, monkeypatch):
    """The traceback is what locates the bug — it must reach the log."""
    import _dauntless_host
    import engine.dev_mode as dev_mode
    _dauntless_host.developer_mode = True

    called: list[tuple] = []
    monkeypatch.setattr(dev_mode._logger, "warning",
                        lambda *a, **k: called.append((a, k)))
    exc = _raise_at("boom")
    dev_mode.log_swallowed("some operation", exc)

    assert len(called) == 1
    _args, kwargs = called[0]
    # exc_info is how logging renders the full traceback
    assert kwargs.get("exc_info") is exc
    assert exc.__traceback__ is not None


def test_log_swallowed_dedupes_repeats_from_the_same_site(reset_dev_mode, monkeypatch):
    """A per-frame swallow must not flood: traceback once, then counted."""
    import _dauntless_host
    import engine.dev_mode as dev_mode
    _dauntless_host.developer_mode = True

    called: list[tuple] = []
    monkeypatch.setattr(dev_mode._logger, "warning",
                        lambda *a, **k: called.append((a, k)))
    for _ in range(50):
        dev_mode.log_swallowed("hot path", _raise_at("same site"))

    assert len(called) == 1, "repeats from one site must be suppressed"
    assert dev_mode.swallowed_counts()[("hot path", "ValueError")] == 50


def test_log_swallowed_still_reports_a_different_site(reset_dev_mode, monkeypatch):
    """Dedupe must not silence a genuinely different failure."""
    import _dauntless_host
    import engine.dev_mode as dev_mode
    _dauntless_host.developer_mode = True

    called: list[tuple] = []
    monkeypatch.setattr(dev_mode._logger, "warning",
                        lambda *a, **k: called.append((a, k)))
    dev_mode.log_swallowed("site A", _raise_at("a"))
    dev_mode.log_swallowed("site B", _raise_at("b"))
    assert len(called) == 2


def test_swallowed_counts_untouched_in_production(reset_dev_mode, monkeypatch):
    """Production parity: dev off records nothing at all — not even a count."""
    import _dauntless_host
    import engine.dev_mode as dev_mode
    _dauntless_host.developer_mode = False

    dev_mode.log_swallowed("prod path", _raise_at("nope"))
    assert dev_mode.swallowed_counts() == {}


def test_swallowed_summary_lines_rank_by_count(reset_dev_mode, monkeypatch):
    """The at-exit summary surfaces hot swallows that were deduped away."""
    import _dauntless_host
    import engine.dev_mode as dev_mode
    _dauntless_host.developer_mode = True
    monkeypatch.setattr(dev_mode._logger, "warning", lambda *a, **k: None)

    dev_mode.log_swallowed("noisy", _raise_at("x"))
    dev_mode.log_swallowed("noisy", _raise_at("x"))
    dev_mode.log_swallowed("quiet", _raise_at("y"))

    lines = dev_mode.swallowed_summary_lines()
    assert any("swallowed exceptions" in ln for ln in lines)
    body = [ln for ln in lines if "noisy" in ln or "quiet" in ln]
    assert "noisy" in body[0] and "2" in body[0], "ranked by count, noisy first"


def test_swallowed_summary_empty_when_nothing_swallowed(reset_dev_mode):
    import engine.dev_mode as dev_mode
    assert dev_mode.swallowed_summary_lines() == []


def test_log_swallowed_never_raises_when_disabled(reset_dev_mode):
    """Defensive: must not raise even if logging would be misconfigured —
    it returns before touching the logger at all in production."""
    import _dauntless_host
    import engine.dev_mode as dev_mode
    _dauntless_host.developer_mode = False
    # No assertion needed beyond "does not raise".
    dev_mode.log_swallowed("ctx", ValueError("x"))
