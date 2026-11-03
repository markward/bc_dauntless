"""Fire control's Python copy is gone (fire control native only, Task 6;
spec docs/superpowers/specs/2026-11-03-fire-control-native-only-design.md
M3, M6, M8.7; the DELETE list is
docs/reference/engine/native-combat/k1-retirement-map.md §1).

A source guard: none of the deleted Python decision code, hand-back
scaffolding or guards may come back. Read by parsing (definitions, not
mentions: a docstring may still cite a deleted name as history) and by
asking the built module. The SDK-facing methods KRM §1 marks KEEP (CanFire,
Fire, FireDumb, StartFiring, StopFiring ...) stay, as thin calls into the
native rule: the guard checks they reach native_combat and nothing else.
"""
import ast
from pathlib import Path

import pytest

try:
    import _dauntless_host as _h
except ImportError:
    _h = None

ROOT = Path(__file__).resolve().parents[2]
WS = ROOT / "engine" / "appc" / "weapon_subsystems.py"
NC = ROOT / "engine" / "appc" / "native_combat.py"
HL = ROOT / "engine" / "host_loop.py"
K1H = ROOT / "native/src/combat/include/dauntless/combat/k1_fire_control.h"
K1C = ROOT / "native/src/combat/src/k1_fire_control.cc"
K2C = ROOT / "native/src/combat/src/k2_beams.cc"
MIR_H = ROOT / "native/src/combat/include/dauntless/combat/mirror.h"
MIR_C = ROOT / "native/src/combat/src/mirror.cc"
HB = ROOT / "native/src/host/host_bindings.cc"


def _defined(path):
    """Every name defined in `path`: module-level defs, classes and
    assignments as "name", and class members as "Class.name"."""
    tree = ast.parse(path.read_text())
    out = set()

    def assigned(node):
        targets = (node.targets if isinstance(node, ast.Assign)
                   else [node.target])
        return [t.id for t in targets if isinstance(t, ast.Name)]

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            out.add(node.name)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            out.update(assigned(node))
        if isinstance(node, ast.ClassDef):
            for sub in node.body:
                if isinstance(sub, ast.FunctionDef):
                    out.add(node.name + "." + sub.name)
                elif isinstance(sub, (ast.Assign, ast.AnnAssign)):
                    out.update(node.name + "." + n for n in assigned(sub))
    return out


#: weapon_subsystems: the Python walk, its decisions and effects, its
#: launches (KRM §1.2).
_WS_GONE = (
    "WeaponSystem.update_weapons", "WeaponSystem.try_fire_weapon",
    "WeaponSystem._live_held_offset", "WeaponSystem._prune_targets",
    "WeaponSystem._resolve_working_group", "WeaponSystem._firing_weapon",
    "WeaponSystem._reseed_all_fire_timers", "WeaponSystem._fired_counter",
    "WeaponSystem._weapon_did_fire", "WeaponSystem.FIRE_TIMER_THRESHOLD",
    "_EnergyWeaponFireMixin._fire_decide",
    "_EnergyWeaponFireMixin._fire_effect",
    "_EnergyWeaponFireMixin._aim_in_arc",
    "_EnergyWeaponFireMixin._charge_gate",
    "PhaserBank._fire_effect",
    "PulseWeapon._fire_decide", "PulseWeapon._fire_effect",
    "PulseWeapon._charge_gate",
    "TorpedoTube._fire_decide", "TorpedoTube._fire_effect",
    "TorpedoTube._spawn_torpedo", "TorpedoTube._ammo_exhausted",
    "Weapon._python_fire_dumb",
    "_solve_pulse_launch_direction", "_resolve_torpedo_aim_point",
    "_in_torpedo_cone", "_emitter_forward_world", "_spawn_projectile",
    "_launch_reads", "_defer_spawn", "_dumb_firing",
)

#: native_combat: the guards, the walk check and launch check, the ASK
#: answers, RUN_PYTHON's driver, the test hook (KRM §1.4).
_NC_GONE = (
    "_K1_LEAF_METHODS", "_K1_SYSTEM_METHODS", "_K1_SYSTEM_PATCHES",
    "_K1_LEAF_PATCHES", "_K1_SHIP_PATCHES", "_K1_LAUNCH_FUNCS",
    "_k1_resolve", "k1_snapshot_stock", "_k1_raw", "k1_snapshot_ship",
    "_k1_send_walk_check", "_k1_overridden", "_k1_recheck_overrides",
    "_k1_overridden_by_type", "_k1_watch", "_k1_stock", "_k1_ship_stock",
    "_k1_walk_check_sent", "k1_snapshot_launch", "_k1_launch_funcs",
    "_k1_launch_funcs_names", "_k1_launch_check", "launch_patched",
    "learn_tube_launch", "_k1_decision", "_k1_pulse_module", "_k1_answer",
    "_K1Walk.walk_start", "use_python_fire_control_for_tests",
    "_python_fire_control", "_sdk_entry",
)

#: host_loop: the pump's Python loop body (KRM §1.3).
_HL_GONE = ("_pump_held_system", "_PUMP_GETTERS")


@pytest.mark.parametrize("path, gone", [(WS, _WS_GONE), (NC, _NC_GONE),
                                         (HL, _HL_GONE)],
                         ids=["weapon_subsystems", "native_combat",
                              "host_loop"])
def test_fire_control_python_retired(path, gone):
    """None of the deleted names is defined again."""
    back = sorted(set(gone) & _defined(path))
    assert back == [], "fire control's Python copy is back: %s" % back


def test_sdk_weapon_methods_are_thin_native_calls():
    """The SDK-facing methods KRM §1 keeps -- each kind's CanFire and Fire,
    Weapon.FireDumb -- are one call into native_combat, nothing else (no
    second copy of a rule behind them)."""
    tree = ast.parse(WS.read_text())
    want = {("_EnergyWeaponFireMixin", "CanFire"): "k1_can_fire",
            ("_EnergyWeaponFireMixin", "Fire"): "k1_fire",
            ("PulseWeapon", "CanFire"): "k1_can_fire",
            ("PulseWeapon", "Fire"): "k1_fire",
            ("TorpedoTube", "CanFire"): "k1_can_fire",
            ("TorpedoTube", "Fire"): "k1_fire",
            ("Weapon", "FireDumb"): "k1_dumb_fire"}
    seen = {}
    for cls in tree.body:
        if not isinstance(cls, ast.ClassDef):
            continue
        for fn in cls.body:
            key = (cls.name, getattr(fn, "name", None))
            if key not in want:
                continue
            body = [s for s in fn.body
                    if not (isinstance(s, ast.Expr)
                            and isinstance(s.value, ast.Constant))]
            assert len(body) == 1, key
            call = body[0].value
            assert isinstance(call, ast.Call), key
            assert isinstance(call.func, ast.Attribute), key
            assert call.func.attr == want[key], key
            assert ast.unparse(call.func.value) == "native_combat", key
            seen[key] = True
    assert set(seen) == set(want), sorted(set(want) - set(seen))


def test_the_kernel_has_no_python_hand_back():
    """The C++ side (KRM §1.5): K1 returns one record a session, DONE; no
    RUN_PYTHON, ASK, WALK_START, FIRE, FIRE_DUMB, BANK_STOP or STOP_SYSTEM
    record, no K1Why (a whole system to Python), no walk check, no launch
    check, no `k1_overridden` (K2's override guard read it: M8.7), no
    K1LaunchWhy::Patched, no K1_LAUNCH_PATCHED / K1_PULSE_MODULE_STALE."""
    h, cc = K1H.read_text(), K1C.read_text()
    for text, name in ((h, "k1_fire_control.h"), (cc, "k1_fire_control.cc")):
        for gone in ("enum class K1Why", "K1Why::", "RUN_PYTHON",
                     "K1Kind::ASK", "K1Kind::WALK_START", "K1Kind::FIRE",
                     "K1Kind::BANK_STOP", "K1Kind::STOP_SYSTEM",
                     "K1WalkCheck", "set_walk_check", "skip_walk",
                     "set_offset", "K1LaunchWhy::Patched",
                     "K1_LAUNCH_PATCHED", "K1_PULSE_MODULE_STALE",
                     "k1_overridden"):
            assert gone not in text, (name, gone)
    for path in (K2C, MIR_H, MIR_C):
        text = path.read_text()
        for gone in ("k1_overridden", "K1_LAUNCH_PATCHED",
                     "K1_PULSE_MODULE_STALE"):
            assert gone not in text, (path.name, gone)
    hb = HB.read_text()
    for gone in ("K1WalkCheckRefs", "K1Verdicts", "K1SessionCheck",
                 "k1_scan(", "k1_launch_recheck", "K1LaunchFunc",
                 "combat_k1_set_walk_check", "combat_k1_set_launch_check",
                 "combat_k1_set_pulse_modules", "combat_k1_answer",
                 "combat_k1_set_offset", "combat_k1_skip_walk"):
        assert gone not in hb, ("host_bindings.cc", gone)


@pytest.mark.skipif(_h is None or not hasattr(_h, "combat_k1_next"),
                    reason="native K1 bindings not built")
def test_the_built_module_has_no_python_hand_back():
    """The built module agrees (a stale .so would not)."""
    assert _h.combat_k1_kinds() == {"DONE": 0}
    for gone in ("combat_k1_set_walk_check", "combat_k1_set_launch_check",
                 "combat_k1_set_pulse_modules", "combat_k1_answer",
                 "combat_k1_set_offset", "combat_k1_skip_walk"):
        assert not hasattr(_h, gone), gone
    counts = _h.combat_k1_counts()
    for gone in ("k1_python_systems", "k1_python_reasons", "k1_asks",
                 "k1_fire_ask_reasons"):
        assert gone not in counts, gone
    assert "launch_patched" not in counts["k1_launch_reasons"]
    assert "k1_overridden" not in _h.combat_field_names()
