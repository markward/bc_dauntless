"""WeaponsDisplay panel snapshot + payload tests.

WeaponsDisplay is the bottom-right player-only panel mirroring
``sdk/Build/scripts/Tactical/Interface/WeaponsDisplay.py``: a ship
silhouette with the player's phaser-arc icons rendered above and
below it, and phaser-field indicator overlays that light up while
each bank fires. No target version — this panel is always the
player's own loadout.
"""
import json

import pytest

import App
import loadspacehelper

from engine.core.game import Game, _set_current_game
from engine.ui.weapons_display_panel import (
    WeaponsDisplayPanel,
    _resolve_icon_descriptors,
    _speed_label_for,
)


class _FakePlayerControl:
    """Stand-in for _PlayerControl with just the fields _speed_label_for
    consumes. The panel reads ``impulse_level`` (0-9 throttle notch) +
    ``_current_speed`` (integrated GU/s)."""
    def __init__(self, impulse_level=0, current_speed_gups=0.0):
        self.impulse_level = impulse_level
        self._current_speed = current_speed_gups


@pytest.fixture(autouse=True)
def reset_global_state():
    """The panel snapshot reads ``Game_GetCurrentGame().GetPlayer()``;
    other test modules in this suite mutate that module-global. Clear
    before AND after each test so we run isolated and don't leak a
    Galaxy into the next test's setup."""
    _set_current_game(None)
    App.g_kSetManager._sets.clear()
    yield
    _set_current_game(None)
    App.g_kSetManager._sets.clear()


def _build_galaxy_as_player():
    App.g_kSetManager._sets.clear()
    ship = loadspacehelper.CreateShip("Galaxy", None, "player", None, 0, 0)
    assert ship is not None
    # The panel resolves the player via Game_GetCurrentGame().GetPlayer();
    # establish a minimal Game so the snapshot sees the ship.
    game = Game()
    game.SetPlayer(ship)
    _set_current_game(game)
    return ship


def test_panel_name_is_weapons():
    panel = WeaponsDisplayPanel()
    assert panel.name == "weapons"


def test_panel_visible_by_default():
    panel = WeaponsDisplayPanel()
    assert panel.visible is True


def test_snapshot_empty_when_no_player():
    """Before a mission loads there is no player ship — the snapshot
    should collapse to the empty/invisible state so the CEF panel
    stays hidden rather than rendering an empty silhouette."""
    panel = WeaponsDisplayPanel()
    # No game / no player resolves to the empty snapshot.
    assert panel._snapshot()[0] is False  # visible flag


def test_snapshot_includes_silhouette_and_icons_for_galaxy():
    ship = _build_galaxy_as_player()
    panel = WeaponsDisplayPanel()
    snap = panel._snapshot()
    visible = snap[0]
    assert visible is True
    payload_json = panel.render_payload()
    assert payload_json is not None
    assert payload_json.startswith("setWeaponsDisplay(")
    body = payload_json[len("setWeaponsDisplay("):-2]
    data = json.loads(body)
    assert data["visible"] is True
    assert data["silhouette_url"] is not None
    icons = data["weapon_icons"]
    # Galaxy has 4 dorsal + 4 ventral phaser banks plus 6 torpedo tubes.
    # Tractor beams set icon_num=0 and must be skipped (SDK's
    # CreateEnergyWeaponPanes never iterates GetTractorBeamSystem).
    assert len(icons) >= 8


def test_descriptors_contain_galaxy_ventral_phaser():
    """galaxy.py VentralPhaser3 sets SetIconNum(350), SetIconAboveShip(0),
    SetIndicatorIconNum(506). The descriptor list must surface that
    mount with the SDK's raw pixel coords (the CSS layer drops them
    straight into left/top against a fixed-size pane that mirrors
    the SDK's WEAPONS_PANE)."""
    ship = _build_galaxy_as_player()
    descriptors = _resolve_icon_descriptors(ship)
    venp3 = next((d for d in descriptors if d["icon_num"] == 350), None)
    assert venp3 is not None
    assert venp3["above"] is False
    assert venp3["x_px"] == 78.0
    assert venp3["y_px"] == 42.0


def test_dorsal_phasers_marked_above_ship():
    ship = _build_galaxy_as_player()
    descriptors = _resolve_icon_descriptors(ship)
    dorsal = [d for d in descriptors if d["above"] is True]
    assert len(dorsal) >= 4


def test_torpedo_tubes_never_in_firing_arc():
    """The in-arc indicator (white stroke) only makes sense for
    arc-gated energy weapons. Torpedo tubes have no canonical arc
    gate in BC — they should never report in_firing_arc=True so the
    panel doesn't render a stroke on the torpedo glyph."""
    ship = _build_galaxy_as_player()
    descriptors = _resolve_icon_descriptors(ship)
    torpedoes = [d for d in descriptors if d["icon_num"] == 370]
    assert torpedoes
    for tube in torpedoes:
        assert tube["in_firing_arc"] is False


def test_icon_num_zero_mounts_skipped():
    """Tractor beams and GenericTemplate emitters call SetIconNum(0)
    explicitly — the "no icon" sentinel. They must not produce a
    descriptor."""
    ship = _build_galaxy_as_player()
    descriptors = _resolve_icon_descriptors(ship)
    assert all(d["icon_num"] != 0 for d in descriptors)


def test_descriptor_carries_firing_state():
    ship = _build_galaxy_as_player()
    bank = ship.GetPhaserSystem()._children[0]
    bank._firing = True
    descriptors = _resolve_icon_descriptors(ship)
    matching = next(
        (d for d in descriptors
         if d["icon_num"] == bank.GetIconNum()
         and d["x_px"] == bank.GetIconPositionX()),
        None,
    )
    assert matching is not None
    assert matching["firing"] is True


def test_descriptor_carries_destroyed_state():
    ship = _build_galaxy_as_player()
    bank = ship.GetPhaserSystem()._children[0]
    bank.SetDestroyed(1)
    descriptors = _resolve_icon_descriptors(ship)
    matching = next(
        (d for d in descriptors
         if d["icon_num"] == bank.GetIconNum()
         and d["x_px"] == bank.GetIconPositionX()),
        None,
    )
    assert matching is not None
    assert matching["destroyed"] is True


def test_render_payload_idempotent_when_state_unchanged():
    _build_galaxy_as_player()
    panel = WeaponsDisplayPanel()
    first = panel.render_payload()
    assert first is not None
    second = panel.render_payload()
    assert second is None


def test_render_payload_re_emits_after_firing_flag_flips():
    ship = _build_galaxy_as_player()
    panel = WeaponsDisplayPanel()
    panel.render_payload()  # prime the cache
    bank = ship.GetPhaserSystem()._children[0]
    bank._firing = True
    again = panel.render_payload()
    assert again is not None


def test_invalidate_drops_snapshot_cache():
    _build_galaxy_as_player()
    panel = WeaponsDisplayPanel()
    panel.render_payload()
    panel.invalidate()
    again = panel.render_payload()
    assert again is not None


def test_dispatch_event_returns_false():
    """No interactive elements on this panel — every event is ignored."""
    panel = WeaponsDisplayPanel()
    assert panel.dispatch_event("anything") is False


def test_resolve_icon_descriptors_on_none_returns_empty():
    assert _resolve_icon_descriptors(None) == ()


# ── In-firing-arc indicator ─────────────────────────────────────────────


class _StubTarget:
    """Bare-minimum target object — the in-arc check only consults
    GetWorldLocation. Avoids spinning up a second loadspacehelper
    ship just to position a point in space."""
    def __init__(self, x, y, z):
        from engine.appc.math import TGPoint3
        self._pos = TGPoint3(x, y, z)

    def GetWorldLocation(self):
        from engine.appc.math import TGPoint3
        return TGPoint3(self._pos.x, self._pos.y, self._pos.z)


def test_in_firing_arc_false_without_target():
    """No selected target → no firing solution; every phaser bank
    reports False so the panel doesn't draw any stroke."""
    ship = _build_galaxy_as_player()
    descriptors = _resolve_icon_descriptors(ship)
    phasers = [d for d in descriptors if 330 <= d["icon_num"] <= 366]
    assert phasers
    for d in phasers:
        assert d["in_firing_arc"] is False


def test_in_firing_arc_true_when_target_directly_ahead():
    """Galaxy facing forward with a target 100 GU dead ahead: every
    forward-facing phaser bank (dorsal + ventral) should report
    in_firing_arc=True. Player's body +Y is forward, so target at
    (0, 100, 0) lies along the firing direction of the forward arcs."""
    ship = _build_galaxy_as_player()
    ship.SetTarget(_StubTarget(0.0, 100.0, 0.0))
    descriptors = _resolve_icon_descriptors(ship)
    forward_phasers = [d for d in descriptors
                       if 330 <= d["icon_num"] <= 366
                       and d["in_firing_arc"]]
    # Galaxy has 4 forward arcs (2 dorsal + 2 ventral) that wrap the
    # saucer's forward edge; expect at least those four to engage.
    assert len(forward_phasers) >= 4


def test_in_firing_arc_false_when_target_out_of_phaser_range():
    """Target beyond PHASER_MAX_RANGE_GU (700) drops every bank out
    of the firing solution even if the arc would otherwise allow."""
    from engine.appc.subsystems import PHASER_MAX_RANGE_GU
    ship = _build_galaxy_as_player()
    ship.SetTarget(_StubTarget(0.0, PHASER_MAX_RANGE_GU + 50.0, 0.0))
    descriptors = _resolve_icon_descriptors(ship)
    phasers = [d for d in descriptors if 330 <= d["icon_num"] <= 366]
    for d in phasers:
        assert d["in_firing_arc"] is False


def test_in_firing_arc_independent_of_charge_and_firing_state():
    """The user's request: the in-arc indicator must light up based
    on geometry alone, regardless of whether the bank has any charge
    or is currently firing."""
    ship = _build_galaxy_as_player()
    ship.SetTarget(_StubTarget(0.0, 100.0, 0.0))
    # Drain every phaser bank fully and turn the system OFF — none
    # of these flips should affect in_firing_arc.
    for bank in ship.GetPhaserSystem()._children:
        bank._charge_level = 0.0
        bank._firing = False
    descriptors = _resolve_icon_descriptors(ship)
    forward_phasers = [d for d in descriptors
                       if 330 <= d["icon_num"] <= 366
                       and d["in_firing_arc"]]
    assert forward_phasers, (
        "in-arc indicator must light up purely on geometry — charge "
        "and firing state should not gate it"
    )


# ── Power state + charge colouring ──────────────────────────────────────

def test_descriptor_offline_when_parent_system_off():
    """Default Galaxy build leaves the PhaserSystem powered off (BC's
    SDK only turns weapons on at red alert). Every phaser descriptor
    should report online=False and charge_ratio=0 so the panel
    renders at the offline grey."""
    ship = _build_galaxy_as_player()
    descriptors = _resolve_icon_descriptors(ship)
    phaser_icons = [d for d in descriptors if 330 <= d["icon_num"] <= 366]
    assert phaser_icons
    for d in phaser_icons:
        assert d["online"] is False
        assert d["charge_ratio"] == 0.0


def test_descriptor_online_with_full_charge_when_powered_on():
    """Once the PhaserSystem is turned on and each bank's charge is
    seeded to max, the descriptors should report online=True and
    charge_ratio=1.0 so the icon lights up at the BC fill colour."""
    ship = _build_galaxy_as_player()
    phasers = ship.GetPhaserSystem()
    phasers.TurnOn()
    for bank in phasers._children:
        bank._charge_level = bank._max_charge
    descriptors = _resolve_icon_descriptors(ship)
    phaser_icons = [d for d in descriptors if 330 <= d["icon_num"] <= 366]
    assert phaser_icons
    for d in phaser_icons:
        assert d["online"] is True
        assert d["charge_ratio"] == 1.0


def test_descriptor_partial_charge_reflects_bank_state():
    """Charge interpolation hinges on GetChargePercentage(); the
    descriptor should mirror it directly so the panel can lerp the
    icon colour between empty and full."""
    ship = _build_galaxy_as_player()
    phasers = ship.GetPhaserSystem()
    phasers.TurnOn()
    bank = phasers._children[0]
    bank._charge_level = bank._max_charge * 0.5
    descriptors = _resolve_icon_descriptors(ship)
    matching = next(
        (d for d in descriptors
         if d["icon_num"] == bank.GetIconNum()
         and d["x_px"] == bank.GetIconPositionX()),
        None,
    )
    assert matching is not None
    assert matching["online"] is True
    assert matching["charge_ratio"] == 0.5


def test_destroyed_mount_is_offline_regardless_of_parent_power():
    """A destroyed bank can't be online no matter what — the icon
    needs the offline colour underneath the destroyed dim filter."""
    ship = _build_galaxy_as_player()
    phasers = ship.GetPhaserSystem()
    phasers.TurnOn()
    bank = phasers._children[0]
    bank._charge_level = bank._max_charge
    bank.SetDestroyed(1)
    descriptors = _resolve_icon_descriptors(ship)
    matching = next(
        (d for d in descriptors
         if d["icon_num"] == bank.GetIconNum()
         and d["x_px"] == bank.GetIconPositionX()),
        None,
    )
    assert matching is not None
    assert matching["online"] is False


def test_torpedo_tubes_online_with_loaded_round_at_full_ratio():
    """A loaded torpedo tube reads at the BC fill colour. Galaxy's
    tubes are max_ready=1; seeding num_ready to that capacity should
    flip charge_ratio to 1.0."""
    ship = _build_galaxy_as_player()
    torps = ship.GetTorpedoSystem()
    torps.TurnOn()
    for tube in torps._children:
        tube.SetNumReady(tube.GetMaxReady())
    descriptors = _resolve_icon_descriptors(ship)
    torp_icons = [d for d in descriptors if d["icon_num"] == 370]
    assert torp_icons
    for d in torp_icons:
        assert d["online"] is True
        assert d["charge_ratio"] == 1.0


def test_torpedo_tube_drops_to_empty_immediately_after_firing():
    """The moment a tube fires (num_ready → 0) the descriptor reads
    at 0.3 — the palette's red stop (g_kSubsystemEmptyColor). Not
    0.0, which is reserved for the energy-weapon "fully discharged
    → black" state. BC's tubes go red (empty) → green (loaded) and
    never display the black/dark-red bottom of the energy palette."""
    ship = _build_galaxy_as_player()
    torps = ship.GetTorpedoSystem()
    torps.TurnOn()
    tube = torps._children[0]
    tube.SetNumReady(0)
    descriptors = _resolve_icon_descriptors(ship)
    matching = next(
        (d for d in descriptors
         if d["icon_num"] == tube.GetIconNum()
         and d["x_px"] == tube.GetIconPositionX()),
        None,
    )
    assert matching is not None
    assert matching["online"] is True
    assert matching["charge_ratio"] == 0.3


def test_torpedo_tube_with_loaded_round_reads_full_ratio():
    """num_ready > 0 → ready → 1.0 → BC full green. There's no
    canonical "mid-reload" state on a tube; the colour is binary."""
    ship = _build_galaxy_as_player()
    torps = ship.GetTorpedoSystem()
    torps.TurnOn()
    tube = torps._children[0]
    tube.SetNumReady(tube.GetMaxReady())
    descriptors = _resolve_icon_descriptors(ship)
    matching = next(
        (d for d in descriptors
         if d["icon_num"] == tube.GetIconNum()
         and d["x_px"] == tube.GetIconPositionX()),
        None,
    )
    assert matching is not None
    assert matching["charge_ratio"] == 1.0


def test_charge_bucket_change_invalidates_snapshot():
    """Snapshot equality quantises charge to 10% buckets — a sub-
    bucket change shouldn't fire, but crossing a bucket should."""
    ship = _build_galaxy_as_player()
    phasers = ship.GetPhaserSystem()
    phasers.TurnOn()
    for bank in phasers._children:
        bank._charge_level = bank._max_charge * 0.5  # bucket = 5
    panel = WeaponsDisplayPanel()
    panel.render_payload()
    # Sub-bucket nudge — stays in bucket 5.
    for bank in phasers._children:
        bank._charge_level = bank._max_charge * 0.54
    assert panel.render_payload() is None, (
        "0.50 → 0.54 stays in the 10% bucket; snapshot must not re-emit"
    )
    # Cross-bucket — bucket 6 vs 5.
    for bank in phasers._children:
        bank._charge_level = bank._max_charge * 0.62
    assert panel.render_payload() is not None, (
        "0.54 → 0.62 crosses a bucket; snapshot must re-emit"
    )


# ── Speed label (BC's helm-tooltip format) ───────────────────────────────

def test_speed_label_default_is_zero_zero():
    """No player_control and no ship velocity → 'Speed 0 : 0 kph'."""
    assert _speed_label_for(None, None) == "Speed 0 : 0 kph"


def test_speed_label_full_impulse_galaxy_max_speed_in_kph():
    """Galaxy's MaxSpeed is 6.3 GU/s = 3969 kph (CLAUDE.md derivation).
    At full impulse (level 9) the label should match
    BC's helm-tooltip readout."""
    pc = _FakePlayerControl(impulse_level=9, current_speed_gups=6.3)
    # GUPS_TO_KPH = 175 m × 3.6 = 630.
    assert _speed_label_for(None, pc) == "Speed 9 : 3969 kph"


def test_speed_label_uses_player_control_over_ship_velocity():
    """When _PlayerControl is wired, the label reads off it (commanded
    throttle + integrated speed) regardless of the ship's instantaneous
    velocity, so the throttle notch responds the instant the user
    bumps it even before the integrator catches up."""
    pc = _FakePlayerControl(impulse_level=5, current_speed_gups=3.5)
    assert _speed_label_for(None, pc) == "Speed 5 : 2205 kph"


def test_speed_label_shows_R_when_reversing():
    """impulse_level is signed (-2..9). Reverse (any negative level) shows
    'R' for the throttle notch, followed by the ship's current speed."""
    pc = _FakePlayerControl(impulse_level=-2, current_speed_gups=0.5)
    label = _speed_label_for(None, pc)
    assert label.startswith("Speed R :")
    assert label.endswith(" kph")


def test_render_payload_carries_speed_label():
    """The JS panel consumes state.speed_label as the header text."""
    _build_galaxy_as_player()
    pc = _FakePlayerControl(impulse_level=3, current_speed_gups=2.1)
    panel = WeaponsDisplayPanel(player_control=pc)
    payload_json = panel.render_payload()
    assert payload_json is not None
    body = payload_json[len("setWeaponsDisplay("):-2]
    data = json.loads(body)
    # 2.1 GU/s × 630 = 1323 kph.
    assert data["speed_label"] == "Speed 3 : 1323 kph"


def test_speed_label_change_triggers_re_emit():
    """Snapshot equality must pick up speed_label flips so the header
    text updates on every throttle change."""
    _build_galaxy_as_player()
    pc = _FakePlayerControl(impulse_level=0, current_speed_gups=0.0)
    panel = WeaponsDisplayPanel(player_control=pc)
    panel.render_payload()  # prime cache
    pc.impulse_level = 5
    pc._current_speed = 3.5
    again = panel.render_payload()
    assert again is not None
