"""A SetPosition(x,y,z) override round-trips through the hardpoint writer.

The transform gizmo persists a subsystem's body-frame position as a 3-arg
SetPosition setter. The writer's canonical fixed point emit(read_models(m))==m
must hold with such an override present, and set_setter must replace a prior
SetPosition rather than appending a second one.

Note: the module fixture must define OVERRIDES (read_models iterates
module.OVERRIDES.items(), per engine/appc/hardpoint_override_writer.py:54) and
the "canonical fixed point" is expressed the same way the sibling suite
(tests/unit/test_hardpoint_override_writer.py::test_emit_round_trips_and_is_a_fixed_point)
expresses it: idempotence of emit(read_models(...)), not literal identity to
hand-typed source — emit() always wraps output in its own header/docstring/
OVERRIDES-dict format, so a bare hand-typed function body can never equal
emit()'s output verbatim.
"""
import types
from engine.appc import hardpoint_override_writer as w


def _module_with(source: str):
    m = types.ModuleType("hardpoint_overrides")
    exec(compile(source, "hardpoint_overrides", "exec"), m.__dict__)
    m.__source__ = source
    return m


SRC = (
    "def galaxy(find):\n"
    "    p = find('Center Impulse')\n"
    "    p.SetPosition(0.1, 2.3, -0.4)\n"
    "OVERRIDES = {'galaxy': galaxy}\n"
)


def test_setposition_is_canonical_fixed_point():
    m = _module_with(SRC)
    models = w.read_models(m)
    # The 3-arg SetPosition tuple survives read_models intact.
    assert models["galaxy"]["Center Impulse"] == [("SetPosition", (0.1, 2.3, -0.4))]
    text = w.emit(models)
    m2 = _module_with(text)
    assert w.read_models(m2) == models          # behavior preserved
    assert w.emit(w.read_models(m2)) == text     # deterministic fixed point


def test_set_setter_replaces_prior_setposition():
    m = _module_with(SRC)
    models = w.read_models(m)
    w.set_setter(models, "galaxy", "Center Impulse", "SetPosition", (9.0, 8.0, 7.0))
    out = w.emit(models)
    assert out.count("SetPosition") == 1
    assert "SetPosition(9.0, 8.0, 7.0)" in out
