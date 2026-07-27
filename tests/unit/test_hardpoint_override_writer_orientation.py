"""A box SetGlowRegionOrientation override round-trips through the writer."""
import types
from engine.appc import hardpoint_override_writer as w


def _module_with(source):
    m = types.ModuleType("hardpoint_overrides")
    exec(compile(source, "hardpoint_overrides", "exec"), m.__dict__)
    return m


SRC = (
    "def galaxy(find):\n"
    "    p = find('Port Impulse')\n"
    "    p.SetGlowRegionShape(0, 'Box')\n"
    "    p.SetGlowRegionPosition(0, -1.22, -0.2, 0.32)\n"
    "    p.SetGlowRegionScale(0, 0.15, 0.2, 0.05)\n"
    "    p.SetGlowRegionOrientation(0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0)\n"
    "OVERRIDES = {'galaxy': galaxy}\n"
)


def test_orientation_is_canonical_fixed_point():
    models = w.read_models(_module_with(SRC))
    text = w.emit(models)
    assert w.emit(w.read_models(_module_with(text))) == text
    assert "SetGlowRegionOrientation(0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0)" in text
