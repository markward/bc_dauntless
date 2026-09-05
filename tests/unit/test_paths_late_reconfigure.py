"""configure() twice must be observed by every consumer.

This is the guard for the rule that makes a first-run picker possible: the
picker runs AFTER CEF is up, so any module that captured a path at import
would still be pointing at the old install when the player picks a folder.

It is deliberately behavioural rather than structural -- the AST guard in
test_path_indirection.py checks the shape, this checks the effect.
"""
import importlib

import pytest

from engine import paths


@pytest.fixture(autouse=True)
def _restore_cache():
    before = paths.current() if paths._RESOLUTION is not None else None
    yield
    paths.configure(before)


def _point_at(root_pair):
    game, sdk = root_pair
    paths.configure(paths.resolve(
        argv=["--game-dir", str(game), "--sdk-dir", str(sdk)], env={}, store=None))


def _second_install(game):
    other = game.parent / "other-install"
    for rel in ("data", "data/Models", "data/Textures", "data/Icons"):
        (other / rel).mkdir(parents=True, exist_ok=True)
    return other


# Every engine/ site that used to be a module-level constant. There are
# EIGHT (not seven, and none of them was already exercised elsewhere): the
# four here each got a no-arg accessor (mirroring weapon_icons/ship_icons/
# damage_icons's _game_icons_dir()/_damage_dir()); name_resolver and
# lip_sync_runtime get their own dedicated tests below because their
# accessors either return a tuple (_tgl_roots) or take an argument
# (_abs_sfx) rather than fitting this parametrize's no-arg/str-contains
# shape.
CONSUMERS = [
    ("engine.ui.weapon_icons", "_game_icons_dir"),
    ("engine.ui.ship_icons", "_game_icons_dir"),
    ("engine.ui.damage_icons", "_damage_dir"),
    ("engine.dev_keybindings", "_test_character_nif"),
    ("engine.appc.viewscreen_static", "_effects_dir"),
    ("engine.appc.bridge_set", "_bridge_game_root"),
]


@pytest.mark.parametrize("module_name,func_name", CONSUMERS)
def test_path_accessors_follow_a_later_configure(fake_bc_install, module_name, func_name):
    game, sdk = fake_bc_install
    module = importlib.import_module(module_name)
    _point_at((game, sdk))
    first = str(getattr(module, func_name)())
    assert str(game) in first

    other = _second_install(game)
    _point_at((other, sdk))
    second = str(getattr(module, func_name)())
    assert str(other) in second
    assert first != second


def test_tgl_roots_follow_a_later_configure(fake_bc_install):
    """name_resolver held BOTH roots in one module-level tuple."""
    from engine.missions import name_resolver
    game, sdk = fake_bc_install
    _point_at((game, sdk))
    assert [str(r) for r in name_resolver._tgl_roots()] == [
        str(sdk / "Build" / "Data" / "TGL"), str(game / "data" / "TGL")]

    other = _second_install(game)
    _point_at((other, sdk))
    assert str(other / "data" / "TGL") in [str(r) for r in name_resolver._tgl_roots()]


def test_lip_sync_runtime_follows_a_later_configure(fake_bc_install):
    """_abs_sfx takes an argument, so it doesn't fit the no-arg CONSUMERS shape."""
    from engine.lip_sync_runtime import _abs_sfx
    game, sdk = fake_bc_install
    _point_at((game, sdk))
    assert str(game) in _abs_sfx("sfx/x.wav")

    other = _second_install(game)
    _point_at((other, sdk))
    assert str(other) in _abs_sfx("sfx/x.wav")


def test_tg_sound_follows_a_later_configure(fake_bc_install):
    from engine.audio import tg_sound
    game, sdk = fake_bc_install
    _point_at((game, sdk))
    assert str(game) in tg_sound._resolve_sfx_path("sfx/x.wav")

    other = _second_install(game)
    _point_at((other, sdk))
    assert str(other) in tg_sound._resolve_sfx_path("sfx/x.wav")


def test_no_engine_module_kept_the_old_env_var():
    """OPEN_STBC_GAME_DIR was a second env var doing engine.paths' job."""
    from engine.audio import tg_sound
    assert not hasattr(tg_sound, "_GAME_DIR_ENV")
