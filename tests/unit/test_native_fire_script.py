"""FireScript's firing cycle, native for stock instances (phase 6 AI part 2,
Task 4).

The engine's FireScript wrapper (ai_optimized._non_lethal_class) runs a stock
instance's Update as ONE ``combat_ai_fire_update`` call: the SDK's
FireScript.Update (AI/Preprocessors.py:281-342) and every FireScript method it
reaches, statement for statement, with every side effect and every read it
does not mirror made as the same Python call in the same order, and only the
mirrored engine reads and the vector arithmetic native.

Pinned here, call by call: two scenes built identically from one seed (the
same scene twice: object ids differ, so everything is compared by name), one
driven through the SDK's Update (``DAUNTLESS_NATIVE_AI=0``) and one through the
native one, step by step under the same world changes. Each step compares the
PS_* code (or the exception), every recorded Python call the Update makes --
method, receiver, arguments, in order (sys.setprofile, filtered to the calls
both paths must make: side effects, callbacks, the RNG, scripts and the reads
the native code keeps in Python) -- the instance's whole __dict__, the RNG
streams and a world digest. The side effects are recording stand-ins on the
weapon objects, so a step changes nothing but what the Update itself writes.
Plus Review Focus 4 (a callback that removes the target mid-Update) and 5 (a
FireScript method patched after a native call)."""
import math
import random
import re
import sys
import types

import pytest

import App
import AI.Preprocessors as pp

from engine.appc import ai_native
from engine.appc import ai_optimized
from engine.appc import ai_sensor_gate
from engine.appc.ai import PreprocessingAI_Create
from engine.appc.math import TGMatrix3, TGPoint3
from engine.appc.objects import PhysicsObjectClass
from engine.appc.sets import SetClass
from engine.appc.ships import ShipClass
from engine.appc.subsystems import ShipSubsystem

try:
    import _dauntless_host as _h
except ImportError:
    _h = None

pytestmark = pytest.mark.skipif(_h is None, reason="native host not built")


def _reset_app_state():
    App.g_kSetManager._sets.clear()
    if hasattr(App.g_kEventManager, "_method_handlers"):
        App.g_kEventManager._method_handlers.clear()


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    monkeypatch.delenv("DAUNTLESS_NATIVE_AI", raising=False)
    _reset_app_state()
    ai_native.reset_stats()
    yield
    ai_sensor_gate.uninstall_ai_sensor_gate()
    _reset_app_state()


# ── Recording stand-ins for the side effects ────────────────────────────────

class _Holder:
    """What a stand-in method is bound to: the object it stands in on, and
    what it returns or does."""

    def __init__(self, receiver, ret=None, effect=None):
        self.receiver = receiver
        self.ret = ret
        self.effect = effect


def _stand_in(name):
    def f(self, *args):
        if self.effect is not None:
            return self.effect(*args)
        return self.ret() if callable(self.ret) else self.ret
    f.__code__ = f.__code__.replace(co_name=name)
    f.__name__ = f.__qualname__ = name
    return f


_STAND_INS = {n: _stand_in(n) for n in (
    "StartFiring", "StopFiringAtTarget", "SetPowerLevel", "SetMode",
    "SetAmmoType", "FireDumb", "GetMode", "IsFiring", "CallExternalFunction",
    "GetAllAIsInTree", "GetClassObjectList", "GetTargetID", "GetDamage",
    "GetLaunchSpeed")}


def _put(obj, name, ret=None, effect=None):
    setattr(obj, name, types.MethodType(_STAND_INS[name],
                                        _Holder(obj, ret, effect)))


# ── The call recorder ───────────────────────────────────────────────────────

#: Every call both paths must make, by name: the side effects, the FireScript
#: callbacks, the RNG and the torpedo scripts, and each read the native code
#: keeps in Python. The reads it mirrors (GetWorldLocation, GetWorldRotation,
#: GetVelocityTG, GetAccelerationTG, GetPredictedPosition, GetPositionTG,
#: GetDirection) and TGPoint3 / TGMatrix3 methods are not here: only the SDK
#: path calls them.
_RECORDED = frozenset({
    "StartFiring", "StopFiringAtTarget", "FireDumb", "SetPowerLevel",
    "SetMode", "SetAmmoType", "CallExternalFunction",
    "TargetVisible", "StopFiring", "ChooseTargetSubsystem", "ChooseTorpType",
    "GetRandomNumber", "import_module", "GetDamage", "GetTargetID",
    "GetShip", "GetContainingSet", "ObjectClass_GetObject", "GetAllAIsInTree",
    "TGProfilingInfo_StartTiming", "TGProfilingInfo_StopTiming",
    "TGObject_GetTGObjectPtr", "ShipSubsystem_Cast", "TorpedoSystem_Cast",
    "PhaserSystem_Cast", "TractorBeamSystem_Cast", "PulseWeaponSystem_Cast",
    "TorpedoTube_Cast", "PulseWeapon_Cast", "PhysicsObjectClass_Cast",
    "ShipClass_Cast", "ShouldBeAimed", "GetNumChildSubsystems",
    "GetChildSubsystem", "GetCurrentAmmoType", "GetLaunchSpeed", "GetProperty",
    "GetOrientationForward", "GetMode", "IsFiring",
    "GetImpulseEngineSubsystem", "GetCurMaxSpeed", "GetClassObjectList",
    "GetTorpedoScript", "GetCondition", "GetMaxCondition",
    "GetDisabledPercentage", "CalculateRoughDirection",
})


def _canon(v, depth=0):
    """A value by what it IS, never by id: objects by type and name."""
    if depth > 6:
        return ("deep",)
    if v is None or isinstance(v, (bool, str)):
        return v
    if isinstance(v, int):
        return ("i", v)
    if isinstance(v, float):
        return ("f", v.hex())
    if isinstance(v, TGPoint3):
        return ("pt", type(v).__name__,
                [_canon(getattr(v, c, None), depth + 1) for c in "xyz"])
    if isinstance(v, TGMatrix3):
        return ("mat", [_canon(e, depth + 1) for e in v.as_tuple()])
    if isinstance(v, (list, tuple)):
        return (type(v).__name__, [_canon(e, depth + 1) for e in v])
    if isinstance(v, dict):
        return ("dict", sorted((repr(_canon(k, depth + 1)),
                                _canon(e, depth + 1)) for k, e in v.items()))
    if isinstance(v, types.ModuleType):
        return ("mod", v.__name__)
    if isinstance(v, pp.FireScript):
        return ("self",)
    if isinstance(v, SetClass):
        return ("set",)             # the two builds' sets: one each
    if isinstance(v, ShipSubsystem):
        ship = v._climb_to_ship() if hasattr(v, "_climb_to_ship") else None
        return ("sub", type(v).__name__,
                ship.GetName() if ship is not None else None, v.GetName())
    if isinstance(v, _Holder):
        return ("holder", _canon(v.receiver, depth + 1))
    name = getattr(v, "GetName", None)
    if callable(name):
        try:
            return ("obj", type(v).__name__, name())
        except Exception:                       # noqa: BLE001 -- a label only
            pass
    return ("other", type(v).__name__)


def _canon_id(obj_id):
    """An object id by the object it names."""
    if obj_id is None:
        return None
    return ("id", _canon(App.TGObject_GetTGObjectPtr(obj_id)))


class _Recorder:
    def __init__(self):
        self.calls = []

    def __call__(self, frame, event, arg):
        if event != "call":
            return
        code = frame.f_code
        if code.co_name not in _RECORDED:
            return
        loc = frame.f_locals
        names = code.co_varnames[:code.co_argcount + code.co_kwonlyargcount]
        receiver = loc.get("self", "<fn>") if names and names[0] == "self" \
            else "<fn>"
        args = [loc.get(n) for n in names if n != "self"]
        if code.co_flags & 0x04:                 # *args
            args.extend(loc.get(code.co_varnames[len(names)], ()))
        if isinstance(receiver, _Holder):
            receiver = receiver.receiver
        if code.co_name == "TGObject_GetTGObjectPtr":
            args = [_canon_id(a) for a in args]
        elif code.co_name == "TGProfilingInfo_StopTiming":
            args = [("timing id",)]          # a process-wide counter
        else:
            args = [_canon(a) for a in args]
        self.calls.append((code.co_name, _canon(receiver), args))


def _outcome(fn):
    try:
        return ("ok", _canon(fn()))
    except Exception as exc:                     # noqa: BLE001 -- compared
        # A transform handle is a process-wide slot number: by shape only.
        return ("raise", type(exc).__name__,
                re.sub(r"\(\d+, \d+\)", "(slot)", str(exc)))


def _state(inst):
    out = {}
    for k, v in inst.__dict__.items():
        if k == "idTargetedSubsystem":
            out[k] = _canon_id(v)
        elif k == "dTargetSubsystemRating":
            out[k] = sorted((repr(_canon_id(i)), _canon(r))
                            for i, r in v.items())
        else:
            out[k] = _canon(v)
    return out


def _rng_state():
    return (App.g_kSystemWrapper._rng.getstate(), random.getstate())


def _set_rng_state(s):
    App.g_kSystemWrapper._rng.setstate(s[0])
    random.setstate(s[1])


# ── Scenes ──────────────────────────────────────────────────────────────────

class _FakeTorp:
    """An in-flight torpedo, as GetClassObjectList(CT_TORPEDO) lists one."""

    def __init__(self, name, target_id, damage):
        self._name = name
        self.target_id = target_id
        self.damage = damage
        _put(self, "GetTargetID", ret=lambda: self.target_id)
        _put(self, "GetDamage", ret=lambda: self.damage)

    def GetName(self):
        return self._name


class _AliasingShip(ShipClass):
    """A ship class whose GetWorldLocation hands out ONE cached TGPoint3:
    the SDK mutates it in place (vDiff.Subtract), so the native path must
    too. Not stock for the mirrored reader: read through Python."""

    def GetWorldLocation(self):
        p = self.__dict__.get("_cached_loc")
        if p is None:
            p = self.__dict__["_cached_loc"] = ShipClass.GetWorldLocation(self)
        return p


class _FakeAI:
    """A node of the AI tree that handles UsingWeaponType."""

    def __init__(self, name, effect):
        self._name = name
        _put(self, "CallExternalFunction", effect=effect)

    def GetName(self):
        return self._name


def _unit(rng):
    v = TGPoint3(*(rng.uniform(-1.0, 1.0) for _ in range(3)))
    if v.Length() < 1e-3:
        v = TGPoint3(0.0, 0.0, 1.0)
    v.Unitize()
    return v


class _Scene:
    """One build of scene `opt` (a dict), its objects named, never by id."""

    def __init__(self, tag, opt):
        import loadspacehelper
        self.opt = opt
        set_name = "Fire" + tag
        self.pSet = App.SetClass_Create()
        self.pSet.SetName(set_name)
        App.g_kSetManager._sets[set_name] = self.pSet
        self.ours = loadspacehelper.CreateShip(opt["ours"], self.pSet, "Ours",
                                               None, 0, 0)
        if opt["target"] == "placement":
            # Not a physics object: PhysicsObjectClass_Cast returns None.
            self.target = App.PlacementObject_Create("Target", set_name)
        else:
            self.target = loadspacehelper.CreateShip(opt["target"], self.pSet,
                                                     "Target", None, 0, 0)
        self.stale = False
        if opt.get("aliasing"):
            self.target.__class__ = _AliasingShip
        self.fs = pp.FireScript("Target", **opt.get("kw", {}))
        for key, value in opt.get("attrs", {}).items():
            setattr(self.fs, key, value)
        self.node = PreprocessingAI_Create(self.ours, "Fire")
        self.node.SetPreprocessingMethod(self.fs, "Update")
        self.inst = self.node.GetPreprocessingInstance()
        assert type(self.inst).__name__ == "FireScript_NonLethal"
        for getter in opt["weapons"]:
            system = getattr(self.ours, getter)()
            assert system is not None, (opt["ours"], getter)
            self.inst.AddWeaponSystem(system)
        if "tractor_mode" in opt:
            self.inst.AddTractorBeam(self.ours, opt["tractor_mode"])
        self.tractor_mode = [0]
        self.tractor_firing = [0]
        for system in self.inst.lWeapons:
            _put(system, "StartFiring", effect=self._start_firing)
            _put(system, "StopFiringAtTarget")
            _put(system, "SetPowerLevel")
            _put(system, "SetMode")
            _put(system, "SetAmmoType")
            _put(system, "GetMode", ret=lambda: self.tractor_mode[0])
            _put(system, "IsFiring", ret=lambda: self.tractor_firing[0])
            for i in range(system.GetNumChildSubsystems()):
                _put(system.GetChildSubsystem(i), "FireDumb")
        for getter in opt.get("aim", ()):
            getattr(self.ours, getter)().GetProperty().SetAimedWeapon(1)
        if opt.get("pulse_junk"):
            # A pulse child that is not a PulseWeapon: its cast is None.
            self.ours.GetPulseWeaponSystem().AddChildSubsystem(
                ShipSubsystem("Junk"))
        self.weapons0 = list(self.inst.lWeapons)
        self.torps = []
        if opt.get("torps_in_flight"):
            real = self.pSet.GetClassObjectList
            _put(self.pSet, "GetClassObjectList",
                 effect=lambda ct: list(self.torps) if ct == App.CT_TORPEDO
                 else real(ct))
        self.using = []
        if opt.get("using_weapon_type"):
            fake = _FakeAI("Listener", self._using_weapon_type)
            node = self.node
            _put(node, "GetAllAIsInTree", ret=lambda: [node, fake])
        self.launch = [None]
        if opt.get("launch_speeds"):
            ammo = self.ours.GetTorpedoSystem().GetCurrentAmmoType()
            real_speed = ammo.GetLaunchSpeed
            _put(ammo, "GetLaunchSpeed",
                 ret=lambda: real_speed() if self.launch[0] is None
                 else self.launch[0])
        self.started = 0

    # A side effect with an effect of its own (Review Focus 4).
    def _start_firing(self, target, offset):
        self.started += 1
        if self.opt.get("kill_on_start") and self.started == 1:
            self.pSet.RemoveObjectFromSet("Target")

    def _using_weapon_type(self, name, weapons):
        self.using.append(len(weapons))
        mode = self.opt["using_weapon_type"]
        if mode == "rotate" and len(self.inst.lWeapons) > 1:
            self.inst.lWeapons = self.inst.lWeapons[1:] + self.inst.lWeapons[:1]
        elif mode == "empty":
            self.inst.lWeapons = []
        elif mode == "kill":
            self.pSet.RemoveObjectFromSet("Target")
        elif mode == "stale":
            # The target's transform handle goes stale mid-Update: its next
            # GetWorldLocation raises StaleHandleError.
            index, generation = self.target._xform
            self.target._xform = (index, generation + 1)
            self.stale = True

    def perturb(self, rng):
        """One step's world change, from a step rng both builds share."""
        opt = self.opt
        if not self.inst.lWeapons:              # "empty" emptied it
            self.inst.lWeapons = list(self.weapons0)
        rng_range = opt.get("range", 150.0)
        dist = rng.uniform(0.2, 1.6) * (rng_range if rng_range < 1e6 else 150.0)
        direction = _unit(rng)
        if opt.get("ahead_or_behind"):
            direction = TGPoint3(0.0, rng.choice((1.0, -1.0)), 0.0)
        self.ours.SetTranslateXYZ(rng.uniform(-5, 5), rng.uniform(-5, 5),
                                  rng.uniform(-5, 5))
        if not opt.get("ahead_or_behind"):
            self.ours.SetAngleAxisRotation(rng.uniform(-math.pi, math.pi),
                                           _unit(rng))
        loc = self.ours.GetWorldLocation()
        place = (loc.x + direction.x * dist, loc.y + direction.y * dist,
                 loc.z + direction.z * dist)
        angle, axis = rng.uniform(-math.pi, math.pi), _unit(rng)
        velocity = TGPoint3(*(rng.uniform(-3, 3) for _ in range(3)))
        accel = tuple(rng.uniform(-0.5, 0.5) for _ in range(3))
        accel_mode = rng.choice(("tuple", "tuple", "none", "missing")) \
            if opt.get("accel_modes") else "tuple"
        if not self.stale:
            self.target.SetTranslateXYZ(*place)
            self.target.SetAngleAxisRotation(angle, axis)
        if isinstance(self.target, PhysicsObjectClass):
            self.target.SetVelocity(velocity)
            if accel_mode == "tuple":
                self.target.__dict__["_acceleration"] = accel
            elif accel_mode == "none":
                self.target.__dict__["_acceleration"] = None
            else:
                self.target.__dict__.pop("_acceleration", None)
        if opt.get("aliasing"):
            self.target.__dict__.pop("_cached_loc", None)
        if opt.get("visibility"):
            sen = self.ours.GetSensorSubsystem()
            sen.SetCondition(sen.GetMaxCondition()
                             if rng.random() < 0.6 else 0.0)
        if opt.get("toggle"):
            for key, values in opt["toggle"].items():
                if rng.random() < 0.3:
                    setattr(self.inst, key, rng.choice(values))
        self.tractor_mode[0] = rng.choice(
            (0, 0, App.TractorBeamSystem.TBS_DOCK_STAGE_1,
             App.TractorBeamSystem.TBS_DOCK_STAGE_2,
             App.TractorBeamSystem.TBS_DOCK_STAGE_2))
        self.tractor_firing[0] = rng.choice((0, 1))
        if opt.get("launch_speeds"):
            self.launch[0] = rng.choice(opt["launch_speeds"])
        if opt.get("torps_in_flight"):
            # Aimed at the target (counted), at us or at nothing (not).
            ids = (self.target.GetObjID(), self.target.GetObjID(),
                   self.ours.GetObjID(), -5)
            self.torps[:] = [
                _FakeTorp("T%d" % i, rng.choice(ids), rng.uniform(0.0, 400.0))
                for i in range(rng.randint(0, 3))]
            sub = self.target.GetSensorSubsystem()
            sub.SetCondition(rng.uniform(0.0, 1.0) * sub.GetMaxCondition())
        if opt.get("using_weapon_type") and rng.random() < 0.4:
            self.inst.bCallUsingWeaponTypeFunc = 1

    def digest(self):
        rows = []
        for ship in (self.ours, self.target):
            p = ship.__dict__.get("_cached_loc")
            rows.append((ship.GetName(), _canon(p),
                         self.pSet.GetObject(ship.GetName()) is not None))
        return (rows, self.started, list(self.using))


def _step_both(sdk, nat, step_rng_seed, monkeypatch):
    """One Update of each build under the same world change; returns the
    two (outcome, calls, state, rng, digest) records."""
    out = []
    rng0 = _rng_state()
    for scene, native in ((sdk, False), (nat, True)):
        scene.perturb(random.Random(step_rng_seed))
        _set_rng_state(rng0)
        if native:
            monkeypatch.delenv("DAUNTLESS_NATIVE_AI", raising=False)
        else:
            monkeypatch.setenv("DAUNTLESS_NATIVE_AI", "0")
        rec = _Recorder()
        sys.setprofile(rec)
        try:
            result = _outcome(lambda: scene.inst.Update(0.0))
        finally:
            sys.setprofile(None)
        out.append((result, rec.calls, _state(scene.inst),
                    _rng_state(), scene.digest()))
    monkeypatch.delenv("DAUNTLESS_NATIVE_AI", raising=False)
    return out


def _first_diff(a, b):
    for label, x, y in zip(("outcome", "calls", "state", "rng", "digest"),
                           a, b):
        if x != y:
            if label == "calls":
                for i, (cx, cy) in enumerate(zip(x, y)):
                    if cx != cy:
                        return "call %d: sdk %r / native %r" % (i, cx, cy)
                return "call count: sdk %d / native %d (next: %r)" % (
                    len(x), len(y), (x + y)[min(len(x), len(y))])
            if label == "state":
                keys = [k for k in set(x) | set(y) if x.get(k) != y.get(k)]
                return "state %r: sdk %r / native %r" % (
                    keys, [x.get(k) for k in keys], [y.get(k) for k in keys])
            return "%s: sdk %r / native %r" % (label, x, y)
    return None


_TBS1 = 4      # App.TractorBeamSystem.TBS_DOCK_STAGE_1 (checked below)

#: name -> scene options. Each scene is run for _STEPS updates per seed.
_SCENES = {
    # Phasers, torpedoes and a tractor in Dock Stage 1, a finite range (in
    # and out), HighPower on and off, the Dock Stage tractor exception.
    "mixed": dict(ours="Galaxy", target="Galaxy", range=150.0,
                  weapons=("GetPhaserSystem", "GetTorpedoSystem"),
                  tractor_mode=_TBS1, kw={"MaxFiringRange": 150.0},
                  accel_modes=True,
                  toggle={"bHighPower": (0, 1), "bEnabled": (1, 1, 1, 0),
                          "eTractorBeamMode": (_TBS1, _TBS1, 0, None)}),
    # A tractor alone, every mode against every wanted mode: the Dock Stage
    # exception's three legs each true and false.
    "tractor": dict(ours="Galaxy", target="Akira", range=1e20, weapons=(),
                    tractor_mode=_TBS1,
                    toggle={"eTractorBeamMode": (_TBS1, _TBS1, 0, None, 5)}),
    # Pulse weapons aimed (the pulse branch of GetWeaponInfo), torpedoes,
    # InaccurateTorps, the gate installed, our sensors on and off.
    "pulse_visibility": dict(ours="Warbird", target="BirdOfPrey",
                             range=1e20, gate=True, visibility=True,
                             weapons=("GetPulseWeaponSystem",
                                      "GetTorpedoSystem"),
                             aim=("GetPulseWeaponSystem",),
                             pulse_junk=True,
                             kw={"InaccurateTorps": 1}),
    # Dumb fire: tubes facing the target and facing away.
    "dumb_fire": dict(ours="Galaxy", target="Akira", range=1e20,
                      ahead_or_behind=True, weapons=("GetTorpedoSystem",),
                      kw={"DumbFireTorps": 1}),
    # DisableOnly: no subsystem left with bAttackIfNoSubsystemsLeft off, and
    # WeaponTooDangerous with in-flight torpedoes targeting the target.
    "disable_only": dict(ours="Galaxy", target="Galaxy", range=1e20,
                         torps_in_flight=True,
                         weapons=("GetTorpedoSystem", "GetPhaserSystem"),
                         kw={"DisableOnly": 1,
                             "TargetSubsystems": [(App.CT_SENSOR_SUBSYSTEM, 1)]},
                         # bAttackIfNoSubsystemsLeft is off (DisableOnly),
                         # and that return skips the cycle: without a nudge
                         # the counter never gets back to -1 (an SDK quirk).
                         toggle={"iLastUpdate": (-1, 0, 1),
                                 "idTargetedSubsystem": (None,)}),
    # No such subsystem on the target, firing without one switched off.
    "no_subsystem": dict(ours="Akira", target="BirdOfPrey", range=1e20,
                         weapons=("GetPhaserSystem", "GetTorpedoSystem"),
                         kw={"TargetSubsystems": [(App.CT_TRACTOR_BEAM_SYSTEM, 1)]},
                         attrs={"bAttackIfNoSubsystemsLeft": 0},
                         toggle={"iLastUpdate": (-1, 0)}),     # as above
    # ChooseSubsystemTargets (the RNG branch) and SmartTorpSelection
    # (ChooseTorpType, SetAmmoType) on a two-ammo Akira.
    "choose": dict(ours="Akira", target="Galaxy", range=1e20,
                   weapons=("GetTorpedoSystem", "GetPhaserSystem"),
                   kw={"ChooseSubsystemTargets": 1, "SmartTorpSelection": 1}),
    # The target a placement object (no physics: the cast is None); the
    # phasers aimed with no direction info (len(lDirections) == 0: fire).
    "placement_target": dict(ours="Galaxy", target="placement", range=1e20,
                             weapons=("GetTorpedoSystem", "GetPhaserSystem"),
                             aim=("GetPhaserSystem",)),
    # Dumb fire at a targeted subsystem (its GetWorldLocation, not the hull's).
    "dumb_fire_subsystem": dict(ours="Galaxy", target="Akira", range=1e20,
                                ahead_or_behind=True,
                                weapons=("GetTorpedoSystem",),
                                kw={"DumbFireTorps": 1, "TargetSubsystems":
                                    [(App.CT_SENSOR_SUBSYSTEM, 1)]}),
    # A UsingWeaponType handler that empties lWeapons (then: no weapons).
    "using_empty": dict(ours="Galaxy", target="Galaxy", range=1e20,
                        using_weapon_type="empty",
                        weapons=("GetPhaserSystem", "GetTorpedoSystem")),
    # A handler that leaves the target's transform handle stale mid-Update.
    "stale_handle": dict(ours="Galaxy", target="Galaxy", range=1e20,
                         using_weapon_type="stale",
                         weapons=("GetTorpedoSystem", "GetPhaserSystem")),
    # A UsingWeaponType handler in the tree that rotates lWeapons.
    "using_weapon_type": dict(ours="Galaxy", target="Galaxy", range=1e20,
                              using_weapon_type="rotate",
                              weapons=("GetPhaserSystem", "GetTorpedoSystem"),
                              tractor_mode=_TBS1),
    # A target class whose GetWorldLocation hands out one cached point (not
    # the mirrored reader: Python, mutated in place as the SDK mutates it).
    "aliasing": dict(ours="Galaxy", target="Galaxy", range=150.0,
                     aliasing=True, kw={"MaxFiringRange": 150.0},
                     weapons=("GetTorpedoSystem", "GetPhaserSystem")),
    # Values of other shapes: an int range, an int threshold, odd counters.
    "odd_values": dict(ours="Galaxy", target="Galaxy", range=150.0,
                       weapons=("GetTorpedoSystem", "GetPhaserSystem"),
                       attrs={"fMaxFiringRange": 150},
                       # A zero launch speed: `fDistance / fSpeed` raises.
                       launch_speeds=(None, None, 0.0, 0, 22.5, 3, -0.0),
                       toggle={"fFireDotThreshold": (0, 0.5, math.nan, 2),
                               "iLastUpdate": (-9, 7, -2, -1, 0, 1, True)}),
}

_STEPS = 60


@pytest.mark.parametrize("scene_name", sorted(_SCENES))
def test_native_fire_update_matches_the_sdk_call_by_call(scene_name,
                                                          monkeypatch):
    assert App.TractorBeamSystem.TBS_DOCK_STAGE_1 == _TBS1
    opt = _SCENES[scene_name]
    if opt.get("gate"):
        ai_sensor_gate.install_ai_sensor_gate()
    seed = sum(map(ord, scene_name))
    random.seed(seed)
    App.g_kSystemWrapper._rng.seed(seed)
    sdk = _Scene("A", opt)
    nat = _Scene("B", opt)
    seen_calls = set()
    raised = set()
    dock_exception = 0
    too_dangerous = [0, 0]           # [held fire, fired anyway]
    facts = set()
    for step in range(_STEPS):
        a, b = _step_both(sdk, nat, seed * 1000 + step, monkeypatch)
        diff = _first_diff(a, b)
        assert diff is None, "step %d of %s: %s" % (step, scene_name, diff)
        names = [c[0] for c in a[1]]
        seen_calls.update(names)
        if a[0][0] == "raise":
            raised.add(a[0][1])
        # The Dock Stage exception: IsFiring, GetMode == STAGE_2 and our
        # mode STAGE_1, so no SetMode follows.
        for i in range(len(names) - 1):
            if names[i] == "IsFiring" and names[i + 1] == "GetMode" and \
                    "SetMode" not in names[i + 2:i + 3]:
                dock_exception += 1
        calls = a[1]
        for i, (n, recv, args) in enumerate(calls):
            nxt = calls[i + 1][0] if i + 1 < len(calls) else None
            if n == "PulseWeapon_Cast" and args and args[0] and \
                    args[0][0] == "sub" and args[0][1] == "ShipSubsystem":
                facts.add("pulse cast failed")
            # An aimed phaser system: no directions, so straight to firing.
            if n == "PulseWeaponSystem_Cast" and args and args[0] and \
                    args[0][1] == "PhaserSystem" and nxt == "StartFiring":
                facts.add("aimed, no directions")
            if n == "PhysicsObjectClass_Cast":
                facts.add("physics target" if args[0][0] == "obj" and
                          args[0][1] != "PlacementObject" else "not physics")
        if "FireDumb" in names and a[2].get("idTargetedSubsystem"):
            facts.add("dumb fire at a subsystem")
        if a[0][0] == "ok" and a[2].get("lWeapons") == ("list", []):
            facts.add("weapons emptied")
        # WeaponTooDangerous' verdict: configuring goes on (the tractor
        # cast is next) only when it was not too dangerous.
        for i, n in enumerate(names):
            if n == "GetDisabledPercentage":
                nxt = names[i + 1] if i + 1 < len(names) else None
                too_dangerous[nxt == "TractorBeamSystem_Cast"] += 1
    stats = ai_native.stats()["fire"]
    # Every native-side step ran the native Update; the SDK side never did.
    assert stats["native"] == _STEPS, stats
    assert stats["reasons"] == {"switch": _STEPS}, stats
    if opt.get("aliasing"):
        assert stats["object_fallbacks"].get("surface", 0) > 0, stats
    else:
        assert stats["object_fallbacks"] == {}, stats
    # The scene reached what it is about.
    want = {
        "mixed": {"StartFiring", "SetPowerLevel", "SetMode",
                  "StopFiringAtTarget"},
        "tractor": {"SetMode", "IsFiring", "StartFiring"},
        "pulse_visibility": {"GetOrientationForward", "StopFiring",
                             "StartFiring"},
        "dumb_fire": {"FireDumb", "CalculateRoughDirection"},
        "disable_only": {"GetTargetID", "import_module", "StopFiring"},
        "no_subsystem": {"StopFiring", "ChooseTargetSubsystem"},
        "choose": {"GetRandomNumber", "ChooseTorpType", "StartFiring"},
        "using_weapon_type": {"CallExternalFunction", "StartFiring"},
        "aliasing": {"StartFiring"},
        "odd_values": {"StartFiring"},
        "placement_target": {"StartFiring"},
        "dumb_fire_subsystem": {"FireDumb"},
        "using_empty": {"CallExternalFunction"},
        "stale_handle": {"CallExternalFunction"},
    }[scene_name]
    assert want <= seen_calls, (want - seen_calls, sorted(seen_calls))
    if scene_name == "tractor":
        assert dock_exception > 0, "the Dock Stage exception never ran"
    want_facts = {
        "pulse_visibility": {"pulse cast failed"},
        "placement_target": {"aimed, no directions", "not physics"},
        "dumb_fire_subsystem": {"dumb fire at a subsystem"},
        "using_empty": {"weapons emptied"},
    }.get(scene_name, set())
    assert want_facts <= facts, (want_facts - facts, facts)
    if scene_name == "stale_handle":
        assert "StaleHandleError" in raised, raised
    if scene_name == "disable_only":
        assert too_dangerous[0] > 0 and too_dangerous[1] > 0, too_dangerous
    if scene_name == "odd_values":
        assert "ZeroDivisionError" in raised, raised


def test_a_target_destroyed_by_the_volley_mid_update(monkeypatch):
    """Review Focus 4. The first StartFiring removes the target from its set
    (in the middle of FireSystemAtTarget); a UsingWeaponType handler removes
    it before the Update reads anything else. Both paths make the same calls
    with the target they hold, and the next Update returns as the SDK's
    does."""
    for mode in ("kill_on_start", "kill_in_handler"):
        opt = dict(ours="Galaxy", target="Galaxy", range=1e20,
                   weapons=("GetTorpedoSystem", "GetPhaserSystem"))
        if mode == "kill_on_start":
            opt["kill_on_start"] = True
        else:
            opt["using_weapon_type"] = "kill"
        random.seed(7)
        sdk = _Scene("A", opt)
        nat = _Scene("B", opt)
        removed = False
        for step in range(12):
            a, b = _step_both(sdk, nat, 7000 + step, monkeypatch)
            diff = _first_diff(a, b)
            assert diff is None, "%s step %d: %s" % (mode, step, diff)
            removed = removed or not a[4][0][1][2]
            # A removed target stays removed (perturb moves it, never re-adds).
        assert removed, mode
        assert nat.pSet.GetObject("Target") is None
    assert ai_native.stats()["fire"]["native"] > 0


def test_a_patched_fire_system_at_target_runs_the_sdk_update(monkeypatch):
    """Review Focus 5. A mission patching FireScript.FireSystemAtTarget after
    native calls: the next Update is the SDK's, and runs the patch; putting
    the SDK's back makes it native again."""
    opt = dict(ours="Galaxy", target="Galaxy", range=1e20,
               weapons=("GetPhaserSystem",))
    scene = _Scene("A", opt)
    for _ in range(4):
        scene.perturb(random.Random(1))
        scene.inst.Update(0.0)
    assert ai_native.stats()["fire"]["native"] == 4
    hits = []
    original = pp.FireScript.FireSystemAtTarget

    def patched(self, *args):
        hits.append(args)
        return original(self, *args)
    monkeypatch.setattr(pp.FireScript, "FireSystemAtTarget", patched)
    for _ in range(4):
        scene.inst.Update(0.0)
    stats = ai_native.stats()["fire"]
    assert stats["native"] == 4 and stats["reasons"] == {"not_stock": 4}, stats
    assert hits, "the patched method never ran"
    monkeypatch.setattr(pp.FireScript, "FireSystemAtTarget", original)
    scene.inst.Update(0.0)
    assert ai_native.stats()["fire"]["native"] == 5


def test_an_instance_attribute_shadowing_a_method_runs_the_sdk_update():
    """An instance that shadows a FireScript method in its own dict is not
    stock: the SDK's Update, which calls the shadow."""
    scene = _Scene("A", dict(ours="Galaxy", target="Galaxy", range=1e20,
                             weapons=("GetPhaserSystem",)))
    called = []
    scene.inst.CheckGoodShot = lambda *a: called.append(a) or 1
    for _ in range(4):
        scene.perturb(random.Random(3))
        scene.inst.Update(0.0)
    stats = ai_native.stats()["fire"]
    assert stats["native"] == 0 and stats["reasons"] == {"not_stock": 4}, stats
    assert called


def test_the_wrapper_keeps_the_sdk_signature_and_the_native_entry_mark():
    """The driver's arity probe still sees (self, dEndTime); the override is
    marked so the stock gate checks the SDK base's Update instead."""
    import inspect
    scene = _Scene("A", dict(ours="Galaxy", target="Galaxy", range=1e20,
                             weapons=("GetPhaserSystem",)))
    upd = type(scene.inst).Update
    assert list(inspect.signature(upd).parameters) == ["self", "dEndTime"]
    assert getattr(upd, "_dauntless_native_entry", False) is True
    # AvoidObstacles' wrapper is not marked: only FireScript is native here.
    avoid = ai_optimized._non_lethal_class(pp.AvoidObstacles)
    assert not getattr(avoid.Update, "_dauntless_native_entry", False)


def test_a_bad_call_shape_raises_the_sdk_type_error():
    scene = _Scene("A", dict(ours="Galaxy", target="Galaxy", range=1e20,
                             weapons=("GetPhaserSystem",)))
    with pytest.raises(TypeError) as native_err:
        scene.inst.Update(0.0, 1.0)
    with pytest.raises(TypeError) as sdk_err:
        pp.FireScript.Update(scene.inst, 0.0, 1.0)
    assert str(native_err.value) == str(sdk_err.value)
    assert ai_native.stats()["fire"]["reasons"] == {"no_mirror": 1}


def _patch_point_subtract(mp):
    real = TGPoint3.Subtract
    mp.setattr(TGPoint3, "Subtract", lambda self, o: real(self, o))


def _patch_matrix_transpose(mp):
    real = TGMatrix3.Transpose
    mp.setattr(TGMatrix3, "Transpose", lambda self: real(self))


def _patch_objects_point(mp):
    from engine.appc import objects
    mp.setattr(objects, "TGPoint3", type("Other", (TGPoint3,), {}))


def _patch_module_len(mp):
    mp.setattr(pp, "len", len, raising=False)


def _patch_sqrt(mp):
    mp.setattr(math, "sqrt", lambda x: x ** 0.5)


@pytest.mark.parametrize("patch", [
    _patch_point_subtract, _patch_matrix_transpose, _patch_objects_point,
    _patch_module_len, _patch_sqrt])
def test_a_patched_engine_surface_runs_the_sdk_update(patch, monkeypatch):
    """What the native arithmetic reproduces -- the engine TGPoint3 /
    TGMatrix3 methods, the classes the mirrored bodies build, math.sqrt, the
    builtins the SDK body calls -- patched after a native call: the next
    Update is the SDK's; undone, native again."""
    scene = _Scene("A", dict(ours="Galaxy", target="Galaxy", range=1e20,
                             weapons=("GetPhaserSystem",)))
    scene.perturb(random.Random(2))
    scene.inst.Update(0.0)
    assert ai_native.stats()["fire"]["native"] == 1
    with monkeypatch.context() as mp:
        patch(mp)
        scene.inst.Update(0.0)
        assert ai_native.stats()["fire"]["reasons"] == {"not_stock": 1}
    scene.inst.Update(0.0)
    assert ai_native.stats()["fire"]["native"] == 2


# ── Boundary probes: the shipped comparisons, at their last bit ─────────────

def _fire_slot_outcome(scene, monkeypatch, native):
    """One Update in the fire slot of the scene's first weapon, target known
    visible: which of StartFiring / StopFiringAtTarget / TargetVisible ran."""
    inst = scene.inst
    inst.bTargetVisible = 1
    inst.iLastUpdate = 0
    inst.idTargetedSubsystem = None
    if native:
        monkeypatch.delenv("DAUNTLESS_NATIVE_AI", raising=False)
    else:
        monkeypatch.setenv("DAUNTLESS_NATIVE_AI", "0")
    rec = _Recorder()
    sys.setprofile(rec)
    try:
        inst.Update(0.0)
    finally:
        sys.setprofile(None)
    monkeypatch.delenv("DAUNTLESS_NATIVE_AI", raising=False)
    names = [c[0] for c in rec.calls]
    return [n for n in names
            if n in ("StartFiring", "StopFiringAtTarget", "TargetVisible")]


def test_the_fire_threshold_is_exact_at_its_last_bit(monkeypatch):
    """CheckGoodShot's `fDot >= self.fFireDotThreshold` on the native
    composite: the SDK's own best dot as the threshold fires, the next float
    up does not -- on both paths."""
    scene = _Scene("A", dict(ours="Galaxy", target="Galaxy", range=1e20,
                             weapons=("GetTorpedoSystem",)))
    scene.perturb(random.Random(11))
    inst = scene.inst
    system = inst.lWeapons[0]
    # The SDK's statements, with the SDK's methods (CheckGoodShot's tail).
    directions, speed = pp.FireScript.GetWeaponInfo(inst, system)
    assert directions
    v = pp.FireScript.PredictTargetLocation(inst, scene.target, None, speed)
    ship = inst.pCodeAI.GetShip()
    v.Subtract(ship.GetWorldLocation())
    v.MultMatrixLeft(ship.GetWorldRotation().Transpose())
    v.Unitize()
    best = max(v.Dot(d) for d in directions)
    for threshold, want in ((best, "StartFiring"),
                            (math.nextafter(best, math.inf),
                             "StopFiringAtTarget")):
        inst.fFireDotThreshold = threshold
        for native in (False, True):
            got = _fire_slot_outcome(scene, monkeypatch, native)
            assert got == [want], (threshold.hex(), native, got)
    assert ai_native.stats()["fire"]["native"] == 2


def test_the_firing_range_is_exact_at_its_last_bit(monkeypatch):
    """TargetInRange's `fSqrLength <= fMaxFiringRange ** 2` on the native
    composite: a squared distance of exactly 25 is in range at 5.0 and out
    at the next float down -- on both paths."""
    scene = _Scene("A", dict(ours="Galaxy", target="Galaxy", range=1e20,
                             weapons=("GetPhaserSystem",)))
    scene.perturb(random.Random(12))
    scene.ours.SetTranslateXYZ(0.0, 0.0, 0.0)
    scene.target.SetTranslateXYZ(3.0, 4.0, 0.0)
    for rng_, want in ((5.0, "StartFiring"),
                       (math.nextafter(5.0, 0.0), "TargetVisible")):
        scene.inst.fMaxFiringRange = rng_
        for native in (False, True):
            got = _fire_slot_outcome(scene, monkeypatch, native)
            assert got[:1] == [want], (rng_.hex(), native, got)
    assert ai_native.stats()["fire"]["native"] == 2
