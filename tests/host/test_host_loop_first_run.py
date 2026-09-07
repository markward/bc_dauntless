"""Boot's path branch: prompt when unresolved, and degrade safely.

The fallback guard here is the most important test in the feature. If a
picker-less platform ever boots on unresolved paths, or loses the
describe_failure() diagnostic, nothing else in the suite would notice.
"""

import sys as _sys

import pytest

from engine import first_run, host_loop, paths
from engine import settings_store as _settings_store_mod
from tests.helpers.source_guards import code_only as _code_only

# Captured before any fixture gets a chance to monkeypatch paths.persist /
# paths.resolve, so a test can reinstate the REAL implementation (pointed at
# a FakeStore, or left otherwise real) instead of the no-op
# _nothing_resolves_by_accident installs for every other test here.
_REAL_PERSIST = paths.persist
_REAL_RESOLVE = paths.resolve


class FakeStore:
    def __init__(self, values=None):
        self._values = dict(values or {})

    def has(self, section, key):
        return (section, key) in self._values

    def get(self, section, key):
        return self._values[(section, key)]

    def set(self, section, key, value):
        self._values[(section, key)] = value


@pytest.fixture
def install(tmp_path):
    game = tmp_path / "install" / "game"          # paths-guard: test fixture tree
    for marker in paths.GAME_MARKERS:
        (game / marker).mkdir(parents=True, exist_ok=True)
    sdk = tmp_path / "install" / "sdk"            # paths-guard: test fixture tree
    (sdk / "Build" / "scripts").mkdir(parents=True, exist_ok=True)
    (sdk / "Build" / "scripts" / "App.py").write_text("")
    (sdk / "Build" / "Data" / "TGL").mkdir(parents=True, exist_ok=True)
    return game, sdk


@pytest.fixture(autouse=True)
def _nothing_resolves_by_accident(monkeypatch):
    """Force every ambient source empty, and never touch the real settings.

    Without this the developer's own settings.json would resolve the roots
    and neither test would exercise the branch it names.
    """
    fake_store = FakeStore()
    real_resolve = paths.resolve

    # The keyword names must match what _resolve_paths_or_report and the
    # first-run screen's resolver actually pass -- both call
    # paths.resolve(argv=, env=, store=, picked=), so a replacement that
    # renames `store` raises TypeError rather than running the branch under
    # test.
    def resolve(argv=None, env=None, store=None, picked=None):
        return real_resolve(argv=[], env={}, store=fake_store, picked=picked)

    monkeypatch.setattr(paths, "resolve", resolve)
    monkeypatch.setattr(paths, "persist", lambda resolution, store=None: None)
    monkeypatch.setattr(paths, "configure", lambda resolution: None)
    return fake_store


def test_unresolved_paths_hand_off_to_the_first_run_screen(monkeypatch, install):
    """When paths.resolve() comes back unresolved, _resolve_paths_or_report
    hands off to the first-run screen and boots on whatever it comes back
    with. The screen's own picker-driving mechanics -- prompting per row,
    skipping an already-resolved one, reporting what was wrong -- are
    FirstRunPanel's job and are covered at that layer
    (tests/unit/test_first_run_panel.py), plus end-to-end through the real
    pump loop (tests/host/test_host_loop_unit.py). This test is the WIRING:
    the screen is consulted on failure, and gets the unresolved Resolution.
    """
    game, sdk = install
    resolved = paths.resolve(argv=[], env={}, store=FakeStore(),
                              picked={"game": str(game), "sdk": str(sdk)})
    seen = []

    def fake_screen(resolution, **kwargs):
        seen.append(resolution)
        return resolved

    monkeypatch.setattr(host_loop, "_run_first_run_screen", fake_screen)

    result = host_loop._resolve_paths_or_report()

    assert result is not None and result.ok
    assert result.source("game") == "picker"
    assert len(seen) == 1 and not seen[0].ok, (
        "the screen must be handed the UNRESOLVED resolution")


def test_no_picker_prints_the_diagnostic_and_stops_boot(monkeypatch, capsys):
    """The fallback guard: Windows, Linux, a stale .so, or a plain cancel."""
    monkeypatch.setattr(first_run, "_default_picker",
                        lambda title, message: None)

    result = host_loop._resolve_paths_or_report()

    assert result is None, "boot must not continue on unresolved paths"
    printed = capsys.readouterr().err
    assert "cannot locate your Bridge Commander install" in printed
    assert "--game-dir" in printed


def test_no_live_browser_skips_the_screen_and_prints_the_diagnostic(
        monkeypatch, capsys):
    """CRITICAL 3 regression: a `--no-cef` build, or a live build whose
    cef_initialize() call failed, stubs every cef_* binding to a no-op --
    including cef_set_load_end_handler, whose callback would then never
    fire. Pumping _run_first_run_screen's loop in that state spins forever
    on a black window with no way for the player to ever close it, where
    the OLD behaviour (before this branch reordered boot) was an
    immediate, legible diagnostic and a non-zero exit.

    run() captures cef_initialize()'s own return value and threads it in
    as `cef_ready`; when False, _resolve_paths_or_report() must skip
    _run_first_run_screen entirely and fall straight through to the same
    describe_failure() + None path a picker-less platform already takes.
    Proven here by making _run_first_run_screen raise if it is ever
    called -- this test fails loudly instead of hanging if the gate is
    ever removed.
    """
    def _must_not_be_called(resolution, **kwargs):
        raise AssertionError(
            "_run_first_run_screen must not run when cef_ready is False -- "
            "there is no live browser for it to draw into")
    monkeypatch.setattr(host_loop, "_run_first_run_screen", _must_not_be_called)

    result = host_loop._resolve_paths_or_report(cef_ready=False)

    assert result is None, "boot must not continue on unresolved paths"
    printed = capsys.readouterr().err
    assert "cannot locate your Bridge Commander install" in printed


def test_a_partial_screen_result_persists_even_when_boot_still_fails(
        monkeypatch, install, _nothing_resolves_by_accident):
    """FINDING 1 regression test: a root the first-run screen located must
    reach the STORE, not just the in-memory Resolution, even when boot still
    fails overall -- e.g. the player located the game folder by hand, then
    quit before finding the sdk one.

    _resolve_paths_or_report() used to call persist() only after the
    `if not resolution.ok: return None` branch, so that player got nothing
    written -- next launch asked for BOTH roots again. persist() must run
    on this partial-resolution path too. The screen itself is stubbed out
    here (its picker-driving mechanics are FirstRunPanel's job, covered in
    tests/unit/test_first_run_panel.py) so this test is purely about what
    _resolve_paths_or_report does with a partial result.
    """
    game, _sdk = install
    fake_store = _nothing_resolves_by_accident

    # _nothing_resolves_by_accident stubs persist() to a no-op so the OTHER
    # tests in this file never touch a store. Reinstate the real
    # implementation for this one test, still pointed at the same
    # fake_store paths.resolve() already uses, so the assertion below
    # watches actual writes rather than an in-memory Resolution field.
    monkeypatch.setattr(
        paths, "persist",
        lambda resolution, store=None: _REAL_PERSIST(resolution, store=fake_store))

    # The screen located "game" and returned with "sdk" still missing --
    # the shape a quit-after-one-pick leaves behind.
    partial = paths.resolve(argv=[], env={}, store=FakeStore(),
                             picked={"game": str(game)})
    assert partial.game == game and not partial.ok
    monkeypatch.setattr(host_loop, "_run_first_run_screen",
                         lambda resolution, **kwargs: partial)

    result = host_loop._resolve_paths_or_report()

    assert result is None, "sdk is still missing, so boot must still stop"
    assert fake_store.has("paths", "game"), (
        "the validated game root was never persisted -- the player will be "
        "asked for it again next launch")
    assert fake_store.get("paths", "game") == str(game)
    assert not fake_store.has("paths", "sdk"), (
        "the missing sdk root must not be written")


def test_the_screens_resolver_stays_bound_to_the_store_boot_captured(
        monkeypatch, install, tmp_path):
    """Carried-forward regression, fix round 2.

    Round 1's version of this test discriminated on VALUE -- a distinctive
    "sdk" answer no fresh SettingsStore() could reproduce -- but
    engine.settings_store.SettingsStore is necessarily patched at the CLASS
    level (it's the only lever a test has over what boot's own `store is
    None` branch would build), so paths.resolve()'s OWN `store is None`
    branch -- exactly what FirstRunPanel._default_resolver hits -- reads
    the SAME patched class and reproduces any answer a correctly-threaded
    resolver gives. Value-based discrimination cannot work here: a review
    proved it with a standalone repro (a bare
    ``lambda picked: paths.resolve(argv=argv, env=env, picked=picked)``
    -- no store -- produced the identical result.sdk under that patch).

    What actually distinguishes a correctly-wired resolver is WHEN it
    captures its store, not what the store contains: bound ONCE, at
    _resolve_paths_or_report()'s own resolve() call, and never
    re-constructed afterwards. So this test captures the resolver, THEN
    changes what a fresh SettingsStore() would build, THEN calls the
    captured resolver -- a resolver closed over the already-built store
    object stays on the ORIGINAL answer regardless; a resolver that
    re-derives its store per call (dropped `resolver=` entirely, or bound
    with the weak/default-equivalent ``paths.resolve(picked=picked)`` form)
    picks up the CHANGED one instead.

    Fix round 3 -- order-dependent gate regression. This test drives the
    REAL _resolve_paths_or_report(), which reads the REAL sys.argv and
    os.environ (that is the whole point: it is checking what boot's own
    resolve() call captures). Under `scripts/check_tests.sh` the gate
    exports DAUNTLESS_GAME_DIR (see that script -- it derives the
    developer's real, VALID game root so the C++ asset tests can run) for
    the whole pytest subprocess. With that var set, the initial
    `_paths.resolve(argv=argv, env=env, store=store)` call inside
    _resolve_paths_or_report() resolves "game" from the environment all by
    itself, and combined with the patched store answering "sdk", the
    Resolution comes back already `ok=True` -- so `_run_first_run_screen`
    (and therefore this test's `fake_screen`) is never even called, and
    `captured["resolver"]` stays None. That is real leakage from the
    process environment, not a bug in the resolver-binding logic this test
    exists to pin -- so argv/env are pinned here explicitly rather than
    trusted to whatever the runner happened to export.
    """
    monkeypatch.setattr(_sys, "argv", ["dauntless"])
    monkeypatch.delenv("DAUNTLESS_GAME_DIR", raising=False)
    monkeypatch.delenv("DAUNTLESS_SDK_DIR", raising=False)
    game, sdk_at_capture = install
    sdk_after_capture = tmp_path / "other_install" / "sdk"  # paths-guard: test fixture tree
    (sdk_after_capture / "Build" / "scripts").mkdir(parents=True, exist_ok=True)
    (sdk_after_capture / "Build" / "scripts" / "App.py").write_text("")
    (sdk_after_capture / "Build" / "Data" / "TGL").mkdir(parents=True, exist_ok=True)

    class _StoreWithSdk:
        """Answers only ("paths", "sdk"), with whichever path it was built
        with -- never touches disk."""
        def __init__(self, sdk_path):
            self._sdk = str(sdk_path)

        def load(self):
            pass

        def has(self, section, key):
            return (section, key) == ("paths", "sdk")

        def get(self, section, key):
            assert (section, key) == ("paths", "sdk")
            return self._sdk

        def set(self, section, key, value):
            pass

    # Undo _nothing_resolves_by_accident's substitution: this test wants the
    # REAL resolve()/persist(), pointed only at the patched SettingsStore
    # class below, not a hardcoded fake one that would mask which store the
    # resolver actually used.
    monkeypatch.setattr(paths, "resolve", _REAL_RESOLVE)
    monkeypatch.setattr(paths, "persist", lambda resolution, store=None: None)
    monkeypatch.setattr(paths, "configure", lambda resolution: None)
    monkeypatch.setattr(_settings_store_mod, "SettingsStore",
                        lambda *a, **kw: _StoreWithSdk(sdk_at_capture))

    captured = {}

    def fake_screen(resolution, **kwargs):
        captured["resolver"] = kwargs.get("resolver")
        return resolution

    monkeypatch.setattr(host_loop, "_run_first_run_screen", fake_screen)

    host_loop._resolve_paths_or_report()

    resolver = captured.get("resolver")
    assert resolver is not None, (
        "_run_first_run_screen must be given a resolver -- a caller that "
        "drops the kwarg would leave FirstRunPanel to fall back to its own "
        "default, which re-derives a store per call instead of staying "
        "bound to boot's")

    # AFTER capture: change what a FRESH SettingsStore() would build. A
    # resolver correctly bound to the store boot already constructed must
    # not observe this -- only a re-defaulting one would.
    monkeypatch.setattr(_settings_store_mod, "SettingsStore",
                        lambda *a, **kw: _StoreWithSdk(sdk_after_capture))

    result = resolver({"game": str(game)})
    assert result.sdk == sdk_at_capture, (
        "the resolver picked up ambient state that changed AFTER it was "
        "captured -- it must stay bound to the store boot built ONCE at "
        "its own resolve() call, not re-derive a fresh one on every call")


def test_the_screen_suppresses_the_3d_scene_while_it_runs(monkeypatch):
    """No asset may load while the game root is unset, so the scene pass is
    off for the screen's whole lifetime and back on before boot continues.

    Comments stripped first (see _code_only): every inspect.getsource
    ordering assertion in this file must run through it, on the file's own
    policy -- a comment mentioning either call spelling would otherwise
    satisfy this without the real calls being in the right order.
    """
    import inspect
    from engine import host_loop
    source = _code_only(inspect.getsource(host_loop._run_first_run_screen))
    on_at = source.index("set_hologram_only_mode(True")
    off_at = source.index("set_hologram_only_mode(False")
    assert on_at < off_at, "the scene pass must be re-enabled after the screen"


def test_the_screen_pushes_its_first_payload_from_the_load_end_handler():
    """A push before the page's scripts have run is silently dropped in this
    project, which has caused real bugs. The screen's initial state must go
    out from the document-load handler, not at cef_initialize time.

    Anchored on the real REGISTRATION spelling (``_set_load_end(panel.
    invalidate)``), not just the bare call ``panel.invalidate()`` -- the
    bare call alone is satisfied by the pre-loop invalidate() that has
    always been there, even while CRITICAL 1 (nothing ever registers a
    load-end handler, so the pre-loop push is the ONLY push and it is
    dropped on frame 1 with nothing to re-trigger it) was fully live. A
    guard anchored only on the bare call therefore passed on broken code
    and its own failure message misled about what was actually missing.
    Comments stripped first (see tests.helpers.source_guards.code_only):
    the bare word "invalidate" also appears in this function's own
    explanatory comments, which would satisfy a looser assertion even with
    the real registration deleted.
    """
    import inspect
    from engine import host_loop
    source = _code_only(inspect.getsource(host_loop._run_first_run_screen))
    assert "_set_load_end(panel.invalidate)" in source, (
        "the load-end handler must be registered to call panel.invalidate() "
        "-- without it, the screen's first payload is pushed before the "
        "page's scripts have run, silently dropped, and nothing ever "
        "re-triggers a push because the panel's own snapshot never changes "
        "again on its own"
    )


def test_cef_comes_up_before_the_sdk_finder_is_installed():
    """The screen must exist before the roots are known, so CEF init has to
    precede _setup_sdk(). Verified on run()'s source rather than by booting
    a window, the same technique the neighbouring boot-order guards use.

    Anchored on the real spellings, not substrings that match something else
    one character in -- a guard in this family has already broken that way.
    Comments stripped first (see _code_only): a comment mentioning
    "r.init()" while explaining a LATER call broke this exact guard once
    already, silently, with no failing test to announce it.
    """
    import inspect
    from engine import host_loop
    source = _code_only(inspect.getsource(host_loop.run))
    init_at = source.index("r.init(")
    cef_at = source.index("r.cef_initialize(")
    resolve_at = source.index("_resolve_paths_or_report(")
    sdk_at = source.index("_setup_sdk()")
    assert init_at < cef_at < resolve_at < sdk_at, (
        "boot order must be: window, CEF, resolve, SDK -- the first-run "
        "screen needs a live browser before the roots are known, and the "
        "SDK meta-path finder needs the roots before it is installed"
    )
