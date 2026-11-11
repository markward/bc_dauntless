"""Boot's path branch: prompt when unresolved, and degrade safely.

The fallback guard here is the most important test in the feature. If a
picker-less platform ever boots on unresolved paths, or loses the
describe_failure() diagnostic, nothing else in the suite would notice.
"""

import hashlib
import sys as _sys

import pytest

from engine import first_run, host_loop, paths, stock_scripts
from engine import settings_store as _settings_store_mod
from tests.helpers.source_guards import code_only as _code_only
from tests.helpers import host_frame_source

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


def _hash(data: bytes) -> str:
    return hashlib.blake2b(data, digest_size=16).hexdigest()


# A two-file stand-in for the committed stock manifest, so a fake install
# can pass (or fail) boot's stock-scripts check (engine.stock_scripts).
_FILES = {"MissionLib.pyc": b"missionlib", "AI/Preprocessors.pyc": b"preprocessors"}


@pytest.fixture(autouse=True)
def _small_manifest(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "cache_dir", lambda: tmp_path / "cache")
    stock_scripts.configure({rel: [_hash(data)] for rel, data in _FILES.items()}, None)
    yield
    stock_scripts.configure(None, None)


def _make_install(root, skip=()):
    for rel in ("data", "data/Models", "data/Textures", "data/Icons"):
        (root / rel).mkdir(parents=True, exist_ok=True)
    for rel, data in _FILES.items():
        if rel in skip:
            continue
        target = root / "scripts" / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    return root


@pytest.fixture
def install(tmp_path):
    """A game install that passes boot's stock-scripts check."""
    return _make_install(tmp_path / "install" / "game")   # paths-guard: test fixture tree


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


@pytest.fixture(autouse=True)
def _mods_scan_is_hermetic(monkeypatch, tmp_path):
    """Point the mods scan at an empty, per-test directory.

    Every test here drives the REAL _resolve_paths_or_report(), and on any
    path that reaches an ok Resolution that now includes a real call to
    mods.install() (Task 10's boot wiring). Without this fixture, that call
    resolves its mods root from real ambient argv/env exactly as boot does
    in production -- which is correct for boot, but means this file's tests
    perform a LIVE scan of whatever happens to sit in the developer's own
    mods/ directory (this worktree keeps a real reference mod there for
    Mark's manual verification) and their stderr output becomes
    machine-dependent: a passing/failing assertion here would depend on
    what mod content someone's checkout happens to have on disk. Discovered
    live via `pytest ... -v -s` printing "mods: aad-moerman-s-steamrunner:
    42 files..." from inside test_unresolved_paths_hand_off_to_the_first_
    run_screen, a test with nothing to do with mods.
    Setting DAUNTLESS_MODS_DIR to an empty tmp_path directory exercises the
    real mods.mods_root()/install() code path (env var precedence, same as
    a real --mods-dir launch) rather than stubbing it out -- a stub would
    also hide a future regression in that code.
    """
    monkeypatch.setenv("DAUNTLESS_MODS_DIR", str(tmp_path / "empty_mods"))


def test_unresolved_paths_hand_off_to_the_first_run_screen(monkeypatch, install):
    """When paths.resolve() comes back unresolved, _resolve_paths_or_report
    hands off to the first-run screen and boots on whatever it comes back
    with. The screen's own picker-driving mechanics -- prompting per row,
    skipping an already-resolved one, reporting what was wrong -- are
    FirstRunPanel's job and are covered at that layer
    (tests/unit/test_first_run_panel.py), plus end-to-end through the real
    pump loop (tests/host/test_first_run_pump_loop.py). This test is the WIRING:
    the screen is consulted on failure, and gets the unresolved Resolution.
    """
    game = install
    resolved = paths.resolve(argv=[], env={}, store=FakeStore(),
                              picked={"game": str(game)})
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


@pytest.mark.parametrize("cef_ready", [True, False])
def test_broken_install_reopens_the_first_run_screen(
        monkeypatch, capsys, tmp_path, _nothing_resolves_by_accident, cef_ready):
    """Spec §4.1a: boot runs the stock-scripts check. A root that resolves
    (its markers are all there) but is missing a listed .pyc is an install
    problem, so it goes back to the first-run screen, the row saying which
    file; with no live browser, describe_failure() names it and boot stops.
    """
    from engine.ui.first_run_panel import FirstRunPanel
    broken = _make_install(tmp_path / "broken" / "game",   # paths-guard: test fixture tree
                           skip=("AI/Preprocessors.pyc",))
    _nothing_resolves_by_accident.set("paths", "game", str(broken))
    seen = []

    def fake_screen(resolution, **kwargs):
        seen.append(resolution)
        return resolution          # the player quit without fixing it

    monkeypatch.setattr(host_loop, "_run_first_run_screen", fake_screen)

    result = host_loop._resolve_paths_or_report(cef_ready=cef_ready)

    assert result is None, "boot must not continue on a broken install"
    missing = "scripts/AI/Preprocessors.pyc"
    printed = capsys.readouterr().err
    assert missing in printed
    if not cef_ready:
        assert seen == []
        return
    assert len(seen) == 1
    handed = seen[0]
    assert handed.game is None and handed.source("game") == "settings"
    panel = FirstRunPanel(handed, picker=lambda title, message: None)
    row = panel._snapshot()["rows"][0]
    assert row["state"] == "bad"
    assert missing in row["hint"]


def test_the_screens_resolver_runs_the_install_check(
        monkeypatch, tmp_path):
    """The re-resolve after a pick goes through the same boot check, so a
    broken folder the screen re-resolves never comes back valid."""
    broken = _make_install(tmp_path / "broken" / "game",   # paths-guard: test fixture tree
                           skip=("AI/Preprocessors.pyc",))
    captured = {}

    def fake_screen(resolution, **kwargs):
        captured["resolver"] = kwargs.get("resolver")
        return resolution

    monkeypatch.setattr(host_loop, "_run_first_run_screen", fake_screen)
    host_loop._resolve_paths_or_report()
    again = captured["resolver"]({"game": str(broken)})
    assert again.game is None
    assert "scripts/AI/Preprocessors.pyc" in again.validation("game").hint


def test_a_root_picked_on_the_screen_is_persisted(
        monkeypatch, install, _nothing_resolves_by_accident):
    """FINDING 1's surviving half: a root the first-run screen located must
    reach the STORE, not just the in-memory Resolution, so the next launch
    does not ask again. (With one content root there is no longer a
    "partial" result: a valid game root is a complete one, and an invalid
    one has nothing to persist.) The screen itself is stubbed out here (its
    picker-driving mechanics are FirstRunPanel's job, covered in
    tests/unit/test_first_run_panel.py).
    """
    game = install
    fake_store = _nothing_resolves_by_accident

    # _nothing_resolves_by_accident stubs persist() to a no-op so the OTHER
    # tests in this file never touch a store. Reinstate the real
    # implementation for this one test, still pointed at the same
    # fake_store paths.resolve() already uses, so the assertion below
    # watches actual writes rather than an in-memory Resolution field.
    monkeypatch.setattr(
        paths, "persist",
        lambda resolution, store=None: _REAL_PERSIST(resolution, store=fake_store))

    picked = paths.resolve(argv=[], env={}, store=FakeStore(),
                            picked={"game": str(game)})
    assert picked.ok
    monkeypatch.setattr(host_loop, "_run_first_run_screen",
                         lambda resolution, **kwargs: picked)
    result = host_loop._resolve_paths_or_report()

    assert result is not None and result.ok
    assert fake_store.get("paths", "game") == str(game), (
        "the validated game root was never persisted -- the player will be "
        "asked for it again next launch")
    assert not fake_store.has("paths", "sdk"), (   # paths-guard: kind label
        "the game never writes an SDK root")


def test_the_screens_resolver_stays_bound_to_the_store_boot_captured(
        monkeypatch, install, tmp_path):
    """Carried-forward regression, fix round 2.

    engine.settings_store.SettingsStore is necessarily patched at the CLASS
    level (it's the only lever a test has over what boot's own `store is
    None` branch would build), so paths.resolve()'s OWN `store is None`
    branch -- exactly what FirstRunPanel._default_resolver hits -- reads
    the SAME patched class and reproduces any answer a correctly-threaded
    resolver gives. Value-based discrimination cannot work here.

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

    With one content root, the store boot captured names a BROKEN install
    (markers there, a listed stock file missing), which is what sends boot
    to the screen at all; the store a fresh SettingsStore() would build
    afterwards names a GOOD one. A correctly-bound resolver, asked with no
    pick, still reports the broken root.

    argv/env are pinned: this test drives the REAL _resolve_paths_or_report(),
    which reads the REAL sys.argv and os.environ, and a gate run exports
    DAUNTLESS_GAME_DIR for the whole pytest process -- that would resolve
    the root from the environment and never reach the screen.
    """
    monkeypatch.setattr(_sys, "argv", ["dauntless"])
    monkeypatch.delenv("DAUNTLESS_GAME_DIR", raising=False)
    good = install
    broken = _make_install(tmp_path / "broken" / "game",   # paths-guard: test fixture tree
                           skip=("AI/Preprocessors.pyc",))

    class _StoreWithGame:
        """Answers only ("paths", "game"), with whichever path it was built
        with -- never touches disk."""
        def __init__(self, game_path):
            self._game = str(game_path)

        def load(self):
            pass

        def has(self, section, key):
            return (section, key) == ("paths", "game")

        def get(self, section, key):
            assert (section, key) == ("paths", "game")
            return self._game

        def set(self, section, key, value):
            pass

    # Undo _nothing_resolves_by_accident's substitution: this test wants the
    # REAL resolve(), pointed only at the patched SettingsStore class below,
    # not a hardcoded fake one that would mask which store the resolver
    # actually used.
    monkeypatch.setattr(paths, "resolve", _REAL_RESOLVE)
    monkeypatch.setattr(paths, "persist", lambda resolution, store=None: None)
    monkeypatch.setattr(paths, "configure", lambda resolution: None)
    monkeypatch.setattr(_settings_store_mod, "SettingsStore",
                        lambda *a, **kw: _StoreWithGame(broken))

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
                        lambda *a, **kw: _StoreWithGame(good))

    result = resolver({})
    assert result.game is None
    assert result.validation("game").root == paths.normalise(broken), (
        "the resolver picked up ambient state that changed AFTER it was "
        "captured -- it must stay bound to the store boot built ONCE at "
        "its own resolve() call, not re-derive a fresh one on every call")


def test_the_screen_suppresses_the_3d_scene_while_it_runs(monkeypatch):
    """No asset may load while the game root is unset, so the scene pass is
    off for the screen's whole lifetime and back on before boot continues.

    This behaviour lives in the shared pump loop, `_run_preboot_panel`,
    since `_run_first_run_screen` is now a thin FirstRunPanel construction
    that delegates to it (Task 12's extraction).

    Comments stripped first (see _code_only): every inspect.getsource
    ordering assertion in this file must run through it, on the file's own
    policy -- a comment mentioning either call spelling would otherwise
    satisfy this without the real calls being in the right order.
    """
    import inspect
    from engine import host_loop
    source = _code_only(inspect.getsource(host_loop._run_preboot_panel))
    on_at = source.index("set_hologram_only_mode(True")
    off_at = source.index("set_hologram_only_mode(False")
    assert on_at < off_at, "the scene pass must be re-enabled after the screen"


def test_the_screen_pushes_its_first_payload_from_the_load_end_handler():
    """A push before the page's scripts have run is silently dropped in this
    project, which has caused real bugs. The screen's initial state must go
    out from the document-load handler, not at cef_initialize time.

    This behaviour lives in the shared pump loop, `_run_preboot_panel`,
    since `_run_first_run_screen` is now a thin FirstRunPanel construction
    that delegates to it (Task 12's extraction).

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
    source = _code_only(inspect.getsource(host_loop._run_preboot_panel))
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
    source = _code_only(host_frame_source.run_source())
    init_at = source.index("r.init(")
    cef_at = source.index("r.cef_initialize(")
    resolve_at = source.index("_resolve_paths_or_report(")
    sdk_at = source.index("_setup_sdk()")
    assert init_at < cef_at < resolve_at < sdk_at, (
        "boot order must be: window, CEF, resolve, SDK -- the first-run "
        "screen needs a live browser before the roots are known, and the "
        "SDK meta-path finder needs the roots before it is installed"
    )
