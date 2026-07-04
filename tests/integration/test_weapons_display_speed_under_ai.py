"""SPEED readout must reflect the ship's real velocity under a helm AI.

Live regression (E1M2): clicking Haven in Helm -> Orbit Planet turned,
in-system-warped, and orbited correctly, but the WeaponsDisplay header
stayed "Speed 0 : 0 kph" the whole time. Manual flight was unaffected.
Root cause (case b — panel plumbing, verified by running this file
against the pre-fix tree): _speed_label_for read the frozen
player_control._current_speed while a helm AI owned the ship (parked at
its handoff value, 0 from rest) even though ship.GetVelocity() carried
the real motion (630 GU/s warp cruise, 30-70 GU/s orbit). Fixed by
01cbd264 (player-control yields under AI; label reads the ship's
published velocity when GetAI() is non-None). These are the regression
guards that were missing when that fix landed.

The tests drive the real AI.Player.OrbitPlanet tree on the player and
read the speed label exactly the way the live panel does, at escalating
fidelity (direct SetAI -> in-system warp -> the full E1M2 helm-click /
MissionLib.SetPlayerAI path through WeaponsDisplayPanel._snapshot ->
QuickBattle boot + mission-picker swap). Each records a per-tick trace
of (GetAI installed, |GetVelocity()|, _current_speed, label) so a
failure names the broken link directly.

The core invariant: whenever a helm AI owns the ship and the ship's
published velocity is non-zero, the label's kph number equals
int(|GetVelocity()| * GUPS_TO_KPH) — never a frozen 0.
"""
import pytest

import App
from engine.core.loop import GameLoop
from engine.units import GUPS_TO_KPH

from tests.integration.test_orbit_planet_ai import (
    _reset_app_state,
    _ship_and_planet,
)


@pytest.fixture(autouse=True)
def _isolate():
    _reset_app_state()
    yield
    _reset_app_state()


def _vmag(ship) -> float:
    v = ship.GetVelocity()
    return (v.x * v.x + v.y * v.y + v.z * v.z) ** 0.5


def _kph_from_label(label: str) -> int:
    # "Speed {notch} : {kph} kph"
    return int(label.split(":")[1].split()[0])


def _trace_row(tick, ship, pc, label):
    return (tick, ship.GetAI() is not None, _vmag(ship),
            pc._current_speed, label)


def _format_trace(trace, every=10):
    rows = [t for i, t in enumerate(trace) if i % every == 0 or i == len(trace) - 1]
    return "\n".join(
        "tick=%d ai=%s |v|=%.4f _current_speed=%.4f label=%r" % t for t in rows
    )


def _assert_label_tracks_velocity(trace):
    """The case-(b) detector: at every recorded tick where the AI owns the
    ship, the label must show exactly the ship's published velocity."""
    mismatches = [
        t for t in trace
        if t[1] and _kph_from_label(t[4]) != int(abs(t[2]) * GUPS_TO_KPH)
    ]
    assert not mismatches, (
        "speed label diverged from ship velocity under AI:\n"
        + _format_trace(mismatches, every=1)
        + "\nfull trace:\n" + _format_trace(trace)
    )


def _drive(ship, pc, ticks, *, read_label):
    """Run GameLoop + the per-frame player-control pass like the live host
    loop (panel reads BEFORE loop.tick, matching host_loop's frame order),
    recording the speed trace each tick."""
    from engine.host_loop import _NO_INPUT

    loop = GameLoop()
    trace = []
    for i in range(ticks):
        trace.append(_trace_row(i, ship, pc, read_label()))
        loop.tick()
        pc.apply(ship, 1.0 / 60.0, _NO_INPUT)
    return trace


# ── 1. In-range orbit, AI installed via direct ship.SetAI ───────────────


def test_speed_label_nonzero_during_in_range_orbit():
    from engine.host_loop import _PlayerControl
    from engine.ui.weapons_display_panel import _speed_label_for

    pSet, ship, haven = _ship_and_planet(distance=350.0)   # inside 400 gate
    import AI.Player.OrbitPlanet
    ship.SetAI(AI.Player.OrbitPlanet.CreateAI(ship, haven))

    pc = _PlayerControl()
    trace = _drive(ship, pc, 240,
                   read_label=lambda: _speed_label_for(ship, pc))

    # Case-(a) detector: the orbit must genuinely translate the ship.
    peak = max(t[2] for t in trace)
    assert peak > 0.01, (
        "ship never gained real velocity under the orbit AI (case a):\n"
        + _format_trace(trace))
    _assert_label_tracks_velocity(trace)
    # And the headline symptom: while moving, the label is not 0 kph.
    moving = [t for t in trace if t[2] * GUPS_TO_KPH >= 1.0]
    assert moving and all(_kph_from_label(t[4]) > 0 for t in moving), (
        "label stayed 0 kph while the ship was moving:\n" + _format_trace(trace))


# ── 2. Far start: turn -> in-system warp transit -> orbit ───────────────


def test_speed_label_tracks_in_system_warp_transit():
    from engine.host_loop import _PlayerControl
    from engine.ui.weapons_display_panel import _speed_label_for

    pSet, ship, haven = _ship_and_planet(distance=5000.0)  # outside 400 gate
    import AI.Player.OrbitPlanet
    ship.SetAI(AI.Player.OrbitPlanet.CreateAI(ship, haven))

    pc = _PlayerControl()
    trace = _drive(ship, pc, 300,
                   read_label=lambda: _speed_label_for(ship, pc))

    _assert_label_tracks_velocity(trace)
    # The warp cruise publishes a large velocity — the label must show it.
    peak_tick = max(trace, key=lambda t: t[2])
    assert peak_tick[2] > 100.0, (
        "no warp-cruise velocity ever published:\n" + _format_trace(trace))
    assert _kph_from_label(peak_tick[4]) > 0, (
        "label read 0 kph during warp cruise:\n" + _format_trace(trace))


# ── 3. Full-fidelity live path: E1M2 helm click -> panel snapshot ───────


def test_e1m2_helm_click_speed_label_via_panel_snapshot():
    """The exact live chain: real E1M2 mission, real Helm -> Orbit Planet
    button (MissionLib.SetPlayerAI), real WeaponsDisplayPanel snapshot
    (which fetches the player itself via Game_GetCurrentGame().GetPlayer())."""
    from engine import host_loop
    from engine.host_loop import _PlayerControl
    from engine.ui.weapons_display_panel import (
        WeaponsDisplayPanel,
        _get_player,
    )
    from tests.integration.test_e1m2_orbit_haven import (
        E1M2_MODULE,
        _find_orbit_menu_and_haven_button,
    )
    from tests.integration.test_sdk_bridge_load import _fresh_world

    _fresh_world()
    mission, episode, game, mod = host_loop._init_mission(E1M2_MODULE)

    import MissionLib
    player = MissionLib.GetPlayer()
    pSet = App.g_kSetManager.GetSet("Vesuvi6")
    haven = pSet.GetObject("Haven")
    loc = haven.GetWorldLocation()
    player.SetTranslateXYZ(loc.x, loc.y + haven.GetRadius() + 100.0, loc.z)
    mod.g_bMissionWinCalled = 1

    orbit_menu, haven_button = _find_orbit_menu_and_haven_button(haven)
    App.g_kEventManager.AddEvent(haven_button._event)
    assert player.GetAI() is not None, "helm click did not install the orbit AI"

    # The panel must resolve the SAME ship the helm handler put the AI on.
    panel_player = _get_player()
    assert panel_player is player, (
        "panel resolves a different player object than MissionLib: "
        "panel=%r missionlib=%r" % (panel_player, player))

    pc = _PlayerControl()
    panel = WeaponsDisplayPanel(player_control=pc)
    trace = _drive(player, pc, 240,
                   read_label=lambda: panel._snapshot()[2])

    peak = max(t[2] for t in trace)
    assert peak > 0.01, (
        "player never gained real velocity under the E1M2 orbit AI (case a):\n"
        + _format_trace(trace))
    _assert_label_tracks_velocity(trace)
    moving = [t for t in trace if t[2] * GUPS_TO_KPH >= 1.0]
    assert moving and all(_kph_from_label(t[4]) > 0 for t in moving), (
        "panel label stayed 0 kph while the ship was moving:\n"
        + _format_trace(trace))


# ── 3b. E1M2 far start: the exact reported live flow ────────────────────


def test_e1m2_far_helm_click_turn_warp_orbit_label():
    """The reported live scenario end-to-end: player at E1M2's real start
    position (far from Haven), helm click -> turn, in-system warp transit,
    then orbit — the label must track the ship's velocity through ALL
    phases, never sitting at 0 kph while the ship moves."""
    from engine import host_loop
    from engine.host_loop import _PlayerControl
    from engine.ui.weapons_display_panel import WeaponsDisplayPanel
    from tests.integration.test_e1m2_orbit_haven import (
        E1M2_MODULE,
        _find_orbit_menu_and_haven_button,
    )
    from tests.integration.test_sdk_bridge_load import _fresh_world

    _fresh_world()
    mission, episode, game, mod = host_loop._init_mission(E1M2_MODULE)

    import MissionLib
    player = MissionLib.GetPlayer()
    pSet = App.g_kSetManager.GetSet("Vesuvi6")
    haven = pSet.GetObject("Haven")
    # Park the player well outside the orbit gate (200 + planet radius) so
    # the click takes the full live flow: turn -> in-system warp -> orbit.
    loc = haven.GetWorldLocation()
    player.SetTranslateXYZ(loc.x, loc.y + 5000.0, loc.z)
    mod.g_bMissionWinCalled = 1

    orbit_menu, haven_button = _find_orbit_menu_and_haven_button(haven)
    App.g_kEventManager.AddEvent(haven_button._event)
    assert player.GetAI() is not None

    pc = _PlayerControl()
    panel = WeaponsDisplayPanel(player_control=pc)
    trace = _drive(player, pc, 900,
                   read_label=lambda: panel._snapshot()[2])

    _assert_label_tracks_velocity(trace)
    peak_tick = max(trace, key=lambda t: t[2])
    assert peak_tick[2] > 100.0, (
        "no in-system-warp velocity ever published on the real E1M2 player:\n"
        + _format_trace(trace))
    moving = [t for t in trace if t[2] * GUPS_TO_KPH >= 1.0]
    assert moving and all(_kph_from_label(t[4]) > 0 for t in moving), (
        "panel label stayed 0 kph while the ship was moving:\n"
        + _format_trace(trace))


# ── 3c. Boot QuickBattle -> mission-picker swap -> helm click ────────────


def test_qb_boot_swap_to_e1m2_orbit_label(monkeypatch):
    """The complete live session shape: boot into QuickBattle, fly frames
    with the persistent _PlayerControl, swap to E1M2 via HostController
    (the dev mission-picker path), then click Haven. The panel and the
    control survive the swap — exactly the state leak surface the live
    client has. pc.apply is fed controller.session.player like the live
    frame loop; the panel resolves its own player."""
    pytest.importorskip("_dauntless_host")
    from tests.host.test_quickbattle_boot import (
        _FakeRenderer,
        _fresh_quickbattle_loader,
    )
    from engine.host_loop import _PlayerControl, _NO_INPUT
    from engine.ui.weapons_display_panel import WeaponsDisplayPanel

    hl, controller = _fresh_quickbattle_loader(monkeypatch)
    monkeypatch.setattr(hl, "_planet_nif_path", lambda planet, **k: "fake.nif")
    controller.session = controller.loader.load_quickbattle()

    pc = _PlayerControl()
    panel = WeaponsDisplayPanel(player_control=pc)
    loop = GameLoop()

    # A stretch of ordinary QB frames so pc/panel accumulate real state.
    for _ in range(60):
        panel.render_payload()
        loop.tick()
        qb_player = controller.session.player
        if qb_player is not None:
            pc.apply(qb_player, 1.0 / 60.0, _NO_INPUT)

    # Dev mission picker: swap to E1M2.
    controller.swap_mission("Maelstrom.Episode1.E1M2.E1M2")
    controller._drain_pending_swap()
    assert controller.session is not None, "E1M2 swap failed"

    import MissionLib
    import sys
    player = MissionLib.GetPlayer()
    assert player is not None
    mod = sys.modules["Maelstrom.Episode1.E1M2.E1M2"]
    pSet = App.g_kSetManager.GetSet("Vesuvi6")
    haven = pSet.GetObject("Haven")
    loc = haven.GetWorldLocation()
    player.SetTranslateXYZ(loc.x, loc.y + 5000.0, loc.z)
    mod.g_bMissionWinCalled = 1

    from tests.integration.test_e1m2_orbit_haven import (
        _find_orbit_menu_and_haven_button,
    )
    orbit_menu, haven_button = _find_orbit_menu_and_haven_button(haven)
    App.g_kEventManager.AddEvent(haven_button._event)
    assert player.GetAI() is not None

    trace = []
    for i in range(900):
        label = panel._snapshot()[2]
        # The live frame loop drives pc with session.player, not the
        # Game player — keep that split so an identity mismatch between
        # the two would surface here.
        drive_ship = controller.session.player
        if drive_ship is None:
            drive_ship = player
        trace.append(_trace_row(i, player, pc, label))
        loop.tick()
        pc.apply(drive_ship, 1.0 / 60.0, _NO_INPUT)

    _assert_label_tracks_velocity(trace)
    peak = max(t[2] for t in trace)
    assert peak > 100.0, (
        "no warp velocity after QB->E1M2 swap:\n" + _format_trace(trace))
    moving = [t for t in trace if t[2] * GUPS_TO_KPH >= 1.0]
    assert moving and all(_kph_from_label(t[4]) > 0 for t in moving), (
        "panel label stayed 0 kph while the ship was moving (post-swap):\n"
        + _format_trace(trace))


# ── 4. Manual flight: readout source and format are unchanged ───────────


def test_manual_flight_label_reads_player_control_state():
    """No AI installed: the label reads _PlayerControl's integrated state
    (impulse notch + _current_speed), exactly as before this fix. Pins the
    manual-flight readout byte-identical."""
    from engine.host_loop import _PlayerControl
    from engine.ui.weapons_display_panel import _speed_label_for

    pSet, ship, haven = _ship_and_planet(distance=350.0)
    assert ship.GetAI() is None

    pc = _PlayerControl()
    pc.impulse_level = 5
    pc._current_speed = 60.0
    expected = "Speed 5 : " + str(int(60.0 * GUPS_TO_KPH)) + " kph"
    assert _speed_label_for(ship, pc) == expected

    # Reverse throttle shows R, magnitude still from _current_speed.
    pc.impulse_level = -2
    pc._current_speed = -20.0
    expected = "Speed R : " + str(int(20.0 * GUPS_TO_KPH)) + " kph"
    assert _speed_label_for(ship, pc) == expected
