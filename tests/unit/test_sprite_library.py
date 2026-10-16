"""Sprite library: legacy paths -> Dauntless sprites (spec 2026-10-16 §7)."""
import pytest

from engine import sprites
from engine.appc import particles as P

NANO = "scripts/Custom/NanoFXv2/"


@pytest.fixture(autouse=True)
def _reset():
    sprites.reset()
    yield
    sprites.reset()


def test_alias_resolution_is_spelling_blind():
    a = sprites.resolve(NANO + "ExplosionFX/Gfx/Explosions/Exp_Nano3.tga")
    b = sprites.resolve("./scripts\\Custom\\NanoFXv2\\ExplosionFX\\Gfx\\Explosions\\Exp_Nano3.TGA")
    assert a is not None and a == b and a.sprite_id == "fireball"


def test_exact_beats_prefix():
    assert sprites.resolve(NANO + "ExplosionFX/Gfx/Explosions/Exp_Flare.tga").sprite_id == "fire_jet"


def test_missing_png_uses_fallback_runtime_fields(tmp_path, monkeypatch):
    (tmp_path / "manifest.json").write_text((sprites.sprites_root() / "manifest.json").read_text())
    (tmp_path / "legacy_aliases.json").write_text((sprites.sprites_root() / "legacy_aliases.json").read_text())
    monkeypatch.setattr(sprites, "sprites_root", lambda: tmp_path)
    ref = sprites.resolve(NANO + "ExplosionFX/Gfx/Explosions/Exp_Nano1.tga")
    assert ref.sprite_id == "fireball"
    assert ref.texture_path == "data/Textures/Effects/ExplosionA.tga"
    assert (ref.cols, ref.rows, ref.playback, ref.brightness) == (8, 8, "life_columns", 2.0)


def test_present_png_is_used(tmp_path, monkeypatch):
    (tmp_path / "manifest.json").write_text((sprites.sprites_root() / "manifest.json").read_text())
    (tmp_path / "legacy_aliases.json").write_text((sprites.sprites_root() / "legacy_aliases.json").read_text())
    (tmp_path / "fireball.png").write_bytes(b"png")
    monkeypatch.setattr(sprites, "sprites_root", lambda: tmp_path)
    ref = sprites.resolve(NANO + "ExplosionFX/Gfx/Explosions/Exp_Nano1.tga")
    assert ref.texture_path == str(tmp_path / "fireball.png")
    assert (ref.cols, ref.rows, ref.playback) == (8, 4, "life_sequence")


def test_native_and_none_kinds():
    assert sprites.resolve(NANO + "ExplosionFX/Gfx/NovaRing/Nova_Ring2a.tga").kind == "native"
    assert sprites.resolve(NANO + "SpecialFX/Gfx/Blinker/Blank.tga").kind == "none"


def test_stock_sheet_keeps_the_callers_path():
    ref = sprites.resolve("data/Textures/Effects/ExplosionB.tga")
    assert ref.texture_path == "data/Textures/Effects/ExplosionB.tga"
    assert (ref.cols, ref.rows) == (8, 8)


def test_fallback_only_stock_entries_do_not_match_callers():
    assert sprites.resolve("data/Textures/Effects/SunFlaresWhite.tga") is None
    assert sprites.resolve("data/rough.tga") is None


def test_unreadable_manifest_passes_paths_through(tmp_path, monkeypatch):
    (tmp_path / "manifest.json").write_text("{not json")
    monkeypatch.setattr(sprites, "sprites_root", lambda: tmp_path)
    assert sprites.resolve(NANO + "ExplosionFX/Gfx/Explosions/Exp_Nano1.tga") is None
    c = P.AnimTSParticleController_Create()
    c.CreateTarget("data/Textures/Effects/ExplosionA.tga")
    assert c._texture_path == "data/Textures/Effects/ExplosionA.tga"


def test_create_target_applies_library_fields():
    c = P.AnimTSParticleController_Create()
    c.CreateTarget(NANO + "SpecialFX/Gfx/Weapon/WeaponFlash.tga")
    assert c._library_kind == "sprite"
    assert c._size_scale in (0.6, 1.0)  # 0.6 once glint_burst.png exists, fallback otherwise
    c2 = P.AnimTSParticleController_Create()
    c2.CreateTarget(NANO + "ExplosionFX/Gfx/NovaRing/Nova_Ring2a.tga")
    assert c2._library_kind == "native" and c2._native["effect"] == "shockwave"
