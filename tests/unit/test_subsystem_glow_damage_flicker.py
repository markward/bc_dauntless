"""Damage flicker: a subsystem that loses condition flickers its light volumes
for DAMAGE_FLICKER_SECS_PER_PERCENT seconds per 1% lost (1% -> 1 s,
10% -> 10 s), reusing the shader's disabled flicker (dim 0, flicker 1)."""

from engine.appc import subsystem_glow as sg


class _Point:
    def __init__(self, x, y, z): self._x, self._y, self._z = x, y, z
    def GetX(self): return self._x
    def GetY(self): return self._y
    def GetZ(self): return self._z


class _Pod:
    """Impulse pod with one baked cylinder region and a condition."""
    def __init__(self, condition=1.0):
        self.condition = condition
        self.disabled = self.destroyed = False
    def GetPosition(self): return _Point(0.0, -1.0, 0.0)
    def GetRadius(self): return 0.5
    def IsDisabled(self): return self.disabled
    def IsDestroyed(self): return self.destroyed
    def GetConditionPercentage(self): return self.condition
    def GetNumChildSubsystems(self): return 0
    def GetName(self): return "pod"
    def GetProperty(self):
        from engine.appc.properties import EngineProperty
        prop = EngineProperty("pod")
        prop.SetGlowRegionShape(0, "Cylinder")
        prop.SetGlowRegionAxis(0, 0.0, -1.0, 0.0)
        prop.SetGlowRegionRadius(0, 0.5)
        prop.SetGlowRegionExtent(0, 0.0, 2.0)
        return prop


class _Ship:
    def __init__(self, impulse): self._impulse = impulse
    def GetWarpEngineSubsystem(self): return None
    def GetImpulseEngineSubsystem(self): return self._impulse
    def GetSensorSubsystem(self): return None


class _Renderer:
    def __init__(self): self.dim_calls = []
    def add_cylinder_region(self, iid, center, axis, radius, length): return 0
    def set_glow_region_dim(self, iid, idx, dim_target, edge_time, flicker):
        self.dim_calls.append((dim_target, edge_time, flicker))
    def set_glow_region_gain(self, iid, idx, gain, gate_axis=(0.0, 0.0, 0.0)):
        pass


HEALTHY_PUSH = (1.0, -1.0, 0.0)


def _rig(condition=1.0):
    pod = _Pod(condition)
    rend = _Renderer()
    ctrl = sg.ShipGlowController(rend, instance_id=1, ship=_Ship(pod))
    ctrl.update(now=0.0)
    return pod, rend, ctrl


def test_flicker_seconds_scale_with_percent_lost():
    assert abs(sg.damage_flicker_secs(0.01) - 1.0) < 1e-9
    assert abs(sg.damage_flicker_secs(0.10) - 10.0) < 1e-9
    assert sg.damage_flicker_secs(0.0) == 0.0


def test_one_percent_hit_flickers_for_one_second():
    pod, rend, ctrl = _rig()
    assert rend.dim_calls[-1] == HEALTHY_PUSH
    pod.condition = 0.99
    ctrl.update(now=5.0)
    assert rend.dim_calls[-1] == (0.0, 5.0, 1.0)
    ctrl.update(now=5.9)
    assert rend.dim_calls[-1] == (0.0, 5.0, 1.0)
    ctrl.update(now=6.1)
    assert rend.dim_calls[-1] == HEALTHY_PUSH


def test_ten_percent_hit_flickers_for_ten_seconds():
    pod, rend, ctrl = _rig()
    pod.condition = 0.90
    ctrl.update(now=5.0)
    ctrl.update(now=14.9)
    assert rend.dim_calls[-1] == (0.0, 5.0, 1.0)
    ctrl.update(now=15.1)
    assert rend.dim_calls[-1] == HEALTHY_PUSH


def test_a_hit_during_a_flicker_adds_its_time_and_keeps_the_phase():
    pod, rend, ctrl = _rig()
    pod.condition = 0.95          # 5 s, until 10
    ctrl.update(now=5.0)
    pod.condition = 0.92          # +3 s, until 13
    ctrl.update(now=8.0)
    assert rend.dim_calls[-1] == (0.0, 5.0, 1.0)
    ctrl.update(now=12.9)
    assert rend.dim_calls[-1] == (0.0, 5.0, 1.0)
    ctrl.update(now=13.1)
    assert rend.dim_calls[-1] == HEALTHY_PUSH


def test_a_hit_after_the_flicker_ended_starts_a_new_one():
    pod, rend, ctrl = _rig()
    pod.condition = 0.99
    ctrl.update(now=5.0)
    ctrl.update(now=7.0)
    pod.condition = 0.97
    ctrl.update(now=20.0)
    assert rend.dim_calls[-1] == (0.0, 20.0, 1.0)
    ctrl.update(now=22.1)
    assert rend.dim_calls[-1] == HEALTHY_PUSH


def test_repair_does_not_flicker():
    pod, rend, ctrl = _rig(condition=0.5)
    pod.condition = 0.8
    ctrl.update(now=5.0)
    assert rend.dim_calls[-1] == HEALTHY_PUSH


def test_damage_present_at_spawn_does_not_flicker():
    pod, rend, ctrl = _rig(condition=0.3)
    assert rend.dim_calls[-1] == HEALTHY_PUSH
    ctrl.update(now=1.0)
    assert rend.dim_calls[-1] == HEALTHY_PUSH


def test_disabled_and_destroyed_states_win_over_the_damage_flicker():
    pod, rend, ctrl = _rig()
    pod.condition = 0.5           # 50 s of flicker
    pod.disabled = True
    ctrl.update(now=5.0)
    assert rend.dim_calls[-1] == (0.0, 5.0, 1.0)   # the disabled push
    pod.disabled, pod.destroyed = False, True
    ctrl.update(now=6.0)
    assert rend.dim_calls[-1] == (0.0, 6.0, 0.0)   # destroyed: blow out, off
