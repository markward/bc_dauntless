"""ObjectClass.RandomOrientation (SDK App.py ObjectClass_RandomOrientation,
used by Systems/Multi1/Multi1.py on every asteroid) and the utopia-module
SetIgnoreClientIDForObjectCreation / IsIgnoreClientIDForObjectCreation pair."""
import App
from engine.appc.objects import ObjectClass


def _rows(m):
    t = m.as_tuple()
    return [t[0:3], t[3:6], t[6:9]]


def _det(r):
    return (r[0][0] * (r[1][1] * r[2][2] - r[1][2] * r[2][1])
            - r[0][1] * (r[1][0] * r[2][2] - r[1][2] * r[2][0])
            + r[0][2] * (r[1][0] * r[2][1] - r[1][1] * r[2][0]))


def test_random_orientation_is_a_proper_rotation():
    obj = ObjectClass()
    App.g_kSystemWrapper.SetRandomSeed(7)
    obj.RandomOrientation()
    r = _rows(obj.GetRotation())
    for i in range(3):
        for j in range(3):
            dot = sum(r[k][i] * r[k][j] for k in range(3))
            assert abs(dot - (1.0 if i == j else 0.0)) < 1e-6
    assert abs(_det(r) - 1.0) < 1e-6
    assert r != [(1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)]


def test_random_orientation_is_seeded_by_the_system_wrapper():
    a, b, c = ObjectClass(), ObjectClass(), ObjectClass()
    App.g_kSystemWrapper.SetRandomSeed(42)
    a.RandomOrientation()
    c.RandomOrientation()
    App.g_kSystemWrapper.SetRandomSeed(42)
    b.RandomOrientation()
    assert a.GetRotation().as_tuple() == b.GetRotation().as_tuple()
    assert a.GetRotation().as_tuple() != c.GetRotation().as_tuple()


def test_ignore_client_id_for_object_creation_is_stored():
    um = App.g_kUtopiaModule
    um.SetIgnoreClientIDForObjectCreation(0)
    try:
        assert um.IsIgnoreClientIDForObjectCreation() == 0
        um.SetIgnoreClientIDForObjectCreation(1)
        assert um.IsIgnoreClientIDForObjectCreation() == 1
    finally:
        um.SetIgnoreClientIDForObjectCreation(0)
