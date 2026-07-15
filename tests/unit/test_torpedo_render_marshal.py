"""_build_torpedo_render_data() marshals projectiles._active into the dict
shape host_io.set_torpedoes expects. Task 2 of the authentic-projectile-
visuals plan adds disruptor-bolt fields (id, is_disruptor, forward,
shell_color, bolt_core_color, bolt_length, bolt_width) to every descriptor —
BOTH torpedo-quad and disruptor-bolt families — because the C++ parser (Task
3) reads every key unconditionally. TORPEDO_BRIGHTNESS is re-baselined to 1.0
here (colors are now audit-authentic; dimming belongs to the glow-layer
alpha, not the marshal)."""
import App
import pytest

from engine.appc.projectiles import Torpedo, register
from engine.appc import projectiles
from engine.host_loop import (
    _build_torpedo_render_data, _color_tuple, PROJECT_ROOT, TORPEDO_BRIGHTNESS,
)


def _color(r, g, b, a=1.0):
    c = App.TGColorA()
    c.SetRGBA(r, g, b, a)
    return c


FULL_KEYS = {
    "position", "core_texture", "core_color", "core_size_a", "core_size_b",
    "glow_texture", "glow_color", "glow_size_a", "glow_size_b", "glow_size_c",
    "flares_texture", "flares_color", "num_flares", "flares_size_a",
    "flares_size_b", "age",
    "id", "is_disruptor", "forward", "shell_color", "bolt_core_color",
    "bolt_length", "bolt_width",
}


@pytest.fixture(autouse=True)
def clear_torpedo_registry():
    projectiles._active.clear()
    yield
    projectiles._active.clear()


def _make_photon():
    t = Torpedo()
    core_color = _color(1.0, 0.99, 0.39)
    glow_color = _color(1.0, 0.25, 0.0)
    t.CreateTorpedoModel(
        "data/Textures/Tactical/TorpedoCore.tga",   core_color, 0.2, 1.2,
        "data/Textures/Tactical/TorpedoGlow.tga",   glow_color, 3.0, 0.3, 0.6,
        "data/Textures/Tactical/TorpedoFlares.tga", glow_color, 8, 0.7, 0.4,
    )
    t._velocity = App.TGPoint3(3.0, 4.0, 0.0)
    register(t)
    return t, core_color, glow_color


def _make_disruptor():
    t = Torpedo()
    shell = _color(0.172549, 1.0, 0.172549)
    core = _color(0.639216, 1.0, 0.639216)
    t.CreateDisruptorModel(shell, core, 2.0, 0.2)
    # velocity left at __init__ default (0,0,0) to exercise the fallback.
    register(t)
    return t, shell, core


def test_torpedo_brightness_rebaselined_to_1_0():
    assert TORPEDO_BRIGHTNESS == 1.0


def test_all_descriptors_carry_the_full_key_set():
    _make_photon()
    _make_disruptor()
    out = _build_torpedo_render_data()
    assert len(out) == 2
    for entry in out:
        assert set(entry.keys()) == FULL_KEYS


def test_photon_entry_fields():
    t, core_color, glow_color = _make_photon()
    out = _build_torpedo_render_data()
    entry = out[0]

    assert entry["is_disruptor"] is False
    assert entry["id"] == t._id

    fx, fy, fz = entry["forward"]
    assert (fx, fy, fz) == pytest.approx((0.6, 0.8, 0.0))
    mag = (fx * fx + fy * fy + fz * fz) ** 0.5
    assert mag == pytest.approx(1.0)

    assert entry["core_texture"].startswith(str(PROJECT_ROOT / "game"))
    assert entry["core_texture"].endswith("TorpedoCore.tga")
    assert entry["glow_texture"].endswith("TorpedoGlow.tga")
    assert entry["flares_texture"].endswith("TorpedoFlares.tga")

    # TORPEDO_BRIGHTNESS is now 1.0 — colors round-trip undimmed.
    assert entry["core_color"] == pytest.approx(_color_tuple(core_color))
    assert entry["glow_color"] == pytest.approx(_color_tuple(glow_color))
    assert entry["flares_color"] == pytest.approx(_color_tuple(glow_color))

    # Disruptor-only fields still present, at their neutral defaults.
    assert entry["shell_color"] == pytest.approx((1.0, 1.0, 1.0, 1.0))
    assert entry["bolt_core_color"] == pytest.approx((1.0, 1.0, 1.0, 1.0))
    assert entry["bolt_length"] == 0.0
    assert entry["bolt_width"] == 0.0


def test_disruptor_entry_fields():
    t, shell, core = _make_disruptor()
    out = _build_torpedo_render_data()
    entry = out[0]

    assert entry["is_disruptor"] is True
    assert entry["id"] == t._id
    assert entry["bolt_length"] == 2.0
    assert entry["bolt_width"] == 0.2

    assert entry["shell_color"] == pytest.approx(_color_tuple(shell))
    assert entry["bolt_core_color"] == pytest.approx(_color_tuple(core))

    # Disruptors never touch the torpedo quad fields -> empty strings,
    # NOT prefixed with the game/ root (guard on falsy input).
    assert entry["core_texture"] == ""
    assert entry["glow_texture"] == ""
    assert entry["flares_texture"] == ""

    # Zero velocity -> fallback forward.
    assert entry["forward"] == pytest.approx((0.0, 0.0, 1.0))
