"""TorpedoTube.Fire — discrete shot. Decrements _num_ready, stamps
_last_fire_time, auto-stops _firing.  Gated on (parent on AND _num_ready > 0).
"""
from engine.appc.math import TGPoint3
from engine.appc.subsystems import TorpedoTube, TorpedoSystem


def _loaded_tube(num_ready=1, max_ready=1):
    tube = TorpedoTube("Forward Torpedo 1")
    parent = TorpedoSystem("Torpedoes")
    parent.TurnOn()
    parent.AddChildSubsystem(tube)
    tube._max_ready = max_ready
    tube._num_ready = num_ready
    tube._reload_delay = 40.0
    return tube


class _AheadTarget:
    """A live target dead ahead of a default-oriented tube (Direction (0,1,0)),
    so Task 7's aim-resolve + +/-30 degree cone gate both pass — used by
    tests that only care about Fire's bookkeeping, not the gates themselves."""
    def GetWorldLocation(self): return TGPoint3(0.0, 100.0, 0.0)
    def IsDead(self): return 0


def test_can_fire_true_when_loaded_and_on():
    tube = _loaded_tube()
    assert tube.CanFire() == 1


def test_can_fire_false_when_empty():
    tube = _loaded_tube(num_ready=0)
    assert tube.CanFire() == 0


def test_can_fire_false_when_parent_off():
    tube = _loaded_tube()
    tube.GetParentSubsystem().TurnOff()
    assert tube.CanFire() == 0


def test_fire_decrements_num_ready():
    tube = _loaded_tube(num_ready=1)
    tube.Fire(target=None, offset=None)
    assert tube.GetNumReady() == 0


def test_fire_records_target():
    """Task 7: a targeted Fire only stamps _target/_target_offset once the
    aim-point resolve + cone both pass (a bare string has no world position
    to resolve, so it can no longer stand in for the target here)."""
    tube = _loaded_tube()
    target = _AheadTarget()
    tube.Fire(target=target, offset="hit_point")
    assert tube._target is target
    assert tube._target_offset == "hit_point"


def test_fire_with_none_target_succeeds():
    tube = _loaded_tube()
    tube.Fire(target=None, offset=None)
    assert tube.GetNumReady() == 0


def test_fire_auto_stops_firing():
    """Torpedoes are discrete-shot — _firing flips False immediately after
    the launch.  The parent WeaponSystem.IsFiring() unifies child firing
    state with the held trigger."""
    tube = _loaded_tube()
    tube.Fire(target=None, offset=None)
    assert tube.IsFiring() == 0


def test_fire_stamps_last_fire_time():
    """BC inits _last_fire_time to -1000.0, GAME time, not -inf
    (combat-and-damage.md:757) — see test_torpedo_tube_reload.py."""
    tube = _loaded_tube()
    assert tube.GetLastFireTime() == -1000.0
    tube.Fire(target=None, offset=None)
    assert tube.GetLastFireTime() > -1000.0


def test_fire_no_ops_when_empty():
    tube = _loaded_tube(num_ready=0)
    tube.Fire(target=None, offset=None)
    assert tube.GetNumReady() == 0  # no underflow
    assert tube.GetLastFireTime() == -1000.0  # no fire-time update


def test_fire_no_sfx_in_pr2a():
    """Torpedo SFX deferred to PR 2b (needs TorpedoAmmoType.GetLaunchSound).
    PR 2a Fire must not crash even with no SFX path wired."""
    tube = _loaded_tube()
    tube.Fire(target=None, offset=None)  # must not raise
    assert tube.GetNumReady() == 0


# ── PR 2b: spawn-path tests ────────────────────────────────────────────────
from unittest.mock import patch  # noqa: E402

import App  # noqa: E402
from engine.appc.projectiles import _active  # noqa: E402
from engine.appc.properties import WeaponSystemProperty  # noqa: E402


def _galaxy_tube_with_photon_script():
    """Set up a TorpedoTube parented to a TorpedoSystem with a PhotonTorpedo
    script bound at slot 0.  Returns (tube, parent_system, parent_ship)."""
    from engine.appc.ships import ShipClass_Create
    from engine.appc.subsystems import TorpedoSystem, TorpedoTube as _TT
    from engine.appc.math import TGPoint3
    ship = ShipClass_Create("Test")
    parent = TorpedoSystem("Torpedoes")
    parent.TurnOn()
    parent_prop = WeaponSystemProperty("Torpedoes")
    parent_prop.SetTorpedoScript(0, "Tactical.Projectiles.PhotonTorpedo")
    parent.SetProperty(parent_prop)
    ship._torpedo_system = parent
    # Wire parent_ship back-reference so _climb_to_ship works.
    parent._parent_ship = ship
    ship.SetWorldLocation(TGPoint3(0, 0, 0))
    tube = _TT("Forward Torpedo 1")
    tube._max_ready = 1
    tube._num_ready = 1
    tube._reload_delay = 40.0
    parent.AddChildSubsystem(tube)
    return tube, parent, ship


def test_fire_spawns_torpedo_with_script_visuals():
    _active.clear()
    tube, _, _ = _galaxy_tube_with_photon_script()
    with patch("engine.audio.tg_sound.TGSoundManager.instance"):
        tube.Fire(target=None, offset=None)
    assert len(_active) == 1
    torp = _active[-1]
    assert torp._core_texture.endswith("TorpedoCore.tga")
    assert torp._core_size_a == 0.2
    assert torp._damage == 500.0
    assert torp._guidance_lifetime == 6.0
    _active.clear()


def test_fire_dumbfires_when_no_target_lock():
    _active.clear()
    tube, _, ship = _galaxy_tube_with_photon_script()
    ship._target = None
    with patch("engine.audio.tg_sound.TGSoundManager.instance"):
        tube.Fire(target=None, offset=None)
    torp = _active[-1]
    assert torp._target_ship is None
    assert torp._velocity.Length() > 0.0
    _active.clear()


def test_fire_stamps_target_lock_but_launch_ignores_its_position():
    """BC-faithful launch (Task 6, audited §2.4.1): the target lock is still
    stamped onto the torpedo for guidance, but it never steers the launch
    velocity — that stays straight out the tube's authored (default,
    ship-forward) Direction, even though the target sits off to the side.

    Task 7: only a TARGETED Fire (target passed explicitly, and only once it
    clears the aim-resolve + +/-30 degree cone gates) stamps the homing
    state — mirrors the real dispatch path, where update_weapons passes the
    ship's locked target straight into Fire().  The target sits at bearing
    ~14 degrees (off-axis, inside the cone) so the gate passes but the
    launch-ignores-aim assertion below still has something to prove."""
    _active.clear()
    tube, _, ship = _galaxy_tube_with_photon_script()
    from engine.appc.math import TGPoint3
    class _Tgt:
        def GetWorldLocation(self): return TGPoint3(50, 200, 0)
        def IsDead(self): return 0
    ship._target = _Tgt()
    ship._target_subsystem = None
    with patch("engine.audio.tg_sound.TGSoundManager.instance"):
        assert tube.Fire(target=ship._target, offset=None) is True
    torp = _active[-1]
    assert torp._target_ship is ship._target
    assert torp._velocity.x == 0.0
    assert torp._velocity.y > 0.0
    _active.clear()


def test_fire_no_script_bound_silent_no_op():
    _active.clear()
    tube, parent, _ = _galaxy_tube_with_photon_script()
    parent.GetProperty()._torpedo_scripts.clear()
    initial_ready = tube.GetNumReady()
    with patch("engine.audio.tg_sound.TGSoundManager.instance"):
        tube.Fire(target=None, offset=None)
    # PR 2a behaviour: NumReady decremented.
    assert tube.GetNumReady() == initial_ready - 1
    # No torpedo spawned.
    assert len(_active) == 0
    _active.clear()


def test_fire_plays_launch_sound():
    """PlaySound(name) is BC-unfaithful and was the confirmed root cause of
    torpedo launch sounds pinning to the world origin (no node, no position
    -- see tests/audio/test_torpedo_launch_positional.py for the live-play
    regression test). Fire must instead mirror MissionLib.py's
    GetSound -> AttachToNode(torp.GetNode()) -> Play() sequence."""
    _active.clear()
    tube, _, _ = _galaxy_tube_with_photon_script()
    with patch("engine.audio.tg_sound.TGSoundManager.instance") as mock_mgr:
        mock_snd = mock_mgr.return_value.GetSound.return_value
        tube.Fire(target=None, offset=None)
        mock_mgr.return_value.GetSound.assert_called_with("Photon Torpedo")
        mock_mgr.return_value.PlaySound.assert_not_called()
        torp = _active[-1]
        mock_snd.AttachToNode.assert_called_once()
        (attached_node,), _kw = mock_snd.AttachToNode.call_args
        # The node isn't the SAME object as a fresh torp.GetNode() call (each
        # call mints a new weak _ObjectNodeRef) -- what matters is it
        # resolves to the torpedo's actual position, not the world origin.
        assert attached_node.GetWorldLocation() == torp.GetWorldLocation()
        mock_snd.Play.assert_called_once_with()
    _active.clear()
