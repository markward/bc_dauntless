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


def test_set_region_replaces_glow_setters_for_index():
    m = _module('''
def _x(find):
    p = find("A")
    if p is not None:
        p.SetRadius(0.5)
        p.SetGlowRegionShape(0, "Cylinder")
        p.SetGlowRegionAxis(0, 0.0, -1.0, 0.0)
        p.SetGlowRegionRadius(0, 0.25)
        p.SetGlowRegionExtent(0, 0.0, 2.0)
OVERRIDES = {"x": _x}
''')
    models = w.read_models(m)
    w.set_region(models, "x", "A", 0, [
        ("SetGlowRegionShape", (0, "Box")),
        ("SetGlowRegionPosition", (0, 1.0, 0.0, 0.0)),
        ("SetGlowRegionScale", (0, 0.5, 0.6, 0.7)),
    ])
    calls = models["x"]["A"]
    # SetRadius (non-glow) preserved; old cylinder glow setters gone.
    assert ("SetRadius", (0.5,)) in calls
    assert not any(s == "SetGlowRegionAxis" for s, a in calls)
    assert not any(s == "SetGlowRegionExtent" for s, a in calls)
    assert ("SetGlowRegionShape", (0, "Box")) in calls
    assert ("SetGlowRegionScale", (0, 0.5, 0.6, 0.7)) in calls


def test_set_region_leaves_other_indices_intact():
    m = _module('''
def _x(find):
    p = find("A")
    if p is not None:
        p.SetGlowRegionShape(0, "Sphere")
        p.SetGlowRegionRadius(0, 0.25)
        p.SetGlowRegionShape(1, "Sphere")
        p.SetGlowRegionRadius(1, 0.4)
OVERRIDES = {"x": _x}
''')
    models = w.read_models(m)
    w.set_region(models, "x", "A", 0, [("SetGlowRegionShape", (0, "Box")),
                                       ("SetGlowRegionScale", (0, 1.0, 1.0, 1.0))])
    calls = models["x"]["A"]
    assert ("SetGlowRegionShape", (1, "Sphere")) in calls   # index 1 untouched
    assert ("SetGlowRegionRadius", (1, 0.4)) in calls
    assert ("SetGlowRegionRadius", (0, 0.25)) not in calls   # index 0 replaced


def test_set_region_creates_absent_subsystem():
    m = _module('def _x(find):\n    return\nOVERRIDES = {"x": _x}\n')
    models = w.read_models(m)
    w.set_region(models, "x", "New", 0, [("SetGlowRegionShape", (0, "Sphere")),
                                         ("SetGlowRegionRadius", (0, 0.3))])
    assert models["x"]["New"] == [("SetGlowRegionShape", (0, "Sphere")),
                                  ("SetGlowRegionRadius", (0, 0.3))]


def test_set_region_result_round_trips():
    m = _module('def _x(find):\n    return\nOVERRIDES = {"x": _x}\n')
    models = w.read_models(m)
    w.set_region(models, "x", "A", 0, [("SetGlowRegionShape", (0, "Box")),
                                       ("SetGlowRegionScale", (0, 1.0, 2.0, 3.0))])
    text = w.emit(models)
    m2 = _module(text)
    assert w.read_models(m2) == models
    assert w.emit(w.read_models(m2)) == text


def test_set_region_empty_calls_clears_and_emit_drops_block():
    m = _module('''
def _x(find):
    p = find("A")
    if p is not None:
        p.SetGlowRegionShape(0, "Sphere")
        p.SetGlowRegionRadius(0, 0.25)
    p = find("B")
    if p is not None:
        p.SetRadius(0.5)
OVERRIDES = {"x": _x}
''')
    models = w.read_models(m)
    w.set_region(models, "x", "A", 0, [])          # remove A's only region
    text = w.emit(models)
    ast.parse(text)                                # valid python (no empty `if:` body)
    assert 'find("A")' not in text                 # A's block dropped entirely
    assert 'find("B")' in text                     # B preserved
    m2 = _module(text)
    assert w.read_models(m2) == {"x": {"B": [("SetRadius", (0.5,))]}}
    assert w.emit(w.read_models(m2)) == text        # canonical fixed point


def test_emit_all_empty_subsystems_emits_return():
    m = _module('''
def _x(find):
    p = find("A")
    if p is not None:
        p.SetGlowRegionShape(0, "Sphere")
OVERRIDES = {"x": _x}
''')
    models = w.read_models(m)
    w.set_region(models, "x", "A", 0, [])
    text = w.emit(models)
    ast.parse(text)
    m2 = _module(text)
    assert w.read_models(m2) == {"x": {}}           # empty function, still callable


def test_emitter_setters_are_index_keyed_and_full_replace():
    models = {}
    w.set_region(models, "galaxy", "Impulse", 0, [
        ("SetLightEmitterKind", (0, "point")),
        ("SetLightEmitterRadius", (0, 1.0)),
    ], prefix="SetLightEmitter")
    # Re-set index 0 => old emitter-0 setters cleared, new ones only.
    w.set_region(models, "galaxy", "Impulse", 0, [
        ("SetLightEmitterKind", (0, "cone")),
    ], prefix="SetLightEmitter")
    calls = dict((s, a) for (s, a) in models["galaxy"]["Impulse"])
    assert calls["SetLightEmitterKind"] == (0, "cone")
    assert "SetLightEmitterRadius" not in calls   # cleared by full-replace
    # Emit round-trips through ast.parse without error.
    text = w.emit(models)
    assert "SetLightEmitterKind" in text


def test_emitter_and_glow_prefixes_coexist_on_one_subsystem():
    models = {}
    w.set_region(models, "galaxy", "Impulse", 0, [("SetGlowRegionShape", (0, "Box"))])
    w.set_region(models, "galaxy", "Impulse", 0, [("SetLightEmitterKind", (0, "point"))],
                 prefix="SetLightEmitter")
    keys = set(s for (s, a) in models["galaxy"]["Impulse"])
    assert {"SetGlowRegionShape", "SetLightEmitterKind"} <= keys   # neither clobbers the other
