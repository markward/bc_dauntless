"""Torpedo reload runs on GAME time, with one timer slot per MaxReady.

Model recovered from stbc.exe --
docs/original_game_reference/gameplay/combat-and-damage.md:740-830:

    last_fire_time   float, GAME time, init -1000.0
    reload_timers    float[], ONE SLOT PER MaxReady;  -1.0 == loaded
    CanFire          num_ready > 0  AND  gameTime - last_fire_time >= ImmediateDelay
    Fire             stamp last_fire_time = gameTime; num_ready--; start a slot cooling
    ReloadTorpedo    num_ready++; oldest cooling slot -> loaded

NOT time.monotonic(): wall time advances while the sim is paused, which made
every tube instantly reload on unpause.

NOT dt-integration: _advance_weapons runs once per RENDER frame with a constant
TICK_DT (host_loop.py:6054, :5525), so integrating dt would make reload
frame-rate dependent -- a Galaxy tube would reload in 20s on a 120Hz display.
"""
import pytest

import App
from engine.appc.subsystems import TorpedoSystem, TorpedoTube


@pytest.fixture
def clock():
    """Drive the game clock directly.  App.g_kUtopiaModule.GetGameTime() reads
    g_kTimerManager._time (App.py:1052), a pure accumulator."""
    App.g_kTimerManager._time = 0.0

    def _set(t: float) -> None:
        App.g_kTimerManager._time = float(t)

    yield _set
    App.g_kTimerManager._time = 0.0


def _tube(max_ready: int = 1, reload_delay: float = 40.0,
          immediate_delay: float = 0.25) -> TorpedoTube:
    system = TorpedoSystem("Torpedoes")
    system.TurnOn()
    tube = TorpedoTube("Forward Torpedo 1")
    tube._reload_delay = reload_delay
    tube._immediate_delay = immediate_delay
    tube._max_ready = max_ready
    tube._num_ready = max_ready
    tube._resize_slots()
    system.AddChildSubsystem(tube)
    return tube


def test_last_fire_time_inits_to_minus_1000(clock):
    """BC init value (combat-and-damage.md:757).  NOT -inf: -inf poisons any
    subtraction a caller might do."""
    assert _tube().GetLastFireTime() == -1000.0


def test_fresh_tube_can_fire_immediately(clock):
    """-1000.0 init means the ImmediateDelay gate is already satisfied at t=0."""
    clock(0.0)
    assert _tube().CanFire() == 1


def test_immediate_delay_gates_a_refire(clock):
    """gameTime - last_fire_time >= ImmediateDelay (combat-and-damage.md:824)."""
    tube = _tube(max_ready=2, immediate_delay=2.0)
    clock(100.0)
    tube.Fire()
    assert tube.GetNumReady() == 1           # still has a round chambered

    clock(101.0)                             # only 1.0s elapsed, gate is 2.0s
    assert tube.CanFire() == 0

    clock(102.0)                             # gate satisfied
    assert tube.CanFire() == 1


def test_reload_completes_after_reload_delay_of_game_time(clock):
    tube = _tube(reload_delay=40.0)
    clock(100.0)
    tube.Fire()
    assert tube.GetNumReady() == 0

    clock(139.0)
    tube.UpdateReload(0.0)
    assert tube.GetNumReady() == 0           # 39s -- not yet

    clock(140.0)
    tube.UpdateReload(0.0)
    assert tube.GetNumReady() == 1           # 40s -- reloaded


def test_pause_does_not_advance_reload(clock):
    """The bug this replaces: with time.monotonic(), pausing for 40s of WALL
    time instantly reloaded every tube.  Game time does not advance while
    paused, so a frozen clock must make no progress.

    Frame count: a dt-INTEGRATING implementation (self._accum += dt) would
    reload once total accumulated dt reaches ReloadDelay/dt = 40s / (1/60s)
    = 2400 frames.  100 frames (1.67s of dt) never exceeds that threshold
    either way, so it can't tell a game-clock implementation apart from a
    dt-integrating one -- both pass.  3000 frames (>2400, with margin) is
    the minimum that actually discriminates: a dt-integrating tube WOULD
    have reloaded by then, while a game-clock tube (frozen clock) must not.
    """
    tube = _tube(reload_delay=40.0)
    clock(100.0)
    tube.Fire()

    for _ in range(3000):                    # >40s worth of dt at 1/60s/frame
        tube.UpdateReload(1.0 / 60.0)        # clock frozen throughout (paused)
    assert tube.GetNumReady() == 0


def test_max_ready_two_reloads_slots_independently(clock):
    """warbird/keldon/galor/kessokmine ship MaxReady=2.  A single scalar
    last_fire_time cannot represent two slots cooling out of phase."""
    tube = _tube(max_ready=2, reload_delay=40.0, immediate_delay=0.25)
    clock(100.0)
    tube.Fire()                              # slot A starts cooling at t=100
    clock(110.0)
    tube.Fire()                              # slot B starts cooling at t=110
    assert tube.GetNumReady() == 0

    clock(140.0)
    tube.UpdateReload(0.0)
    assert tube.GetNumReady() == 1           # A done (40s), B has 10s to go

    clock(149.0)
    tube.UpdateReload(0.0)
    assert tube.GetNumReady() == 1           # B still not done

    clock(150.0)
    tube.UpdateReload(0.0)
    assert tube.GetNumReady() == 2           # B done


def test_reload_never_exceeds_max_ready(clock):
    tube = _tube(max_ready=1)
    clock(1000.0)
    for _ in range(5):
        tube.UpdateReload(0.0)
    assert tube.GetNumReady() == 1


def test_reloads_correctly_when_max_ready_set_without_resize_slots(clock):
    """_max_ready set directly, with NO _resize_slots() call -- exactly the
    pattern six existing test fixtures use (test_torpedo_tube_fire.py,
    test_torpedo_tube_power_gate.py, test_torpedo_spread_volley.py,
    test_weapon_config.py, test_weapon_tactical_commands.py,
    test_torpedo_ammo_selection.py).  Before the self-heal fix, Fire()
    would decrement _num_ready but stamp NO slot (the empty _reload_timers
    loop is a no-op), so UpdateReload found nothing cooling and the tube
    never reloaded again -- a silent, permanent brick with no exception.
    """
    system = TorpedoSystem("Torpedoes")
    system.TurnOn()
    tube = TorpedoTube("Forward Torpedo 1")
    tube._reload_delay = 40.0
    tube._immediate_delay = 0.25
    tube._max_ready = 1
    tube._num_ready = 1
    # Deliberately NOT calling tube._resize_slots() -- _reload_timers stays [].
    system.AddChildSubsystem(tube)

    clock(100.0)
    tube.Fire()
    assert tube.GetNumReady() == 0

    clock(140.0)                             # 40s of game time elapsed
    tube.UpdateReload(0.0)
    assert tube.GetNumReady() == 1           # self-healed and reloaded


def test_set_num_ready_zero_keeps_tube_reloadable(clock):
    """SetNumReady/IncNumReady/DecNumReady are real SDK surface (App.py:
    6018-6020) a mission can call directly, bypassing Fire().  Before the
    slot-sync fix, SetNumReady(0) left every slot LOADED (Fire never ran to
    put one into cooldown), so UpdateReload found nothing cooling and the
    tube never refilled -- a silent, permanent brick."""
    tube = _tube(max_ready=1, reload_delay=40.0)
    clock(100.0)
    tube.SetNumReady(0)
    assert tube.GetNumReady() == 0

    clock(140.0)                             # 40s of game time elapsed
    tube.UpdateReload(0.0)
    assert tube.GetNumReady() == 1           # slot was put into cooldown, now reloaded


def test_dec_num_ready_keeps_tube_reloadable(clock):
    """Same guarantee via DecNumReady on a MaxReady=2 tube: only the
    decremented slot should start cooling, the other stays loaded."""
    tube = _tube(max_ready=2, reload_delay=40.0)
    clock(100.0)
    tube.DecNumReady()
    assert tube.GetNumReady() == 1

    clock(140.0)
    tube.UpdateReload(0.0)
    assert tube.GetNumReady() == 2           # the decremented slot reloaded
