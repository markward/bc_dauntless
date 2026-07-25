import ast
import types
import engine.appc.hardpoint_override_writer as w


def _module(src):
    m = types.ModuleType("fake_overrides")
    exec(compile(src, "<fake>", "exec"), m.__dict__)   # noqa: S102
    return m


_SRC = '''
def _galaxy(find):
    for name in ("Port Impulse", "Star Impulse"):
        p = find(name)
        if p is not None:
            p.SetGlowRegionShape(0, "Cylinder")
            p.SetGlowRegionRadius(0, 0.25)
    p = find("Center Impulse")
    if p is not None:
        p.SetGlowRegionRadius(0, 0.25)
        p.SetRadius(0.25)

OVERRIDES = {"galaxy": _galaxy}
'''


def test_read_models_captures_calls_per_subsystem():
    m = _module(_SRC)
    models = w.read_models(m)
    assert list(models) == ["galaxy"]
    g = models["galaxy"]
    # Loop expanded into two subsystems, each with its recorded calls.
    assert g["Port Impulse"] == [("SetGlowRegionShape", (0, "Cylinder")),
                                 ("SetGlowRegionRadius", (0, 0.25))]
    assert g["Star Impulse"] == [("SetGlowRegionShape", (0, "Cylinder")),
                                 ("SetGlowRegionRadius", (0, 0.25))]
    assert g["Center Impulse"] == [("SetGlowRegionRadius", (0, 0.25)),
                                   ("SetRadius", (0.25,))]


def test_set_setter_replaces_radius_not_duplicates():
    m = _module(_SRC)
    models = w.read_models(m)
    w.set_setter(models, "galaxy", "Center Impulse", "SetRadius", (0.5,))
    calls = models["galaxy"]["Center Impulse"]
    assert calls.count(("SetRadius", (0.5,))) == 1
    assert not any(s == "SetRadius" and a == (0.25,) for s, a in calls)
    # Glow untouched.
    assert ("SetGlowRegionRadius", (0, 0.25)) in calls


def test_set_setter_adds_block_when_subsystem_absent():
    m = _module(_SRC)
    models = w.read_models(m)
    w.set_setter(models, "galaxy", "Sensor Array", "SetRadius", (0.3,))
    assert models["galaxy"]["Sensor Array"] == [("SetRadius", (0.3,))]


def test_emit_round_trips_and_is_a_fixed_point():
    m = _module(_SRC)
    models = w.read_models(m)
    text = w.emit(models)
    ast.parse(text)                                   # valid python
    m2 = _module(text)
    assert w.read_models(m2) == models                # behavior preserved
    assert w.emit(w.read_models(m2)) == text          # deterministic fixed point


def test_emit_glow_index_distinguished_by_set_setter():
    m = _module('''
def _x(find):
    p = find("A")
    if p is not None:
        p.SetGlowRegionRadius(0, 0.1)
        p.SetGlowRegionRadius(1, 0.2)
OVERRIDES = {"x": _x}
''')
    models = w.read_models(m)
    w.set_setter(models, "x", "A", "SetGlowRegionRadius", (1, 0.9))  # edit index 1 only
    calls = models["x"]["A"]
    assert ("SetGlowRegionRadius", (0, 0.1)) in calls
    assert ("SetGlowRegionRadius", (1, 0.9)) in calls
    assert ("SetGlowRegionRadius", (1, 0.2)) not in calls
