"""Mirror the live ./build/dauntless launch path exactly: call
engine.host_loop._init_mission('Custom.Tutorial.Episode.M2Objects.M2Objects')
and tick the GameLoop. Check whether the AI subtree actually gets
attached and whether banks ever enter _firing.

User reports: even after Slices G/H/I/J, the live launch shows no
weapons fire while our isolated diagnostic
(test_galaxy_combat_fire_diagnostic) does. This test bridges that
gap by going through the same Initialize() path the live host uses.
"""
import App
import pytest


def _reset_app_state():
    App.g_kSetManager._sets.clear()
    if hasattr(App.g_kEventManager, "_method_handlers"):
        App.g_kEventManager._method_handlers.clear()
    App.g_kTimerManager._time = 0.0
    App.g_kRealtimeTimerManager._time = 0.0


@pytest.fixture(autouse=True)
def _isolate():
    _reset_app_state()
    yield
    _reset_app_state()


def _walk_banks(ship):
    sys_ = ship.GetPhaserSystem() if hasattr(ship, "GetPhaserSystem") else None
    if sys_ is None:
        return []
    return [sys_.GetWeapon(i) for i in range(sys_.GetNumWeapons())]


def test_m2objects_live_path_fires_phasers():
    from engine.host_loop import _init_mission
    from engine.core.loop import GameLoop

    mission, episode, game, mod = _init_mission(
        "Custom.Tutorial.Episode.M2Objects.M2Objects"
    )

    # Find Galaxy 1 and Galaxy 2 in any set.
    found = {}
    for pSet in App.g_kSetManager._sets.values():
        for obj in pSet._objects.values():
            name = getattr(obj, "_name", None) or (
                obj.GetName() if hasattr(obj, "GetName") else None
            )
            if name in ("Galaxy 1", "Galaxy 2", "player"):
                found[name] = obj
    print(f"\nShips found: {list(found.keys())}")
    print(f"Sets: {list(App.g_kSetManager._sets.keys())}")

    for nm, ship in found.items():
        ai = ship.GetAI() if hasattr(ship, "GetAI") else None
        print(f"  {nm}: AI={'attached' if ai is not None else 'NONE'} "
              f"phaser_banks={len(_walk_banks(ship))}")

    # Inspect AI tree state of each AI ship.
    from engine.appc.ai import PreprocessingAI
    print("\n--- AI tree inspection (initial) ---")
    for nm, ship in found.items():
        ai = ship.GetAI() if hasattr(ship, "GetAI") else None
        if ai is None:
            continue
        for node in ai.GetAllAIsInTree():
            if isinstance(node, PreprocessingAI):
                inst = node._preprocessing_instance
                if inst is None:
                    continue
                # FireScript
                if hasattr(inst, "lWeapons"):
                    print(f"  [{nm}] FireScript node={node.GetName()!r} "
                          f"sTarget={getattr(inst, 'sTarget', '?')!r}")
                # SelectTarget
                if hasattr(inst, "DamageEvent") and hasattr(inst, "pTargetGroup"):
                    pg = inst.pTargetGroup
                    names = pg.GetNameTuple() if hasattr(pg, "GetNameTuple") else "?"
                    print(f"  [{nm}] SelectTarget node={node.GetName()!r} "
                          f"target_names={names} "
                          f"sCurrentTarget={getattr(inst, 'sCurrentTarget', '?')!r}")

    # Check what set each ship is in + its position.
    for nm, ship in found.items():
        s = ship.GetContainingSet() if hasattr(ship, "GetContainingSet") else None
        sn = s.GetName() if s is not None and hasattr(s, "GetName") else "?"
        loc = ship.GetWorldLocation()
        print(f"  {nm} in set={sn}  pos=({loc.x:.1f}, {loc.y:.1f}, {loc.z:.1f})")

    loop = GameLoop()
    any_fired = False
    fire_log: list[tuple] = []
    print("\n--- Per-second motion + distance trace ---")
    for sec in range(1, 31):
        loop.advance(60)
        for nm, ship in found.items():
            for bank in _walk_banks(ship):
                if bank.IsFiring():
                    any_fired = True
                    fire_log.append((sec, nm, bank._name))
        g1 = found.get("Galaxy 1"); g2 = found.get("Galaxy 2")
        if g1 is not None and g2 is not None:
            la = g1.GetWorldLocation(); lb = g2.GetWorldLocation()
            dist = ((la.x - lb.x) ** 2 + (la.y - lb.y) ** 2 + (la.z - lb.z) ** 2) ** 0.5
            sp1 = g1.GetSpeedSetpoint(); sp2 = g2.GetSpeedSetpoint()
            print(f"  t={sec:2d}s  dist={dist:6.1f}  "
                  f"G1 sp={sp1[0] if sp1 else None} cs={g1._current_speed:.2f}  "
                  f"G2 sp={sp2[0] if sp2 else None} cs={g2._current_speed:.2f}")

    print("\n--- positions after ticking ---")
    for nm, ship in found.items():
        loc = ship.GetWorldLocation()
        sp = ship.GetSpeedSetpoint()
        cs = getattr(ship, "_current_speed", "?")
        print(f"  {nm}  pos=({loc.x:.1f}, {loc.y:.1f}, {loc.z:.1f})  "
              f"sp_setpoint={sp[0] if sp else None}  cur_speed={cs}")

    # Re-inspect FireScript state after ticking
    print("\n--- AI tree inspection (after 15s) ---")
    for nm, ship in found.items():
        ai = ship.GetAI() if hasattr(ship, "GetAI") else None
        if ai is None:
            continue
        for node in ai.GetAllAIsInTree():
            if isinstance(node, PreprocessingAI):
                inst = node._preprocessing_instance
                if inst is None or not hasattr(inst, "lWeapons"):
                    continue
                print(f"  [{nm}] FireScript node={node.GetName()!r}  "
                      f"sTarget={getattr(inst, 'sTarget', '?')!r}  "
                      f"bTargetVisible={getattr(inst, 'bTargetVisible', '?')}  "
                      f"iLastUpdate={getattr(inst, 'iLastUpdate', '?')}  "
                      f"preprocess_done={node._preprocess_done}  "
                      f"_fire_held={getattr(ship.GetPhaserSystem(), '_fire_held', '?')}")
    print(f"\nFire events in 15s: {len(fire_log)}")
    for t, nm, b in fire_log[:10]:
        print(f"  t={t}s {nm} {b} firing")
    print(f"ANY bank ever fired: {any_fired}")
    assert any_fired, "M2Objects via live path: phasers must fire within 15 s"
