"""icon_tracer is the shared TGA → SVG trace pipeline. weapon_icons +
damage_icons both call into it. Smoke-test the public surface so
moves between modules don't silently break either consumer."""
from engine.ui import icon_tracer


def test_icon_spec_exposed():
    spec = icon_tracer.IconSpec("X.tga", 0, 0, 16, 16)
    assert spec.tga == "X.tga"
    assert spec.w == 16


def test_transform_constants_exposed():
    assert icon_tracer.ROTATE_0 == 0
    assert icon_tracer.ROTATE_180 == 1
    assert icon_tracer.MIRROR_NONE == 0
    assert icon_tracer.MIRROR_HORIZONTAL == 1
    assert icon_tracer.MIRROR_VERTICAL == 2


def test_potrace_missing_error_class():
    assert issubclass(icon_tracer.PotraceMissingError, RuntimeError)


def test_wrap_with_inset_clip_idempotent():
    """Re-wrapping an SVG that already has a clipPath should be a no-op."""
    once = icon_tracer._wrap_with_inset_clip(
        '<svg><g><path d="M0,0 L1,1"/></g></svg>'
    )
    twice = icon_tracer._wrap_with_inset_clip(once)
    assert once == twice


def test_weapon_icons_reexports_from_tracer():
    """weapon_icons.py must keep the helpers available under the same
    names so any existing import path still works after the move."""
    from engine.ui import weapon_icons
    assert weapon_icons.IconSpec is icon_tracer.IconSpec
    assert weapon_icons._wrap_with_inset_clip is icon_tracer._wrap_with_inset_clip
